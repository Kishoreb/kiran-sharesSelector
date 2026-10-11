"""
Offline sanity tests (no network): crafted price paths where the correct
answer is known by hand, plus a no-lookahead check on the real strategies.

    python test_toolkit.py
"""

import numpy as np
import pandas as pd

from backtester import Backtester
from candidate_engine import Candidate, CandidateEngine
from costs import CostModel
from data import add_indicators
from exits import suggest_stop
from filters import ResultsCalendar, TradeFilters
from market import Benchmark
from risk import RiskEngine
from strategies import STRATEGIES, Signal, Strategy

N = 90
IDX = pd.bdate_range("2024-01-01", periods=N)


def make_df(o=None, h=None, l=None, c=None, volume=1e7):
    base = np.full(N, 100.0)
    c = base.copy() if c is None else np.asarray(c, float)
    o = c.copy() if o is None else np.asarray(o, float)
    h = np.maximum(o, c) + 0.5 if h is None else np.asarray(h, float)
    l = np.minimum(o, c) - 0.5 if l is None else np.asarray(l, float)
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": np.full(N, volume)}, index=IDX)
    return add_indicators(df)


class OneShot(Strategy):
    """Signals once, at bar `at`, with stop = close * stop_frac."""
    name = "oneshot"

    def __init__(self, at=60, stop_frac=0.95, **kw):
        super().__init__(**kw)
        self.at, self.stop_frac = at, stop_frac

    def signal(self, df, i):
        if i == self.at:
            c = float(df["Close"].iloc[i])
            return Signal(enter=True, entry=c, stop=c * self.stop_frac, conditions={"x": True})
        return Signal(enter=False, conditions={})


def run(data, strat=None, costs=None, risk=None, **kw):
    risk = risk or RiskEngine(100000, 1.5, 8.0, 5, 2.0)
    bt = Backtester(strat or OneShot(), risk, 100000,
                    cost_model=costs if costs is not None else CostModel.zero(), **kw)
    return bt.run(data, progress=False)


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ---- A: gap below the stop exits at the OPEN, not at the stop price
o = np.full(N, 100.0); c = np.full(N, 100.0)
o[62] = 90; c[62] = 91
r = run({"AAA": make_df(o=o, c=c)})
t = r.trades[0]
assert t.entry_date == str(IDX[61].date()) and approx(t.entry_price, 100), t
assert t.exit_date == str(IDX[62].date()) and approx(t.exit_price, 90) and t.exit_reason == "stop", t
assert t.quantity == 300 and approx(t.pnl_rupees, -3000), t
print("A ok: gap through stop exits at open (90), not 95; entry at NEXT open; qty 300")

# ---- B: time-stop exits at the next open after 14 calendar days with <0.5R
r = run({"AAA": make_df()})
t = r.trades[0]
assert t.exit_reason == "time_stop" and t.exit_date == str(IDX[72].date()), t
print("B ok: time-stop fired, exit", t.exit_date)
r = run({"AAA": make_df()}, time_stop_days=0)
assert r.trades[0].exit_reason == "end_of_backtest"
print("B2 ok: time-stop off -> position runs to end of backtest")

# ---- C: breakeven trail at +1R, then stopped out at breakeven (reason trailing_stop)
o = np.full(N, 100.0); c = np.full(N, 100.0); l = np.full(N, 99.5); h = np.full(N, 100.5)
o[62], c[62], h[62], l[62] = 101, 106, 106.5, 100.8
o[63], c[63], h[63], l[63] = 106, 104, 106, 103
o[64], c[64], h[64], l[64] = 103, 99.5, 103.5, 99
r = run({"AAA": make_df(o, h, l, c)})
t = r.trades[0]
assert t.exit_reason == "trailing_stop" and approx(t.exit_price, 100) and t.exit_date == str(IDX[64].date()), t
print("C ok: stop moved to breakeven after +1R and exited there:", t.exit_reason, t.exit_price)
r = run({"AAA": make_df(o, h, l, c)}, use_trailing=False)
assert r.trades[0].exit_reason != "trailing_stop"
print("C2 ok: --no-trailing leaves the stop alone")

# ---- D: gap up through target fills at the open (limit order, no slippage)
o = np.full(N, 100.0); c = np.full(N, 100.0)
o[62], c[62] = 115, 114
r = run({"AAA": make_df(o=o, c=c)}, costs=CostModel(slippage_pct=0.1))
t = r.trades[0]
assert t.exit_reason == "target" and approx(t.exit_price, 115), t
assert approx(t.entry_price, 100 * 1.001), t
print("D ok: target gap fills at open 115; entry carries 0.1% slippage")

