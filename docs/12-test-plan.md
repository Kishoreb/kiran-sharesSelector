# Test plan

Audience: a developer or QA person deciding what to test next and how to run it, and a reviewer deciding whether this toolkit's test coverage is good enough to trust.

Evidence: 16 of 16 entry points read · 11 capabilities · 10 open unknowns relevant to this document · commit b472b9b · Surveyor 2.2.0 · 2026-10-25

---

## How to read this document

This plan builds on [10-test-review.md](10-test-review.md)'s strengths and risk ranking and on [11-developer-testing-tasks.md](11-developer-testing-tasks.md)'s five tasks. It does not repeat their evidence in full. Facts about the current suite are cited as in those documents; general advice on how to organise testing going forward is labelled `Recommendation:`, as the rules for this document require.

## Strategy by level

What exists today, observed: all 6 test files are plain Python scripts with top-level `assert` statements, run directly with `python <file>.py`, not collected by pytest's own discovery (`def test_*`, `class Test*` and `unittest` all returned 0 matches) [inventory "Surprising zeros"]. In substance, two levels already exist, even though no file or folder separates them:

- Offline, synthetic-input tests: `test_toolkit.py`, `test_membership.py`, `test_ml.py` and `test_validation.py` all drive a real production function or command over a hand-built input whose correct answer is known, with any mock placed only at the network boundary (for example `screener.fetch_history` in `test_validation.py:37`, `screener_in.get_raw` in `test_ml.py:227`) [10-test-review.md "Strengths"; 08-developer-onboarding.md "Running the tests"]. These need no internet connection and cover the flows graded well tested or tested on the surface in [09-test-exposure-map.md](09-test-exposure-map.md).
- Live, real-data runs: `real_data_check.py` is the one tool meant to exercise the toolkit against real Yahoo and NSE data, by checking connectivity and then running `validate` as a subprocess [S07/F013]. It has no assertions of its own; a person is meant to read its output. No test drives it offline, and whether its real-data output is sensible is open (U16) [S07/F013; 10-test-review.md "Risks ranked by importance times weakness", rank 5].

No level in between (for example, replaying a recorded real response instead of a hand-built synthetic one) was found in any of the 11 slices.

Recommendation: keep both levels, name them, and extend the first one to close the gaps [09-test-exposure-map.md](09-test-exposure-map.md) already lists:

1. Unit level: pure functions that take already-loaded data and make no network or file call, for example `trend_state`, `verdict` and `add_portfolio_flags` in `holdings_analysis.py`, and `isin_checksum_ok`, `choose_isin` and `reconcile` in `cdsl_holdings_to_xls.py`. [11-developer-testing-tasks.md](11-developer-testing-tasks.md) tasks 2 and 4 already specify these as hand-built-input, known-answer checks; this plan does not repeat them.
2. Offline integration level: a command or class run end to end with the network monkeypatched, in the same style `test_toolkit.py`, `test_membership.py`, `test_ml.py` and `test_validation.py` already use. [11-developer-testing-tasks.md](11-developer-testing-tasks.md) tasks 1, 3 and 5 extend this level to the `--fundamentals` enrichment path, the `monitor` verdict ladder, and `real_data_check.py`'s own branching logic (with `reachable` monkeypatched).
3. Real-data level: a person runs `real_data_check.py` and `monitor` against live data on a schedule the owner chooses, and reads the result. This level stays manual; nothing in the 11 slices shows an automated check of real-data output, and judging real-data accuracy is outside what reading code can do (rules section 2).

## Priority areas from document 10

The order below is [10-test-review.md](10-test-review.md)'s "Risks ranked by importance times weakness" table, restated as work areas. Each area is the same risk, not a new one.

