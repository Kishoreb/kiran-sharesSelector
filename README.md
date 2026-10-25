# Indian equity trading toolkit — Strategy / Risk / Candidate / Backtest engines

A small modular Python system that applies YOUR rules (from `trading-rules.md`)
mechanically to real NSE price data. It does not predict prices, rank stocks
by "quality", or recommend what to buy — it tells you what currently meets
your rules, sizes it for your capital, and lets you check historically how
those rules would have played out.

**Must be run on your own computer with normal internet access** — this
uses Yahoo Finance for price data and NSE's archives for index constituent
lists; neither is reachable from a sandboxed environment.

## Architecture

```
data.py                 Fetches OHLCV + indicators from Yahoo Finance
universe.py             Live NIFTY index lists from NSE + dated snapshots
membership.py           Point-in-time index membership (cuts survivorship bias)
strategies.py           STRATEGY ENGINE - pullback_trend, breakout, pluggable; section-3 technical filters
risk.py                 RISK ENGINE - position sizing, targets, portfolio heat
costs.py                Delivery charges (STT, stamp, GST, DP) + slippage
filters.py              Pre-trade filters: liquidity, stop width, results calendar
market.py               Benchmark regime filter + relative strength
exits.py                Breakeven / swing-low trailing stop and time-stop (shared by backtester and monitor)
candidate_engine.py     CANDIDATE ENGINE - screens + ranks a universe, today
backtester.py           BACKTESTER - gap-aware simulation, next-open fills, costs
validation.py           in/out-of-sample, year/regime, sweeps, walk-forward, Monte Carlo, ablation
report.py               Self-contained HTML validation report
real_data_check.py      One-command real-data run of `validate` for both strategies
monitor.py              POSITION MONITOR - is an open position still valid
fundamentals.py         Section-1 rule checks (screen only); fund_weights.py + fundamental_weights.csv = rule weights
screener_in.py          screener.in statements (up to 10y), FII/DII table
nse_client.py           NSE shareholding, pledge (incl. XBRL), announcements
ownership.py            Promoter / pledge / FII-DII metrics and quarter-on-quarter changes
qualitative.py          News sentiment (lexicon / FinBERT / LLM) + governance red-flag scan
news_dedup.py          Optional near-duplicate headline removal (word overlap or local sentence embeddings)
gov_classifier.py       Optional classifier that lowers likely false-positive governance flags
anomaly.py              Financial anomaly scan (cash flow vs profit, debtor days, other income, ...)
meta_model.py          META-LABELING - optional calibrated win-probability filter (train-meta / --meta)
cdsl_holdings_to_xls.py CDSL CAS PDF -> holdings .xls and mutual fund -MF.XLS (see HoldingToExcel.md)
holdings_analysis.py    Runs the rules over YOUR holdings -> *_analysis.xlsx
screener.py             CLI: screen / backtest / validate / monitor / update-price / train-meta / snapshot-changes
diagnose_dump.py, fetch_xbrl_sample.py   Diagnostics for --debug-dump folders and NSE XBRL tags
test_toolkit.py, test_sources.py, test_validation.py, test_membership.py, test_ml.py, test_dedup.py, test_universe.py   Offline tests
```

Each module works standalone (import and use in your own scripts) or
through the CLI. Other commands: `validate` (stress-test a backtest), `train-meta`,
`snapshot-changes`; holdings analysis runs through `holdings_analysis.py`.

## Setup (one time)

```
pip install -r requirements.txt
```

`requirements.txt` holds everything. `torch` and `transformers` are needed only for FinBERT and the
embedding classifier; on Windows install the right `torch` build from pytorch.org first.
Python 3.9+; `pytesseract` also needs the Tesseract program, and only for scanned CAS PDFs.

## Screening — what meets your rules today

```
python screener.py screen --index nifty200 --strategy pullback_trend
python screener.py screen --index nifty500 --strategy breakout --min-score 5
python screener.py screen --symbols RELIANCE TCS INFY --capital 100000 --risk-pct 1.5
```

