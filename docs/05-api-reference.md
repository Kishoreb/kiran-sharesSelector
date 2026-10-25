# API reference

Audience: a developer or integrator who needs the exact command, inputs, outputs and error behaviour for each entry point, without reading the source first.

Evidence: 16 of 16 entry points read · 11 capabilities · 20 open unknowns relevant to this document · commit b472b9b · Surveyor 2.2.0 · 2026-10-25

---

## How to read this document

There is no network API here. Every entry point is started by hand from a command line, `python <file>.py [sub-command] [options]`, so "method and path" in a typical API reference becomes the command line itself [inventory]. An option's default is stated only where the parser line, a dataclass default it reads from, or an equivalent line was read and checked in a slice. A default known only from the README and not matched against the parser is marked "not quote-checked" [doc-diff].

All 16 entry points were read across slices S01 to S11; none is marked `not read`.

## All entry points

| ID | Command | Capability | Flow | Test result |
|---|---|---|---|---|
| E001 | `screener.py screen` | C01 Screen and rank candidate trades | F001 | tested on the surface (technical path, S01); unknown (enrichment path, S02) |
| E002 | `screener.py backtest` | C05 Backtest the trading rules on history | F002 | well tested |
| E003 | `screener.py validate` | C06 Validate a backtest | F003 | well tested |
| E004 | `screener.py train-meta` | C08 Filter trades by predicted quality | F004 | well tested |
| E005 | `screener.py monitor` | C02 Monitor an open position | F005 | tested on the surface |
| E006 | `screener.py update-price` | C10 Refresh prices in a results file | F006 | not tested |
| E007 | `screener.py snapshot-changes` | C09 Rebuild index membership history | F007 | well tested |
| E008 | `holdings_analysis.py` | C03 Analyse existing holdings | F008 | not tested |
| E009 | `cdsl_holdings_to_xls.py` | C04 Convert a CDSL account statement to Excel | F009 | not tested |
| E010 | `gov_classifier.py train` | C07 Check companies for red flags | F010 | well tested (TF-IDF path) |
| E011 | `gov_classifier.py import-sheet` | C07 | F011 | tested on the surface |
| E012 | `gov_classifier.py predict` | C07 | F012 | tested on the surface |
| E013 | `real_data_check.py` | C06 | F013 | not tested |
| E014 | `anomaly.py` | C07 | F014 | well tested |
| E015 | `diagnose_dump.py` | C11 Diagnose data-source problems | F015 | not tested |
| E016 | `fetch_xbrl_sample.py` | C11 | F016 | not tested |

Source: capabilities.md, obligations.md, and each slice's "Test result" line [S01-S11].

---

## E001: `screener.py screen`

C01 Screen and rank candidate trades · F001

**Command**: `python screener.py screen [options]` [S01/F001: `screener.py:754`]

**Inputs**

| Option | Purpose | Default | Evidence |
|---|---|---|---|
| `--symbols` | explicit symbol list, instead of an index | none; overrides `--index` | test_ml.py:146 (usage) |
| `--index` | NSE index to screen | `nifty50` (not quote-checked) | doc-diff N8 |
| `--strategy` | `pullback_trend` or `breakout` | `pullback_trend` | S01/F001; `strategies.py:278` |
| `--capital` | capital used for position sizing | not quote-checked | `risk.py:60` (usage) |
| `--risk-pct` | % of capital risked per trade | 1.5 | `screener.py:703` |
| `--reward-risk` | target as a multiple of the stop distance | 2.0 | `risk.py:91` |
| `--heat-ceiling` | portfolio heat ceiling, accepted but not enforced by this command (Risk 1, see 04-screen-and-rank.md) | 8.0 | `screener.py:703`; U07 |
| `--max-positions` | position-count ceiling, accepted but not enforced by this command | 5 | `screener.py` (04-screen-and-rank.md); U07 |
| `--max-stop-pct` | rejects a setup with a wider stop | 8.0 | `filters.py:93` |
| `--sma200` / `--no-sma200` | require close above the 200-day average | on | `strategies.py:37` |
| `--min-turnover-cr` | minimum daily traded value filter | 1.0 Crore (not quote-checked) | doc-diff N2 |
| `--max-from-high-pct` | require close within N% of the 52-week high | 20 (not quote-checked) | doc-diff N3 |
| `--fundamentals` | `off` / `flag` / `filter` | `off` | `screener.py:761` |
| `--anomalies` | `off` / `flag` / `filter` | `off` (same pattern as the other two enrichment switches) | S02/F001 |
| `--qualitative` | `off` / `flag` / `filter` | `off` | `screener.py:790` |
| `--fund-weight` | weight given to fundamentals in the ranking points | 1.0 (not quote-checked) | doc-diff N5 |
| `--meta` | `off` / `flag` / `filter`, applies a trained meta-model | `off` (same pattern) | S01/F001 |
| `--meta-model` | path to a trained meta-model pickle | not quote-checked | S01/F001: `screener.py:323` |
| `--out` | output CSV path | `screening_results.csv` | `screener.py:814` |
| `--benchmark` | index used for the regime check and relative strength | not quote-checked | `screener.py:138` (usage) |

Full rule thresholds (13 fundamental rules, 7 anomaly rules, 12 news patterns) are in [04-screen-and-rank.md](04-screen-and-rank.md), not repeated here.

