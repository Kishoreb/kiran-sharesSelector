"""
Main CLI for the trading toolkit: Strategy Engine + Risk Engine +
Candidate Engine + Backtester + Validation, wired together.

Subcommands:

  screen            what currently meets your rules, right now, sized for
                    your capital (Candidate Engine + Risk Engine)
  backtest          how your rules would have performed historically, with
                    sizing, costs, filters and portfolio risk limits enforced
  validate          does that backtest result survive harder questions:
                    in/out-of-sample, by year and regime, Monte Carlo,
                    parameter sweeps, walk-forward, feature ablation
  monitor           given a position you already hold, does the original
                    thesis still hold, and what should your stop be now
  update-price      adds/refreshes one dated price column in an existing
                    screening_results.csv, leaving everything else untouched
  snapshot-changes  turns the dated index-list snapshots universe.py saves
                    into index-change rows for --membership-file

Requires internet access on the machine you run this on and the packages in
requirements.txt: pip install -r requirements.txt

Examples:
    python screener.py screen --index nifty200 --strategy pullback_trend
    python screener.py backtest --index nifty200 --period 5y --membership-file index_changes.csv
    python screener.py validate --index nifty200 --period 5y --sweep reward_risk=1.5,2,3 --ablation
    python screener.py monitor --symbol TATASTEEL --entry 452 --stop 438 --qty 133 --entry-date 2026-07-15
    python screener.py update-price --file screening_results.csv
    python screener.py snapshot-changes --index nifty200 --out index_changes.csv
"""

import argparse
import os
import sys

import pandas as pd

from universe import get_index_symbols, get_index_constituents, INDEX_URLS, changes_from_snapshots
from strategies import STRATEGIES, TechnicalFilters
import fundamentals as fund
import validation as val
import report as rpt
import qualitative as qual
from risk import RiskEngine
from candidate_engine import CandidateEngine
from monitor import PositionMonitor
from data import fetch_history
from filters import TradeFilters, ResultsCalendar, REASON_LABELS
from market import Benchmark
from membership import MembershipHistory, merge_changes_file, period_start


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------
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


def build_tech_filters(args) -> TechnicalFilters:
    return TechnicalFilters(
        min_avg_value_cr=args.min_turnover_cr,
        require_above_sma200=args.sma200,
        max_pct_from_52w_high=args.max_from_high_pct,
    )


def build_strategy(args):
    """Instantiate the chosen strategy with its tuning options and the section-3 technical filters."""
    kw = {"stop_mode": args.stop_mode, "atr_mult": args.atr_mult, "filters": build_tech_filters(args)}
    if args.strategy == "pullback_trend":
        kw.update(pullback_lookback=args.pullback_lookback, min_pullback_days=args.min_pullback_days)
    elif args.strategy == "breakout":
        kw.update(breakout_lookback=args.breakout_lookback, volume_multiple=args.volume_multiple)
    return STRATEGIES[args.strategy](**kw)


def build_trade_filters(args) -> TradeFilters:
    return TradeFilters(args.min_traded_value, args.max_stop_pct, args.results_buffer_days)


def load_calendar(args):
    if not getattr(args, "results_file", None):
        return None
    cal = ResultsCalendar.from_file(args.results_file)
    if cal.skipped_rows:
        print(f"  [warning] {cal.skipped_rows} unreadable row(s) skipped in {args.results_file}")
    return cal


def fetch_benchmark_df(args, period):
    """Benchmark index history, or None (with a warning) if it cannot be fetched."""
    try:
        return fetch_history(args.benchmark, period=period)
    except Exception as e:
        print(f"  [warning] benchmark {args.benchmark} unavailable ({e}): "
              f"no regime filter and no relative-strength ranking.")
        return None


def fetch_universe_data(symbols, period) -> dict:
    print(f"Fetching {period} of history for {len(symbols)} symbols (this can take a while)...")
    data = {}
    for idx, sym in enumerate(symbols, 1):
        try:
            data[sym.upper()] = fetch_history(sym, period=period)
            print(f"  [{idx}/{len(symbols)}] {sym} ok")
        except Exception as e:
            print(f"  [{idx}/{len(symbols)}] {sym} skipped ({e})")
    return data