Every candidate is scored (how many of the strategy's conditions are true),
ranked (score first, then reward:risk), and sized using the Risk Engine —
you get entry, stop, target, and exact quantity for your capital, saved to
`screening_results.csv`.

## Backtesting — how your rules performed historically

```
python screener.py backtest --index nifty50 --strategy pullback_trend --period 2y
python screener.py backtest --index nifty200 --strategy breakout --period 3y --capital 100000
python screener.py backtest --symbols RELIANCE TCS INFY --strategy pullback_trend
```

This walks every symbol day by day, entering trades exactly when the
strategy would have signalled (using only that day and earlier — no
lookahead), sizing each one through the Risk Engine, and enforcing your
portfolio heat ceiling and max concurrent positions across the whole
universe simultaneously, same as live trading would. Outputs:

- Console summary: win rate, profit factor, expectancy, avg R-multiple, max
  drawdown, CAGR, total return
- `backtest_trades.csv` — every simulated trade
- `backtest_equity.csv` — day-by-day portfolio equity, for plotting a curve
  yourself in Excel or a Python plotting library if you want one

## Monitoring — is a position you already hold still worth keeping

```
python screener.py monitor --symbol TATASTEEL --entry 452 --stop 438 --qty 133 --entry-date 2026-07-15
python screener.py monitor --symbol INFY --entry 1540 --stop 1490 --target 1650 --qty 60 --entry-date 2026-06-20 --strategy breakout
```

This is a different question from screening or backtesting: given a
position you're already in, does the original thesis still hold, and
should your stop move? It checks:

- Whether price has already touched your stop or target since entry (in
  case you're checking a few days late)
- Whether the strategy's ongoing trend conditions still hold (not the
  entry trigger — that's a one-time event — but the underlying trend:
  still above rising EMAs)
- A trailing-stop suggestion: once you're up 1x your initial risk, it
  suggests moving the stop to breakeven, then trailing it below the most
  recent swing low as the trade extends
- A time-stop flag if you've held 14+ days with less than 0.5R of progress

Output is a verdict — **Hold**, **Hold, but raise your stop**, **Trend
broken — consider exiting**, **Time-stop reached**, or **Should already be
closed** — plus the reasoning behind it. It does not place or close trades
for you; you still execute the decision yourself.

## Sector concentration check (screen only)

When `--index` is used (not `--symbols`/`--file`), each candidate is tagged
with its NSE industry classification, pulled straight from the same index
CSV. After ranking, candidates are walked in rank order and flagged once a
sector has already contributed more than `--max-per-sector` (default 2)
candidates ahead of it — so if your top-ranked picks happen to be four PSU
banks, the 3rd and 4th get an `over_sector_cap` flag in both the console
output and the CSV, rather than silently handing you a concentrated,
under-diversified shortlist.

```
python screener.py screen --index nifty200 --max-per-sector 2
```

Flagging, not filtering: flagged candidates still appear in the output —
the tool doesn't remove them, since you might have a reason to want two IT
names and skip a lower-ranked pick from elsewhere. The call stays yours.

**Limitation:** this only checks concentration *within this screening run*.
It has no visibility into positions you already hold from a previous day —
if you're already sitting on 2 IT names from the ledger, a fresh IT
candidate here won't know that. Cross-check manually against your open
positions, or lower `--max-per-sector` to leave headroom.

## Tracking price over time (update-price)

```
python screener.py update-price --file screening_results.csv
python screener.py update-price --file screening_results.csv --date 2026-08-15
```

Adds a column named `price on <date>` (default: today) to an existing
`screening_results.csv`, filled with each symbol's latest closing price.
This is the only thing that changes — every other column, every other
row's values, and their exact original formatting are preserved untouched.
Run it again on a later day and it adds another dated column, building a
simple price-tracking log across your screening runs over time. Running it
twice on the same day overwrites that day's column rather than duplicating
it. The `TOTAL` row is left blank in the new column, since it isn't a stock.

## Technical filters (from the shortlisting doc, section 3)

Three extra gates are applied on top of every strategy's own conditions, in
both `screen` and `backtest`. Each adds a named condition to the score
(`liquidity_ok`, `above_sma200`, `near_52w_high`) and must be true for an
entry to fire. All are on by default and can be switched off:

| Flag | Default | Rule |
|---|---|---|
| `--min-turnover-cr` | 1.0 | 20-day average of Close x Volume at least this many Rs crore (0 disables) |
| `--sma200` / `--no-sma200` | on | Close above the 200-day SMA |
| `--max-from-high-pct` | 20 | Close within this % of the 52-week high (0 disables) |

Notes: stocks with fewer than ~200 bars of history fail the SMA200 and
52-week checks (so very recent listings are excluded), and on a `--period 2y`
backtest the first ~200 trading days can't produce entries. Use `--period 3y`
or longer if you want a full 2 years of tradable history. Because the filters
add conditions, `total` in the output grows (e.g. 6 -> 9), so re-check any
`--min-score` you rely on.

**Market-cap label (screen only).** Each candidate gets `market_cap_cr` and
`cap_class` (Large > 20,000 Cr, Mid 5,000-20,000, Small < 5,000) from Yahoo's
current market cap. `--cap-class large|mid|small` keeps only that band;
candidates where Yahoo had no market cap are kept and labelled `Unknown`.
This is a live snapshot, not point-in-time, so it is not used in the backtester.

## Fundamental filters (from the shortlisting doc, section 1) -- screen only

```
python screener.py screen --index nifty200 --fundamentals flag
python screener.py screen --index nifty200 --fundamentals filter --skip-rules peg
python screener.py screen --index nifty200 --fundamentals filter --max-de 1.0 --min-roce 12
```

Runs AFTER the technical screen, only on candidates that already qualified,
so the number of Yahoo calls stays small. `flag` annotates each candidate
(`fund_status` = pass / fail / n/a, `fund_notes`, plus `roce_pct`,
`roe_avg_pct`, `debt_equity`, `pe`, `peg` in the CSV); `filter` also drops
the ones that fail. Default is `off`.

| Rule (`--skip-rules` name) | Default | Computed from |
|---|---|---|
| ROCE (`roce`) | >= 15% | EBIT / (total assets - current liabilities), latest year |
| ROE (`roe`) | >= 15% avg | Net income / equity, average of up to 5 years Yahoo has |
| Debt-to-equity (`de`) | <= 0.5 | Total debt / equity, latest year |
| Interest coverage (`icr`) | >= 3x | EBIT / interest expense (no interest cost = infinite) |
| Sales growth (`sales_growth`) | >= 10% | 3Y CAGR if 4 years exist, else YoY |
| PAT growth (`pat_growth`) | >= 12% | 3Y CAGR if 4 years exist, else YoY |
| P/E vs industry (`pe_vs_industry`) | <= industry P/E x 1.10 | Median P/E of the company's own peer table on screener.in (needs 5+ peers), fetched per candidate and cached 7 days. An `industry_pe.csv` (`industry,pe` per line, `--industry-pe-file`) overrides it. n/a if the peer table cannot be read |
| FII trend (`fii_trend`) | FII holding did not fall | Change over the latest quarter, `--min-fii-change` |
| DII trend (`dii_trend`) | DII holding did not fall | Change over the latest quarter, `--min-dii-change`; FII and DII are separate rules |
| PEG (`peg`) | < 1.0 | P/E / PAT growth %, only when both are positive |

How missing data is handled:
- **n/a is not a pass.** A rule Yahoo can't supply shows as n/a in `fund_notes`. By default n/a does not reject a stock; `--strict-fundamentals` makes it a fail.
- **Banks / NBFCs** (industry containing "Financial") are exempt from ROCE, D/E and interest coverage and shown as `exempt`. Use `--index` so sector info exists.
- **P/E vs industry** uses the median of the company's own screener.in peer table (not a median over the screened universe); `industry_pe.csv` is an optional override. The peer request is untested against the live site: if a run shows `data: industry P/E: ...`, use `--debug-dump` and send the `screener_peers_*.html` file. Skip the rule with `--skip-rules pe_vs_industry`.
- **Rule weights (optional).** `--weights-file fundamental_weights.csv` weighs the rules (0 skips one); without it every rule counts 1. The CSV gains `fund_passed_w`, `fund_evaluated_w`, `fund_score`, `fund_tier`, `industry_pe`, `sales_growth_pct`, `pat_growth_pct`, `promoter_change_1q`, `pledged_change_1q`, `fii_pct`, `fii_change_1q`, `dii_pct`, `dii_change_1q`, `sentiment_label`.
- **PEG < 1** is strict; expect it to reject most stocks. Try it with `--skip-rules peg` to see how much it matters.

Limitations: these are the latest annual statements, not point-in-time, so
they are NOT used in `backtest` (that would add lookahead bias). Yahoo's
Indian coverage has gaps and typically only ~4 annual periods, so spot-check
anything surprising against the company's filings.

## Ranking with fundamentals, and the thesis line (screen)

**Ranking.** Candidates are ranked by combined points, then by reward:risk:

    points = technical conditions true + fund_weight x fundamental rules passed

`--fund-weight` (default 1.0) sets how much each passed fundamental rule is
worth; `0` ranks on technicals only. Rules that are n/a or exempt (e.g. a bank's
ROCE) earn nothing, so missing data lowers a stock's rank slightly instead of
counting as a pass. With `--fundamentals off` the ranking is exactly what it
was before. Note that in `flag` mode a stock that fails some fundamentals can
still outrank one with weaker technicals; use `--fundamentals filter` if you
want failures removed rather than just demoted.

**Thesis.** Each candidate gets a one-line `thesis` (console and CSV), built
from a template out of fields already computed -- no LLM, no new data:

    BBB (Large cap, Capital Goods): pullback + reclaim of rising 20/50 EMA trend - pullback
    and reclaim of the 20-EMA, rising 50-EMA, above 200-SMA, near 52-week high, liquid.
    Entry 100, stop 95 (-5.0%), target 110 (+10.0%), R:R 2.0, risk Rs 50. Fundamentals pass
    (6/7 rules): ROCE 22.1%, ROE 18.4%, D/E 0.12, P/E 18.0, PEG 0.9. Watch: some fundamentals
    unavailable; not confirmed: volume above average.

It restates why your rules fired and what to double-check (sector cap,
failed or missing fundamentals, volume not confirmed). It is not a
recommendation. The CSV also gains `fund_passed`, `fund_evaluated`,
`cond_met` and `cond_missed` columns.

## Optional ML layers (PyTorch / scikit-learn)

Four add-ons sit AROUND the rule-based engine. All are off by default, none changes your entry/stop/target
rules, and each falls back to the old behaviour if its model or package is missing.

```
pip install -r requirements.txt           # includes torch, transformers, scikit-learn (Windows: see pytorch.org for the right torch build)
```

### 1. FinBERT news sentiment (`qualitative.py`)

Replaces the keyword lexicon with FinBERT (finance-tuned BERT, runs locally). Score = P(positive) - P(negative).

```
python screener.py screen --index nifty200 --qualitative flag --llm finbert
python holdings_analysis.py Kiran_2026-06_holdings.xls --llm finbert
python holdings_analysis.py holdings.xls --llm finbert --llm-model C:\models\finbert    # local copy
```

The first run downloads `ProsusAI/finbert` (about 440 MB) from Hugging Face; for an offline machine download
it once and pass the folder with `--llm-model`. If the model cannot load, a warning is printed and the lexicon is
used. Headline sentiment stays noisy: it is a prompt to read the listed headlines, not a signal on its own.

### 1b. News de-duplication (`news_dedup.py`)

Google News returns the same story many times, which inflates the headline count and lets one story dominate the
sentiment average. `--dedup` keeps one headline per cluster of near-duplicates (newest kept) before scoring.

```
python screener.py screen --index nifty200 --qualitative flag --dedup lexical     # word overlap, no extra packages
python screener.py screen --index nifty200 --qualitative flag --dedup embed       # local sentence embeddings
python holdings_analysis.py holdings.xls --dedup embed --dedup-model C:\models\minilm
```

Only headlines within 3 days of an already-kept similar one are dropped, so a story that returns weeks later
still counts. `embed` loads `sentence-transformers/all-MiniLM-L6-v2` (about 90 MB, via `transformers`, needs
torch); if it cannot load, it warns and falls back to word overlap. The result gains `news_dupes_removed`.
Default is `none` (old behaviour). Offline tests: `python test_dedup.py`.

### 2. Governance-flag classifier (`gov_classifier.py`)

The regexes still find red flags. A small text classifier gives a second opinion on each hit and **lowers the
severity one step** (High -> Medium -> Low) when it is confident the hit is a false positive. It never removes
or raises a flag; every flag keeps `ml_prob` and `ml_note`.

```
python gov_classifier.py train                           # seed set + governance_labels.csv, TF-IDF + logistic regression
python gov_classifier.py train --embedder ProsusAI/finbert   # PyTorch embeddings instead of TF-IDF
python gov_classifier.py predict "Nomura cuts rating on Siemens" --flag rating_downgrade
python holdings_analysis.py holdings.xls --gov-model gov_model.pkl
python screener.py screen --index nifty200 --qualitative flag --gov-model gov_model.pkl
```

Improving it: open the **Governance flags** sheet of `*_analysis.xlsx`, fill the `label` column (1 = genuine,
0 = false positive), then `python gov_classifier.py import-sheet Kiran_2026-06_holdings_analysis.xlsx` and train again.
`train` prints a cross-validation report, including how many genuine flags would have been wrongly demoted.
The built-in seed set (about 40 rows) is only a demo; aim for 100+ reviewed rows before relying on it.

### 3. Meta-labeling trade-quality filter (`meta_model.py`, `train-meta`)

The strategy still decides whether a setup exists. A gradient-boosting model (scikit-learn
`HistGradientBoostingClassifier`) then estimates how likely that setup is to end as a winner, from point-in-time
features only: stop distance, ATR %, 5/20/63-day returns, relative strength vs index, volume ratio, distance from
EMAs / 200-SMA / 52-week high, EMA slope, close position in the day's range, traded value, index trend and return,
signal score, strategy type. Fundamentals, market cap and news are **not** used (live snapshots would leak the future).

```
python screener.py train-meta --index nifty200 --strategy pullback_trend --period 5y
python screener.py train-meta --index nifty500 --strategy breakout --period 5y --dataset-out meta_rows.csv
python screener.py screen --index nifty200 --strategy pullback_trend --meta flag
python screener.py screen --index nifty200 --strategy pullback_trend --meta filter --meta-min-prob 0.45
```

`train-meta` runs the backtest with capital, position-count and heat limits lifted (so every signal becomes a
training row), builds features on the signal day, then validates **walk-forward**: each fold trains only on trades
that had already closed before the test window, and scores the next unseen window. It prints out-of-sample AUC,
plain rules vs "keep the top 70 / 50 / 30%", how many folds improved, and a plain-words verdict. The model file
(`meta_model.pkl`) is written either way; **only use `--meta` if the verdict supports it.** One model per strategy.

In `screen`, `--meta flag` adds `meta_prob` to the CSV and thesis and ranks by it after points (before relative
strength); `--meta filter` also drops candidates below `--meta-min-prob` (default: the cut-off stored in the model).
Retrain periodically (for example monthly) so the model sees recent trades.

`train-meta` also calibrates the probabilities: the model is fitted on the earlier part of the training trades and an
isotonic (200+ rows) or Platt/sigmoid (40-199 rows) calibrator on the later part, so "min prob 0.5" means roughly
"half of such setups won". With too few rows it says `none` (raw probabilities). The report adds Brier scores
(raw vs calibrated vs always guessing the base rate) and a reliability table (5 buckets, predicted vs actual win
rate, out-of-sample). If the table is far from the diagonal, do not trust the probabilities as numbers.

Limits: survivorship bias (today's index list, or use `--membership-file`) is in the training data; a few hundred
trades is a small sample; the filter is only as good as its out-of-sample table; and a model trained in one market
regime may fail in another. Offline tests: `python test_ml.py`.

### 4. Financial anomaly detection (`anomaly.py`)

Looks at the numbers themselves (screener.in annual statements, now including the cash-flow table) for patterns
that often accompany trouble. Seven transparent rules, each showing the numbers behind it: 3-year operating cash
flow under 50% of net profit; negative operating cash flow despite profit; debtor days or inventory days up 30%+
(and 10+ days) vs the previous 3-year average; other income 40%+ of PBT (or +20 pts); borrowings CAGR 15%+ and 20+ pts
above sales CAGR; operating margin moving 8+ pts vs its 3-year average. With 8+ companies in the run it also flags
robust-z-score outliers vs peers, and with 30+ it adds an Isolation Forest score (`anomaly_iso_pct`).
Level: **High** = 2+ rule flags; **Watch** = 1 rule flag, a peer outlier, or top-5% Isolation Forest; **None**;
**n/a** = no usable statements, or a bank/NBFC (these ratios do not apply). Missing data is never a flag.

```
python anomaly.py POLYCAB VMART TITAN
python holdings_analysis.py Kiran_2026-06_holdings.xls              # anomaly scan is on; --skip-anomalies to turn off
python screener.py screen --index nifty200 --anomalies flag         # annotate (CSV columns, thesis "Watch:" line)
python screener.py screen --index nifty200 --anomalies filter       # also drop level High
```

Limits: screen-only (latest annual statements, not point-in-time, never in the backtester); in `screen` only the
candidates are analysed, so the peer layers usually do not run there (rules do); capex phases, acquisitions and
one-off income trigger the rules legitimately. A flag is a reason to read the filings, not a verdict. The first run
after this update re-fetches screener.in pages (cache version bumped) to read the cash-flow table.

## Whole-market universe (`--index all`)

```
python screener.py screen --index all                                  # every EQ-series NSE stock with last-day traded value >= Rs 0.5 Cr
python screener.py screen --index all --universe-min-turnover-cr 2     # stricter pre-filter
python screener.py screen --index all --universe-min-turnover-cr 0     # no pre-filter (thousands of symbols: very slow)
python screener.py screen --index all --cap-class small --max-from-high-pct 15
```

The list comes from NSE's `EQUITY_L.csv` (EQ series only, so trade-for-trade BE stocks are dropped) and the latest
daily bhavcopy (`sec_bhavdata_full`), which gives every stock's traded value in one file, so illiquid names are
removed BEFORE any price history is downloaded. The pre-filter uses ONE day's traded value as a cheap first cut;
the strategy's own 20-day liquidity rule (`--min-turnover-cr`) still applies afterwards. If no bhavcopy is
found for the last 7 days the run stops with a message instead of silently using an unfiltered list.

Sector: taken from the Nifty 500 list where the stock is in it; otherwise `Unknown`, or `Financial Services (guessed)`
when the company name looks like a lender (so the bank-style rule exemptions apply). Stocks outside the Nifty 500
therefore have no industry P/E and are not counted in the sector-cap check. Guessed names are left out of the
industry P/E medians.

Limits: today's list only (survivorship bias; `--membership-file` is ignored with `--index all`), and market cap is
still Yahoo's live snapshot, so use `--cap-class small|mid|large` to pick the band. A full-market run downloads
price history per symbol, so expect it to take much longer than Nifty 200; `screen` is the sensible use. Untested
against the live NSE files (offline tests only): if the bhavcopy columns or URL change, `parse_bhavcopy` and
`BHAV_URL` in `universe.py` are the two places to fix.

## Shared options (both screen and backtest)


| Flag | Default | Meaning |
|---|---|---|
| `--index` | `nifty50` | `nifty50` / `niftynext50` / `nifty100` / `nifty200` / `nifty500` / `all`, fetched live from NSE |
| `--symbols` | — | Explicit symbol list, overrides `--index` |
| `--file` | — | Text file of symbols, overrides `--index` |
| `--strategy` | `pullback_trend` | `pullback_trend` or `breakout` |
| `--capital` | 100000 | Capital to size positions against |
| `--risk-pct` | 1.5 | Risk % of capital per trade |
| `--heat-ceiling` | 8.0 | Max total open-position risk, % of capital |
| `--max-positions` | 5 | Max concurrent open positions |
| `--reward-risk` | 2.0 | Target = entry + this × (entry − stop) |
| `--max-per-sector` | 2 | (screen only) Flag candidates beyond this many per sector |

## The two built-in strategies

**`pullback_trend`** — price above rising 20/50-EMA, pulled back to the
20-EMA, reclaimed it on rising volume. Stop = tighter of recent swing low
or the 50-EMA. This is the framework from `trading-rules.md`.

**`breakout`** — price breaks above its own recent N-day high on strong
volume (1.5x average), with the 50-EMA still trending up, closing in the
upper part of the day's range. Stop = just below the old resistance level
or the 20-EMA, whichever is tighter.

Add your own by subclassing `Strategy` in `strategies.py` and registering
it in the `STRATEGIES` dict — the candidate engine and backtester will pick
it up automatically via `--strategy your_name`.

## Known limitations — read before trusting backtest numbers

- **Survivorship bias**: `--index` always fetches TODAY's constituent list.
  Backtesting 3 years back still uses today's NIFTY 500, not what was in the
  index 3 years ago — stocks that were removed (often because they performed
  badly) are invisible to the backtest. This inflates results.
- **Costs are estimates.** Statutory charges (STT, exchange, SEBI, stamp duty, GST, DP charge) and 0.10%
  slippage per market fill are deducted (`costs.py`; `--no-costs` switches them off). The rates are best
  estimates: check them against a contract note from your broker. **Capital-gains tax is not modelled.**
- **Fills are idealised**: next-open entries, gap-aware stops, no circuit-limit or liquidity-depth modelling,
  daily bars only.
- **Same-day stop/target conflict**: if both the stop and target would have
  been hit on the same day, the backtester conservatively assumes the stop
  hit first. Real outcomes could go either way.
- **Fundamentals, ownership, news and anomaly checks are live snapshots**, so they are screen-only and never
  used in the backtester or as ML features.
- **Parsers are untested against live sites.** The NSE, screener.in and Google News code and the FinBERT
  download were only tested offline; use `--debug-dump` on a real run if a field comes back empty.
- **ML layers are aids.** The governance classifier's seed set is a demo (aim for 100+ reviewed labels); use
  `--meta` only if the `train-meta` verdict supports it.
- **Data quality**: Yahoo Finance data for NSE stocks can have gaps or
  occasional errors. Spot-check surprising results against a real chart.
- This is a rule-checking and simulation tool, not investment advice, and a
  backtest is not a promise of future performance — markets change, and a
  rule set that worked on the last 2 years may not work on the next 2.

## Files this produces

| File | From |
|---|---|
| `screening_results.csv` | `screen` — today's ranked candidates |
| `backtest_trades.csv` | `backtest` — every simulated trade |
| `backtest_equity.csv` | `backtest` — day-by-day equity curve |
| `.cache/*.csv` | `universe.py` — cached NSE index lists (1 day) |
| `meta_model.pkl`, `meta_rows.csv` | `train-meta` — trained filter, optional training rows |
| `*_analysis.xlsx` | `holdings_analysis.py` — Summary, Holdings analysis, Not analysed, Governance flags sheets (incl. anomaly columns) |
| `validation_report_*.html`, `validation_sweep_*.csv` | `validate --report / --sweep-out`, `real_data_check.py` |
| `index_changes.csv` | `snapshot-changes` — input for `--membership-file` |
| `gov_model.pkl`, `governance_labels.csv` | `gov_classifier.py` — classifier and your reviewed flag labels |
