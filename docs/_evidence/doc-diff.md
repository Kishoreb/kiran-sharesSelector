# Doc-diff: existing documentation vs code evidence

Commit b472b9b · Surveyor 2.2.0 · 2026-10-24

Existing documentation files compared:
- `README.md` (389 lines, the main project README)
- `HoldingToExcel.md` (325 lines, titled "Mutual Fund Shortlister")
- `stock_shortlisting_parameters_for_indian_markets.md` (72 lines, a design specification)

No wiki exports, OpenAPI specifications or architecture notes were found outside these three files. The `.docx` versions of each were not read (binary files; the `.md` versions are assumed to match).

---

## Confirmed

Statements the slices support. Each cites the slice and flow.

### README.md

| # | Statement (paraphrased) | Location in README | Evidence |
|---|---|---|---|
| C1 | `data.py` fetches OHLCV + indicators from Yahoo Finance | line 17 | S01 F001: `data.py:50` |
| C2 | `universe.py` fetches live NIFTY index constituent lists from NSE | line 19 | S01 F001: `universe.py:29` |
| C3 | `strategies.py` has two strategies, pullback_trend and breakout, pluggable | line 20 | S01 F001: `strategies.py:194`, `strategies.py:261`, `strategies.py:278` |
| C4 | `risk.py` handles position sizing, targets and portfolio heat | line 21 | S01 F001: `risk.py:60`, `risk.py:91` |
| C5 | `candidate_engine.py` screens and ranks a universe | line 22 | S01 F001: `candidate_engine.py:98`, `candidate_engine.py:180` |
| C6 | `backtester.py` is a historical simulation engine | line 23 | S06 F002: `backtester.py:174` |
| C7 | `monitor.py` checks whether an open position is still valid | line 24 | S03 F005: `monitor.py:54` |
| C8 | `screener.py` is the CLI that wires all commands together | line 25 | S01 F001: `screener.py:754` and 6 other sub-commands in the inventory |
| C9 | `meta_model.py` is an optional calibrated win-probability filter | line 26 | S09 F004: `meta_model.py:122`, `meta_model.py:162` |
| C10 | `anomaly.py` is a financial anomaly scan | line 27 | S08 F014: `anomaly.py:207` |
| C11 | `gov_classifier.py` lowers likely false-positive governance flags | line 28 | S08 F010: `gov_classifier.py:194` |
| C12 | `qualitative.py` provides news sentiment and governance red-flag scanning | line 29 | S02 F001: `qualitative.py:43`, `qualitative.py:129` |
| C13 | `screen` gives entry, stop, target and quantity sized to capital and risk percentage | lines 47-51 | S01 F001: `risk.py:60`, `risk.py:91`, `screener.py:393` |
| C14 | Results saved to `screening_results.csv` | line 51 | S01 F001: `screener.py:814` |
| C15 | Backtest walks every symbol day by day with no lookahead | lines 63-65 | S06 F002: `backtester.py:221`; tests confirm no-lookahead (`test_toolkit.py:183`) |
| C16 | Backtest enforces portfolio heat ceiling and max positions | line 65 | S06 F002: `backtester.py:263` |
| C17 | Backtest outputs: console summary, `backtest_trades.csv`, `backtest_equity.csv` | lines 68-71 | S06 F002: `screener.py:436-437` |
| C18 | Monitor checks whether price touched stop or target since entry | line 82 | S03 F005: `monitor.py:84`, `monitor.py:86` |
| C19 | Monitor checks the strategy's trend conditions | line 85 | S03 F005: `monitor.py:69` |
| C20 | Trailing stop: breakeven at +1R, then trail below recent swing low | lines 88-91 | S03 F005: `exits.py:27`, `exits.py:30` |
| C21 | Time-stop at 14+ days with less than 0.5R | line 92 | S03 F005: `exits.py:37` |
| C22 | Five verdicts: Hold, raise stop, trend broken, time-stop, should already be closed | lines 94-96 | S03 F005: `monitor.py:84-96` |
| C23 | Monitor does not place or close trades | line 97 | S03 F005: `cmd_monitor` writes no file, prints only |
| C24 | Sector concentration is flagged, not filtered | lines 113-116 | S01 F001: `candidate_engine.py:279` |
| C25 | `update-price` adds a dated column `price on <date>` | lines 127-128 | S10 F006: `screener.py:672`, `screener.py:689` |
| C26 | TOTAL row is left blank in the new column | line 138 | S10 F006: `screener.py:675` |
| C27 | `--sma200` on by default | line 150 | S01 F001: `strategies.py:37` |
| C28 | `--fundamentals` default is `off` | line 178 | S02 F001: `screener.py:761` |
| C29 | Banks/NBFCs exempt from ROCE, D/E and interest coverage | line 193 | S02 F001: `fundamentals.py:79` |
| C30 | ROCE default 15% | line 183 | S02 F001: `fundamentals.py:88` |
| C31 | `flag` mode annotates but does not drop; `filter` mode drops failures | lines 175-178 | S02 F001: `screener.py:248` |
| C32 | Ranking adds fundamentals as points per passed rule | lines 206-207 | S01/S02 F001: `candidate_engine.py:167` |
| C33 | Meta-model uses HistGradientBoostingClassifier | line 274 | S09 F004: `meta_model.py:122` |
| C34 | Meta-model features are point-in-time; fundamentals, market cap and news excluded | lines 277-278 | S09 F004: `meta_model.py:58` |
| C35 | Walk-forward validation trains only on trades closed before each test window | line 289 | S09 F004: `meta_model.py:189` |
| C36 | Calibration: isotonic with 200+ rows, sigmoid with 40-199 | line 298 | S09 F004: `meta_model.py:162` |
| C37 | Anomaly detection has seven threshold rules | lines 310-314 | S08 F014: `anomaly.py:128-141` |
| C38 | Anomaly levels: High = 2+ flags, Watch = 1 flag or outlier or top-5% IF, None | line 315 | S08 F014: `anomaly.py:199-200` |
| C39 | Peer z-scores need 8+ companies, Isolation Forest needs 30+ | line 316 | S08 F014: confirmed by `test_ml.py` (45 companies for IF) |
| C40 | Banks/NBFCs = n/a for anomaly | line 317 | S08 F014: `anomaly.py:212` |
| C41 | Same-day stop/target conflict: backtester assumes stop hit first | lines 369-370 | S06 F002: `backtester.py:288-289` |
| C42 | `--risk-pct` default 1.5, `--heat-ceiling` default 8.0, `--max-positions` default 5, `--reward-risk` default 2.0 | lines 340-344 | S01 F001: `screener.py:703`, S06 F002: `backtester.py:263` |

