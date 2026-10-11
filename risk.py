"""
Risk Engine.

Turns an entry/stop pair into an actual position size, and tracks total
risk across open positions against a portfolio ceiling — the same logic
as the Position size and Portfolio heat features in the HTML ledger,
but usable programmatically here so the backtester enforces the exact
same discipline a live trader following these rules would.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PositionSize:
    quantity: int
    capital_required: float
    risk_amount: float
    risk_pct_of_capital: float
    capped_by_capital: bool


@dataclass
class OpenPosition:
    symbol: str
    entry: float
    stop: float
    quantity: int
    entry_date: Optional[str] = None


class RiskEngine:
    def __init__(self, capital: float, risk_pct_per_trade: float = 1.5,
                 portfolio_heat_ceiling_pct: float = 8.0, max_concurrent_positions: int = 5,
                 reward_risk_ratio: float = 2.0, min_risk_fraction: float = 0.5):
        self.capital = capital
        self.risk_pct_per_trade = risk_pct_per_trade
        self.portfolio_heat_ceiling_pct = portfolio_heat_ceiling_pct
        self.max_concurrent_positions = max_concurrent_positions
        self.reward_risk_ratio = reward_risk_ratio
        self.min_risk_fraction = min_risk_fraction

    def position_size(self, entry: float, stop: float, available_capital: Optional[float] = None,
                      capital_limit: Optional[float] = None) -> PositionSize:
        """
        available_capital: the base the risk % is applied to (use total
            EQUITY in a backtest, so risk per trade doesn't shrink as cash
            gets deployed).
        capital_limit: the most you can actually spend on this position
            (e.g. free CASH). Defaults to available_capital.
        """
        cap = available_capital if available_capital is not None else self.capital
        limit = capital_limit if capital_limit is not None else cap
        risk_per_share = abs(entry - stop)
        if risk_per_share <= 0:
            return PositionSize(0, 0, 0, 0, False)

        risk_amount = cap * (self.risk_pct_per_trade / 100)
        qty_by_risk = int(risk_amount // risk_per_share)
        qty_by_capital = int(max(limit, 0) // entry) if entry > 0 else 0
        qty = min(qty_by_risk, qty_by_capital)
        qty = max(qty, 0)

        capital_required = qty * entry
        actual_risk = qty * risk_per_share
        return PositionSize(
            quantity=qty,
            capital_required=round(capital_required, 2),
            risk_amount=round(actual_risk, 2),
            risk_pct_of_capital=round((actual_risk / cap * 100) if cap else 0, 3),
            capped_by_capital=qty_by_risk > qty_by_capital,
        )

    def undersized(self, risk_amount: float, base_capital: Optional[float] = None) -> bool:
        """
        True if capital/cash limits cut the position's actual risk below
        `min_risk_fraction` of the risk you intended to take (risk % x capital).
        Typical causes: a very tight stop that would swallow all your capital
        in one position, or a 1-2 share stub bought with leftover cash. Those
        are not trades you'd really place. 0 disables the rule.
        """
        if self.min_risk_fraction <= 0:
            return False
        cap = base_capital if base_capital is not None else self.capital
        return risk_amount < self.min_risk_fraction * cap * self.risk_pct_per_trade / 100

    def target_price(self, entry: float, stop: float) -> float:
        """Target based on a fixed reward:risk multiple of the stop distance."""
        risk = entry - stop
        return round(entry + risk * self.reward_risk_ratio, 2)

    def portfolio_heat(self, open_positions: List[OpenPosition], capital: Optional[float] = None) -> dict:
        cap = capital if capital is not None else self.capital
        total_risk = sum(max(0, p.entry - p.stop) * p.quantity for p in open_positions)
        heat_pct = (total_risk / cap * 100) if cap else 0
        return {
            "open_positions": len(open_positions),
            "total_risk_rupees": round(total_risk, 2),
            "heat_pct": round(heat_pct, 3),
            "over_ceiling": heat_pct >= self.portfolio_heat_ceiling_pct,
            "at_max_positions": len(open_positions) >= self.max_concurrent_positions,
        }

    def can_add_position(self, open_positions: List[OpenPosition], new_entry: float, new_stop: float,
                          new_qty: int, capital: Optional[float] = None) -> bool:
        cap = capital if capital is not None else self.capital
        if len(open_positions) >= self.max_concurrent_positions:
            return False
        hypothetical = open_positions + [OpenPosition(symbol="_new", entry=new_entry, stop=new_stop, quantity=new_qty)]
        heat = self.portfolio_heat(hypothetical, capital=cap)
        return not heat["over_ceiling"]