def _r(v, nd=1):
    if v is None:
        return None
    return v if v == float("inf") else round(v, nd)


def setup_membership(args, symbols):
    """
    Point-in-time membership, only meaningful with --index. Returns
    (history or None, symbols to download).
    """
    if not args.membership_file:
        return None, symbols
    if args.symbols or args.file:
        print("Note: --membership-file only applies with --index; ignoring it.")
        return None, symbols
    try:
        history = MembershipHistory.from_file(symbols, args.membership_file)
    except (OSError, ValueError) as e:
        print(f"Error reading {args.membership_file}: {e}")
        sys.exit(1)
    for w in history.warnings:
        print(f"  [membership warning] {w}")
    start = period_start(args.period)
    return history, sorted(history.symbols_since(start))


def membership_note(history, symbol_data, period) -> str:
    start = period_start(period)
    former = sorted(s for s in history.symbols_since(start) if s not in history.current)
    have = {s.upper() for s in symbol_data}
    with_data = [s for s in former if s in have]
    missing = history.missing_data(symbol_data, start)
    return (f"Membership coverage: {len(history.changes)} index changes loaded. "
            f"Signals are skipped on days a stock was not in the index. "
            f"Data for former members: {len(with_data)} downloaded {with_data or ''}; "
            f"{len(missing)} members without price data {missing or ''}. "
            f"Survivorship bias is reduced, not eliminated.")


def base_params(args) -> dict:
    """The backtest parameter set (validation.DEFAULT_BASE keys) taken from the CLI flags."""
    base = {k: getattr(args, k) for k in val.DEFAULT_BASE}
    base["tech_filters"] = build_tech_filters(args)
    return base


# --------------------------------------------------------------------------
# screen
# --------------------------------------------------------------------------
def apply_fundamentals(candidates, args, symbols, sector_map):
    """
    Section-1 fundamental checks on the (already technical-qualified) candidates.
    Mode 'flag' annotates each candidate; mode 'filter' also drops 'fail' ones.
    Screen only: Yahoo statements are latest-snapshot, not point-in-time.
    """
    cfg = fund.FundamentalFilters(
        min_roce=args.min_roce, min_roe=args.min_roe, max_de=args.max_de, min_icr=args.min_icr,
        min_sales_growth=args.min_sales_growth, min_pat_growth=args.min_pat_growth, max_peg=args.max_peg,
        skip=set(args.skip_rules or []), strict=args.strict_fundamentals,
        min_promoter=args.min_promoter, max_pledge=args.max_pledge,
        promoter_decline_quarters=args.promoter_decline_quarters, min_inst_change=args.min_inst_change,
    )
    ind_pe = {}
    if "pe_vs_industry" not in cfg.skip:
        if sector_map:
            print(f"\nBuilding industry P/E medians from {len(symbols)} symbols (cached for 7 days)...")
            ind_pe = fund.industry_pe_map(symbols, sector_map)
        else:
            print("\n(No sector info for manually-specified symbols: P/E vs industry will show as n/a.)")

    print(f"\nFundamental check on {len(candidates)} candidate(s)...")
    kept = []
    for c in candidates:
        m, err = fund.get_metrics(c.symbol)
        res = fund.evaluate(m, c.sector, cfg, ind_pe.get(c.sector))
        c.fund_status = res["status"]
        c.fund_passed, c.fund_evaluated = len(res["passed"]), res["evaluated"]
        parts = []
        if res["failed"]:
            parts.append("failed: " + ",".join(res["failed"]))
        if res["unknown"]:
            parts.append("n/a: " + ",".join(res["unknown"]))
        if res["exempt"]:
            parts.append("exempt: " + ",".join(res["exempt"]))
        if err:
            parts.append(f"data: {err}")
        c.fund_notes = " | ".join(parts)
        if m:
            c.roce_pct, c.roe_avg_pct = _r(m.get("roce")), _r(m.get("roe_avg"))
            c.debt_equity, c.pe, c.peg = _r(m.get("de"), 2), _r(m.get("pe")), _r(m.get("peg"), 2)
            c.promoter_pct, c.pledged_pct = m.get("promoter_pct"), m.get("pledged_pct")
        print(f"  {c.symbol:<14} {c.fund_status:<5} {c.fund_notes}")
        if args.fundamentals == "filter" and c.fund_status == "fail":
            continue
        kept.append(c)
    dropped = len(candidates) - len(kept)
    if dropped:
        print(f"  {dropped} candidate(s) dropped by fundamental filters.")
    return kept


