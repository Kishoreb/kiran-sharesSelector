"""
Offline tests for the ML layers (no network, no model downloads):  python test_ml.py
FinBERT itself is not downloaded here; its scoring maths and its fall-back path are tested.
"""
import contextlib, io, os, sys, tempfile
import numpy as np
import pandas as pd

import candidate_engine
import gov_classifier as gc
import meta_model as mm
import qualitative as q
import screener
from candidate_engine import Candidate, CandidateEngine
from data import add_indicators
from market import Benchmark

TMP = tempfile.mkdtemp()

# ---- 1. FinBERT scorer: maths, fall-back, factory
assert q.FinBertScorer.score_from_probs([0.1, 0.2, 0.7], 2, 0) == 0.6
sc = q.FinBertScorer(os.path.join(TMP, "no_such_model"))
with contextlib.redirect_stdout(io.StringIO()):
    assert sc.score("X", ["a", "b"]) == [None, None]
assert sc.error and sc.name == "finbert:no_such_model" and sc.score("X", []) == []
assert q.make_scorer("none") is None and isinstance(q.make_scorer("finbert"), q.FinBertScorer)
assert q.make_scorer("ollama").kind == "ollama"
print("1 ok: FinBERT scorer (maths, graceful fall-back, factory)")

# ---- 2. governance classifier
model_path = os.path.join(TMP, "gov.pkl")
gm = gc.train(os.path.join(TMP, "none.csv"), model_path, log=lambda *a: None)
assert gm.report["rows"] >= 30 and gm.report["cv_auc"] is not None
gm = gc.GovModel.load(model_path)
p_fp = gm.prob("rating_downgrade", "Nomura cuts rating on Siemens to neutral, trims target price")
p_ok = gm.prob("rating_downgrade", "CRISIL downgrades rating on Test's bonds")
assert p_fp < p_ok, (p_fp, p_ok)
f = {"flag": "rating_downgrade", "severity": "Medium", "text": "x"}
gm.apply(f, "Nomura cuts rating on Siemens to neutral, trims target price")
assert f["severity"] == "Low" and "false positive" in f["ml_note"] and 0 <= f["ml_prob"] <= 1, f
g = {"flag": "sebi_action", "severity": "High", "text": "x"}
gm.apply(g, "SEBI slaps penalty on promoter of Test")
assert g["severity"] == "High" and "ml_note" not in g                      # genuine flag untouched
# integration: scan_items passes every regex hit through the model; no model = unchanged
class Stub:
    name = "stub"
    def apply(self, f, text):
        f["ml_prob"] = 0.1; f["severity"] = gc.SEVERITY_DOWN[f["severity"]]; return f
items = [{"title": "ICRA downgrades Test's long-term rating to BBB-", "date": "2026-10-01"}]
assert q.scan_items(items, "NSE")[0]["severity"] == "Medium" and "ml_prob" not in q.scan_items(items, "NSE")[0]
r2 = q.scan_items(items, "NSE", None, Stub())
assert r2[0]["severity"] == "Low" and r2[0]["ml_prob"] == 0.1
r3 = q.scan_items(items, "NSE", None, gm)                      # real model keeps a genuine downgrade
assert r3[0]["severity"] == "Medium" and r3[0]["ml_prob"] > gm.demote_below
# labels CSV + sheet import
lab = os.path.join(TMP, "labels.csv")
df = pd.DataFrame({"flag": ["sebi_action", "sebi_action", "mgmt_exit"], "text": ["a text", "b text", "c text"],
                   "label": [1, "", 0]})
xl = os.path.join(TMP, "a.xlsx")
with pd.ExcelWriter(xl) as xw:
    df.to_excel(xw, sheet_name="Governance flags", index=False)
assert gc.import_sheet(xl, lab) == 2 and gc.import_sheet(xl, lab) == 0 and len(gc.load_labels(lab)) == 2
try:
    gc.train(os.path.join(TMP, "none.csv"), model_path, use_seed=False, log=lambda *a: None)
    raise AssertionError("should refuse to train on 0 rows")
except ValueError:
    pass
