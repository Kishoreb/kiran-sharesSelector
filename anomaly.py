#!/usr/bin/env python3
"""
Financial anomaly detection ("forensic accounting" flags) from screener.in statements.

The regex/news layer only sees problems somebody wrote a headline about. This module looks at the numbers
themselves and flags patterns that often precede or accompany trouble:

  cfo_vs_profit               3-year operating cash flow is under 50% of 3-year net profit
  cfo_negative_with_profit    latest-year operating cash flow is negative although profit is positive
  debtor_days_jump            debtor days up 30%+ (and 10+ days) vs the average of the previous 3 years
  inventory_days_jump         same for inventory days
  other_income_high           other income is 40%+ of profit before tax, or jumped 20+ points vs its 3-year average
  borrowings_outgrowing_sales 3-year borrowings CAGR is 15%+ and 20+ points above the sales CAGR
  opm_swing                   operating margin moved 8+ points vs its 3-year average (either direction)

Two statistical layers need peers, so they only run when enough companies are analysed together:
  * robust z-scores (median / MAD) per metric, adverse direction only, flagged beyond 3.5   (8+ companies)
  * Isolation Forest over all metrics -> `anomaly_iso_pct`, how unusual the company is vs the others  (30+ companies)

Level: High = 2+ rule flags; Watch = 1 rule flag, or a peer outlier, or Isolation Forest in the top 5%;
None = nothing flagged; n/a = no usable statements (or a bank / NBFC, where these ratios do not apply).

Honest limits: screen-only (live snapshot of the latest annual statements, never used in the backtester); screener.in
coverage and labels vary; a flag is a reason to read the filings, not a verdict (capex phases, acquisitions, lumpy
receivables and one-off income all trigger these rules legitimately). Every flag shows the numbers behind it.

    python anomaly.py POLYCAB VMART TITAN           # quick look (cached screener.in pages, polite delay)
"""

import statistics
import sys

import screener_in as si

FINANCIAL_KEYWORD = "financ"
Z_CUT = 3.5
MIN_Z_PEERS = 8
MIN_IF_PEERS = 30
IF_TOP_PCT = 95.0

# metric -> adverse direction (+1 = high is bad, -1 = low is bad); opm_swing is compared in absolute terms
ADVERSE = {"cfo_pat_3y": -1, "debtor_days_pct": 1, "inventory_days_pct": 1, "oi_share": 1,
           "borr_gap": 1, "opm_swing": 1}
LABELS = {"cfo_pat_3y": "3y operating cash flow / net profit", "debtor_days_pct": "debtor-days change %",
          "inventory_days_pct": "inventory-days change %", "oi_share": "other income share of PBT %",
          "borr_gap": "borrowings CAGR minus sales CAGR (pts)", "opm_swing": "operating margin swing (pts)"}


# ---------------------------------------------------------------- features
def _series(grid, *names):
    """{column label: value} for one statement row (None values dropped), in column order."""
    row = si._row(grid, *names) if grid else None
    if row is None:
        return {}
    return {c: v for c, v in zip(grid["cols"], row) if v is not None}


def _cagr3(d, years):
    ys = [y for y in years if y in d][-4:]
    if len(ys) < 4 or d[ys[0]] <= 0 or d[ys[-1]] <= 0:
        return None
    return ((d[ys[-1]] / d[ys[0]]) ** (1 / 3) - 1) * 100


def _vs_prior(d, years, k=3, min_prior=2):
    """(latest value, mean of up to k previous values) or None."""
    ys = [y for y in years if y in d]
    if len(ys) < min_prior + 1:
        return None
    prior = [d[y] for y in ys[-(k + 1):-1]]
    return d[ys[-1]], sum(prior) / len(prior)


