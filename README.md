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
data.py               Fetches OHLCV + indicators from Yahoo Finance
fundamentals.py        Yahoo annual-statement ratios + rule checks (screen only)
universe.py            Fetches live NIFTY index constituent lists from NSE
strategies.py           STRATEGY ENGINE — pullback_trend, breakout, pluggable
risk.py                 RISK ENGINE — position sizing, targets, portfolio heat
candidate_engine.py      CANDIDATE ENGINE — screens + ranks a universe, today
backtester.py             BACKTESTER — historical simulation + metrics
monitor.py                 POSITION MONITOR — is an open position still valid
screener.py                  CLI — wires it all together (screen / backtest / monitor / update-price)
```

Each module works standalone (import and use in your own scripts) or
through the CLI.

## Setup (one time)

```
pip install -r requirements.txt
```

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
| P/E vs industry (`pe_vs_industry`) | <= industry median x 1.10 | Median trailing P/E of NSE-Industry peers in the screened universe (needs >= 5 peers) |
| PEG (`peg`) | < 1.0 | P/E / PAT growth %, only when both are positive |

How missing data is handled:
- **n/a is not a pass.** A rule Yahoo can't supply shows as n/a in `fund_notes`. By default n/a does not reject a stock; `--strict-fundamentals` makes it a fail.
- **Banks / NBFCs** (industry containing "Financial") are exempt from ROCE, D/E and interest coverage and shown as `exempt`. Use `--index` so sector info exists.
- **P/E vs industry** builds peer medians by fetching P/E for the whole universe on the first run (slow for nifty500), then caches for 7 days under `.cache/fundamentals/`. Skip it with `--skip-rules pe_vs_industry`.
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

## Shared options (both screen and backtest)


| Flag | Default | Meaning |
|---|---|---|
| `--index` | `nifty50` | `nifty50` / `niftynext50` / `nifty100` / `nifty200` / `nifty500`, fetched live from NSE |
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
- **No brokerage, STT, or taxes** are deducted in the backtest. Real returns
  would be lower, especially with many small trades.
- **No slippage** — fills assume you get exactly the signalled price.
- **Same-day stop/target conflict**: if both the stop and target would have
  been hit on the same day, the backtester conservatively assumes the stop
  hit first. Real outcomes could go either way.
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
