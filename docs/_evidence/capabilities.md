# Capabilities and slice plan

Commit b472b9b · Surveyor 2.2.0 · 2026-10-24

Capability names and importance confirmed by the human: yes, owner, 2026-10-24 (names ok; importance not objected to)

Importance ratings are `inferred` from what each tool does to real money or personal data. No person has stated them yet. Capability names come from module docstrings and command help text (first lines only), not from a full reading.

## Capabilities

| ID | Name (business words) | Importance | Why this importance | Entry points | Supporting code |
|---|---|---|---|---|---|
| C01 | Screen and rank candidate trades | High | It sizes real positions against the user's capital and risk limits (inferred from the `screen` options `--capital`, `--risk-pct`, `--heat-ceiling` at `screener.py:702-704`) | E001 | `candidate_engine.py`, `strategies.py`, `risk.py`, `filters.py`, `market.py`, `universe.py`, `data.py`, `costs.py`, `fundamentals.py`, `fund_weights.py`, `screener_in.py`, `ownership.py`, `nse_client.py`, `qualitative.py`, `report.py` |
| C02 | Monitor an open position | High | It tells the user whether to keep holding and where to move the stop on money already invested | E005 | `monitor.py`, `exits.py`, `strategies.py`, `data.py` |
| C03 | Analyse existing holdings | High | It runs the toolkit's rules over the user's real portfolio and writes a row per holding | E008 | `holdings_analysis.py`, `fundamentals.py`, `ownership.py`, `nse_client.py`, `qualitative.py`, `gov_classifier.py`, `anomaly.py`, `screener_in.py`, `universe.py` |
| C04 | Convert a CDSL account statement to Excel | Medium | It reads a password-protected statement tied to the user's PAN (tax ID) and holdings; it feeds C03. Personal financial data, but no trading decision is made here | E009 | `cdsl_holdings_to_xls.py` (single file) |
| C05 | Backtest the trading rules on history | Medium | It informs whether to trust the rules; it moves no money by itself | E002 | `backtester.py`, `strategies.py`, `risk.py`, `filters.py`, `exits.py`, `costs.py`, `market.py`, `membership.py`, `data.py`, `universe.py` |
| C06 | Validate a backtest (is the result luck?) | Medium | It decides how far the user trusts a backtest result; wrong output gives false confidence | E003, E013 | `validation.py`, `report.py`, `backtester.py`, `real_data_check.py` |
| C07 | Check companies for red flags | Medium | A wrong flag can wrongly remove or keep a share. Classifier and anomaly checks add warnings to C01 and C03 | E010, E011, E012, E014 | `gov_classifier.py`, `anomaly.py`, `qualitative.py`, `screener_in.py` |
| C08 | Filter trades by predicted quality (meta-model) | Low | Optional layer on top of the rules; it never creates signals or changes stops (module docstring `meta_model.py`) | E004 | `meta_model.py`, `candidate_engine.py` |
| C09 | Rebuild index membership history | Low | Reduces survivorship bias (backtests that quietly skip dropped shares); input to C05 | E007 | `membership.py`, `universe.py` |
| C10 | Refresh prices in a results file | Low | Housekeeping on a CSV the user already has | E006 | `screener.py` (sub-command code), `data.py` |
| C11 | Diagnose data-source problems | Low | Developer aids for parser problems and raw filing tags; no output used for trades | E015, E016 | `diagnose_dump.py`, `fetch_xbrl_sample.py`, `nse_client.py` |

Supporting code is listed from imports and docstrings, not yet confirmed by reading.

## Flows

One flow per entry point for now. `/survey-4-read` may split a flow if a command has several distinct modes.

| Flow | Capability | Entry point | Business name |
|---|---|---|---|
| F001 | C01 | E001 | Screen and rank candidates against my rules now |
| F002 | C05 | E002 | Backtest my rules on history |
| F003 | C06 | E003 | Stress-test a backtest |
| F004 | C08 | E004 | Train the trade-quality filter |
| F005 | C02 | E005 | Check an open position |
| F006 | C10 | E006 | Add or refresh a dated price column |
| F007 | C09 | E007 | Build index-change rows from saved snapshots |
| F008 | C03 | E008 | Run the rules over my existing holdings |
| F009 | C04 | E009 | Convert a CDSL statement PDF to Excel |
| F010 | C07 | E010 | Train the governance-flag classifier |
| F011 | C07 | E011 | Add reviewed rows from a holdings analysis sheet |
| F012 | C07 | E012 | Score one piece of text for governance concern |
| F013 | C06 | E013 | Real-data validation run for each strategy |
| F014 | C07 | E014 | Detect financial anomalies from statements |
| F015 | C11 | E015 | Summarise a debug dump folder |
| F016 | C11 | E016 | Fetch a sample shareholding filing and list its pledge tags |

## Slice plan

High-importance capabilities first. At most 6 flows per slice. No prior analysis exists, so every slice starts `not read`.

| Slice | Capability | Flows | Question | Files to open | Related tests | Status |
|---|---|---|---|---|---|---|
| S01 | C01 | F001 | How does `screen` get a universe and price history, apply strategies, filters and risk sizing, and rank candidates? | `screener.py`, `candidate_engine.py`, `strategies.py`, `risk.py`, `filters.py`, `market.py`, `universe.py`, `data.py` | `test_toolkit.py`, `test_ml.py` | read |
| S02 | C01 | F001 | How are fundamentals, ownership and news flags added to a screen result, and what happens when a source fails? | `fundamentals.py`, `fund_weights.py`, `screener_in.py`, `ownership.py`, `nse_client.py`, `qualitative.py` | `test_screen_enrich.py`, `test_sources.py` | read |
| S03 | C02 | F005 | What does `monitor` decide about an open position, and which exit rules does it apply? | `screener.py` (monitor sub-command), `monitor.py`, `exits.py` | `test_toolkit.py` (exit checks, unconfirmed) | read |
| S04 | C03 | F008 | How does the holdings analysis read the holdings file, call each check, and write the result? | `holdings_analysis.py` | none found by import search: next probe in the slice | read |
| S05 | C04 | F009 | How does the converter open a protected PDF, parse holdings, and write the two Excel files? | `cdsl_holdings_to_xls.py` (large, 1,172+ lines, read in parts) | none found by import search | read |
| S06 | C05 | F002 | How does the backtest walk through history, apply costs and exits, and report trades? | `backtester.py`, `costs.py`, `exits.py`, `membership.py` | `test_toolkit.py`, `test_membership.py` | read |
| S07 | C06 | F003, F013 | What does `validate` test (split, years, regimes, Monte Carlo, sweeps, walk-forward, ablation), and how is the report built? | `validation.py`, `report.py`, `real_data_check.py` | `test_validation.py` | read |
| S08 | C07 | F010, F011, F012, F014 | How do the classifier and the anomaly check decide a flag is genuine, and where do their results go? | `gov_classifier.py`, `anomaly.py` | `test_ml.py` | read |
| S09 | C08 | F004 | How is the meta-model trained, saved and applied to rank or filter trades? | `meta_model.py` | `test_ml.py` | read |
| S10 | C09, C10 | F006, F007 | How do `update-price` and `snapshot-changes` change files, and what do they leave untouched? | `screener.py` (two sub-commands), `membership.py` | `test_membership.py` | read |
| S11 | C11 | F015, F016 | What do the two diagnostic scripts read and print? | `diagnose_dump.py`, `fetch_xbrl_sample.py` | none found by import search | read |

11 slices to read. Reading 5 slices per run means 3 runs of `/survey-4-read`.