Contradiction: `screener.py:216` passes `min_inst_change` to `FundamentalFilters`, whose fields are `min_fii_change`/`min_dii_change` (`fundamentals.py:99`); `--fundamentals flag` or `filter` is inferred to raise `TypeError` at construction (U02). `fund.industry_pe_map`, called at `screener.py:222`, is defined in no root `*.py` file (U03), so the P/E-vs-industry rule cannot run.

**Outputs**: a CSV file (`screening_results.csv` or `--out`) with one row per candidate plus a `TOTAL` row [S01/F001: `screener.py:393`, `screener.py:391`]. Side files: a cached NSE index list and one dated snapshot per day under the cache directory [S01/F001: `universe.py:156`].

**Success**: prints the ranked candidates and writes the CSV. If no candidate qualifies, prints "No candidates met your rules today." and returns without writing, leaving an existing CSV unchanged [S01/F001: `screener.py:357`].

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| NSE index list cannot be downloaded, no cached copy | exits 1 | `screener.py:70` |
| NSE index list cannot be downloaded, cached copy exists | falls back to cache, prints a warning, continues | `universe.py:162` |
| One symbol's price history cannot be fetched | that symbol is skipped, run continues | `candidate_engine.py:91` |
| Benchmark download fails | regime warning and relative-strength ranking are disabled, run continues | `screener.py:138` |
| `--meta-model` file cannot be loaded | run stops with an error message | `screener.py:323` |
| No candidate passes the rules | prints a message, returns, writes no CSV | `screener.py:357` |

**Security**: not-applicable (local tool, no login or permission check) [S01/F001]. When `--qualitative` uses the Anthropic scorer, the API key is read from `[secret reference: ANTHROPIC_API_KEY]` [S02/F001: `qualitative.py:222`]. The screener.in module states its terms of use do not grant a right to bulk automated access, and this command fetches one page per candidate (U13) [S02/F001: `screener_in.py:16`].

**Example**: `test_ml.py:146` runs `sys.argv = ["screener.py", "screen", "--symbols", *SYMS[:15], "--meta", "filter", "--meta-model", out_pkl, ...]` and asserts the output contains "Meta-model loaded" [S01/F001].

---

## E002: `screener.py backtest`

C05 Backtest the trading rules on history · F002

**Command**: `python screener.py backtest [options]` [S06/F002: `screener.py:817`]

**Inputs**

| Option | Purpose | Default | Evidence |
|---|---|---|---|
| `--strategy` | strategy to simulate | `pullback_trend` (same registry as `screen`) | S06/F002; `strategies.py:278` |
| `--no-costs` | disable the cost model | costs on | S06/F002: `costs.py` `CostModel.zero()` |
| `--no-trailing` | disable the breakeven/swing-low trail | trailing on | S06/F002: `exits.py:27` |
| `--time-stop-days` | calendar days before the time-stop fires, 0 to disable | 14 | S03/F005, shared with monitor: `exits.py:37` |
| `--membership-file` | point-in-time index membership CSV, used only with `--index` | none | S06/F002: `screener.py:407` |
| `--trades-out` | trade log CSV path | `backtest_trades.csv` | `screener.py:820` |
| `--equity-out` | equity curve CSV path | `backtest_equity.csv` | S06/F002 |
| `--risk-pct`, `--reward-risk`, `--heat-ceiling`, `--max-positions` | same meaning as `screen`, and enforced here (unlike `screen`) | same defaults as E001 | `backtester.py:263` |

**Outputs**: `backtest_trades.csv` (or `--trades-out`) and `backtest_equity.csv` (or `--equity-out`); a console summary (win rate, profit factor, expectancy, max drawdown, CAGR, fees, exit-reason counts, skip counts) [S06/F002: `screener.py:436`, `screener.py:437`].

**Success**: walks every trading date with no lookahead, closes anything still open at the final bar with reason `end_of_backtest`, and prints the summary [S06/F002: `backtester.py:221`, `backtester.py:354`].

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| No price data fetched | prints a message, exits 1 | `screener.py:409`, `screener.py:410` |
| A signal cannot be filled (no bar, gap below stop, position-count or heat ceiling reached, undersized, not in the index that day, filter rejection) | counted and skipped by reason, run continues | `backtester.py:241`, `backtester.py:247`, `backtester.py:264` |

**Security**: not-applicable (local tool, no login or permission check) [S06/F002].

**Example**: no test drives this command through its CLI; `test_toolkit.py` drives the `Backtester` class directly and asserts exact exit prices, dates and reasons for crafted price paths, for example `test_toolkit.py:67` - `assert t.exit_date == str(IDX[62].date()) and approx(t.exit_price, 90) and t.exit_reason == "stop", t` [S06/F002]. No test asserts the content of `backtest_trades.csv` or `backtest_equity.csv` themselves.

---

## E003: `screener.py validate`

C06 Validate a backtest (is the result luck?) · F003

**Command**: `python screener.py validate [options]` [S07/F003: `screener.py:824`]

**Inputs**

