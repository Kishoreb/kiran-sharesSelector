"""
Main CLI for the trading toolkit: Strategy Engine + Risk Engine +
Candidate Engine + Backtester, wired together.

Six subcommands:

  screen        -- what currently meets your rules, right now, sized for
                   your capital (Candidate Engine + Risk Engine)
  backtest      -- how your rules would have performed historically, with
                   realistic sizing and portfolio risk limits enforced
                   (Backtester + Strategy + Risk Engine)
  validate      -- stress-test the backtest: in/out-of-sample split, per-year and
                   per-regime breakdown, parameter sensitivity, walk-forward,
                   Monte Carlo drawdown range, offline HTML report
  snapshot-changes -- build/extend an index-changes CSV (for --membership-file)
                   from dated constituent snapshots
  monitor       -- given a position you already hold, does the original
                   thesis still hold, and what should your stop be now
                   (Position Monitor + Strategy)
  update-price  -- adds/refreshes one dated price column in an existing
                   screening_results.csv, leaving every other column and
                   row untouched

Requires internet access on the machine you run this on (this sandbox has
none) and the packages in requirements.txt: pip install -r requirements.txt

Examples:
    python screener.py screen --index nifty200 --strategy pullback_trend
    python screener.py screen --index nifty500 --strategy breakout --min-score 5
    python screener.py backtest --index nifty50 --strategy pullback_trend --period 2y
    python screener.py backtest --symbols RELIANCE TCS INFY --strategy breakout
    python screener.py backtest --index nifty200 --stop-mode atr --regime-ema 200 --no-costs
    python screener.py screen --index nifty200 --results-file results_calendar.csv --regime-mode block
    python screener.py validate --index nifty200 --period 5y --sweep reward_risk=1.5,2,3 --sweep atr_mult=1.5,2,2.5
    python screener.py monitor --symbol TATASTEEL --entry 452 --stop 438 --qty 133 --entry-date 2026-07-15
    python screener.py update-price --file screening_results.csv
"""

import argparse
import sys

import pandas as pd

from universe import get_index_symbols, get_index_constituents, INDEX_URLS
from strategies import STRATEGIES
from risk import RiskEngine
from candidate_engine import CandidateEngine
from backtester import Backtester
from monitor import PositionMonitor
from data import fetch_history
from costs import CostModel
from filters import TradeFilters, ResultsCalendar, REASON_LABELS
from market import Benchmark
import validation as val
from membership import MembershipHistory, merge_changes_file, period_start
from universe import changes_from_snapshots, list_snapshots
from report import build_report


def resolve_symbols(args) -> list:
    if args.symbols:
        return args.symbols
    if args.file:
        with open(args.file) as f:
            return [line.strip() for line in f if line.strip()]
    print(f"Fetching {args.index} constituents from NSE...")
    try:
        symbols = get_index_symbols(args.index, refresh=args.refresh)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(f"Got {len(symbols)} symbols.\n")
    return symbols


def resolve_sector_map(args) -> dict:
    """
    Sector info is only available when pulling a live NSE index (the CSV
    has an Industry column). --symbols/--file give no sector info, so the
    map is empty and everything shows as 'Unknown' -- concentration
    checking is skipped in that case rather than guessing.
    """
    if args.symbols or args.file:
        return {}
    try:
        constituents = get_index_constituents(args.index, refresh=args.refresh)
        return {c["symbol"].upper(): c["industry"] for c in constituents}
    except RuntimeError:
        return {}


def build_risk_engine(args) -> RiskEngine:
    return RiskEngine(
        capital=args.capital,
        risk_pct_per_trade=args.risk_pct,
        portfolio_heat_ceiling_pct=args.heat_ceiling,
        max_concurrent_positions=args.max_positions,
        reward_risk_ratio=args.reward_risk,
        min_risk_fraction=args.min_risk_fraction,
    )


def build_strategy(args):
    kwargs = dict(stop_mode=args.stop_mode, atr_mult=args.atr_mult)
    if args.strategy == "pullback_trend":
        kwargs.update(pullback_lookback=args.pullback_lookback, min_pullback_days=args.min_pullback_days)
    return STRATEGIES[args.strategy](**kwargs)


