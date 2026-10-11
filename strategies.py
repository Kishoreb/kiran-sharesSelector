"""
Strategy Engine.

Each strategy implements one method: signal(df, i) -> Signal, looking ONLY
at df.iloc[:i+1] (today and earlier) so it can be used identically for live
screening (i = last row) and backtesting (walking i forward through history)
without any lookahead bias.

Stop placement is configurable on every strategy:
  stop_mode="structure"  (default) -- the strategy's own structural level
                          (swing low / EMA / breakout level)
  stop_mode="atr"        -- close - atr_mult x ATR(14)

Add a new strategy by subclassing Strategy and registering it in STRATEGIES
at the bottom of this file.
"""

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


@dataclass
class Signal:
    enter: bool
    entry: Optional[float] = None
    stop: Optional[float] = None
    reason: str = ""
    conditions: dict = None   # which sub-conditions were true, for transparency/scoring

    @property
    def score(self):
        if not self.conditions:
            return 0
        return sum(1 for v in self.conditions.values() if v)

    @property
    def total(self):
        return len(self.conditions) if self.conditions else 0


class Strategy:
    name = "base"
    min_bars_required = 55  # enough history for 50-EMA + lookback windows

    def __init__(self, stop_mode: str = "structure", atr_mult: float = 2.0):
        if stop_mode not in ("structure", "atr"):
            raise ValueError("stop_mode must be 'structure' or 'atr'")
        self.stop_mode = stop_mode
        self.atr_mult = atr_mult

    def _pick_stop(self, today: pd.Series, structure_levels: List[float]) -> Optional[float]:
        """
        structure mode: the tightest (highest) structural level that is
        below today's close. atr mode: close - atr_mult x ATR14.
        Returns None if no valid stop exists.
        """
        close = float(today["Close"])
        if self.stop_mode == "atr":
            atr = today["atr14"] if "atr14" in today.index else float("nan")
            if pd.notna(atr) and atr > 0:
                level = close - self.atr_mult * float(atr)
                return float(level) if level > 0 else None
            return None
        candidates = [float(l) for l in structure_levels if l < close]
        return max(candidates) if candidates else None

    def signal(self, df: pd.DataFrame, i: int) -> Signal:
        raise NotImplementedError

    def trend_intact(self, df: pd.DataFrame, i: int) -> dict:
        """
        Checks whether the THESIS behind an already-open position still
        holds — not whether today is a fresh entry trigger. Used by the
        position monitor, not by screening/backtesting entries.
        """
        raise NotImplementedError


class PullbackTrendStrategy(Strategy):
    """
    Trend-following pullback/reclaim, per the swing framework:
    price above rising 20/50 EMA, pulled back to the 20-EMA, reclaimed it
    on rising volume. Stop = tighter of recent swing low or the 50-EMA
    (or an ATR stop, if stop_mode="atr").

    The pullback is the run of consecutive closes at/below the 20-EMA that
    ends the day before the reclaim. It must last at least
    `min_pullback_days` (a one-day dip is noise) and at most
    `pullback_lookback` days (a longer stretch below the 20-EMA is a trend
    change, not a pullback). Set min_pullback_days=1 and a large
    pullback_lookback to get the old, looser behaviour.

    Note: volume confirmation is scored but is NOT required to enter.
    """
    name = "pullback_trend"

    def __init__(self, pullback_lookback: int = 10, min_pullback_days: int = 2, **kwargs):
        super().__init__(**kwargs)
        self.pullback_lookback = pullback_lookback
        self.min_pullback_days = min_pullback_days

    def _pullback_length(self, df: pd.DataFrame, i: int) -> int:
        """Consecutive closes at/below the 20-EMA ending at bar i-1 (looks back at most lookback+1 bars)."""
        n = 0
        j = i - 1
        while j >= 0 and n <= self.pullback_lookback and df["Close"].iloc[j] <= df["ema20"].iloc[j]:
            n += 1
            j -= 1
        return n

    def signal(self, df: pd.DataFrame, i: int) -> Signal:
        if i < self.min_bars_required:
            return Signal(enter=False, reason="not enough history", conditions={})

        today = df.iloc[i]
        yesterday = df.iloc[i - 1]

        price_above_20ema = bool(today["Close"] > today["ema20"])
        price_above_50ema = bool(today["Close"] > today["ema50"])
        ema50_now = df["ema50"].iloc[i]
        ema50_prior = df["ema50"].iloc[max(0, i - 20)]
        ema50_sloping_up = bool(ema50_now > ema50_prior)

        pullback_len = self._pullback_length(df, i)
        had_pullback = self.min_pullback_days <= pullback_len <= self.pullback_lookback
        reclaimed_today = bool(today["Close"] > today["ema20"] and yesterday["Close"] <= yesterday["ema20"])
        pullback_and_reclaim = had_pullback and reclaimed_today

        vol_confirmed = bool(today["Volume"] > today["vol_avg20"]) if pd.notna(today["vol_avg20"]) else False

        swing_low = df["Low"].iloc[max(0, i - 20):i + 1].min()
        stop = self._pick_stop(today, [swing_low, today["ema50"]])
        has_valid_stop = stop is not None

        conditions = {
            "price_above_20ema": price_above_20ema,
            "price_above_50ema": price_above_50ema,
            "ema50_sloping_up": ema50_sloping_up,
            "pullback_and_reclaim": pullback_and_reclaim,
            "volume_confirmed": vol_confirmed,
            "has_valid_stop": has_valid_stop,
        }

        enter = all([price_above_20ema, price_above_50ema, ema50_sloping_up, pullback_and_reclaim, has_valid_stop])
        return Signal(enter=enter, entry=float(today["Close"]) if enter else None,
                       stop=float(stop) if enter and has_valid_stop else None,
                       reason="pullback + reclaim of rising 20/50 EMA trend" if enter else "conditions not met",
                       conditions=conditions)

    def trend_intact(self, df: pd.DataFrame, i: int) -> dict:
        today = df.iloc[i]
        ema50_now = df["ema50"].iloc[i]
        ema50_prior = df["ema50"].iloc[max(0, i - 20)]
        return {
            "price_above_20ema": bool(today["Close"] > today["ema20"]),
            "price_above_50ema": bool(today["Close"] > today["ema50"]),
            "ema50_sloping_up": bool(ema50_now > ema50_prior),
        }


