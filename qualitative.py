"""
Qualitative layer (shortlisting doc, section 4) -- everything except concall summaries:

  * News: recent headlines per company from Google News RSS (public feed).
  * Sentiment: each headline scored -1..+1 by a finance keyword lexicon (offline,
    default) or, optionally, by a language model (local Ollama or the Anthropic API).
    Aggregated as 30-day sentiment, the previous 60 days, and the trend (difference).
  * Governance red flags: regex scan over the headlines AND over NSE corporate
    announcements for auditor resignations, qualified opinions, SEBI actions, fraud
    probes, pledge invocations, insolvency/default, rating downgrades, results delays,
    senior management exits, promoter selling, short-seller reports.

Honest limits:
  * Headline sentiment is noisy; the lexicon is crude. Treat it as a prompt to read the
    headlines (they are listed), never as a signal on its own.
  * Red flags are pattern matches, not findings: every flag carries its source text, date
    and link so you can verify it. News-sourced flags are lower confidence than NSE filings.
  * Live data: results are a snapshot, so this is screen-only (never used in the backtester).
  * Network code could not be tested against the live feeds from the sandbox.
"""

import csv
import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "qualitative")
CACHE_TTL = 24 * 3600
FORCE_REFRESH = False        # bypass cached results (set by --refresh-cache / --debug-dump)
PATTERN_VERSION = 4          # bump when FLAG_PATTERNS / scoring change, so stale cached results are ignored
NEWS_URL = "https://news.google.com/rss/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/124.0 Safari/537.36"}
SEVERITY_RANK = {"": 0, "Low": 1, "Medium": 2, "High": 3}

# ---------------------------------------------------------------- red flags
FLAG_PATTERNS = [
    ("auditor_resignation", "High",
     r"auditors?\W.{0,40}resign|resign\w*.{0,40}(statutory )?auditor|resignation of (the )?(statutory )?auditors?"),
    ("qualified_audit", "High",
     r"qualified (audit )?(opinion|report)|adverse opinion|disclaimer of opinion|audit qualification"),
    ("sebi_action", "High",
     r"sebi\W.{0,60}(penalt|fine[sd]?\b|bans?\b|barred|debar|show[- ]cause|adjudicat|orders? against|impound|probe|investigat|notice)"
     r"|(penalt|fine[sd]?\b|banned|debarred|show[- ]cause|probe|investigat).{0,60}\bsebi\b"),
    ("fraud_probe", "High",
     r"(fraud|embezzl|misappropriat|money laundering|irregularit).{0,60}(alleg|probe|investigat|case\b|fir\b|arrest|charge)"
     r"|(alleg|probe|investigat).{0,60}(fraud|embezzl|misappropriat|laundering|irregularit)"
     r"|forensic audit|enforcement directorate|\bsfio\b|\bcbi\b"
     r"|(income[- ]tax|\bit\b department|\bed\b|\bcbi\b).{0,30}(raid|search|survey)"),
    ("pledge_invocation", "High", r"invo(ke|ked|cation|cat\w*).{0,30}pledge|pledge\w*.{0,30}invo(ke|ked|cation)"),
    ("insolvency_default", "High",
     r"\bnclt\b.{0,50}(admit|initiat|insolvency|petition|plea)|insolvency (petition|plea|proceedings?|resolution process)"
     r"|\bcirp\b|files? for (insolvency|bankruptcy)|bankruptcy (filing|protection)"
     r"|defaults? on (its |the )?(loan|debt|bonds?|repayment|interest|payment)|loan default|payment default"
     r"|missed (an )?(interest|repayment|payment)|debt restructuring|one[- ]time settlement"),
    ("rating_downgrade", "Medium",
     r"(crisil|icra|\bcare\b|india ratings|moody|fitch|s&p|brickwork|acuite|credit rating|debt rating)\W.{0,60}"
     r"(downgrad|cut\b|lower|negative|watch)|(downgrad|lower|cut)\w*.{0,40}(credit rating|debt rating|bonds?|ncds?"
     r"|commercial paper|long[- ]term rating)"),
    ("results_delay", "Medium",
     r"delay\w*.{0,40}(submission|filing|financial results|results)|postpone\w*.{0,30}(board meeting|results)"
     r"|fail\w*\s+to\s+(file|submit)"),
    ("mgmt_exit", "Medium",
     r"(resign\w*|steps? down|quits?).{0,40}\b(cfo|ceo|chief financial|chief executive|managing director|chairman|chairperson)\b"
     r"|\b(cfo|ceo|chief financial officer|chief executive|chairman|chairperson)\b.{0,30}(resign\w*|steps? down|quits?)"),
    ("mgmt_exit_minor", "Low",
     r"(resign\w*|steps? down|quits?).{0,60}\b(company secretary|compliance officer|director)\b"
     r"|\b(company secretary|compliance officer)\b.{0,30}(resign\w*|steps? down|quits?)"),
    ("promoter_selling", "Medium", r"promoter\w*.{0,30}(sells?|sold|offload\w*|stake sale|pares?|reduces?)"),
    ("short_seller", "Medium", r"short[- ]seller|hindenburg"),
]
_FLAG_RE = [(n, sev, re.compile(p, re.I)) for n, sev, p in FLAG_PATTERNS]
_SUBJECT_FIRST = {"promoter_selling", "mgmt_exit", "mgmt_exit_minor", "short_seller"}   # news only: company named BEFORE the match
_SUBSIDIARY_CTX = re.compile(r"subsidiar|associate compan|joint venture|step[- ]down", re.I)
# The company can be the BUYER or CREDITOR in an insolvency (bidding for a bankrupt rival, a customer in CIRP).
# Such text is not a red flag about the company itself, so insolvency/default matches are dropped when it appears.
_NOT_ABOUT_SELF = re.compile(r"acqui\w+|\bbid(s|ding|der)?\b|takeover|\bbuys?\b|resolution applicant|"
                             r"successful (bidder|applicant)|financial creditor|operational creditor|"
                             r"insolvent (firm|company|rival|builder|developer)|personal insolvency|"
                             r"insolvency (proceedings?|petition|process) (of|against) (dr|mr|mrs|ms|shri|smt)\b", re.I)