def build_filters(args) -> TradeFilters:
    return TradeFilters(min_traded_value_cr=args.min_traded_value,
                        max_stop_pct=args.max_stop_pct,
                        results_buffer_days=args.results_buffer_days)


def load_results_calendar(args):
    if not args.results_file:
        return None
    try:
        cal = ResultsCalendar.from_file(args.results_file)
    except OSError as e:
        print(f"Warning: couldn't read results file ({e}); results-date check skipped.")
        return None
    if cal.skipped_rows:
        print(f"Warning: {cal.skipped_rows} line(s) in {args.results_file} had no readable date and were ignored.")
    return cal


def load_benchmark_df(args):
    """Raw index price data (for regime / relative strength / validation). None if unavailable."""
    try:
        return fetch_history(args.benchmark, period="10y")
    except Exception as e:
        print(f"Warning: couldn't load benchmark {args.benchmark} ({e}). "
              f"Regime filter and relative-strength ranking are disabled for this run.\n")
        return None


def load_benchmark(args):
    """Index data for the regime filter and relative-strength ranking. None if unavailable."""
    bench_df = load_benchmark_df(args)
    return Benchmark(bench_df, regime_ema=max(args.regime_ema, 0)) if bench_df is not None else None


def resolve_universe(args):
    """
    Returns (symbols_to_download, membership_or_None). With --membership-file
    (index mode only), also downloads former index members so the backtest can
    include stocks that were later dropped, and restricts entries to the days
    each stock was actually in the index.
    """
    symbols = resolve_symbols(args)
    if not getattr(args, "membership_file", None):
        return symbols, None
    if args.symbols or args.file:
        print("Note: --membership-file only applies with --index; ignoring it for an explicit symbol list.\n")
        return symbols, None
    try:
        membership = MembershipHistory.from_file(symbols, args.membership_file)
    except (OSError, ValueError) as e:
        print(f"Error reading {args.membership_file}: {e}")
        sys.exit(1)
    for w in membership.warnings:
        print(f"  [membership warning] {w}")
    start = period_start(args.period)
    all_syms = sorted(membership.symbols_since(start))
    extra = len(all_syms) - len(set(s.upper() for s in symbols) & set(all_syms))
    print(f"Point-in-time membership: {len(symbols)} current constituents + {extra} former members "
          f"to download for the last {args.period}.\n")
    return all_syms, membership


def membership_coverage_note(membership, symbol_data, args):
    """Prints (and returns) an honest statement of how much survivorship bias is left."""
    if membership is None:
        return None
    start = period_start(args.period)
    missing = membership.missing_data(symbol_data.keys(), start)
    former = [s for s in missing if s not in membership.current]
    total = len(membership.symbols_since(start))
    msg = (f"Membership coverage: {total - len(missing)} of {total} index members since {start} had price data. "
           f"{len(former)} former member(s) had none (Yahoo often drops delisted/renamed tickers): "
           f"{', '.join(former[:15])}{' ...' if len(former) > 15 else ''}. "
           f"Survivorship bias is reduced, not eliminated; results are still biased optimistic by whatever is missing.")
    print("\n" + msg)
    return msg


def fetch_symbol_data(symbols, period):
    print(f"Fetching {period} of history for {len(symbols)} symbols (this can take a while)...")
    symbol_data = {}
    for idx, sym in enumerate(symbols, 1):
        try:
            symbol_data[sym.upper()] = fetch_history(sym, period=period)
            print(f"  [{idx}/{len(symbols)}] {sym} ok")
        except Exception as e:
            print(f"  [{idx}/{len(symbols)}] {sym} skipped ({e})")
    return symbol_data


def print_regime_banner(benchmark, args):
    if benchmark is None or args.regime_ema <= 0:
        return
    status = benchmark.is_bullish(benchmark.last_date)
    word = {True: "ABOVE", False: "BELOW", None: "unknown vs"}[status]
    print(f"Market regime: {args.benchmark} closed {word} its {args.regime_ema}-EMA "
          f"(as of {benchmark.last_date}).")
    if status is False:
        print("  Both strategies are trend-following; new entries have a lower base rate in this regime.")
    print()


