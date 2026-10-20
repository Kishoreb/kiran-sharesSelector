"""
NSE public-site client: shareholding pattern (promoter %), promoter pledge data
and corporate announcements.

NSE's JSON endpoints only answer a browser-like session: first GET the home page
(to get cookies), then call /api/... with a Referer. Brotli encoding is disabled
(requests cannot decode it without an extra package).

IMPORTANT: the endpoint paths and JSON field names below are written from my
knowledge of the NSE website and could not be tested against the live site from
the sandbox. The parsers therefore look fields up by tolerant name matching, and
DEBUG_DIR (set via --debug-dump) saves every raw response so that a mismatch can
be fixed from the file. Every successful response is cached on disk.
"""

import json
import os
import re
import time
from datetime import date, datetime, timedelta

import requests

BASE = "https://www.nseindia.com"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "nse")
DEBUG_DIR = None
FORCE_REFRESH = False        # bypass the on-disk cache (set by --refresh-cache / --debug-dump)
MIN_DELAY = 1.0
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": BASE + "/",
}
ENDPOINTS = {
    "shareholding": "/api/corporate-share-holdings-master",
    "pledge": "/api/corporate-pledgedata",
    "announcements": "/api/corporate-announcements",
}
CACHE_TTL = {"shareholding": 7 * 86400, "pledge": 7 * 86400, "announcements": 86400}

_session = None
_last = [0.0]


def _sess():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
        _session.get(BASE + "/", timeout=15)          # cookies
    return _session


def _http_json(path, params):
    global _session
    for attempt in (1, 2):
        wait = MIN_DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = _sess().get(BASE + path, params=params, timeout=20)
        if r.status_code in (401, 403) and attempt == 1:
            _session = None                           # stale cookies: start a fresh session once
            continue
        r.raise_for_status()
        return r.json()


def _cache_file(kind, symbol, tag=""):
    return os.path.join(CACHE_DIR, f"{kind}_{symbol.strip().upper().replace('&', '_')}{tag}.json")


def fetch(kind: str, symbol: str, extra: dict = None, tag: str = "", with_symbol: bool = True):
    """Raw JSON for one endpoint/symbol, cached. Raises on failure. `tag` distinguishes query variants in the
    cache and dump file names; with_symbol=False asks for the endpoint's bulk list."""
    path = _cache_file(kind, symbol, tag)
    if not FORCE_REFRESH and os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL[kind]:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    params = {"index": "equities", **({"symbol": symbol.strip().upper()} if with_symbol else {}), **(extra or {})}
    js = _http_json(ENDPOINTS[kind], params)
    if DEBUG_DIR:                                     # always saved, even when the answer is empty
        os.makedirs(DEBUG_DIR, exist_ok=True)
        with open(os.path.join(DEBUG_DIR, f"nse_{kind}_{symbol.upper()}{tag}.json"), "w", encoding="utf-8") as f:
            json.dump(js, f, indent=1)
    if _rows(js):                                     # an empty answer is not cached: it may be a wrong query
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(js, f)
    return js


# ---------------------------------------------------------------- tolerant parsing
def _rows(js):
    if isinstance(js, list):
        return [d for d in js if isinstance(d, dict)]
    if isinstance(js, dict):
        for k in ("data", "Data", "result", "results"):
            if isinstance(js.get(k), list):
                return [d for d in js[k] if isinstance(d, dict)]
    return []


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def parse_date(s):
    s = str(s or "").strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S",
                "%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    m = re.match(r"(\d{1,2}-[A-Za-z]{3}-\d{4})", s)
    return parse_date(m.group(1)) if m and m.group(1) != s else None


def _key(d, *cands, avoid=()):
    low = {k.lower(): k for k in d}
    for c in cands:                                   # exact name first
        if c.lower() in low:
            return d[low[c.lower()]]
    for c in cands:                                   # then substring
        for lk, k in low.items():
            if c.lower() in lk and not any(a in lk for a in avoid):
                return d[k]
    return None


def parse_shareholding(js):
    """[{date, promoter, public}] newest first."""
    out = []
    for d in _rows(js):
        dt = parse_date(_key(d, "date", "asondate", "as_on_date", avoid=("submission", "broadcast")))
        prom = _num(_key(d, "pr_and_prgrp", "promoter_and_promoter_group", "promoter"))
        if dt and prom is not None:
            out.append({"date": dt, "promoter": prom, "public": _num(_key(d, "public_val", "public"))})
    return sorted(out, key=lambda x: x["date"], reverse=True)


