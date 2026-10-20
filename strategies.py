"""
Strategy Engine.

Each strategy implements one method: signal(df, i) -> Signal, looking ONLY
at df.iloc[:i+1] (today and earlier) so it can be used identically for live
screening (i = last row) and backtesting (walking i forward through history)
without any lookahead bias.

Every strategy takes two stop options:
  stop_mode = "structure"  stop at a chart level below price (strategy specific)
  stop_mode = "atr"        stop = close - atr_mult x ATR(14)
atr_mult is ignored in structure mode.

Add a new strategy by subclassing Strategy and registering it in STRATEGIES
at the bottom of this file.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

STOP_MODES = ("structure", "atr")


@dataclass
class TechnicalFilters:
    """
    Extra gates from the shortlisting doc (section 3), applied on top of
    each strategy's own conditions. Each enabled filter adds one named
    condition to the Signal (so it shows in score/total) AND must be true
    for the entry to fire. Set a value to 0 / False to disable it.
    Missing data (e.g. fewer than 200 bars) counts as NOT passing.
    """
    min_avg_value_cr: float = 1.0          # 20-day avg daily traded value floor, Rs crore
    require_above_sma200: bool = True      # close > 200-day SMA
    max_pct_from_52w_high: float = 20.0    # close within this % of the 52-week high

    def conditions(self, df: pd.DataFrame, i: int) -> dict:
        row = df.iloc[i]
        out = {}
        if self.min_avg_value_cr and self.min_avg_value_cr > 0:
            v = row.get("avg_value20")
            out["liquidity_ok"] = bool(pd.notna(v) and v >= self.min_avg_value_cr * 1e7)
        if self.require_above_sma200:
            sma = row.get("sma200")
            out["above_sma200"] = bool(pd.notna(sma) and row["Close"] > sma)
        if self.max_pct_from_52w_high and self.max_pct_from_52w_high > 0:
            hi = row.get("high_252")
            out["near_52w_high"] = bool(pd.notna(hi) and row["Close"] >= hi * (1 - self.max_pct_from_52w_high / 100))
        return out


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


def atr(df: pd.DataFrame, i: int, n: int = 14) -> float:
    """Average true range over the n bars ending at bar i (uses only bars <= i). NaN if too little data."""
    lo = max(1, i - n + 1)
    if i < 1 or lo > i:
        return float("nan")
    high = df["High"].to_numpy(dtype=float)[lo:i + 1]
    low = df["Low"].to_numpy(dtype=float)[lo:i + 1]
    prev = df["Close"].to_numpy(dtype=float)[lo - 1:i]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    return float(tr.mean()) if len(tr) else float("nan")


class Strategy:
    name = "base"
    min_bars_required = 55  # enough history for 50-EMA + lookback windows

    def __init__(self, stop_mode: str = "structure", atr_mult: float = 2.0,
                 filters: Optional[TechnicalFilters] = None):
        if stop_mode not in STOP_MODES:
            raise ValueError(f"stop_mode must be one of {STOP_MODES}, got '{stop_mode}'")
        self.stop_mode = stop_mode
        self.atr_mult = atr_mult
        self.filters = filters

    def _filter_conditions(self, df: pd.DataFrame, i: int) -> dict:
        return self.filters.conditions(df, i) if self.filters else {}

    def _stop(self, df: pd.DataFrame, i: int, structure_levels) -> Optional[float]:
        """The stop for an entry at today's close, or None if no valid stop (must be > 0 and < close)."""
        close = float(df["Close"].iloc[i])
        if self.stop_mode == "atr":
            a = atr(df, i)
            if not np.isfinite(a) or a <= 0:
                return None
            s = close - self.atr_mult * a
            return float(s) if 0 < s < close else None
        cands = [float(l) for l in structure_levels if l < close]
        return max(cands) if cands else None

    def signal(self, df: pd.DataFrame, i: int) -> Signal:
        raise NotImplementedError

    def trend_intact(self, df: pd.DataFrame, i: int) -> dict:
        """
        Checks whether the THESIS behind an already-open position still
        holds, not whether today is a fresh entry trigger. Used by the
        position monitor, not by screening/backtesting entries.
        """
        raise NotImplementedError