def print_rejections(rejected):
    if not rejected:
        return
    counts = {}
    for _, _, reason in rejected:
        counts[reason] = counts.get(reason, 0) + 1
    print(f"\n{len(rejected)} signal(s) dropped by your filters:")
    for reason, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        names = ", ".join(sorted({sym for sym, _, r in rejected if r == reason})[:12])
        print(f"    {REASON_LABELS.get(reason, reason)}: {n}  ({names})")


def cmd_screen(args):
    strategy = build_strategy(args)
    risk_engine = build_risk_engine(args)
    symbols = resolve_symbols(args)
    sector_map = resolve_sector_map(args)
    benchmark = load_benchmark(args)
    regime_mode = "off" if args.regime_ema <= 0 else args.regime_mode

    engine = CandidateEngine([strategy], risk_engine, sector_map=sector_map,
                             filters=build_filters(args), benchmark=benchmark,
                             results_calendar=load_results_calendar(args), regime_mode=regime_mode)
    print_regime_banner(benchmark, args)
    print(f"Screening {len(symbols)} symbols with '{strategy.name}' (stop mode: {strategy.stop_mode})...\n")
    candidates = engine.screen_universe(symbols)
    candidates = [c for c in candidates if c.score >= args.min_score]
    ranked = engine.rank(candidates)

    if not ranked:
        print("\nNo candidates met your rules today.")
        print_rejections(engine.rejected)
        return

    concentration = None
    if sector_map:
        concentration = CandidateEngine.flag_sector_concentration(ranked, max_per_sector=args.max_per_sector)

    print(f"\n{len(ranked)} candidate(s), ranked:\n")
    for c in ranked:
        flag = "  \u26a0 sector cap" if c.over_sector_cap else ""
        if c.regime_ok is False:
            flag += "  \u26a0 market below trend"
        sector_str = f" [{c.sector}]" if sector_map else ""
        rs_str = f"RS {c.rel_strength:+.1f}" if c.rel_strength is not None else "RS n/a"
        print(f"  {c.symbol:<14} {c.strategy:<16} {c.score}/{c.total}  "
              f"entry {c.entry:<8} stop {c.stop:<8} ({c.stop_pct}%) target {c.target:<8} "
              f"(+{c.target_gain_pct}%)  qty {c.quantity}  {rs_str}{sector_str}{flag}")

    if concentration and concentration["breached_sectors"]:
        print(f"\n\u26a0 Sector concentration warning (cap: {args.max_per_sector} per sector):")
        for sector, count in concentration["breached_sectors"].items():
            print(f"    {sector}: {count} candidates in your top picks — consider skipping the flagged ones")
    elif sector_map:
        print(f"\nNo sector over your cap of {args.max_per_sector} per sector.")
    elif not (args.symbols or args.file):
        pass
    else:
        print("\n(Sector info unavailable for manually-specified symbols; concentration check skipped.)")

    print_rejections(engine.rejected)

    rows = CandidateEngine.to_rows(ranked)
    total_capital = round(sum(c.capital_required for c in ranked), 2)
    rows.append({**{k: "" for k in rows[0]}, "symbol": "TOTAL", "capital_required": total_capital})

    pd.DataFrame(rows).to_csv(args.out, index=False)
    print(f"\nTotal capital required across all candidates: Rs {total_capital}")
    print(f"Saved to {args.out}")
    print("This reports what meets YOUR rules right now, ranked transparently.")
    print("It is not a buy recommendation. Confirm on your own chart before acting.")


def build_cost_model(args) -> CostModel:
    if args.no_costs:
        return CostModel.zero()
    return CostModel(brokerage_pct=args.brokerage_pct, slippage_pct=args.slippage_pct)