# ---- E: costs reduce P&L and reconcile with cash
cm = CostModel()
r = run({"AAA": make_df(o=o, c=c)}, costs=cm)
t = r.trades[0]
assert t.fees > 0
assert abs((r.final_equity - 100000) - sum(x.pnl_rupees for x in r.trades)) < 0.5
print(f"E ok: fees Rs {t.fees:.2f}; buy cost on Rs 1L = {cm.buy_cost(100000):.2f}, sell = {cm.sell_cost(100000):.2f}")

# ---- F: equity-based sizing -- 2nd position is NOT shrunk by the cash the 1st one used
r = run({"AAA": make_df(), "BBB": make_df()})
qtys = sorted(t.quantity for t in r.trades)
assert qtys == [300, 300], qtys
print("F ok: both positions risk 1.5% of equity (qty 300 each; cash-based sizing would give 210)")

# ---- G: max_positions=1 -> second signal skipped and counted
r = run({"AAA": make_df(), "BBB": make_df()}, risk=RiskEngine(100000, 1.5, 8.0, 1, 2.0))
assert len(r.trades) == 1 and r.skips.get("max_positions") == 1, (len(r.trades), r.skips)
print("G ok: skip counted ->", r.skips)

# ---- H: filters
r = run({"AAA": make_df(volume=10)}, filters=TradeFilters(5.0, 0, 0))
assert not r.trades and r.skips.get("liquidity") == 1
r = run({"AAA": make_df()}, filters=TradeFilters(0, 3.0, 0))
assert not r.trades and r.skips.get("stop_too_wide") == 1
cal = ResultsCalendar({"AAA": [IDX[60].date() + pd.Timedelta(days=5)]})
r = run({"AAA": make_df()}, filters=TradeFilters(0, 0, 14), results_calendar=cal)
assert not r.trades and r.skips.get("results_soon") == 1
cal2 = ResultsCalendar({"AAA": [IDX[60].date() + pd.Timedelta(days=40)]})
r = run({"AAA": make_df()}, filters=TradeFilters(0, 0, 14), results_calendar=cal2)
assert len(r.trades) == 1
print("H ok: liquidity / stop-width / results-date filters each skip and are counted")

# ---- I: regime filter
falling = make_df(c=np.linspace(200, 100, N))
bench = Benchmark(falling, regime_ema=20)
assert bench.is_bullish(IDX[60].date()) is False
r = run({"AAA": make_df()}, benchmark=bench, regime_filter=True)
assert not r.trades and r.skips.get("regime") == 1
r = run({"AAA": make_df()}, benchmark=bench, regime_filter=False)
assert len(r.trades) == 1
print("I ok: bearish index blocks entry when regime filter is on")

# ---- J: relative strength + ranking
rising = Benchmark(make_df(c=np.linspace(100, 110, N)), regime_ema=20)
stock = make_df(c=np.linspace(100, 130, N))
rs = rising.relative_strength(stock, 80)
assert rs is not None and rs > 0, rs
mk = lambda s, rs_, sp: Candidate(s, "x", 5, 6, 100, 95, 110, 10, 1000, 50, "", rel_strength=rs_, stop_pct=sp)
ranked = CandidateEngine.rank([mk("LOW", 1.0, 3), mk("NONE", None, 1), mk("HIGH", 9.0, 5), mk("TIE", 9.0, 2)])
assert [c.symbol for c in ranked] == ["TIE", "HIGH", "LOW", "NONE"], [c.symbol for c in ranked]
print("J ok: ranking = score, then relative strength, then tighter stop; RS =", rs)

# ---- K: trailing only activates after +1R (documented rule)
df = make_df()
df.loc[df.index[70], "Low"] = 98.0
s_new, r_mult = suggest_stop(df, 80, 90.0, 85.0, 85.0)   # price 100 => r=2
assert r_mult >= 1 and s_new >= 90.0
s_flat, r_flat = suggest_stop(df, 80, 100.0, 95.0, 95.0)  # r=0 -> untouched
assert approx(s_flat, 95.0)
print("K ok: no trailing below +1R; breakeven/trail above it")