class PullbackTrendStrategy(Strategy):
    """
    Trend-following pullback/reclaim, per the swing framework:
    price above rising 20/50 EMA, pulled back to the 20-EMA, reclaimed it
    on rising volume.

    Pullback length = the run of consecutive closes at/below the 20-EMA that
    ends the day before the reclaim. It must be at least `min_pullback_days`
    (a one-day dip is noise) and at most `pullback_lookback` (a longer slide
    is a broken trend, not a pullback).

    Structure stop = tighter of the 20-day swing low or the 50-EMA.
    """
    name = "pullback_trend"

    def __init__(self, pullback_lookback: int = 10, min_pullback_days: int = 2,
                 stop_mode: str = "structure", atr_mult: float = 2.0,
                 filters: Optional[TechnicalFilters] = None):
        super().__init__(stop_mode=stop_mode, atr_mult=atr_mult, filters=filters)
        self.pullback_lookback = pullback_lookback
        self.min_pullback_days = min_pullback_days

    def pullback_run(self, df: pd.DataFrame, i: int) -> int:
        """Consecutive closes at/below the 20-EMA ending at bar i-1; counted up to pullback_lookback + 1."""
        lo = max(0, i - self.pullback_lookback - 1)
        close = df["Close"].to_numpy(dtype=float)[lo:i]
        ema = df["ema20"].to_numpy(dtype=float)[lo:i]
        run = 0
        for c, e in zip(close[::-1], ema[::-1]):
            if c <= e:
                run += 1
            else:
                break
        return run

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

        reclaimed_today = bool(today["Close"] > today["ema20"] and yesterday["Close"] <= yesterday["ema20"])
        run = self.pullback_run(df, i)
        pullback_and_reclaim = reclaimed_today and self.min_pullback_days <= run <= self.pullback_lookback

        vol_confirmed = bool(today["Volume"] > today["vol_avg20"]) if pd.notna(today["vol_avg20"]) else False

        swing_low = df["Low"].iloc[max(0, i - 20):i + 1].min()
        stop = self._stop(df, i, [swing_low, today["ema50"]])
        has_valid_stop = stop is not None

        conditions = {
            "price_above_20ema": price_above_20ema,
            "price_above_50ema": price_above_50ema,
            "ema50_sloping_up": ema50_sloping_up,
            "pullback_and_reclaim": pullback_and_reclaim,
            "volume_confirmed": vol_confirmed,
            "has_valid_stop": has_valid_stop,
        }
        extra = self._filter_conditions(df, i)
        conditions.update(extra)

        enter = all([price_above_20ema, price_above_50ema, ema50_sloping_up, pullback_and_reclaim,
                     has_valid_stop]) and all(extra.values())
        return Signal(enter=enter, entry=float(today["Close"]) if enter else None,
                      stop=stop if enter else None,
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
    longer-term trend still up. Structure stop = just below the breakout
    level (old resistance, now expected to act as support) or the 20-EMA,
    whichever is tighter.
    """
    name = "breakout"

    def __init__(self, breakout_lookback: int = 20, volume_multiple: float = 1.5,
                 stop_mode: str = "structure", atr_mult: float = 2.0,
                 filters: Optional[TechnicalFilters] = None):
        super().__init__(stop_mode=stop_mode, atr_mult=atr_mult, filters=filters)
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

        closed_near_high = (bool(today["Close"] >= today["Low"] + 0.7 * (today["High"] - today["Low"]))
                            if today["High"] > today["Low"] else True)

        stop = self._stop(df, i, [prior_high * 0.98, today["ema20"]])
        has_valid_stop = stop is not None

        conditions = {
            "price_above_50ema": price_above_50ema,
            "ema50_sloping_up": ema50_sloping_up,
            "broke_above_recent_range": broke_out,
            "strong_volume": strong_volume,
            "closed_near_high": closed_near_high,
            "has_valid_stop": has_valid_stop,
        }
        extra = self._filter_conditions(df, i)
        conditions.update(extra)

        enter = all([price_above_50ema, ema50_sloping_up, broke_out, strong_volume, has_valid_stop]) and all(extra.values())
        return Signal(enter=enter, entry=float(today["Close"]) if enter else None,
                      stop=stop if enter else None,
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