def features_from_raw(raw: dict) -> dict:
    """Metric dict from a screener_in.get_raw() result. Missing inputs give None, never a guess."""
    pl, bs, ra = si.annual_only(raw.get("pl")), si.annual_only(raw.get("bs")), si.annual_only(raw.get("ratios"))
    cf = si.annual_only(raw.get("cf")) if raw.get("cf") else None
    years = pl["cols"] if pl else []
    sales, pat = _series(pl, "sales", "revenue"), _series(pl, "net profit")
    pbt, oi, opm = _series(pl, "profit before tax"), _series(pl, "other income"), _series(pl, "opm %", "opm")
    dd, inv = _series(ra, "debtor days"), _series(ra, "inventory days")
    borr, cfo = _series(bs, "borrowings"), _series(cf, "cash from operating activity", "cash from operating")

    f = {k: None for k in ("cfo_pat_3y", "cfo_pat_years", "cfo_negative_with_profit", "debtor_days",
                           "debtor_days_abs", "debtor_days_pct", "inventory_days_abs", "inventory_days_pct",
                           "oi_share", "oi_share_jump", "borr_cagr", "sales_cagr", "borr_gap", "opm_swing")}
    f["history_years"] = len(years)

    both = [y for y in years if y in cfo and y in pat]
    if both:
        f["cfo_negative_with_profit"] = 1.0 if cfo[both[-1]] < 0 < pat[both[-1]] else 0.0
        last3 = both[-3:]
        if len(last3) == 3 and sum(pat[y] for y in last3) > 0:
            f["cfo_pat_3y"] = sum(cfo[y] for y in last3) / sum(pat[y] for y in last3)
            f["cfo_pat_years"] = ", ".join(last3)

    for key, d in (("debtor_days", dd), ("inventory_days", inv)):
        vp = _vs_prior(d, years)
        if vp and vp[1] > 0:
            f[key + "_abs"] = vp[0] - vp[1]
            f[key + "_pct"] = (vp[0] / vp[1] - 1) * 100
            if key == "debtor_days":
                f["debtor_days"] = vp[0]

    shares = {y: oi[y] / pbt[y] * 100 for y in years if y in oi and y in pbt and pbt[y] > 0}
    if shares:
        ys = [y for y in years if y in shares]
        f["oi_share"] = shares[ys[-1]]
        prior = [shares[y] for y in ys[-4:-1]]
        if len(prior) >= 2:
            f["oi_share_jump"] = shares[ys[-1]] - sum(prior) / len(prior)

    bc, sc = _cagr3(borr, [y for y in years if y in borr and y in sales]), _cagr3(sales, years)
    if bc is not None and sc is not None:
        f["borr_cagr"], f["sales_cagr"], f["borr_gap"] = bc, sc, bc - sc

    vp = _vs_prior(opm, years)
    if vp:
        f["opm_swing"] = vp[0] - vp[1]
    return f


# ---------------------------------------------------------------- rules
def rule_flags(f: dict):
    """[(name, text with the numbers)] for the transparent threshold rules."""
    out = []
    v = f.get("cfo_pat_3y")
    if v is not None and v < 0.5:
        out.append(("cfo_vs_profit", f"3y operating cash flow is {v * 100:.0f}% of net profit ({f.get('cfo_pat_years')})"))
    if f.get("cfo_negative_with_profit"):
        out.append(("cfo_negative_with_profit", "latest-year operating cash flow negative despite positive profit"))
    for key, label in (("debtor_days", "debtor days"), ("inventory_days", "inventory days")):
        pct, ab = f.get(key + "_pct"), f.get(key + "_abs")
        if pct is not None and pct >= 30 and ab >= 10:
            out.append((key + "_jump", f"{label} up {pct:.0f}% ({ab:+.0f} days) vs the previous 3-year average"))
    sh, jump = f.get("oi_share"), f.get("oi_share_jump")
    if (sh is not None and sh >= 40) or (jump is not None and jump >= 20):
        out.append(("other_income_high", f"other income is {sh:.0f}% of PBT"
                    + (f" ({jump:+.0f} pts vs 3-year average)" if jump is not None else "")))
    gap, bc = f.get("borr_gap"), f.get("borr_cagr")
    if gap is not None and gap >= 20 and bc >= 15:
        out.append(("borrowings_outgrowing_sales",
                    f"borrowings {bc:.0f}% CAGR vs sales {f['sales_cagr']:.0f}% CAGR (3y)"))
    sw = f.get("opm_swing")
    if sw is not None and abs(sw) >= 8:
        out.append(("opm_swing", f"operating margin {sw:+.1f} pts vs its 3-year average"))
    return out


# ---------------------------------------------------------------- peers
def _metric(f, k):
    v = f.get(k)
    if v is None:
        return None
    return abs(v) if k == "opm_swing" else v


def _z_flags(feats: dict):
    """{symbol: [text]} robust-z outliers (adverse direction only), per metric with enough peers."""
    out = {s: [] for s in feats}
    for k, sign in ADVERSE.items():
        vals = {s: _metric(f, k) for s, f in feats.items() if _metric(f, k) is not None}
        if len(vals) < MIN_Z_PEERS:
            continue
        med = statistics.median(vals.values())
        mad = statistics.median(abs(x - med) for x in vals.values()) * 1.4826
        if mad <= 0:
            continue
        for s, x in vals.items():
            z = (x - med) / mad
            if z * sign > Z_CUT:
                out[s].append(f"peer outlier: {LABELS[k]} {x:.1f} (z={z:+.1f} vs median {med:.1f})")
    return out