# ---- L: ATR stop mode and structure mode both produce a valid stop
rng = np.random.default_rng(1)
n = 400
idx = pd.bdate_range("2023-01-02", periods=n)
rets = rng.normal(0.0006, 0.015, n)
close = 100 * np.exp(np.cumsum(rets))
op = close * (1 + rng.normal(0, 0.004, n))
hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
vol = rng.integers(2_000_000, 6_000_000, n).astype(float)
base = add_indicators(pd.DataFrame({"Open": op, "High": hi, "Low": lo, "Close": close, "Volume": vol}, index=idx))
for name, cls in STRATEGIES.items():
    for mode in ("structure", "atr"):
        st = cls(stop_mode=mode)
        sigs = [st.signal(base, i) for i in range(60, n)]
        for sg in sigs:
            if sg.enter:
                assert 0 < sg.stop < sg.entry
        # no lookahead: signal at i must not change when future rows are removed
        for i in range(60, n, 25):
            a, b = st.signal(base, i), st.signal(base.iloc[: i + 1], i)
            assert a.enter == b.enter and a.conditions == b.conditions and a.stop == b.stop
print("L ok: both strategies x both stop modes valid; no lookahead")

# ---- M: full multi-symbol run, costs on, cash reconciles with the trade log
data = {}
for k in range(12):
    rets = rng.normal(0.0008, 0.016, n)
    cl = 100 * np.exp(np.cumsum(rets))
    op = cl * (1 + rng.normal(0, 0.006, n))
    hi = np.maximum(op, cl) * (1 + np.abs(rng.normal(0, 0.006, n)))
    lo = np.minimum(op, cl) * (1 - np.abs(rng.normal(0, 0.006, n)))
    data[f"S{k}"] = add_indicators(pd.DataFrame({"Open": op, "High": hi, "Low": lo, "Close": cl,
                                                 "Volume": rng.integers(2_000_000, 6_000_000, n).astype(float)}, index=idx))
bench = Benchmark(add_indicators(pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close,
                                               "Volume": np.ones(n)}, index=idx)), regime_ema=50)
for strat_name in STRATEGIES:
    bt = Backtester(STRATEGIES[strat_name](), RiskEngine(100000, 1.5, 8.0, 5, 2.0), 100000,
                    cost_model=CostModel(), filters=TradeFilters(5.0, 8.0, 0),
                    benchmark=bench, regime_filter=True)
    res = bt.run(data, progress=False)
    recon = abs((res.final_equity - 100000) - sum(t.pnl_rupees for t in res.trades))
    assert recon < 1.0, recon
    assert all(t.quantity > 0 and t.fees > 0 for t in res.trades)
    m = res.metrics()
    print(f"M ok [{strat_name}]: trades={m['total_trades']} exits={m.get('exit_reasons')} skipped={m['signals_skipped']}")

# ---- N: capital-limited stub / tiny-stop positions are skipped, not traded
r = run({"AAA": make_df()}, strat=OneShot(stop_frac=0.999))
assert not r.trades and r.skips.get("undersized") == 1, (r.trades, r.skips)
r = run({"AAA": make_df()}, strat=OneShot(stop_frac=0.999), risk=RiskEngine(100000, 1.5, 8.0, 5, 2.0, min_risk_fraction=0))
assert len(r.trades) == 1
print("N ok: tiny-stop position that would swallow all capital is skipped as undersized (rule can be turned off)")

# ---- O: pullback length is measured as a run of closes at/below the 20-EMA; lookback caps it, min days floors it
from strategies import PullbackTrendStrategy


def pullback_df(k, n=160, pk=80):
    c = 100 * 1.006 ** np.arange(n)
    peak = c[pk]
    for j in range(1, k + 1):
        c[pk + j] = peak * (0.992 ** j)      # slide below the lagging 20-EMA
    i = pk + k + 1
    c[i] = peak * 1.05                         # sharp reclaim
    c[i + 1:] = c[i]
    o = c.copy()
    df = pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.003, "Low": np.minimum(o, c) * 0.997,
                       "Close": c, "Volume": np.full(n, 1e7)}, index=pd.bdate_range("2024-01-01", periods=n))
    return add_indicators(df), i


df6, i6 = pullback_df(6)      # 1-day pullback
df9, i9 = pullback_df(9)      # 4-day pullback
df12, i12 = pullback_df(12)   # 7-day pullback
mk = lambda **kw: PullbackTrendStrategy(**kw)
assert mk(min_pullback_days=1, pullback_lookback=10).signal(df6, i6).enter
assert not mk(min_pullback_days=2, pullback_lookback=10).signal(df6, i6).enter
assert mk(min_pullback_days=3, pullback_lookback=10).signal(df9, i9).enter
assert mk(min_pullback_days=2, pullback_lookback=10).signal(df12, i12).enter
assert not mk(min_pullback_days=2, pullback_lookback=5).signal(df12, i12).enter
print("O ok: 1-day dip rejected at min 2 days; 7-day slide accepted at max 10 but rejected at max 5 (pullback_lookback now matters)")

print("\nAll checks passed.")