print("2 ok: classifier trains, demotes only likely false positives, no-model path unchanged, sheet import")

# ---- 3. meta-labeling
N = 1300
IDX = pd.bdate_range("2021-01-01", periods=N)

def synth(drift, vol=0.016, seed=0):
    r = np.random.default_rng(seed)
    cl = 100 * np.exp(np.cumsum(r.normal(drift, vol, N)))
    op = cl * (1 + r.normal(0, 0.005, N))
    hi = np.maximum(op, cl) * (1 + np.abs(r.normal(0, 0.006, N)))
    lo = np.minimum(op, cl) * (1 - np.abs(r.normal(0, 0.006, N)))
    return add_indicators(pd.DataFrame({"Open": op, "High": hi, "Low": lo, "Close": cl,
                                        "Volume": r.integers(2_000_000, 6_000_000, N).astype(float)}, index=IDX))

SYMS = [f"S{k}" for k in range(80)]
DATA = {s: synth(0.0008, seed=200 + k) for k, s in enumerate(SYMS)}
DATA["^NSEI"] = synth(0.0004, 0.009, seed=1)
fetch = lambda sym, period="2y", interval="1d": DATA[sym.upper().replace(".NS", "")]
screener.fetch_history = fetch
candidate_engine.fetch_history = fetch
candidate_engine.fetch_market_cap_cr = lambda s: None
bench = Benchmark(DATA["^NSEI"], regime_ema=50)

# no look-ahead: features at bar i are unchanged when later rows are removed
for s in SYMS[:3]:
    for i in (300, 700, 1100):
        a = mm.features_at(DATA[s], i, bench, None, "breakout")
        b = mm.features_at(DATA[s].iloc[: i + 1], i, bench, None, "breakout")
        assert np.allclose([a[k] for k in mm.FEATURES], [b[k] for k in mm.FEATURES], equal_nan=True), (s, i)
assert set(mm.features_at(DATA["S0"], 300, bench)) == set(mm.FEATURES)
print("3a ok: features are point-in-time (no look-ahead)")

out_pkl, ds_csv = os.path.join(TMP, "meta.pkl"), os.path.join(TMP, "ds.csv")
buf = io.StringIO()
sys.argv = ["screener.py", "train-meta", "--symbols", *SYMS, "--period", "5y", "--strategy", "breakout", "--volume-multiple", "1.1",
            "--min-train-trades", "30", "--wf-train-months", "12", "--wf-test-months", "6",
            "--meta-out", out_pkl, "--dataset-out", ds_csv, "--no-sma200", "--max-from-high-pct", "0"]
with contextlib.redirect_stdout(buf):
    try:
        screener.main()
    except SystemExit as e:
        print("EXIT", e.code)
text = buf.getvalue()
assert "Walk-forward" in text and "Verdict" in text and os.path.exists(out_pkl), text[-1500:]
ds = pd.read_csv(ds_csv)
assert set(mm.FEATURES) <= set(ds.columns) and ds["label"].isin([0, 1]).all() and len(ds) >= 30
m = mm.load(out_pkl)
assert m.strategy == "breakout" and set(m.features) == set(mm.FEATURES)
p = m.predict(mm.features_at(DATA["S0"], 600, bench, None, "breakout"))
assert 0 <= p <= 1
print(f"3b ok: train-meta end to end ({len(ds)} rows); sample prob {p}")

# walk-forward never trains on trades still open at the test start
wf = mm.walk_forward(ds, 12, 6, 30, 0.5)
assert wf["folds"] >= 1 and wf["oos_trades"] > 0 and "verdict" in wf
tiny = mm.walk_forward(ds.iloc[:10], 12, 6, 30, 0.5)
assert tiny["folds"] == 0 and "No usable" in tiny["verdict"]
print("3c ok: walk-forward folds + too-little-data path")

# engine: probability recorded, used as ranking tie-break only after points
class FakeMeta:
    threshold = 0.5
    def predict(self, feats): return 0.7
