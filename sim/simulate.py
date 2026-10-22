"""Replay a realistic CI history against the flaky test detector and check every verdict.

Builds a throwaway git repository from this project. Then, for each simulated CI run:

1. Even runs are pull requests: they commit a change. Usually it's an unrelated docs edit;
   at a few scripted points it's a real change (a lock removed or added, a bug introduced or
   fixed, a data file edited, a test renamed). Odd runs are the merge of that PR to main.
2. Like a CI matrix, the suite runs once per environment (timezone UTC and PST), each with its
   own ``CHAOS_SEED``, so every job gets different faults. Failures are retried once with
   another seed, as the CI workflow does.
3. ``flaky-detector ingest`` records each job with the matching GitHub event and environment.

Finally the whole history is analysed and each verdict is compared with the ground truth in
``EXPECTED``. Exits 1 if any test is misclassified.

    python sim/simulate.py --out sim-output [--runs 30] [--summary-file "$GITHUB_STEP_SUMMARY"]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flaky_detector.analysis import FAILING, FIXED, FLAKY, HEALTHY, analyze
from flaky_detector.store import load_runs

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
RUNS = 30
ENVIRONMENTS = {"utc": "UTC", "pst": "PST"}  # matrix environment -> LAB_TZ
# lab/data/rates.json isn't Python, so coverage can't see that tests read it.
FINGERPRINT_EXTRA = ["lab/node.py", "lab/data/*.json"]

LOCK_REMOVED = 10
BANK_LOCK_ADDED = 12
DISCOUNT_BROKEN = 14
RATES_CHANGED = 16
TEST_RENAMED = 18
DISCOUNT_FIXED = 20
SEPARATOR_DROPPED = 24


@dataclass
class Change:
    message: str
    edits: list[tuple[str, str, str]]  # (path, old, new)


DISCOUNT_OK = "return round(price * (1 - percent / 100), 2)"
DISCOUNT_BUG = "return round(price * (1 - percent / 100) ** 2, 2)  # PRICE-88: stacked promotions"
DEPOSIT_RACY = """\
        current = self.balance
        if PREEMPTED:
            time.sleep(0.0005)  # another thread deposits here, and its update is lost
        self.balance = current + amount
"""
DEPOSIT_LOCKED = """\
        with self._lock:
            current = self.balance
            if PREEMPTED:
                time.sleep(0.0005)
            self.balance = current + amount
