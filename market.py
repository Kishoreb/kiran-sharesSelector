"""
Market context: the benchmark index (default Nifty 50, ^NSEI).

Provides two things, both strictly "as of" a given date so the backtester
never looks ahead:

  - Regime check: is the index closing above its N-day EMA? Both built-in
    strategies are trend-following, so they tend to do badly when the
    broad market is below its trend.
  - Relative strength: a stock's N-day return minus the index's N-day
    return (in percentage points). Used to rank candidates.
"""

import bisect
import math
from datetime import date
from typing import Optional

import pandas as pd


class Benchmark:
    def __init__(self, df: pd.DataFrame, regime_ema: int = 50):
        self.regime_ema = max(int(regime_ema), 0)
        self._dates = [ts.date() for ts in df.index]
        self._close = [float(x) for x in df["Close"].to_numpy()]
        if self.regime_ema > 0:
            ema = df["Close"].ewm(span=self.regime_ema, adjust=False).mean()
            self._bull = [bool(c > e) for c, e in zip(df["Close"], ema)]
        else:
            self._bull = None

    @property
    def last_date(self) -> Optional[date]:
        return self._dates[-1] if self._dates else None

    def _pos(self, d: date) -> int:
        return bisect.bisect_right(self._dates, d) - 1

    def close_asof(self, d: date) -> Optional[float]:
        p = self._pos(d)
        return self._close[p] if p >= 0 else None

    def is_bullish(self, d: date) -> Optional[bool]:
        """
        True/False if the index closed above/below its EMA on the latest
        bar on or before d. None = unknown (regime check off, date before
        the data starts, or still inside the EMA warm-up) -- callers treat
        None as "don't block".
        """
        if self._bull is None:
            return None
        p = self._pos(d)
        if p < 0 or p < self.regime_ema:
            return None
        return self._bull[p]

    def relative_strength(self, df: pd.DataFrame, i: int, lookback: int = 63) -> Optional[float]:
        """Stock return minus index return over `lookback` bars, in % points."""
        if i < lookback:
            return None
        b_now = self.close_asof(df.index[i].date())
        b_then = self.close_asof(df.index[i - lookback].date())
        s_now = float(df["Close"].iloc[i])
        s_then = float(df["Close"].iloc[i - lookback])
        if None in (b_now, b_then) or b_then <= 0 or s_then <= 0:
            return None
        rs = ((s_now / s_then) - (b_now / b_then)) * 100
        return round(rs, 2) if math.isfinite(rs) else None