| Option | Purpose | Default | Evidence |
|---|---|---|---|
| `--split` | in-sample / out-of-sample split fraction or date | S07/F003 | `validation.py:199` (verdict text implies the option) |
| `--sweep` | parameter sweep specification | none | `screener.py:520` |
| `--max-combos` | refuses a sweep larger than this many combinations | 60 | `validation.py:239` |
| `--mc-sims` | Monte Carlo simulation count | S07/F003 | `screener.py:503` |
| `--wf-train-months`, `--wf-test-months` | walk-forward window sizes | S07/F003 | `screener.py:535` |
| `--ablation` | run the ablation table | off | `screener.py:545` |
| `--report` | write a self-contained HTML report | none | `screener.py:550` |
| `--sweep-out` | write the sweep table to a CSV | none | `screener.py:532` |

**Outputs**: console stat tables and plain-English verdicts for up to seven tests (split, calendar-year, regime, Monte Carlo, sweep, walk-forward, ablation). With `--report`, a single offline HTML file with inline SVG charts, no JavaScript or external resources [S07/F003: `report.py:2-3`]. With `--sweep-out`, a CSV of the sweep table.

**Success**: runs the configured backtest once, applies the requested tests, and prints each verdict.

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| Bad `--sweep` or `--split` value | prints `Error: ...`, exits 1 | `screener.py:457`, `screener.py:458` |
| Sweep exceeds `--max-combos` | `ValueError`, caught, exits 1 | `validation.py:239` |
| No usable equity curve | prints a message, returns before the later tests | `screener.py:480` |
| Too few trades for a given test | that test returns a "too few trades" verdict instead of a number | `validation.py:199` |

**Security**: not-applicable (local tool, no login or permission check); the HTML report makes no network call when opened [S07/F003: `report.py:2-3`].

**Example**: `test_validation.py` runs the real `validate` command over synthetic 5-year data with the network monkeypatched (replaced for the test), and asserts the HTML report contains every section and no `<script>` tag or external link: `test_validation.py:83` - `for needle in ("Equity curve", "In-sample vs out-of-sample", "By calendar year", "Monte Carlo", ...)`; `test_validation.py:86` - `assert "<script" not in html and "http://" not in html...` [S07/F003].

---

## E004: `screener.py train-meta`

C08 Filter trades by predicted quality (meta-model) · F004

**Command**: `python screener.py train-meta [options]` [S09/F004: `screener.py:840`]

**Inputs**

| Option | Purpose | Default | Evidence |
|---|---|---|---|
| `--min-train-trades` | minimum dataset rows required to save a model | 100 | `screener.py:571` |
| `--keep-top` | fraction of out-of-sample probabilities kept | 0.5 | S09/F004: `meta_model.py` stored threshold |
| `--label` | `win` (net profit after costs) or `target` (profit target hit) | `win` | `meta_model.py:113` |
| `--wf-train-months`, `--wf-test-months` | walk-forward window sizes | S09/F004 | `screener.py:576` |
| `--meta-out` | model output path | `meta_model.pkl` | S09/F004 |
| `--dataset-out` | optional training dataset CSV | none | `screener.py:569` |
| (period) | history length downloaded | `5y` | `screener.py:843` |

**Outputs**: a pickle model (default `meta_model.pkl`) holding the features, the stored probability threshold, the strategy name, the out-of-sample summary and the calibration method [S09/F004: `meta_model.py:254`]. Optional training-dataset CSV. Console walk-forward table, Brier scores, reliability table and verdict.

**Success**: trains on every signal from an uncapped backtest (capital, position-count and heat limits lifted so setup quality, not capacity, decides inclusion) [S09/F004: `screener.py:564`], validates walk-forward, and saves the model.

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| Dataset has fewer rows than `--min-train-trades` | prints guidance, exits 1, does not save | `screener.py:571`, `screener.py:574` |
| scikit-learn missing | `ImportError`, caught, prints an install hint, exits 1 | `screener.py:577` |
| No fold has enough closed trades | returns a "no usable folds" verdict instead of raising | `meta_model.py:201` |

**Security**: not-applicable (local tool, no login or permission check); the saved model is later loaded with `pickle` by `screen`, a trusted-input assumption rather than an access-control rule [S09/F004].

**Example**: no literal CLI invocation is quoted in the slice. `test_ml.py:112` - `assert "Walk-forward" in text and "Verdict" in text and os.path.exists(out_pkl), text[-1500:]` confirms an end-to-end training run saves the model and prints the expected sections [S09/F004].

---

## E005: `screener.py monitor`

C02 Monitor an open position · F005

**Command**: `python screener.py monitor --stop <price> [options]` [S03/F005: `screener.py:855`]

**Inputs**

| Option | Purpose | Default | Evidence |
|---|---|---|---|
| symbol | the share to check | required | S03/F005 |
| entry price | the price the position was opened at | required | S03/F005 |
| `--stop` | the position's current stop-loss price | required | `screener.py:858` |
| quantity | shares held | required | S03/F005 |
| entry date | when the position was opened | required | S03/F005 |
| target | optional profit target | optional | S03/F005 |
| strategy | which strategy's trend test to apply | optional, same registry as `screen` | S03/F005 |
| time-stop days | days before the time-stop fires | optional, 14 if unset (matches the backtest default) | `exits.py:37` |

**Outputs**: none written to disk. Prints the verdict and reasoning to the console [S03/F005: `screener.py:648`].

**Success**: downloads one year of history, tests trend conditions on the last bar, and returns the first verdict that applies, in order: stop already hit, target already hit, trend broken, time-stop reached, raise the stop, or hold [S03/F005: `monitor.py:84-96`].

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| Any error (no data, bad date, network problem) | caught, printed as `Error: ...`, function returns, process exits 0 (inferred, no `sys.exit` call seen) | `screener.py:635` |