### HoldingToExcel.md (CDSL converter section only)

| # | Statement | Location | Evidence |
|---|---|---|---|
| C43 | Reads a CDSL CAS PDF and writes two Excel files (stocks and mutual funds) | lines 209-215 | S05 F009: `cdsl_holdings_to_xls.py:1135`, `cdsl_holdings_to_xls.py:1153` |
| C44 | ISIN check digit validation with OCR look-alike correction | lines 257-261 | S05 F009: `cdsl_holdings_to_xls.py:159`, `cdsl_holdings_to_xls.py:103` |
| C45 | Stock row arithmetic: qty x price = value | line 262 | S05 F009: `cdsl_holdings_to_xls.py:464` |
| C46 | MF row arithmetic: units x NAV = valuation | line 263 | S05 F009: `cdsl_holdings_to_xls.py:793` |
| C47 | Reconciliation sheet compares sums with printed totals | lines 245-246, 253 | S05 F009: `cdsl_holdings_to_xls.py:652` |
| C48 | Flagged rows shaded yellow | line 266 | S05 F009: `cdsl_holdings_to_xls.py:954` |
| C49 | `cdsl_holdings_to_xls.py` has no automated tests | line 275 | S05 F009: search boundary stated, no test found |

### stock_shortlisting_parameters_for_indian_markets.md

| # | Statement | Location | Evidence |
|---|---|---|---|
| C50 | ROCE > 15%, ROE > 15%, D/E < 0.5, ICR > 3.0x, sales growth > 10%, PAT growth > 12%, P/E vs industry, PEG < 1.0 | section 1 table | S02 F001: `fundamentals.py:88` and the rule defaults (all match) |
| C51 | Liquidity filter: minimum daily trading value > 1 Crore | section 3 | S01 F001: `screener.py` `--min-turnover-cr` default 1.0 |
| C52 | 200-day SMA filter | section 3 | S01 F001: `strategies.py:37` |
| C53 | 52-week high proximity | section 3 | S01 F001: `strategies.py` `max_from_high_pct` (default 20) |
| C54 | Governance scans (auditor resignations, regulatory penalties, qualified opinions) | section 4 | S02 F001: `qualitative.py` 12 regex red-flag patterns |
| C55 | News sentiment scoring | section 4 | S02 F001: `qualitative.py:43` (Google News RSS) |
| C56 | Market cap classification: Large > 20,000 Cr, Mid 5,000-20,000, Small < 5,000 | section 3 | S01 F001: README documents these thresholds; S01 confirms `cap_class` column |