def cmd_backtest(args):
    strategy = build_strategy(args)
    risk_engine = build_risk_engine(args)
    symbols, membership = resolve_universe(args)
    benchmark = load_benchmark(args)

    symbol_data = fetch_symbol_data(symbols, args.period)

    if not symbol_data:
        print("No data fetched, nothing to backtest.")
        return
    membership_coverage_note(membership, symbol_data, args)

    print(f"\nRunning backtest with '{strategy.name}' (stop mode: {strategy.stop_mode})...")
    bt = Backtester(strategy, risk_engine, initial_capital=args.capital,
                    cost_model=build_cost_model(args), filters=build_filters(args),
                    benchmark=benchmark, regime_filter=args.regime_ema > 0,
                    results_calendar=load_results_calendar(args),
                    use_trailing=not args.no_trailing, time_stop_days=args.time_stop_days,
                    membership=membership)
    result = bt.run(symbol_data)

    print(f"\n{len(result.trades)} trades generated.\n")
    metrics = result.metrics()
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    trades_rows = [{
        "symbol": t.symbol, "strategy": t.strategy, "entry_date": t.entry_date,
        "entry_price": t.entry_price, "exit_date": t.exit_date, "exit_price": t.exit_price,
        "stop": t.stop, "target": t.target, "quantity": t.quantity,
        "exit_reason": t.exit_reason, "fees": round(t.fees, 2), "entry_equity": round(t.entry_equity, 2),
        "pnl_rupees": t.pnl_rupees, "r_multiple": t.r_multiple,
    } for t in result.trades]
    pd.DataFrame(trades_rows).to_csv(args.trades_out, index=False)
    pd.DataFrame(result.equity_curve).to_csv(args.equity_out, index=False)
    print(f"\nSaved trade log to {args.trades_out}")
    print(f"Saved equity curve to {args.equity_out}")
    print("\nIMPORTANT: this backtest has real limitations (see README) --")
    print("survivorship bias (today's index list, not history's), daily-bar fills,")
    print("and cost/slippage numbers that are estimates (see costs.py). Capital gains")
    print("tax is not deducted. Treat results as a rough sanity check on your rules,")
    print("not a promise of future returns.")


def _fmt_params(d):
    return ", ".join(f"{k}={v}" for k, v in d.items()) if isinstance(d, dict) else str(d)


