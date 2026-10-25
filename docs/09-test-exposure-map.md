# Test exposure map

Audience: a developer or QA person who needs to know, for each capability and flow, what the current tests actually check and where there is no test at all.

Evidence: 16 of 16 entry points read · 11 capabilities · 8 open unknowns relevant to this document · commit b472b9b · Surveyor 2.2.0 · 2026-10-25

---

## How to read the results below

All six test files are plain Python scripts with top-level `assert` lines, not `def test_*` functions that pytest discovers on its own [inventory "Surprising zeros"]. The results below describe what each file's assertions check if run, read from the code. Whether pytest actually collects and runs them, and whether they currently pass, was not observed: Surveyor does not run code, and that question is open (U01, below) [inventory "Tests"].

All 16 entry points were read during phase 4 (slices S01-S11); none in this document is `scan only, not read`.

## C01 Screen and rank candidate trades (High)

| Flow | Entry point | Read in | Test files | Result |
|---|---|---|---|---|
| F001, core technical path | E001 | S01 | `test_toolkit.py`, `test_ml.py` | tested on the surface |
| F001, enrichment path (`--fundamentals`, `--anomalies`, `--qualitative`) | E001 | S02 | `test_screen_enrich.py`, `test_sources.py` | unknown |

What is tested (core path): `test_toolkit.py` checks ranking order, that strategy signals use no future data (no lookahead), valid stops for both strategies, and the pullback-length rule [S01/F001]. `test_ml.py` runs `screen` end to end with the meta-model filter, checks the run prints "Meta-model loaded", and checks that a missing model file stops the run [S01/F001].

Known gaps (core path): no test checks the sector-concentration flag, the TOTAL row, the market-cap class filter, the "no candidates" path, the index-download fallback, or position sizing inside `screen` itself. Search boundary: `flag_sector|to_rows|over_sector_cap|max_per_sector|No candidates|TOTAL|get_index_symbols|get_index_constituents|cap_class` in all `test_*.py` files at the repository root [S01/F001].

Enrichment path: `test_screen_enrich.py` and `test_sources.py` exercise the fundamentals, ownership and news wiring, but both call command options or a function the current code does not have (`--weights-file`, `fund_passed_w`, `parse_peers_fragment`) [S02/F001]. Whether these two files pass when run is open (U04, U05); one root cause under consideration is that some files are older than others (U06) [S02/F001]. The `--fundamentals` option may also fail at construction, since `screener.py` passes a field name `FundamentalFilters` does not define (U02) [S02/F001].

## C02 Monitor an open position (High)

| Flow | Entry point | Read in | Test files | Result |
|---|---|---|---|---|
| F005 | E005 | S03 | `test_toolkit.py` (shared exit functions only) | tested on the surface |

What is tested: no test calls `PositionMonitor` or the `monitor` command directly. `test_toolkit.py` checks the exit functions `monitor.py` shares with the backtester, `suggest_stop` and `time_stop_hit`, through backtests: the breakeven trail, the time-stop firing on the expected date, and the stop-touched exit arithmetic [S03/F005].

Known gaps: the verdict ladder at `monitor.py:84-96`, `target_already_hit`, and the behaviour once a stop has been raised (U08) are untested. Search boundary: `PositionMonitor|cmd_monitor|"monitor"|monitor\.check` in all root `*.py` files: matches only in `monitor.py` and `screener.py`, no `test_*.py` match [S03/F005]. Whether the date comparison at `monitor.py:65` works on real Yahoo data whose price index carries a time zone is also untested (U09) [S03/F005].

## C03 Analyse existing holdings (High)

| Flow | Entry point | Read in | Test files | Result |
|---|---|---|---|---|
| F008 | E008 | S04 | none found | not tested |

What is tested: nothing. Search boundary: `holdings_analysis` in all `test_*.py` files at the repository root: no match [S04/F008].

Known gaps: every function in `holdings_analysis.py`, including the pure functions `trend_state`, `verdict` and `add_portfolio_flags`, which the slice notes could be tested without a network call [S04/F008].

## C04 Convert a CDSL account statement to Excel (Medium)

| Flow | Entry point | Read in | Test files | Result |
|---|---|---|---|---|
| F009 | E009 | S05 | none found | not tested |