def scan_text(text: str, tokens=None, source: str = "nse"):
    """[(flag, severity, matched snippet)] for one piece of text.
    tokens: lowercase company name/ticker fragments. For NEWS headlines, flags in _SUBJECT_FIRST only count when
    the company is named before the matched phrase ('Edelweiss promoter sells ...; HDFC MF buys ...' is not HDFC
    AMC's promoter selling). NSE filings are the company's own, so no such check applies."""
    out, hit = [], {}
    for name, sev, rx in _FLAG_RE:
        m = rx.search(text or "")
        if not m:
            continue
        if name == "insolvency_default" and _NOT_ABOUT_SELF.search(text):
            continue
        if name == "auditor_resignation" and _SUBSIDIARY_CTX.search(text):
            name, sev = "auditor_resignation_subsidiary", "Medium"       # routine-ish; still worth a glance
        if tokens and source == "news" and name in _SUBJECT_FIRST:
            if not any(t in (text[:m.start()] or "").lower() for t in tokens):
                continue
        hit[name] = (name, sev, m.group(0)[:80])
    if "mgmt_exit" in hit:
        hit.pop("mgmt_exit_minor", None)                                 # one exit, one flag: the senior one
    return list(hit.values())


def scan_items(items, source, tokens=None, gov_model=None):
    """items: [{'text'|'title', 'date', 'link'}] -> list of flag dicts (deduplicated).
    gov_model (gov_classifier.GovModel): optional second opinion; adds ml_prob and may lower a severity one step."""
    seen, flags = set(), []
    for it in items:
        text = it.get("text") or it.get("title") or ""
        for name, sev, snip in scan_text(text, tokens, source):
            key = (name, text[:80])
            if key in seen:
                continue
            seen.add(key)
            if source == "news" and sev == "High":
                sev = "Medium"                      # a headline alone is unverified; only NSE filings count as High
            f = {"flag": name, "severity": sev, "source": source, "date": str(it.get("date") or ""),
                 "text": text[:200], "link": it.get("link") or ""}
            if gov_model is not None:
                gov_model.apply(f, text)
            flags.append(f)
    return flags