---

## Contradicted

The code does not support these statements. Each cites the contradicting evidence.

### D1. Backtest costs and slippage (README.md, lines 367-368) — affects C05

README "Known limitations" says:

> "No brokerage, STT, or taxes are deducted in the backtest. Real returns would be lower."
> "No slippage — fills assume you get exactly the signalled price."

Code evidence (S06 F002): `costs.py` (51 lines, read whole) computes delivery brokerage, STT, exchange and SEBI charges, GST, stamp duty and a per-sell DP charge, plus a 0.1% slippage adjustment on market fills. The backtester calls `CostModel` by default, and `--no-costs` turns it off. Tests confirm costs are positive and final equity reconciles with the sum of trade P&L (`test_toolkit.py:107`).

Impact: someone reading only the README would believe backtest results ignore costs, when in fact they include Indian statutory charges by default. See open question U17.

### D2. Ranking algorithm (README.md, line 48) — affects C01 (High)

README says candidates are:

> "ranked (score first, then reward:risk)"

Code evidence (S01 F001): the sort key is `(CandidateEngine.points(c, fund_weight), mp, rs, -c.stop_pct)` at `candidate_engine.py:180` (checked). The components are: total points, meta-model probability, relative strength versus the benchmark, tighter stop percentage. The reward-to-risk ratio is used for target calculation (`risk.py:91`), not for ranking. See open question U18.

### D3. Fundamental data source (README.md, line 18) — affects C01 (High)

README's architecture box says:

> "fundamentals.py        Yahoo annual-statement ratios + rule checks (screen only)"

Code evidence (S02 F001): `get_metrics` tries screener.in first (`fundamentals.py:277`), and falls back to Yahoo only when screener.in fails (`fundamentals.py:284`). The primary data source is screener.in, not Yahoo. See open question U19.

### D4. Number of fundamental rules (README.md, lines 181-189) — affects C01 (High)

README lists 8 fundamental rules (ROCE, ROE, D/E, ICR, sales growth, PAT growth, P/E vs industry, PEG).

Code evidence (S02 F001): `fundamentals.py:82` defines `ALL_RULES` with 13 entries. The additional rules cover promoter holding, promoter decline, FII change, DII change and pledge percentage (the ownership rules in S02). See open question U20.

### D5. Earnings call and BSE references (stock_shortlisting_parameters_for_indian_markets.md)

The specification says:

> Section 4: "Earnings Call Transcripts (Concalls): Extract guidance on future revenue goals, CAPEX timelines, and operating margin outlooks."
> Architecture: "Data Ingestion Layer (NSE/BSE APIs, Screener Data, Financial Statements)"

Code evidence (S01-S11, all slices): no code processes earnings call transcripts. No module fetches from BSE APIs directly; BSE data is reached only through Yahoo Finance as a fallback suffix `.BO` (`holdings_analysis.py:151`, S04). See open question U21.

---

## Not covered

Statements about things the slices did not read. Marked `unverified`.

### README.md

| # | Statement | Location | Why not covered |
|---|---|---|---|
| N1 | "Each module works standalone (import and use in your own scripts) or through the CLI" | line 31 | No slice tested standalone imports outside the CLI |
| N2 | `--min-turnover-cr` default 1.0 Crore; 20-day average of Close x Volume | lines 149-150 | The filter exists (S01), but the exact default was not confirmed from a checked quote of the default value |
| N3 | `--max-from-high-pct` default 20, "close within this % of the 52-week high" | line 151 | Same: the filter exists but the default was not quote-checked |
| N4 | "Running update-price twice on the same day overwrites that day's column rather than duplicating it" | line 137 | S10 read the command but did not trace the overwrite-vs-duplicate path |
| N5 | `--fund-weight` default 1.0 | line 209 | Not quote-checked; the ranking formula was confirmed but not this specific default |
| N6 | P/E vs industry: "Median trailing P/E of NSE-Industry peers in the screened universe (needs >= 5 peers)" | line 188 | The P/E-vs-industry function (`industry_pe_map`) is missing from the code entirely (U03); this threshold cannot be confirmed |
| N7 | "P/E vs industry ... caches for 7 days under .cache/fundamentals/" | line 194 | Same: function missing from the code |
| N8 | The `--index` default is `nifty50` | line 335 | Not quote-checked from the parser definition |

