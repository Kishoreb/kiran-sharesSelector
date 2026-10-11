"""
Backtest validation.

A single backtest number can look good by luck or by tuning. This module
asks harder questions of the same rules:

  split_validation   -- in-sample vs out-of-sample: does it hold on data
                        it wasn't looked at on?
  yearly / regime    -- does it only work in one year or one market regime?
  run_sweep          -- parameter sensitivity: does it still work when the
                        lookbacks / R:R / stops move a bit, or only at one
                        magic setting?
  walk_forward       -- pick parameters on a training window using only
                        trades already closed, then score them on the NEXT
                        unseen window, and roll forward.
  monte_carlo        -- shuffle / resample trade order to see a realistic
                        drawdown range instead of the one path that happened.

Honest limits (also in the README): all of this still runs on today's index
constituents (survivorship bias); sweeps and walk-forward slice a single
whole-period run per parameter set by trade dates (an approximation of
re-running with parameters switched mid-stream); Monte Carlo drawdown is
trade-to-trade, not daily mark-to-market, and treats trades as sequential.
More parameter combinations tried = more chance one looks good by luck.
"""

import itertools
import math
from datetime import timedelta
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from backtester import Backtester, BacktestResult, Trade
from costs import CostModel
from filters import TradeFilters, ResultsCalendar
from market import Benchmark
from membership import MembershipHistory
from risk import RiskEngine
from strategies import STRATEGIES

# name -> (type, strategies it applies to; None = all)
SWEEPABLE = {
    "pullback_lookback": (int, {"pullback_trend"}),
    "min_pullback_days": (int, {"pullback_trend"}),
    "breakout_lookback": (int, {"breakout"}),
    "volume_multiple": (float, {"breakout"}),
    "atr_mult": (float, None),
    "stop_mode": (str, None),
    "reward_risk": (float, None),
    "risk_pct": (float, None),
    "heat_ceiling": (float, None),
    "max_positions": (int, None),
    "max_stop_pct": (float, None),
    "min_traded_value": (float, None),
    "regime_ema": (int, None),
    "time_stop_days": (int, None),
}

DEFAULT_BASE = dict(
    strategy="pullback_trend", stop_mode="structure", atr_mult=2.0,
    pullback_lookback=10, min_pullback_days=2, breakout_lookback=20, volume_multiple=1.5,
    capital=100000.0, risk_pct=1.5, heat_ceiling=8.0, max_positions=5, reward_risk=2.0, min_risk_fraction=0.5,
    min_traded_value=5.0, max_stop_pct=8.0, results_buffer_days=14, regime_ema=50,
    no_costs=False, slippage_pct=0.10, brokerage_pct=0.0, no_trailing=False, time_stop_days=14,
)


# ---------------------------------------------------------------- helpers

def parse_sweeps(specs: Optional[List[str]], strategy: str) -> Dict[str, list]:
    """['reward_risk=1.5,2,3', ...] -> {'reward_risk': [1.5, 2.0, 3.0]}. Raises ValueError on bad input."""
    out: Dict[str, list] = {}
    for spec in specs or []:
        if "=" not in spec:
            raise ValueError(f"--sweep expects name=v1,v2,... (got '{spec}')")
        name, vals = spec.split("=", 1)
        name = name.strip()
        if name not in SWEEPABLE:
            raise ValueError(f"can't sweep '{name}'. Choose from: {', '.join(sorted(SWEEPABLE))}")
        typ, only = SWEEPABLE[name]
        if only and strategy not in only:
            raise ValueError(f"'{name}' only applies to: {', '.join(sorted(only))}")
        try:
            parsed = [typ(v.strip()) for v in vals.split(",") if v.strip()]
        except ValueError:
            raise ValueError(f"couldn't read the values in '{spec}'")
        if len(parsed) < 2:
            raise ValueError(f"'{name}' needs at least two values to sweep")
        if name == "stop_mode" and any(v not in ("structure", "atr") for v in parsed):
            raise ValueError("stop_mode values must be structure and/or atr")
        out[name] = parsed
    return out


