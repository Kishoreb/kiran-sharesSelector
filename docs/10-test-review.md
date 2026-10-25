# Test review

Audience: a developer or QA person deciding where to spend testing effort next, and what to trust in the existing suite before relying on it.

Evidence: 16 of 16 entry points read · 11 capabilities · 10 open unknowns relevant to this document · commit b472b9b · Surveyor 2.2.0 · 2026-10-25

---

## How to read the results below

This document grades the same 6 test files and 16 entry points as [09-test-exposure-map.md](09-test-exposure-map.md), from the same evidence. It does not add new code reading. Every result below describes what a test's assertions check if the file runs; whether pytest collects and runs these files, and whether they currently pass, was not observed (U01) [inventory "Surprising zeros"].

## Strengths

The 6 flows graded "well tested" in document 9 (F002, F003, F004, F007, F010's TF-IDF path, F014) share one pattern: the test drives the real production function, not a replacement for it, over an input whose correct answer the test author can work out by hand, and then asserts that exact answer rather than just "it ran".

Examples:

- `test_toolkit.py` builds hand-crafted price paths and asserts the exact exit date, exit price and reason the real `Backtester` should produce: a gap through the stop fills at 90, not 95, on the known date [S06/F002: `test_toolkit.py:67`]; the final equity reconciles with the sum of trade profit and loss to within 0.5 rupees [S06/F002: `test_toolkit.py:107`].
- `test_membership.py` writes three dated snapshot files and asserts the exact ADD/REMOVE rows `changes_from_snapshots` produces from them [S10/F007: `test_membership.py:111`].
- `test_ml.py` plants one outlier company among 45 normal ones and asserts `analyse_many` marks only the planted outlier High, with an Isolation Forest score of 95 or above [S08/F014: `test_ml.py:233`].
- `test_validation.py` fixes the Monte Carlo seed and asserts the shuffle drawdown percentiles come out ordered (p50 ≤ p95 ≤ p99) and reproducible [S07/F003: `test_validation.py:60`].
- `test_ml.py` checks the meta-model's probability calibration pulls an over-confident score back toward the true win rate, to within 0.1 [S09/F004: `test_ml.py:182`].
- `test_ml.py` asserts the governance classifier demotes a known false positive to Low while leaving a genuine High flag untouched [S08/F010: `test_ml.py:40`, `test_ml.py:43`].

Where these tests remove the network, they replace only the network call, not the logic under test: `test_validation.py` monkeypatches `screener.fetch_history` so `validate` runs on synthetic 5-year data, but the split, sweep, walk-forward and Monte Carlo maths underneath run unmodified [S07/F003: `test_validation.py:37`, from inventory "Needs a human look"]. The mock sits at the network boundary, not inside the logic being tested.

## Tests that prove little

Four flows are graded "tested on the surface" in document 9 (F001's core path, F005, F011, F012). In each case a test exists and passes real input through real code, but stops short of the outcome the capability actually promises.

- F001, the `screen` command itself: the only test that runs `screen` end to end with the meta-model filter asserts that the string "Meta-model loaded" appears in the output and that a missing model file stops the run [S01/F001: `test_ml.py:146`, `test_ml.py:151`]. It does not check the candidates or the ranking that run produced. The ranking logic itself is checked, but through a separate, direct call to `CandidateEngine.rank`, not through this command run [S09/F004: `test_ml.py:137`].
- F005, `monitor`: no test calls `PositionMonitor` or the `monitor` command [S03/F005]. The only testing contact is indirect: `exits.py`'s `suggest_stop` and `time_stop_hit`, which `monitor.py` shares with the backtester, are exercised through backtests [S03/F005: `test_toolkit.py:74`, `test_toolkit.py:87`]. The verdict ladder the user actually reads, `monitor.py:84-96`, has no test at all.
- F011, `import-sheet`: the only test asserts a row count, 2 rows added on first import and 0 on a repeat [S08/F011: `test_ml.py:62`]. It does not check which label spellings `_norm_label` accepts (1/0, yes/no, genuine/false-positive) or that a sheet missing a required column raises the documented error.
- F012, `predict`: the command's own behaviour, including the line it prints, has no test. The one test that touches this area calls the `prob()` method directly, one layer below the command line [S08/F012: `test_ml.py:35`]. Because that lower-level test exists, document 9 grades F012 "tested on the surface" rather than "not tested", but the `predict` branch itself (`gov_classifier.py:291-304`) has zero coverage.

## Disabled tests

No `pytest.mark.skip`, `pytest.mark.skipif`, `pytest.mark.xfail`, `unittest.skip`, `pytest.skip` or `importorskip` marker was found in any `*.py` file at the repository root, so no test is formally disabled within that search [inventory "Disabled tests" row: search boundary as stated]. That search did not cover commented-out `assert` lines; whether a check was ever written and then silently commented out is not measured [inventory "Disabled tests" row].

## Level-of-test problems

### How the suite runs

All 6 test files are plain Python scripts with top-level `assert` statements, not `def test_*` functions a runner discovers on its own [inventory "Surprising zeros"]. `test_toolkit.py` groups its checks into letter-labelled sections that each print a confirmation when reached, for example "G ok" at `test_toolkit.py:119` [inventory "Needs a human look"].

Because each section is top-level code rather than its own function, an uncaught `AssertionError` partway through a file is inferred to stop that file there, so later sections never run and never report a result, pass or fail, not only the section that failed. This is reasoned from how Python executes top-level statements in a script; no test run was observed to confirm or disprove it, since Surveyor does not run code. Whether pytest collects and runs these 6 files as tests at all, and whether they currently pass end to end, is open (U01), and it qualifies every "well tested" and "tested on the surface" result in this document and in document 9.

### Tests written against code that has moved on

`test_screen_enrich.py` and `test_sources.py` call command options and functions that the code in this tree does not have: `--weights-file`, `--no-weights-file`, `--technical-only`, `--industry-pe-file`, and a Candidate field `fund_passed_w` [S01/F001: `test_screen_enrich.py:107`, `test_screen_enrich.py:102`]; `parse_peers_fragment` and a `peers` entry from `get_raw` [S02/F001: `test_sources.py:104-105`]. A test file that calls a name the production code does not define cannot run past that line, whatever its assert count suggests about coverage. `screener.py` separately passes `min_inst_change` to a class that defines `min_fii_change` and `min_dii_change` instead [S01/F001: `screener.py:216`; S02/F001: `fundamentals.py:99-100`], and calls `fund.industry_pe_map`, which no root file defines [S02/F001: `screener.py:222`]. Whether the tests or the production modules are the ones that moved on is open (U02, U03, U04, U05, U06). Until it is answered, the enrichment path of C01, a High-importance capability, has an unresolved rather than a known test result.

### A tested helper can disguise an untested command

F012's `predict` command, above, shows the pattern in miniature: a flow can be graded "tested on the surface" because a function one layer below the entry point is tested directly, while the entry point a user actually runs has no test pointed at it.

## Risks ranked by importance times weakness

The ranking combines each flow's capability importance (High, Medium or Low, from `capabilities.md`) with its test weakness. Weakest to strongest, by the vocabulary in rules section 9: `not tested` and `unknown` outrank `tested on the surface`, which outranks `well tested`. Within the same importance and weakness, the one with more at stake (real money, personal data, or the only check meant to catch a given failure) is ranked first.

| Rank | Capability (importance) | Flow | Weakness | Why |
|---|---|---|---|---|
| 1 | C01 Screen and rank candidate trades (High) | F001, enrichment path | unknown; likely cannot execute past a mismatched function call | The option a user would set to turn on fundamentals (`--fundamentals`) is inferred to crash at construction (U02), and the function behind P/E-vs-industry does not exist (U03); the two test files for this path call names the code does not have either (U04, U05, U06) [S01/F001, S02/F001]. |
| 2 | C03 Analyse existing holdings (High) | F008 | not tested; 0 tests found | This runs the toolkit's rules over the owner's real portfolio. No search match for `holdings_analysis` in any test file [S04/F008]. Even the pure functions `trend_state`, `verdict` and `add_portfolio_flags`, which need no network call, have no test. |
| 3 | C02 Monitor an open position (High) | F005 | tested on the surface; the verdict ladder itself is untested, plus two open correctness questions | This is the capability that tells the owner whether to keep holding a position already bought. The verdict order (`monitor.py:84-96`) has no test [S03/F005]. Whether a raised stop is compared correctly against old price lows (U08) and whether the date comparison works on real, timezone-carrying Yahoo data (U09) are both open. |
| 4 | C04 Convert a CDSL statement to Excel (Medium) | F009 | not tested; no sample statement exists in the repository to test against | Handles the owner's tax-ID password and real holdings data [S05/F009]. There is no automated check and no redacted sample to build one from; real-world accuracy, especially on scanned statements, is unmeasured (U15). |
| 5 | C06 Validate a backtest (Medium) | F013, real-data wrapper | not tested, inside an otherwise well-tested capability | `real_data_check.py` is the one path meant to catch a broken real-data case before the owner trusts a backtest; no offline test drives it, and whether it produces sensible numbers on live data is open (U16) [S07/F013]. |
| 6 | C07 Check companies for red flags (Medium) | F010 embedder path, F011, F012 | unexercised, or tested on the surface only | The optional PyTorch sentence-embedding path is not exercised by any test (only the default TF-IDF path is) [S08/F010]. The `import-sheet` and `predict` command branches are proven only at the surface, as described above. |
| 7 | C10 Refresh prices in a results file (Low), C11 Diagnose data-source problems (Low) | F006, F015, F016 | not tested | Housekeeping and developer-diagnostic tools; no money or personal data is at stake [S10/F006, S11]. |

Both High-importance gaps that are not C02 (C01's enrichment path, C03) sit on the capability's main flow, not a side option; a user who turns on `--fundamentals` or runs the holdings analysis is not using an edge case.

---

## Unknowns and next probes

| ID | Question | Why it matters here | Next probe |
|---|---|---|---|
| U01 | The six test files have no `def test_*` functions and are built as sequential top-level `assert` statements. Does pytest collect and report them, and do they pass, and does a failure partway through a file hide every later check in that file? | Every test result in this document and in document 9 describes what the assertions check if the file runs to completion, not a confirmed pass. | Run `pytest` and `python test_toolkit.py` (and the other five) in a sandbox and compare what each reports. |
| U02 | Does `screen --fundamentals flag` stop with an error, since `screener.py:216` passes `min_inst_change` to a class that has no such field? | Decides whether C01's enrichment path, ranked risk #1 above, has any working entry at all. | Run it in a sandbox, or ask the developer which file is newer. |
| U03 | Where is `fund.industry_pe_map`, called at `screener.py:222` and `holdings_analysis.py:306` but defined in no root file? | The P/E-vs-industry rule cannot run in either `screen` or the holdings analysis until this is found. | `git log -S industry_pe_map`; ask the developer. |
| U04 | Does `test_screen_enrich.py` pass, given it expects options and a field the current code does not have? | Decides whether C01's enrichment path has a working test. | Run it in a sandbox, or ask the developer. |
| U05 | Does `test_sources.py` pass, given it calls `parse_peers_fragment`, which `screener_in.py` does not define? | Same as U04, for the data-source tests behind C01's enrichment path. | Run it in a sandbox, or ask the developer. |
| U06 | Are `screener.py`, `candidate_engine.py` and `screener_in.py` older than `fundamentals.py`, `fund_weights.py`, `holdings_analysis.py` and the two drifted tests? | One answer may settle whether the enrichment tests are current or stale, and whether they count toward coverage at all. | `git log --oneline -- screener.py candidate_engine.py screener_in.py fundamentals.py`. |
| U08 | Is it intended that `monitor`'s "should already be closed" verdict compares a raised stop against lows from before the raise? | The untested verdict ladder (C02, risk #3) includes this path; whether it is a bug changes what a new test should assert. | Ask the developer or owner. |
| U09 | Does `monitor.py:65`'s date comparison work on real Yahoo data, whose price index may carry a time zone? | No test covers this for C02; a real-data failure would be hidden behind a clean exit code. | Run `monitor` on a real symbol and read the output, or print `df.index.tz`. |
| U15 | How accurate is the CDSL statement converter (C04, risk #4) on real statements, especially scanned ones? | C04 has no test and no sample; this is the only way to judge it short of writing one. | Ask the owner for a redacted sample statement, or the "Reconciliation" sheet of a past run. |
| U16 | Do `real_data_check.py` and `validate` (C06's real-data flow, risk #5) produce sensible numbers on real Yahoo/NSE data? | F013 is the one path meant to catch a broken real-data case, and it has no automated test. | Run `python real_data_check.py --quick` (or `--check-only` first) with normal internet. |

## Related documents

- [09-test-exposure-map.md](09-test-exposure-map.md): the per-flow test results this document grades for strength and weakness.
- [04-screen-and-rank.md](04-screen-and-rank.md): C01's risks in depth, including U02 to U06 and U18.
- [01-overview.md](01-overview.md): the capabilities table with each capability's importance rating.
- [08-developer-onboarding.md](08-developer-onboarding.md): how to run each test file and which need no network connection.
- [11-developer-testing-tasks.md](11-developer-testing-tasks.md): concrete testing tasks built from the risks ranked above.
- [12-test-plan.md](12-test-plan.md): overall test strategy built from this review.
