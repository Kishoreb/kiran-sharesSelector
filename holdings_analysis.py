#!/usr/bin/env python3
"""
holdings_analysis.py
====================
Runs the existing toolkit over the stocks you ALREADY HOLD (the *_holdings.xls
written by cdsl_holdings_to_xls.py) and writes one row per holding.

Reuses, unchanged:
  data.fetch_history / fetch_market_cap_cr   prices + indicators (Yahoo)
  strategies.trend_intact / signal           same trend rules + TechnicalFilters as `screen`
  fundamentals.get_metrics / evaluate        section-1 fundamentals (cached 7 days)
  universe.get_index_constituents            NSE industry for the sector view

What it adds: ISIN -> NSE symbol mapping, position weights, a trend state, a
rule-based stop level and the rupee risk to it, and portfolio-level flags.

The CAS has no cost price or buy date, so P&L and the `monitor` command's
entry-based checks cannot be done. The stop here is the strategy's own
structure stop (higher of 20-day swing low and 50-EMA, if below price).

Output is a rule check, not a buy/sell recommendation.

    python holdings_analysis.py Kiran_2026-06_holdings.xls
    python holdings_analysis.py Kiran_2026-06_holdings.xls --index nifty500 --max-weight 20
    python holdings_analysis.py holdings.xls --symbol-map my_map.csv --skip-fundamentals
"""

import argparse
import csv
import io
import os
import re
import sys
import time
from collections import defaultdict

import pandas as pd
import requests

import fundamentals as fund
import fund_weights as fw
import qualitative as qual
import universe
from data import classify_market_cap, fetch_history, fetch_market_cap_cr
from strategies import STRATEGIES, TechnicalFilters

EQUITY_LIST_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

# ISIN -> NSE symbol, for the holdings in Kiran_2026-06_holdings.xls. Fallback only:
# the official NSE list (EQUITY_L.csv) and --symbol-map take precedence. VERIFY these.
BUILTIN_SYMBOLS = {
    "INE883F01010": "AADHARHFC", "INE117A01022": "ABB", "INE079A01024": "AMBUJACEM",
    "INE852O01025": "APTUS", "INE563J01010": "ASTEC", "INE192R01011": "DMART",
    "INE02IJ01035": "AZAD", "INE377Y01014": "BAJAJHFL", "INE02RE01045": "FIRSTCRY",
    "INE290S01011": "CARTRADE", "INE739E01017": "CERA", "INE259A01022": "COLPAL",
    "INE111A01025": "CONCOR", "INE0JS101016": "DREAMFOLKS", "INE128S01021": "FIVESTAR",
    "INE127D01025": "HDFCAMC", "INE066F01020": "HAL", "INE202E01016": "IREDA",
    "INE115Q01022": "IKS", "INE953L01027": "JSFB", "INE749A01030": "JINDALSTEL",
    "INE970X01018": "LEMONTREE", "INE115A01026": "LICHSGFIN", "INE414G01012": "MUTHOOTFIN",
    "INE045601023": "PARAS", "INE417T01026": "POLICYBZR", "INE455K01017": "POLYCAB",
    "INE630A01024": "SESHAPAPER", "INE003A01024": "SIEMENS", "INE01A001028": "STANLEY",
    "INE280A01028": "TITAN", "INE849A01020": "TRENT", "INE974X01010": "TIINDIA",
    "INE665J01013": "VMART", "INE945H01021": "V2RETAIL", "INE205A01025": "VEDL",
    "INE01EA01019": "VMM", "INE226A01021": "VOLTAS", "INE274F01020": "WESTLIFE",
}

FIN_NAME_RE = re.compile(r"FINANCE|FINANCIAL|BANK|HOUSING FIN|ASSET MANAGEMENT|AMC", re.I)


# ----------------------------------------------------------------- loading
def clean_name(s):
    s = re.split(r"#| - |\[", str(s))[0]
    return re.sub(r"\s+", " ", s).strip()