What is tested: nothing. Search boundary: `cdsl_holdings|isin_checksum_ok|choose_isin|extract_mf` in all `test_*.py` files at the repository root: no match [S05/F009]. The repository also holds no sample statement to test against [S05/F009].

Known gaps: every function, including the pure ISIN check-digit repair (`choose_isin`) and the row-arithmetic cross-checks, neither of which needs a PDF to test [S05/F009]. How accurate the converter is on real statements, especially scanned ones, is open (U15) [S05/F009].

## C05 Backtest the trading rules on history (Medium)

| Flow | Entry point | Read in | Test files | Result |
|---|---|---|---|---|
| F002 | E002 | S06 | `test_toolkit.py`, `test_membership.py` | well tested |

What is tested: `test_toolkit.py` drives the real `Backtester` over hand-crafted price paths where the correct answer is known: a gap through the stop exits at the open with the right quantity and P&L, the time-stop fires on the expected date, the stop trails to breakeven and exits there, a gap up through the target fills at the open with no slippage, costs are positive and final equity reconciles with the sum of trade P&L, sizing is against equity rather than cash, and each skip reason (`max_positions`, liquidity, stop-width, results-calendar, regime) is counted [S06/F002]. `test_membership.py` checks that a former index member trades while it was a member and that a not-yet-member is skipped and counted [S06/F002].

Known gaps: no test asserts the content of the written CSV files (`backtest_trades.csv`, `backtest_equity.csv`) or the exact metric values in `BacktestResult.metrics()` beyond the exit-reason and skip dictionaries. Search boundary: `trades_out|equity_out|to_csv|metrics\(|cagr|max_drawdown` in all `test_*.py` files at the repository root; matches were only the sweep-table and membership checks, not the backtest's own trade or equity files [S06/F002].

## C06 Validate a backtest (Medium)

| Flow | Entry point | Read in | Test files | Result |
|---|---|---|---|---|
| F003, `validate` command | E003 | S07 | `test_validation.py` | well tested |
| F013, real-data wrapper | E013 | S07 | none found | not tested |

What is tested (F003): `test_validation.py` runs the real `validate` command end to end over synthetic 5-year data with network calls monkeypatched (replacing a function during the test so no real call is made), and asserts the HTML report contains every section (equity curve, in/out-of-sample, calendar year, Monte Carlo, parameter sensitivity, walk-forward, an `<svg>` tag) with no `<script>` tag or external link; that the sweep CSV has the expected shape; that a run with no sweep skips those sections cleanly; that Monte Carlo percentiles are ordered and reproducible with a fixed seed; and that a known inert parameter is detected [S07/F003].

Known gaps (F003): no test asserts the exact verdict strings for the split, walk-forward or sweep tests, nor the regime-breakdown numbers. Search boundary: `verdict|regime_breakdown|efficiency|degradation` in all `test_*.py` files at the repository root; matches were only inside `validation.py` itself [S07/F003].

What is tested (F013): nothing. `real_data_check.py` needs live internet by design and runs `validate` as a subprocess; no offline test drives it. Search boundary: `real_data_check|real_check|check-only|SWEEPS_FULL|reachable` in all `test_*.py` files at the repository root: no match [S07/F013]. Whether it produces sensible numbers on real data, and whether the connectivity-then-subprocess path works end to end, is open (U16) [S07/F013].

## C07 Check companies for red flags (Medium)

| Flow | Entry point | Read in | Test files | Result |
|---|---|---|---|---|
| F010, train the classifier | E010 | S08 | `test_ml.py` | well tested (TF-IDF path only) |
| F011, import reviewed rows | E011 | S08 | `test_ml.py` | tested on the surface |
| F012, score one piece of text | E012 | S08 | `test_ml.py` | tested on the surface |
| F014, financial anomaly scan | E014 | S08 | `test_ml.py` | well tested |

What is tested (F010): `test_ml.py` trains a model from the seed set only, asserts the report has 30+ rows and an AUC, that a known false-positive scores lower than a genuine flag, that `apply` demotes the false positive to Low with a note while leaving a genuine flag at High untouched, that the regex-to-model integration keeps a genuine downgrade and demotes a stub, and that training on zero rows is refused [S08/F010].

Known gaps (F010): the `--embedder` PyTorch path (`Embedder`, the "embed" model kind) is not exercised; only the default TF-IDF path is tested. Search boundary: `embedder|Embedder|transformers|AutoModel|kind == "embed"` in all `test_*.py` files at the repository root: no match [S08/F010].

