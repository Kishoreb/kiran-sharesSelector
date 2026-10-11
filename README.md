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
data.py               Fetches OHLCV + indicators (EMA, ATR, traded value) from Yahoo Finance
universe.py            Fetches live NIFTY index constituent lists from NSE (+ saves dated snapshots)
membership.py           POINT-IN-TIME MEMBERSHIP — who was in the index on a given past date
strategies.py           STRATEGY ENGINE — pullback_trend, breakout, pluggable; structure or ATR stops
risk.py                 RISK ENGINE — position sizing, targets, portfolio heat
filters.py               PRE-TRADE FILTERS — liquidity, stop width, results-date calendar
market.py                 MARKET CONTEXT — index regime check + relative strength vs Nifty
exits.py                   EXIT RULES — breakeven/trailing/time-stop, shared by monitor + backtester
costs.py                    COST MODEL — STT/stamp/exchange/DP charges + slippage
candidate_engine.py          CANDIDATE ENGINE — screens + ranks a universe, today
backtester.py                 BACKTESTER — historical simulation + metrics
validation.py                  VALIDATION — out-of-sample, sensitivity, walk-forward, Monte Carlo
report.py                       HTML REPORT — offline equity/drawdown charts + validation tables
monitor.py                     POSITION MONITOR — is an open position still valid
screener.py                     CLI — wires it all together (screen / backtest / validate / snapshot-changes / monitor / update-price)
test_toolkit.py                  Offline sanity tests (python test_toolkit.py)
test_validation.py                Offline tests for the validation tools (python test_validation.py)
test_membership.py                 Offline tests for membership, snapshots, ablation (python test_membership.py)
real_data_check.py                  One command: real-data validation of both strategies into a dated folder
index_changes.example.csv            Format example for --membership-file (made-up symbols)
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
python screener.py screen --index nifty200 --regime-mode block --results-file results_calendar.csv
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

This walks every symbol day by day, queuing an order when the strategy
signals (using only that day and earlier — no lookahead), filling it at the
next open, sizing each one through the Risk Engine against current equity, and
enforcing your portfolio heat ceiling and max concurrent positions across the
whole universe simultaneously, same as live trading would. Outputs:

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

## What changed in this version (realism fixes + filters)

**Backtest fixes**

- **Equity-based sizing.** Risk per trade and the heat ceiling are measured against
  current equity (cash + open positions), not free cash. Previously risk per trade
  shrank, and heat % was overstated, as cash got deployed.
- **Next-open entries.** A signal on today's close is filled at the NEXT day's open
  (how you actually trade after a post-market screen). Size, heat and max-position
  checks happen at fill time with the real fill price. If several orders compete for
  the same slots they are filled best-ranked first (score, relative strength, stop
  tightness) — the same order the screener shows.
- **Gap-aware exits.** If a day opens through your stop you exit at the open, not at
  the stop price; a gap above target fills at the open. If both stop and target are
  inside one day's range, the stop is assumed first.
- **Backtest uses your real exit rules.** Breakeven at +1R, trail below the latest
  swing low, and the 14-day time-stop (executed at the next open) now run in the
  backtest via `exits.py`, the same code the monitor uses. `--no-trailing` and
  `--time-stop-days 0` switch them off for comparison.
- **Costs and slippage.** Statutory charges and 0.10% slippage per market fill are
  deducted by default. The numbers in `costs.py` are estimates of typical
  discount-broker DELIVERY charges — check them against a contract note from your
  own broker. `--no-costs` gives gross results. Capital gains tax is not deducted.
- **Ranking fix.** Reward:risk was the old tiebreaker but is identical for every
  candidate (target is a fixed multiple of the stop distance). Ranking is now:
  score → relative strength vs Nifty (63-day) → tighter stop.
- **Behaviour change in the monitor:** the trailing stop now starts only after +1R,
  as the rules above describe. The old code trailed to the swing low at any R.

**New filters and options** (screen and backtest)

| Flag | Default | Meaning |
|---|---|---|
| `--regime-ema` | 50 | Nifty must close above this EMA. `0` = off. Backtest blocks entries when it doesn't; screen follows `--regime-mode` |
| `--regime-mode` | flag | (screen) `flag` keeps candidates but marks them, `block` drops them, `off` ignores regime |
| `--benchmark` | ^NSEI | Index used for regime and relative strength |
| `--min-traded-value` | 5 | Min 20-day average traded value, Rs crore (0 = off) |
| `--min-risk-fraction` | 0.5 | Skip setups where capital limits cut your risk below this fraction of the intended risk (a very tight stop that would swallow all your capital, or a 1–2 share stub). 0 = off |
| `--max-stop-pct` | 8 | Reject setups whose stop is wider than this % of entry (0 = off) |
| `--stop-mode` | structure | `structure` (swing low / EMA / breakout level) or `atr` (close − `--atr-mult` × ATR14) |
| `--pullback-lookback` | 10 | pullback_trend: LONGEST pullback (consecutive closes at/below the 20-EMA) that still counts |
| `--min-pullback-days` | 2 | pullback_trend: SHORTEST pullback that counts (1 = the old, looser behaviour) |
| `--membership-file` | — | Index-changes CSV for point-in-time membership (backtest/validate, `--index` mode only) |
| `--atr-mult` | 2.0 | ATR multiple for `--stop-mode atr` |
| `--results-file` | — | Your own file of result dates; entries near a result are skipped |
| `--results-buffer-days` | 14 | Skip if results are due within this many days |