def top_severity(flags) -> str:
    best = ""
    for f in flags:
        if SEVERITY_RANK[f["severity"]] > SEVERITY_RANK[best]:
            best = f["severity"]
    return best


# ---------------------------------------------------------------- lexicon sentiment
_POS = {"surge": 2, "surges": 2, "soar": 2, "soars": 2, "jump": 1, "jumps": 1, "rally": 1, "rallies": 1,
        "gain": 1, "gains": 1, "rise": 1, "rises": 1, "record": 1, "beat": 1, "beats": 1, "upgrade": 2,
        "upgrades": 2, "upgraded": 2, "outperform": 2, "bags": 1, "wins": 1, "win": 1, "order": 0.5, "orders": 0.5,
        "strong": 1, "robust": 1, "growth": 0.5, "profit": 0.5, "buyback": 1, "dividend": 0.5, "expansion": 0.5,
        "approval": 1, "approves": 1, "raises": 0.5, "boost": 1, "boosts": 1, "positive": 1, "bullish": 2,
        "turnaround": 1, "recovery": 1, "acquires": 0.5, "partnership": 0.5, "top pick": 2, "buy": 0.5}
_NEG = {"fall": 1, "falls": 1, "fell": 1, "plunge": 2, "plunges": 2, "slump": 2, "slumps": 2, "tumble": 2,
        "tumbles": 2, "crash": 2, "crashes": 2, "drop": 1, "drops": 1, "decline": 1, "declines": 1, "slips": 1,
        "downgrade": 2, "downgrades": 2, "downgraded": 2, "miss": 1, "misses": 1, "loss": 1, "losses": 1,
        "weak": 1, "weakness": 1, "probe": 2, "fraud": 3, "penalty": 2, "fine": 1, "fined": 2, "default": 3,
        "resigns": 1, "resignation": 1, "raid": 2, "raids": 2, "concern": 1, "concerns": 1, "warning": 1,
        "warns": 1, "lawsuit": 1, "slash": 1, "slashes": 1, "cuts": 1, "cut": 1, "bearish": 2, "sell": 0.5,
        "selloff": 1, "pressure": 1, "scam": 3, "insolvency": 3, "debt": 0.5, "risk": 0.5, "delay": 1,
        "delays": 1, "shortfall": 1, "underperform": 2, "layoffs": 1, "ban": 2, "banned": 2}
_NEGATORS = {"no", "not", "never", "without", "denies", "denied", "rules out", "ruled out"}
_TOK = re.compile(r"[a-z][a-z'-]*")


def lexicon_score(headline: str) -> float:
    """-1..+1. Negators in the two words before a term flip its sign."""
    toks = _TOK.findall((headline or "").lower())
    pos = neg = 0.0
    for i, t in enumerate(toks):
        w = _POS.get(t)
        n = _NEG.get(t)
        if w is None and n is None:
            continue
        flipped = any(x in _NEGATORS for x in toks[max(0, i - 2):i])
        if w is not None:
            if flipped:
                neg += w
            else:
                pos += w
        if n is not None:
            if flipped:
                pos += n
            else:
                neg += n
    tot = pos + neg
    return round((pos - neg) / tot, 3) if tot else 0.0


