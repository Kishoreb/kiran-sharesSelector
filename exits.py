"""
Exit rules shared by the Position Monitor (live) and the Backtester, so the
backtest tests the same trailing/time-stop logic you actually follow.

Rules (from trading-rules.md):
  - Once price is up `activate_at_r` x initial risk, move the stop to breakeven.
  - From then on, trail the stop up to the most recent swing low (never
    lower than the current stop, and always below the current price).
  - Time-stop: held `time_stop_days`+ calendar days with less than `min_r`
    of progress -> flag for exit.
"""

from typing import Tuple

import pandas as pd


def suggest_stop(df: pd.DataFrame, i: int, entry: float, initial_stop: float,
                 current_stop: float, swing_low_lookback: int = 10,
                 activate_at_r: float = 1.0) -> Tuple[float, float]:
    """Returns (new_stop, r_multiple_at_bar_i). Uses only data up to and including bar i."""
    price = float(df["Close"].iloc[i])
    risk = entry - initial_stop
    r_multiple = (price - entry) / risk if risk > 0 else 0.0

    new_stop = current_stop
    if r_multiple >= activate_at_r:
        new_stop = max(new_stop, entry)
        swing_low = float(df["Low"].iloc[max(0, i - swing_low_lookback):i + 1].min())
        if new_stop < swing_low < price:
            new_stop = swing_low
    return float(new_stop), float(r_multiple)


def time_stop_hit(days_held_calendar: int, r_multiple: float,
                  time_stop_days: int = 14, min_r: float = 0.5) -> bool:
    return time_stop_days > 0 and days_held_calendar >= time_stop_days and r_multiple < min_r