def load_holdings(path):
    try:
        df = pd.read_excel(path, sheet_name="Holdings")
    except ValueError:
        df = pd.read_excel(path)
    df = df[df["ISIN"].notna()]
    out = {}
    for _, r in df.iterrows():
        isin = str(r["ISIN"]).strip()
        h = out.setdefault(isin, {"isin": isin, "name": clean_name(r["Security"]), "qty": 0.0,
                                  "value": 0.0, "price": float(r["Market Price / Face Value"]),
                                  "dps": []})
        h["qty"] += float(r["Current Bal"])
        h["value"] += float(r["Value (Rs)"])
        dp = str(r.get("Demat Account (DP)", "")).strip()
        if dp and dp not in h["dps"]:
            h["dps"].append(dp)
    return list(out.values())


def nse_isin_map(refresh=False):
    """ISIN -> symbol from NSE's official equity list (cached 7 days). {} if unreachable."""
    path = os.path.join(universe.CACHE_DIR, "equity_l.csv")
    text = None
    if not refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) < 7 * 86400:
        text = open(path, encoding="utf-8").read()
    else:
        try:
            r = requests.get(EQUITY_LIST_URL, headers=universe.HEADERS, timeout=15)
            r.raise_for_status()
            text = r.text
            os.makedirs(universe.CACHE_DIR, exist_ok=True)
            open(path, "w", encoding="utf-8").write(text)
        except Exception as e:
            print(f"  [warning] could not fetch NSE equity list ({e})")
            if os.path.exists(path):
                text = open(path, encoding="utf-8").read()
    out = {}
    for row in csv.DictReader(io.StringIO(text or "")):
        row = {(k or "").strip().upper(): (v or "").strip() for k, v in row.items()}
        if row.get("ISIN NUMBER") and row.get("SYMBOL"):
            out[row["ISIN NUMBER"]] = row["SYMBOL"]
    return out


def read_symbol_map(path):
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0].strip() and not row[0].startswith("#") and row[0].lower() != "isin":
                out[row[0].strip()] = row[1].strip().upper()
    return out


def resolve_symbols(holdings, args):
    nse = {} if args.no_nse_list else nse_isin_map()
    user = read_symbol_map(args.symbol_map) if args.symbol_map else {}
    for h in holdings:
        isin = h["isin"]
        h["symbol"], h["symbol_src"], h["skip_reason"] = None, "", ""
        if isin.startswith("INF"):
            h["skip_reason"] = "Fund/ETF unit - stock rules do not apply"
        elif h["price"] <= 1.0:
            h["skip_reason"] = "Placeholder price (1.00) - probably unlisted, no market data"
        for src, m in (("--symbol-map", user), ("NSE list", nse), ("built-in (verify)", BUILTIN_SYMBOLS)):
            if isin in m:
                h["symbol"], h["symbol_src"] = m[isin], src
                break
        if not h["skip_reason"] and not h["symbol"]:
            h["skip_reason"] = "No NSE symbol found for this ISIN (add it with --symbol-map)"


# ----------------------------------------------------------------- analysis
def get_history(symbol, period):
    last = None
    for suffix in (".NS", ".BO"):
        try:
            return fetch_history(symbol + suffix, period=period), suffix
        except Exception as e:
            last = e
    raise last


def trend_state(above20, above50, rising50, above200):
    """Intact: all true. Broken: below 50-EMA and below 200-SMA. Otherwise Weakening."""
    known = [x for x in (above20, above50, rising50, above200) if x is not None]
    if not known or above50 is None:
        return "Insufficient data"
    if all(known) and len(known) == 4:
        return "Intact"
    if not above50 and (above200 is False or (above200 is None and not rising50)):
        return "Broken"
    return "Weakening"