# ---------------------------------------------------------------- optional LLM scorer
class LLMScorer:
    """Scores headlines with a language model. kind = 'ollama' (local, no key) or 'anthropic'
    (needs ANTHROPIC_API_KEY). Any failure returns None for the batch and the caller falls back
    to the lexicon, so a model outage never breaks a run."""

    def __init__(self, kind="ollama", model=None, url=None, batch=25, timeout=120):
        self.kind, self.batch, self.timeout = kind, batch, timeout
        if kind == "ollama":
            self.model = model or os.environ.get("OLLAMA_MODEL", "llama3.1")
            self.url = (url or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        elif kind == "anthropic":
            self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
            self.url = "https://api.anthropic.com/v1/messages"
        else:
            raise ValueError("llm kind must be 'ollama' or 'anthropic'")
        self.name = f"{kind}:{self.model}"

    def _prompt(self, company, headlines):
        lines = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(headlines))
        return ("You classify Indian stock-market news headlines about the company '" + company + "' by what they "
                "imply for the company's shareholders. For EACH headline give a number from -1 (very negative) "
                "to 1 (very positive); 0 = neutral or unrelated. Reply with ONLY JSON like "
                '{"scores":[0.2,-0.6]} containing exactly ' + str(len(headlines)) + " numbers, in order.\n\n" + lines)

    def _call(self, prompt):
        if self.kind == "ollama":
            r = requests.post(self.url + "/api/chat", timeout=self.timeout, json={
                "model": self.model, "stream": False, "format": "json", "options": {"temperature": 0},
                "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            return r.json()["message"]["content"]
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        r = requests.post(self.url, timeout=self.timeout,
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                          json={"model": self.model, "max_tokens": 1000, "temperature": 0,
                                "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        return r.json()["content"][0]["text"]

    @staticmethod
    def parse(text, n):
        m = re.search(r"\{.*\}", text or "", re.S)
        if not m:
            return None
        try:
            vals = json.loads(m.group(0)).get("scores")
        except Exception:
            return None
        if not isinstance(vals, list) or len(vals) != n:
            return None
        try:
            return [max(-1.0, min(1.0, float(v))) for v in vals]
        except (TypeError, ValueError):
            return None

    def score(self, company, headlines):
        out = []
        for i in range(0, len(headlines), self.batch):
            chunk = headlines[i:i + self.batch]
            try:
                res = self.parse(self._call(self._prompt(company, chunk)), len(chunk))
            except Exception:
                res = None
            out += res if res else [None] * len(chunk)
        return out


# ---------------------------------------------------------------- FinBERT scorer (PyTorch, local)
class FinBertScorer:
    """Scores headlines with FinBERT (finance-tuned BERT) running locally: score = P(positive) - P(negative),
    -1..+1, same contract as LLMScorer. Needs `pip install torch transformers`. The model is downloaded once from
    Hugging Face (ProsusAI/finbert) or loaded from a local folder (--llm-model C:\\models\\finbert). If it cannot be
    loaded, score() returns None for every headline and the caller falls back to the lexicon."""

    def __init__(self, model=None, batch=32, max_len=128):
        self.model_id = model or os.environ.get("FINBERT_MODEL", "ProsusAI/finbert")
        self.batch, self.max_len = batch, max_len
        self.name = "finbert:" + (os.path.basename(self.model_id.rstrip("/\\")) or self.model_id)
        self.error, self._ready = None, False

    @staticmethod
    def score_from_probs(probs, pos_idx, neg_idx):
        return round(float(probs[pos_idx] - probs[neg_idx]), 3)

    def _load(self):
        if self._ready:
            return
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self._torch = torch
        self._tok = AutoTokenizer.from_pretrained(self.model_id)
        self._mdl = AutoModelForSequenceClassification.from_pretrained(self.model_id).eval()
        labels = {int(i): str(l).lower() for i, l in self._mdl.config.id2label.items()}
        self._pos = next(i for i, l in labels.items() if l.startswith("pos"))
        self._neg = next(i for i, l in labels.items() if l.startswith("neg"))
        self._dev = "cuda" if torch.cuda.is_available() else "cpu"
        self._mdl.to(self._dev)
        self._ready = True

    def score(self, company, headlines):
        if not headlines:
            return []
        try:
            self._load()
        except Exception as e:
            if self.error is None:
                self.error = f"{type(e).__name__}: {e}"[:200]
                print(f"  [warning] FinBERT unavailable ({self.error}); using the keyword lexicon instead")
            return [None] * len(headlines)
        out = []
        for i in range(0, len(headlines), self.batch):
            chunk = headlines[i:i + self.batch]
            try:
                enc = self._tok(chunk, padding=True, truncation=True, max_length=self.max_len, return_tensors="pt")
                enc = {k: v.to(self._dev) for k, v in enc.items()}
                with self._torch.no_grad():
                    probs = self._torch.softmax(self._mdl(**enc).logits, dim=-1).cpu().numpy()
                out += [self.score_from_probs(p, self._pos, self._neg) for p in probs]
            except Exception:
                out += [None] * len(chunk)
        return out


def make_scorer(kind, model=None, url=None):
    """'none' -> None (lexicon); 'finbert' -> FinBertScorer; 'ollama' / 'anthropic' -> LLMScorer."""
    if kind in (None, "none"):
        return None
    if kind == "finbert":
        return FinBertScorer(model)
    return LLMScorer(kind, model, url)


def load_gov_model(path):
    """Optional governance false-positive classifier trained by gov_classifier.py. None if no path is given."""
    if not path:
        return None
    import gov_classifier
    return gov_classifier.GovModel.load(path)


# ---------------------------------------------------------------- news
def clean_company_name(name: str) -> str:
    """'ABB INDIALIMITED' -> 'ABB INDIA'; 'AMBUJA CEMENTS LIMITED- NEW EQUITY SHARES...' -> 'AMBUJA CEMENTS'.
    Cuts at the first 'limited' / 'ltd' even when the CAS glued it to the name."""
    s = re.split(r"#| - |\[|\(", str(name))[0]
    m = re.search(r"limited|ltd\b", s, re.I)
    if m:
        s = s[:m.start()]
    s = re.sub(r"\b(pvt|private|inc\.?)\b", "", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip(" .,-")


def _query(term: str, days: int):
    last = None
    for k in range(3):                                  # transient timeouts happen (seen in a real run)
        try:
            r = requests.get(NEWS_URL, params={"q": f'"{term}" (stock OR shares OR NSE OR results) when:{days}d',
                                               "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last = e
            time.sleep(1.5 * (k + 1))
    raise last


def fetch_news(name: str, days: int = 90, limit: int = 80, symbol: str = None):
    """[{'title','link','source','date'(datetime, UTC)}] from Google News RSS, newest first.
    Long legal names rarely match headlines, so if the full name finds fewer than 8 items the first two
    words, then the ticker, are searched too."""
    base = clean_company_name(name)
    words = base.split()
    variants = [base] + ([" ".join(words[:2])] if len(words) > 2 else [])
    if symbol and symbol.upper() != base.upper():
        variants.append(symbol)
    items, seen = [], set()
    for v in variants:
        for it in parse_rss(_query(v, days), name, symbol):
            if it["title"] not in seen:
                seen.add(it["title"])
                items.append(it)
        if len(items) >= 8:
            break
    return sorted(items, key=lambda x: x["date"], reverse=True)[:limit]


def parse_rss(xml_text: str, company: str = "", symbol: str = None):
    root = ET.fromstring(xml_text)
    head = clean_company_name(company).lower().split(" ")[0] if company else ""
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        try:
            dt = parsedate_to_datetime(it.findtext("pubDate") or "")
            dt = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        low = title.lower()
        if head and head not in low and not (symbol and len(symbol) >= 3 and symbol.lower() in low):
            # drop results that never mention the company (by name or ticker)
            continue
        out.append({"title": title, "link": (it.findtext("link") or "").strip(), "source": src, "date": dt})
    return sorted(out, key=lambda x: x["date"], reverse=True)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def sentiment_summary(items, scores, now=None, min_n=3):
    """30-day sentiment, previous-period sentiment and the trend between them."""
    now = now or datetime.now(timezone.utc)
    recent = [s for it, s in zip(items, scores) if it["date"] >= now - timedelta(days=30)]
    prev = [s for it, s in zip(items, scores) if it["date"] < now - timedelta(days=30)]
    s30, sp = _mean(recent), _mean(prev)
    trend = round(s30 - sp, 3) if (s30 is not None and sp is not None and len(recent) >= min_n and len(prev) >= min_n) else None
    label = None if s30 is None else "Positive" if s30 > 0.15 else "Negative" if s30 < -0.15 else "Neutral"
    return {"news_n_30d": len(recent), "news_n_prev": len(prev), "sentiment_30d": s30, "sentiment_prev": sp,
            "sentiment_trend": trend, "sentiment_label": label}


# ---------------------------------------------------------------- company names
def symbol_name_map() -> dict:
    """SYMBOL -> company name from NSE's equity list if it is cached (holdings_analysis downloads it)."""
    import universe
    path = os.path.join(universe.CACHE_DIR, "equity_l.csv")
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                row = {(k or "").strip().upper(): (v or "").strip() for k, v in row.items()}
                if row.get("SYMBOL") and row.get("NAME OF COMPANY"):
                    out[row["SYMBOL"]] = row["NAME OF COMPANY"]
    return out


# ---------------------------------------------------------------- main entry
def _cache_file(symbol, tag):
    return os.path.join(CACHE_DIR, f"{symbol.upper().replace('&', '_')}_{tag}.json")


def analyse(symbol: str, name: str = None, days: int = 90, scorer=None,
            use_news: bool = True, use_announcements: bool = True, gov_model=None) -> dict:
    """
    Never raises. Returns a flat dict ready for a table row:
      news_n_30d, sentiment_30d, sentiment_prev, sentiment_trend, sentiment_label, scorer,
      flag_severity ('', 'Medium', 'High'), flag_text (one line), flags (list of dicts),
      top_negative (headline text), q_notes (what could not be fetched).
    """
    name = name or symbol
    tag = hashlib.md5(f"v{PATTERN_VERSION}|{days}|{use_news}|{use_announcements}|{scorer.name if scorer else 'lexicon'}|{gov_model.name if gov_model else 'regex'}".encode()).hexdigest()[:8]
    path = _cache_file(symbol, tag)
    if not FORCE_REFRESH and os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    notes, items, flags, sent = [], [], [], {}
    if use_news:
        try:
            items = fetch_news(name, days, symbol=symbol)
            if not items:
                notes.append(f"news: no headlines found for '{clean_company_name(name)}'")
            heads = [i["title"] for i in items]
            scores = [lexicon_score(h) for h in heads]
            used = "lexicon"
            if scorer and heads:
                llm = scorer.score(clean_company_name(name), heads)
                if any(v is not None for v in llm):
                    scores = [l if l is not None else s for l, s in zip(llm, scores)]
                    used = scorer.name if all(v is not None for v in llm) else scorer.name + "+lexicon"
                else:
                    notes.append("LLM scoring failed, used lexicon")
            sent = sentiment_summary(items, scores)
            sent["scorer"] = used
            neg = sorted(zip(scores, items), key=lambda x: x[0])[:1]
            sent["top_negative"] = neg[0][1]["title"] if neg and neg[0][0] < -0.3 else ""
            head = clean_company_name(name).lower().split(" ")[0]
            tokens = [t for t in {head, symbol.lower()} if len(t) >= 3]
            flags += scan_items([{"title": i["title"], "date": i["date"].date(), "link": i["link"]} for i in items],
                                "news", tokens, gov_model)
        except Exception as e:
            notes.append(f"news: {type(e).__name__}: {e}"[:160])
    if use_announcements:
        try:
            import nse_client
            ann = nse_client.announcements(symbol, days)
            flags = scan_items(ann, "NSE", None, gov_model) + flags               # NSE filings first: higher confidence
        except Exception as e:
            notes.append(f"NSE announcements: {type(e).__name__}: {e}"[:160])

    sev = top_severity(flags)
    order = sorted(flags, key=lambda f: (-SEVERITY_RANK[f["severity"]], f["source"] != "NSE"))
    res = {**{k: sent.get(k) for k in ("news_n_30d", "news_n_prev", "sentiment_30d", "sentiment_prev",
                                       "sentiment_trend", "sentiment_label", "scorer", "top_negative")},
           "flag_severity": sev,
           "flag_text": "; ".join(f"{f['flag']} [{f['severity']}, {f['source']}, {f['date']}]" for f in order[:4]),
           "flags": order, "q_notes": " | ".join(notes)}
    if not notes:                                               # only cache complete results
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(res, f, default=str)
    return res
