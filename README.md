# Flaky Test Lab

A small codebase whose tests fail for every common flaky reason, plus real bugs and tricky cases that must *not* be called flaky. A simulator replays a CI history and checks that the [flaky test detector](https://github.com/Shirojoufu/Flaky-Tests) gets every verdict right. The detector's own CI runs this simulator on every commit.

## The cases

Each flaky test has a hidden assumption that holds most of the time. [`lab/chaos.py`](lab/chaos.py) decides, per run, whether the conditions that break it occur. The failures themselves are real: real sockets time out, real worker processes die, real threads race.

**Flaky** (must be detected):

| Test | Failure type | What actually goes wrong |
| --- | --- | --- |
| `test_inventory` | race condition, introduced by a code change | stable until a "performance" change removes the lock, then it oversells; the detector must date the onset |
| `test_quotes` | connection delay | a congested upstream answers after the client's 250 ms socket timeout |
| `test_service` | startup race | a cold-started service isn't listening yet: connection refused |
| `test_cluster` | hardware: node crash | a worker node process is killed mid-job (`os._exit(137)`) and there is no failover |
| `test_storage` | hardware: disk failure | a bad sector returns `EIO` |
| `test_events` | async ordering | replies are assumed to arrive in request order |
| `test_stats` | random test data | sometimes no reading is high enough, and the mean divides by zero |
| `test_timing` | timing assertion | a stalled runner blows a 100 ms budget |
| `test_settings` | order dependence | one test leaks global state, and the other fails whenever it runs second; test order is shuffled per run, as with pytest-randomly |
| `test_ids` | rare (~3%) | the clock steps backwards and IDs collide; severity must stay low or medium |

**Adversarial** (look flaky, or are easy to get wrong):

| Test | Case | Correct verdict |
| --- | --- | --- |
| `test_bank` | a race that a later change fixes by adding a lock | **fixed**, dated to that change, once enough clean runs rule out the old failure rate; until then "possibly fixed" |
| `test_rates` | a regression in `lab/data/rates.json`, a file coverage can't see | **failing** since the edit. This only works because CI lists `lab/data/*.json` in `fingerprint-extra`; without it, the pass before the edit and the fail after it look like "same code" and the test would be wrongly called flaky. |
| `test_reports` | passes in UTC, always fails in PST, on identical code | in a CI matrix: **failing** in `[pst]`, healthy in `[utc]`, not flaky |
| `test_pricing.test_discount` | a real regression, later fixed | **healthy** (never flaky) |
| `test_currency.test_thousands_separator` | a real regression that stays broken | **failing**, dated to the breaking change |
| `test_currency.test_euro_symbol` | its code changes but it still passes | **healthy** |
| `test_text.test_word_count` | renamed mid-history | both names **healthy** |
| `test_settings.test_configure_currency` | the polluter in the order-dependence pair, always passes | **healthy** |

`CHAOS_SEED` picks the faults (the same seed replays the same faults), and `LAB_TZ` picks the timezone:

```sh
CHAOS_SEED=demo pytest -v      # replay a specific run
LAB_TZ=PST pytest -v           # the PST matrix leg
pytest -v                      # a fresh, genuinely random run
```

## The simulator

[`sim/simulate.py`](sim/simulate.py) builds a throwaway git repo from this project and replays 30 CI runs. The runs alternate between a pull request and its merge to `main`, and each one is a two-job matrix (UTC and PST):

- Most PRs only edit `CHANGELOG.md`. Seven make real changes:

  | Run | Change |
  | --- | --- |
  | 10 | inventory lock removed |
  | 12 | bank lock added |
  | 14 | discount broken |
  | 16 | FX rates data file edited |
  | 18 | a test renamed |
  | 20 | discount fixed |
  | 24 | price formatting broken for good |

- Every job uses its own chaos seed and retries its failures once with another seed, as CI does.
- Every job goes through `flaky-detector ingest --environment <utc|pst>`. The full history is then analysed, and each verdict is compared with the ground truth in `EXPECTED`. That includes onset, fix and failing-since dates, and severity for the rare flake.

```sh
pip install -e ".[test]" "flaky-detector @ git+https://github.com/Shirojoufu/Flaky-Tests"
python sim/simulate.py --out sim-output
```

`sim-output/` then holds the run history, the detector's report and graph data, and `validation.md`. Here the simulator runs on every push (**Validate the detector**). In [Flaky-Tests](https://github.com/Shirojoufu/Flaky-Tests) it runs against every detector commit. Either fails if any verdict is wrong.

### Results

From a local run. Seeds make it reproducible, and CI gives identical results:

| | Test | Case | Expected | Detected | Severity | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| ✅ | `test_bank.test_concurrent_deposits_are_not_lost` | race condition, fixed by adding a lock | fixed | fixed, flaky | medium | utc: failed 7/16 before; fixed in run 12, 18 passes since · pst: fix pending since run 12: 18 of the 20 clean passes needed at its 14% fail rate |
| ✅ | `test_inventory.test_concurrent_reservations_never_oversell` | race condition introduced by a code change | flaky | flaky | critical | utc and pst: flaky code since run 10; previous code last ran in run 9 |
| ✅ | `test_quotes.test_fetch_quote` | connection delay: client timeout | flaky | flaky | critical | utc: 11/40 executions failed · pst: 8/37 |
| ✅ | `test_service.test_call_right_after_start` | startup race: connection refused | flaky | flaky | critical | utc: 10/37 · pst: 9/36 |
| ✅ | `test_cluster.test_map_across_nodes` | hardware: worker node crash | flaky | flaky | high | utc: 3/16 · pst: 2/32 |
| ✅ | `test_storage.test_write_and_read_back` | hardware: disk bad sector (EIO) | flaky | flaky | high, medium | utc: 3/33 · pst: 2/32 |
| ✅ | `test_events.test_replies_in_request_order` | async ordering assumption | flaky | flaky | critical, high | utc: 10/38 · pst: 4/17 |
| ✅ | `test_stats.test_mean_of_high_readings` | random test data edge case | flaky | flaky | critical | utc: 40/54 · pst: 39/53 |
| ✅ | `test_timing.test_batch_within_latency_budget` | timing: stalled runner | flaky | flaky | high, medium | utc: 1/15 · pst: 2/32 |
| ✅ | `test_settings.test_default_currency` | order dependence: leaked global state | flaky | flaky | critical | utc: 22/52 · pst: 10/40 |
| ✅ | `test_ids.test_ids_are_unique` | rare (~3%): clock steps backwards | flaky | flaky | medium | utc: 2/32 · pst: 3/33 |
| ✅ | `test_rates.test_convert_to_euros` | regression in a data file coverage can't see | failing | failing |  | failing since run 16 |
| ✅ | `test_reports.test_report_date_early_morning [utc]` | environment-specific: fine in UTC | healthy | healthy |  |  |
| ✅ | `test_reports.test_report_date_early_morning [pst]` | environment-specific: always fails in PST | failing | failing |  | failing since run 0 |
| ✅ | `test_currency.test_thousands_separator` | real regression, still broken | failing | failing |  | failing since run 24 |
| ✅ | `test_pricing.test_discount` | real regression, later fixed | healthy | healthy |  | failed 12 times on broken code, passes since the fix |
| ✅ | 8 more controls | unaffected, renamed, polluter, deterministic | healthy | healthy |  |  |

**46/46 verdicts correct.** The `test_bank` row is worth a look. With the same fix in the same run, the utc copy had failed 7 of 16 times beforehand, so 18 clean runs were plenty to call it fixed. The pst copy had failed only 2 of 14 times. At that rate, 18 clean runs could still be luck, so it stays "possibly fixed" until it reaches 20.

Outcomes per run, utc job (`.` passed, `x` failed, `r` failed then passed on retry, blank: the test didn't exist yet or anymore):

```
run                                                         0         1         2
                                                            012345678901234567890123456789
test_bank.test_concurrent_deposits_are_not_lost             x.x..x.r......................
test_inventory.test_concurrent_reservations_never_oversell  ..........x..r.r....r..rx..xrx
test_quotes.test_fetch_quote                                ....r..rr..rr..x..rr..r...r...
test_service.test_call_right_after_start                    r..r......r..x....x.........rx
test_cluster.test_map_across_nodes                          ...................x.....r....
test_storage.test_write_and_read_back                       ........r..........r......r...
test_events.test_replies_in_request_order                   .r....r.........r...rrx..x.r..
test_stats.test_mean_of_high_readings                       rr..xx.xxxrr.xrrxr.xxxxxx.rxxx
test_timing.test_batch_within_latency_budget                .......................r......
test_settings.test_default_currency                         rrrrr.r.rr.rr.rrrrrrr..r..rrrr
test_ids.test_ids_are_unique                                ........r.................r...
test_pricing.test_discount                                  ..............xxxxxx..........
test_currency.test_thousands_separator                      ........................xxxxxx
test_rates.test_convert_to_euros                            ................xxxxxxxxxxxxxx
test_text.test_word_count                                   ..................
test_text.test_count_words                                                    ............
test_reports.test_report_date_early_morning [pst]           xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## What the lab doesn't cover

- **Realistic volume.** Fault rates here are 3–35% so 30 runs are enough. Real flakes are often rarer, and the detector needs at least one failure *and* one pass on the same code before it can say anything.
- **Other languages.** Only pytest is tested. The detector reads JUnit XML and coverage.py JSON, so other frameworks need their own adapters before they work.
- **Untracked inputs without `fingerprint-extra`.** `test_rates` shows the mitigation, not a fix. A test that reads an unlisted data file, an environment variable or a network service can still be misjudged when only that input changes.
- **Coarse extra files.** `fingerprint-extra` applies to every test. Editing `rates.json` gives *every* test a new fingerprint, which splits each flaky test's evidence at that point (see `test_cluster` utc: 3/16).

## CI

[`ci.yml`](.github/workflows/ci.yml) runs the suite as a UTC/PST matrix with random faults on every PR, every push and every three hours, and feeds the results to the detector's GitHub Action. Real flaky history builds up on the `flaky-data` branch, with one record per matrix job, and each run's job summary shows the current report. Test failures don't fail this job, because this repo exists to be flaky.