What is tested (F011): `test_ml.py` writes a 3-row "Governance flags" workbook, imports it, and asserts 2 rows are added the first time and 0 the second, and that the labels CSV then has 2 rows [S08/F011].

Known gaps (F011): the accepted label spellings in `_norm_label` (1/0, yes/no, genuine/false-positive and similar) and the missing-column `ValueError` are not asserted [S08/F011].

What is tested (F012): the underlying `prob` method that the `predict` command calls is tested directly, confirming a known false positive scores lower than a genuine flag [S08/F012].

Known gaps (F012): the `predict` CLI branch itself and its printed line are not driven by any test. Search boundary: `"predict"|cmd == "predict"|P\(genuine\)` in all `test_*.py` files at the repository root: no match [S08/F012].

What is tested (F014): `test_ml.py` builds a "good" and a "bad" synthetic company and asserts the bad one triggers the expected six rules and the good one triggers none; that missing statements give no flag; that `analyse_many` over 45 normal companies plus one planted outlier marks the outlier High with an Isolation Forest score of 95 or above and a peer-outlier note, while none of the 45 is High; that a bank and an unreadable symbol are `n/a`; and that a single company (too few peers) still gets its rule flags [S08/F014].

Known gaps (F014): the rule and peer-layer maths are checked only on synthetic, planted data. Accuracy on real screener.in statements is unverified, the same live-data limitation noted for the screen enrichment path (U13, U15) [S08/F014].

## C08 Filter trades by predicted quality (meta-model) (Low)

| Flow | Entry point | Read in | Test files | Result |
|---|---|---|---|---|
| F004 | E004 | S09 | `test_ml.py` | well tested |

What is tested: `test_ml.py` asserts features at a bar are unchanged when later rows are removed (no lookahead); runs `train-meta` end to end on synthetic data and checks the model is saved with the right dataset columns and labels; checks walk-forward produces folds and that too little data gives a "no usable folds" verdict; checks the ranking engine uses the win probability only as a tie-break after points; runs `screen --meta filter` end to end and checks a missing model gives a clear error; and checks the calibration method (isotonic, sigmoid or none) matches the sample size, stays within [0,1], and pulls an over-confident score back toward the true win rate [S09/F004].

Known gaps: no test asserts the specific "promising" or "unstable" verdict text, nor the stored probability threshold saved in the model file. Search boundary: `promising|unstable|threshold|fit_and_save` in all `test_*.py` files at the repository root; matches drive `fit_and_save` indirectly but assert only that the model loads and predicts, not the verdict string [S09/F004].

## C09 Rebuild index membership history (Low)

| Flow | Entry point | Read in | Test files | Result |
|---|---|---|---|---|
| F007 | E007 | S10 | `test_membership.py` | well tested |

What is tested: `test_membership.py` writes three dated snapshot files, calls `changes_from_snapshots`, and asserts the exact ADD/REMOVE rows; calls `merge_changes_file` twice and asserts 2 rows added then 0; and checks the underlying `MembershipHistory`: reconstruction flips membership exactly on the effective date, an inconsistent change list raises a warning, the change-file parser gives line-numbered errors, and the backtester drops a signal on a stock not in the index that day [S10/F007].

Known gaps: no test drives the `snapshot-changes` CLI wrapper itself (the functions it calls are tested directly), nor the "no snapshots yet" message path. Search boundary: `snapshot-changes|cmd_snapshot_changes|No index changes` in all `test_*.py` files at the repository root: no match [S10/F007].

## C10 Refresh prices in a results file (Low)

| Flow | Entry point | Read in | Test files | Result |
|---|---|---|---|---|
| F006 | E006 | S10 | none found | not tested |

What is tested: nothing. Search boundary: `update-price|cmd_update_price|price on ` in all `test_*.py` files at the repository root: no match [S10/F006].

Known gaps: the all-strings preservation of every other column, the TOTAL-row skip, the column naming, and the per-symbol fetch-failure path are all untested [S10/F006].

## C11 Diagnose data-source problems (Low)

| Flow | Entry point | Read in | Test files | Result |
|---|---|---|---|---|
| F015 | E015 | S11 | none found | not tested |
| F016 | E016 | S11 | none found | not tested |