def apply_qualitative(candidates, args):
    """Section-4 news sentiment + governance red-flag scan on the candidates that already qualified.
    Mode 'flag' annotates; 'filter' also drops candidates with a High-severity red flag."""
    scorer = None if args.llm == "none" else qual.LLMScorer(args.llm, args.llm_model, args.ollama_url)
    names = qual.symbol_name_map()
    print(f"\nNews sentiment and governance scan on {len(candidates)} candidate(s) (last {args.news_days} days)...")
    kept = []
    for c in candidates:
        q = qual.analyse(c.symbol, names.get(c.symbol, c.symbol), days=args.news_days, scorer=scorer)
        c.sentiment_30d, c.sentiment_trend = q.get("sentiment_30d"), q.get("sentiment_trend")
        c.qual_severity, c.qual_flags = q.get("flag_severity") or "", q.get("flag_text") or ""
        s30 = f"{c.sentiment_30d:+.2f}" if c.sentiment_30d is not None else "n/a"
        print(f"  {c.symbol:<14} sentiment {s30:<6} flags: {c.qual_flags or 'none'}"
              + (f"   [{q['q_notes']}]" if q.get("q_notes") else ""))
        if args.qualitative == "filter" and c.qual_severity == "High":
            continue
        kept.append(c)
    if len(kept) < len(candidates):
        print(f"  {len(candidates) - len(kept)} candidate(s) dropped for High-severity governance flags.")
    return kept


def cmd_screen(args):
    fund.configure(provider=args.fund_source, growth_years=args.growth_years, use_nse=not args.no_nse,
                   debug_dir=args.debug_dump, refresh=args.refresh_cache)
    strategy = build_strategy(args)
    risk_engine = build_risk_engine(args)
    symbols = resolve_symbols(args)
    sector_map = resolve_sector_map(args)

    bench_df = fetch_benchmark_df(args, "2y")
    benchmark = Benchmark(bench_df, regime_ema=args.regime_ema) if bench_df is not None else None
    if benchmark is not None and args.regime_ema > 0:
        bull = benchmark.is_bullish(benchmark.last_date)
        if bull is False:
            print(f"\n\u26a0 Market regime: {args.benchmark} is BELOW its {args.regime_ema}-EMA. "
                  f"The backtester blocks new entries in this state; candidates below are still listed.\n")
        elif bull:
            print(f"Market regime: {args.benchmark} is above its {args.regime_ema}-EMA.\n")

    engine = CandidateEngine([strategy], risk_engine, sector_map=sector_map, benchmark=benchmark,
                             trade_filters=build_trade_filters(args), results_calendar=load_calendar(args))
    print(f"Screening {len(symbols)} symbols with '{strategy.name}'...\n")
    candidates = engine.screen_universe(symbols)
    if engine.skipped:
        print("\nDropped by pre-trade filters: " +
              ", ".join(f"{REASON_LABELS.get(k, k)}: {n}" for k, n in engine.skipped.items()))
    candidates = [c for c in candidates if c.score >= args.min_score]
    if args.cap_class != "all":
        # "Unknown" (Yahoo had no market cap) is kept rather than silently dropped; it is labelled in the output.
        candidates = [c for c in candidates if c.cap_class.lower() in (args.cap_class, "unknown")]
    if args.fundamentals != "off" and candidates:
        candidates = apply_fundamentals(candidates, args, symbols, sector_map)
    if args.qualitative != "off" and candidates:
        candidates = apply_qualitative(candidates, args)
    ranked = engine.rank(candidates, fund_weight=args.fund_weight)

    if not ranked:
        print("\nNo candidates met your rules today.")
        return

    concentration = None
    if sector_map:
        concentration = CandidateEngine.flag_sector_concentration(ranked, max_per_sector=args.max_per_sector)

    for c in ranked:
        c.thesis = CandidateEngine.build_thesis(c)

    print(f"\n{len(ranked)} candidate(s), ranked:\n")
    for c in ranked:
        flag = "  \u26a0 sector cap" if c.over_sector_cap else ""
        sector_str = f" [{c.sector}]" if sector_map else ""
        rs = f"  RS {c.rel_strength:+.1f}" if c.rel_strength is not None else ""
        print(f"  {c.symbol:<14} {c.strategy:<16} {c.score}/{c.total}  "
              f"entry {c.entry:<8} stop {c.stop:<8} target {c.target:<8} "
              f"(+{c.target_gain_pct}%)  qty {c.quantity}  {c.cap_class}{sector_str}{rs}{flag}"
              + (f"  [fund:{c.fund_status} {c.fund_passed}/{c.fund_evaluated}]" if c.fund_status else ""))
        print(f"      {c.thesis}")

    if concentration and concentration["breached_sectors"]:
        print(f"\n\u26a0 Sector concentration warning (cap: {args.max_per_sector} per sector):")
        for sector, count in concentration["breached_sectors"].items():
            print(f"    {sector}: {count} candidates in your top picks - consider skipping the flagged ones")
    elif sector_map:
        print(f"\nNo sector over your cap of {args.max_per_sector} per sector.")
    elif not (args.symbols or args.file):
        pass
    else:
        print("\n(Sector info unavailable for manually-specified symbols; concentration check skipped.)")

    rows = CandidateEngine.to_rows(ranked)
    total_capital = round(sum(c.capital_required for c in ranked), 2)
    rows.append({**{k: "" for k in rows[0]}, "symbol": "TOTAL", "capital_required": total_capital})

    pd.DataFrame(rows).to_csv(args.out, index=False)
    print(f"\nTotal capital required across all candidates: Rs {total_capital}")
    print(f"Saved to {args.out}")
    print("This reports what meets YOUR rules right now, ranked transparently.")
    print("It is not a buy recommendation. Confirm on your own chart before acting.")