def cmd_validate(args):
    try:
        sweeps = val.parse_sweeps(args.sweep, args.strategy)
        split = val.parse_split(args.split) if args.split else None
    except ValueError as e:
        print(f"Error: {e}")
        return

    symbols, membership = resolve_universe(args)
    symbol_data = fetch_symbol_data(symbols, args.period)
    if not symbol_data:
        print("No data fetched, nothing to validate.")
        return
    coverage_msg = membership_coverage_note(membership, symbol_data, args)
    bench_df = load_benchmark_df(args)
    base = dict(
        strategy=args.strategy, stop_mode=args.stop_mode, atr_mult=args.atr_mult, pullback_lookback=args.pullback_lookback,
        min_pullback_days=args.min_pullback_days, capital=args.capital,
        risk_pct=args.risk_pct, heat_ceiling=args.heat_ceiling, max_positions=args.max_positions,
        reward_risk=args.reward_risk, min_risk_fraction=args.min_risk_fraction, min_traded_value=args.min_traded_value, max_stop_pct=args.max_stop_pct,
        results_buffer_days=args.results_buffer_days, regime_ema=args.regime_ema, no_costs=args.no_costs,
        slippage_pct=args.slippage_pct, brokerage_pct=args.brokerage_pct, no_trailing=args.no_trailing,
        time_stop_days=args.time_stop_days)
    runner = val.make_runner(symbol_data, bench_df, base, load_results_calendar(args), membership=membership)

    print(f"\nBase run with '{args.strategy}'...")
    res = runner()
    metrics = res.metrics()
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    if not res.trades:
        print("\nNo trades generated, so there is nothing to validate. Try a longer --period or a wider universe.")
        return

    ctx = {"meta": f"{args.strategy} on {len(symbol_data)} symbols, {args.period}, capital Rs {args.capital:,.0f}",
           "equity_curve": res.equity_curve, "metrics": metrics, "notes": [coverage_msg] if coverage_msg else []}
    if membership is None and args.index:
        ctx["notes"].append("Universe is today's index constituents (no --membership-file), so survivorship bias applies in full.")

    if split is not None:
        sp = val.split_validation(res, split)
        ctx["split"] = sp
        print(f"\n1. In-sample vs out-of-sample (split at {sp['cut']})")
        print(val.format_table(["", "trades", "win %", "avg R", "expectancy", "net P&L", "max DD %"],
              [[lbl, sp[k]["trades"], sp[k]["win_rate_pct"], sp[k]["avg_r"], sp[k]["expectancy"],
                sp[k]["net_pnl"], sp[k]["max_dd_pct"]] for lbl, k in (("in-sample", "in_sample"), ("out-of-sample", "out_of_sample"))]))
        print(f"  -> {sp['verdict']}")

    ctx["yearly"] = val.yearly_breakdown(res.trades)
    print("\n2. By entry year")
    print(val.format_table(["year", "trades", "win %", "avg R", "net P&L"],
          [[r["period"], r["trades"], r["win_rate_pct"], r["avg_r"], r["net_pnl"]] for r in ctx["yearly"]]))
    ctx["regime"] = val.regime_breakdown(res.trades, bench_df)
    if ctx["regime"]:
        print("\n3. By market regime at entry")
        print(val.format_table(["regime", "trades", "win %", "avg R", "net P&L"],
              [[r["period"], r["trades"], r["win_rate_pct"], r["avg_r"], r["net_pnl"]] for r in ctx["regime"]]))

    if args.mc_sims > 0:
        ctx["mc"] = mc = val.monte_carlo(res.trades, sims=args.mc_sims, seed=args.mc_seed)
        print("\n4. Monte Carlo drawdown range")
        if mc["too_few"]:
            print(f"  only {mc['n']} usable trades; need {mc['min']}+ for a meaningful simulation")
        else:
            print(f"  max drawdown if the same trades arrived in random order: median {mc['shuffle_dd']['p50']}%, "
                  f"95th pct {mc['shuffle_dd']['p95']}%, 99th pct {mc['shuffle_dd']['p99']}%")
            print(f"  resampled: final return 5th/50th/95th pct {mc['bootstrap_return']['p5']}% / "
                  f"{mc['bootstrap_return']['p50']}% / {mc['bootstrap_return']['p95']}%;  "
                  f"P(loss) {mc['prob_loss_pct']}%, P(drawdown > 20%) {mc['prob_dd_over_20_pct']}%")

    if sweeps:
        n_combos = 1
        for v in sweeps.values():
            n_combos *= len(v)
        print(f"\n5. Parameter sensitivity: {n_combos} combinations ({_fmt_params({k: v for k, v in sweeps.items()})})")
        try:
            rows = val.run_sweep(runner, sweeps, max_combos=args.max_combos)
        except ValueError as e:
            print(f"Error: {e}")
            rows = []
        if rows:
            ctx["sweep_rows"], ctx["sweep_summary"] = rows, val.summarize_sweep(rows)
            print(f"  -> {ctx['sweep_summary']['verdict']}")
            if ctx["sweep_summary"].get("inert_params"):
                print(f"  !! changing {', '.join(ctx['sweep_summary']['inert_params'])} produced identical trades at "
                      f"every value: it probably has no effect in the strategy logic.")
            pd.DataFrame([{**r["params"], **{k: v for k, v in r.items() if k not in ("params", "trades_list")}}
                          for r in rows]).to_csv(args.sweep_out, index=False)
            print(f"  Saved sweep table to {args.sweep_out}")
            if args.wf_train_months > 0 and args.wf_test_months > 0:
                wf = val.walk_forward(rows, res.trades, [p["date"] for p in res.equity_curve],
                                      args.wf_train_months, args.wf_test_months)
                ctx["wf"] = wf
                print(f"\n6. Walk-forward ({args.wf_train_months}m train / {args.wf_test_months}m test)")
                print(val.format_table(["test window", "chosen", "train R", "test trades", "test R", "base R"],
                      [[w["test"], _fmt_params(w["chosen"]), w["train_avg_r"], w["test_trades"],
                        w["test_avg_r"], w["base_test_avg_r"]] for w in wf["windows"]]))
                print(f"  stitched out-of-sample: {wf['oos']['trades']} trades, avg R {wf['oos']['avg_r']}; "
                      f"fixed base over same windows: avg R {wf['base_oos']['avg_r']}; efficiency {wf['efficiency']}")
                print(f"  -> {wf['verdict']}")
    elif args.wf_train_months > 0:
        print("\n(Walk-forward and sensitivity skipped: pass one or more --sweep name=v1,v2,...)")

    if args.ablation:
        print("\n7. What is driving the result? (one feature switched off at a time)")
        ctx["ablation"] = val.run_ablation(runner, args.strategy)
        print(val.format_table(["variant", "trades", "avg R", "median R", "net P&L", "max DD %"],
              [[r["label"], r["trades"], r["avg_r"], r["median_r"], r["net_pnl"], r["max_dd_pct"]] for r in ctx["ablation"]]))

    build_report(args.report, ctx)
    print(f"\nSaved report to {args.report} (open it in any browser; works offline).")
    print("Reminder: survivorship bias still applies, and every extra parameter you sweep raises the odds of a lucky fit.")