What is tested: nothing, for either script. Search boundary: `diagnose_dump` and `fetch_xbrl` searched across the whole repository; no test file references either script [S11/F015, S11/F016].

Known gaps: neither script's output has been checked against a known-correct answer. The tag-extraction regex in `fetch_xbrl_sample.py` has not been checked against a real XBRL filing [S11/F016].

## Summary counts

16 flows across 11 capabilities. `F001` is counted twice below because its two code paths, core technical screening and optional enrichment, carry different results (see C01 above); every other flow is counted once.

| Result | Flows | Count |
|---|---|---|
| well tested | F002, F003, F004, F007, F010 (TF-IDF path), F014 | 6 |
| tested on the surface | F001 (core path), F005, F011, F012 | 4 |
| not tested | F006, F008, F009, F013, F015, F016 | 6 |
| unknown | F001 (enrichment path) | 1 |
| switched off | none found | 0 |
| scan only, not read | none | 0 |

By importance, where a flow is `not tested` or `unknown`:

| Importance | Capabilities | Flows with no test, or an unresolved test |
|---|---|---|
| High | C01, C02, C03 | C01's enrichment path (unknown); C03 F008 (not tested) |
| Medium | C04, C05, C06, C07 | C04 F009 (not tested); C06 F013 (not tested) |
| Low | C08, C09, C10, C11 | C10 F006 (not tested); C11 F015, F016 (not tested) |

Every Medium-importance capability except C04 and the real-data half of C06 has at least one well-tested flow. Both High-importance capabilities with a gap (C01's enrichment path, C03) carry it on the main flow itself, not a side path.

---

## Unknowns and next probes

| ID | Question | Why it matters here | Next probe |
|---|---|---|---|
| U01 | The six test files have no `def test_*` functions. Does pytest collect and report them, and do they pass? | Every "well tested" and "tested on the surface" result above describes what the assertions check if run, not a confirmed pass. | Run `pytest` and `python test_toolkit.py` (and the other five) in a sandbox and compare. |
| U04 | Does `test_screen_enrich.py` pass, given it expects options and a field the current code does not have? | Decides whether C01's enrichment path has any working test at all. | Run it in a sandbox, or ask the developer. |
| U05 | Does `test_sources.py` pass, given it calls `parse_peers_fragment`, which `screener_in.py` does not define? | Same as U04, for the data-source tests behind C01's enrichment path. | Run it in a sandbox, or ask the developer. |
| U06 | Are some files older than others, explaining U02 to U05? | One answer may settle whether C01's enrichment tests are current or stale. | `git log --oneline -- screener.py candidate_engine.py screener_in.py fundamentals.py`. |
| U08 | Is it intended that `monitor`'s "should already be closed" verdict compares a raised stop against lows from before the raise? | The untested verdict ladder (C02) includes this path; whether it is a bug or by design changes what a new test should assert. | Ask the developer or owner. |
| U09 | Does `monitor.py:65`'s date comparison work on real Yahoo data, whose price index may carry a time zone? | No test covers this for C02; a real-data failure would be hidden behind a clean exit code. | Run `monitor` on a real symbol and read the output, or print `df.index.tz`. |
| U15 | How accurate is the CDSL statement converter (C04) on real statements, especially scanned ones? | C04 has no test and no sample; this is the only way to judge it short of writing one. | Ask the owner for a redacted sample statement, or the "Reconciliation" sheet of a past run. |
| U16 | Do `real_data_check.py` and `validate` (C06's real-data flow, F013) produce sensible numbers on real Yahoo/NSE data? | F013 is the one path meant to catch a broken real-data case, and it has no automated test. | Run `python real_data_check.py --quick` (or `--check-only` first) with normal internet. |

## Related documents

- [01-overview.md](01-overview.md): the capabilities table, with a test-result column for each capability.
- [03-request-to-response-flow.md](03-request-to-response-flow.md): the main, alternative and exception flows each test result above is checking.
- [05-api-reference.md](05-api-reference.md): the example drawn from a test, or the stated search boundary where none exists, for every entry point.
- [08-developer-onboarding.md](08-developer-onboarding.md): how to run each test file, and which four of the six need no network connection.
- [10-test-review.md](10-test-review.md): strengths, weak tests and disabled tests.
- [11-developer-testing-tasks.md](11-developer-testing-tasks.md): concrete testing tasks built from the gaps above.
