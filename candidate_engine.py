"""
Candidate Engine.

Runs a universe of symbols through one or more strategies, sizes each
qualifying setup via the Risk Engine, and ranks the results. This is the
"what currently meets my rules, sized for my capital" view — not a
prediction of what will perform best.
"""

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

from data import fetch_history, fetch_market_cap_cr, classify_market_cap
from strategies import Strategy
from risk import RiskEngine
from filters import TradeFilters, ResultsCalendar
from market import Benchmark


@dataclass
class Candidate:
    symbol: str
    strategy: str
    score: int
    total: int
    entry: float
    stop: float
    target: float
    quantity: int
    capital_required: float
    risk_amount: float
    reason: str
    sector: str = "Unknown"
    market_cap_cr: float = 0.0
    cap_class: str = "Unknown"
    # Fundamentals (section 1) -- filled in by the screener only when --fundamentals is on
    fund_status: str = ""          # pass / fail / n/a, or "" when not run
    fund_notes: str = ""           # e.g. "failed: roce,de | n/a: icr | exempt: roce,de,icr"
    roce_pct: Optional[float] = None
    roe_avg_pct: Optional[float] = None
    debt_equity: Optional[float] = None
    pe: Optional[float] = None
    peg: Optional[float] = None
    fund_passed: int = 0           # fundamental rules passed (n/a and exempt rules are NOT counted)
    fund_evaluated: int = 0        # fundamental rules actually evaluated
    fund_passed_w: float = 0.0     # same, summed by rule weight (all weights 1 unless --weights-file is given)
    fund_evaluated_w: float = 0.0
    fund_score: str = ""           # passed weight / evaluated weight, e.g. "11/13"
    fund_tier: str = ""            # Strong / Mixed / Weak / n/a
    industry_pe: Optional[float] = None    # industry P/E the P/E rule used (screener.in peer median or industry_pe.csv)
    sales_growth_pct: Optional[float] = None
    pat_growth_pct: Optional[float] = None
    promoter_change_1q: Optional[float] = None    # pp, latest quarter
    pledged_change_1q: Optional[float] = None     # pp, only for consecutive-quarter XBRL filings
    fii_pct: Optional[float] = None
    fii_change_1q: Optional[float] = None         # pp; FII and DII are judged separately
    dii_pct: Optional[float] = None
    dii_change_1q: Optional[float] = None
    cond_met: str = ""             # strategy/technical conditions that were true
    cond_missed: str = ""          # conditions that were false (non-gating ones, e.g. volume)
    over_sector_cap: bool = False
    error: str = ""
    thesis: str = ""               # templated one-liner, built after ranking (see build_thesis)
    rel_strength: Optional[float] = None   # 63-day return minus index return, % points (None = unknown)
    stop_pct: float = 0.0                  # (entry - stop) / entry in %, tighter is better
    # Ownership (section 2) and qualitative layer (section 4) -- filled in by the screener when enabled
    promoter_pct: Optional[float] = None
    pledged_pct: Optional[float] = None
    sentiment_30d: Optional[float] = None
    sentiment_trend: Optional[float] = None
    sentiment_label: str = ""            # Positive / Neutral / Negative
    qual_severity: str = ""                # '', 'Medium' or 'High' governance red-flag severity
    qual_flags: str = ""
    anomaly_level: str = ""                # financial anomaly scan: "", "None", "Watch", "High" or "n/a"
    anomaly_flags: str = ""
    meta_prob: Optional[float] = None       # meta-model win probability (None = model off / not computable)

    @property
    def target_gain_pct(self) -> float:
        if self.entry:
            return round((self.target - self.entry) / self.entry * 100, 2)
        return 0.0


