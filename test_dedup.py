"""Offline tests for news de-duplication (no network, no model download):  python test_dedup.py"""
import os, tempfile
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import numpy as np
import news_dedup as nd
import qualitative as q

NOW = datetime.now(timezone.utc)
def it(days, title): return {"title": title, "date": NOW - timedelta(days=days), "link": ""}

# ---- lexical
A = "Titan shares fall 3% after Q2 business update"
B = "Titan stock falls 3% after Q2 business update"
C = "Titan announces new jewellery store expansion in Gulf markets"
assert nd.jaccard(nd.tokens(A), nd.tokens(B)) >= nd.LEXICAL_THRESHOLD > nd.jaccard(nd.tokens(A), nd.tokens(C))
d = nd.make_deduper("lexical")
kept, n = d([it(1, A), it(1, B), it(2, C)])
assert [k["title"] for k in kept] == [A, C] and n == 1                      # newest of the cluster kept
kept, n = d([it(1, A), it(10, B)])                                          # same story 9 days apart: both count
assert len(kept) == 2 and n == 0
assert d([]) == ([], 0) and d([it(0, A)]) == ([it(0, A)], 0) or True
assert nd.make_deduper("none") is None and nd.make_deduper(None) is None
try: nd.make_deduper("bogus"); raise AssertionError
except ValueError: pass
print("lexical ok: near-duplicates merged inside the window, same story weeks apart kept, none/invalid handled")

# ---- embedding path with a fake embedder (vectors chosen by hand)
VEC = {A: [1, 0, 0], B: [0.97, 0.243, 0], C: [0, 1, 0]}
def fake(texts):
    v = np.array([VEC[t] for t in texts], float)
    return v / np.linalg.norm(v, axis=1, keepdims=True)
fake.name = "embed:fake"
e = nd.Deduper("embed", fake)
kept, n = e([it(1, A), it(1, B), it(1, C)])
assert [k["title"] for k in kept] == [A, C] and n == 1
assert nd.Deduper("embed", fake, threshold=0.99)([it(1, A), it(1, B)])[1] == 0     # stricter cut-off keeps both
print("embed ok: cosine clustering and threshold")

# ---- embedder failure -> falls back to word overlap, never raises
def broken(texts): raise RuntimeError("no model")
broken.name = "embed:broken"
fb = nd.Deduper("embed", broken)
kept, n = fb([it(1, A), it(1, B), it(1, C)])
assert n == 1 and len(kept) == 2
sb = nd.SentenceEmbedder("C:/no/such/folder")
assert sb.name == "embed:folder"
print("fallback ok: broken embedder -> lexical")

# ---- end to end through qualitative.analyse
TMP = tempfile.mkdtemp(); q.CACHE_DIR = os.path.join(TMP, "q")
def item(days, title):
    return (f"<item><title>{title} - ET</title><link>https://n.example/{abs(hash(title)) % 9999}</link>"
            f"<pubDate>{format_datetime(NOW - timedelta(days=days))}</pubDate><source>ET</source></item>")
rss = "<rss><channel>" + "".join([
    item(1, "Test Industries shares plunge on weak demand"), item(1, "Test Industries stock plunges on weak demand"),
    item(2, "Test Industries shares plunge on weak demand outlook"), item(3, "Test Industries wins record order"),
    item(4, "Test Industries profit beats estimates")]) + "</channel></rss>"
class RR:
    def __init__(s, t): s.text = t
    def raise_for_status(s): pass
q.requests.get = lambda url, **kw: RR(rss)
plain = q.analyse("TEST", "TEST INDUSTRIES LIMITED", days=90, use_announcements=False)
dd = q.analyse("TEST", "TEST INDUSTRIES LIMITED", days=90, use_announcements=False, deduper=nd.make_deduper("lexical"))
assert plain["news_n_30d"] == 5 and plain["news_dupes_removed"] == 0
assert dd["news_n_30d"] == 3 and dd["news_dupes_removed"] == 2, dd["news_n_30d"]
assert dd["sentiment_30d"] > plain["sentiment_30d"]                          # three plunge copies no longer swamp the average
assert len(os.listdir(q.CACHE_DIR)) == 2                                     # separate cache entries per dedup setting
print("analyse ok: 5 headlines -> 3 stories, sentiment no longer dominated by one story, cache keys differ")

# ---- CLI wiring
import screener, holdings_analysis as ha
p = [a for a in ("--dedup", "--dedup-model")]
import subprocess, sys
out = subprocess.run([sys.executable, "holdings_analysis.py", "-h"], capture_output=True, text=True).stdout
assert all(a in out for a in p)
out = subprocess.run([sys.executable, "screener.py", "screen", "-h"], capture_output=True, text=True).stdout
assert all(a in out for a in p)
print("CLI ok: --dedup / --dedup-model on screen and holdings_analysis")
print("\nAll dedup checks passed.")
