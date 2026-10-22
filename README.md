# Flaky Test Lab

A small codebase whose tests fail for every common flaky reason, plus a few real bugs. It also has a simulator that replays a CI history and checks that the [flaky test detector](https://github.com/Shirojoufu/Flaky-Tests) classifies every test correctly.

## The failure modes

Each flaky test has a hidden assumption that holds most of the time. [`lab/chaos.py`](lab/chaos.py) decides, per run, whether the conditions that break it occur. The failures themselves are real: real sockets time out, real worker processes die, real threads race.

| Test | Failure type | What actually goes wrong |
| --- | --- | --- |
| `test_bank` | race condition | threads preempted between read and write lose deposits |
| `test_inventory` | race condition, introduced by a code change | stable until a "performance" change removes the lock, then it oversells |
| `test_quotes` | connection delay | a congested upstream answers after the client's 250 ms socket timeout |
| `test_service` | startup race | a cold-started service isn't listening yet: connection refused |
| `test_cluster` | hardware: node crash | a worker node process is killed mid-job (`os._exit(137)`) and there is no failover |
| `test_storage` | hardware: disk failure | a bad sector returns `EIO` |
| `test_events` | async ordering | replies are assumed to arrive in request order |
| `test_stats` | random test data | sometimes no reading is high enough, and the mean divides by zero |
| `test_timing` | timing assertion | a stalled runner blows a 100 ms budget |
| `test_settings` | order dependence | one test leaks global state, and the other fails whenever it runs second. Test order is shuffled per run, as with pytest-randomly. |

There are also controls that must **not** be called flaky:

- **A real regression, later fixed** (`test_pricing.test_discount`).
- **A real regression that stays broken** (`test_currency.test_thousands_separator`).
- **A test whose code changes but still passes** (`test_currency.test_euro_symbol`).
- **The polluter in the order-dependence pair**, which always passes.
- **Plain deterministic tests.**

`CHAOS_SEED` picks the faults. The same seed replays the same faults, and with no seed set every run draws a fresh one:

```sh
CHAOS_SEED=demo pytest -v      # replay a specific run
pytest -v                      # a fresh, genuinely random run
```

## The simulator

[`sim/simulate.py`](sim/simulate.py) builds a throwaway git repo from this project and replays 30 CI runs, alternating between a pull request and its merge to `main`:

- Most PRs only edit `CHANGELOG.md`. Four of them make real code changes:
  - run 10 removes the inventory lock
  - run 14 breaks the discount
  - run 20 fixes the discount
  - run 24 breaks price formatting for good
- Each run uses a different chaos seed and retries its failures once with another seed, as CI does.
- Every run goes through `flaky-detector ingest`. The full history is then analysed, and each verdict is compared with the ground truth in `EXPECTED`. That includes *when* the inventory flake started and *when* the formatting regression began.

```sh
pip install -e ".[test]" "flaky-detector @ git+https://github.com/Shirojoufu/Flaky-Tests"
python sim/simulate.py --out sim-output
```

`sim-output/` then holds the run history, the detector's report and graph data, and `validation.md`. The **Validate the detector** workflow runs this on every push and fails if any test is misclassified.

### Results

From a local run (Windows, Python 3.15). CI results differ slightly from run to run, because the races are real:

| | Test | Failure type | Expected | Detected | Severity | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| ✅ | `test_bank.test_concurrent_deposits_are_not_lost` | race condition: lost update | flaky | flaky | critical | 12/39 executions failed, 18 flips |
| ✅ | `test_inventory.test_concurrent_reservations_never_oversell` | race condition introduced by a code change | flaky | flaky | critical | flaky code since run 10; previous code last ran in run 9 |
| ✅ | `test_quotes.test_fetch_quote` | connection delay: client timeout | flaky | flaky | critical | 11/39 executions failed, 16 flips |
| ✅ | `test_service.test_call_right_after_start` | startup race: connection refused | flaky | flaky | critical | 14/40 executions failed, 17 flips |
| ✅ | `test_cluster.test_map_across_nodes` | hardware: worker node crash | flaky | flaky | medium | 3/33 executions failed, 6 flips |
| ✅ | `test_storage.test_write_and_read_back` | hardware: disk bad sector (EIO) | flaky | flaky | critical | 4/34 executions failed, 8 flips |
| ✅ | `test_events.test_replies_in_request_order` | async ordering assumption | flaky | flaky | critical | 8/37 executions failed, 14 flips |
| ✅ | `test_stats.test_mean_of_high_readings` | random test data edge case | flaky | flaky | critical | 42/54 executions failed, 19 flips |
| ✅ | `test_timing.test_batch_within_latency_budget` | timing: stalled runner | flaky | flaky | high | 3/33 executions failed, 6 flips |
| ✅ | `test_settings.test_default_currency` | order dependence: leaked global state | flaky | flaky | critical | 17/47 executions failed, 33 flips |
| ✅ | `test_settings.test_configure_currency` | pollutes state but always passes | healthy | healthy |  |  |
| ✅ | `test_pricing.test_discount` | real regression, later fixed | healthy | healthy |  | failed 12 times on broken code, passes since the fix |
| ✅ | `test_pricing.test_no_discount` | same file as a regression, unaffected | healthy | healthy |  |  |
| ✅ | `test_currency.test_thousands_separator` | real regression, still broken | failing | failing |  | failing since run 24 |
| ✅ | `test_currency.test_euro_symbol` | its code changed, still passes | healthy | healthy |  |  |
| ✅ | `test_inventory.test_reserve_more_than_available` | single-threaded, deterministic | healthy | healthy |  |  |
| ✅ | `test_text.*` (3 tests) | control | healthy | healthy |  |  |

Outcomes per run (`.` passed, `x` failed, `r` failed then passed on retry):

```
run                                                         0         1         2
                                                            012345678901234567890123456789
test_bank.test_concurrent_deposits_are_not_lost             ..x.....rr.rr..x..rx.....r....
test_inventory.test_concurrent_reservations_never_oversell  ..........xr........x....rxr..
test_quotes.test_fetch_quote                                ..xr.....r..r..r..rx.r.r......
test_service.test_call_right_after_start                    r.....x..r...x..r....x.rr...xr
test_cluster.test_map_across_nodes                          ..................r.....r...r.
test_storage.test_write_and_read_back                       ........rr.....r.........r....
test_events.test_replies_in_request_order                   ...r...x.....r........rr.r..r.
test_stats.test_mean_of_high_readings                       rxxxr.xxxx..rxx.xx.rxrxxxxx.xr
test_timing.test_batch_within_latency_budget                ...............r............rr
test_settings.test_default_currency                         r..rr..r.rr..rrrrrr..r.r..rr.r
test_pricing.test_discount                                  ..............xxxxxx..........
test_currency.test_thousands_separator                      ........................xxxxxx
```

Note the two consistently failing stretches: `x` with no `r`, starting exactly where the code changed. The detector calls those real failures, not flakes, even though `test_stats` also fails every attempt in some runs. The difference is that `test_stats` also *passes* on the same code.

## CI

[`ci.yml`](.github/workflows/ci.yml) runs the suite with random faults on every PR, every push, and every three hours, and feeds the results to the detector's GitHub Action. Real flaky history builds up on the `flaky-data` branch, and each run's job summary shows the current report. Test failures don't fail this job, because this repo exists to be flaky.
