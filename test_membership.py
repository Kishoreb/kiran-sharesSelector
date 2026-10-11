"""
Offline tests for point-in-time membership, index-change snapshots and the
ablation table. No network.

    python test_membership.py
"""

import os
import sys
import tempfile
from datetime import date

import numpy as np
import pandas as pd

import membership as mb
import universe
from backtester import Backtester
from costs import CostModel
from data import add_indicators
from membership import MembershipHistory
from risk import RiskEngine
from strategies import Signal, Strategy

D = date

# ---- reconstruction from today's list by undoing changes
changes = [(D(2024, 3, 28), "C", "ADD"), (D(2024, 3, 28), "D", "REMOVE"),
           (D(2025, 3, 28), "B", "ADD"), (D(2025, 3, 28), "E", "REMOVE")]
h = MembershipHistory({"A", "B", "C"}, changes)
assert not h.warnings, h.warnings
mem = lambda d: {s for s in "ABCDEF" if h.is_member(s, d)}
assert mem(D(2023, 1, 1)) == {"A", "D", "E"}
assert mem(D(2024, 3, 27)) == {"A", "D", "E"}            # day before the effective date
assert mem(D(2024, 3, 28)) == {"A", "C", "E"}            # effective date itself
assert mem(D(2025, 3, 27)) == {"A", "C", "E"}
assert mem(D(2025, 6, 1)) == {"A", "B", "C"}
assert h.symbols_since(D(2024, 1, 1)) == {"A", "B", "C", "D", "E"}
assert h.symbols_since(D(2025, 6, 1)) == {"A", "B", "C"}
assert h.missing_data(["A", "B", "C", "D"], D(2024, 1, 1)) == ["E"]
print("reconstruction ok: membership flips exactly on the effective date")

# ---- inconsistent change lists are flagged, not silently trusted
bad = MembershipHistory({"A", "X"}, [(D(2024, 1, 2), "X", "REMOVE")])
assert any("today's list" in w for w in bad.warnings), bad.warnings
dup = MembershipHistory({"A"}, [(D(2024, 1, 2), "A", "ADD"), (D(2024, 6, 3), "A", "ADD")])
assert any("already" in w for w in dup.warnings), dup.warnings
print("consistency warnings ok")

# ---- file parsing
tmp = tempfile.mkdtemp()
f = os.path.join(tmp, "chg.csv")
open(f, "w").write("# comment\ndate,symbol,action\n2024-03-28,c.ns,in\n28-03-2024,D,OUT\n")
assert mb.read_changes(f) == [(D(2024, 3, 28), "C", "ADD"), (D(2024, 3, 28), "D", "REMOVE")]
for body in ("2024-03-28,C\n", "notadate,C,ADD\n", "2024-03-28,C,MAYBE\n"):
    open(f, "w").write(body)
    try:
        mb.read_changes(f)
        raise AssertionError("should have rejected: " + body)
    except ValueError as e:
        assert "line 1" in str(e)
print("file parsing ok (clear errors with line numbers)")

assert mb.period_start("5y", D(2026, 10, 11)) < D(2021, 10, 20)
assert mb.period_start("6mo", D(2026, 10, 11)) < D(2026, 4, 20)
assert mb.period_start("max") < D(2000, 1, 1)

# ---- backtester drops signals on stocks that weren't in the index that day
N = 90
IDX = pd.bdate_range("2024-01-01", periods=N)


class OneShot(Strategy):
    name = "oneshot"

    def __init__(self, at=60, **kw):
        super().__init__(**kw)
        self.at = at

    def signal(self, df, i):
        if i == self.at:
            c = float(df["Close"].iloc[i])
            return Signal(enter=True, entry=c, stop=c * 0.95, conditions={"x": True})
        return Signal(enter=False, conditions={})


def flat():
    c = np.full(N, 100.0)
    return add_indicators(pd.DataFrame({"Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c,
                                        "Volume": np.full(N, 1e7)}, index=IDX))


signal_day = IDX[60].date()
hist = MembershipHistory({"AAA"}, [(signal_day + pd.Timedelta(days=30), "BBB", "REMOVE")])   # BBB leaves later -> member on signal day
hist2 = MembershipHistory({"AAA"}, [(signal_day + pd.Timedelta(days=1), "BBB", "ADD")])     # BBB joins after the signal day
risk = RiskEngine(100000, 1.5, 8.0, 5, 2.0)
r = Backtester(OneShot(), risk, 100000, cost_model=CostModel.zero(), membership=hist).run({"AAA": flat(), "BBB": flat()}, progress=False)
assert sorted(t.symbol for t in r.trades) == ["AAA", "BBB"] and not r.skips.get("not_in_index"), (r.trades, r.skips)
r = Backtester(OneShot(), risk, 100000, cost_model=CostModel.zero(), membership=hist2).run({"AAA": flat(), "BBB": flat()}, progress=False)
assert [t.symbol for t in r.trades] == ["AAA"] and r.skips.get("not_in_index") == 1, (r.trades, r.skips)
print("backtester ok: a former member trades while it was in the index; a not-yet-member is skipped and counted")