Open question: the "stop already hit" test compares every low since the entry date against the stop value the user types in. After a stop has been raised, this can report "Should already be closed" for a position that was never actually stopped out (U08) [S03/F005: `monitor.py:66`]. Whether `df[df.index >= entry_dt]` works against Yahoo data that carries a time zone is also unresolved (U09).

**Security**: not-applicable (local tool; position details are typed in and not stored; no login or permission check) [S03/F005].

**Example**: no test calls `PositionMonitor` or the `monitor` command. The exit functions it shares with the backtester (`suggest_stop`, `time_stop_hit`) are exercised indirectly through backtest tests, for example `test_toolkit.py:87` - `assert t.exit_reason == "trailing_stop" and approx(t.exit_price, 100) and t.exit_date == str(IDX[64].date()), t` [S03/F005].

---

## E006: `screener.py update-price`

C10 Refresh prices in a results file · F006

**Command**: `python screener.py update-price <file> [--date YYYY-MM-DD]` [S10/F006: `screener.py:867`]

**Inputs**

| Option | Purpose | Default | Evidence |
|---|---|---|---|
| file | an existing `screening_results.csv`-shaped CSV | required | `screener.py:666` |
| `--date` | date label for the new column | today's date | S10/F006: `screener.py:672` |

**Outputs**: overwrites the input file in place, adding or refreshing one column named `price on <date>`; every other cell is read and written back as its exact original text (`dtype=str`, `keep_default_na=False`) [S10/F006: `screener.py:662`, `screener.py:666`, `screener.py:689`]. The `TOTAL` row is skipped when fetching prices [`screener.py:675`].

**Success**: prints "Updated column '<name>' in <file>. No other column was changed." [S10/F006: `screener.py:692`].

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| File does not exist | prints `Error: <file> not found.`, returns | `screener.py:659` |
| File has no `symbol` column | prints an error, returns | `screener.py:668` |
| One symbol's price cannot be fetched | that cell stays blank, a "skipped" note is printed, run continues | `screener.py:685` |

Not traced: whether running `update-price` twice on the same day overwrites that day's column or duplicates it (N4, doc-diff).

**Security**: not-applicable (local tool, no login or permission check) [S10/F006].

**Example**: no test drives this command. Search boundary: `update-price|cmd_update_price|price on ` across all `test_*.py` files at the repository root, no match [S10/F006].

---

## E007: `screener.py snapshot-changes`

C09 Rebuild index membership history · F007

**Command**: `python screener.py snapshot-changes [--index NAME] [--out FILE]` [S10/F007: `screener.py:872`]

**Inputs**

| Option | Purpose | Default | Evidence |
|---|---|---|---|
| `--index` | which index's saved snapshots to diff | S10/F007 | `screener.py:611` |
| `--out` | index-changes CSV to append to | `index_changes.csv` | S10/F007 |

**Outputs**: appends new ADD/REMOVE rows to the index-changes CSV, creating it with a header comment if it does not exist; only rows not already present are added, so re-running adds nothing twice [S10/F007: `membership.py:147`, `membership.py:150`]. Prints how many changes were seen and how many were new [`screener.py:617`].

**Success**: diffs consecutive dated constituent snapshots that `universe.py` already saved (from running `screen` or `backtest` with `--index`), and writes the ADD/REMOVE rows.

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| Fewer than two snapshots on different days | prints an explanatory message, returns without writing | `screener.py:612`, `screener.py:613` |

**Security**: not-applicable (local tool, reads only local snapshot files, no network, no login or permission check) [S10/F007].

**Example**: `test_membership.py:111` - `assert ch == [(D(2026, 4, 2), "DDD", "ADD"), (D(2026, 4, 2), "CCC", "REMOVE")], ch` and `test_membership.py:113` - `assert mb.merge_changes_file(out, ch) == 2 and mb.merge_changes_file(out, ch) == 0`, driving the underlying `changes_from_snapshots` and `merge_changes_file` functions directly rather than the CLI wrapper [S10/F007].

---

## E008: `holdings_analysis.py`

C03 Analyse existing holdings · F008

**Command**: `python holdings_analysis.py <file> [options]` [S04/F008: `holdings_analysis.py:386`, `holdings_analysis.py:387`]

**Inputs**

| Option | Purpose | Default | Evidence |
|---|---|---|---|
| file | the `*_holdings.xls` file written by E009 | required | `holdings_analysis.py:387` |
| `--symbol-map` | user-supplied ISIN-to-symbol overrides, tried before the NSE list | none | `holdings_analysis.py:140` |
| `--max-weight` | flag a single holding above this % of the portfolio | 25.0 | `holdings_analysis.py:424` |
| `--max-sector-weight` | flag a sector above this % of the portfolio | 40.0 | `holdings_analysis.py:425` |
| `--skip-fundamentals` | turn off the fundamentals check | fundamentals on | `holdings_analysis.py:298` |
| `--min-promoter` | minimum promoter holding threshold passed to `FundamentalFilters` | S04/F008 | `holdings_analysis.py:302` |
| `--max-pledge` | maximum pledge threshold passed to `FundamentalFilters` | S04/F008 | `holdings_analysis.py:302` |
| `--industry-pe` | enables the P/E-vs-industry rule, which calls the missing `fund.industry_pe_map` (U03) | off | `holdings_analysis.py:306` |
| `--out` | output workbook path | `<input>_analysis.xlsx` | `holdings_analysis.py:452` |

