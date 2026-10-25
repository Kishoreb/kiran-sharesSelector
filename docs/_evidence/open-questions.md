# Open questions

Questions the code could not answer, grouped by who can answer them. Updated 2026-10-24 (after /survey-5-compare).

"Contradiction" means two sources in the repository disagree. The affected claims stay `unknown` until a person settles which source is right.

## For a developer

| ID | Question | Why it matters | From | Status |
|---|---|---|---|---|
| U01 | The owner says tests run with pytest, but the 6 test files have no `def test_*` functions (checks run at the top level of each file). Does pytest collect and report them, and do they pass? | Decides how tests are run and counted in documents 8, 9 and 12. Running tests is outside Surveyor's read-only rule. | inventory | open |
| U02 | Contradiction. `screener.py:216` passes `min_inst_change` to `FundamentalFilters`, which defines `min_fii_change` and `min_dii_change` (`fundamentals.py:99-100`). Does `screen --fundamentals flag` stop with an error? | Decides whether the fundamentals option of the main command works. | S01, S02 | open |
| U03 | Contradiction. `fund.industry_pe_map` is called at `screener.py:222` and `holdings_analysis.py:306` but no root `*.py` file defines it. Where is it? | Decides whether P/E-versus-industry works in `screen` and with `--industry-pe` in the holdings analysis. | S02, S04 | open |
| U04 | Contradiction. `test_screen_enrich.py` expects `--weights-file`, `--no-weights-file`, `--technical-only`, `--industry-pe-file`, fundamentals and news ON by default, and a Candidate field `fund_passed_w`. `screener.py` and `candidate_engine.py` have none of these, and `--fundamentals` defaults to `off` (`screener.py:761`). Which is current? | The test cannot match this code. Document 10 cannot grade this flow's tests until it is settled. | S01, S02 | open |
| U05 | Contradiction. `test_sources.py:104-105` calls `parse_peers_fragment` and expects a `peers` entry from `get_raw`. `screener_in.py` has neither. Does `test_sources.py` pass? | Same as U04, for the data-source tests. | S02 | open |
| U06 | Root cause of U02 to U05: are `screener.py`, `candidate_engine.py` and `screener_in.py` older than `fundamentals.py`, `fund_weights.py`, `holdings_analysis.py` and the two tests? Which versions are current? Probe: `git log --oneline -- <file>` for each. | One answer may settle U02 to U05 together. | S02 | open |
| U08 | `monitor.py:66` compares every low since the entry date with the stop the user types, which the option text calls the current stop. After a stop has been raised, can this give "Should already be closed" for a position that was never stopped out? Intended? | Decides the trust to place in the monitor verdict after a stop is trailed. | S03 | open |
| U09 | Does `df[df.index >= entry_dt]` (`monitor.py:65`) work on real Yahoo data, whose index may carry a time zone? | The whole `monitor` command may fail on real data. No test covers it. | S03 | open |
| U10 | `holdings_analysis.py:78` opens the converter's default `.xls` output with pandas, which needs `xlrd` for old Excel files. `xlrd` is not named in `requirements.txt` or `install-commands.txt`. Is it installed? | Decides whether the two tools work together out of the box. | S04 | open |
| U14 | What does `anomaly.analyse_many` do (called from `screener.py:262` and `holdings_analysis.py:333`)? | Needed for capability C07. | S04 | answered in S08 (financial anomaly detection; see S08 F014) |
| U16 | Do `real_data_check.py` (F013) and the `validate` command produce sensible numbers on real Yahoo/NSE data, and does the connectivity-then-subprocess path work end to end? No offline test drives `real_data_check.py`. | Decides how far a backtest/validation result can be trusted; C06 is Medium importance. | S07 | open |
| U17 | Contradiction (docs vs code). README "Known limitations" says "No brokerage, STT, or taxes are deducted" and "No slippage". `costs.py` (51 lines, S06 F002) computes delivery brokerage, STT, exchange and SEBI charges, GST, stamp duty and 0.1% slippage; the backtester applies them by default (`--no-costs` turns them off). `test_toolkit.py:107` confirms costs are positive. Is the README outdated? | Someone reading only the README would believe backtest results ignore transaction costs. | doc-diff D1 | open |
| U18 | Contradiction (docs vs code). README says candidates are "ranked (score first, then reward:risk)". The sort key is `(points, meta_prob, relative_strength, -stop_pct)` at `candidate_engine.py:180` (S01 F001). The reward:risk ratio is used for target calculation (`risk.py:91`), not ranking. Which description is current? | Affects how a user understands the ranking. C01 is High importance. | doc-diff D2 | open |
| U19 | Contradiction (docs vs code). README architecture line says `fundamentals.py` provides "Yahoo annual-statement ratios". Code tries screener.in first (`fundamentals.py:277`) and falls back to Yahoo (`fundamentals.py:284`, S02 F001). Is the README outdated? | A user expecting Yahoo as the primary source would not understand rate-limiting or cache behaviour. | doc-diff D3 | open |
| U20 | Contradiction (docs vs code). README's fundamental-filters table lists 8 rules. `fundamentals.py:82` defines `ALL_RULES` with 13 entries (S02 F001); the additional 5 cover promoter holding, promoter decline, FII change, DII change and pledge. Is the README missing the ownership rules? | A user relying on the table would not know about 5 active rules. | doc-diff D4 | open |
| U22 | No file declares a required Python version, and `requirements.txt` was only read for package names, not version pins (inventory). The only version evidence is the developer's local `.venv` (3.14.3). Which Python and package versions does the toolkit actually support? | Someone setting up a new machine has no stated target to install against. | 06-runtime-and-deployment | open |
| U23 | `install-commands.txt`'s recorded contents are three Python packages (pdfplumber, xlwt, pytesseract). Does it, or any other file, also cover installing the Tesseract OCR engine itself, which `pytesseract` only wraps? | Without Tesseract installed separately, OCR of scanned CDSL statements (part of C04) cannot work even with every Python package present. | 06-runtime-and-deployment | open |
| U24 | `cdsl_holdings_to_xls.py:579` opens the password-protected PDF with no `try`/`except` around the call. What exception does `pdfplumber` raise on a wrong password, and what does the user see and the exit code become? | The converter (C04) handles every other failure with its own message; this is the one path found with no handler at all. | S05, 07-error-handling-and-observability | open |

