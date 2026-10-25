"""
Fundamentals (shortlisting doc, section 1).

Computes ROCE, ROE (multi-year average), debt-to-equity, interest coverage,
sales / PAT growth, P/E vs industry P/E and PEG from Yahoo Finance annual
statements, and checks them against configurable thresholds.

Design rules:
  * SCREEN ONLY. These are live snapshots of the latest annual statements,
    not point-in-time, so they must not be used inside the backtester
    (that would add lookahead bias on top of the survivorship bias).
  * Cached on disk (default 7 days) -- fundamentals change quarterly, and
    Yahoo calls are slow.
  * Missing data is "n/a", never a silent pass or fail. By default n/a does
    not reject a stock (Yahoo coverage of Indian small/mid caps has gaps);
    use strict=True to reject on any n/a.
  * P/E vs industry uses the INDUSTRY P/E of the company's own peer group (screener.in's peer-comparison
    median), or a value from industry_pe.csv if you maintain one. Not a median over the screened index.
  * Banks / NBFCs ("Financial Services" industry) are exempt from ROCE,
    debt-to-equity and interest coverage, which don't mean the same thing
    for lenders.
  * Yahoo typically gives ~4 annual periods, so "3Y CAGR" needs all four
    and "ROE average" is over however many (up to 5) are available.
"""

import csv
import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from data import to_yf_symbol

try:
    import yfinance as yf
except ImportError:
    yf = None

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "fundamentals")
CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # 7 days

# ---- data source settings (see configure()) ----
PROVIDER = "screener"        # "screener" (up to 10y of statements) or "yahoo" (~4y)
GROWTH_YEARS = 5             # horizon for the sales / PAT growth rules: 3, 5 or 10 (falls back to shorter)
USE_NSE = True               # fetch promoter holding / pledging from NSE
FALLBACK_YAHOO = True        # if the primary source fails for a symbol, use Yahoo instead
FORCE_REFRESH = False        # ignore every cache (statements, NSE, news)
METRICS_VERSION = 3          # bump when metrics change shape; older cache files are recomputed


def configure(provider=None, growth_years=None, use_nse=None, fallback=None, debug_dir=None, refresh=None):
    """One place to set the data source from CLI flags. debug_dir implies refresh: raw pages are only
    saved when they are actually fetched, so cached answers would leave the folder empty."""
    global PROVIDER, GROWTH_YEARS, USE_NSE, FALLBACK_YAHOO, FORCE_REFRESH
    if provider is not None:
        PROVIDER = provider
    if growth_years is not None:
        GROWTH_YEARS = growth_years
    if use_nse is not None:
        USE_NSE = use_nse
    if fallback is not None:
        FALLBACK_YAHOO = fallback
    if refresh or debug_dir:
        FORCE_REFRESH = True
        import nse_client, qualitative, screener_in
        screener_in.FORCE_REFRESH = nse_client.FORCE_REFRESH = qualitative.FORCE_REFRESH = True
        print("Cache bypass is ON: screener.in, NSE and news are fetched fresh"
              + (f"; raw responses are saved in {debug_dir}" if debug_dir else "") + ".")
    if debug_dir:
        import nse_client
        import screener_in
        screener_in.DEBUG_DIR = nse_client.DEBUG_DIR = debug_dir


FINANCIAL_KEYWORD = "financ"          # matches NSE industry "Financial Services"
FINANCIAL_EXEMPT_RULES = {"roce", "de", "icr"}
INDUSTRY_PE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "industry_pe.csv")

ALL_RULES = ["roce", "roe", "de", "icr", "sales_growth", "pat_growth", "pe_vs_industry", "peg",
             "promoter_holding", "promoter_trend", "pledging", "fii_trend", "dii_trend"]


@dataclass
class FundamentalFilters:
    min_roce: float = 15.0            # %
    min_roe: float = 15.0             # % (multi-year average)
    max_de: float = 0.5               # ratio
    min_icr: float = 3.0              # x
    min_sales_growth: float = 10.0    # % (3Y CAGR if available, else YoY)
    min_pat_growth: float = 12.0      # % (3Y CAGR if available, else YoY)
    max_peg: float = 1.0
    pe_tolerance: float = 1.10        # "close to or lower than industry": P/E <= industry median x this
    min_promoter: float = 50.0        # % promoter holding (rule n/a for companies with ~no promoter)
    max_pledge: float = 5.0           # % of promoter shares pledged
    promoter_decline_quarters: int = 3   # fail if promoter holding fell in each of this many latest quarters
    min_fii_change: float = 0.0       # pp change in FII holding over the latest quarter (rule fails below this)
    min_dii_change: float = 0.0       # pp change in DII holding over the latest quarter (rule fails below this)
    skip: set = field(default_factory=set)   # rule names to disable, from ALL_RULES
    strict: bool = False              # True: any n/a rejects the stock


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------
def _cache_file(symbol: str) -> str:
    return os.path.join(CACHE_DIR, f"{symbol.strip().upper()}.json")