# ---- snapshots -> change list
universe.CACHE_DIR = os.path.join(tmp, ".cache")
os.makedirs(universe._snapshot_dir())
hdr = "Company Name,Industry,Symbol,Series,ISIN Code\n"
row = lambda s: f"{s} Ltd,Banks,{s},EQ,INE000\n"
for day, syms in (("2026-03-01", "AAA BBB CCC"), ("2026-04-02", "AAA BBB DDD"), ("2026-04-03", "AAA BBB DDD")):
    open(os.path.join(universe._snapshot_dir(), f"nifty50_{day}.csv"), "w").write(hdr + "".join(row(s) for s in syms.split()))
ch = universe.changes_from_snapshots("nifty50")
assert ch == [(D(2026, 4, 2), "DDD", "ADD"), (D(2026, 4, 2), "CCC", "REMOVE")], ch
out = os.path.join(tmp, "index_changes.csv")
assert mb.merge_changes_file(out, ch) == 2 and mb.merge_changes_file(out, ch) == 0
assert set(mb.read_changes(out)) == set(ch)
print("snapshots ok: diff of dated lists -> change rows; re-running adds nothing twice")

# ---- end to end through the real CLI: membership file + ablation
import screener  # noqa: E402

rng = np.random.default_rng(3)
NN = 1300
IDX2 = pd.bdate_range("2021-01-01", periods=NN)


def synth(drift, vol=0.016, seed=0):
    r_ = np.random.default_rng(seed)
    cl = 100 * np.exp(np.cumsum(r_.normal(drift, vol, NN)))
    op = cl * (1 + r_.normal(0, 0.005, NN))
    hi = np.maximum(op, cl) * (1 + np.abs(r_.normal(0, 0.006, NN)))
    lo = np.minimum(op, cl) * (1 - np.abs(r_.normal(0, 0.006, NN)))
    return add_indicators(pd.DataFrame({"Open": op, "High": hi, "Low": lo, "Close": cl,
                                        "Volume": r_.integers(2_000_000, 6_000_000, NN).astype(float)}, index=IDX2))


CUR = [f"S{k}" for k in range(20)]
DATA = {s: synth(0.0007, seed=10 + k) for k, s in enumerate(CUR)}
DATA["OLD1"] = synth(0.0007, seed=77)          # a former member WITH data
DATA["^NSEI"] = synth(0.0004, 0.009, seed=1)
# OLD2 is a former member with NO price data (Yahoo-style gap)
screener.fetch_history = lambda sym, period="2y", interval="1d": DATA[sym.upper().replace(".NS", "")] if sym.upper().replace(".NS", "") in DATA else (_ for _ in ()).throw(ValueError("no price data returned"))
screener.get_index_symbols = lambda index, refresh=False: CUR
chg = os.path.join(tmp, "idx.csv")
open(chg, "w").write("# date,symbol,action\n2023-06-30,OLD1,REMOVE\n2023-06-30,S3,ADD\n2024-06-28,OLD2,REMOVE\n2024-06-28,S4,ADD\n")
rep = os.path.join(tmp, "r.html")
sys.argv = ["screener.py", "validate", "--index", "nifty50", "--period", "5y", "--membership-file", chg,
            "--ablation", "--mc-sims", "0", "--report", rep]
import io, contextlib  # noqa: E402
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    screener.main()
out_text = buf.getvalue()
assert "former members" in out_text and "OLD2" in out_text and "Membership coverage" in out_text, out_text[:2000]
assert "7. What is driving the result" in out_text and "Looser pullback" in out_text
html = open(rep, encoding="utf-8").read()
assert "What is driving the result" in html and "Membership coverage" in html
print("end-to-end ok: former member downloaded, missing-data member reported, ablation table in console and HTML")

# explicit --symbols + membership file is ignored with a note, not an error
sys.argv = ["screener.py", "backtest", "--symbols", "S0", "S1", "S2", "--period", "5y", "--membership-file", chg,
            "--trades-out", os.path.join(tmp, "t.csv"), "--equity-out", os.path.join(tmp, "e.csv")]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    screener.main()
assert "only applies with --index" in buf.getvalue()
print("\nAll membership checks passed.")