def cmd_snapshot_changes(args):
    snaps = list_snapshots(args.index)
    if len(snaps) < 2:
        print(f"Only {len(snaps)} dated snapshot(s) of {args.index} saved so far (in .cache/snapshots). "
              f"Snapshots are saved whenever a fresh list is downloaded (screen/backtest/validate with --refresh "
              f"or after the 1-day cache expires). Come back after the index has been re-downloaded across a rebalance.")
        return
    changes = changes_from_snapshots(args.index)
    added = merge_changes_file(args.out, changes)
    print(f"{len(snaps)} snapshots ({snaps[0][0]} to {snaps[-1][0]}): {len(changes)} change(s) seen, "
          f"{added} new row(s) written to {args.out}.")
    print("Dates are when a change was first SEEN, which is on or after the true effective date.")


def cmd_monitor(args):
    strategy_cls = STRATEGIES[args.strategy]
    strategy = strategy_cls()
    monitor = PositionMonitor(strategy, time_stop_days=args.time_stop_days)

    print(f"Checking {args.symbol}...\n")
    try:
        result = monitor.check(
            symbol=args.symbol, entry=args.entry, stop=args.stop,
            quantity=args.qty, entry_date=args.entry_date, target=args.target,
        )
    except Exception as e:
        print(f"Error: {e}")
        return

    print(f"  Current price:     {result.current_price}")
    print(f"  Entry / stop:      {result.entry} / {result.original_stop}")
    print(f"  Days held:         {result.days_held}")
    print(f"  Unrealized P&L:    Rs {result.unrealized_pnl}")
    print(f"  R-multiple:        {result.r_multiple}")
    print(f"  Trend conditions:  {result.trend_conditions}")
    if result.stop_already_hit:
        print(f"  \u26a0 Price touched your stop at some point since entry")
    if result.target_already_hit:
        print(f"  \u26a0 Price touched your target at some point since entry")
    print(f"\n  VERDICT: {result.verdict}")
    print(f"  {result.verdict_reason}")
    if result.suggested_stop != result.original_stop:
        print(f"  Suggested stop: {result.suggested_stop} (was {result.original_stop})")


def cmd_update_price(args):
    import os
    from datetime import date as date_cls

    if not os.path.exists(args.file):
        print(f"Error: {args.file} not found.")
        return

    # dtype=str + keep_default_na=False: every existing cell is read and
    # written back as the exact original text, so no other column can be
    # altered even incidentally (e.g. pandas silently turning "6" into
    # "6.0" when a column has blank cells elsewhere, like the TOTAL row).
    df = pd.read_csv(args.file, dtype=str, keep_default_na=False)
    if "symbol" not in df.columns:
        print(f"Error: {args.file} doesn't look like a screening_results.csv (no 'symbol' column).")
        return

    col_date = args.date if args.date else str(date_cls.today())
    col_name = f"price on {col_date}"

    prices = {}
    symbols = [s for s in df["symbol"].tolist() if s != "TOTAL"]
    print(f"Fetching latest close for {len(symbols)} symbols...")
    for idx, sym in enumerate(symbols, 1):
        try:
            hist = fetch_history(sym, period="5d")
            last_close = round(float(hist["Close"].iloc[-1]), 2)
            prices[sym] = str(last_close)
            print(f"  [{idx}/{len(symbols)}] {sym}: {last_close}")
        except Exception as e:
            prices[sym] = ""
            print(f"  [{idx}/{len(symbols)}] {sym}: skipped ({e})")

    # Only this column is touched. Every other existing column, and every
    # row's other values, are written back exactly as they were.
    df[col_name] = df["symbol"].map(lambda s: prices.get(s, ""))

    df.to_csv(args.file, index=False)
    print(f"\nUpdated column '{col_name}' in {args.file}. No other column was changed.")


