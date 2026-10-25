"""
Offline test of `screener.py screen` wiring (no network): fundamentals + qualitative are OFF by default and
switched on with --fundamentals / --qualitative, --weights-file is optional, the new CSV columns are written.

    python test_screen_enrich.py
"""
import io
import contextlib
import os
import sys
import tempfile

import numpy as np
import pandas as pd

import candidate_engine
import fundamentals as fund
import qualitative as qual
import screener
from data import add_indicators

TMP = tempfile.mkdtemp()


def pullback_df(k=12, pk=250):
    n = pk + k + 2
    c = 100 * 1.006 ** np.arange(n)
    peak = c[pk]
    for j in range(1, k + 1):
        c[pk + j] = peak * (0.992 ** j)
    c[pk + k + 1] = peak * 1.05
    o = c.copy()
    df = pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.003, "Low": np.minimum(o, c) * 0.997,
                       "Close": c, "Volume": np.full(n, 1e7)}, index=pd.bdate_range("2024-01-01", periods=n))
    return add_indicators(df)


DF = pullback_df()
candidate_engine.fetch_history = lambda sym, period="2y", interval="1d": DF
candidate_engine.fetch_market_cap_cr = lambda sym: 30000.0
screener.fetch_history = lambda sym, period="2y", interval="1d": DF
qual.symbol_name_map = lambda: {}

METRICS = {"roce": 20.0, "roe_avg": 18.0, "de": 0.1, "icr": float("inf"), "sales_growth": 12.0, "pat_growth": 15.0,
           "pe": 20.0, "peg": 1.3, "industry_pe": 25.0, "industry_pe_n": 8, "industry_pe_src": "screener.in peer median",
           "promoter_pct": 60.0, "promoter_decline_streak": 0, "promoter_change_1q": 0.1, "pledged_pct": 0.0,
           "pledged_change_1q": 0.0, "fii_pct": 11.4, "fii_change_1q": 0.5, "dii_pct": 9.4, "dii_change_1q": -0.3,
           "ownership_notes": "", "source": "screener.in"}
calls = {"fund": 0, "qual": 0}


def fake_metrics(sym):
    calls["fund"] += 1
    return dict(METRICS), ""


def fake_qual(sym, name=None, **kw):
    calls["qual"] += 1
    return {"sentiment_30d": 0.4, "sentiment_trend": 0.1, "sentiment_label": "Positive", "flag_severity": "Medium",
            "flag_text": "mgmt_exit [Medium, news, 2026-10-01]", "q_notes": ""}


fund.get_metrics, qual.analyse = fake_metrics, fake_qual


ON = ["--fundamentals", "flag", "--qualitative", "flag"]


def run(*extra, weights=None):
    out = os.path.join(TMP, "out.csv")
    argv = ["screener.py", "screen", "--symbols", "AAA", "--max-stop-pct", "0", "--out", out, *extra]
    if weights is not None:
        wf = os.path.join(TMP, "w.csv")
        open(wf, "w").write(weights)
        argv += ["--weights-file", wf]
    sys.argv = argv
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        screener.main()
    return pd.read_csv(out, keep_default_na=False), buf.getvalue()


# ---- both layers switched on, weights file read
W = "rule,weight\npat_growth,2\npeg,0\nsales_growth,1\n"
df, text = run(*ON, weights=W)
row = df[df.symbol == "AAA"].iloc[0]
assert calls["fund"] == 1 and calls["qual"] == 1, calls
assert row.fund_status == "fail"                                    # dii_trend failed (DII fell)
# peg weight 0 -> skipped; pat_growth weighs 2; pe_vs_industry 20 <= 25 x 1.1 passes; dii_trend fails
assert "peg" not in row.fund_notes and "failed: dii_trend" in row.fund_notes, row.fund_notes
n_rules = 13 - 1                                                    # 13 rules, peg skipped; promoter rules all evaluated
# (the TOTAL row makes every column text, so numbers are converted before comparing)
assert float(row.fund_evaluated) == n_rules, row.fund_evaluated
assert float(row.fund_passed) == n_rules - 1 and float(row.fund_passed_w) == n_rules - 1 + 1 \
    and float(row.fund_evaluated_w) == n_rules + 1, (row.fund_passed, row.fund_passed_w, row.fund_evaluated_w)   # pat_growth counts 2