def analyse(h, strategies, sector_map, fcfg, args, weights=None, ind_pe=None):
    r = {"symbol": h["symbol"], "isin": h["isin"], "name": h["name"], "qty": h["qty"],
         "value": round(h["value"], 2), "reported_price": h["price"], "demat": "; ".join(h["dps"]),
         "symbol_src": h["symbol_src"]}
    df, suffix = get_history(h["symbol"], args.period)
    i = len(df) - 1
    t = df.iloc[i]
    close = float(t["Close"])
    r.update(yahoo_symbol=h["symbol"] + suffix, data_date=str(df.index[i].date()), close=round(close, 2),
             price_vs_statement_pct=round((close / h["price"] - 1) * 100, 1) if h["price"] else None,
             bars=len(df))
    r["live_value"] = round(close * h["qty"], 2)

    sma200, hi252 = t.get("sma200"), t.get("high_252")
    r["pct_vs_sma200"] = round((close / sma200 - 1) * 100, 1) if pd.notna(sma200) else None
    r["pct_below_52w_high"] = round((1 - close / hi252) * 100, 1) if pd.notna(hi252) else None
    r["ret_3m_pct"] = round((close / float(df["Close"].iloc[i - 63]) - 1) * 100, 1) if i >= 63 else None
    r["ret_1y_pct"] = round((close / float(df["Close"].iloc[i - 252]) - 1) * 100, 1) if i >= 252 else None

    if "avg_value20" in df.columns:
        av = t.get("avg_value20")
    else:
        av = (df["Close"] * df["Volume"]).rolling(20).mean().iloc[i]
    r["avg_traded_value_cr"] = round(float(av) / 1e7, 2) if pd.notna(av) else None
    r["position_pct_of_daily_turnover"] = round(r["live_value"] / float(av) * 100, 1) if pd.notna(av) and av > 0 else None

    ti = strategies["pullback_trend"].trend_intact(df, i)
    above20, above50, rising50 = ti["price_above_20ema"], ti["price_above_50ema"], ti["ema50_sloping_up"]
    above200 = bool(close > sma200) if pd.notna(sma200) else None
    r.update(above_20ema=above20, above_50ema=above50, ema50_rising=rising50, above_200sma=above200)
    r["trend_state"] = trend_state(above20, above50, rising50, above200)

    # structure stop, same construction as the pullback strategy
    swing_low = float(df["Low"].iloc[max(0, i - 20):i + 1].min())
    cands = [x for x in (swing_low, float(t["ema50"])) if x < close]
    stop = max(cands) if cands else None
    r["stop"] = round(stop, 2) if stop else None
    r["stop_pct"] = round((close - stop) / close * 100, 1) if stop else None
    r["risk_to_stop_rs"] = round((close - stop) * h["qty"], 2) if stop else None

    for name, strat in strategies.items():
        sig = strat.signal(df, i)
        r[f"{name}_signal"] = f"{sig.score}/{sig.total}" + (" ENTRY" if sig.enter else "")

    cap_cr = fetch_market_cap_cr(h["symbol"]) if not args.skip_marketcap else None
    r["market_cap_cr"] = cap_cr
    r["cap_class"] = classify_market_cap(cap_cr)
    sector = sector_map.get(h["symbol"].upper())
    if not sector:
        sector = "Financial Services" if FIN_NAME_RE.search(h["name"]) else "Unknown"
        r["sector_src"] = "guessed from name" if sector != "Unknown" else ""
    r["sector"] = sector

    if fcfg is not None:
        m, err = fund.get_metrics(h["symbol"])
        res = fund.evaluate(m, sector, fcfg, fund.override_for(ind_pe, sector))
        sc = fw.score(res, weights)
        r["industry_pe"], r["industry_pe_src"] = res.get("industry_pe"), res.get("industry_pe_src")
        r["fund_score"] = sc["text"]                  # passed weight / evaluated weight, e.g. "5/7"
        r["fund_score_pct"] = sc["pct"]
        r["fund_tier"] = fw.tier(sc["pct"], args.fund_strong, args.fund_weak)
        notes = []
        if res["failed"]:
            notes.append("failed: " + ",".join(res["failed"]))
        if res["unknown"]:
            notes.append("n/a: " + ",".join(res["unknown"]))
        if res["exempt"]:
            notes.append("exempt: " + ",".join(res["exempt"]))
        if err:
            notes.append("data: " + err)
        r["fund_notes"] = " | ".join(notes)
        if m:
            r["fund_source"] = m.get("source")
            r["history_years"] = m.get("history_years")
            for k_out, k in (("promoter_pct", "promoter_pct"), ("promoter_change_1q", "promoter_change_1q"),
                             ("promoter_change_4q", "promoter_change_4q"),
                             ("pledged_pct", "pledged_pct"), ("pledged_change_1q", "pledged_change_1q"),
                             ("pledged_pct_total", "pledged_pct_total"),
                             ("pledge_src", "pledge_src"), ("pledge_asof", "pledge_asof"), ("fii_pct", "fii_pct"), ("dii_pct", "dii_pct"),
                             ("fii_change_1q", "fii_change_1q"), ("dii_change_1q", "dii_change_1q"), ("ownership_notes", "ownership_notes"),
                             ("statements", "statements"), ("growth_from_standalone", "growth_from_standalone"), ("sales_cagr_5y", "sales_cagr_5y"), ("sales_cagr_10y", "sales_cagr_10y"),
                             ("pat_cagr_5y", "pat_cagr_5y"), ("pat_cagr_10y", "pat_cagr_10y")):
                r[k_out] = m.get(k)
            for k_out, k in (("roce_pct", "roce"), ("roe_avg_pct", "roe_avg"), ("debt_equity", "de"),
                             ("pe", "pe"), ("peg", "peg"), ("sales_growth_pct", "sales_growth"),
                             ("pat_growth_pct", "pat_growth")):
                v = m.get(k)
                r[k_out] = round(v, 2) if isinstance(v, float) and v != float("inf") else v
    if not args.skip_qualitative:
        names = getattr(args, "_names", None)
        if names is None:
            names = args._names = qual.symbol_name_map()
        q = qual.analyse(h["symbol"], names.get(h["symbol"].upper(), h["name"]), days=args.news_days,
                         scorer=getattr(args, "scorer", None), gov_model=getattr(args, "gov", None),
                         deduper=getattr(args, "deduper", None))
        for k in ("news_n_30d", "news_dupes_removed", "sentiment_30d", "sentiment_trend", "sentiment_label", "flag_severity",
                  "flag_text", "top_negative", "q_notes"):
            r[k] = q.get(k)
        r["_flags"] = q.get("flags") or []
    return r