Backtest-only: `--no-costs`, `--slippage-pct`, `--brokerage-pct`, `--no-trailing`,
`--time-stop-days`.

Anything dropped by a filter is reported, never silently removed: the screen prints
a "dropped by your filters" summary, and the backtest metrics include
`signals_skipped` by reason.

**Results calendar file** (Yahoo's earnings dates for NSE stocks are unreliable, so
this is a file you maintain):

```
# symbol,date
RELIANCE,2026-10-17
INFY,2026-10-15
```

**Defaults changed the numbers.** With the defaults above, backtest results will
differ from earlier runs (costs, next-open fills, regime filter, trailing). To see
the effect of each piece, switch them off one at a time (`--no-costs`,
`--regime-ema 0`, `--no-trailing`, `--min-traded-value 0 --max-stop-pct 0`).

## Validating a backtest — is the edge real or just luck?

One backtest number can look good by luck or by tuning. `validate` asks harder
questions of the same rules, with the same defaults as `backtest`:

```
python screener.py validate --index nifty200 --period 5y
python screener.py validate --index nifty200 --period 5y \
    --sweep reward_risk=1.5,2,3 --sweep atr_mult=1.5,2,2.5 --sweep stop_mode=structure,atr \
    --wf-train-months 12 --wf-test-months 3
```

Use `--period 5y` or more: each section needs enough trades (15+ per half, 20+
out-of-sample in walk-forward) to say anything, and the tool tells you when it
doesn't have them rather than printing a confident-looking verdict.

| Section | Question it answers |
|---|---|
| Equity + daily drawdown charts | What did the path actually look like? |
| 1. In-sample vs out-of-sample (`--split 0.7` or a date) | Does it hold on the part of the history it wasn't "looked at" on? |
| 2. By calendar year | Is all the profit from one good year? |
| 3. By market regime at entry | Does it only work when Nifty is above its 50-EMA? (Empty "below" group is expected while the regime filter is on — run with `--regime-ema 0` to see it.) |
| 4. Monte Carlo (`--mc-sims`) | How bad could the drawdown have been had the same trades arrived in a different order? Plan for the 95th percentile, not the path that happened |
| 5. Parameter sensitivity (`--sweep name=v1,v2,...`, repeatable) | Does it still work when parameters move, or only at one magic setting? Flags parameters that have no effect at all |
| 6. Walk-forward (`--wf-train-months`, `--wf-test-months`) | Pick parameters using only past, already-closed trades, then score them on the next unseen window, and roll forward. Compared against just keeping your base parameters |
| 7. Ablation (`--ablation`) | Which feature is carrying the result? Switches costs, regime filter, trailing, time-stop, the extra filters, ATR stops and the loose pullback off one at a time |

Sweepable names: `reward_risk`, `risk_pct`, `heat_ceiling`, `max_positions`,
`atr_mult`, `stop_mode`, `max_stop_pct`, `min_traded_value`, `regime_ema`,
`time_stop_days`, plus `pullback_lookback` (pullback_trend) and
`breakout_lookback` / `volume_multiple` (breakout). `--max-combos` (default 60)
stops you launching a huge grid.

Outputs: `validation_report.html` (open in any browser — it is self-contained, no
internet, scripts or external fonts needed) and `validation_sweep.csv`.

**How to read it**

- Every extra parameter you sweep raises the chance that the best row is luck.
  Look at whether the best row's *neighbours* are also good, and at the share of
  parameter sets that are profitable — not just the winner.
- Walk-forward efficiency (out-of-sample avg R ÷ training avg R) near 1 or above is
  reassuring; well below ~0.5 suggests the in-window results were mostly fit.
- Median R is shown next to average R because a few outliers can move the average.

**Limits of these tools (be honest with yourself about them)**

- Survivorship bias is unchanged: everything runs on today's index constituents.
- Sweeps and walk-forward run each parameter set once over the whole period and
  slice its trades by date. That approximates, but is not identical to, switching
  parameters mid-stream with positions carried across.