class BreakoutStrategy(Strategy):
    """
    Breaks out above its own recent range on strong volume, with the
    longer-term trend still up. Stop = the breakout level itself (the old
    resistance, now expected to act as support) or the 20-EMA, whichever
    is tighter (or an ATR stop, if stop_mode="atr").
    """
    name = "breakout"

    def __init__(self, breakout_lookback: int = 20, volume_multiple: float = 1.5, **kwargs):
        super().__init__(**kwargs)
        self.breakout_lookback = breakout_lookback
        self.volume_multiple = volume_multiple

    def signal(self, df: pd.DataFrame, i: int) -> Signal:
        if i < self.min_bars_required:
            return Signal(enter=False, reason="not enough history", conditions={})

        today = df.iloc[i]
        prior_high = df["High"].iloc[max(0, i - self.breakout_lookback):i].max()

        price_above_50ema = bool(today["Close"] > today["ema50"])
        ema50_now = df["ema50"].iloc[i]
        ema50_prior = df["ema50"].iloc[max(0, i - 20)]
        ema50_sloping_up = bool(ema50_now > ema50_prior)

        broke_out = bool(today["Close"] > prior_high)
        vol_avg = today["vol_avg20"]
        strong_volume = bool(pd.notna(vol_avg) and today["Volume"] > vol_avg * self.volume_multiple)

        closed_near_high = bool(today["Close"] >= today["Low"] + 0.7 * (today["High"] - today["Low"])) if today["High"] > today["Low"] else True

        stop = self._pick_stop(today, [prior_high * 0.98, today["ema20"]])
        has_valid_stop = stop is not None

        conditions = {
            "price_above_50ema": price_above_50ema,
            "ema50_sloping_up": ema50_sloping_up,
            "broke_above_recent_range": broke_out,
            "strong_volume": strong_volume,
            "closed_near_high": closed_near_high,
            "has_valid_stop": has_valid_stop,
        }

        enter = all([price_above_50ema, ema50_sloping_up, broke_out, strong_volume, has_valid_stop])
        return Signal(enter=enter, entry=float(today["Close"]) if enter else None,
                       stop=float(stop) if enter and has_valid_stop else None,
                       reason=f"broke {self.breakout_lookback}-day range on volume" if enter else "conditions not met",
                       conditions=conditions)

    def trend_intact(self, df: pd.DataFrame, i: int) -> dict:
        today = df.iloc[i]
        ema50_now = df["ema50"].iloc[i]
        ema50_prior = df["ema50"].iloc[max(0, i - 20)]
        return {
            "price_above_50ema": bool(today["Close"] > today["ema50"]),
            "ema50_sloping_up": bool(ema50_now > ema50_prior),
            "price_above_20ema": bool(today["Close"] > today["ema20"]),
        }


STRATEGIES = {
    "pullback_trend": PullbackTrendStrategy,
    "breakout": BreakoutStrategy,
}