"""

CHANGES = {
    LOCK_REMOVED: Change("Drop inventory lock to cut contention under load", [
        ("lab/inventory.py", "import threading\n", "import threading\nfrom contextlib import nullcontext\n"),
        ("lab/inventory.py", "        with self._lock:\n", "        with nullcontext():  # PERF-212: lock was a bottleneck\n"),
    ]),
    BANK_LOCK_ADDED: Change("Lock account deposits", [
        ("lab/bank.py", "import time\n", "import threading\nimport time\n"),
        ("lab/bank.py", "        self.balance = balance\n", "        self.balance = balance\n        self._lock = threading.Lock()\n"),
        ("lab/bank.py", DEPOSIT_RACY, DEPOSIT_LOCKED),
    ]),
    DISCOUNT_BROKEN: Change("Support stacked promotions", [("lab/pricing.py", DISCOUNT_OK, DISCOUNT_BUG)]),
    RATES_CHANGED: Change("Refresh FX rates", [("lab/data/rates.json", '"EUR": 0.92', '"EUR": 0.95')]),
    TEST_RENAMED: Change("Rename word count test", [("tests/test_text.py", "def test_word_count", "def test_count_words")]),
    DISCOUNT_FIXED: Change("Fix double-applied discount", [("lab/pricing.py", DISCOUNT_BUG, DISCOUNT_OK)]),
    SEPARATOR_DROPPED: Change("Simplify price formatting", [("lab/currency.py", "{amount:,.2f}", "{amount:.2f}")]),
}


@dataclass
class Expect:
    status: str
    kind: str
    introduced: int | None = None  # run where the flaky code first appeared
    failing_since: int | None = None
    fixed_in: int | None = None
    failed_then_fixed: bool = False
    severity_in: tuple[str, ...] | None = None


# Keys without an environment apply to every environment; "key [env]" entries override.
EXPECTED = {
    "tests.test_bank.test_concurrent_deposits_are_not_lost":
        Expect(FIXED, "race condition, fixed by adding a lock", fixed_in=BANK_LOCK_ADDED),
    "tests.test_inventory.test_concurrent_reservations_never_oversell":
        Expect(FLAKY, "race condition introduced by a code change", introduced=LOCK_REMOVED),
    "tests.test_quotes.test_fetch_quote": Expect(FLAKY, "connection delay: client timeout"),
    "tests.test_service.test_call_right_after_start": Expect(FLAKY, "startup race: connection refused"),
    "tests.test_cluster.test_map_across_nodes": Expect(FLAKY, "hardware: worker node crash"),
    "tests.test_storage.test_write_and_read_back": Expect(FLAKY, "hardware: disk bad sector (EIO)"),
    "tests.test_events.test_replies_in_request_order": Expect(FLAKY, "async ordering assumption"),
    "tests.test_stats.test_mean_of_high_readings": Expect(FLAKY, "random test data edge case"),
    "tests.test_timing.test_batch_within_latency_budget": Expect(FLAKY, "timing: stalled runner"),
    "tests.test_settings.test_default_currency": Expect(FLAKY, "order dependence: leaked global state"),
    "tests.test_ids.test_ids_are_unique":
        Expect(FLAKY, "rare (~3%): clock steps backwards", severity_in=("low", "medium")),
    "tests.test_settings.test_configure_currency": Expect(HEALTHY, "pollutes state but always passes"),
    "tests.test_pricing.test_discount":
        Expect(HEALTHY, "real regression, later fixed", failed_then_fixed=True),
    "tests.test_pricing.test_no_discount": Expect(HEALTHY, "same file as a regression, unaffected"),
    "tests.test_currency.test_thousands_separator":
        Expect(FAILING, "real regression, still broken", failing_since=SEPARATOR_DROPPED),
    "tests.test_currency.test_euro_symbol": Expect(HEALTHY, "its code changed, still passes"),
    "tests.test_rates.test_convert_to_euros":
        Expect(FAILING, "regression in a data file coverage can't see", failing_since=RATES_CHANGED),
    "tests.test_reports.test_report_date_early_morning [utc]": Expect(HEALTHY, "environment-specific: fine in UTC"),
    "tests.test_reports.test_report_date_early_morning [pst]":
        Expect(FAILING, "environment-specific: always fails in PST", failing_since=0),
    "tests.test_inventory.test_reserve_more_than_available": Expect(HEALTHY, "single-threaded, deterministic"),
    "tests.test_text.test_word_count": Expect(HEALTHY, "renamed in run 18: old name"),
    "tests.test_text.test_count_words": Expect(HEALTHY, "renamed in run 18: new name"),
    "tests.test_text.test_slugify": Expect(HEALTHY, "control"),
    "tests.test_text.test_truncate": Expect(HEALTHY, "control"),
}

IGNORE = shutil.ignore_patterns(".git", ".venv", "sim-output", "__pycache__", ".pytest_cache", "*.egg-info",
                                ".coverage*", "coverage.json", ".flaky")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=ROOT / "sim-output")
    parser.add_argument("--runs", type=int, default=RUNS)
    parser.add_argument("--summary-file", type=Path, help="append the results here, e.g. $GITHUB_STEP_SUMMARY")
    args = parser.parse_args(argv)

    out = args.out.resolve()
    shutil.rmtree(out, ignore_errors=True)
    store = out / "history" / "runs"
    with tempfile.TemporaryDirectory(prefix="flaky-lab-") as tmp:
        repo = Path(tmp) / "lab"
        shutil.copytree(ROOT, repo, ignore=IGNORE)
        git(repo, "init", "-q", "-b", "main")
        commit(repo, "Initial import")
        for n in range(args.runs):
            simulate_run(repo, n, store, Path(tmp))

    runs = load_runs(store)
    verdicts = analyze(runs)
    subprocess.run([sys.executable, "-m", "flaky_detector", "analyze", "--store", str(store),
                    "--out", str(out / "report")], check=True)
    validation, ok = render_validation(runs, verdicts)
    (out / "validation.md").write_text(validation, encoding="utf-8")
    print("\n" + validation)
    if args.summary_file:
        with args.summary_file.open("a", encoding="utf-8") as handle:
            handle.write(validation + "\n\n")
            handle.write((out / "report" / "summary.md").read_text(encoding="utf-8"))
    return 0 if ok else 1


def simulate_run(repo: Path, n: int, store: Path, tmp: Path) -> None:
    pr = 100 + n // 2
    previous = git(repo, "rev-parse", "HEAD")
    if n % 2 == 0:
        change = CHANGES.get(n)
        if change:
            for path, old, new in change.edits:
                target = repo / path
                text = target.read_text(encoding="utf-8")
                assert old in text, f"run {n}: {old!r} not in {path}"
                target.write_text(text.replace(old, new, 1), encoding="utf-8")
            message = f"{change.message} (#{pr})"
        else:
            with (repo / "CHANGELOG.md").open("a", encoding="utf-8") as log:
                log.write(f"- Docs and housekeeping for #{pr}\n")
            message = f"Update changelog (#{pr})"
        commit(repo, message)
        event_name, ref = "pull_request", f"refs/pull/{pr}/merge"
        payload = {"pull_request": {"number": pr, "base": {"sha": previous},
                                    "head": {"sha": git(repo, "rev-parse", "HEAD"), "ref": f"feature/{pr}"}}}
    else:
        message = f"Merge pull request #{pr} from lab/feature/{pr}"
        commit(repo, message, allow_empty=True)
        event_name, ref = "push", "refs/heads/main"
        payload = {"before": previous, "head_commit": {"message": message}}

    summary = []
    for environment, tz in ENVIRONMENTS.items():
        results = tmp / f"run-{n:02d}-{environment}"
        results.mkdir()
        junit, retry, coverage = results / "junit.xml", results / "retry.xml", results / "coverage.json"
        seed = f"sim-{n}-{environment}"
        tests = pytest(repo, seed, tz, "--junitxml", str(junit), "--cov", "--cov-context=test",
                       f"--cov-report=json:{coverage}")
        retried = tests.returncode == 1
        if retried:
            pytest(repo, f"{seed}-retry", tz, "--last-failed", "--no-cov", "--junitxml", str(retry))

        event = results / "event.json"
        event.write_text(json.dumps(payload), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
        env.update(GITHUB_EVENT_NAME=event_name, GITHUB_REF=ref, GITHUB_RUN_ID=f"sim-{n:02d}",
                   GITHUB_RUN_ATTEMPT="1", GITHUB_EVENT_PATH=str(event), GITHUB_REPOSITORY="lab/simulation",
                   GITHUB_WORKFLOW="simulation")
        command = [sys.executable, "-m", "flaky_detector", "ingest", "--junit", str(junit),
                   "--coverage", str(coverage), "--store", str(store), "--root", str(repo),
                   "--environment", environment,
                   "--timestamp", (START + timedelta(hours=3 * n)).isoformat(),
                   "--fingerprint-extra", *FINGERPRINT_EXTRA]
        if retried:
            command += ["--rerun", str(retry)]
        saved = subprocess.run(command, check=True, env=env, capture_output=True, text=True).stdout.strip()

        record = json.loads(Path(saved).read_text(encoding="utf-8"))
        failed = [k for k, t in record["tests"].items() if t["attempts"][0] in ("failed", "error")]
        still = [k for k in failed if record["tests"][k]["attempts"][-1] in ("failed", "error")]
        summary.append(f"{environment}: {len(failed)} failed, {len(still)} after retry")

    where = f"PR #{pr}" if event_name == "pull_request" else f"main (merge #{pr})"
    print(f"run {n:2d}  {where:<18} {' · '.join(summary):<50} {message if n % 2 == 0 else ''}", flush=True)


def pytest(repo: Path, seed: str, tz: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CHAOS_SEED": seed, "LAB_TZ": tz}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", *args], cwd=repo, env=env,
                          capture_output=True, text=True)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, message: str, allow_empty: bool = False) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Lab Simulator", "-c", "user.email=lab@example.com", "-c", "commit.gpgsign=false",
        "commit", "-q", *(["--allow-empty"] if allow_empty else []), "-m", message)


def run_number(ref: dict | None) -> int | None:
    """Simulated run number of a run reference (run ids are ``sim-NN``)."""
    return int(ref["run_id"].removeprefix("sim-")) if ref else None


def check(expect: Expect, verdict) -> tuple[bool, str]:
    if verdict is None:
        return False, "never ran"
    if expect.fixed_in is not None and verdict.status == FLAKY and verdict.possibly_fixed_in:
        # The fix may not have had enough clean runs yet to rule out the old failure rate.
        since = run_number(verdict.possibly_fixed_in)
        if since != expect.fixed_in:
            return False, f"possibly fixed in run {since}, expected {expect.fixed_in}"
        return True, (f"fix pending since run {since}: {verdict.passes_since_fix} of the "
                      f"{verdict.passes_needed} clean passes needed at its {verdict.failure_rate:.0%} fail rate")
    if verdict.status != expect.status:
        return False, f"detected {verdict.status}"
    if expect.severity_in and verdict.severity not in expect.severity_in:
        return False, f"severity {verdict.severity}, expected {' or '.join(expect.severity_in)}"
    if expect.introduced is not None:
        introduced, previous = run_number(verdict.introduced_in), run_number(verdict.previous_code_seen_in)
        if (introduced, previous) != (expect.introduced, expect.introduced - 1):
            return False, f"onset run {introduced}, expected {expect.introduced}"
        return True, f"flaky code since run {introduced}; previous code last ran in run {previous}"
    if expect.failing_since is not None:
        since = run_number(verdict.failing_since)
        if since != expect.failing_since:
            return False, f"failing since run {since}, expected {expect.failing_since}"
        return True, f"failing since run {since}"
    if expect.fixed_in is not None:
        fixed = run_number(verdict.fixed_in)
        if fixed != expect.fixed_in:
            return False, f"fixed in run {fixed}, expected {expect.fixed_in}"
        return True, (f"failed {verdict.flaky_failures}/{verdict.flaky_observations} before; fixed in run "
                      f"{fixed}, {verdict.passes_since_fix} passes since")
    if expect.failed_then_fixed:
        if not verdict.failures:
            return False, "never failed"
        return True, f"failed {verdict.failures} times on broken code, passes since the fix"
    if verdict.status == FLAKY:
        return True, f"{verdict.flaky_failures}/{verdict.flaky_observations} executions failed"
    return True, ""


def cases() -> list[tuple[str, Expect, list[str]]]:
    """Each expectation with the verdict keys it covers (one per environment it applies to)."""
    out = []
    for key, expect in EXPECTED.items():
        if " [" in key:
            out.append((key, expect, [key]))
        else:
            envs = [env for env in ENVIRONMENTS if f"{key} [{env}]" not in EXPECTED]
            out.append((key, expect, [f"{key} [{env}]" for env in envs]))
    return out


def render_validation(runs: list[dict], verdicts: dict) -> tuple[str, bool]:
    rows, correct, total = [], 0, 0
    covered = set()
    for key, expect, verdict_keys in cases():
        results = [(vk, *check(expect, verdicts.get(vk))) for vk in verdict_keys]
        covered.update(verdict_keys)
        ok = all(r[1] for r in results)
        correct += sum(r[1] for r in results)
        total += len(results)
        detected = ", ".join(sorted({verdicts[vk].status if vk in verdicts else "missing" for vk in verdict_keys}))
        severities = ", ".join(sorted({verdicts[vk].severity for vk in verdict_keys
                                       if vk in verdicts and verdicts[vk].severity}))
        evidence = " · ".join(f"{vk.rsplit(' [', 1)[1][:-1]}: {msg}" if len(results) > 1 else msg
                              for vk, _, msg in results if msg)
        rows.append(f"| {'✅' if ok else '❌'} | `{key.removeprefix('tests.')}` | {expect.kind} | {expect.status} "
                    f"| {detected} | {severities} | {evidence} |")
    unexpected = sorted(set(verdicts) - covered)
    ok = correct == total and not unexpected
    pr_runs = len({r["run_id"] for r in runs if r["event"] == "pull_request"})
    run_count = len({r["run_id"] for r in runs})
    lines = [
        f"# Detector validation: {correct}/{total} verdicts correct {'✅' if ok else '❌'}",
        "",
        f"Replayed {run_count} CI runs ({pr_runs} pull request runs, {run_count - pr_runs} merges to main), each a "
        f"{len(ENVIRONMENTS)}-environment matrix ({', '.join(ENVIRONMENTS)}) with its own chaos seeds. Scripted "
        f"changes: inventory lock removed (run {LOCK_REMOVED}), bank lock added ({BANK_LOCK_ADDED}), discount "
        f"broken ({DISCOUNT_BROKEN}) and fixed ({DISCOUNT_FIXED}), FX rates data file edited ({RATES_CHANGED}), "
        f"a test renamed ({TEST_RENAMED}), thousands separator dropped ({SEPARATOR_DROPPED}). "
        "Every other PR only edits the changelog.",
        "",
        "| | Test | Case | Expected | Detected | Severity | Evidence |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *rows,
    ]
    if unexpected:
        lines += ["", "Verdicts missing from the ground truth: " + ", ".join(f"`{k}`" for k in unexpected)]
    lines += ["", "### Outcomes per run (utc environment)", "",
              "`.` passed · `x` failed · `r` failed, then passed on retry · blank: test didn't exist", "",
              "```", *timeline(runs), "```"]
    return "\n".join(lines), ok


def timeline(runs: list[dict], environment: str = "utc") -> list[str]:
    rows = [(key, environment) for key in EXPECTED if " [" not in key]
    rows += [(key.rsplit(" [", 1)[0], key.rsplit(" [", 1)[1][:-1]) for key in EXPECTED if " [" in key]
    labels = [key.removeprefix("tests.") + (f" [{env}]" if env != environment else "") for key, env in rows]
    width = max(map(len, labels))
    count = len({r["run_id"] for r in runs})
    ruler = "".join(str(n // 10) if n % 10 == 0 else " " for n in range(count))
    lines = [f"{'run':<{width}}  {ruler}", f"{'':<{width}}  {''.join(str(n % 10) for n in range(count))}"]
    for (key, env), label in zip(rows, labels):
        marks = []
        for run in (r for r in runs if r.get("environment") == env):
            attempts = run["tests"].get(key, {}).get("attempts", [])
            if not attempts:
                marks.append(" ")
            elif attempts[0] not in ("failed", "error"):
                marks.append(".")
            else:
                marks.append("r" if attempts[-1] == "passed" else "x")
        lines.append(f"{label:<{width}}  {''.join(marks)}")
    return lines


if __name__ == "__main__":
    sys.exit(main())
