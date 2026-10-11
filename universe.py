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