def _load(symbol: str) -> dict:
    try:
        with open(_cache_file(symbol), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(symbol: str, data: dict):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_file(symbol), "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass  # cache is best-effort


def _fresh(ts) -> bool:
    return ts is not None and (time.time() - ts) < CACHE_MAX_AGE_SECONDS


# --------------------------------------------------------------------------
# Metric computation (pure functions -- testable without network)
# --------------------------------------------------------------------------
def _series(df, names) -> Optional[pd.Series]:
    """First matching row of a yfinance statement as a numeric Series, oldest -> newest."""
    if df is None or getattr(df, "empty", True):
        return None
    for name in names:
        if name in df.index:
            s = pd.to_numeric(df.loc[name], errors="coerce").dropna()
            if len(s):
                s.index = pd.to_datetime(s.index)
                return s.sort_index()
    return None


def _latest_pair(a: Optional[pd.Series], b: Optional[pd.Series]):
    if a is None or b is None:
        return None, None
    common = a.index.intersection(b.index)
    if len(common) == 0:
        return None, None
    d = common.max()
    return float(a[d]), float(b[d])


def _growth(s: Optional[pd.Series]) -> Tuple[Optional[float], Optional[float]]:
    """(YoY %, 3Y CAGR %). Either is None if the base is missing or non-positive."""
    if s is None or len(s) < 2:
        return None, None
    last, prev = float(s.iloc[-1]), float(s.iloc[-2])
    yoy = (last / prev - 1) * 100 if prev > 0 and last > 0 else None
    cagr = None
    if len(s) >= 4:
        base = float(s.iloc[-4])
        if base > 0 and last > 0:
            cagr = ((last / base) ** (1 / 3) - 1) * 100
    return yoy, cagr


def compute_metrics(fin, bs, pe: Optional[float]) -> dict:
    """fin / bs are yfinance annual financials / balance_sheet DataFrames."""
    ebit = _series(fin, ["EBIT", "Operating Income"])
    rev = _series(fin, ["Total Revenue", "Operating Revenue"])
    ni = _series(fin, ["Net Income", "Net Income Common Stockholders"])
    interest = _series(fin, ["Interest Expense", "Interest Expense Non Operating"])
    ta = _series(bs, ["Total Assets"])
    cl = _series(bs, ["Current Liabilities", "Total Current Liabilities"])
    eq = _series(bs, ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"])
    debt = _series(bs, ["Total Debt"])

    out = {k: None for k in ("roce", "roe_avg", "roe_years", "de", "icr", "sales_growth",
                             "sales_growth_basis", "pat_growth", "pat_growth_basis", "pe", "peg")}

    # ROCE = EBIT / (total assets - current liabilities)
    if ebit is not None and ta is not None and cl is not None:
        capital = (ta - cl).dropna()
        e, c = _latest_pair(ebit, capital)
        if e is not None and c and c > 0:
            out["roce"] = e / c * 100

    # ROE: average of NI / equity over up to the last 5 years
    if ni is not None and eq is not None:
        common = ni.index.intersection(eq.index)
        vals = [float(ni[d]) / float(eq[d]) * 100 for d in sorted(common)[-5:] if float(eq[d]) > 0]
        if vals:
            out["roe_avg"] = sum(vals) / len(vals)
            out["roe_years"] = len(vals)

    # Debt / equity (latest year, same date)
    debt_latest = None
    if debt is not None and eq is not None:
        d_, e_ = _latest_pair(debt, eq)
        if d_ is not None and e_ and e_ > 0:
            out["de"] = d_ / e_
            debt_latest = d_
    elif debt is not None:
        debt_latest = float(debt.iloc[-1])

    # Interest coverage = EBIT / interest expense. No interest cost -> infinite coverage.
    if ebit is not None and interest is not None:
        e, i_ = _latest_pair(ebit, interest.abs())
        if e is not None:
            out["icr"] = float("inf") if i_ == 0 else e / i_
    if out["icr"] is None and debt_latest is not None and debt_latest == 0:
        out["icr"] = float("inf")

    # Growth: 3Y CAGR when 4 years exist, else YoY
    for key, s in (("sales_growth", rev), ("pat_growth", ni)):
        yoy, cagr = _growth(s)
        if cagr is not None:
            out[key], out[key + "_basis"] = cagr, "3Y CAGR"
        elif yoy is not None:
            out[key], out[key + "_basis"] = yoy, "YoY"

    # P/E and PEG (PEG = P/E / PAT growth %, only when both are positive)
    if pe is not None and pe > 0:
        out["pe"] = float(pe)
        if out["pat_growth"] is not None and out["pat_growth"] > 0:
            out["peg"] = out["pe"] / out["pat_growth"]
    return out


# --------------------------------------------------------------------------
# Fetching (network)
# --------------------------------------------------------------------------
def _fetch_info_pe(ticker) -> Optional[float]:
    try:
        pe = ticker.get_info().get("trailingPE")
        return float(pe) if pe and pe > 0 else None
    except Exception:
        return None


def _yahoo_metrics(symbol: str) -> Tuple[Optional[dict], str]:
    if yf is None:
        return None, "yfinance not installed"
    try:
        t = yf.Ticker(to_yf_symbol(symbol))
        fin, bs = t.financials, t.balance_sheet
        if fin is None or fin.empty or bs is None or bs.empty:
            return None, "no financial statements from Yahoo"
        m = compute_metrics(fin, bs, _fetch_info_pe(t))
        m["source"] = "yahoo"
        return m, ""
    except Exception as e:
        return None, str(e)


def get_metrics(symbol: str) -> Tuple[Optional[dict], str]:
    """
    Cached metrics for one symbol. Returns (metrics, note). Statement metrics come from
    PROVIDER (cached 7 days); ownership metrics (NSE + screener.in table) are added on
    every call from their own caches, so a transient NSE failure is retried next run.
    """
    cache = _load(symbol)
    metrics, note, raw = None, "", None
    if (not FORCE_REFRESH and _fresh(cache.get("metrics_ts")) and cache.get("metrics")
            and cache.get("provider") == PROVIDER and cache.get("ver") == METRICS_VERSION):
        metrics = dict(cache["metrics"])
    else:
        if PROVIDER == "screener":
            try:
                import screener_in
                raw = screener_in.get_raw(symbol)
                metrics = screener_in.metrics_from_raw(raw, GROWTH_YEARS)
            except Exception as e:
                note = f"screener.in: {e}"[:200]
                if not FALLBACK_YAHOO:
                    return None, note
        if metrics is None:
            metrics, yerr = _yahoo_metrics(symbol)
            if metrics is None:
                return None, (note + " | " if note else "") + yerr
            note = (note + " -> " if note else "") + "used Yahoo (about 4 years of history)"
        cache.update({"metrics": metrics, "metrics_ts": time.time(), "provider": PROVIDER, "ver": METRICS_VERSION,
                      "pe": metrics.get("pe"), "pe_ts": time.time()})
        _save(symbol, cache)
    if metrics.get("source") == "screener.in":
        import screener_in
        screener_in.pick_growth(metrics, GROWTH_YEARS)
    try:
        import ownership
        metrics.update(ownership.get(symbol, metrics, USE_NSE))
    except Exception as e:
        metrics["ownership_notes"] = f"ownership failed: {e}"[:160]
    if metrics.get("source") == "screener.in":          # industry P/E = median P/E of the company's screener.in peers
        try:
            import screener_in
            metrics.update(screener_in.get_industry_pe(symbol))
        except Exception as e:
            note = (note + " | " if note else "") + f"industry P/E: {e}"[:160]
    return metrics, note


def load_industry_pe_overrides(path: str = None) -> Dict[str, float]:
    """
    Optional file YOU maintain, one industry per line:   industry,pe
        Capital Goods,42.5
    Matched case-insensitively against the NSE industry name of the company. When present it takes
    precedence over screener.in's peer median. Missing file = no overrides (not an error).
    """
    path = path or INDUSTRY_PE_FILE
    out: Dict[str, float] = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 2 or not row[0].strip() or row[0].strip().startswith("#"):
                continue
            if row[0].strip().lower() == "industry":
                continue
            try:
                pe = float(row[1].split("#")[0].strip())
            except ValueError:
                continue
            if pe > 0:
                out[row[0].strip().lower()] = pe
    return out


def override_for(overrides: Optional[Dict[str, float]], industry: str):
    """(pe, 0, 'industry_pe file') for this industry, or None."""
    pe = (overrides or {}).get((industry or "").strip().lower())
    return (pe, 0, "industry_pe file") if pe else None


# --------------------------------------------------------------------------
# Rule evaluation
# --------------------------------------------------------------------------
def _status(value, ok) -> str:
    return "n/a" if value is None else ("pass" if ok(value) else "fail")


def evaluate(metrics: Optional[dict], industry: str, cfg: FundamentalFilters,
             industry_pe: Optional[tuple] = None) -> dict:
    """
    industry_pe: optional (pe, n_peers[, source]) that overrides the industry P/E carried in `metrics`
    (screener.in's peer median). With neither, the P/E-vs-industry rule is n/a.
    Returns {"status": pass|fail|n/a, "failed": [...], "unknown": [...], "exempt": [...], "industry_pe": ...}.
    status 'fail' = at least one rule failed (or, in strict mode, any rule is n/a).
    status 'n/a'  = nothing could be evaluated at all.
    """
    if metrics is None:
        return {"status": "n/a", "failed": [], "passed": [], "evaluated": 0,
                "unknown": [r for r in ALL_RULES if r not in cfg.skip], "exempt": []}

    is_financial = FINANCIAL_KEYWORD in (industry or "").lower()
    pe = metrics.get("pe")
    ipe = industry_pe
    ipe_src = (ipe[2] if ipe and len(ipe) > 2 else "override") if ipe else None
    if not ipe and metrics.get("industry_pe"):
        ipe = (metrics["industry_pe"], metrics.get("industry_pe_n") or 0)
        ipe_src = metrics.get("industry_pe_src") or "screener.in peer median"
    pe_vs = pe if (pe is not None and ipe) else None

    # widely-held companies (no promoter, ~0%) cannot be judged on promoter rules: those rules are n/a
    prom = metrics.get("promoter_pct")
    prom_known = prom if (prom is not None and prom >= 1.0) else None

    checks = {
        "roce": _status(metrics.get("roce"), lambda v: v >= cfg.min_roce),
        "roe": _status(metrics.get("roe_avg"), lambda v: v >= cfg.min_roe),
        "de": _status(metrics.get("de"), lambda v: v <= cfg.max_de),
        "icr": _status(metrics.get("icr"), lambda v: v >= cfg.min_icr),
        "sales_growth": _status(metrics.get("sales_growth"), lambda v: v >= cfg.min_sales_growth),
        "pat_growth": _status(metrics.get("pat_growth"), lambda v: v >= cfg.min_pat_growth),
        "pe_vs_industry": (_status(pe_vs, lambda v: v <= ipe[0] * cfg.pe_tolerance) if ipe else "n/a"),
        "peg": _status(metrics.get("peg"), lambda v: v < cfg.max_peg),
        "promoter_holding": _status(prom_known, lambda v: v >= cfg.min_promoter),
        "promoter_trend": _status(metrics.get("promoter_decline_streak") if prom_known is not None else None,
                                  lambda v: v < cfg.promoter_decline_quarters),
        "pledging": _status(metrics.get("pledged_pct") if prom_known is not None else None,
                            lambda v: v <= cfg.max_pledge),
        "fii_trend": _status(metrics.get("fii_change_1q"), lambda v: v >= cfg.min_fii_change),
        "dii_trend": _status(metrics.get("dii_change_1q"), lambda v: v >= cfg.min_dii_change),
    }

    failed, passed, unknown, exempt, evaluated = [], [], [], [], 0
    for rule in ALL_RULES:
        if rule in cfg.skip:
            continue
        if is_financial and rule in FINANCIAL_EXEMPT_RULES:
            exempt.append(rule)
            continue
        s = checks[rule]
        if s == "n/a":
            unknown.append(rule)
        else:
            evaluated += 1
            if s == "fail":
                failed.append(rule)
            else:
                passed.append(rule)

    if failed or (cfg.strict and unknown):
        status = "fail"
    elif evaluated == 0:
        status = "n/a"
    else:
        status = "pass"
    return {"status": status, "failed": failed, "passed": passed, "evaluated": evaluated,
            "unknown": unknown, "exempt": exempt,
            "industry_pe": ipe[0] if ipe else None, "industry_pe_src": ipe_src}
