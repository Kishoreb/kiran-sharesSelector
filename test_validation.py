"""
Offline tests for the validation tools (no network): synthetic 5-year data,
screener.fetch_history monkeypatched, then the real `validate` command is run.

    python test_validation.py
"""

import os
import sys
import tempfile

import numpy as np
import pandas as pd

import screener
import validation as val
from backtester import Trade
from data import add_indicators

rng = np.random.default_rng(7)
N = 1300
IDX = pd.bdate_range("2021-01-01", periods=N)


def synth(drift, vol=0.016, seed=None):
    r = np.random.default_rng(seed)
    cl = 100 * np.exp(np.cumsum(r.normal(drift, vol, N)))
    op = cl * (1 + r.normal(0, 0.005, N))
    hi = np.maximum(op, cl) * (1 + np.abs(r.normal(0, 0.006, N)))
    lo = np.minimum(op, cl) * (1 - np.abs(r.normal(0, 0.006, N)))
    v = r.integers(2_000_000, 6_000_000, N).astype(float)
    return add_indicators(pd.DataFrame({"Open": op, "High": hi, "Low": lo, "Close": cl, "Volume": v}, index=IDX))


DATA = {f"S{k}": synth(0.0007, seed=100 + k) for k in range(30)}
DATA["^NSEI"] = synth(0.0004, vol=0.009, seed=1)
screener.fetch_history = lambda sym, period="2y", interval="1d": DATA[sym.upper().replace(".NS", "")]

# ---- unit checks
for bad in (["nope=1,2"], ["reward_risk=2"], ["breakout_lookback=10,20"], ["stop_mode=x,y"], ["reward_risk"]):
    try:
        val.parse_sweeps(bad, "pullback_trend")
        raise AssertionError(f"should have rejected {bad}")
    except ValueError:
        pass
assert val.parse_sweeps(["reward_risk=1.5,2", "pullback_lookback=7,10"], "pullback_trend") == \
    {"reward_risk": [1.5, 2.0], "pullback_lookback": [7, 10]}
assert val.parse_split("0.7") == 0.7 and val.parse_split("2024-03-01") == "2024-03-01"
print("parse_sweeps / parse_split ok")


def mk(i, pnl, eq=100000.0, d="2022-01-03"):
    return Trade("X", "s", d, 100.0, d, 100.0, 95.0, 110.0, 100, "stop", 0.0, eq) if pnl == 0 else \
        Trade("X", "s", d, 100.0, d, 100.0 + pnl / 100, 95.0, 110.0, 100, "stop", 0.0, eq)


# Monte Carlo: final return of a pure shuffle is order-independent; DD distribution bounded; marker consistent
trades = [mk(i, p) for i, p in enumerate([2000, -1000, 1500, -1000, -1000, 3000, -1000, 1500, -1000, -1000] * 4)]
mc = val.monte_carlo(trades, sims=500, seed=1)
assert not mc["too_few"] and mc["shuffle_dd"]["p50"] <= mc["shuffle_dd"]["p95"] <= mc["shuffle_dd"]["p99"]
assert mc["bootstrap_return"]["p5"] <= mc["bootstrap_return"]["p50"] <= mc["bootstrap_return"]["p95"]
assert val.monte_carlo(trades[:5])["too_few"]
assert val.monte_carlo(trades, sims=500, seed=1)["shuffle_dd"] == mc["shuffle_dd"]   # seed reproducible
print("monte_carlo ok:", mc["shuffle_dd"], mc["bootstrap_return"])

# sensitivity: a parameter with no effect must be flagged
sym_only = {k: v for k, v in DATA.items() if k != "^NSEI"}
runner = val.make_runner(sym_only, DATA["^NSEI"], dict(val.DEFAULT_BASE))
rows = val.run_sweep(runner, {"atr_mult": [1.5, 2.5], "reward_risk": [2.0, 3.0]}, progress=False)
sm = val.summarize_sweep(rows)   # atr_mult is inert while stop_mode = structure
assert sm["inert_params"] == ["atr_mult"], sm["inert_params"]
print("inert-parameter detection ok:", sm["inert_params"])

# ---- end to end through the real CLI
out = tempfile.mkdtemp()
rep, sw = os.path.join(out, "r.html"), os.path.join(out, "s.csv")
sys.argv = ["screener.py", "validate", "--symbols", *[k for k in DATA if k != "^NSEI"],
            "--period", "5y", "--sweep", "reward_risk=1.5,2,3", "--sweep", "min_pullback_days=1,2",
            "--wf-train-months", "12", "--wf-test-months", "6", "--mc-sims", "500",
            "--report", rep, "--sweep-out", sw]
screener.main()
html = open(rep, encoding="utf-8").read()
for needle in ("Equity curve", "In-sample vs out-of-sample", "By calendar year", "Monte Carlo",
               "Parameter sensitivity", "Walk-forward", "<svg"):
    assert needle in html, needle
assert "<script" not in html and "http://" not in html.replace("http://www.w3.org/2000/svg", "")
sweep = pd.read_csv(sw)
assert len(sweep) == 6 and {"reward_risk", "min_pullback_days", "avg_r", "net_pnl"} <= set(sweep.columns)
print(f"\nend-to-end ok: report {len(html):,} bytes, sweep rows {len(sweep)}")

# no sweep -> still produces a report, skips sensitivity/walk-forward cleanly
sys.argv = ["screener.py", "validate", "--symbols", *[k for k in DATA if k != "^NSEI"][:10],
            "--period", "5y", "--mc-sims", "0", "--report", rep, "--split", "2023-06-01"]
screener.main()
assert "Parameter sensitivity" not in open(rep, encoding="utf-8").read()
print("\nAll validation checks passed.")
