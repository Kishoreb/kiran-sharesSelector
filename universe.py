"""
Fetches official NSE index constituent lists directly from NSE's public
archives, so the screener always uses a current, accurate universe instead
of a hardcoded list that goes stale.

NSE sometimes rejects requests that don't look like they're coming from a
browser, so a User-Agent header is set. If a fetch fails (network issue,
NSE blocking the request, URL changed), it falls back to a locally cached
copy from the last successful fetch, or the small built-in NIFTY 50 list
as a last resort.
"""

import csv
import io
import os
import re
import time
from datetime import date, datetime

import requests

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
CACHE_MAX_AGE_SECONDS = 24 * 60 * 60  # 1 day

INDEX_URLS = {
    "nifty50": "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "niftynext50": "https://archives.nseindia.com/content/indices/ind_niftynext50list.csv",
    "nifty100": "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
    "nifty200": "https://archives.nseindia.com/content/indices/ind_nifty200list.csv",
    "nifty500": "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,*/*",
}


def _cache_path(index_name: str) -> str:
    return os.path.join(CACHE_DIR, f"{index_name}.csv")


def _read_cache(index_name: str):
    path = _cache_path(index_name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write_cache(index_name: str, text: str):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_cache_path(index_name), "w", encoding="utf-8") as f:
        f.write(text)


def _snapshot_dir() -> str:
    return os.path.join(CACHE_DIR, "snapshots")


