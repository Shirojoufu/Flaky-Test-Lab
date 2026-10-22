"""Replay a realistic CI history against the flaky test detector and check every verdict.

Builds a throwaway git repository from this project. Then, for each simulated CI run:

1. Even runs are pull requests: they commit a change. Usually it's an unrelated docs edit;
   at a few scripted points it's a real code change (a lock removed, a bug introduced or fixed).
   Odd runs are the merge of that PR to main.
2. The suite runs with ``CHAOS_SEED=sim-<n>``, so each run gets different faults. Failures are
   retried once with a different seed, as the CI workflow does.
3. ``flaky-detector ingest`` records the run with the matching GitHub event.

Finally the whole history is analysed and each test's verdict is compared with the ground
truth in ``EXPECTED``. Exits 1 if any test is misclassified.

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

from flaky_detector.analysis import FAILING, FLAKY, HEALTHY, analyze
from flaky_detector.store import load_runs

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
RUNS = 30

LOCK_REMOVED = 10
DISCOUNT_BROKEN = 14
DISCOUNT_FIXED = 20
SEPARATOR_DROPPED = 24


@dataclass
class Change:
    message: str
    edits: list[tuple[str, str, str]]  # (path, old, new)


DISCOUNT_OK = "return round(price * (1 - percent / 100), 2)"
DISCOUNT_BUG = "return round(price * (1 - percent / 100) ** 2, 2)  # PRICE-88: stacked promotions"

CHANGES = {
    LOCK_REMOVED: Change("Drop inventory lock to cut contention under load", [
        ("lab/inventory.py", "import threading\n", "import threading\nfrom contextlib import nullcontext\n"),
        ("lab/inventory.py", "        with self._lock:\n", "        with nullcontext():  # PERF-212: lock was a bottleneck\n"),
    ]),
    DISCOUNT_BROKEN: Change("Support stacked promotions", [("lab/pricing.py", DISCOUNT_OK, DISCOUNT_BUG)]),
    DISCOUNT_FIXED: Change("Fix double-applied discount", [("lab/pricing.py", DISCOUNT_BUG, DISCOUNT_OK)]),
    SEPARATOR_DROPPED: Change("Simplify price formatting", [("lab/currency.py", "{amount:,.2f}", "{amount:.2f}")]),
}


@dataclass
class Expect:
    status: str
    kind: str
    introduced: int | None = None  # run where the flaky code first appeared
    failing_since: int | None = None
    failed_then_fixed: bool = False


EXPECTED = {
    "tests.test_bank.test_concurrent_deposits_are_not_lost": Expect(FLAKY, "race condition: lost update"),
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
    "tests.test_settings.test_configure_currency": Expect(HEALTHY, "pollutes state but always passes"),
    "tests.test_pricing.test_discount":
        Expect(HEALTHY, "real regression, later fixed", failed_then_fixed=True),
    "tests.test_pricing.test_no_discount": Expect(HEALTHY, "same file as a regression, unaffected"),
    "tests.test_currency.test_thousands_separator":
        Expect(FAILING, "real regression, still broken", failing_since=SEPARATOR_DROPPED),
    "tests.test_currency.test_euro_symbol": Expect(HEALTHY, "its code changed, still passes"),
    "tests.test_inventory.test_reserve_more_than_available": Expect(HEALTHY, "single-threaded, deterministic"),
    "tests.test_text.test_slugify": Expect(HEALTHY, "control"),
    "tests.test_text.test_truncate": Expect(HEALTHY, "control"),
    "tests.test_text.test_word_count": Expect(HEALTHY, "control"),
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

    results = tmp / f"run-{n:02d}"
    results.mkdir()
    junit, retry, coverage = results / "junit.xml", results / "retry.xml", results / "coverage.json"
    seed = f"sim-{n}"
    tests = pytest(repo, seed, "--junitxml", str(junit), "--cov", "--cov-context=test",
                   f"--cov-report=json:{coverage}")
    retried = tests.returncode == 1
    if retried:
        pytest(repo, f"{seed}-retry", "--last-failed", "--no-cov", "--junitxml", str(retry))

    event = results / "event.json"
    event.write_text(json.dumps(payload), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
    env.update(GITHUB_EVENT_NAME=event_name, GITHUB_REF=ref, GITHUB_RUN_ID=f"sim-{n:02d}",
               GITHUB_RUN_ATTEMPT="1", GITHUB_EVENT_PATH=str(event), GITHUB_REPOSITORY="lab/simulation",
               GITHUB_WORKFLOW="simulation")
    command = [sys.executable, "-m", "flaky_detector", "ingest", "--junit", str(junit), "--coverage", str(coverage),
               "--store", str(store), "--root", str(repo), "--timestamp", (START + timedelta(hours=3 * n)).isoformat(),
               "--fingerprint-extra", "lab/node.py"]
    if retried:
        command += ["--rerun", str(retry)]
    subprocess.run(command, check=True, env=env, capture_output=True)

    record = json.loads(sorted(store.glob(f"*-sim-{n:02d}-1.json"))[0].read_text(encoding="utf-8"))
    failed = sorted(k for k, t in record["tests"].items() if t["attempts"][0] in ("failed", "error"))
    still = [k for k in failed if record["tests"][k]["attempts"][-1] in ("failed", "error")]
    where = f"PR #{pr}" if event_name == "pull_request" else f"main (merge #{pr})"
    print(f"run {n:2d}  {where:<18} {len(failed)} failed, {len(still)} still failing after retry"
          f"   {message if n % 2 == 0 else ''}", flush=True)


def pytest(repo: Path, seed: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CHAOS_SEED": seed}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", *args], cwd=repo, env=env,
                          capture_output=True, text=True)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, message: str, allow_empty: bool = False) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Lab Simulator", "-c", "user.email=lab@example.com", "-c", "commit.gpgsign=false",
        "commit", "-q", *(["--allow-empty"] if allow_empty else []), "-m", message)


def check(key: str, expect: Expect, verdict) -> tuple[bool, str]:
    if verdict is None:
        return False, "never ran"
    if verdict.status != expect.status:
        return False, f"expected {expect.status}"
    if expect.introduced is not None:
        introduced = verdict.introduced_in["index"]
        previous = (verdict.previous_code_seen_in or {}).get("index")
        if (introduced, previous) != (expect.introduced, expect.introduced - 1):
            return False, f"onset run {introduced}, expected {expect.introduced}"
        return True, f"flaky code since run {introduced}; previous code last ran in run {previous}"
    if expect.failing_since is not None:
        since = verdict.failing_since["index"]
        if since != expect.failing_since:
            return False, f"failing since run {since}, expected {expect.failing_since}"
        return True, f"failing since run {since}"
    if expect.failed_then_fixed:
        if not verdict.failures:
            return False, "never failed"
        return True, f"failed {verdict.failures} times on broken code, passes since the fix"
    if verdict.status == FLAKY:
        return True, f"{verdict.flaky_failures}/{verdict.flaky_observations} executions failed, {verdict.flips} flips"
    return True, ""


def render_validation(runs: list[dict], verdicts: dict) -> tuple[str, bool]:
    rows, correct = [], 0
    unexpected = sorted(set(verdicts) - set(EXPECTED))
    for key, expect in EXPECTED.items():
        verdict = verdicts.get(key)
        ok, evidence = check(key, expect, verdict)
        correct += ok
        severity = verdict.severity if verdict and verdict.severity else ""
        detected = verdict.status if verdict else "missing"
        rows.append(f"| {'✅' if ok else '❌'} | `{key.removeprefix('tests.')}` | {expect.kind} | {expect.status} "
                    f"| {detected} | {severity} | {evidence} |")
    ok = correct == len(EXPECTED) and not unexpected
    pr_runs = sum(1 for r in runs if r["event"] == "pull_request")
    lines = [
        f"# Detector validation: {correct}/{len(EXPECTED)} tests classified correctly {'✅' if ok else '❌'}",
        "",
        f"Replayed {len(runs)} CI runs ({pr_runs} pull request runs, {len(runs) - pr_runs} merges to main), "
        "each with a different chaos seed. Code changes: inventory lock removed in run "
        f"{LOCK_REMOVED}, discount bug introduced in run {DISCOUNT_BROKEN} and fixed in run {DISCOUNT_FIXED}, "
        f"thousands separator dropped in run {SEPARATOR_DROPPED}. Every other PR only edits the changelog.",
        "",
        "| | Test | Failure type | Expected | Detected | Severity | Evidence |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *rows,
    ]
    if unexpected:
        lines += ["", "Tests missing from the ground truth: " + ", ".join(f"`{k}`" for k in unexpected)]
    lines += ["", "### Outcomes per run", "", "`.` passed · `x` failed · `r` failed, then passed on retry", "",
              "```", *timeline(runs), "```"]
    return "\n".join(lines), ok


def timeline(runs: list[dict]) -> list[str]:
    width = max(len(k.removeprefix("tests.")) for k in EXPECTED)
    ruler = "".join(str(n // 10) if n % 10 == 0 else " " for n in range(len(runs)))
    lines = [f"{'run':<{width}}  {ruler}", f"{'':<{width}}  {''.join(str(n % 10) for n in range(len(runs)))}"]
    for key in EXPECTED:
        marks = []
        for run in runs:
            attempts = run["tests"].get(key, {}).get("attempts", [])
            if not attempts or attempts[0] not in ("failed", "error"):
                marks.append(".")
            else:
                marks.append("r" if attempts[-1] == "passed" else "x")
        lines.append(f"{key.removeprefix('tests.'):<{width}}  {''.join(marks)}")
    return lines


if __name__ == "__main__":
    sys.exit(main())