- Monte Carlo drawdown is trade-to-trade, not daily mark-to-market, and treats
  overlapping trades as sequential. Treat it as a range, not a forecast.
- None of this proves a strategy will work going forward; it can only show that
  it was not obviously a fluke on the data you have.

**Pullback definition changed (this affects pullback_trend results).** Earlier
versions said "had a pullback" if any close in the last N days was below the
20-EMA. Because the reclaim rule already requires *yesterday* to have closed at or
below the 20-EMA, that was always true, so `pullback_lookback` did nothing. Now
the pullback is the run of consecutive closes at/below the 20-EMA that ends the
day before the reclaim, and it must last between `--min-pullback-days` (default 2:
a one-day dip is noise) and `--pullback-lookback` (default 10: a longer stretch
below the 20-EMA is a trend change). `--min-pullback-days 1` with a large lookback
gives the old behaviour. Note also that volume confirmation is *scored* but not
*required* to enter, despite the strategy description saying "on rising volume".
That was left as is; say if you want it required.

## Point-in-time index membership (reduces survivorship bias)

`--index` normally uses TODAY's constituents, so stocks dropped from the index
(often because they did badly) are invisible to the backtest. With
`--membership-file`, the tool reconstructs who was in the index on each past
date by undoing the changes you give it, downloads former members too, and
only allows entries on days a stock was actually in the index.

```
python screener.py backtest --index nifty200 --period 5y --membership-file index_changes.csv
python screener.py validate --index nifty200 --period 5y --membership-file index_changes.csv
```

**You have to supply the changes file** — I could not fetch historical index
data and did not invent any. See `index_changes.example.csv` for the format
(`date,symbol,action`, effective date = first day the change applies). NSE
Indices publishes "Replacements in indices" press releases on niftyindices.com
(`Press_Release/ind_prsDDMMYYYY.pdf`), normally effective the last working day
of March and September; each lists additions and removals per index, by company
name (you need the NSE ticker). Work backwards from today. Nifty 500 changes
a lot per rebalance (the September 2026 review replaced 27 names); Nifty 50 or
100 are far less work to transcribe. The tool checks your rows against today's
list and prints a warning for anything that doesn't add up.

Going forward you can build the file automatically: `universe.py` now saves a
dated snapshot of each index list it downloads (`.cache/snapshots/`), and

```
python screener.py snapshot-changes --index nifty200 --out index_changes.csv
```

diffs those snapshots into change rows (dates are when a change was first *seen*,
on or after the true effective date). This only covers the time since you started
saving snapshots.

**What it does not fix.** Yahoo often has no price data for delisted, merged or
renamed tickers, so a former member may be impossible to backtest. Every run now
prints how many former members had no data and lists them. Survivorship bias is
*reduced, not eliminated*, and what remains still biases results optimistic.

## Real-data check (run this first)

Everything in this toolkit has been tested on synthetic data only. Before relying
on any number, run it on real prices, on a machine with normal internet access:

```
python real_data_check.py --check-only     # are Yahoo and NSE reachable?
python real_data_check.py --quick          # nifty200, 5y, both strategies, reward_risk sweep only
python real_data_check.py                  # full sweeps (slower)
```

It saves a dated folder with `summary_<strategy>.txt`,
`validation_report_<strategy>.html` and `validation_sweep_<strategy>.csv`. Read
the verdict lines first, then the "what is driving the result" table: if the
result is only positive with costs off, or only with one filter on, that feature,
not the strategy, is carrying it.

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

## Core options (both screen and backtest)


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

- **Survivorship bias**: by default `--index` fetches TODAY's constituent list (use `--membership-file` to reduce this, see above; it cannot remove it).
  Backtesting 3 years back still uses today's NIFTY 500, not what was in the
  index 3 years ago — stocks that were removed (often because they performed
  badly) are invisible to the backtest. This inflates results.
- **Costs are estimates.** Charges and slippage are deducted, but the rates in
  `costs.py` are typical discount-broker figures, not yours — verify them. Income/
  capital-gains tax is not deducted.
- **Fills are daily-bar approximations.** No circuit-limit handling, no partial
  fills, no intraday path; slippage is a flat percentage.
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
| `backtest_trades.csv` | `backtest` — every simulated trade (incl. fees, exit reason) |
| `backtest_equity.csv` | `backtest` — day-by-day equity curve |
| `validation_report.html` | `validate` — charts + all validation tables, works offline |
| `validation_sweep.csv` | `validate` — one row per parameter combination |
| `index_changes.csv` | `snapshot-changes` — index additions/removals for `--membership-file` |
| `.cache/snapshots/*.csv` | `universe.py` — dated copy of each index list downloaded |
| `real_check_*/` | `real_data_check.py` — reports and summaries from a real-data run |
| `.cache/*.csv` | `universe.py` — cached NSE index lists (1 day) |
