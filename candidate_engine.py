"""
Candidate Engine.

Runs a universe of symbols through one or more strategies, applies the
pre-trade filters, sizes each qualifying setup via the Risk Engine, and
ranks the results. This is the "what currently meets my rules, sized for
my capital" view — not a prediction of what will perform best.
"""

from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple

from data import fetch_history
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
    over_sector_cap: bool = False
    error: str = ""
    rel_strength: Optional[float] = None   # 63-day return minus Nifty's, % points
    stop_pct: float = 0.0                  # (entry - stop) / entry, %
    traded_value_cr: float = 0.0           # 20-day avg traded value, Rs crore
    regime_ok: Optional[bool] = None       # None = not checked / unknown

    @property
    def target_gain_pct(self) -> float:
        if self.entry:
            return round((self.target - self.entry) / self.entry * 100, 2)
        return 0.0


class CandidateEngine:
    def __init__(self, strategies: List[Strategy], risk_engine: RiskEngine, sector_map: Optional[dict] = None,
                 filters: Optional[TradeFilters] = None, benchmark: Optional[Benchmark] = None,
                 results_calendar: Optional[ResultsCalendar] = None, regime_mode: str = "flag"):
        """
        regime_mode: "off"   -- ignore the market regime
                     "flag"  -- keep candidates, mark regime_ok=False when the index is below its trend
                     "block" -- drop all candidates while the index is below its trend
        Everything dropped by a filter is recorded in self.rejected as
        (symbol, strategy, reason_key) so nothing disappears silently.
        """
        self.strategies = strategies
        self.risk_engine = risk_engine
        self.sector_map = sector_map or {}
        self.filters = filters
        self.benchmark = benchmark
        self.results_calendar = results_calendar
        self.regime_mode = regime_mode
        self.rejected: List[Tuple[str, str, str]] = []

    def screen_symbol(self, symbol: str) -> List[Candidate]:
        results = []
        try:
            df = fetch_history(symbol)
        except Exception as e:
            return [Candidate(symbol=symbol.upper(), strategy="", score=0, total=0, entry=0, stop=0,
                               target=0, quantity=0, capital_required=0, risk_amount=0, reason="", error=str(e))]

        i = len(df) - 1
        regime = None
        if self.benchmark is not None and self.regime_mode != "off":
            regime = self.benchmark.is_bullish(df.index[i].date())

        for strat in self.strategies:
            sig = strat.signal(df, i)
            if not sig.enter:
                continue
            sym = symbol.upper()
            if self.regime_mode == "block" and regime is False:
                self.rejected.append((sym, strat.name, "regime"))
                continue
            if self.filters is not None:
                reason = self.filters.check(df, i, sig.entry, sig.stop, symbol=sym,
                                            calendar=self.results_calendar)
                if reason:
                    self.rejected.append((sym, strat.name, reason))
                    continue
            target = self.risk_engine.target_price(sig.entry, sig.stop)
            size = self.risk_engine.position_size(sig.entry, sig.stop)
            if size.quantity <= 0:
                self.rejected.append((sym, strat.name, "zero_quantity"))
                continue
            if self.risk_engine.undersized(size.risk_amount):
                self.rejected.append((sym, strat.name, "undersized"))
                continue
            tv = float(df["traded_value20"].iloc[i]) if "traded_value20" in df.columns else float("nan")
            results.append(Candidate(
                symbol=sym, strategy=strat.name, score=sig.score, total=sig.total,
                entry=round(sig.entry, 2), stop=round(sig.stop, 2), target=target,
                quantity=size.quantity, capital_required=size.capital_required,
                risk_amount=size.risk_amount, reason=sig.reason,
                sector=self.sector_map.get(sym, "Unknown"),
                rel_strength=self.benchmark.relative_strength(df, i) if self.benchmark is not None else None,
                stop_pct=round((sig.entry - sig.stop) / sig.entry * 100, 2),
                traded_value_cr=round(tv / 1e7, 1) if tv == tv else 0.0,
                regime_ok=regime,
            ))
        return results

    def screen_universe(self, symbols: List[str], progress: bool = True) -> List[Candidate]:
        all_candidates = []
        for idx, sym in enumerate(symbols, 1):
            if progress:
                print(f"  [{idx}/{len(symbols)}] {sym}...", end=" ")
            n_rejected_before = len(self.rejected)
            results = self.screen_symbol(sym)
            errored = [r for r in results if r.error]
            passed = [r for r in results if not r.error]
            if progress:
                if errored:
                    print(f"skipped ({errored[0].error})")
                elif passed:
                    print(", ".join(f"{c.strategy}:{c.score}/{c.total}" for c in passed))
                elif len(self.rejected) > n_rejected_before:
                    print(f"signal filtered out ({self.rejected[-1][2]})")
                else:
                    print("no signal")
            all_candidates.extend(passed)
        return all_candidates

    @staticmethod
    def rank(candidates: List[Candidate]) -> List[Candidate]:
        """
        Ranks by score first (more confirming conditions), then by relative
        strength vs the index (stronger first), then by tighter stop.

        (Reward:risk used to be the tiebreaker, but the target is a fixed
        multiple of the stop distance so it was identical for every
        candidate.) Candidates with no relative-strength figure sort after
        those that have one. Transparent and rule-based, not a prediction.
        """
        def key(c: Candidate):
            rs = c.rel_strength if c.rel_strength is not None else float("-inf")
            return (c.score, rs, -c.stop_pct)

        return sorted(candidates, key=key, reverse=True)

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