def make_runner(symbol_data: Dict[str, pd.DataFrame], bench_df: Optional[pd.DataFrame], base: dict,
                results_calendar: Optional[ResultsCalendar] = None,
                membership: Optional[MembershipHistory] = None) -> Callable[..., BacktestResult]:
    """Returns run(overrides) -> BacktestResult, re-using the already-downloaded data."""
    bench_cache: Dict[int, Benchmark] = {}

    def bench_for(ema: int) -> Optional[Benchmark]:
        if bench_df is None:
            return None
        if ema not in bench_cache:
            bench_cache[ema] = Benchmark(bench_df, regime_ema=ema)
        return bench_cache[ema]

    def run(overrides: Optional[dict] = None) -> BacktestResult:
        p = {**DEFAULT_BASE, **base, **(overrides or {})}
        skw = {"stop_mode": p["stop_mode"], "atr_mult": p["atr_mult"]}
        if p["strategy"] == "pullback_trend":
            skw["pullback_lookback"] = p["pullback_lookback"]
            skw["min_pullback_days"] = p["min_pullback_days"]
        elif p["strategy"] == "breakout":
            skw["breakout_lookback"] = p["breakout_lookback"]
            skw["volume_multiple"] = p["volume_multiple"]
        strategy = STRATEGIES[p["strategy"]](**skw)
        risk = RiskEngine(p["capital"], p["risk_pct"], p["heat_ceiling"], p["max_positions"], p["reward_risk"],
                          min_risk_fraction=p["min_risk_fraction"])
        costs = CostModel.zero() if p["no_costs"] else CostModel(
            brokerage_pct=p["brokerage_pct"], slippage_pct=p["slippage_pct"])
        bt = Backtester(
            strategy, risk, p["capital"], cost_model=costs,
            filters=TradeFilters(p["min_traded_value"], p["max_stop_pct"], p["results_buffer_days"]),
            benchmark=bench_for(int(p["regime_ema"])), regime_filter=p["regime_ema"] > 0 and bench_df is not None,
            results_calendar=results_calendar, use_trailing=not p["no_trailing"],
            time_stop_days=p["time_stop_days"], membership=membership)
        return bt.run(symbol_data, progress=False)

    return run


def max_drawdown_pct(values) -> float:
    peak, worst = None, 0.0
    for v in values:
        peak = v if peak is None else max(peak, v)
        if peak:
            worst = max(worst, (peak - v) / peak * 100)
    return round(worst, 2)


def trade_stats(trades: List[Trade]) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "win_rate_pct": None, "avg_r": None, "median_r": None, "expectancy": None,
                "net_pnl": 0.0, "profit_factor": None}
    gp = sum(t.pnl_rupees for t in trades if t.pnl_rupees > 0)
    gl = abs(sum(t.pnl_rupees for t in trades if t.pnl_rupees <= 0))
    pf = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else None)
    return {
        "trades": n,
        "win_rate_pct": round(sum(1 for t in trades if t.pnl_rupees > 0) / n * 100, 1),
        "avg_r": round(sum(t.r_multiple for t in trades) / n, 3),
        "median_r": round(float(np.median([t.r_multiple for t in trades])), 3),
        "expectancy": round(sum(t.pnl_rupees for t in trades) / n, 2),
        "net_pnl": round(sum(t.pnl_rupees for t in trades), 2),
        "profit_factor": round(pf, 2) if pf not in (None, float("inf")) else pf,
    }


def run_summary(res: BacktestResult) -> dict:
    s = trade_stats(res.trades)
    s["max_dd_pct"] = max_drawdown_pct([p["equity"] for p in res.equity_curve])
    s["return_pct"] = round((res.final_equity - res.initial_capital) / res.initial_capital * 100, 2)
    return s


# ---------------------------------------------------------------- 1. in/out of sample

def parse_split(text: str):
    """'0.7' -> 0.7 (fraction of the date range); '2025-03-01' -> that date string."""
    try:
        f = float(text)
        if 0 < f < 1:
            return f
        raise ValueError("--split as a number must be between 0 and 1")
    except ValueError as e:
        if "between" in str(e):
            raise
    return str(pd.Timestamp(text).date())