def verdict(r):
    state = r.get("trend_state")
    base = {"Intact": "Hold - trend intact", "Weakening": "Watch - trend weakening",
            "Broken": "Review - trend broken"}.get(state, "Review - insufficient data")
    if r.get("fund_tier") == "Weak" and state in ("Weakening", "Broken"):
        base += " + weak fundamentals"
    if r.get("flag_severity") == "High":
        base += " + governance flag"
    return base


# ----------------------------------------------------------------- output
def build(args):
    holdings = load_holdings(args.file)
    resolve_symbols(holdings, args)
    print(f"{len(holdings)} distinct holdings (duplicates across demat accounts merged by ISIN)")
    sector_map = {}
    try:
        sector_map = {c["symbol"].upper(): c["industry"] for c in universe.get_index_constituents(args.index)}
    except Exception as e:
        print(f"  [warning] no sector info ({e})")

    flt = TechnicalFilters(min_avg_value_cr=args.min_turnover_cr, require_above_sma200=args.sma200,
                           max_pct_from_52w_high=args.max_from_high_pct)
    strategies = {n: cls(filters=flt) for n, cls in STRATEGIES.items()}
    weights = fw.load_weights(args.weights_file)
    fcfg, ind_pe = None, {}
    if not args.skip_fundamentals:
        skip = fw.skip_set(weights)
        fcfg = fund.FundamentalFilters(skip=skip, min_promoter=args.min_promoter, max_pledge=args.max_pledge)
        print("Fundamental rule weights: " + ", ".join(f"{k}={v:g}" for k, v in weights.items()))
        ind_pe = fund.load_industry_pe_overrides(args.industry_pe_file)
        if ind_pe:
            print(f"Industry P/E overrides loaded for {len(ind_pe)} industries.")

    rows, skipped = [], []
    for k, h in enumerate(holdings, 1):
        tag = f"[{k}/{len(holdings)}] {h['symbol'] or h['isin']:<12}"
        if h["skip_reason"]:
            print(f"  {tag} skipped: {h['skip_reason']}")
            skipped.append({"isin": h["isin"], "name": h["name"], "qty": h["qty"],
                            "value": round(h["value"], 2), "reason": h["skip_reason"]})
            continue
        try:
            r = analyse(h, strategies, sector_map, fcfg, args, weights, ind_pe)
            r["verdict"] = verdict(r)
            rows.append(r)
            print(f"  {tag} {r['trend_state']:<10} fund:{r.get('fund_score', '-')}")
        except Exception as e:
            print(f"  {tag} FAILED: {e}")
            skipped.append({"isin": h["isin"], "name": h["name"], "qty": h["qty"],
                            "value": round(h["value"], 2), "reason": f"data error: {e}"})
    return rows, skipped