# --------------------------------------------------------------------------
# backtest / validate
# --------------------------------------------------------------------------
def prepare_backtest(args):
    """Shared by backtest and validate: symbols, data, benchmark, membership, calendar -> runner."""
    symbols = resolve_symbols(args)
    history, to_download = setup_membership(args, symbols)
    symbol_data = fetch_universe_data(to_download, args.period)
    if not symbol_data:
        print("No data fetched, nothing to backtest.")
        sys.exit(1)
    bench_df = fetch_benchmark_df(args, args.period)
    runner = val.make_runner(symbol_data, bench_df, base_params(args), results_calendar=load_calendar(args),
                             membership=history)
    note = membership_note(history, symbol_data, args.period) if history is not None else None
    if note:
        print("\n" + note)
    return symbol_data, bench_df, runner, note


def cmd_backtest(args):
    symbol_data, bench_df, runner, note = prepare_backtest(args)
    print(f"\nRunning backtest with '{args.strategy}'...")
    result = runner()

    print(f"\n{len(result.trades)} trades generated.\n")
    for k, v in result.metrics().items():
        print(f"  {k}: {v}")

    rows = [{
        "symbol": t.symbol, "strategy": t.strategy, "entry_date": t.entry_date,
        "entry_price": t.entry_price, "exit_date": t.exit_date, "exit_price": t.exit_price,
        "stop": t.stop, "target": t.target, "quantity": t.quantity,
        "exit_reason": t.exit_reason, "fees": round(t.fees, 2),
        "pnl_rupees": t.pnl_rupees, "r_multiple": t.r_multiple,
    } for t in result.trades]
    pd.DataFrame(rows).to_csv(args.trades_out, index=False)
    pd.DataFrame(result.equity_curve).to_csv(args.equity_out, index=False)
    print(f"\nSaved trade log to {args.trades_out}")
    print(f"Saved equity curve to {args.equity_out}")
    print("\nIMPORTANT: this backtest still has limitations (see README) --")
    print("survivorship bias (today's index list unless --membership-file is used, and Yahoo may lack")
    print("data for delisted names), daily bars only, no circuit-limit or liquidity-fill modelling.")
    print("Statutory costs and slippage ARE deducted (see costs.py; --no-costs switches them off).")
    print("Treat results as a rough sanity check on your rules, not a promise of future returns.")