**Outputs**: `<input>_analysis.xlsx` with sheets Summary, Holdings analysis, Not analysed and Governance flags [S04/F008: `holdings_analysis.py:452`, `holdings_analysis.py:455`]. Falls back to a CSV file if `openpyxl` is missing [`holdings_analysis.py:463`]. Downloads the NSE equity list into a local cache; if `fundamental_weights.csv` is missing, writes a template file [`fund_weights.py:64`].

**Success**: maps each ISIN to an NSE symbol, analyses each holding (trend state, stop, fundamentals, news, anomaly level), runs the portfolio-level flags, and writes the workbook.

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| A holding raises an error during analysis | printed as FAILED, listed on the "Not analysed" sheet, run continues | `holdings_analysis.py:322` |
| No holding could be analysed | `sys.exit("Nothing could be analysed.")` | `holdings_analysis.py:437` |
| NSE equity list cannot be downloaded | warning printed, falls back to a cached copy or the built-in list | `holdings_analysis.py:110` |

**Security**: observed. The input and output both carry personal financial data: ISINs, quantities, values, and demat (DP) account names [S04/F008: `holdings_analysis.py:173`]. The source code embeds a built-in table of the owner's own ISINs [`holdings_analysis.py:51`]. The output workbook has no password or encryption option. Whether this repository is private is unresolved (U12).

**Example**: no test imports or runs this file. Search boundary: `holdings_analysis` across all `test_*.py` files at the repository root, no match [S04/F008].

---

## E009: `cdsl_holdings_to_xls.py`

C04 Convert a CDSL account statement to Excel · F009

**Command**: `python cdsl_holdings_to_xls.py <pdf> [--output NAME] [--password PWD] [--pages RANGE] [--dpi N] [--force-ocr] [--workers N] [--skip-mf]` [S05/F009: `cdsl_holdings_to_xls.py:1107`, `cdsl_holdings_to_xls.py:1109`]

**Inputs**