eng = CandidateEngine([], None, benchmark=bench, meta=FakeMeta())
assert eng._meta_prob(DATA["S0"], 400, None, "breakout") == 0.7
assert CandidateEngine([], None)._meta_prob(DATA["S0"], 400, None, "x") is None
mk = lambda s, mp: Candidate(s, "x", 5, 6, 100, 95, 110, 10, 1000, 50, "", rel_strength=1.0, stop_pct=3, meta_prob=mp)
ranked = CandidateEngine.rank([mk("LOW", 0.4), mk("NONE", None), mk("HIGH", 0.8)])
assert [c.symbol for c in ranked] == ["HIGH", "LOW", "NONE"]
hi_score = Candidate("TOP", "x", 6, 6, 100, 95, 110, 10, 1000, 50, "", meta_prob=0.1)
assert CandidateEngine.rank([mk("HIGH", 0.8), hi_score])[0].symbol == "TOP"       # points still come first
assert "win probability 80%" in CandidateEngine.build_thesis(mk("HIGH", 0.8))
assert "win probability" not in CandidateEngine.build_thesis(mk("N", None))
print("3d ok: engine meta probability, ranking order, thesis line")

# screen CLI with the model on: runs, and a missing model gives a clear error
rows = ["TOTAL"]
sys.argv = ["screener.py", "screen", "--symbols", *SYMS[:15], "--meta", "filter", "--meta-model", out_pkl,
            "--strategy", "breakout", "--out", os.path.join(TMP, "scr.csv")]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    screener.main()
assert "Meta-model loaded" in buf.getvalue()
sys.argv[sys.argv.index(out_pkl)] = os.path.join(TMP, "missing.pkl")
buf = io.StringIO()
try:
    with contextlib.redirect_stdout(buf):
        screener.main()
    raise AssertionError("should exit")
except SystemExit:
    assert "could not load" in buf.getvalue()
print("3e ok: screen --meta filter, clear error for a missing model")

# ---- 4. calibration
wf = mm.walk_forward(ds, 12, 6, 30, 0.5)
assert set(wf["brier"]) == {"raw", "calibrated", "constant"} and wf["calib_methods"], wf["brier"]
assert len(wf["reliability"]) == 5 and sum(r["trades"] for r in wf["reliability"]) == wf["oos_trades"]
def cal_df(n, seed=0):
    r = np.random.default_rng(seed)
    d = pd.DataFrame({k: r.normal(size=n) for k in mm.FEATURES})
    d["label"] = (r.random(n) < 1 / (1 + np.exp(-2.5 * d["stop_pct"]))).astype(int)   # strong signal in one feature
    d["entry_date"] = pd.date_range("2022-01-01", periods=n, freq="D").strftime("%Y-%m-%d")
    return d
for n, want in ((700, "isotonic"), (150, "sigmoid"), (60, "none")):
    d = cal_df(n)
    cm = mm.fit_calibrated(d)
    assert cm.method == want, (n, cm.method)
    p, raw = cm.predict_proba(d[mm.FEATURES])[:, 1], cm.predict_raw(d[mm.FEATURES])
    assert ((p >= 0) & (p <= 1)).all() and abs(float(pd.Series(p).corr(pd.Series(raw), method="spearman"))) > 0.9
# a deliberately over-confident score gets pulled back toward the true win rate
big = cal_df(900, seed=3)
cm = mm.fit_calibrated(big.iloc[:700])
test = big.iloc[700:]
assert abs(cm.predict_proba(test[mm.FEATURES])[:, 1].mean() - test["label"].mean()) < 0.1
print("4 ok: calibration (isotonic / sigmoid / none by sample size), Brier + reliability table in walk-forward")