def _print_stats(title, headers, rows):
    print(f"\n{title}")
    print(val.format_table(headers, rows))


def cmd_validate(args):
    try:
        sweeps = val.parse_sweeps(args.sweep, args.strategy)
        split = val.parse_split(args.split)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    symbol_data, bench_df, runner, mem_note = prepare_backtest(args)
    print(f"\nRunning the as-configured backtest with '{args.strategy}'...")
    res = runner()
    metrics = res.metrics()
    print()
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    ctx = {"meta": f"{args.strategy}, {len(symbol_data)} symbols with data, period {args.period}, "
                   f"capital Rs {args.capital:,.0f}, risk {args.risk_pct}% per trade, "
                   f"reward:risk {args.reward_risk}, stops {args.stop_mode}",
           "equity_curve": res.equity_curve, "metrics": metrics, "notes": []}
    if mem_note:
        ctx["notes"].append(mem_note)
    if bench_df is None:
        ctx["notes"].append("Benchmark data was unavailable: no regime filter, no regime breakdown, "
                            "no relative-strength ranking.")
    ctx["notes"].append("Section-3 technical filters (above 200-SMA, near 52-week high, turnover) are applied "
                        "as configured on the command line.")
    if not res.equity_curve:
        print("No equity curve (no usable data); nothing more to validate.")
        return

    # 1. in / out of sample
    ctx["split"] = sp = val.split_validation(res, split)
    _print_stats(f"1. In-sample vs out-of-sample (split at {sp['cut']})", rpt.STAT_HEADERS + ["Max DD %"],
                 [rpt._stat_row("In-sample", sp["in_sample"]) + [sp["in_sample"]["max_dd_pct"]],
                  rpt._stat_row("Out-of-sample", sp["out_of_sample"]) + [sp["out_of_sample"]["max_dd_pct"]]])
    print("  Verdict: " + sp["verdict"])

    # 2. calendar year, 3. regime
    ctx["yearly"] = val.yearly_breakdown(res.trades)
    if ctx["yearly"]:
        _print_stats("2. By calendar year (trades grouped by entry date)", rpt.STAT_HEADERS,
                     [rpt._stat_row(r["period"], r) for r in ctx["yearly"]])
    ctx["regime"] = val.regime_breakdown(res.trades, bench_df, args.regime_ema if args.regime_ema > 0 else 50)
    if ctx["regime"]:
        _print_stats("3. By market regime at entry", rpt.STAT_HEADERS,
                     [rpt._stat_row(r["period"], r) for r in ctx["regime"]])

    # 4. Monte Carlo
    ctx["mc"] = None
    if args.mc_sims > 0:
        ctx["mc"] = mc = val.monte_carlo(res.trades, sims=args.mc_sims)
        print("\n4. Monte Carlo: how bad could the drawdown have been?")
        if mc["too_few"]:
            print(f"  Only {mc['n']} usable trades; need {mc['min']}+ for a meaningful simulation.")
        else:
            print(f"  Max drawdown (trades reshuffled): median {mc['shuffle_dd']['p50']}%, "
                  f"95th pct {mc['shuffle_dd']['p95']}%, 99th pct {mc['shuffle_dd']['p99']}%")
            print(f"  Max drawdown (trades resampled):  median {mc['bootstrap_dd']['p50']}%, "
                  f"95th pct {mc['bootstrap_dd']['p95']}%, 99th pct {mc['bootstrap_dd']['p99']}%")
            print(f"  Chance of finishing below the start: {mc['prob_loss_pct']}%; "
                  f"chance of a drawdown over 20%: {mc['prob_dd_over_20_pct']}%")

    # 5. sweeps, 6. walk-forward
    ctx["sweep_rows"], ctx["wf"] = None, None
    if sweeps:
        print(f"\n5. Parameter sensitivity ({len(sweeps)} parameter(s)):")
        try:
            rows = val.run_sweep(runner, sweeps, max_combos=args.max_combos)
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
        sm = val.summarize_sweep(rows)
        ctx["sweep_rows"], ctx["sweep_summary"] = rows, sm
        print("  " + sm["verdict"])
        if sm.get("inert_params"):
            print("  No effect: " + ", ".join(sm["inert_params"]) + " produced identical trades at every value.")
        if args.sweep_out:
            keys = ("trades", "win_rate_pct", "avg_r", "median_r", "expectancy", "net_pnl",
                    "profit_factor", "max_dd_pct", "return_pct")
            pd.DataFrame([{**r["params"], **{k: r.get(k) for k in keys}} for r in rows]).to_csv(args.sweep_out, index=False)
            print(f"  Saved sweep table to {args.sweep_out}")
        dates = [p["date"] for p in res.equity_curve]
        ctx["wf"] = wf = val.walk_forward(rows, res.trades, dates, args.wf_train_months, args.wf_test_months)
        print("\n6. Walk-forward")
        print(f"  Out-of-sample: {wf['oos']['trades']} trades, avg R {wf['oos']['avg_r']}; "
              f"fixed base on the same windows: avg R {wf['base_oos']['avg_r']}; efficiency {wf['efficiency']}")
        print("  Verdict: " + wf["verdict"])

    # 7. ablation
    ctx["ablation"] = None
    if args.ablation:
        print("\n7. What is driving the result? (one feature switched off at a time)")
        ctx["ablation"] = val.run_ablation(runner, args.strategy)

    for n in ctx["notes"]:
        print("\n" + n)
    if args.report:
        rpt.build_report(args.report, ctx)
        print(f"\nSaved HTML report to {args.report}")
    print("\nA rule-checking tool, not investment advice. A backtest is not a promise of future performance.")