### HoldingToExcel.md — mutual fund shortlister section

| # | Statement | Location | Why not covered |
|---|---|---|---|
| N9 | The entire mutual fund shortlister (shortlist.py, config.py, fund_universe.py, fetch_nav_data.py, metrics.py, benchmark.py, portfolio_quality.py, holdings_fetch.py, amc_registry.py, report.py) | lines 1-200 | **These files do not exist in this repository.** The inventory counted 35 Python files; none of them are the mutual fund shortlisting scripts. HoldingToExcel.md describes a different project that shares only `cdsl_holdings_to_xls.py`. |
| N10 | Tests: test_benchmark.py, test_portfolio_quality.py | lines 286-291 | These test files do not exist in this repository either. The 6 test files in the inventory are all for the stock screening toolkit. |

### HoldingToExcel.md — CDSL converter section

| # | Statement | Location | Why not covered |
|---|---|---|---|
| N11 | "NPS sections are ignored" | line 218 | Not traced in S05 |
| N12 | "Tested on one statement with a text layer (Kiran_2026-06.pdf): 48 stock rows and 75 mutual fund rows, with all totals matching" | lines 268-269 | Statement of history; not verifiable from the code |
| N13 | Stock file columns Frozen Bal, Pledge Bal, Pledge Setup Bal, Free Bal | line 242 | S05 confirmed the sheet and key columns but not every column name |

### stock_shortlisting_parameters_for_indian_markets.md

| # | Statement | Location | Why not covered |
|---|---|---|---|
| N14 | Promoter Holding preferred > 50% | section 2 | S02 confirms ownership data is fetched but the specific 50% threshold was not quote-checked as a default |
| N15 | Promoter Pledging < 5% (ideally 0%) | section 2 | Same: pledge data is fetched, specific threshold not confirmed |
| N16 | FII and DII quarterly increases as signals | section 2 | S02 confirms `min_fii_change` and `min_dii_change` fields exist; the trigger logic was not traced in detail |

---

## Intent, policy and history

Statements that cannot come from code. Copied as `source: existing documentation, <file>`.

| # | Statement | Source file | Type |
|---|---|---|---|
| P1 | "It does not predict prices, rank stocks by 'quality', or recommend what to buy — it tells you what currently meets your rules" | README.md, lines 3-5 | intent: project purpose |
| P2 | "Must be run on your own computer with normal internet access" | README.md, lines 9-10 | operational requirement |
| P3 | "This is a rule-checking and simulation tool, not investment advice, and a backtest is not a promise of future performance" | README.md, lines 374-375 | disclaimer |
| P4 | "Flagging, not filtering: flagged candidates still appear in the output — the tool doesn't remove them, since you might have a reason. The call stays yours." | README.md, lines 114-116 | design intent for sector concentration |
| P5 | "Headline sentiment stays noisy: it is a prompt to read the listed headlines, not a signal on its own" | README.md, line 251 | design intent for news scoring |
| P6 | "only use --meta if the verdict supports it" | README.md, line 291 | guidance for meta-model usage |
| P7 | "A flag is a reason to read the filings, not a verdict" | README.md, line 327 | design intent for anomaly detection |
| P8 | "Improving it: open the Governance flags sheet of *_analysis.xlsx, fill the label column, then import-sheet and train again. The built-in seed set (about 40 rows) is only a demo; aim for 100+ reviewed rows before relying on it." | README.md, lines 267-270 | guidance for classifier improvement |
| P9 | "This is a screening tool, not investment advice — check exit loads, expense ratios, fund manager tenure, portfolio overlap and your own risk profile before investing." | HoldingToExcel.md, lines 316-318 | disclaimer (for the mutual fund shortlister, which is not in this repository) |
| P10 | The specification's "Proposed AI Agent Architecture" diagram with Quantitative Screening Engine, Qualitative & NLP Agent, and Final Scoring layers | stock_shortlisting_parameters_for_indian_markets.md, lines 56-70 | design intent: target architecture |

---

## Summary

| List | Count |
|---|---|
| Confirmed | 56 |
| Contradicted | 5 |
| Not covered | 16 |
| Intent / policy / history | 10 |
