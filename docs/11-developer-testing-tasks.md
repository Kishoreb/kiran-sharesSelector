# Developer testing tasks

Audience: a developer deciding where to add tests next, ranked so the riskiest gaps close first.

Evidence: 16 of 16 entry points read · 5 capabilities · 13 open unknowns relevant to this document · commit b472b9b · Surveyor 2.2.0 · 2026-10-25

---

The five tasks below come from the risk ranking in [10-test-review.md](10-test-review.md), highest risk first. Each targets a capability that is either High importance with a real test gap, or Medium importance with zero tests.

Every task in this document proposes a new test written in the same style as the six that already exist: a plain Python script with top-level `assert` statements, run with `python <file>` (the convention stated in `test_validation.py:5` and used by all six current test files [inventory "Tests" table]). Whether pytest collects and reports these scripts, and whether a failure partway through one hides every later check in that file, is still open (U01) [10-test-review.md "Level-of-test problems"]. That question applies to every task here as much as it does to the existing suite: a new test written this way is exposed to the same unresolved collection question until U01 is answered.

## Task 1: Resolve and test the `--fundamentals` enrichment path (C01, High importance)

Risk: `screener.py:216` passes `min_inst_change` to `FundamentalFilters`, which defines `min_fii_change` and `min_dii_change` instead [S02/F001: `fundamentals.py:99`]; `screener.py:222` calls `fund.industry_pe_map`, which no root `*.py` file defines [S02/F001]. The two test files that cover this path, `test_screen_enrich.py` and `test_sources.py`, call command options and a function name the current code also does not have [S01/F001: `test_screen_enrich.py:107`; S02/F001: `test_sources.py:105`]. This is capability C01's enrichment path, ranked risk 1 in [10-test-review.md](10-test-review.md) because it is inferred to be unable to run at all, not merely undertested.

Target files: `screener.py` (lines 216, 222), `fundamentals.py` (lines 99-100), `screener_in.py`, `test_screen_enrich.py`, `test_sources.py`.

What to assert:
- Whether constructing `FundamentalFilters` the way `screener.py:216` does raises an error.
- Whether `fund.industry_pe_map` exists anywhere in the project's history, or needs to be written.
- Once the above is settled: that `screen --fundamentals flag` runs end to end on a small synthetic candidate and adds the correct fundamentals columns and status, not just that it completes.

Steps:
1. Settle U06 first: run `git log --oneline -- screener.py candidate_engine.py screener_in.py fundamentals.py` to see whether the enrichment modules or the screen/screener_in modules changed more recently, or ask the developer directly.
2. Settle U02: build a `FundamentalFilters` the way `screener.py:216` does, in a throwaway script or the Python REPL, and record whether it raises `TypeError` for the unknown `min_inst_change` argument.
3. Settle U03: search the full git history for `industry_pe_map` (`git log -S industry_pe_map`) to find where it was defined or removed.
4. Depending on what steps 1 to 3 show, either fix `screener.py` and `screener_in.py` to match the names `fundamentals.py` and the tests expect, or fix `test_screen_enrich.py` and `test_sources.py` to match the current production names. Do not change both sides to agree by guesswork.
5. Add one new assert-based check to `test_screen_enrich.py` that runs `screen --fundamentals flag` on a small, hand-built candidate set and asserts the specific fundamentals status and columns that result, following the existing pattern of asserting an exact value rather than that the run completed [10-test-review.md "Strengths"].

Done-when:
- [ ] U02, U03 and U06 have recorded answers (or a developer decision) in `open-questions.md`
- [ ] `screen --fundamentals flag` and `screen --fundamentals filter` both run without raising, on at least one symbol
- [ ] `test_screen_enrich.py` and `test_sources.py` call only option names and functions that exist in the current tree
- [ ] The new assertion checks fundamentals values on a known candidate, not only that the command printed something

This task does not resolve U04 or U05 (whether the two existing test files pass once the names are reconciled) until step 4 is complete, or U07 (whether ignoring the portfolio heat ceiling in `screen` is intended), which is a product decision, not a test gap.

## Task 2: Add direct tests for the holdings-analysis pure functions (C03, High importance)

Risk: no test imports or runs `holdings_analysis.py`; a search for `holdings_analysis` in all `test_*.py` files at the repository root found no match [S04/F008]. This runs the toolkit's rules over the owner's real portfolio, ranked risk 2 in [10-test-review.md](10-test-review.md) because the gap is total and sits on the capability's main flow, not an option.

Target files: `holdings_analysis.py` (the `trend_state`, `verdict` and `add_portfolio_flags` functions, read whole in S04).