def cmd_snapshot_changes(args):
    changes = changes_from_snapshots(args.index)
    if not changes:
        print(f"No index changes found yet for {args.index}. Snapshots are saved each time the index list is "
              f"downloaded (screen/backtest/validate with --index); you need at least two on different days.")
        return
    n = merge_changes_file(args.out, changes)
    print(f"{len(changes)} change(s) seen in snapshots; {n} new row(s) added to {args.out}.")


# --------------------------------------------------------------------------
# monitor / update-price
# --------------------------------------------------------------------------
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
                   help="Skip positions whose capital-limited risk is below this fraction of intended risk (0 disables)")
    # strategy tuning
    p.add_argument("--stop-mode", choices=["structure", "atr"], default="structure", dest="stop_mode")
    p.add_argument("--atr-mult", type=float, default=2.0, dest="atr_mult", help="ATR stop multiple (atr mode only)")
    p.add_argument("--pullback-lookback", type=int, default=10, dest="pullback_lookback",
                   help="pullback_trend: longest pullback (days below the 20-EMA) still accepted")
    p.add_argument("--min-pullback-days", type=int, default=2, dest="min_pullback_days",
                   help="pullback_trend: shortest pullback accepted (1 lets one-day dips count)")
    p.add_argument("--breakout-lookback", type=int, default=20, dest="breakout_lookback")
    p.add_argument("--volume-multiple", type=float, default=1.5, dest="volume_multiple")
    # section-3 technical filters (on by default; each can be switched off)
    p.add_argument("--min-turnover-cr", type=float, default=1.0, dest="min_turnover_cr",
                   help="Min 20-day avg daily traded value in Rs crore (0 disables)")
    p.add_argument("--sma200", action=argparse.BooleanOptionalAction, default=True,
                   help="Require close above 200-day SMA (--no-sma200 disables)")
    p.add_argument("--max-from-high-pct", type=float, default=20.0, dest="max_from_high_pct",
                   help="Require close within this %% of the 52-week high (0 disables)")
    # pre-trade filters and market regime (same ones the backtester applies)
    p.add_argument("--min-traded-value", type=float, default=5.0, dest="min_traded_value",
                   help="Pre-trade liquidity floor, Rs crore of 20-day avg traded value (0 disables)")
    p.add_argument("--max-stop-pct", type=float, default=8.0, dest="max_stop_pct",
                   help="Reject setups whose stop is wider than this %% of entry (0 disables)")
    p.add_argument("--results-file", dest="results_file", help="CSV of 'symbol,date' result dates you maintain")
    p.add_argument("--results-buffer-days", type=int, default=14, dest="results_buffer_days",
                   help="Skip entries with results due within this many days (0 disables)")
    p.add_argument("--regime-ema", type=int, default=50, dest="regime_ema",
                   help="Benchmark EMA for the regime filter (0 disables)")
    p.add_argument("--benchmark", default="^NSEI", help="Benchmark index symbol (default Nifty 50, ^NSEI)")