def add_anomalies(rows):
    """Financial anomaly scan (anomaly.py) over all analysed holdings; z-scores / Isolation Forest use the
    holdings themselves as peers, so those layers only run with 8+ / 30+ stocks."""
    import anomaly
    print("Financial anomaly scan (screener.in statements, cached 7 days)...")
    res = anomaly.analyse_many([(r["symbol"], r.get("sector", "")) for r in rows], log=print)
    for r in rows:
        x = res.get(r["symbol"], {})
        r["anomaly_level"], r["anomaly_flags"] = x.get("anomaly_level"), x.get("anomaly_flags")
        r["anomaly_iso_pct"], r["anomaly_notes"] = x.get("anomaly_iso_pct"), x.get("anomaly_notes")


def add_portfolio_flags(rows, skipped, args):
    total = sum(r["live_value"] for r in rows) + sum(s["value"] for s in skipped)
    sec = defaultdict(float)
    for r in rows:
        r["weight_pct"] = round(r["live_value"] / total * 100, 2)
        sec[r["sector"]] += r["live_value"]
    for r in rows:
        flags = []
        if r["weight_pct"] > args.max_weight:
            flags.append(f"concentration {r['weight_pct']}% > {args.max_weight}% cap")
        sw = sec[r["sector"]] / total * 100
        if r["sector"] != "Unknown" and sw > args.max_sector_weight:
            flags.append(f"sector {r['sector']} {sw:.0f}% of portfolio")
        pt = r.get("position_pct_of_daily_turnover")
        if pt is not None and pt > 5:
            flags.append(f"position = {pt}% of a day's turnover (exit friction)")
        if r.get("flag_text"):
            flags.append("governance: " + r["flag_text"])
        if r.get("anomaly_level") in ("High", "Watch") and r.get("anomaly_flags"):
            flags.append(f"financial anomalies ({r['anomaly_level']}): " + r["anomaly_flags"])
        if r.get("above_200sma") is None:
            flags.append("<200 bars: 200-SMA unavailable")
        if abs(r.get("price_vs_statement_pct") or 0) > 25:
            flags.append("price moved >25% since statement")
        r["flags"] = "; ".join(flags)
    rows.sort(key=lambda r: -r["live_value"])
    return total, dict(sorted(sec.items(), key=lambda kv: -kv[1]))


