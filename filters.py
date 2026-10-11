"""
Pre-trade filters applied on top of a strategy's raw signal.

  - Liquidity: minimum 20-day average traded value (Close x Volume).
  - Stop width: reject setups whose stop is too far from entry (wide stops
    mean tiny position sizes and poor structure).
  - Results calendar: skip entries when a quarterly result is due within N
    days. Yahoo's earnings dates for NSE stocks are unreliable, so this
    uses a file YOU maintain (see ResultsCalendar).

check() returns None if the setup passes, otherwise a short reason key.
"""

import csv
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional

REASON_LABELS = {
    "regime": "market below its trend (regime filter)",
    "liquidity": "average traded value below minimum",
    "stop_too_wide": "stop wider than max allowed",
    "results_soon": "results due within the buffer window",
    "undersized": "capital-limited to under the minimum share of your intended risk",
    "zero_quantity": "position size rounds to zero for your capital/risk",
}


def _norm_symbol(sym: str) -> str:
    s = sym.strip().upper()
    for suffix in (".NS", ".BO"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def _parse_date(text: str) -> Optional[date]:
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class ResultsCalendar:
    """
    Plain CSV/text file, one result date per line:

        # symbol,date
        RELIANCE,2026-10-17
        INFY,2026-10-15

    Dates as YYYY-MM-DD (DD-MM-YYYY and DD/MM/YYYY also accepted). A symbol
    can appear on several lines. Lines starting with '#' and a header row
    are ignored; anything else unparseable is counted in `skipped_rows`.
    """

    def __init__(self, entries: Optional[Dict[str, List[date]]] = None, skipped_rows: int = 0):
        self._entries = {k: sorted(v) for k, v in (entries or {}).items()}
        self.skipped_rows = skipped_rows

    @classmethod
    def from_file(cls, path: str) -> "ResultsCalendar":
        entries: Dict[str, List[date]] = {}
        skipped = 0
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if not row or not row[0].strip() or row[0].strip().startswith("#"):
                    continue
                if row[0].strip().lower() == "symbol":
                    continue
                d = _parse_date(row[1]) if len(row) > 1 else None
                if d is None:
                    skipped += 1
                    continue
                entries.setdefault(_norm_symbol(row[0]), []).append(d)
        return cls(entries, skipped)

    def days_to_next(self, symbol: str, d: date) -> Optional[int]:
        """Calendar days from d to the next result date on/after d, or None."""
        for rd in self._entries.get(_norm_symbol(symbol), []):
            if rd >= d:
                return (rd - d).days
        return None


@dataclass
class TradeFilters:
    min_traded_value_cr: float = 5.0   # Rs crore, 20-day avg traded value; 0 disables
    max_stop_pct: float = 8.0          # max (entry - stop) / entry in %; 0 disables
    results_buffer_days: int = 14      # skip if results within this many days; 0 disables

    def check(self, df, i: int, entry: float, stop: float, symbol: str = "",
              calendar: Optional[ResultsCalendar] = None) -> Optional[str]:
        if self.min_traded_value_cr > 0:
            tv = float(df["traded_value20"].iloc[i]) if "traded_value20" in df.columns else float("nan")
            if math.isnan(tv) or tv / 1e7 < self.min_traded_value_cr:
                return "liquidity"

        if self.max_stop_pct > 0 and entry > 0:
            stop_pct = (entry - stop) / entry * 100
            if stop_pct > self.max_stop_pct:
                return "stop_too_wide"

        if calendar is not None and self.results_buffer_days > 0:
            n = calendar.days_to_next(symbol, df.index[i].date())
            if n is not None and n <= self.results_buffer_days:
                return "results_soon"

        return None