def add_common_args(p):



    p.add_argument("--index", choices=list(INDEX_URLS), default="nifty50",
                    help="NSE index to fetch live (default: nifty50)")
    p.add_argument("--refresh", action="store_true", help="Force a fresh index download instead of using cache")
    p.add_argument("--symbols", nargs="+", help="Space-separated symbols, overrides --index")
    p.add_argument("--file", help="Text file, one symbol per line, overrides --index")
    p.add_argument("--strategy", choices=list(STRATEGIES), default="pullback_trend")
    p.add_argument("--capital", type=float, default=100000, help="Capital to size positions against")
    p.add_argument("--risk-pct", type=float, default=1.5, dest="risk_pct", help="Risk %% of capital per trade")
    p.add_argument("--heat-ceiling", type=float, default=8.0, dest="heat_ceiling", help="Max total portfolio risk %%")
    p.add_argument("--max-positions", type=int, default=5, dest="max_positions", help="Max concurrent open positions")
    p.add_argument("--reward-risk", type=float, default=2.0, dest="reward_risk", help="Target = entry + this x stop distance")
    p.add_argument("--min-risk-fraction", type=float, default=0.5, dest="min_risk_fraction",
                    help="Skip setups where capital limits cut your risk below this fraction of the intended risk (0 = off)")
    p.add_argument("--stop-mode", choices=["structure", "atr"], default="structure", dest="stop_mode",
                    help="structure = swing low / EMA / breakout level (default); atr = close - atr-mult x ATR(14)")
    p.add_argument("--pullback-lookback", type=int, default=10, dest="pullback_lookback",
                    help="pullback_trend: longest pullback (days below the 20-EMA) that still counts as a pullback")
    p.add_argument("--min-pullback-days", type=int, default=2, dest="min_pullback_days",
                    help="pullback_trend: shortest pullback that counts (1 = old, looser behaviour)")
    p.add_argument("--atr-mult", type=float, default=2.0, dest="atr_mult", help="ATR multiple for --stop-mode atr")
    p.add_argument("--min-traded-value", type=float, default=5.0, dest="min_traded_value",
                    help="Min 20-day avg traded value in Rs crore (0 = off)")
    p.add_argument("--max-stop-pct", type=float, default=8.0, dest="max_stop_pct",
                    help="Reject setups whose stop is wider than this %% of entry (0 = off)")
    p.add_argument("--results-file", default=None, dest="results_file",
                    help="CSV of 'SYMBOL,YYYY-MM-DD' result dates you maintain; entries near a result are skipped")
    p.add_argument("--results-buffer-days", type=int, default=14, dest="results_buffer_days",
                    help="Skip setups with results due within this many days (needs --results-file)")
    p.add_argument("--regime-ema", type=int, default=50, dest="regime_ema",
                    help="Market regime: index must close above this EMA (0 = regime filter off)")
    p.add_argument("--membership-file", default=None, dest="membership_file",
                    help="CSV of index changes (date,symbol,ADD|REMOVE) for point-in-time membership; backtest/validate only, --index mode")
    p.add_argument("--benchmark", default="^NSEI", help="Index used for regime and relative strength (default ^NSEI = Nifty 50)")


def add_backtest_args(p):
    p.add_argument("--no-costs", action="store_true", dest="no_costs", help="Turn off charges AND slippage (gross results)")
    p.add_argument("--slippage-pct", type=float, default=0.10, dest="slippage_pct", help="Adverse move per market fill, %%")
    p.add_argument("--brokerage-pct", type=float, default=0.0, dest="brokerage_pct", help="Brokerage per side, %% of turnover")
    p.add_argument("--no-trailing", action="store_true", dest="no_trailing", help="Fixed stop/target only, no breakeven/trailing")
    p.add_argument("--time-stop-days", type=int, default=14, dest="time_stop_days",
                       help="Exit at next open if held this many days with <0.5R progress (0 = off)")