| Option | Purpose | Default | Evidence |
|---|---|---|---|
| pdf | the CDSL CAS statement | required | `cdsl_holdings_to_xls.py:1109` |
| `--password` | PDF password (the owner's PAN in capitals) | none | `cdsl_holdings_to_xls.py:1115` |
| `--output` | stock-holdings output path | `<pdf>_holdings.xls` | `cdsl_holdings_to_xls.py:1126` |
| `--skip-mf` | skip the mutual-fund workbook | off (mutual funds included) | `cdsl_holdings_to_xls.py:1153` |
| `--pages`, `--dpi`, `--force-ocr`, `--workers` | page range, OCR (optical character recognition: turning an image of text into text) resolution, force OCR even when a text layer exists, worker count | S05/F009 | `cdsl_holdings_to_xls.py:1135` |

**Outputs**: `<pdf>_holdings.xls` and, unless `--skip-mf`, `<pdf>-MF.XLS` [S05/F009: `cdsl_holdings_to_xls.py:1126`, `cdsl_holdings_to_xls.py:1133`]. Each workbook has a "Reconciliation" sheet; rows with a problem are shaded yellow [`cdsl_holdings_to_xls.py:954`]. An existing output file with the same name is overwritten without warning (no `os.path.exists` check found) [S05/F009].

**Success**: extracts stock rows, reconciles totals against the printed statement, writes the holdings workbook, then (unless skipped) does the same for mutual funds.

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| No holding rows found | `sys.exit("No holding rows were found. Try --force-ocr, a higher --dpi, or --pages.")` | `cdsl_holdings_to_xls.py:624` |
| `xlwt` or `pytesseract` missing | `sys.exit` with an install message | `cdsl_holdings_to_xls.py:940` |
| No mutual fund table found | prints a message, finishes after the stock file | S05/F009 |
| Row arithmetic (qty x price, units x NAV) does not match within tolerance | row flagged in the "Check" column, run continues | `cdsl_holdings_to_xls.py:464`, `cdsl_holdings_to_xls.py:793` |
| Wrong PDF password | unhandled; the `pdfplumber.open(..., password=...)` call is not wrapped in a `try`/`except` | `cdsl_holdings_to_xls.py:579` |

Flagged rows are not excluded from E008's analysis, since `holdings_analysis.py` never reads the "Check" column (U11).

**Security**: observed. The password is the owner's tax ID (PAN), passed as a command-line option, which can remain in shell history and be visible in the process list [S05/F009: `cdsl_holdings_to_xls.py:1115`]. The output workbooks hold holdings, quantities, values and demat account names with no protection. `pdfplumber` and `xlwt` are not listed in `requirements.txt`; the module's own usage text names them as separate installs [`cdsl_holdings_to_xls.py:36`].

**Example**: no test touches this file. The repository holds no sample statement [S05/F009].

---

## E010: `gov_classifier.py train`

C07 Check companies for red flags · F010

**Command**: `python gov_classifier.py train [options]`, calling `train(a.labels, a.out, a.embedder, use_seed=not a.no_seed)` [S08/F010: `gov_classifier.py:281`, `gov_classifier.py:298`]

**Inputs**

| Parameter | Purpose | Default | Evidence |
|---|---|---|---|
| labels | CSV of reviewed (flag, text, label) rows | required | `gov_classifier.py:298` |
| out | model output pickle path | `gov_model.pkl` | S08/F010 |
| embedder | use Hugging Face sentence embeddings instead of TF-IDF | off (TF-IDF) | `gov_classifier.py:150`, `gov_classifier.py:222` |
| no-seed | exclude the built-in seed set | seed set included | `gov_classifier.py:232` |

**Outputs**: a pickle model, default `gov_model.pkl` [S08/F010: `gov_classifier.py:272`, `gov_classifier.py:201`]. Prints the cross-validated AUC and the false-positive / genuine-demoted counts.

**Success**: needs at least 30 labelled rows with at least 8 of each class; cross-validates, fits on all rows, and saves the model [S08/F010: `gov_classifier.py:239`].

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| Fewer than 30 rows, or fewer than 8 of a class | `ValueError`, caught, printed as `Error:` | `gov_classifier.py:240`, `gov_classifier.py:305` |
| scikit-learn missing | `ImportError`, caught, printed as `Error:` | `gov_classifier.py:305` |
| Prediction-time model error (at apply time, not training) | swallowed; flag gets a `model error` note and is returned unchanged | `gov_classifier.py:190`, `gov_classifier.py:191` |

**Security**: not-applicable (local tool, no login or permission check). The saved model is later loaded with `pickle`, which executes arbitrary code from the file; this is a trusted-input assumption (the owner's own model), not an access-control rule [S08/F010].

**Example**: `test_ml.py:32` - `gm = gc.train(os.path.join(TMP, "none.csv"), model_path, log=lambda *a: None)`, trained from the seed set alone, with `test_ml.py:37` - `assert p_fp < p_ok, (p_fp, p_ok)` confirming a known false positive scores lower than a genuine flag [S08/F010]. The `--embedder` path is not exercised by any test.

---

## E011: `gov_classifier.py import-sheet`

C07 Check companies for red flags · F011

**Command**: `python gov_classifier.py import-sheet <xlsx> [options]`, calling `import_sheet(a.xlsx, a.labels, a.sheet)` [S08/F011: `gov_classifier.py:287`, `gov_classifier.py:300`]

**Inputs**

| Parameter | Purpose | Default | Evidence |
|---|---|---|---|
| xlsx | a holdings-analysis workbook (E008 output) | required | `gov_classifier.py:300` |
| labels | labels CSV to append to | `governance_labels.csv` | S08/F011 |
| sheet | sheet name to read | `Governance flags` | `gov_classifier.py:114` |

**Outputs**: appends new labelled rows to the labels CSV, creating it with a header if it does not exist [S08/F011: `gov_classifier.py:131`, `gov_classifier.py:130`]. Returns and prints the count of rows added.

**Success**: a row is added only when it has a non-blank flag, a non-blank text, a recognised label, and is not already present [S08/F011: `gov_classifier.py:126`].

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| Sheet is missing a `flag`, `text` or `label` column | `ValueError`, caught, printed as `Error:` | `gov_classifier.py:120` |

**Security**: not-applicable (local tool reading a workbook the owner produced) [S08/F011].

**Example**: `test_ml.py:62` - `assert gc.import_sheet(xl, lab) == 2 and gc.import_sheet(xl, lab) == 0 and len(gc.load_labels(lab)) == 2`, confirming the first import adds 2 rows and a repeat import adds 0 [S08/F011]. The accepted label spellings in `_norm_label` (1/0, yes/no, genuine/false-positive) and the missing-column error are not separately asserted.

---

## E012: `gov_classifier.py predict`

C07 Check companies for red flags · F012

**Command**: `python gov_classifier.py predict "<text>" --flag <type> [--model PATH]` [S08/F012: `gov_classifier.py:291`]

**Inputs**

| Parameter | Purpose | Default | Evidence |
|---|---|---|---|
| text | the headline or filing line to score | required | S08/F012 |
| `--flag` | the flag type (rule name) the text relates to | required | `gov_classifier.py:304` |
| `--model` | path to the trained pickle | S08/F012 | `gov_classifier.py:303` |

**Outputs**: none written. Prints `P(genuine) = <probability> (demoted below <cutoff>)` [S08/F012: `gov_classifier.py:304`].

**Success**: loads the pickled model and returns the probability that the given flag and text describe a genuine concern; makes no change to any file.

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| Model file missing or unreadable | `OSError` (or an import/value error), caught, `sys.exit(f"Error: {e}")` | `gov_classifier.py:305`, `gov_classifier.py:306` |

**Security**: not-applicable; reads only the local pickle file, same trusted-input assumption as E010 [S08/F012].

**Example**: the underlying `prob` method the CLI calls is tested directly: `test_ml.py:35` - `p_fp = gm.prob("rating_downgrade", "Nomura cuts rating on Siemens to neutral, trims target price")` [S08/F012]. The `predict` CLI branch and its printed line are not driven by any test.

---

## E013: `real_data_check.py`

C06 Validate a backtest (is the result luck?) · F013

**Command**: `python real_data_check.py [--quick] [--check-only] [--dry-run] [--out-dir DIR] [--strategy NAME]` [S07/F013: `real_data_check.py:60`, `real_data_check.py:61`]

**Inputs**

| Option | Purpose | Default | Evidence |
|---|---|---|---|
| `--quick` | smaller sweep set (`reward_risk` only) for a faster first run | full sweep set | `real_data_check.py:83`, `real_data_check.py:42` |
| `--check-only` | exit after the connectivity check | off | `real_data_check.py:74` |
| `--dry-run` | print the commands without running them | off | S07/F013 |
| `--out-dir` | output folder | `real_check_<YYYYMMDD_HHMM>/` next to the script | `real_data_check.py:82` |

**Outputs**: a dated folder with `summary_<strategy>.txt` per strategy (written by this script) plus `validation_report_<strategy>.html` and `validation_sweep_<strategy>.csv` (written by the child `validate` process) [S07/F013: `real_data_check.py:82`, `real_data_check.py:100`].

**Success**: checks Yahoo Finance and the NSE archive are reachable, then for each strategy (default both) runs `screener.py validate --ablation --report --sweep-out` as a subprocess and streams its output to console and to the summary file [S07/F013: `real_data_check.py:88`, `real_data_check.py:101`].

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| Yahoo Finance unreachable, not a dry run | prints a message, exits 1 | `real_data_check.py:80` |
| NSE archive unreachable | not fatal; the last cached index list can be used | `real_data_check.py:57` |
| A strategy's subprocess exits non-zero | prints a message pointing to its summary file, continues with the next strategy | `real_data_check.py:106`, `real_data_check.py:107` |

**Security**: not-applicable (local tool, no login or permission check); spawns `screener.py` as a subprocess with `sys.executable`, a fixed path and controlled arguments [S07/F013].

**Example**: no offline test drives this script; it needs live internet by design. Search boundary: `real_data_check|real_check|check-only|SWEEPS_FULL|reachable` across all `test_*.py` files at the repository root, no match (U16) [S07/F013].

---

## E014: `anomaly.py`

C07 Check companies for red flags · F014

**Command**: `python anomaly.py SYMBOL [SYMBOL ...]` [S08/F014: `anomaly.py:257`, `anomaly.py:249`]

**Inputs**

| Parameter | Purpose | Default | Evidence |
|---|---|---|---|
| SYMBOL (one or more) | companies to analyse together as peers | required | `anomaly.py:249` |

**Outputs**: none written when run standalone. Prints one line per symbol with its anomaly level and flags [S08/F014: `anomaly.py:252`]. The same `analyse_many` function is also called from E001's `--anomalies` option and from E008, where it annotates each candidate or holding with `anomaly_level`/`anomaly_flags` columns instead of printing [`screener.py:266`, `screener.py:268`].

**Success**: fetches screener.in statements for each symbol, applies seven threshold rules, and (with 8+ companies) adds peer z-scores, or (with 30+) an Isolation Forest outlier score. Levels: High (2+ rule flags), Watch (1 flag, a peer outlier, or top-5% Isolation Forest score), None [S08/F014: `anomaly.py:199`, `anomaly.py:200`].

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| Statements unreadable, or fewer than 4 annual columns | level `n/a` with the error in a note; never raises | `anomaly.py:222`, `anomaly.py:219` |
| Bank or NBFC | level `n/a` (ratios do not apply) | `anomaly.py:212` |
| Missing input metric | treated as unknown, never flagged | S08/F014 |

**Security**: not-applicable (local tool, no login or permission check) [S08/F014].

**Example**: the CLI prints one line per symbol, but the tests exercise the underlying `analyse_many` function directly: `test_ml.py:233` - `assert res["BAD"]["anomaly_level"] == "High" and res["BAD"]["anomaly_iso_pct"] >= 95, res["BAD"]`, over 45 synthetic peer companies plus one planted outlier [S08/F014].

---

## E015: `diagnose_dump.py`

C11 Diagnose data-source problems · F015

**Command**: `python diagnose_dump.py [folder] [SYMBOL ...]` [S11/F015: `diagnose_dump.py:83-85`]

**Inputs**

| Parameter | Purpose | Default | Evidence |
|---|---|---|---|
| folder | directory of saved debug dump files to summarise | `dump` | `diagnose_dump.py:83-84` |
| SYMBOL (extra args) | symbols to show in full detail | none (first 2 HTML and first 1 of each NSE type shown by default) | `diagnose_dump.py:85`, `diagnose_dump.py:96`, `diagnose_dump.py:100` |

**Outputs**: console only. No files are written and no network requests are made [S11/F015].

**Success**: dispatches each file in the folder by name prefix, `screener_*.html` to the screener.in page parser and `nse_*.json` to the matching NSE JSON parser, and prints a one-line summary of what each parser found [S11/F015: `diagnose_dump.py:94-98`].

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| Folder is empty | `sys.exit(f"nothing in {folder}")` | `diagnose_dump.py:87-88` |
| A single file raises an exception during analysis | error printed, processing continues to the next file | `diagnose_dump.py:101-102` |

**Security**: not-applicable. Reads only local dump files and prints summaries; no credentials, no network, no personal data beyond what the dump files already contain [S11/F015].

**Example**: no test drives this script. Search boundary: `diagnose_dump` across all repository files, no match outside the script itself [S11/F015].

---

## E016: `fetch_xbrl_sample.py`

C11 Diagnose data-source problems · F016

**Command**: `python fetch_xbrl_sample.py [SYMBOL ...]` [S11/F016: `fetch_xbrl_sample.py:19`]

**Inputs**

| Parameter | Purpose | Default | Evidence |
|---|---|---|---|
| SYMBOL (one or more) | symbols to fetch a sample shareholding filing for | `VEDL` | `fetch_xbrl_sample.py:19` |

**Outputs**: one XML file per symbol under `dump_xbrl/<SYMBOL>_<date>.xml` [S11/F016: `fetch_xbrl_sample.py:20`, `fetch_xbrl_sample.py:44-45`]. Prints up to 25 distinct (tag, value) pairs whose XML tag name contains "pledg" or "encumb" [`fetch_xbrl_sample.py:47`, `fetch_xbrl_sample.py:52`].

**Success**: fetches NSE shareholding records for each symbol, picks the latest by date, downloads the linked XBRL filing, and lists its pledge/encumbrance tags.

**Error cases**

| Condition | Result | Evidence |
|---|---|---|
| Shareholding fetch fails | error printed, symbol skipped | `fetch_xbrl_sample.py:24-25` |
| No shareholding records for the symbol | message printed, symbol skipped | `fetch_xbrl_sample.py:28-29` |
| XBRL download fails | error printed, symbol skipped | `fetch_xbrl_sample.py:39-40` |

**Security**: inferred. Makes HTTP requests to NSE's public site and archives using a browser-like session from `nse_client._sess()`; no credentials are sent beyond session cookies obtained from the NSE home page. Downloaded filings are public regulatory documents [S11/F016: `fetch_xbrl_sample.py:38`, `nse_client.py:48-54`]. The direct `_sess().get()` call bypasses `nse_client`'s own rate limiting and 401/403 retry logic [`nse_client.py:60-61`].

**Example**: no test references this script. Search boundary: `fetch_xbrl` across all repository files, no match outside the script itself [S11/F016].

---

## Unknowns and next probes

| ID | Question | Entry points affected | Next probe |
|---|---|---|---|
| U01 | The 6 test files have no `def test_*` functions; does pytest collect and report them, and do they pass? | all entries whose test result above depends on these files | Run the tests in a sandbox |
| U02 | Does `screen --fundamentals flag` crash because `min_inst_change` is not a `FundamentalFilters` field? | E001 | Run the command in a sandbox; ask the developer |
| U03 | Where is `fund.industry_pe_map` defined? Called but not found. | E001, E008 | `git log -S industry_pe_map`; ask the developer |
| U04 | Does `test_screen_enrich.py` pass against this code? | E001 | Run the test; ask the developer |
| U05 | Does `test_sources.py` pass against this code? | E001 (enrichment path) | Run the test; ask the developer |
| U06 | Which files are current: the CLI modules or the two drifted tests? | E001 | `git log --oneline` per file; ask the developer |
| U07 | Is it intended that `screen` accepts `--heat-ceiling`/`--max-positions` but never checks them? | E001 | Ask the product owner |
| U08 | Is it intended that `monitor`'s stop-touched test uses lows from before a stop was raised? | E005 | Ask the developer or owner |
| U09 | Does the entry-date comparison in `monitor` work against Yahoo data that carries a time zone? | E005 | Run on a real symbol in a sandbox |
| U10 | Is `xlrd` (needed to read `.xls` with pandas) actually installed? It is in no requirements file. | E008 | Ask the developer which packages are installed |
| U11 | Should rows the converter flags "Check" be excluded or marked in the holdings analysis? | E008, E009 | Ask the product owner |
| U12 | Is the repository private? It embeds the owner's ISIN list and takes a tax-ID password on the command line. | E008, E009 | Ask the product owner or security |
| U13 | Does the owner accept the screener.in terms-of-use warning against bulk automated access? | E001, E008 | Ask the product owner |
| U15 | How accurate is the CDSL converter on real statements, especially scanned ones? | E009 | Ask for a redacted sample or a past "Reconciliation" sheet |
| U16 | Does `real_data_check.py` produce sensible numbers end to end on real data? | E013 | Run `--quick` or `--check-only` with normal internet |
| N2 | `--min-turnover-cr` default (1.0 Crore) is from the README, not quote-checked against the parser | E001 | Read the `add_argument` line for `--min-turnover-cr` |
| N3 | `--max-from-high-pct` default (20) is from the README, not quote-checked | E001 | Read the `add_argument` line |
| N4 | Does running `update-price` twice the same day overwrite or duplicate the column? | E006 | Trace the column-write path for a repeat run |
| N5 | `--fund-weight` default (1.0) is from the README, not quote-checked | E001 | Read the `add_argument` line |
| N8 | `--index` default (`nifty50`) is from the README, not quote-checked | E001 | Read the `add_argument` line |

## Related documents

- [01-overview.md](01-overview.md): capabilities table and system context for all 16 entry points.
- [02-module-architecture.md](02-module-architecture.md): which modules each entry point's command delegates to.
- [03-request-to-response-flow.md](03-request-to-response-flow.md): the full main/alternative/exception flow behind each command, by capability.
- [04-screen-and-rank.md](04-screen-and-rank.md): the full rule thresholds for E001 (`screen`), not repeated in this document.
- [07-error-handling-and-observability.md](07-error-handling-and-observability.md): error and exit-code patterns across entry points.
- [09-test-exposure-map.md](09-test-exposure-map.md): test coverage detail per flow.