def split_validation(res: BacktestResult, split, min_trades: int = 15) -> dict:
    dates = [p["date"] for p in res.equity_curve]
    cut = dates[min(int(len(dates) * split), len(dates) - 1)] if isinstance(split, float) else split
    parts = {}
    for label, pick in (("in_sample", lambda d: d < cut), ("out_of_sample", lambda d: d >= cut)):
        trades = [t for t in res.trades if pick(t.entry_date)]
        eq = [p["equity"] for p in res.equity_curve if pick(p["date"])]
        st = trade_stats(trades)
        st["max_dd_pct"] = max_drawdown_pct(eq)
        parts[label] = st
    i, o = parts["in_sample"], parts["out_of_sample"]
    if i["trades"] < min_trades or o["trades"] < min_trades:
        verdict = (f"Too few trades to judge (need {min_trades}+ in each half; have "
                   f"{i['trades']} and {o['trades']}). Use a longer --period or a wider universe.")
    elif o["avg_r"] <= 0 < i["avg_r"]:
        verdict = "Out-of-sample average R is not positive while in-sample is: the edge did not carry over."
    elif i["avg_r"] > 0 and o["avg_r"] < 0.5 * i["avg_r"]:
        verdict = "Out-of-sample average R is less than half of in-sample: material degradation."
    elif i["avg_r"] <= 0 and o["avg_r"] <= 0:
        verdict = "Not profitable in either half."
    elif o["avg_r"] >= i["avg_r"]:
        verdict = "Out-of-sample did at least as well as in-sample: no sign of overfitting from this split alone."
    else:
        verdict = "Out-of-sample performance is broadly in line with in-sample."
    return {"cut": cut, **parts, "verdict": verdict}


# ---------------------------------------------------------------- 2. year / regime

def yearly_breakdown(trades: List[Trade]) -> List[dict]:
    years = sorted({t.entry_date[:4] for t in trades})
    return [{"period": y, **trade_stats([t for t in trades if t.entry_date[:4] == y])} for y in years]


def regime_breakdown(trades: List[Trade], bench_df: Optional[pd.DataFrame], ema: int = 50) -> Optional[List[dict]]:
    """Classifies each trade by whether the index was above its EMA on the signal day (day before entry)."""
    if bench_df is None:
        return None
    bench = Benchmark(bench_df, regime_ema=ema)
    groups: Dict[str, List[Trade]] = {f"Index above {ema}-EMA": [], f"Index below {ema}-EMA": [], "Unknown": []}
    for t in trades:
        b = bench.is_bullish(pd.Timestamp(t.entry_date).date() - timedelta(days=1))
        key = f"Index above {ema}-EMA" if b is True else f"Index below {ema}-EMA" if b is False else "Unknown"
        groups[key].append(t)
    return [{"period": k, **trade_stats(v)} for k, v in groups.items() if v]


# ---------------------------------------------------------------- 3. parameter sensitivity

def run_sweep(runner, sweeps: Dict[str, list], max_combos: int = 60, progress: bool = True) -> List[dict]:
    names = list(sweeps)
    combos = list(itertools.product(*sweeps.values()))
    if len(combos) > max_combos:
        raise ValueError(f"{len(combos)} parameter combinations exceeds --max-combos {max_combos}. "
                         f"Sweep fewer values (and remember: more combinations = more luck-fitting).")
    rows = []
    for k, vals in enumerate(combos, 1):
        ov = dict(zip(names, vals))
        res = runner(ov)
        row = {"params": ov, "trades_list": res.trades, **run_summary(res)}
        rows.append(row)
        if progress:
            print(f"  [{k}/{len(combos)}] {ov}  trades {row['trades']}  avg R {row['avg_r']}  net Rs {row['net_pnl']}")
    return rows


def find_inert_params(rows: List[dict]) -> List[str]:
    """Swept parameters whose values produced IDENTICAL results everywhere (so they do nothing)."""
    if not rows:
        return []
    names = list(rows[0]["params"])
    inert = []
    for name in names:
        groups: Dict[tuple, List[dict]] = {}
        for r in rows:
            key = tuple((n, r["params"][n]) for n in names if n != name)
            groups.setdefault(key, []).append(r)
        if all(len(g) > 1 and len({(x["trades"], x["net_pnl"]) for x in g}) == 1 for g in groups.values()):
            inert.append(name)
    return inert


