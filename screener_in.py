"""
Fundamentals from screener.in (public company pages) -- up to 10 years of annual
statements, compounded 3/5/10-year sales & profit growth, ROE averages and the
quarterly shareholding table (promoters / FIIs / DIIs).

Why: Yahoo only returns ~4 annual periods, so no 5Y or 10Y CAGR is possible.

Design rules:
  * Parses the page with the standard library only (html.parser): no bs4/lxml needed.
  * Polite: one request per MIN_DELAY seconds, results cached on disk for 7 days.
  * Fails loudly: if the page layout is not what this parser expects (site redesign,
    login wall, blocked) it raises, and fundamentals.py falls back to Yahoo.
  * DEBUG_DIR: when set, every raw page is saved there so a layout change can be
    diagnosed from the file.

Terms of use: screener.in's terms do not grant a right to bulk automated access.
A few dozen holdings once a week is light, but it is your call -- keep MIN_DELAY
generous and do not point this at the whole of Nifty 500 repeatedly.
"""

import json
import os
import re
import time
from html.parser import HTMLParser

import requests

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "screener")
CACHE_MAX_AGE = 7 * 24 * 3600
MIN_DELAY = 1.5
DEBUG_DIR = None
FORCE_REFRESH = False        # bypass the on-disk cache (set by --refresh-cache / --debug-dump)
RAW_VERSION = 2              # bump when the parsed layout changes; older cache files are re-fetched
ALT_MIN_YEARS = 9            # fewer annual columns than this -> also read the standalone page
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}
_last_request = [0.0]


# ---------------------------------------------------------------- text helpers
def clean_label(s: str) -> str:
    s = (s or "").replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\s*\+$", "", s).strip()


def num(s):
    """'1,234.5' -> 1234.5, '12%' -> 12.0, '₹ 1,234 Cr.' -> 1234.0, '' / '--' -> None."""
    if s is None:
        return None
    t = str(s).replace("\xa0", " ").replace(",", "").replace("₹", "").replace("%", "")
    t = t.replace("Cr.", "").replace("\u2212", "-").strip()
    return float(t) if re.fullmatch(r"-?\d+(\.\d+)?", t) else None


# ---------------------------------------------------------------- HTML parsing
_PERIOD = re.compile(r"^(?:[A-Z][a-z]{2}\s+)?\d{4}$|^TTM$")