What to assert:
- `trend_state` returns "Intact" when all four trend tests are true, "Broken" when the position is below both the 50-day and 200-day averages, and "Weakening" otherwise [S04/F008: `holdings_analysis.py:164`, `holdings_analysis.py:166`].
- `verdict` appends "weak fundamentals" and "governance flag" text under the conditions that trigger them [S04/F008: `holdings_analysis.py:277`].
- `add_portfolio_flags` flags a holding over 25% of portfolio value, a sector over 40%, a position over 5% of a day's traded value, and a price move of more than 25% since the statement [S04/F008: `holdings_analysis.py:424`, `holdings_analysis.py:425`, `holdings_analysis.py:354`, `holdings_analysis.py:362`].

Steps:
1. Create a new test file, `test_holdings_analysis.py`, following the top-level-assert style of the other six test files [inventory "Tests" table].
2. Import `trend_state`, `verdict` and `add_portfolio_flags` from `holdings_analysis`.
3. Before writing assertions, read `holdings_analysis.py` around lines 160-170, 270-280 and 340-365 to confirm the exact input shape each function expects (the slice evidence confirms the decision logic and the named local variables `above50`, `above200`, `rising50`, `known`, `pt`, but not the full function signatures, since Surveyor reads in slices and does not cite unread lines).
4. Build hand-crafted inputs for each of the three trend_state outcomes and assert the exact string returned, following the same known-answer pattern `test_toolkit.py` uses for the backtester [10-test-review.md "Strengths": `test_toolkit.py:67`].
5. Build one holding that should trigger each portfolio flag and one that should not, and assert both outcomes, so the test also proves a non-flagged case stays clean.
6. Leave the network-dependent parts of F008 (NSE symbol resolution, price download) for a later task, or monkeypatch `fetch_history` the way `test_validation.py:37` monkeypatches `screener.fetch_history` [S07/F003].

Done-when:
- [ ] `test_holdings_analysis.py` exists and runs with `python test_holdings_analysis.py`
- [ ] All three `trend_state` outcomes are asserted against known inputs
- [ ] `verdict`'s "weak fundamentals" and "governance flag" text is asserted under the triggering condition and absent otherwise
- [ ] Each of the four `add_portfolio_flags` thresholds has a passing and a non-triggering case asserted