def summarize_sweep(rows: List[dict], min_trades: int = 10) -> dict:
    valid = [r for r in rows if r["trades"] >= min_trades and r["avg_r"] is not None]
    if not valid:
        return {"combos": len(rows), "valid": 0, "inert_params": find_inert_params(rows),
                "verdict": f"No parameter set produced {min_trades}+ trades; nothing to compare."}
    profitable = [r for r in valid if r["avg_r"] > 0 and r["net_pnl"] > 0]
    avg_rs = sorted(r["avg_r"] for r in valid)
    share = len(profitable) / len(valid)
    if share >= 0.8:
        verdict = "Most nearby parameter sets are profitable: the result does not hinge on one setting."
    elif share >= 0.5:
        verdict = "Mixed: roughly half the parameter sets are profitable. Treat the best one with suspicion."
    else:
        verdict = "Fragile: most parameter sets lose money, so a good-looking best result is probably tuning luck."
    return {"combos": len(rows), "valid": len(valid), "profitable": len(profitable),
            "inert_params": find_inert_params(rows),
            "share_profitable_pct": round(share * 100, 1),
            "median_avg_r": round(float(np.median(avg_rs)), 3),
            "best_avg_r": avg_rs[-1], "worst_avg_r": avg_rs[0], "verdict": verdict}


# ---------------------------------------------------------------- 4. walk-forward

def walk_forward(sweep_rows: List[dict], base_trades: List[Trade], dates: List[str],
                 train_months: int, test_months: int, min_trades: int = 10) -> dict:
    """
    For each window: choose the parameter set with the best average R over
    trades that were ENTERED and CLOSED inside the training window, then
    record how that set's trades entered in the following test window did.
    Compared against the fixed base parameters over the same test windows.
    """
    first, last = pd.Timestamp(dates[0]), pd.Timestamp(dates[-1])
    windows, t0 = [], first
    while True:
        tr_end = t0 + pd.DateOffset(months=train_months)
        te_end = tr_end + pd.DateOffset(months=test_months)
        if te_end > last + pd.Timedelta(days=1):
            break
        windows.append((str(t0.date()), str(tr_end.date()), str(te_end.date())))
        t0 = t0 + pd.DateOffset(months=test_months)

    out_rows, oos_trades, base_oos = [], [], []
    for tr_start, test_start, test_end in windows:
        best, best_stats = None, None
        for r in sweep_rows:
            tr = [t for t in r["trades_list"] if t.entry_date >= tr_start and t.exit_date < test_start]
            st = trade_stats(tr)
            if st["trades"] >= min_trades and (best is None or st["avg_r"] > best_stats["avg_r"]):
                best, best_stats = r, st
        base_test = [t for t in base_trades if test_start <= t.entry_date < test_end]
        row = {"train": f"{tr_start} to {test_start}", "test": f"{test_start} to {test_end}"}
        if best is None:
            row.update({"chosen": "skipped (too few training trades)", "train_avg_r": None,
                        "test_trades": 0, "test_avg_r": None, "test_net_pnl": 0.0,
                        "base_test_trades": len(base_test), "base_test_avg_r": trade_stats(base_test)["avg_r"]})
        else:
            te = [t for t in best["trades_list"] if test_start <= t.entry_date < test_end]
            ts = trade_stats(te)
            oos_trades.extend(te)
            base_oos.extend(base_test)
            row.update({"chosen": best["params"], "train_avg_r": best_stats["avg_r"],
                        "test_trades": ts["trades"], "test_avg_r": ts["avg_r"], "test_net_pnl": ts["net_pnl"],
                        "base_test_trades": len(base_test), "base_test_avg_r": trade_stats(base_test)["avg_r"]})
        out_rows.append(row)

    oos, base = trade_stats(oos_trades), trade_stats(base_oos)
    train_rs = [r["train_avg_r"] for r in out_rows if r["train_avg_r"] is not None]
    mean_train = float(np.mean(train_rs)) if train_rs else None
    efficiency = (oos["avg_r"] / mean_train) if (oos["avg_r"] is not None and mean_train and mean_train > 0) else None
    if not windows:
        verdict = "Period too short for these window lengths: lengthen --period or shorten the windows."
    elif oos["trades"] < 20:
        verdict = f"Only {oos['trades']} out-of-sample trades: too few to conclude anything."
    elif oos["avg_r"] <= 0:
        verdict = "Parameters chosen on past data did not make money on the next unseen window."
    elif base["avg_r"] is not None and oos["avg_r"] < base["avg_r"]:
        verdict = "Positive, but re-optimizing did no better than keeping the fixed base parameters."
    else:
        verdict = "Parameters chosen in-window were profitable on unseen windows and beat the fixed base."
    return {"windows": out_rows, "oos": oos, "base_oos": base,
            "efficiency": round(efficiency, 2) if efficiency is not None else None, "verdict": verdict}


