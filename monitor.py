"""
Position Monitor.

Answers a different question than the Candidate Engine: not "should I
enter," but "given I already hold this, does my original thesis still
hold, and what should my stop be now."

This mirrors the exit rules in trading-rules.md:
  - Trend intact check (still above rising 20/50 EMA)
  - Move stop to breakeven once price is up 1x initial risk
  - Trail the stop below each new higher swing low after that (not before)
  - Time-stop: flag if 2+ weeks in with little progress
"""

from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional

import pandas as pd

from data import fetch_history
from strategies import Strategy
from exits import suggest_stop, time_stop_hit


@dataclass
class MonitorResult:
    symbol: str
    current_price: float
    entry: float
    original_stop: float
    quantity: int
    days_held: int
    unrealized_pnl: float
    r_multiple: float
    trend_conditions: dict
    trend_intact: bool
    stop_already_hit: bool
    target_already_hit: Optional[bool]
    suggested_stop: float
    time_stop_flag: bool
    verdict: str
    verdict_reason: str


class PositionMonitor:
    def __init__(self, strategy: Strategy, time_stop_days: int = 14, swing_low_lookback: int = 10):
        self.strategy = strategy
        self.time_stop_days = time_stop_days
        self.swing_low_lookback = swing_low_lookback

    def check(self, symbol: str, entry: float, stop: float, quantity: int,
              entry_date: str, target: Optional[float] = None) -> MonitorResult:
        df = fetch_history(symbol, period="1y")
        i = len(df) - 1
        today = df.iloc[i]
        current_price = float(today["Close"])

        entry_dt = pd.Timestamp(entry_date)
        # Trading days held, and calendar days for the time-stop check
        days_held_calendar = (pd.Timestamp(df.index[i].date()) - entry_dt).days

        # Has the original stop or target already been breached at any point
        # since entry? (Someone might be running this a few days late.)
        since_entry = df[df.index >= entry_dt]
        stop_already_hit = bool((since_entry["Low"] <= stop).any()) if len(since_entry) else False
        target_already_hit = bool((since_entry["High"] >= target).any()) if target and len(since_entry) else None

        trend_conditions = self.strategy.trend_intact(df, i)
        trend_ok = all(trend_conditions.values())

        risk_per_share = entry - stop
        r_multiple = ((current_price - entry) / risk_per_share) if risk_per_share > 0 else 0
        unrealized_pnl = (current_price - entry) * quantity

        # Trailing stop suggestion (shared with the backtester via exits.py):
        # breakeven once up 1R, then trail below the most recent swing low.
        # Trailing only starts after the 1R trigger, per the rules above.
        suggested_stop, _ = suggest_stop(df, i, entry, stop, stop, self.swing_low_lookback)

        time_stop_flag = time_stop_hit(days_held_calendar, r_multiple, self.time_stop_days)

        # Verdict
        if stop_already_hit:
            verdict, reason = "Should already be closed", f"Price touched your stop ({stop}) since entry."
        elif target_already_hit:
            verdict, reason = "Should already be closed", f"Price touched your target ({target}) since entry."
        elif not trend_ok:
            failed = [k for k, v in trend_conditions.items() if not v]
            verdict, reason = "Trend broken — consider exiting", f"No longer meets: {', '.join(failed)}."
        elif time_stop_flag:
            verdict, reason = "Time-stop reached", f"{days_held_calendar} days held with only {r_multiple:.2f}R progress — re-review the thesis."
        elif suggested_stop > stop:
            verdict, reason = "Hold, but raise your stop", f"Trail stop up to {round(suggested_stop, 2)} (was {stop})."
        else:
            verdict, reason = "Hold", "Trend still intact, no rule change triggered."

        return MonitorResult(
            symbol=symbol.upper(), current_price=round(current_price, 2), entry=entry, original_stop=stop,
            quantity=quantity, days_held=days_held_calendar, unrealized_pnl=round(unrealized_pnl, 2),
            r_multiple=round(r_multiple, 3), trend_conditions=trend_conditions, trend_intact=trend_ok,
            stop_already_hit=stop_already_hit, target_already_hit=target_already_hit,
            suggested_stop=round(suggested_stop, 2), time_stop_flag=time_stop_flag,
            verdict=verdict, verdict_reason=reason,
        )