class CandidateEngine:
    def __init__(self, strategies: List[Strategy], risk_engine: RiskEngine, sector_map: Optional[dict] = None,
                 fetch_market_cap: bool = True, benchmark: Optional[Benchmark] = None,
                 trade_filters: Optional[TradeFilters] = None,
                 results_calendar: Optional[ResultsCalendar] = None, meta=None):
        self.meta = meta                            # meta_model.MetaModel or None
        self.fetch_market_cap = fetch_market_cap
        self.strategies = strategies
        self.risk_engine = risk_engine
        self.sector_map = sector_map or {}
        self.benchmark = benchmark                  # for relative strength (ranking tiebreaker)
        self.trade_filters = trade_filters          # same pre-trade filters the backtester applies
        self.results_calendar = results_calendar
        self.skipped: Dict[str, int] = {}           # filter reason -> signals dropped
        self.no_data: List[str] = []                # symbols whose price download failed
        self.aborted = False                        # True if the run stopped because Yahoo returned nothing at all

    def screen_symbol(self, symbol: str) -> List[Candidate]:
        results = []
        try:
            df = fetch_history(symbol)
        except Exception as e:
            return [Candidate(symbol=symbol.upper(), strategy="", score=0, total=0, entry=0, stop=0,
                               target=0, quantity=0, capital_required=0, risk_amount=0, reason="", error=str(e))]

        i = len(df) - 1
        cap_cr = None
        cap_fetched = False
        for strat in self.strategies:
            sig = strat.signal(df, i)
            if not sig.enter:
                continue
            if self.trade_filters is not None:
                reason = self.trade_filters.check(df, i, sig.entry, sig.stop, symbol=symbol,
                                                  calendar=self.results_calendar)
                if reason:
                    self.skipped[reason] = self.skipped.get(reason, 0) + 1
                    continue
            target = self.risk_engine.target_price(sig.entry, sig.stop)
            size = self.risk_engine.position_size(sig.entry, sig.stop)
            if size.quantity <= 0:
                continue
            # Market cap is a network call, so only fetch for symbols that qualify (once per symbol).
            if self.fetch_market_cap and not cap_fetched:
                cap_cr = fetch_market_cap_cr(symbol)
                cap_fetched = True
            results.append(Candidate(
                symbol=symbol.upper(), strategy=strat.name, score=sig.score, total=sig.total,
                entry=round(sig.entry, 2), stop=round(sig.stop, 2), target=target,
                quantity=size.quantity, capital_required=size.capital_required,
                risk_amount=size.risk_amount, reason=sig.reason,
                sector=self.sector_map.get(symbol.upper(), "Unknown"),
                market_cap_cr=cap_cr or 0.0, cap_class=classify_market_cap(cap_cr),
                cond_met=",".join(k for k, v in (sig.conditions or {}).items() if v),
                cond_missed=",".join(k for k, v in (sig.conditions or {}).items() if not v),
                rel_strength=self.benchmark.relative_strength(df, i) if self.benchmark is not None else None,
                stop_pct=round((sig.entry - sig.stop) / sig.entry * 100, 2),
                meta_prob=self._meta_prob(df, i, sig, strat.name),
            ))
        return results

    def _meta_prob(self, df, i, sig, strategy_name) -> Optional[float]:
        """Meta-model win probability for this setup, or None if no model / features could not be built."""
        if self.meta is None:
            return None
        try:
            import meta_model
            return self.meta.predict(meta_model.features_at(df, i, self.benchmark, sig, strategy_name))
        except Exception:
            return None

    ABORT_AFTER_FAILURES = 10    # consecutive failed downloads with zero successes -> stop, Yahoo is not answering

    def screen_universe(self, symbols: List[str], progress: bool = True) -> List[Candidate]:
        all_candidates = []
        ok, streak = 0, 0
        for idx, sym in enumerate(symbols, 1):
            if progress:
                print(f"  [{idx}/{len(symbols)}] {sym}...", end=" ")
            results = self.screen_symbol(sym)
            errored = [r for r in results if r.error]
            passed = [r for r in results if not r.error]
            if progress:
                if errored:
                    print(f"skipped ({errored[0].error})")
                elif passed:
                    print(", ".join(f"{c.strategy}:{c.score}/{c.total}" for c in passed))
                else:
                    print("no signal")
            all_candidates.extend(passed)
            if errored:
                self.no_data.append(sym)
                streak += 1
                if ok == 0 and streak >= self.ABORT_AFTER_FAILURES:
                    self.aborted = True
                    break
            else:
                ok, streak = ok + 1, 0
        return all_candidates

    @staticmethod
    def points(c: Candidate, fund_weight: float = 1.0) -> float:
        """
        Ranking points = technical conditions true + fund_weight x fundamental
        rules passed (summed by rule weight). Fundamentals only count when they were run (fund_status
        set). A rule that is n/a or exempt earns nothing, so missing data
        slightly lowers a stock's rank rather than being treated as a pass.
        With fundamentals off, this is exactly the old technical score.
        """
        return c.score + (fund_weight * c.fund_passed_w if c.fund_status else 0)

    @staticmethod
    def rank(candidates: List[Candidate], fund_weight: float = 1.0) -> List[Candidate]:
        """
        Ranks by combined points (technical + fundamental), then by meta-model
        probability (when a model is loaded), then by relative strength vs the index (unknown ranks last), then by tighter stop.
        Same ordering the backtester uses when several entries compete for
        one slot. A transparent, rule-based ranking, not a prediction.
        """
        def key(c: Candidate):
            rs = c.rel_strength if c.rel_strength is not None else float("-inf")
            mp = c.meta_prob if c.meta_prob is not None else float("-inf")
            return (CandidateEngine.points(c, fund_weight), mp, rs, -c.stop_pct)

        return sorted(candidates, key=key, reverse=True)

    _LABELS = {
        "price_above_20ema": "above 20-EMA", "price_above_50ema": "above 50-EMA",
        "ema50_sloping_up": "rising 50-EMA", "pullback_and_reclaim": "pullback and reclaim of the 20-EMA",
        "volume_confirmed": "volume above average", "has_valid_stop": "valid stop",
        "broke_above_recent_range": "broke its recent range", "strong_volume": "strong volume",
        "closed_near_high": "closed near the day's high", "liquidity_ok": "liquid",
        "above_sma200": "above 200-SMA", "near_52w_high": "near 52-week high",
    }
    _SHOWN = ["pullback_and_reclaim", "broke_above_recent_range", "ema50_sloping_up", "above_sma200",
              "near_52w_high", "volume_confirmed", "strong_volume", "liquidity_ok"]

    @staticmethod
    def build_thesis(c: Candidate) -> str:
        """
        Templated one-line summary assembled only from fields already computed
        for the candidate -- no LLM, no new data. It restates why the rules
        fired and what to watch; it is not a recommendation.
        """
        L = CandidateEngine._LABELS
        met = [x for x in c.cond_met.split(",") if x]
        missed = [x for x in c.cond_missed.split(",") if x]

        why = [L[k] for k in CandidateEngine._SHOWN if k in met]
        head = f"{c.symbol}"
        tag = ", ".join(x for x in (f"{c.cap_class} cap" if c.cap_class != "Unknown" else "",
                                    c.sector if c.sector != "Unknown" else "") if x)
        if tag:
            head += f" ({tag})"
        parts = [f"{head}: {c.reason}" + (f" - {', '.join(why)}" if why else "")]

        risk = c.entry - c.stop
        stop_pct = round(risk / c.entry * 100, 1) if c.entry else 0
        rr = round((c.target - c.entry) / risk, 1) if risk > 0 else 0
        parts.append(f"Entry {c.entry}, stop {c.stop} (-{stop_pct}%), target {c.target} (+{c.target_gain_pct}%), "
                     f"R:R {rr}, risk Rs {c.risk_amount}")

        if c.rel_strength is not None:
            parts[-1] += f", {c.rel_strength:+.1f} pts vs index over 63 days"
        if c.fund_status:
            vals = []
            if c.roce_pct is not None:
                vals.append(f"ROCE {c.roce_pct}%")
            if c.roe_avg_pct is not None:
                vals.append(f"ROE {c.roe_avg_pct}%")
            if c.debt_equity is not None:
                vals.append(f"D/E {c.debt_equity}")
            if c.pe is not None:
                vals.append(f"P/E {c.pe}")
            if c.peg is not None:
                vals.append(f"PEG {c.peg}")
            f = f"Fundamentals {c.fund_status} ({c.fund_passed}/{c.fund_evaluated} rules)"
            parts.append(f + (": " + ", ".join(vals) if vals else ""))

        if c.promoter_pct is not None:
            own = f"Promoter {c.promoter_pct}%"
            if c.pledged_pct is not None:
                own += f", {c.pledged_pct}% pledged"
            parts.append(own)
        inst = []
        for lab, pct, chg in (("FII", c.fii_pct, c.fii_change_1q), ("DII", c.dii_pct, c.dii_change_1q)):
            if pct is not None:
                inst.append(f"{lab} {pct}%" + (f" ({chg:+.2f} pp)" if chg is not None else ""))
        if inst:
            parts.append(", ".join(inst))
        if c.sentiment_30d is not None:
            tr = f", trend {c.sentiment_trend:+.2f}" if c.sentiment_trend is not None else ""
            parts.append(f"News sentiment (30d) {c.sentiment_30d:+.2f}{tr}")

        if c.meta_prob is not None:
            parts.append(f"Meta-model win probability {c.meta_prob:.0%}")

        watch = []
        if c.qual_flags:
            watch.append("governance flags: " + c.qual_flags)
        if c.anomaly_level in ("Watch", "High") and c.anomaly_flags:
            watch.append(f"financial anomalies ({c.anomaly_level}): {c.anomaly_flags}")
        if c.over_sector_cap:
            watch.append("over your sector cap")
        if c.fund_status and "failed:" in c.fund_notes:
            watch.append(c.fund_notes.split("|")[0].strip().replace("failed:", "failed fundamentals:"))
        if c.fund_status and "n/a:" in c.fund_notes:
            watch.append("some fundamentals unavailable")
        soft = [L.get(k, k) for k in missed if k in ("volume_confirmed", "closed_near_high")]
        if soft:
            watch.append("not confirmed: " + ", ".join(soft))
        if watch:
            parts.append("Watch: " + "; ".join(watch))
        return ". ".join(parts) + "."

    @staticmethod
    def flag_sector_concentration(ranked_candidates: List[Candidate], max_per_sector: int = 2) -> dict:
        """
        Walks the already-ranked list in order and marks candidate.over_sector_cap
        = True once a sector has already contributed max_per_sector candidates
        ahead of it in rank order. Does not remove or reorder anything -- it
        flags, so you keep the final call on whether to skip a flagged pick.
        Returns a summary: sector -> count, and which sectors breached the cap.
        """
        sector_counts: dict = {}
        for c in ranked_candidates:
            sector_counts[c.sector] = sector_counts.get(c.sector, 0) + 1
            c.over_sector_cap = sector_counts[c.sector] > max_per_sector

        breached = {s: n for s, n in sector_counts.items() if n > max_per_sector and s != "Unknown"}
        return {"sector_counts": sector_counts, "breached_sectors": breached, "max_per_sector": max_per_sector}

    @staticmethod
    def to_rows(candidates: List[Candidate]) -> List[dict]:
        rows = []
        for c in candidates:
            row = asdict(c)
            # Insert target_gain_pct right after 'target' for readability
            ordered = {}
            for k, v in row.items():
                ordered[k] = v
                if k == "target":
                    ordered["target_gain_pct"] = c.target_gain_pct
            rows.append(ordered)
        return rows
