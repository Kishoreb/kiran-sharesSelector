"""Offline tests for the 'all' NSE universe (no network):  python test_universe.py"""
import os, sys, tempfile
from datetime import date

import universe as u

TMP = tempfile.mkdtemp()
u.CACHE_DIR = os.path.join(TMP, ".cache")
EQUITY = ("SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
          "AAA,Alpha Industries Limited,EQ,01-JAN-2000,1,1,INE000A01010,1\n"
          "BBB,Beta Finance Limited,EQ,01-JAN-2000,1,1,INE000B01010,1\n"
          "CCC,Gamma Traders Limited,EQ,01-JAN-2000,1,1,INE000C01010,1\n"
          "DDD,Delta Illiquid Limited,EQ,01-JAN-2000,1,1,INE000D01010,1\n"
          "EEE,Epsilon Trade Only Limited,BE,01-JAN-2000,1,1,INE000E01010,1\n")
BHAV = ("SYMBOL, SERIES, DATE1, PREV_CLOSE, CLOSE_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES\n"
        "AAA, EQ, 23-Oct-2026, 100, 101, 1000, 5000.00, 10\n"       # Rs 50 Cr
        "BBB, EQ, 23-Oct-2026, 100, 101, 1000, 120.00, 10\n"        # Rs 1.2 Cr
        "CCC, EQ, 23-Oct-2026, 100, 101, 1000, 20.00, 10\n"         # Rs 0.2 Cr
        "DDD, EQ, 23-Oct-2026, 100, 101, 1000, -, 10\n"             # no number
        "EEE, BE, 23-Oct-2026, 100, 101, 1000, 9999.00, 10\n")       # wrong series


class R:
    def __init__(s, code, text=""): s.status_code, s.text = code, text
    def raise_for_status(s):
        if s.status_code != 200: raise RuntimeError(f"HTTP {s.status_code}")


calls = []
def fake_get(url, **kw):
    calls.append(url)
    if "EQUITY_L" in url: return R(200, EQUITY)
    if "sec_bhavdata_full_24102026" in url: return R(404)       # Saturday-style gap: no file
    if "sec_bhavdata_full_23102026" in url: return R(200, BHAV)
    if "nifty500" in url: return R(200, "Company Name,Industry,Symbol,Series,ISIN Code\nAlpha,Capital Goods,AAA,EQ,INE000A01010\n")
    return R(404)
u.requests.get = fake_get

assert [e["symbol"] for e in u.get_equity_list()] == ["AAA", "BBB", "CCC", "DDD"]       # BE series dropped
assert u.parse_bhavcopy(BHAV) == {"AAA": 50.0, "BBB": 1.2, "CCC": 0.2}                   # lakh -> crore, '-' and BE skipped
m, d = u.get_turnover_cr(today=date(2026, 10, 24))                                         # Saturday: weekend skipped, 23rd used
assert d == date(2026, 10, 23) and m["AAA"] == 50.0
n = len(calls); u.get_turnover_cr(today=date(2026, 10, 24)); assert len(calls) == n       # served from the day cache
print("equity list + bhavcopy parsing ok (series filter, lakh->crore, weekend walk-back, cache)")

u.date = type("D", (date,), {"today": staticmethod(lambda: date(2026, 10, 24))})
rows = u.get_all_constituents(min_turnover_cr=1.0)
assert [r["symbol"] for r in rows] == ["AAA", "BBB"], rows
ind = {r["symbol"]: r["industry"] for r in rows}
assert ind["AAA"] == "Capital Goods" and ind["BBB"] == "Financial Services (guessed)"
assert [r["symbol"] for r in u.get_all_constituents(min_turnover_cr=0)] == ["AAA", "BBB", "CCC", "DDD"]
u.ALL_MIN_TURNOVER_CR = 0.1
assert [s for s in u.get_index_symbols("all")] == ["AAA", "BBB", "CCC"]                    # via the normal entry point
print("filter ok: pre-filter by traded value, 0 keeps all, industry from Nifty 500 or guessed for lenders")

# bhavcopy unavailable -> clear error that names the way out; equity list offline -> stale cache still works
u.requests.get = lambda url, **kw: R(404) if "bhav" in url else fake_get(url)
for f in os.listdir(u.CACHE_DIR):
    if f.startswith("bhav_"): os.remove(os.path.join(u.CACHE_DIR, f))
try:
    u.get_all_constituents(min_turnover_cr=1.0); raise AssertionError("should fail loudly")
except RuntimeError as e:
    assert "universe-min-turnover-cr 0" in str(e)
def offline(url, **kw): raise RuntimeError("offline")
u.requests.get = offline
os.utime(os.path.join(u.CACHE_DIR, "equity_l.csv"), (0, 0))                                # make the cache stale
assert len(u.get_equity_list()) == 4
print("failure handling ok: missing bhavcopy fails loudly with the fix; offline uses the stale equity list")

# CLI wiring
import subprocess
out = subprocess.run([sys.executable, "screener.py", "screen", "-h"], capture_output=True, text=True).stdout
assert "--universe-min-turnover-cr" in out and "all" in out
print("CLI ok: --index all, --universe-min-turnover-cr")
print("\nAll universe checks passed.")