| Priority | Area | Current state | What closes it |
|---|---|---|---|
| 1 | C01's `--fundamentals` enrichment path (High importance) | Unknown: `screener.py:216` passes a field `FundamentalFilters` does not define, `fund.industry_pe_map` is called but defined nowhere, and both test files for this path call names the current code lacks (U02, U03, U04, U05, U06) [10-test-review.md rank 1] | Settle U02, U03 and U06 first, then write or fix the test, per [11-developer-testing-tasks.md](11-developer-testing-tasks.md) task 1 |
| 2 | C03 holdings analysis (High importance) | Not tested: no test file matches `holdings_analysis` [10-test-review.md rank 2; S04/F008] | Unit-level tests on the pure functions, per task 2 |
| 3 | C02 `monitor` verdict ladder (High importance) | Tested on the surface: the shared exit functions are tested through the backtester, but the verdict ladder itself (`monitor.py:84-96`) is not, and two correctness questions are open (U08, U09) [10-test-review.md rank 3] | Offline-integration tests calling `PositionMonitor.check` directly, per task 3 |
| 4 | C04 CDSL converter (Medium importance) | Not tested; no sample statement exists to test against [10-test-review.md rank 4] | Unit-level tests on the checksum, OCR-repair and arithmetic functions, per task 4 |
| 5 | C06 real-data wrapper (Medium importance) | Not tested, inside an otherwise well-tested capability (U16) [10-test-review.md rank 5] | Offline-integration test with `reachable` monkeypatched, per task 5 |
| 6 | C07 embedder path, `import-sheet`, `predict` (Medium importance) | Unexercised or tested on the surface only [10-test-review.md rank 6] | Not covered by a task in document 11; see "Unknowns and next probes" below |
| 7 | C10 `update-price`, C11 diagnostics (Low importance) | Not tested [10-test-review.md rank 7] | Not covered by a task in document 11; housekeeping and developer tools, lowest priority |

[11-developer-testing-tasks.md](11-developer-testing-tasks.md) covers priorities 1 to 5 in full. Priorities 6 and 7 have no task written yet.

## Entry and exit criteria

Entry criteria, before starting work on a priority area:

| Area | Must be true first | Why |
|---|---|---|
| Priority 1 (C01 enrichment) | U02, U03 and U06 answered, or a developer decision recorded in `open-questions.md` | Writing a test against code that may not run at all would test the wrong target; [11-developer-testing-tasks.md](11-developer-testing-tasks.md) task 1 makes the same point |
| All offline-integration and unit tests | U01 answered: does pytest collect and run these scripts, and does a failure partway through one hide later checks in the same file | Decides whether new tests should follow the same top-level-assert convention or move to `def test_*` functions; every existing and proposed test result in documents 9 to 11 is qualified by this unknown |
| Priority 3 (C02 monitor) | None beyond U01; the verdict ladder can be tested directly by calling `PositionMonitor.check`, without needing U08 or U09 answered first | Task 3 already shows the test can record current behaviour even while whether that behaviour is correct stays open |

Recommendation: treat U01 as the one blocking question for the whole plan, not just one area, and settle it before writing any new test file, since it decides whether the new tests will even be collected and reported.

Exit criteria, for calling a priority area's testing work done:

- Recommendation: a priority area is done when its flow's test result (rules section 9 vocabulary) reaches at least `tested on the surface`, and for a High-importance capability's main flow, reaches `well tested`: a known-answer input drives the real function and the test asserts the exact outcome, not only that the run completed. [10-test-review.md](10-test-review.md)'s "Tests that prove little" section shows what falls short of this bar today (F001's core path, F005, F011, F012).
- Recommendation: a priority area is not done while any of its target functions is tested only indirectly, the way `predict`'s CLI branch is graded "tested on the surface" solely because the `prob()` method one layer below it has a test [10-test-review.md "A tested helper can disguise an untested command"].
- The contradictions behind priority 1 (U02 to U06) are not closed by a passing test alone: rules section 12 requires recording which side, the production code or the test file, was the one that moved, not silently picking one.

## Tooling already in the repository

- The top-level `assert` script convention itself: 6 files, 268 `assert` lines in total, each run with `python <file>.py` [inventory "Tests" table].
- A `.pytest_cache/` folder exists alongside the project, showing pytest has been invoked here at least once, even though no `pytest.ini`, `tox.ini` or `conftest.py` was found and none of the 6 files defines a `def test_*` function pytest would discover on its own [inventory "Tests"; inventory "Configuration files"].
- Monkeypatching (replacing a function during a test run so no real call is made) is already used to isolate the network boundary: `test_validation.py:37` replaces `screener.fetch_history`, and `test_ml.py:227` replaces `screener_in.get_raw` [10-test-review.md "Strengths"; S08].
- No coverage tool, no CI configuration file (`.github/`, `Jenkinsfile`, `azure-pipelines.yml` and similar all returned 0 matches), and no package manifest were found [inventory "Surprising zeros"].

Recommendations:

- Recommendation: keep the existing monkeypatch-at-the-network-boundary pattern for any new offline-integration test; [10-test-review.md](10-test-review.md) found no case where this pattern reached into the logic under test instead of the network.
- Recommendation: once U01 is settled, if pytest does collect these files, add a minimal `pytest.ini` (or `pyproject.toml` `[tool.pytest.ini_options]` section) that states that intent explicitly, rather than leaving pytest's behaviour on these files implicit.
- Recommendation: if the six files are kept as top-level-assert scripts rather than converted to `def test_*` functions, split each file's sections into separate functions at minimum, so one `AssertionError` does not silently end the remaining checks in the same file, a risk [10-test-review.md](10-test-review.md) raises under "Level-of-test problems" but does not resolve.
- Recommendation: add a `requirements-dev.txt` (or a dev extra) that pins pytest if it becomes the runner, since no test-running package is declared anywhere today [inventory "Configuration files"].

---

## Unknowns and next probes

| ID | Question | Why it matters here | Next probe |
|---|---|---|---|
| U01 | Does pytest collect and run the six existing top-level-assert test files, and would it also collect new ones written the same way, and do they pass? | This is the entry criterion for every other item in this plan: it decides how the test suite is actually run and reported. | Run `pytest` and `python test_toolkit.py` (and the other five) in a sandbox and compare what each reports. |
| U02 | Does `screen --fundamentals flag` stop with an error, since `screener.py:216` passes `min_inst_change` to a class with no such field? | Blocks priority area 1. | Run it in a sandbox, or ask the developer which file is newer. |
| U03 | Where is `fund.industry_pe_map`, called at `screener.py:222` and `holdings_analysis.py:306` but defined in no root file? | Blocks priority area 1. | `git log -S industry_pe_map`; ask the developer. |
| U04 | Does `test_screen_enrich.py` pass, given it expects options and a field the current code does not have? | Decides whether priority area 1 already has a working test, once the production code is settled. | Run it in a sandbox, or ask the developer. |
| U05 | Does `test_sources.py` pass, given it calls `parse_peers_fragment`, which `screener_in.py` does not define? | Same as U04. | Run it in a sandbox, or ask the developer. |
| U06 | Are `screener.py`, `candidate_engine.py` and `screener_in.py` older than `fundamentals.py`, `fund_weights.py`, `holdings_analysis.py` and the two drifted tests? | May settle U02 to U05 together, and is the entry criterion for priority area 1. | `git log --oneline -- screener.py candidate_engine.py screener_in.py fundamentals.py`. |
| U08 | Is it intended that `monitor`'s "should already be closed" verdict compares a raised stop against lows from before the raise? | Decides what a new test of the verdict ladder (priority area 3) should assert as correct, not merely as current. | Ask the developer or owner. |
| U09 | Does `monitor.py:65`'s date comparison work on real Yahoo data, whose price index may carry a time zone? | A real-data-level check for priority area 3 depends on this being resolved first. | Run `monitor` on a real symbol and read the output, or print `df.index.tz`. |
| U15 | How accurate is the CDSL statement converter (priority area 4) on real statements, especially scanned ones? | A unit test on the checksum and arithmetic functions cannot judge OCR accuracy; this needs a real sample. | Ask the owner for a redacted sample statement, or the "Reconciliation" sheet of a past run. |
| U16 | Do `real_data_check.py` and `validate` (priority area 5) produce sensible numbers on real Yahoo/NSE data? | This is the exit criterion for the real-data level described above; no offline test can substitute for it. | Run `python real_data_check.py --quick` (or `--check-only` first) with normal internet. |

Priority areas 6 and 7 (the embedder path, `import-sheet`, `predict`, `update-price`, and the two developer-diagnostic scripts) have no open unknown recorded against them beyond what [09-test-exposure-map.md](09-test-exposure-map.md) already lists as known gaps; they have no task in [11-developer-testing-tasks.md](11-developer-testing-tasks.md) either, so starting work there has no blocking question but also no worked example to follow.

## Related documents

- [10-test-review.md](10-test-review.md): the strengths, weaknesses and risk ranking this plan is built from.
- [09-test-exposure-map.md](09-test-exposure-map.md): the per-flow test results behind that ranking.
- [11-developer-testing-tasks.md](11-developer-testing-tasks.md): the five concrete tasks for priority areas 1 to 5.
- [08-developer-onboarding.md](08-developer-onboarding.md): how to run each existing test file today, and which need no network connection.
- [01-overview.md](01-overview.md): the capabilities table with each capability's importance rating, used to weight the priority order above.