def summary_sheet(rows, skipped, total, sec):
    risk = sum(r["risk_to_stop_rs"] or 0 for r in rows)
    lines = [("Portfolio value (statement-date, all rows)", round(sum(r["value"] for r in rows) + sum(s["value"] for s in skipped), 2)),
             ("Portfolio value (latest close, analysed rows + skipped at statement value)", round(total, 2)),
             ("Holdings analysed / skipped", f"{len(rows)} / {len(skipped)}"),
             ("Total rupee risk if every stop is hit", round(risk, 2)),
             ("  as % of portfolio", round(risk / total * 100, 2) if total else None)]
    by_v = defaultdict(lambda: [0, 0.0])
    for r in rows:
        by_v[r["verdict"]][0] += 1
        by_v[r["verdict"]][1] += r["live_value"]
    lines += [("", "")] + [(f"Verdict: {v}", f"{n} holdings, Rs {val:,.0f} ({val / total * 100:.1f}%)") for v, (n, val) in by_v.items()]
    lines += [("", "")] + [(f"Sector: {s}", f"Rs {v:,.0f} ({v / total * 100:.1f}%)") for s, v in sec.items()]
    return pd.DataFrame(lines, columns=["Item", "Value"])


def main():
    ap = argparse.ArgumentParser(description="Run the toolkit's rules over your existing holdings.")
    ap.add_argument("file", help="*_holdings.xls from cdsl_holdings_to_xls.py")
    ap.add_argument("--out", help="output .xlsx (default: <file>_analysis.xlsx)")
    ap.add_argument("--index", default="nifty500", choices=list(universe.INDEX_URLS), help="index used for sector lookup")
    ap.add_argument("--period", default="2y")
    ap.add_argument("--symbol-map", dest="symbol_map", help="CSV 'isin,symbol' overrides")
    ap.add_argument("--no-nse-list", action="store_true", dest="no_nse_list", help="don't download NSE's ISIN list")
    ap.add_argument("--skip-fundamentals", action="store_true", dest="skip_fundamentals")
    ap.add_argument("--weights-file", dest="weights_file", default=None,
                    help="CSV of 'rule,weight' (default: fundamental_weights.csv next to this script; 0 skips a rule)")
    ap.add_argument("--industry-pe-file", dest="industry_pe_file", default=None,
                    help="CSV 'industry,pe' you maintain; beats the screener.in peer median (default: industry_pe.csv if present)")
    ap.add_argument("--fund-strong", type=float, default=75.0, dest="fund_strong", help="score %% at/above which fundamentals are 'Strong'")
    ap.add_argument("--fund-weak", type=float, default=50.0, dest="fund_weak", help="score %% below which fundamentals are 'Weak'")
    ap.add_argument("--skip-marketcap", action="store_true", dest="skip_marketcap")
    ap.add_argument("--fund-source", choices=["screener", "yahoo"], default="screener", dest="fund_source",
                    help="fundamentals source: screener.in (up to 10y) or Yahoo (about 4y)")
    ap.add_argument("--growth-years", type=int, choices=[3, 5, 10], default=5, dest="growth_years",
                    help="horizon of the sales / PAT growth CAGR rules (falls back to shorter if not available)")
    ap.add_argument("--no-yahoo-fallback", action="store_true", dest="no_yahoo_fallback")
    ap.add_argument("--no-nse", action="store_true", dest="no_nse", help="skip NSE (promoter holding, pledging, announcements)")
    ap.add_argument("--min-promoter", type=float, default=50.0, dest="min_promoter")
    ap.add_argument("--max-pledge", type=float, default=5.0, dest="max_pledge")
    ap.add_argument("--skip-qualitative", action="store_true", dest="skip_qualitative",
                    help="skip news sentiment and governance red-flag scan")
    ap.add_argument("--news-days", type=int, default=90, dest="news_days")
    ap.add_argument("--llm", choices=["none", "ollama", "anthropic", "finbert"], default="none",
                    help="score headlines with a language model instead of the keyword lexicon")
    ap.add_argument("--llm-model", dest="llm_model", default=None)
    ap.add_argument("--ollama-url", dest="ollama_url", default=None)
    ap.add_argument("--gov-model", dest="gov_model", default=None,
                    help="governance false-positive classifier (gov_model.pkl from gov_classifier.py train)")
    ap.add_argument("--dedup", choices=["none", "lexical", "embed"], default="none",
                    help="drop near-duplicate headlines before scoring sentiment (embed = local sentence-embedding model)")
    ap.add_argument("--dedup-model", dest="dedup_model", default=None,
                    help="embedding model for --dedup embed (HF id or local folder; default all-MiniLM-L6-v2)")
    ap.add_argument("--refresh-cache", action="store_true", dest="refresh_cache",
                    help="ignore cached screener.in / NSE / news results and fetch everything fresh (--debug-dump implies this)")
    ap.add_argument("--debug-dump", dest="debug_dump", default=None,
                    help="folder to save raw screener.in pages and NSE JSON responses (for diagnosing layout changes)")
    ap.add_argument("--skip-anomalies", action="store_true", dest="skip_anomalies",
                    help="skip the financial anomaly scan (cash flow vs profit, debtor days, other income, ...)")
    ap.add_argument("--max-weight", type=float, default=25.0, dest="max_weight", help="flag positions above this %% of portfolio")
    ap.add_argument("--max-sector-weight", type=float, default=40.0, dest="max_sector_weight")
    ap.add_argument("--min-turnover-cr", type=float, default=1.0, dest="min_turnover_cr")
    ap.add_argument("--sma200", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--max-from-high-pct", type=float, default=20.0, dest="max_from_high_pct")
    args = ap.parse_args()

    fund.configure(provider=args.fund_source, growth_years=args.growth_years, use_nse=not args.no_nse,
                   fallback=not args.no_yahoo_fallback, debug_dir=args.debug_dump, refresh=args.refresh_cache)
    args.scorer = qual.make_scorer(args.llm, args.llm_model, args.ollama_url)
    args.gov = qual.load_gov_model(args.gov_model)
    args.deduper = qual.make_deduper(args.dedup, args.dedup_model)
    rows, skipped = build(args)
    if not rows:
        sys.exit("Nothing could be analysed.")
    if not args.skip_anomalies:
        add_anomalies(rows)
    total, sec = add_portfolio_flags(rows, skipped, args)
    flag_rows = [{"symbol": r["symbol"], "severity": f["severity"], "flag": f["flag"], "source": f["source"],
                  "date": f["date"], "text": f["text"], "link": f["link"],
                  "ml_prob": f.get("ml_prob"), "label": ""}
                 for r in rows for f in r.get("_flags", [])]
    for r in rows:
        r.pop("_flags", None)
    df, sk, sm = pd.DataFrame(rows), pd.DataFrame(skipped), summary_sheet(rows, skipped, total, sec)
    front = [c for c in ["symbol", "name", "verdict", "weight_pct", "live_value", "qty", "close", "trend_state",
                         "fund_score", "fund_tier", "sentiment_label", "flag_severity", "anomaly_level", "flags"] if c in df.columns]
    df = df[front + [c for c in df.columns if c not in front]]

    out = args.out or os.path.splitext(args.file)[0] + "_analysis.xlsx"
    try:
        with pd.ExcelWriter(out, engine="openpyxl") as xw:
            sm.to_excel(xw, sheet_name="Summary", index=False)
            df.to_excel(xw, sheet_name="Holdings analysis", index=False)
            if len(sk):
                sk.to_excel(xw, sheet_name="Not analysed", index=False)
            if flag_rows:                       # every flag with the text that triggered it, to verify by eye
                pd.DataFrame(flag_rows).to_excel(xw, sheet_name="Governance flags", index=False)
            for ws in xw.sheets.values():
                ws.freeze_panes = "A2"
    except ImportError:
        out = os.path.splitext(out)[0] + ".csv"
        df.to_csv(out, index=False)
    print(f"\n{sm.to_string(index=False, header=False)}\n")
    for r in rows[:15]:
        print(f"  {r['symbol']:<12} {r['weight_pct']:>5}%  {r['verdict']:<40} {r['flags']}")
    print(f"\nSaved {out}\nA rule check against your own thresholds, not a buy/sell recommendation.")


if __name__ == "__main__":
    main()