This task does not resolve U10 (whether `xlrd` is installed to open the converter's `.xls` output) [S04/F008], since the pure functions above take already-loaded data and do not call `pd.read_excel` themselves.

## Task 3: Test the `monitor` verdict ladder directly (C02, High importance)

Risk: no test calls `PositionMonitor` or the `monitor` command; the verdict order itself, `monitor.py:84-96`, has no test [S03/F005]. This is the capability that tells the owner whether to keep holding a position already bought, ranked risk 3 in [10-test-review.md](10-test-review.md), with two open correctness questions on top of the missing test.

Target files: `monitor.py` (the `PositionMonitor.check` method and the verdict order at lines 84-96).

What to assert:
- Each of the five verdict branches fires on a price path built to trigger exactly that branch and no other: stop already hit, trend broken, time-stop reached, raise the stop, and hold [S03/F005: `monitor.py:84`, `monitor.py:88`, `monitor.py:91`, `monitor.py:93`, `monitor.py:96`].
- The current behaviour when a stop has been raised: whether a price low from before the raise, now below the new stop, still produces "Should already be closed" (U08) [S03/F005: `monitor.py:66`].
- Whether a timezone-aware price index, as real Yahoo data may return, makes `df[df.index >= entry_dt]` raise (U09) [S03/F005: `monitor.py:65`].

Steps:
1. Add a new test file, `test_monitor.py`, or a new section in `test_toolkit.py` (it already imports the same strategy and exit code `monitor.py` shares [S03/F005: `backtester.py:46`]).
2. Build a synthetic price `DataFrame` the same way `test_toolkit.py` does for the backtester, and call `PositionMonitor.check` directly rather than through the command line, so the verdict ladder is tested without going through `screener.py`'s argument parsing.
3. Write one price path per verdict branch, each constructed to trigger only that branch, and assert the exact verdict string `monitor.py:84-96` returns.
4. Add the case that settles U08: a price path whose low fell below a stop value lower than the one passed in, to record whether `check` reports "Should already be closed" for a position that was never actually stopped out at the original level.
5. Add a case using a `DatetimeIndex` with a timezone attached, and assert whether `monitor.py:65`'s comparison raises or runs, to settle U09.
6. Record the result of steps 4 and 5 as the current, tested behaviour. Whether that behaviour is the intended one is still a question for the developer or owner (U08), not something a test can decide.

Done-when:
- [ ] `PositionMonitor.check` is called directly in a test for each of the five verdict branches, with the exact verdict string asserted
- [ ] A raised-stop scenario is tested and its current result recorded as a comment or assertion either way
- [ ] A timezone-aware index case is tested and its result recorded either way

This task settles what the code currently does for U08 and U09, but not whether that behaviour is correct; both stay open for a developer or the owner to decide.

## Task 4: Add direct tests for the CDSL converter's checksum and arithmetic checks (C04, Medium importance)

Risk: no test touches `cdsl_holdings_to_xls.py`; a search for `cdsl_holdings|isin_checksum_ok|choose_isin|extract_mf` in all `test_*.py` files found no match, and the repository holds no sample statement to test against [S05/F009]. Ranked risk 4 in [10-test-review.md](10-test-review.md): the file handles the owner's tax-ID password and real holdings data with no automated check at all.

Target files: `cdsl_holdings_to_xls.py` (`isin_checksum_ok`, `choose_isin`, the stock-row arithmetic check, and `reconcile`).

What to assert:
- `isin_checksum_ok` returns true for a valid ISIN and false for one with an altered check digit [S05/F009: `cdsl_holdings_to_xls.py:159`].
- `choose_isin` corrects an OCR look-alike character (optical character recognition: turning an image of text into text) only when the correction makes the checksum pass, and leaves a correctly-read ISIN unchanged [S05/F009: `cdsl_holdings_to_xls.py:103`].
- A stock row where quantity times price equals value within 0.02 rupees passes, and one further off is flagged "CHECK: qty x price does not equal value" [S05/F009: `cdsl_holdings_to_xls.py:464`, `cdsl_holdings_to_xls.py:468`].
- `reconcile`'s total-matching tolerance of 0.5 rupees: a total within tolerance reports "MATCHES statement", one outside it does not [S05/F009: `cdsl_holdings_to_xls.py:652`].

Steps:
1. Create `test_cdsl_holdings_to_xls.py`, following the same top-level-assert convention as the other six test files.
2. Import `isin_checksum_ok`, `choose_isin` and `reconcile` from `cdsl_holdings_to_xls`; read the surrounding lines of each (around `cdsl_holdings_to_xls.py:100-180`, `:460-470` and `:640-655`) to confirm each function's exact input shape before writing assertions, since these are pure functions that need no PDF.
3. Assert `isin_checksum_ok` on one known-valid ISIN and one with the last digit changed.
4. Assert `choose_isin` repairs a look-alike character only when the repaired string passes the checksum, and passes through text that is already correct.
5. Assert the row-arithmetic check on a passing triple and a failing triple.
6. Assert `reconcile` on a total 0.4 rupees off (should match) and one 0.6 rupees off (should not).

Done-when:
- [ ] `test_cdsl_holdings_to_xls.py` exists and runs without opening any PDF file
- [ ] `isin_checksum_ok` has a passing and a failing case asserted
- [ ] `choose_isin` has a case where it corrects text and a case where it leaves text unchanged
- [ ] The row-arithmetic check and `reconcile` each have a passing and a failing case asserted

This task does not close U15 (how accurate the converter is on real, especially scanned, statements): that still needs a redacted real sample from the owner, since reading the code cannot judge OCR accuracy [S05/F009]. It also does not close U11 (whether holdings analysis should treat "Check"-flagged rows differently) [S04/F008, S05/F009], which is a product decision.

## Task 5: Make the real-data validation wrapper testable offline (C06, Medium importance)

Risk: no test drives `real_data_check.py`; a search for `real_data_check|real_check|check-only|SWEEPS_FULL|reachable` in all `test_*.py` files found no match [S07/F013]. Ranked risk 5 in [10-test-review.md](10-test-review.md): this is the one path meant to catch a broken real-data case before the owner trusts a backtest, and it has no automated test at all.

Target files: `real_data_check.py` (the `reachable` connectivity check, the `SWEEPS_QUICK`/`SWEEPS_FULL` selection, and the `--check-only`/`--dry-run` short-circuits).

What to assert:
- `--quick` selects a sweep set limited to `reward_risk` values, matching `SWEEPS_QUICK` [S07/F013: `real_data_check.py:42`, `real_data_check.py:83`].
- `--check-only` stops after the connectivity check and does not start a subprocess [S07/F013: `real_data_check.py:74`, `real_data_check.py:101`].
- `--dry-run` prints the commands it would run and does not start a subprocess either.
- When Yahoo is reported unreachable and it is not a dry run, the script exits with code 1 [S07/F013: `real_data_check.py:80`].

Steps:
1. Create `test_real_data_check.py`.
2. Monkeypatch the `reachable` function (the one each entry of `CHECKS` is passed into at `real_data_check.py:74`) so the connectivity result can be forced true or false without a real network call, the same way `test_validation.py:37` monkeypatches `screener.fetch_history` for the `validate` command [S07/F003].
3. Assert that with `--quick`, the sweep dictionary passed toward the `validate` subprocess command matches `SWEEPS_QUICK`'s shape (`reward_risk` only), not `SWEEPS_FULL`.
4. Assert that `--check-only` returns before any call that would start `subprocess.Popen`.
5. Assert the same for `--dry-run`.
6. With `reachable` monkeypatched to report Yahoo unreachable, assert the process would exit with code 1 outside a dry run.

Done-when:
- [ ] `test_real_data_check.py` runs the connectivity check logic without making a real network call
- [ ] `--quick`, `--check-only` and `--dry-run` each have a passing assertion
- [ ] The Yahoo-unreachable exit-code-1 path is asserted

This task does not close U16 (whether `real_data_check.py` and `validate` produce sensible numbers on real Yahoo and NSE data): that still needs a live run, `python real_data_check.py --quick`, read by a person, since Surveyor and an offline test cannot judge real-data output quality [S07/F013].

---

## Unknowns and next probes

| ID | Question | Next probe |
|---|---|---|
| U01 | Does pytest collect and run the six existing top-level-assert test files, and would it also collect the new ones this document proposes, and do they pass? | Run `pytest` and `python test_toolkit.py` (and the others) in a sandbox and compare what each reports. |
| U02 | Does `screen --fundamentals flag` stop with an error, since `screener.py:216` passes `min_inst_change` to a class with no such field? | Run it in a sandbox, or ask the developer which file is newer. |
| U03 | Where is `fund.industry_pe_map`, called at `screener.py:222` and `holdings_analysis.py:306` but defined in no root file? | `git log -S industry_pe_map`; ask the developer. |
| U04 | Does `test_screen_enrich.py` pass, given it expects options and a field the current code does not have? | Run it in a sandbox, or ask the developer. |
| U05 | Does `test_sources.py` pass, given it calls `parse_peers_fragment`, which `screener_in.py` does not define? | Run it in a sandbox, or ask the developer. |
| U06 | Are `screener.py`, `candidate_engine.py` and `screener_in.py` older than `fundamentals.py`, `fund_weights.py`, `holdings_analysis.py` and the two drifted tests? | `git log --oneline -- screener.py candidate_engine.py screener_in.py fundamentals.py`. |
| U08 | Is it intended that `monitor`'s "should already be closed" verdict compares a raised stop against lows from before the raise? | Ask the developer or owner. |
| U09 | Does `monitor.py:65`'s date comparison work on real Yahoo data, whose price index may carry a time zone? | Run `monitor` on a real symbol and read the output, or print `df.index.tz`. |
| U10 | Can `pd.read_excel` open the converter's default `.xls` output without the `xlrd` package, which is not named in `requirements.txt` or `install-commands.txt`? | Run the analysis on a converter output in a sandbox; ask the developer which packages are installed. |
| U11 | Should rows the converter flags "Check" be excluded or marked in the holdings analysis, instead of treated like any other row? | Ask the owner. |
| U12 | The source embeds the owner's ISIN list and the converter takes the PAN-based PDF password on the command line. Is the repository private, and is that acceptable? | Ask the owner or security. |
| U15 | How accurate is the CDSL statement converter on real statements, especially scanned ones? | Ask the owner for a redacted sample statement, or the "Reconciliation" sheet of a past run. |
| U16 | Do `real_data_check.py` and `validate` produce sensible numbers on real Yahoo/NSE data? | Run `python real_data_check.py --quick` (or `--check-only` first) with normal internet. |

## Related documents

- [10-test-review.md](10-test-review.md): the risk ranking these five tasks are built from.
- [09-test-exposure-map.md](09-test-exposure-map.md): the per-flow test results behind that ranking.
- [04-screen-and-rank.md](04-screen-and-rank.md): C01's risks in depth, including U02 to U06.
- [08-developer-onboarding.md](08-developer-onboarding.md): how to run each existing test file and which need no network connection.
- [12-test-plan.md](12-test-plan.md): the overall test strategy these tasks feed into.