def add_backtest_args(p):
    p.add_argument("--period", default="2y", help="History length, e.g. 3y, 5y (yfinance format)")
    p.add_argument("--membership-file", dest="membership_file",
                   help="index-changes CSV (date,symbol,action) for point-in-time membership; needs --index")
    p.add_argument("--no-costs", action="store_true", dest="no_costs", help="Switch off statutory costs and slippage")
    p.add_argument("--slippage-pct", type=float, default=0.10, dest="slippage_pct")
    p.add_argument("--brokerage-pct", type=float, default=0.0, dest="brokerage_pct")
    p.add_argument("--no-trailing", action="store_true", dest="no_trailing", help="Do not trail stops (breakeven/swing low)")
    p.add_argument("--time-stop-days", type=int, default=14, dest="time_stop_days",
                   help="Exit flagged after this many days with <0.5R progress (0 disables)")


def main():
    parser = argparse.ArgumentParser(description="Strategy + Risk + Candidate + Backtest + Validation engine for Indian cash equity swing trading.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_screen = sub.add_parser("screen", help="Screen and rank candidates against your rules, right now")
    add_common_args(p_screen)
    p_screen.add_argument("--min-score", type=int, default=0, dest="min_score")
    p_screen.add_argument("--max-per-sector", type=int, default=2, dest="max_per_sector",
                          help="Flag candidates beyond this many per sector, in rank order")
    p_screen.add_argument("--cap-class", choices=["all", "large", "mid", "small"], default="all", dest="cap_class",
                          help="Keep only this market-cap band (Large >20000 Cr, Mid 5000-20000, Small <5000)")
    p_screen.add_argument("--fundamentals", choices=["off", "flag", "filter"], default="off",
                          help="Section-1 fundamentals: off (default), flag (annotate only), filter (drop failures). "
                               "Uses Yahoo annual statements; screen only, not point-in-time.")
    p_screen.add_argument("--min-roce", type=float, default=15.0, dest="min_roce", help="Min ROCE %%")
    p_screen.add_argument("--min-roe", type=float, default=15.0, dest="min_roe", help="Min average ROE %%")
    p_screen.add_argument("--max-de", type=float, default=0.5, dest="max_de", help="Max debt-to-equity")
    p_screen.add_argument("--min-icr", type=float, default=3.0, dest="min_icr", help="Min interest coverage (x)")
    p_screen.add_argument("--min-sales-growth", type=float, default=10.0, dest="min_sales_growth", help="Min sales growth %%")
    p_screen.add_argument("--min-pat-growth", type=float, default=12.0, dest="min_pat_growth", help="Min PAT growth %%")
    p_screen.add_argument("--max-peg", type=float, default=1.0, dest="max_peg", help="Max PEG (exclusive)")
    p_screen.add_argument("--skip-rules", nargs="+", dest="skip_rules", choices=fund.ALL_RULES,
                          help="Fundamental rules to disable, e.g. --skip-rules peg pe_vs_industry")
    p_screen.add_argument("--strict-fundamentals", action="store_true", dest="strict_fundamentals",
                          help="Treat missing Yahoo data as a fail (default: missing data does not reject)")
    p_screen.add_argument("--fund-weight", type=float, default=1.0, dest="fund_weight",
                          help="Ranking points per fundamental rule passed (technical conditions count 1 each; "
                               "0 = ignore fundamentals when ranking)")
    p_screen.add_argument("--fund-source", choices=["screener", "yahoo"], default="screener", dest="fund_source",
                          help="fundamentals source: screener.in (up to 10y of history) or Yahoo (about 4y)")
    p_screen.add_argument("--growth-years", type=int, choices=[3, 5, 10], default=5, dest="growth_years",
                          help="horizon of the sales / PAT growth CAGR rules (falls back to shorter if unavailable)")
    p_screen.add_argument("--no-nse", action="store_true", dest="no_nse",
                          help="skip NSE (promoter holding, pledging, announcements)")
    p_screen.add_argument("--min-promoter", type=float, default=50.0, dest="min_promoter", help="Min promoter holding %%")
    p_screen.add_argument("--max-pledge", type=float, default=5.0, dest="max_pledge", help="Max %% of promoter shares pledged")
    p_screen.add_argument("--promoter-decline-quarters", type=int, default=3, dest="promoter_decline_quarters",
                          help="Fail the promoter-trend rule if holding fell in each of this many latest quarters")
    p_screen.add_argument("--min-inst-change", type=float, default=0.0, dest="min_inst_change",
                          help="Min change (pp) in FII+DII holding over the latest quarter")
    p_screen.add_argument("--qualitative", choices=["off", "flag", "filter"], default="off",
                          help="Section 4: news sentiment + governance red-flag scan. flag = annotate, "
                               "filter = also drop High-severity red flags")
    p_screen.add_argument("--news-days", type=int, default=90, dest="news_days")
    p_screen.add_argument("--llm", choices=["none", "ollama", "anthropic"], default="none",
                          help="score headlines with a language model instead of the keyword lexicon")
    p_screen.add_argument("--llm-model", dest="llm_model", default=None)
    p_screen.add_argument("--ollama-url", dest="ollama_url", default=None)
    p_screen.add_argument("--refresh-cache", action="store_true", dest="refresh_cache",
                          help="ignore cached screener.in / NSE / news results (--debug-dump implies this)")
    p_screen.add_argument("--debug-dump", dest="debug_dump", default=None,
                          help="folder to save raw screener.in pages / NSE JSON for diagnosing layout changes")
    p_screen.add_argument("--out", default="screening_results.csv")
    p_screen.set_defaults(func=cmd_screen)

    p_bt = sub.add_parser("backtest", help="Backtest your rules against historical data")
    add_common_args(p_bt)
    add_backtest_args(p_bt)
    p_bt.add_argument("--trades-out", default="backtest_trades.csv", dest="trades_out")
    p_bt.add_argument("--equity-out", default="backtest_equity.csv", dest="equity_out")
    p_bt.set_defaults(func=cmd_backtest)

    p_val = sub.add_parser("validate", help="Stress-test a backtest: split, years, regimes, Monte Carlo, sweeps, walk-forward, ablation")
    add_common_args(p_val)
    add_backtest_args(p_val)
    p_val.add_argument("--split", default="0.7", help="In/out-of-sample split: fraction (0.7) or date (2024-03-01)")
    p_val.add_argument("--sweep", action="append", metavar="NAME=V1,V2,...",
                       help="Parameter to sweep, repeatable, e.g. --sweep reward_risk=1.5,2,3")
    p_val.add_argument("--max-combos", type=int, default=60, dest="max_combos",
                       help="Refuse sweeps with more parameter combinations than this")
    p_val.add_argument("--wf-train-months", type=int, default=24, dest="wf_train_months")
    p_val.add_argument("--wf-test-months", type=int, default=6, dest="wf_test_months")
    p_val.add_argument("--mc-sims", type=int, default=2000, dest="mc_sims", help="Monte Carlo simulations (0 skips)")
    p_val.add_argument("--ablation", action="store_true", help="Switch features off one at a time")
    p_val.add_argument("--report", help="Write a self-contained HTML report here")
    p_val.add_argument("--sweep-out", dest="sweep_out", help="Write the sweep table to this CSV")
    p_val.set_defaults(func=cmd_validate)

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

    p_snap = sub.add_parser("snapshot-changes", help="Build index-change rows from saved constituent snapshots")
    p_snap.add_argument("--index", choices=list(INDEX_URLS), default="nifty50")
    p_snap.add_argument("--out", default="index_changes.csv")
    p_snap.set_defaults(func=cmd_snapshot_changes)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