# ---------------------------------------------------------------- 5. Monte Carlo

def _paths_dd_and_final(rets: np.ndarray):
    paths = np.cumprod(1.0 + rets, axis=1)
    paths = np.concatenate([np.ones((paths.shape[0], 1)), paths], axis=1)
    peak = np.maximum.accumulate(paths, axis=1)
    dd = ((peak - paths) / peak).max(axis=1) * 100
    return dd, (paths[:, -1] - 1) * 100


def monte_carlo(trades: List[Trade], sims: int = 2000, seed: int = 42, min_trades: int = 20) -> Optional[dict]:
    """
    Each trade becomes a return on the equity it was sized from
    (pnl / equity at entry), then:
      shuffle   -- same trades, random order: shows how much of the
                   drawdown was just the order they arrived in
                   (final return is identical by construction)
      bootstrap -- trades drawn with replacement: a range for both final
                   return and drawdown
    """
    rets = np.array([t.pnl_rupees / t.entry_equity for t in trades if t.entry_equity > 0], dtype=float)
    n = len(rets)
    if n < min_trades:
        return {"too_few": True, "n": n, "min": min_trades}
    rng = np.random.default_rng(seed)
    shuf = rets[np.argsort(rng.random((sims, n)), axis=1)]
    boot = rets[rng.integers(0, n, (sims, n))]
    dd_s, _ = _paths_dd_and_final(shuf)
    dd_b, fin_b = _paths_dd_and_final(boot)
    observed_dd, _ = _paths_dd_and_final(rets[None, :])
    pct = lambda a, q: round(float(np.percentile(a, q)), 2)
    return {
        "too_few": False, "n": n, "sims": sims,
        "observed_trade_dd_pct": round(float(observed_dd[0]), 2),
        "shuffle_dd": {"p50": pct(dd_s, 50), "p95": pct(dd_s, 95), "p99": pct(dd_s, 99)},
        "bootstrap_dd": {"p50": pct(dd_b, 50), "p95": pct(dd_b, 95), "p99": pct(dd_b, 99)},
        "bootstrap_return": {"p5": pct(fin_b, 5), "p50": pct(fin_b, 50), "p95": pct(fin_b, 95)},
        "prob_loss_pct": round(float((fin_b < 0).mean() * 100), 1),
        "prob_dd_over_20_pct": round(float((dd_b > 20).mean() * 100), 1),
        "dd_samples": dd_b.tolist(),
    }


# ---------------------------------------------------------------- 6. ablation

def run_ablation(runner, strategy: str, progress: bool = True) -> List[dict]:
    """Switch one feature off at a time to see what is actually driving the result."""
    cases = [
        ("As configured", {}),
        ("No costs or slippage (gross)", {"no_costs": True}),
        ("No market-regime filter", {"regime_ema": 0}),
        ("No breakeven/trailing stop", {"no_trailing": True}),
        ("No time-stop", {"time_stop_days": 0}),
        ("No liquidity / stop-width / undersized filters",
         {"min_traded_value": 0.0, "max_stop_pct": 0.0, "min_risk_fraction": 0.0}),
        ("ATR stops instead of structure stops", {"stop_mode": "atr"}),
    ]
    if strategy == "pullback_trend":
        cases.append(("Looser pullback (1-day dips count)", {"min_pullback_days": 1}))
    rows = []
    for label, ov in cases:
        res = runner(ov)
        row = {"label": label, **run_summary(res)}
        rows.append(row)
        if progress:
            print(f"  {label}: trades {row['trades']}, avg R {row['avg_r']}, net Rs {row['net_pnl']}")
    return rows


# ---------------------------------------------------------------- console tables

def format_table(headers: List[str], rows: List[list]) -> str:
    cells = [[("-" if v is None else f"{v}") for v in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in cells)) if cells else len(h) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    body = ["  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in cells]
    return "\n".join(["  " + line, "  " + "  ".join("-" * w for w in widths)] + ["  " + b for b in body])
