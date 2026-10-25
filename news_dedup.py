#!/usr/bin/env python3
"""
News de-duplication (shortlisting doc, section 4).

Google News returns the same story many times (syndicated copies, 'X shares fall' / 'X stock falls' from
different outlets). Counted separately they inflate `news_n_30d` and drag the sentiment average towards
one story. This module keeps ONE headline per cluster of near-duplicates before sentiment is scored.

Methods (--dedup):
  none     no de-duplication (default, old behaviour)
  lexical  word-set Jaccard similarity, no extra packages
  embed    cosine similarity of small local sentence embeddings (default model
           sentence-transformers/all-MiniLM-L6-v2, ~90 MB, loaded through `transformers`; needs torch).
           If the model cannot be loaded it falls back to lexical with a warning.

Rules: items are processed newest first; an item is dropped if it is similar enough to an already-kept item
published within `window_days` (default 3), so a story that genuinely re-appears weeks later still counts.
Only duplicates are removed: nothing is rewritten, and the kept headline is the newest of its cluster.

    python news_dedup.py "Titan shares fall 3% after Q2 update" "Titan stock falls 3% post Q2 business update"
"""

import re
import sys

LEXICAL_THRESHOLD = 0.6
EMBED_THRESHOLD = 0.85
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_STOP = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "as", "after", "by", "with", "is", "are",
         "its", "it", "from", "over", "amid", "says", "said", "may", "will", "stock", "stocks", "share", "shares"}
_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STEM = re.compile(r"(ing|ed|es|s)$")


def tokens(text):
    """Lowercase content words, light stemming (falls/fell are NOT merged: kept simple and predictable)."""
    out = set()
    for w in _WORD.findall((text or "").lower()):
        if w in _STOP:
            continue
        out.add(_STEM.sub("", w) if len(w) > 4 else w)
    return out


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class SentenceEmbedder:
    """Mean-pooled, L2-normalised sentence embeddings via transformers. Loaded lazily; .error is set on failure."""

    def __init__(self, model=None, batch=32, max_len=64):
        self.model_id = model or DEFAULT_MODEL
        self.batch, self.max_len = batch, max_len
        self.name = "embed:" + (self.model_id.rstrip("/\\").replace("\\", "/").split("/")[-1] or self.model_id)
        self.error, self._ready = None, False

    def _load(self):
        if self._ready:
            return
        import torch
        from transformers import AutoModel, AutoTokenizer
        self._torch = torch
        self._tok = AutoTokenizer.from_pretrained(self.model_id)
        self._mdl = AutoModel.from_pretrained(self.model_id).eval()
        self._ready = True

    def __call__(self, texts):
        import numpy as np
        self._load()
        out = []
        with self._torch.no_grad():
            for i in range(0, len(texts), self.batch):
                enc = self._tok(list(texts[i:i + self.batch]), padding=True, truncation=True,
                                max_length=self.max_len, return_tensors="pt")
                h = self._mdl(**enc).last_hidden_state
                m = enc["attention_mask"].unsqueeze(-1).float()
                v = (h * m).sum(1) / m.sum(1).clamp(min=1)
                out.append(self._torch.nn.functional.normalize(v, dim=1).numpy())
        return np.vstack(out) if out else np.zeros((0, 1))


class Deduper:
    """Callable: items -> (kept_items, n_removed). `items` are dicts with 'title' and a 'date' (datetime/date),
    newest first. embedder: any callable list[str] -> array of L2-normalised vectors (None = lexical)."""

    def __init__(self, method="lexical", embedder=None, threshold=None, window_days=3):
        if method not in ("lexical", "embed"):
            raise ValueError("dedup method must be 'lexical' or 'embed'")
        self.method, self.embedder, self.window_days = method, embedder, window_days
        self.threshold = threshold if threshold is not None else (EMBED_THRESHOLD if method == "embed" else LEXICAL_THRESHOLD)
        self._warned = False

    @property
    def name(self):
        emb = getattr(self.embedder, "name", "embed") if self.method == "embed" else "lexical"
        return f"dedup:{emb}:{self.threshold}:{self.window_days}d"

    def _vectors(self, titles):
        if self.method != "embed" or self.embedder is None:
            return None
        try:
            return self.embedder(titles)
        except Exception as e:
            if not self._warned:
                self._warned = True
                if hasattr(self.embedder, "error"):
                    self.embedder.error = f"{type(e).__name__}: {e}"[:200]
                print(f"  [warning] sentence embedder unavailable ({type(e).__name__}: {str(e)[:100]}); "
                      f"de-duplicating with word overlap instead")
            return None

    def __call__(self, items):
        if len(items) < 2:
            return list(items), 0
        titles = [it.get("title") or it.get("text") or "" for it in items]
        vecs = self._vectors(titles)
        thr = self.threshold if vecs is not None else LEXICAL_THRESHOLD
        toks = [tokens(t) for t in titles]
        kept_idx = []
        for i, it in enumerate(items):
            dup = False
            for j in kept_idx:
                if self.window_days is not None and not _within(items[i], items[j], self.window_days):
                    continue
                sim = float(vecs[i] @ vecs[j]) if vecs is not None else jaccard(toks[i], toks[j])
                if sim >= thr:
                    dup = True
                    break
            if not dup:
                kept_idx.append(i)
        return [items[i] for i in kept_idx], len(items) - len(kept_idx)


def _within(a, b, days):
    da, db = a.get("date"), b.get("date")
    try:
        return abs((da - db).total_seconds()) <= days * 86400
    except Exception:
        try:
            return abs((da - db).days) <= days
        except Exception:
            return True                      # no usable dates: compare anyway


def make_deduper(kind, model=None):
    """'none'/None -> None; 'lexical' -> Deduper; 'embed' -> Deduper with a SentenceEmbedder."""
    if kind in (None, "none"):
        return None
    if kind == "lexical":
        return Deduper("lexical")
    if kind == "embed":
        return Deduper("embed", SentenceEmbedder(model))
    raise ValueError("dedup must be none, lexical or embed")


def main():
    texts = sys.argv[1:]
    if len(texts) < 2:
        sys.exit('usage: python news_dedup.py "headline one" "headline two" [...]')
    items = [{"title": t, "date": None} for t in texts]
    for kind in ("lexical",):
        kept, n = make_deduper(kind)(items)
        print(f"{kind}: kept {len(kept)}, removed {n}")
        for k in kept:
            print("  " + k["title"])
    print("pairwise word-overlap:", [(i, j, round(jaccard(tokens(texts[i]), tokens(texts[j])), 2))
                                       for i in range(len(texts)) for j in range(i + 1, len(texts))])


if __name__ == "__main__":
    main()