def parse_pledge(js):
    """[{date, pledged_pct, field}] newest first. pledged_pct = % of PROMOTER shares pledged where the
    response lets us tell; `field` records which JSON key was used so it can be verified."""
    out = []
    for d in _rows(js):
        dt = parse_date(_key(d, "shp", "date", "asondate", "as_on_date", "dateofsubmission", avoid=("broadcast",)))
        nums = {k: _num(v) for k, v in d.items() if _num(v) is not None}
        # Real NSE records (checked against Wockhardt): percPromoterShares = pledged shares as % of promoter holding,
        # and `shp` is the shareholding-pattern date the record refers to (compBroadcastDate is NOT).
        pp = next((v for k, v in nums.items() if k.lower() == "percpromotershares"), None)
        if pp is not None:
            out.append({"date": dt, "pledged_pct": pp, "field": "percPromoterShares"})
            continue
        cands = {k: v for k, v in nums.items() if re.search(r"pledg|encum", k, re.I)}
        if not cands:
            cands = {k: v for k, v in nums.items() if re.search(r"perc|per_|pct", k, re.I)}
        if not cands:
            continue
        field = next((k for k in cands if re.search(r"prom", k, re.I)), None) or next(iter(cands))
        out.append({"date": dt, "pledged_pct": cands[field], "field": field})
    return sorted(out, key=lambda x: x["date"] or date.min, reverse=True)


def parse_announcements(js, days=90):
    """[{date, text, link}] newest first, limited to the last `days` days."""
    cutoff = date.today() - timedelta(days=days)
    out = []
    for d in _rows(js):
        dt = parse_date(_key(d, "an_dt", "sort_date", "date", "exchdisstime", avoid=("broadcast",)))
        if dt and dt < cutoff:
            continue
        parts = [str(_key(d, "desc", "subject") or ""), str(_key(d, "attchmnttext", "details", "body") or "")]
        text = ": ".join(p.strip() for p in parts if p and p.strip())
        if text:
            out.append({"date": dt, "text": text[:600], "link": _key(d, "attchmntfile", "attachment", "link")})
    return sorted(out, key=lambda x: x["date"] or date.min, reverse=True)


# ---------------------------------------------------------------- convenience
def shareholding(symbol):
    return parse_shareholding(fetch("shareholding", symbol))


# ---------------------------------------------------------------- XBRL shareholding filing (pledge)
# Each shareholding record links to the company's XBRL filing (BSE "SHP" taxonomy). Verified on a real filing
# (Wockhardt, Sep 2026): values are FRACTIONS (0.0997 = 9.97%); the context ShareholdingOfPromoterAndPromoterGroup_ContextI
# gives pledged shares as a share of the PROMOTER GROUP's holding (the number the pledging rule needs, matches screener.in),
# ShareholdingPattern_ContextI gives it as a share of ALL shares. A yes/no flag says whether any promoter shares are pledged.
XBRL_BASE = "https://nsearchives.nseindia.com/"
XBRL_TTL = 7 * 86400
_PLEDGE_FLAGS = ("WhetherAnySharesHeldByPromotersAreEncumberedUnderPledgedForPromoterAndPromoterGroup",
                 "WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged")
_PCT_TAG = "EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares"
_NUM_TAG = "NumberOfSharesEncumberedUnderPledged"
_CTX_PROMOTER = "ShareholdingOfPromoterAndPromoterGroup_ContextI"
_CTX_TOTAL = "ShareholdingPattern_ContextI"


def _xbrl_values(text, tag):
    """{contextRef: value text} for every <prefix:tag contextRef="...">value</...> (exact tag name only)."""
    rx = re.compile(r"<(?:[\w.-]+:)?" + tag + r"\s[^>]*?contextRef\s*=\s*[\"']([^\"']+)[\"'][^>]*>([^<]*)<")
    return {m.group(1): m.group(2).strip() for m in rx.finditer(text)}


def _fraction_to_pct(v):
    x = _num(v)
    return round(x * 100, 2) if x is not None and 0 <= x <= 1.0000001 else None