assert row.fund_score == f"{n_rules}/{n_rules + 1}" and row.fund_tier == "Strong", row.fund_score
for col, want in (("industry_pe", 25.0), ("sales_growth_pct", 12.0), ("pat_growth_pct", 15.0), ("promoter_change_1q", 0.1),
                  ("pledged_change_1q", 0.0), ("fii_pct", 11.4), ("fii_change_1q", 0.5), ("dii_pct", 9.4),
                  ("dii_change_1q", -0.3), ("sentiment_30d", 0.4)):
    assert float(row[col]) == want, (col, row[col])
assert row.sentiment_label == "Positive" and "mgmt_exit" in row.qual_flags and "FII 11.4% (+0.50 pp)" in row.thesis, row.thesis
print("screen ok: fundamentals + qualitative ran, weights applied, new columns written")

# ---- weights drive the ranking points
cand = candidate_engine.Candidate("X", "s", 5, 8, 100, 95, 110, 1, 100, 5, "", fund_status="pass", fund_passed=3, fund_passed_w=7.0)
assert candidate_engine.CandidateEngine.points(cand, 1.0) == 12.0 and candidate_engine.CandidateEngine.points(cand, 0) == 5
print("ranking ok: points use passed weight")

# ---- no weights file: every rule weighs 1, peg evaluated (and fails)
df, text = run(*ON)
row = df[df.symbol == "AAA"].iloc[0]
assert float(row.fund_evaluated) == 13 and "peg" in row.fund_notes and row.fund_score == "11/13", (row.fund_evaluated, row.fund_notes, row.fund_score)
print("no weights file ok")

# ---- industry P/E override file beats the page value (P/E 20 vs industry 10 x 1.1 -> fails)
ov = os.path.join(TMP, "ipe.csv")
open(ov, "w").write("industry,pe\nUnknown,10\n")
df, text = run(*ON, "--industry-pe-file", ov)
assert "pe_vs_industry" in df[df.symbol == "AAA"].iloc[0].fund_notes and float(df[df.symbol == "AAA"].iloc[0].industry_pe) == 10.0
print("industry P/E override ok")

# ---- each layer works alone, and with no flags both stay off (the default)
calls.update(fund=0, qual=0)
df, _ = run("--fundamentals", "flag")
assert calls == {"fund": 1, "qual": 0} and df[df.symbol == "AAA"].iloc[0].fund_status != "" and df[df.symbol == "AAA"].iloc[0].sentiment_label == ""
calls.update(fund=0, qual=0)
df, _ = run("--qualitative", "flag")
assert calls == {"fund": 0, "qual": 1} and df[df.symbol == "AAA"].iloc[0].fund_status == ""
calls.update(fund=0, qual=0)
df, text = run()
r = df[df.symbol == "AAA"].iloc[0]
assert calls == {"fund": 0, "qual": 0} and r.fund_status == "" and r.sentiment_label == "" and r.fund_score == "", calls
print("switches ok: each layer alone, both off by default")

# ---- update-price still works on the wider CSV (every existing column preserved)
screener.fetch_history = lambda sym, period="5d", interval="1d": DF
before = pd.read_csv(os.path.join(TMP, "out.csv"), dtype=str, keep_default_na=False)
sys.argv = ["screener.py", "update-price", "--file", os.path.join(TMP, "out.csv"), "--date", "2026-10-21"]
with contextlib.redirect_stdout(io.StringIO()):
    screener.main()
after = pd.read_csv(os.path.join(TMP, "out.csv"), dtype=str, keep_default_na=False)
assert list(after.columns) == list(before.columns) + ["price on 2026-10-21"] and after[before.columns].equals(before)
print("\nAll screen-enrichment checks passed.")