def _iso_scores(feats: dict):
    """{symbol: percentile 0-100 of how unusual the company is}. Empty when too few companies / no sklearn."""
    cols = list(ADVERSE)
    rows = {s: [_metric(f, k) for k in cols] for s, f in feats.items()}
    rows = {s: r for s, r in rows.items() if sum(v is not None for v in r) >= 4}
    if len(rows) < MIN_IF_PEERS:
        return {}
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return {}
    X = np.array([[np.nan if v is None else v for v in r] for r in rows.values()], dtype=float)
    med = np.nanmedian(X, axis=0)
    X = np.where(np.isnan(X), med, X)
    X = np.clip(StandardScaler().fit_transform(np.nan_to_num(X)), -6, 6)
    m = IsolationForest(n_estimators=200, random_state=0).fit(X)
    raw = -m.decision_function(X)                      # higher = more unusual
    order = raw.argsort().argsort()
    return {s: round(float(o) / (len(raw) - 1) * 100, 1) for s, o in zip(rows, order)}


def _level(n_rules, n_z, iso):
    if n_rules >= 2:
        return "High"
    if n_rules == 1 or n_z or (iso is not None and iso >= IF_TOP_PCT):
        return "Watch"
    return "None"


def analyse_many(items, log=None) -> dict:
    """items: [(symbol, industry)]. Returns {symbol: {anomaly_level, anomaly_flags, anomaly_iso_pct, anomaly_n,
    anomaly_notes}}. Never raises; a symbol whose statements cannot be read gets level 'n/a' and a note."""
    feats, res, fin = {}, {}, set()
    for sym, industry in items:
        if FINANCIAL_KEYWORD in (industry or "").lower():
            fin.add(sym)
            res[sym] = {"anomaly_level": "n/a", "anomaly_flags": "", "anomaly_iso_pct": None, "anomaly_n": 0,
                        "anomaly_notes": "bank / NBFC: these ratios do not apply"}
            continue
        try:
            f = features_from_raw(si.get_raw(sym))
            if f["history_years"] < 4:
                raise ValueError(f"only {f['history_years']} annual columns")
            feats[sym] = f
        except Exception as e:
            res[sym] = {"anomaly_level": "n/a", "anomaly_flags": "", "anomaly_iso_pct": None, "anomaly_n": 0,
                        "anomaly_notes": f"{type(e).__name__}: {e}"[:160]}
            if log:
                log(f"  {sym}: anomaly data unavailable ({e})")
    z, iso = _z_flags(feats), _iso_scores(feats)
    for sym, f in feats.items():
        rules = rule_flags(f)
        missing = [k for k in ("cfo_pat_3y", "debtor_days_pct", "oi_share", "borr_gap", "opm_swing") if f.get(k) is None]
        texts = [f"{n}: {t}" for n, t in rules] + z.get(sym, [])
        iso_pct = iso.get(sym)
        notes = []
        if missing:
            notes.append("not evaluated (no data): " + ",".join(missing))
        if not iso:
            notes.append(f"peer layers need {MIN_Z_PEERS}+ / {MIN_IF_PEERS}+ companies (have {len(feats)})")
        res[sym] = {"anomaly_level": _level(len(rules), len(z.get(sym, [])), iso_pct),
                    "anomaly_flags": "; ".join(texts), "anomaly_iso_pct": iso_pct,
                    "anomaly_n": len(rules) + len(z.get(sym, [])), "anomaly_notes": " | ".join(notes)}
    return res


def analyse(symbol: str, industry: str = "") -> dict:
    return analyse_many([(symbol, industry)])[symbol]


def main():
    syms = [s.upper() for s in sys.argv[1:]]
    if not syms:
        sys.exit("usage: python anomaly.py SYMBOL [SYMBOL ...]")
    for sym, r in analyse_many([(s, "") for s in syms], log=print).items():
        print(f"{sym:<14} {r['anomaly_level']:<6} {r['anomaly_flags'] or r['anomaly_notes'] or 'no flags'}")
    print("\nA reason to read the filings, not a verdict.")


if __name__ == "__main__":
    main()