# ---- 5. financial anomaly detection
import anomaly as an
import screener_in as si
YRS = [f"Mar {y}" for y in range(2016, 2026)] + ["TTM"]
def grid(**rows): return {"cols": YRS, "rows": {k.replace("_", " "): v for k, v in rows.items()}}
def company(bad=False, seed=0):
    r = np.random.default_rng(seed)
    n = 10
    sales = [1000 * 1.1 ** i for i in range(n)]
    pat = [s * 0.10 for s in sales]
    pbt = [p * 1.3 for p in pat]
    oi = [b * 0.05 for b in pbt]
    cfo = [p * (1.0 + r.normal(0, 0.05)) for p in pat]
    dd = [40 + r.normal(0, 1.0) for _ in range(n)]
    inv = [50 + r.normal(0, 1.0) for _ in range(n)]
    borr = [100 + r.normal(0, 3) for _ in range(n)]
    opm = [15 + r.normal(0, 0.5) for _ in range(n)]
    if bad:
        cfo = [c * 0.2 for c in cfo[:-1]] + [-20.0]
        dd[-1] = 75.0
        oi[-1] = pbt[-1] * 0.55
        borr = [100 * 1.5 ** i for i in range(n)]
        opm[-1] = 28.0
    t = lambda v: v + [v[-1]]
    return {"pl": grid(sales=t(sales), net_profit=t(pat), profit_before_tax=t(pbt), other_income=t(oi), **{"opm_%": t(opm)}),
            "bs": {"cols": YRS[:-1], "rows": {"borrowings": borr}},
            "ratios": {"cols": YRS[:-1], "rows": {"debtor days": dd, "inventory days": inv}},
            "cf": {"cols": YRS[:-1], "rows": {"cash from operating activity": cfo}}}
good, badc = company(False), company(True)
assert an.rule_flags(an.features_from_raw(good)) == []
names = {n for n, _ in an.rule_flags(an.features_from_raw(badc))}
assert {"cfo_vs_profit", "cfo_negative_with_profit", "debtor_days_jump", "other_income_high",
        "borrowings_outgrowing_sales", "opm_swing"} <= names, names
missing = an.features_from_raw({"pl": good["pl"]})                        # no cash flow / ratios / balance sheet
assert missing["cfo_pat_3y"] is None and an.rule_flags(missing) == []     # missing data: n/a, never a flag
# parser: the cash-flow section is read
html = ("<section id='cash-flow'><table><thead><tr><th></th><th>Mar 2024</th><th>Mar 2025</th></tr></thead><tbody>"
        "<tr><td>Cash from Operating Activity&nbsp;+</td><td>10</td><td>20</td></tr></tbody></table></section>")
assert si.parse_page(html)["cf"]["rows"]["cash from operating activity"] == [10.0, 20.0]
# universe run: one planted outlier among 45 normal companies, a bank, and a symbol that fails to load
raws = {f"OK{k}": company(False, seed=k) for k in range(45)}
raws["BAD"] = badc
def fake_get_raw(sym):
    if sym == "BROKEN": raise RuntimeError("blocked")
    return raws[sym]
si.get_raw = fake_get_raw
items = [(k, "Capital Goods") for k in raws] + [("BANKCO", "Financial Services"), ("BROKEN", "Capital Goods")]
res = an.analyse_many(items)
assert res["BAD"]["anomaly_level"] == "High" and res["BAD"]["anomaly_iso_pct"] >= 95, res["BAD"]
assert "cfo_vs_profit" in res["BAD"]["anomaly_flags"] and "peer outlier" in res["BAD"]["anomaly_flags"]
assert all(res[f"OK{k}"]["anomaly_level"] != "High" for k in range(45))
assert res["BANKCO"]["anomaly_level"] == "n/a" and res["BROKEN"]["anomaly_level"] == "n/a" and "blocked" in res["BROKEN"]["anomaly_notes"]
one = an.analyse_many([("BAD", "Capital Goods")])["BAD"]                    # too few peers: rules only, and says so
assert one["anomaly_level"] == "High" and one["anomaly_iso_pct"] is None and "peer layers need" in one["anomaly_notes"]
# candidate thesis shows the anomaly
c = Candidate("BAD", "x", 5, 6, 100, 95, 110, 10, 1000, 50, "", anomaly_level="High", anomaly_flags="cfo_vs_profit: x")
assert "financial anomalies (High)" in CandidateEngine.build_thesis(c)
print("5 ok: anomaly rules, no flags on missing data, peer z-score + Isolation Forest, bank/err = n/a, cash-flow parsing")

print("\nAll ML-layer checks passed.")
