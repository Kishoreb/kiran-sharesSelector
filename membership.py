"""
Point-in-time index membership, to cut survivorship bias.

`universe.py` only knows TODAY's constituents, so a backtest quietly skips
every stock that was dropped from the index (often because it did badly) and
includes stocks that only entered after their big run. This module
reconstructs "who was in the index on date D" by taking today's list and
UNDOING the index changes you give it, newest first.

You supply the changes as a CSV (one file per index):

    # date,symbol,action
    2025-03-28,SOMECO,ADD
    2025-03-28,OLDCO,REMOVE

  - date   = EFFECTIVE date: the first trading day the change applies.
             NSE press releases say e.g. "effective from September 30, 2026
             (close of September 29, 2026)" -> use 2026-09-30.
  - symbol = NSE ticker (press releases list company names; look up the ticker).
  - action = ADD (member from this date on) or REMOVE (not a member from this
             date on). IN / OUT are accepted too.

Source: NSE Indices publishes "Replacements in indices" press releases at
niftyindices.com (Press_Release/ind_prsDDMMYYYY.pdf), normally effective the
last working day of March and September. `snapshot-changes` can also build
this file going forward from dated constituent snapshots that `universe.py`
now saves each time it downloads a list.

What this does NOT fix (the backtester reports it per run):
  - Price data. Yahoo often has no data for delisted, merged or renamed
    tickers, so a former member may be impossible to backtest. Those are
    listed as "members without price data"; survivorship bias is reduced,
    not eliminated, and the result is still biased in the optimistic direction.
  - Corporate actions that change tickers: use the ticker Yahoo knows.
"""

import csv
from bisect import bisect_right
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Set, Tuple

ACTIONS = {"ADD": "ADD", "IN": "ADD", "REMOVE": "REMOVE", "OUT": "REMOVE"}


def _norm(sym: str) -> str:
    s = sym.strip().upper()
    for suffix in (".NS", ".BO"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def _parse_date(text: str) -> Optional[date]:
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def read_changes(path: str) -> List[Tuple[date, str, str]]:
    """Returns [(effective_date, symbol, 'ADD'|'REMOVE')]. Raises ValueError naming the bad line."""
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for lineno, row in enumerate(csv.reader(f), 1):
            if not row or not row[0].strip() or row[0].strip().startswith("#"):
                continue
            if row[0].strip().lower() == "date":
                continue
            if len(row) < 3:
                raise ValueError(f"line {lineno}: expected date,symbol,action")
            d = _parse_date(row[0])
            action = ACTIONS.get(row[2].strip().upper())
            if d is None:
                raise ValueError(f"line {lineno}: can't read date '{row[0]}'")
            if action is None:
                raise ValueError(f"line {lineno}: action must be ADD or REMOVE, got '{row[2]}'")
            out.append((d, _norm(row[1]), action))
    return out


class MembershipHistory:
    def __init__(self, current: Iterable[str], changes: List[Tuple[date, str, str]]):
        self.current: Set[str] = {_norm(s) for s in current}
        self.changes = sorted(changes)
        self._events: Dict[str, List[Tuple[date, str]]] = {}
        for d, sym, action in self.changes:
            self._events.setdefault(sym, []).append((d, action))
        self._event_dates = {s: [d for d, _ in ev] for s, ev in self._events.items()}
        self.warnings: List[str] = []
        self._check_consistency()

    @classmethod
    def from_file(cls, current: Iterable[str], path: str) -> "MembershipHistory":
        return cls(current, read_changes(path))

    # -- state before the first event is the opposite of what that event does
    def _initial_state(self, sym: str) -> bool:
        return self._events[sym][0][1] == "REMOVE"

    def _check_consistency(self):
        for sym, events in self._events.items():
            state = self._initial_state(sym)
            for d, action in events:
                new_state = action == "ADD"
                if new_state == state:
                    self.warnings.append(f"{sym}: {action} on {d} but it was already "
                                         f"{'a member' if state else 'not a member'} (duplicate or missing change?)")
                state = new_state
            if state != (sym in self.current):
                self.warnings.append(
                    f"{sym}: changes leave it {'in' if state else 'out of'} the index, but today's list "
                    f"{'has' if sym in self.current else 'does not have'} it (a change is missing or mistyped)")

    def is_member(self, symbol: str, d: date) -> bool:
        sym = _norm(symbol)
        events = self._events.get(sym)
        if not events:
            return sym in self.current
        n = bisect_right(self._event_dates[sym], d)       # events with effective date <= d
        if n == 0:
            return self._initial_state(sym)
        return events[n - 1][1] == "ADD"

    def symbols_since(self, start: date) -> Set[str]:
        """Every symbol that was a member on `start` or joined afterwards (i.e. everything worth downloading)."""
        out = set(self.current)
        for sym, events in self._events.items():
            if self.is_member(sym, start) or any(a == "ADD" and d > start for d, a in events):
                out.add(sym)
        return out

    def missing_data(self, have: Iterable[str], start: date) -> List[str]:
        """Symbols that were index members at some point since `start` but have no price data."""
        have_set = {_norm(s) for s in have}
        return sorted(self.symbols_since(start) - have_set)


def merge_changes_file(path: str, new_changes: List[Tuple[date, str, str]]) -> int:
    """Append changes not already in the file (creating it with a header if needed). Returns rows added."""
    try:
        existing = set(read_changes(path))
        fresh = not existing
    except FileNotFoundError:
        existing, fresh = set(), True
    to_add = sorted(set(new_changes) - existing)
    if not to_add:
        return 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        if fresh:
            f.write("# date,symbol,action  (effective date = first day the change applies)\n")
        w = csv.writer(f)
        for d, sym, action in to_add:
            w.writerow([d.isoformat(), sym, action])
    return len(to_add)


def period_start(period: str, today: Optional[date] = None) -> date:
    """yfinance-style period ('5y', '6mo', '90d', 'max') -> approximate start date."""
    today = today or date.today()
    p = period.strip().lower()
    try:
        if p.endswith("mo"):
            days = int(p[:-2]) * 31
        elif p.endswith("y"):
            days = int(p[:-1]) * 366
        elif p.endswith("d"):
            days = int(p[:-1])
        else:
            return date(1990, 1, 1)
    except ValueError:
        return date(1990, 1, 1)
    from datetime import timedelta
    return today - timedelta(days=days)