## For the product owner or business

| ID | Question | Why it matters | From | Status |
|---|---|---|---|---|
| U07 | `screen` receives the portfolio heat ceiling (8%) and the maximum number of positions (5) but never checks them; only the backtester does (`backtester.py:263`). Is that intended? | A screen result can list more risk than the ceiling allows. | S01 | open |
| U11 | The converter marks doubtful rows in a "Check" column, and the holdings analysis ignores that column. Should flagged rows be excluded or marked in the analysis? | A misread quantity or price would flow into the portfolio analysis unmarked. | S04, S05 | open |
| U13 | `screener_in.py:16` says screener.in's terms do not grant a right to bulk automated access. The tools fetch one page per candidate or holding. Is this accepted? | A policy decision about the data source. | S02, S04 | open |
| U15 | How accurate is the statement converter on real statements, especially scanned ones? Can the owner share a redacted sample or the "Reconciliation" sheet from a past run? | There is no test and no sample, so accuracy cannot be graded from the code. | S05 | open |
| U21 | `stock_shortlisting_parameters_for_indian_markets.md` section 4 specifies "Earnings Call Transcripts (Concalls)" processing, and the architecture diagram names "BSE APIs". No code processes concalls (S01-S11); BSE is reached only as a Yahoo `.BO` suffix fallback. Are these planned features, or has the spec drifted from the implementation? | Determines whether the spec is a current requirement or an outdated wish list. | doc-diff D5 | open |

## For operations

| ID | Question | Why it matters | From | Status |
|---|---|---|---|---|

## For security

| ID | Question | Why it matters | From | Status |
|---|---|---|---|---|
| U12 | The source embeds the owner's ISIN list (`holdings_analysis.py:51`), and the converter takes the tax-ID password as a command-line option (`cdsl_holdings_to_xls.py:1115`). A remote named `origin` exists in the git data. Is the repository private, and is this acceptable? | Personal financial data in code and shell history. | S04, S05 | open |

## Answered

| ID | Answer | Source (role, date) | Documents updated |
|---|---|---|---|