def _write_snapshot(index_name: str, text: str):
    """Keep one dated copy per day (never overwritten by later days) so index changes can be diffed later."""
    os.makedirs(_snapshot_dir(), exist_ok=True)
    path = os.path.join(_snapshot_dir(), f"{index_name}_{date.today().isoformat()}.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def list_snapshots(index_name: str):
    """[(date, path)] oldest first."""
    out = []
    folder = _snapshot_dir()
    if not os.path.isdir(folder):
        return out
    prefix = f"{index_name}_"
    for name in os.listdir(folder):
        if name.startswith(prefix) and name.endswith(".csv"):
            try:
                d = datetime.strptime(name[len(prefix):-4], "%Y-%m-%d").date()
            except ValueError:
                continue
            out.append((d, os.path.join(folder, name)))
    return sorted(out)


def changes_from_snapshots(index_name: str):
    """
    Diff consecutive dated snapshots -> [(date, symbol, 'ADD'|'REMOVE')].
    The date is when the change was first SEEN in a snapshot, which is on or
    after the true effective date (the more often you download, the closer it is).
    """
    snaps = list_snapshots(index_name)
    out = []
    for (_, pa), (db, pb) in zip(snaps, snaps[1:]):
        with open(pa, encoding="utf-8") as fa, open(pb, encoding="utf-8") as fb:
            sa, sb = set(_parse_symbols(fa.read())), set(_parse_symbols(fb.read()))
        out += [(db, s.upper(), "ADD") for s in sorted(sb - sa)]
        out += [(db, s.upper(), "REMOVE") for s in sorted(sa - sb)]
    return out


def _cache_is_fresh(index_name: str) -> bool:
    path = _cache_path(index_name)
    if not os.path.exists(path):
        return False
    return (time.time() - os.path.getmtime(path)) < CACHE_MAX_AGE_SECONDS


def _parse_constituents(csv_text: str):
    """Returns list of {'symbol': ..., 'industry': ...} dicts."""
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []
    for row in reader:
        symbol, industry = None, None
        for key, val in row.items():
            if not key:
                continue
            k = key.strip().lower()
            if k == "symbol" and val.strip():
                symbol = val.strip()
            elif k == "industry" and val.strip():
                industry = val.strip()
        if symbol:
            rows.append({"symbol": symbol, "industry": industry or "Unknown"})
    return rows


def _parse_symbols(csv_text: str):
    return [row["symbol"] for row in _parse_constituents(csv_text)]


def get_index_constituents(index_name: str, refresh: bool = False, use_cache_on_failure: bool = True):
    """
    Returns a list of {'symbol': ..., 'industry': ...} for the given index.
    Same fetch/cache/fallback behaviour as get_index_symbols.
    """
    index_name = index_name.lower()
    if index_name == ALL_INDEX:
        return get_all_constituents(refresh)
    if index_name not in INDEX_URLS:
        raise ValueError(f"Unknown index '{index_name}'. Choose from: {list(INDEX_URLS)}")

    if not refresh and _cache_is_fresh(index_name):
        cached = _read_cache(index_name)
        if cached:
            return _parse_constituents(cached)

    try:
        resp = requests.get(INDEX_URLS[index_name], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        text = resp.text
        rows = _parse_constituents(text)
        if not rows:
            raise ValueError("fetched CSV but found no symbols in it (format may have changed)")
        _write_cache(index_name, text)
        _write_snapshot(index_name, text)
        return rows
    except Exception as e:
        if use_cache_on_failure:
            cached = _read_cache(index_name)
            if cached:
                print(f"  [warning] live fetch of {index_name} failed ({e}); using last cached copy")
                return _parse_constituents(cached)
        raise RuntimeError(
            f"Could not fetch '{index_name}' from NSE ({e}), and no cached copy exists. "
            f"Check your internet connection, or pass --symbols / --file instead."
        )


def get_index_symbols(index_name: str, refresh: bool = False, use_cache_on_failure: bool = True):
    """
    Returns a list of NSE symbols for the given index (one of INDEX_URLS keys).
    Fetches live from NSE unless a fresh cache exists and refresh=False.
    Falls back to the last successful cache if the live fetch fails.
    """
    return [row["symbol"] for row in get_index_constituents(index_name, refresh, use_cache_on_failure)]


# ---------------------------------------------------------------- the whole NSE market ("all")
ALL_INDEX = "all"
ALL_MIN_TURNOVER_CR = 0.5        # pre-filter: last-day traded value in Rs crore (0 = keep every EQ-series stock); set by screener.py
EQUITY_LIST_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
BHAV_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
_FIN_NAME_RE = re.compile(r"FINANCE|FINANCIAL|BANK|HOUSING FIN|ASSET MANAGEMENT|AMC", re.I)


def _norm_row(row):
    return {(k or "").strip().upper(): (v or "").strip() for k, v in row.items()}


def get_equity_list(refresh: bool = False):
    """[{'symbol','name'}] for every EQ-series stock in NSE's official list (cached 7 days; stale cache if offline)."""
    path = os.path.join(CACHE_DIR, "equity_l.csv")
    text = None
    if not refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) < 7 * 86400:
        text = open(path, encoding="utf-8").read()
    else:
        try:
            r = requests.get(EQUITY_LIST_URL, headers=HEADERS, timeout=20)
            r.raise_for_status()
            text = r.text
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            if os.path.exists(path):
                print(f"  [warning] live fetch of the NSE equity list failed ({e}); using the last cached copy")
                text = open(path, encoding="utf-8").read()
            else:
                raise RuntimeError(f"Could not fetch NSE's equity list ({e}) and no cached copy exists.")
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        row = _norm_row(row)
        if row.get("SYMBOL") and row.get("SERIES", "EQ").upper() == "EQ":
            out.append({"symbol": row["SYMBOL"].upper(), "name": row.get("NAME OF COMPANY", "")})
    if not out:
        raise RuntimeError("NSE equity list had no EQ-series rows (format may have changed)")
    return out


def parse_bhavcopy(text: str) -> dict:
    """{symbol: traded value in Rs crore} for EQ-series rows of NSE's sec_bhavdata_full file (TURNOVER_LACS / 100)."""
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        row = _norm_row(row)
        if row.get("SERIES", "").upper() != "EQ" or not row.get("SYMBOL"):
            continue
        key = next((k for k in row if "TURNOVER" in k), None)
        try:
            out[row["SYMBOL"].upper()] = float(row[key].replace(",", "")) / 100.0
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    return out


def get_turnover_cr(refresh: bool = False, max_back: int = 7, today: date = None):
    """(turnover map, bhavcopy date) from the latest NSE bhavcopy that exists, walking back over weekends and
    holidays (each day's file is cached). Raises RuntimeError if none of the last `max_back` days is available."""
    from datetime import timedelta
    today = today or date.today()
    last = None
    for k in range(max_back + 1):
        d = today - timedelta(days=k)
        if d.weekday() >= 5:
            continue
        path = os.path.join(CACHE_DIR, f"bhav_{d:%Y%m%d}.csv")
        text = None
        if not refresh and os.path.exists(path):
            text = open(path, encoding="utf-8").read()
        else:
            try:
                r = requests.get(BHAV_URL.format(d=f"{d:%d%m%Y}"), headers=HEADERS, timeout=30)
                if r.status_code == 200 and "SYMBOL" in r.text[:500].upper():
                    text = r.text
                    os.makedirs(CACHE_DIR, exist_ok=True)
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(text)
                else:
                    last = f"HTTP {r.status_code} for {d}"
            except Exception as e:
                last = str(e)
        if text:
            m = parse_bhavcopy(text)
            if m:
                return m, d
            last = f"bhavcopy for {d} had no usable rows"
    raise RuntimeError(f"No NSE bhavcopy found for the last {max_back} days ({last}). "
                       f"Pass --universe-min-turnover-cr 0 to skip the liquidity pre-filter.")


def get_all_constituents(refresh: bool = False, min_turnover_cr: float = None):
    """Every EQ-series NSE stock whose last-day traded value is at least `min_turnover_cr` (a cheap pre-filter so you
    do not download price history for thousands of dead stocks; the strategy's own 20-day liquidity filter still applies).
    Industry comes from the Nifty 500 list where the stock is in it; otherwise 'Unknown', or
    'Financial Services (guessed)' when the company name looks like a lender (so bank-style rule exemptions apply)."""
    cr = ALL_MIN_TURNOVER_CR if min_turnover_cr is None else min_turnover_cr
    eq = get_equity_list(refresh)
    kept = eq
    if cr > 0:
        turn, d = get_turnover_cr(refresh)
        kept = [e for e in eq if turn.get(e["symbol"], 0.0) >= cr]
        print(f"  Universe 'all': {len(eq)} EQ-series stocks, {len(kept)} with traded value >= Rs {cr} Cr on {d}.")
    else:
        print(f"  Universe 'all': {len(eq)} EQ-series stocks (no liquidity pre-filter).")
    try:
        ind = {c["symbol"].upper(): c["industry"] for c in get_index_constituents("nifty500", refresh)}
    except Exception:
        ind = {}
    return [{"symbol": e["symbol"],
             "industry": ind.get(e["symbol"]) or ("Financial Services (guessed)" if _FIN_NAME_RE.search(e["name"]) else "Unknown")}
            for e in kept]