def main():
    parser = argparse.ArgumentParser(description="Strategy + Risk + Candidate + Backtest engine for Indian cash equity swing trading.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_screen = sub.add_parser("screen", help="Screen and rank candidates against your rules, right now")
    add_common_args(p_screen)
    p_screen.add_argument("--min-score", type=int, default=0, dest="min_score")
    p_screen.add_argument("--max-per-sector", type=int, default=2, dest="max_per_sector",
                           help="Flag candidates beyond this many per sector, in rank order")
    p_screen.add_argument("--regime-mode", choices=["off", "flag", "block"], default="flag", dest="regime_mode",
                           help="flag = keep candidates but mark them when market is below trend (default); block = drop them")
    p_screen.add_argument("--out", default="screening_results.csv")
    p_screen.set_defaults(func=cmd_screen)

    p_bt = sub.add_parser("backtest", help="Backtest your rules against historical data")
    add_common_args(p_bt)
    p_bt.add_argument("--period", default="2y", help="History length, e.g. 1y, 2y, 5y (yfinance format)")
    add_backtest_args(p_bt)
    p_bt.add_argument("--trades-out", default="backtest_trades.csv", dest="trades_out")
    p_bt.add_argument("--equity-out", default="backtest_equity.csv", dest="equity_out")
    p_bt.set_defaults(func=cmd_backtest)

    p_val = sub.add_parser("validate", help="Stress-test a backtest: out-of-sample, per-year/regime, parameter sensitivity, walk-forward, Monte Carlo, HTML report")
    add_common_args(p_val)
    add_backtest_args(p_val)
    p_val.add_argument("--period", default="5y", help="History length; 5y+ recommended so each section has enough trades")
    p_val.add_argument("--split", default="0.7", help="In-sample/out-of-sample cut: fraction of the period (0.7) or a date (2025-03-01); empty string to skip")
    p_val.add_argument("--sweep", action="append", metavar="NAME=V1,V2,...",
                        help="Parameter to vary; repeat for a grid. e.g. --sweep reward_risk=1.5,2,3 --sweep atr_mult=1.5,2,2.5")
    p_val.add_argument("--max-combos", type=int, default=60, dest="max_combos", help="Refuse sweeps larger than this")
    p_val.add_argument("--wf-train-months", type=int, default=12, dest="wf_train_months", help="Walk-forward training window (0 = skip)")
    p_val.add_argument("--wf-test-months", type=int, default=3, dest="wf_test_months", help="Walk-forward test window")
    p_val.add_argument("--mc-sims", type=int, default=2000, dest="mc_sims", help="Monte Carlo simulations (0 = skip)")
    p_val.add_argument("--mc-seed", type=int, default=42, dest="mc_seed")
    p_val.add_argument("--ablation", action="store_true", help="Also switch features off one at a time to see what drives the result")
    p_val.add_argument("--report", default="validation_report.html")
    p_val.add_argument("--sweep-out", default="validation_sweep.csv", dest="sweep_out")
    p_val.set_defaults(func=cmd_validate)

    p_snap = sub.add_parser("snapshot-changes", help="Build/extend an index-changes CSV by diffing the dated constituent snapshots saved on each download")
    p_snap.add_argument("--index", choices=list(INDEX_URLS), default="nifty50")
    p_snap.add_argument("--out", default="index_changes.csv")
    p_snap.set_defaults(func=cmd_snapshot_changes)

    p_mon = sub.add_parser("monitor", help="Check whether an already-open position is still worth holding")
    p_mon.add_argument("--symbol", required=True)
    p_mon.add_argument("--entry", type=float, required=True, help="Your actual entry price")
    p_mon.add_argument("--stop", type=float, required=True, help="Your current stop-loss price")
    p_mon.add_argument("--qty", type=int, required=True)
    p_mon.add_argument("--entry-date", required=True, dest="entry_date", help="YYYY-MM-DD")
    p_mon.add_argument("--target", type=float, default=None, help="Your target price, if you set one")
    p_mon.add_argument("--strategy", choices=list(STRATEGIES), default="pullback_trend",
                        help="Which strategy's trend rules to check ongoing validity against")
    p_mon.add_argument("--time-stop-days", type=int, default=14, dest="time_stop_days")
    p_mon.set_defaults(func=cmd_monitor)

    p_price = sub.add_parser("update-price", help="Add/refresh a single dated price column in an existing screening CSV, without touching anything else")
    p_price.add_argument("--file", default="screening_results.csv", help="Path to the CSV to update")
    p_price.add_argument("--date", default=None, help="Label for the column, default is today's date (YYYY-MM-DD)")
    p_price.set_defaults(func=cmd_update_price)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