class _Page(HTMLParser):
    """Collects <table>s (with the id of their enclosing <section>) and the top-ratios list.
    Tables, rows and cells are kept on a stack, so a table NESTED inside a cell (tooltips, expandable rows)
    cannot swallow the outer table's remaining rows."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections, self.tables, self.stack = [], [], []
        self.in_top, self.li, self.cap, self.cap_depth = False, None, None, 0
        self.top = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "") or ""
        t = self.stack[-1] if self.stack else None
        if tag == "section":
            self.sections.append(a.get("id", ""))
        elif tag == "table":
            sec = next((s for s in reversed(self.sections) if s), "")
            self.stack.append({"section": sec, "cls": cls, "head": None, "rows": [], "all": [],
                               "row": None, "has_th": False, "cell": None})
        elif tag == "tr" and t is not None:
            t["row"], t["has_th"] = [], False
        elif tag in ("td", "th") and t is not None and t["row"] is not None:
            t["cell"] = ""
            t["has_th"] = t["has_th"] or tag == "th"
        elif tag == "ul" and a.get("id") == "top-ratios":
            self.in_top = True
        elif tag == "li" and self.in_top:
            self.li = {}
        elif tag == "span" and self.li is not None:
            if self.cap:
                self.cap_depth += 1
            elif "name" in cls.split():
                self.cap, self.cap_depth, self.li["name"] = "name", 0, ""
            elif "value" in cls.split():
                self.cap, self.cap_depth, self.li["value"] = "value", 0, ""

    def handle_endtag(self, tag):
        t = self.stack[-1] if self.stack else None
        if tag == "section" and self.sections:
            self.sections.pop()
        elif tag in ("td", "th") and t is not None and t["cell"] is not None and t["row"] is not None:
            t["row"].append(t["cell"])
            t["cell"] = None
        elif tag == "tr" and t is not None and t["row"] is not None:
            if t["row"]:
                t["all"].append(t["row"])
                if t["has_th"] and t["head"] is None:
                    t["head"] = t["row"]
                else:
                    t["rows"].append(t["row"])
            t["row"] = None
        elif tag == "table" and t is not None:
            self.tables.append(self.stack.pop())
        elif tag == "ul" and self.in_top:
            self.in_top = False
        elif tag == "li" and self.li is not None:
            if "name" in self.li:
                self.top.append((clean_label(self.li["name"]), clean_label(self.li.get("value", ""))))
            self.li = None
        elif tag == "span" and self.cap:
            if self.cap_depth:
                self.cap_depth -= 1
            else:
                self.cap = None

    def handle_data(self, data):
        if self.stack and self.stack[-1]["cell"] is not None:
            self.stack[-1]["cell"] += data
        if self.cap and self.li is not None:
            self.li[self.cap] += data


def _header_and_body(t):
    """(header cells, body rows). The header is the <th> row when it is wide; otherwise the first row whose
    cells look like periods ('Mar 2015', 'TTM') even if the page marked them as <td>."""
    head = t["head"] or []
    if len(head) > 2:
        return head, t["rows"]
    for i, row in enumerate(t["all"][:3]):
        if sum(1 for c in row[1:] if _PERIOD.match(clean_label(c))) >= 3:
            return row, [r for j, r in enumerate(t["all"]) if j != i]
    return head, t["rows"]


def tables_in_section(html: str, section: str):
    """Diagnostics: the tables the parser sees inside one <section id=...>."""
    p = _Page()
    p.feed(html)
    return [t for t in p.tables if t["section"] == section]


_LABEL_RULES = {                       # fallback when a table is not inside the expected <section>
    "pl": lambda L: "net profit" in L and ("sales" in L or "revenue" in L),
    "bs": lambda L: "reserves" in L and ("borrowings" in L or "deposits" in L),
    "ratios": lambda L: "roce %" in L or "debtor days" in L,
    "holding": lambda L: "promoters" in L and "public" in L,
}


def parse_page(html: str) -> dict:
    p = _Page()
    p.feed(html)
    raw = {"top": {k: v for k, v in p.top}, "ranges": {}, "pl": None, "bs": None, "ratios": None, "holding": None}

    def grid(head, body):
        cols = [clean_label(c) for c in head[1:]]
        rows = {}
        for r in body:
            if len(r) < 2:
                continue
            vals = [num(c) for c in r[1:]]
            vals += [None] * (len(cols) - len(vals))
            rows[clean_label(r[0]).lower()] = vals[:len(cols)]
        return {"cols": cols, "rows": rows}

    wide = []                                              # (table, grid)
    for t in p.tables:
        head, body = _header_and_body(t)
        if len(head) == 1:                                 # e.g. "Compounded Sales Growth"
            title = clean_label(head[0]).lower()
            if title:
                raw["ranges"][title] = {clean_label(r[0]).rstrip(":").lower(): num(r[1])
                                        for r in body if len(r) >= 2}
        elif len(head) > 2 and sum(1 for c in head[1:] if _PERIOD.match(clean_label(c))) >= 2:
            # only tables whose columns are periods ("Mar 2015", "TTM") are statements; this also skips tables
            # nested inside a cell, which complete before their parent and would otherwise be taken for it
            g = grid(head, body)
            wide.append((t, g))
            key = {"profit-loss": "pl", "balance-sheet": "bs", "ratios": "ratios",
                   "shareholding": "holding"}.get(t["section"])
            if key and raw[key] is None:                   # first table per section = annual / quarterly
                raw[key] = g
    for key, rule in _LABEL_RULES.items():                 # fallback by row labels, never from quarters/peers
        if raw[key] is None:
            for t, g in wide:
                if t["section"] not in ("quarters", "peers") and rule(set(g["rows"])):
                    raw[key] = g
                    break
    return raw


def annual_only(g):
    """Drop the TTM column from a grid."""
    if not g:
        return g
    keep = [i for i, c in enumerate(g["cols"]) if c.upper() != "TTM"]
    return {"cols": [g["cols"][i] for i in keep],
            "rows": {k: [v[i] for i in keep] for k, v in g["rows"].items()}}


# ---------------------------------------------------------------- fetching
def _cache_path(symbol):
    return os.path.join(CACHE_DIR, f"{symbol.strip().upper().replace('/', '_')}.json")


def _http_get(url):
    wait = MIN_DELAY - (time.time() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    _last_request[0] = time.time()
    return requests.get(url, headers=HEADERS, timeout=20)


def _get_with_retry(url, tries=3):
    last = None
    for k in range(tries):
        try:
            return _http_get(url)
        except requests.RequestException as e:          # DNS blips, resets, timeouts
            last = e
            time.sleep(2 * (k + 1))
    raise RuntimeError(f"network error: {type(last).__name__}: {str(last)[:100]}")


def fetch_html(symbol: str, kinds=("consolidated/", "")) -> str:
    from urllib.parse import quote
    sym = quote(symbol.strip().upper(), safe="")
    last = None
    for kind in kinds:
        r = _get_with_retry(f"https://www.screener.in/company/{sym}/{kind}")
        last = r
        if r.status_code == 200:
            if DEBUG_DIR:
                os.makedirs(DEBUG_DIR, exist_ok=True)
                tag = "consolidated" if kind else "standalone"
                with open(os.path.join(DEBUG_DIR, f"screener_{symbol.upper()}_{tag}.html"), "w", encoding="utf-8") as f:
                    f.write(r.text)
            return r.text
        if r.status_code == 429:
            raise RuntimeError("HTTP 429 (rate limited) - raise screener_in.MIN_DELAY or wait")
        if r.status_code not in (404, 302):
            break
    raise RuntimeError(f"HTTP {last.status_code} for {symbol}")


def get_raw(symbol: str, refresh: bool = False) -> dict:
    """Parsed page for one symbol (cached 7 days). Raises if the layout is not recognised."""
    path = _cache_path(symbol)
    if not (refresh or FORCE_REFRESH) and os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_MAX_AGE:
        try:
            with open(path, encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("_v") == RAW_VERSION:
                return cached
        except Exception:
            pass
    raw = parse_page(fetch_html(symbol))
    if not raw["pl"] or not raw["pl"]["rows"]:
        # Companies without consolidated statements (no subsidiaries) can answer /consolidated/ with an empty page.
        try:
            raw2 = parse_page(fetch_html(symbol, kinds=("",)))
            if raw2["pl"] and raw2["pl"]["rows"]:
                raw, raw["_basis"] = raw2, "standalone"
        except Exception:
            pass
    if not raw["pl"] or not raw["pl"]["rows"]:
        raise RuntimeError("profit & loss table not found - page layout changed, or a login/blocked page "
                           "(use --debug-dump to save the page)")
    # The consolidated page can have only a few years (consolidation started recently). If so, also read the
    # standalone page and keep it as `alt`, used ONLY to fill growth horizons the primary page cannot give.
    n_ann = len(annual_only(raw["pl"])["cols"])
    if n_ann < ALT_MIN_YEARS and raw.get("_basis") != "standalone":
        try:
            alt = parse_page(fetch_html(symbol, kinds=("",)))
            if alt["pl"] and len(annual_only(alt["pl"])["cols"]) > n_ann:
                raw["alt"] = {"pl": alt["pl"], "ranges": alt["ranges"]}
        except Exception:
            pass
    raw["_v"] = RAW_VERSION
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    return raw


# ---------------------------------------------------------------- metrics
def _row(grid, *names):
    if not grid:
        return None
    for n in names:
        if n in grid["rows"]:
            return grid["rows"][n]
    for n in names:
        for k, v in grid["rows"].items():
            if k.startswith(n):
                return v
    return None


def _last(vals):
    for v in reversed(vals or []):
        if v is not None:
            return v
    return None


def cagr(vals, years):
    pts = [v for v in (vals or []) if v is not None]
    if len(pts) < years + 1:
        return None
    last, base = pts[-1], pts[-1 - years]
    return ((last / base) ** (1 / years) - 1) * 100 if last > 0 and base > 0 else None


def pick_growth(metrics: dict, years: int):
    """Set sales_growth / pat_growth (+ basis, peg) from the stored 3/5/10-year CAGRs,
    using `years` if available, else the next shorter horizon."""
    chain = [y for y in (10, 5, 3) if y <= years] or [3]
    for key, short in (("sales_growth", "sales"), ("pat_growth", "pat")):
        metrics[key], metrics[key + "_basis"] = None, None
        for y in chain:
            v = metrics.get(f"{short}_cagr_{y}y")
            if v is not None:
                metrics[key], metrics[key + "_basis"] = v, f"{y}Y CAGR"
                break
    pe, g = metrics.get("pe"), metrics.get("pat_growth")
    metrics["peg"] = pe / g if pe and pe > 0 and g and g > 0 else None
    return metrics


def metrics_from_raw(raw: dict, growth_years: int = 5) -> dict:
    pl, bs, ratios = annual_only(raw["pl"]), annual_only(raw.get("bs")), annual_only(raw.get("ratios"))
    rng, top = raw.get("ranges", {}), raw.get("top", {})
    out = {k: None for k in ("roce", "roe_avg", "roe_years", "de", "icr", "sales_growth", "sales_growth_basis",
                             "pat_growth", "pat_growth_basis", "pe", "peg", "market_cap_cr")}
    out["source"] = "screener.in"
    out["statements"] = raw.get("_basis", "consolidated")
    out["history_years"] = len(pl["cols"]) if pl else 0

    sales = _row(pl, "sales", "revenue")
    profit = _row(pl, "net profit")
    pbt = _row(pl, "profit before tax")
    interest = _row(pl, "interest")

    # growth: the site's own compounded blocks first, our own CAGR from the series as fallback
    for short, block, series in (("sales", "compounded sales growth", sales), ("pat", "compounded profit growth", profit)):
        for y in (3, 5, 10):
            v = (rng.get(block) or {}).get(f"{y} years")
            out[f"{short}_cagr_{y}y"] = v if v is not None else cagr(series, y)

    # fill growth horizons the primary page cannot give from the standalone statements (longer history)
    used = []
    alt = raw.get("alt")
    if alt:
        apl = annual_only(alt["pl"])
        for short, block, series in (("sales", "compounded sales growth", _row(apl, "sales", "revenue")),
                                     ("pat", "compounded profit growth", _row(apl, "net profit"))):
            for y in (3, 5, 10):
                if out[f"{short}_cagr_{y}y"] is None:
                    v = (alt.get("ranges", {}).get(block) or {}).get(f"{y} years")
                    v = v if v is not None else cagr(series, y)
                    if v is not None:
                        out[f"{short}_cagr_{y}y"] = v
                        used.append(f"{short}_{y}y")
    out["growth_from_standalone"] = ", ".join(used) or None

    # ROCE (latest annual) and ROE (5-year average)
    out["roce"] = _last(_row(ratios, "roce %", "roce")) if ratios else None
    if out["roce"] is None:
        out["roce"] = num(top.get("ROCE"))
    roe5 = (rng.get("return on equity") or {}).get("5 years")
    if roe5 is not None:
        out["roe_avg"], out["roe_years"] = roe5, 5
    elif bs and profit:
        eq, res = _row(bs, "equity capital"), _row(bs, "reserves")
        if eq and res:
            vals = [p / (e + r) * 100 for p, e, r in zip(profit, eq, res)
                    if None not in (p, e, r) and (e + r) > 0][-5:]
            if vals:
                out["roe_avg"], out["roe_years"] = sum(vals) / len(vals), len(vals)

    # debt / equity (latest year)
    if bs:
        eq, res, debt = _row(bs, "equity capital"), _row(bs, "reserves"), _row(bs, "borrowings")
        e, r_, d = _last(eq), _last(res), _last(debt)
        if None not in (e, r_, d) and (e + r_) > 0:
            out["de"] = d / (e + r_)

    # interest coverage = (PBT + interest) / interest; no interest cost = infinite
    pb, it = _last(pbt), _last(interest)
    if pb is not None and it is not None:
        out["icr"] = float("inf") if it == 0 else (pb + it) / it

    out["pe"] = num(top.get("Stock P/E"))
    out["market_cap_cr"] = num(top.get("Market Cap"))
    out["pledged_pct_screener"] = num(top.get("Pledged percentage"))
    pick_growth(out, growth_years)

    # shareholding history, oldest -> newest
    h = raw.get("holding")
    if h:
        for key, label in (("promoters", "promoters"), ("fiis", "fiis"), ("diis", "diis")):
            r = _row(h, label)
            out[f"hold_{key}"] = [[c, v] for c, v in zip(h["cols"], r or []) if v is not None]
    return out