def parse_xbrl_pledge(text):
    """-> {flag, pledged_pct (of promoter holding), pledged_pct_total (of all shares), pledged_shares, note}.
    flag False and no figures -> 0.0 (the company declared no pledge). Figures absent otherwise -> None (n/a), never 0."""
    out = {"flag": None, "pledged_pct": None, "pledged_pct_total": None, "pledged_shares": None, "note": ""}
    for tag in _PLEDGE_FLAGS:
        vals = _xbrl_values(text, tag)
        v = next(iter(vals.values()), "").lower()
        if v in ("true", "false"):
            out["flag"] = (v == "true")
            break
    pct, num = _xbrl_values(text, _PCT_TAG), _xbrl_values(text, _NUM_TAG)
    out["pledged_pct"] = _fraction_to_pct(pct.get(_CTX_PROMOTER))
    out["pledged_pct_total"] = _fraction_to_pct(pct.get(_CTX_TOTAL))
    out["pledged_shares"] = _num(num.get(_CTX_PROMOTER))
    if out["pledged_pct"] is None:
        if out["flag"] is False:
            out.update(pledged_pct=0.0, pledged_pct_total=0.0, pledged_shares=0.0)
        else:
            out["note"] = "XBRL: promoter-group pledge figure not found" + (" although the filing says shares are pledged" if out["flag"] else "")
    elif out["flag"] is False and out["pledged_pct"] > 0:
        out["note"] = "XBRL: flag says no pledge but figures are non-zero (figures used)"
    elif out["flag"] and out["pledged_pct"] == 0:
        out["note"] = "XBRL: flag says pledged but figure is 0"
    return out


def _http_text(url):
    global _session
    for attempt in (1, 2):
        wait = MIN_DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = _sess().get(url, timeout=40)
        if r.status_code in (401, 403) and attempt == 1:
            _session = None
            continue
        r.raise_for_status()
        return r.content.decode("utf-8", errors="replace")


def xbrl_url(rec):
    u = str(rec.get("xbrl") or "").strip()
    if not u or u == "-":
        return None
    return u if u.startswith("http") else XBRL_BASE + u.lstrip("/")


def xbrl_pledge(symbol, back=0):
    """Pledge figures from the shareholding XBRL filing `back` quarters before the latest (0 = latest),
    cached 7 days, or None if there is no such record or it has no link.
    Raises if the download fails or is not XBRL. Result includes asof (the shareholding quarter) and url."""
    recs = [(parse_date(d.get("date")), d) for d in _rows(fetch("shareholding", symbol))]
    recs = sorted([(dt, d) for dt, d in recs if dt], key=lambda x: x[0], reverse=True)
    if len(recs) <= back:
        return None
    dt, rec = recs[back]
    url = xbrl_url(rec)
    if not url:
        return None
    suffix = "" if back == 0 else f"_prev{back}"
    path = _cache_file("xbrlpledge", symbol, suffix)
    if not FORCE_REFRESH and os.path.exists(path) and time.time() - os.path.getmtime(path) < XBRL_TTL:
        try:
            with open(path, encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("url") == url:
                return cached
        except Exception:
            pass
    text = _http_text(url)
    if "xbrl" not in text[:3000].lower():
        raise ValueError("XBRL link did not return an XBRL file (got: " + text[:60].replace("\n", " ") + ")")
    if DEBUG_DIR:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        with open(os.path.join(DEBUG_DIR, f"nse_xbrl_{symbol.upper()}{suffix}.xml"), "w", encoding="utf-8") as f:
            f.write(text)
    res = parse_xbrl_pledge(text)
    res.update(asof=str(dt), url=url)
    if res["pledged_pct"] is not None:                 # only complete answers are cached
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(res, f)
    return res


_bulk_pledge = None          # per-run memo of the bulk list (None = not fetched yet)


def _find_symbol(js, symbol):
    """Rows of a bulk answer that belong to `symbol` (matched on any key literally called symbol/sym)."""
    want = symbol.strip().upper()
    out = [d for d in _rows(js) if str(_key(d, "symbol", "sm_symbol", "sym") or "").strip().upper() == want]
    return out


def pledge(symbol):
    """Promoter pledge records, newest first. The plain query (symbol only) returned an empty answer for every
    symbol in a real run -- including Vedanta, whose promoter does pledge -- so if it is empty we also try the
    same query with a 2-year date range, then the bulk list for that range filtered by symbol."""
    global _bulk_pledge
    rows = parse_pledge(fetch("pledge", symbol))
    if rows:
        return rows
    today = date.today()
    rng = {"from_date": (today - timedelta(days=730)).strftime("%d-%m-%Y"), "to_date": today.strftime("%d-%m-%Y")}
    rows = parse_pledge(fetch("pledge", symbol, rng, tag="_v1"))
    if rows:
        return rows
    if _bulk_pledge is None:
        _bulk_pledge = fetch("pledge", "ALL", rng, tag="_bulk", with_symbol=False)
    return parse_pledge(_find_symbol(_bulk_pledge, symbol))


def announcements(symbol, days=90):
    return parse_announcements(fetch("announcements", symbol), days)
