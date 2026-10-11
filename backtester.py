"""
Backtester.

Walks multiple symbols forward day by day, simulating what a trader
following the given Strategy + RiskEngine rules would have actually done.
No lookahead -- a signal on day i only ever uses data from day i and earlier.

How a day is processed (in this order):
  1. Time-stop exits flagged yesterday are executed at today's OPEN.
  2. Entry orders from yesterday's close signals are filled at today's OPEN
     (best-ranked first). Size and the heat / max-position checks are done
     at fill time with the real fill price, against current EQUITY (cash +
     open positions marked at the last close), not against free cash.
  3. Stops / targets are checked against today's bar. Gap-aware: if the day
     OPENS through the stop you exit at the open, not at the stop price. If
     both stop and target fall inside the day's range, the stop is assumed
     to hit first.
  4. At the close, stops are trailed (breakeven at +1R, then below the
     latest swing low -- same code as the Position Monitor) and the
     time-stop is evaluated for tomorrow.
  5. New signals are generated from the close. If a point-in-time membership
     history is supplied, signals on stocks that were not in the index that
     day are dropped. They then go through the regime filter and the pre-trade filters (liquidity, stop width, results
     calendar) and queued for tomorrow's open.

Costs: statutory charges + slippage from costs.CostModel are deducted
(pass CostModel.zero() to switch them off).

Still simplified (see README): survivorship bias (index list is TODAY's
constituents), no circuit-limit / liquidity-fill modelling, daily bars only.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from strategies import Strategy
from risk import RiskEngine, OpenPosition
from costs import CostModel
from filters import TradeFilters, ResultsCalendar
from market import Benchmark
from membership import MembershipHistory
from exits import suggest_stop, time_stop_hit


@dataclass
class Trade:
    symbol: str
    strategy: str
    entry_date: str
    entry_price: float      # actual fill, after slippage
    exit_date: str
    exit_price: float       # actual fill, after slippage (targets: limit price)
    stop: float             # INITIAL stop -- the basis for R-multiples
    target: float
    quantity: int
    exit_reason: str        # "stop", "trailing_stop", "target", "time_stop", "end_of_backtest"
    fees: float = 0.0       # all statutory charges, buy + sell
    entry_equity: float = 0.0  # portfolio equity when the position was opened (for Monte Carlo)

    @property
    def pnl_rupees(self) -> float:
        """Net P&L after fees (slippage is already inside entry/exit price)."""
        return round((self.exit_price - self.entry_price) * self.quantity - self.fees, 2)

    @property
    def r_multiple(self) -> float:
        risk_total = (self.entry_price - self.stop) * self.quantity
        if risk_total <= 0:
            return 0.0
        return round(self.pnl_rupees / risk_total, 3)


@dataclass
class BacktestResult:
    trades: List[Trade]
    equity_curve: List[dict]  # [{"date": ..., "equity": ...}, ...]
    initial_capital: float
    final_equity: float
    skips: Dict[str, int] = field(default_factory=dict)  # reason -> signals not traded

    def metrics(self) -> dict:
        n = len(self.trades)
        skips = dict(sorted(self.skips.items(), key=lambda kv: -kv[1]))
        if n == 0:
            return {"total_trades": 0, "note": "no trades were generated over this period",
                    "signals_skipped": skips}

        wins = [t for t in self.trades if t.pnl_rupees > 0]
        losses = [t for t in self.trades if t.pnl_rupees <= 0]
        gross_profit = sum(t.pnl_rupees for t in wins)
        gross_loss = abs(sum(t.pnl_rupees for t in losses))
        win_rate = len(wins) / n * 100
        avg_win = (gross_profit / len(wins)) if wins else 0
        avg_loss = (gross_loss / len(losses)) if losses else 0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0
        expectancy = sum(t.pnl_rupees for t in self.trades) / n
        avg_r = sum(t.r_multiple for t in self.trades) / n

        equity_values = [pt["equity"] for pt in self.equity_curve]
        peak = equity_values[0] if equity_values else self.initial_capital
        max_dd = 0.0
        for v in equity_values:
            peak = max(peak, v)
            dd = (peak - v) / peak * 100 if peak else 0
            max_dd = max(max_dd, dd)

        total_return_pct = (self.final_equity - self.initial_capital) / self.initial_capital * 100
        days = 0
        if len(self.equity_curve) >= 2:
            d0 = pd.Timestamp(self.equity_curve[0]["date"])
            d1 = pd.Timestamp(self.equity_curve[-1]["date"])
            days = max((d1 - d0).days, 1)
        years = days / 365 if days else 0
        cagr_pct = ((self.final_equity / self.initial_capital) ** (1 / years) - 1) * 100 if years > 0 and self.initial_capital > 0 else 0

        exit_reasons: Dict[str, int] = {}
        for t in self.trades:
            exit_reasons[t.exit_reason] = exit_reasons.get(t.exit_reason, 0) + 1

        return {
            "total_trades": n,
            "win_rate_pct": round(win_rate, 1),
            "avg_win_rupees": round(avg_win, 2),
            "avg_loss_rupees": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf (no losing trades)",
            "expectancy_rupees_per_trade": round(expectancy, 2),
            "avg_r_multiple": round(avg_r, 3),
            "max_drawdown_pct": round(max_dd, 2),
            "total_return_pct": round(total_return_pct, 2),
            "cagr_pct": round(cagr_pct, 2) if years > 0 else "n/a (period too short)",
            "final_equity": round(self.final_equity, 2),
            "total_fees_rupees": round(sum(t.fees for t in self.trades), 2),
            "exit_reasons": exit_reasons,
            "signals_skipped": skips,
        }


def _build_date_index(symbol_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict[pd.Timestamp, int]]:
    """For each symbol, map normalized date -> integer row position."""
    out = {}
    for sym, df in symbol_data.items():
        out[sym] = {ts.normalize(): pos for pos, ts in enumerate(df.index)}
    return out


class Backtester:
    def __init__(self, strategy: Strategy, risk_engine: RiskEngine, initial_capital: float,
                 cost_model: Optional[CostModel] = None,
                 filters: Optional[TradeFilters] = None,
                 benchmark: Optional[Benchmark] = None,
                 regime_filter: bool = False,
                 results_calendar: Optional[ResultsCalendar] = None,
                 use_trailing: bool = True,
                 time_stop_days: int = 14,
                 swing_low_lookback: int = 10,
                 membership: Optional[MembershipHistory] = None):
        self.strategy = strategy
        self.risk_engine = risk_engine
        self.initial_capital = initial_capital
        self.cost_model = cost_model if cost_model is not None else CostModel()
        self.filters = filters if filters is not None else TradeFilters(0, 0, 0)
        self.benchmark = benchmark
        self.regime_filter = regime_filter
        self.results_calendar = results_calendar
        self.use_trailing = use_trailing
        self.time_stop_days = time_stop_days
        self.swing_low_lookback = swing_low_lookback
        self.membership = membership

    def run(self, symbol_data: Dict[str, pd.DataFrame], progress: bool = True) -> BacktestResult:
        cm = self.cost_model
        rk = self.risk_engine
        date_index = _build_date_index(symbol_data)
        all_dates = sorted(set().union(*[set(d.keys()) for d in date_index.values()])) if date_index else []
        arrays = {
            sym: {k: df[c].to_numpy(dtype=float)
                  for k, c in (("open", "Open"), ("high", "High"), ("low", "Low"), ("close", "Close"))}
            for sym, df in symbol_data.items()
        }

        cash = self.initial_capital
        open_positions: Dict[str, dict] = {}
        closed_trades: List[Trade] = []
        equity_curve = []
        last_close: Dict[str, float] = {}
        pending_entries: List[dict] = []
        pending_exits: Dict[str, str] = {}
        skips: Dict[str, int] = defaultdict(int)

        def equity_now() -> float:
            return cash + sum(p["qty"] * last_close.get(s, p["entry"]) for s, p in open_positions.items())

        def open_list() -> List[OpenPosition]:
            return [OpenPosition(symbol=s, entry=p["entry"], stop=p["stop"], quantity=p["qty"])
                    for s, p in open_positions.items()]

        def finish(sym: str, raw_price: float, reason: str, exit_date, market_order: bool):
            nonlocal cash
            pos = open_positions.pop(sym)
            fill = cm.adjust_sell_price(raw_price) if market_order else raw_price
            value = fill * pos["qty"]
            sell_cost = cm.sell_cost(value)
            cash += value - sell_cost
            closed_trades.append(Trade(
                symbol=sym, strategy=self.strategy.name,
                entry_date=str(pos["entry_date"]), entry_price=pos["entry"],
                exit_date=str(exit_date), exit_price=fill,
                stop=pos["initial_stop"], target=pos["target"], quantity=pos["qty"],
                exit_reason=reason, fees=pos["buy_cost"] + sell_cost,
                entry_equity=pos["entry_equity"],
            ))

        def rank_key(order: dict):
            rs = order["rs"] if order["rs"] is not None else float("-inf")
            return (order["score"], rs, -order["stop_pct"])

        for n_day, date in enumerate(all_dates):
            d = date.date()

            # 1. Time-stop exits flagged at yesterday's close -> today's open
            for sym in list(pending_exits):
                if sym not in open_positions:
                    del pending_exits[sym]
                    continue
                if date not in date_index[sym]:
                    continue
                i = date_index[sym][date]
                finish(sym, arrays[sym]["open"][i], pending_exits.pop(sym), d, market_order=True)

            # 2. Fill yesterday's entry orders at today's open, best-ranked first
            if pending_entries:
                for order in sorted(pending_entries, key=rank_key, reverse=True):
                    sym = order["symbol"]
                    if sym in open_positions:
                        continue
                    if date not in date_index[sym]:
                        skips["no_bar_to_fill"] += 1   # day order lapses
                        continue
                    i = date_index[sym][date]
                    stop = order["stop"]
                    fill = cm.adjust_buy_price(arrays[sym]["open"][i])
                    if fill <= stop:
                        skips["gap_below_stop"] += 1
                        continue
                    if len(open_positions) >= rk.max_concurrent_positions:
                        skips["max_positions"] += 1
                        continue
                    equity = equity_now()
                    size = rk.position_size(fill, stop, available_capital=equity, capital_limit=cash)
                    qty = size.quantity
                    while qty > 0 and qty * fill + cm.buy_cost(qty * fill) > cash:
                        qty -= 1
                    if qty <= 0:
                        skips["zero_size_or_no_cash"] += 1
                        continue
                    if rk.undersized(qty * (fill - stop), equity):
                        skips["undersized"] += 1
                        continue
                    if not rk.can_add_position(open_list(), fill, stop, qty, capital=equity):
                        skips["heat_ceiling"] += 1
                        continue
                    buy_cost = cm.buy_cost(qty * fill)
                    cash -= qty * fill + buy_cost
                    open_positions[sym] = {
                        "entry": fill, "stop": stop, "initial_stop": stop,
                        "target": rk.target_price(fill, stop),
                        "qty": qty, "entry_date": d, "buy_cost": buy_cost,
                        "entry_equity": equity,
                    }
                pending_entries = []

            # 3. Stop / target checks against today's bar (gap-aware, stop first)
            for sym in list(open_positions):
                if date not in date_index[sym]:
                    continue
                pos = open_positions[sym]
                i = date_index[sym][date]
                o, h, l = arrays[sym]["open"][i], arrays[sym]["high"][i], arrays[sym]["low"][i]
                stop_reason = "trailing_stop" if pos["stop"] > pos["initial_stop"] else "stop"
                if o <= pos["stop"]:
                    finish(sym, o, stop_reason, d, market_order=True)
                elif o >= pos["target"]:
                    finish(sym, o, "target", d, market_order=False)
                elif l <= pos["stop"]:
                    finish(sym, pos["stop"], stop_reason, d, market_order=True)
                elif h >= pos["target"]:
                    finish(sym, pos["target"], "target", d, market_order=False)

            # Latest close per symbol (used for equity and the MTM curve)
            for sym, dm in date_index.items():
                if date in dm:
                    last_close[sym] = float(arrays[sym]["close"][dm[date]])

            # 4. At the close: trail stops, evaluate the time-stop for tomorrow
            for sym in list(open_positions):
                if date not in date_index[sym]:
                    continue
                pos = open_positions[sym]
                i = date_index[sym][date]
                df = symbol_data[sym]
                if self.use_trailing:
                    pos["stop"], r_mult = suggest_stop(df, i, pos["entry"], pos["initial_stop"],
                                                       pos["stop"], self.swing_low_lookback)
                else:
                    risk = pos["entry"] - pos["initial_stop"]
                    r_mult = (last_close[sym] - pos["entry"]) / risk if risk > 0 else 0.0
                if sym not in pending_exits and time_stop_hit(
                        (d - pos["entry_date"]).days, r_mult, self.time_stop_days):
                    pending_exits[sym] = "time_stop"

            # 5. New signals from today's close -> orders for tomorrow's open
            regime_ok = True
            if self.regime_filter and self.benchmark is not None:
                regime_ok = self.benchmark.is_bullish(d) is not False
            for sym, dm in date_index.items():
                if date not in dm or sym in open_positions:
                    continue
                i = dm[date]
                df = symbol_data[sym]
                sig = self.strategy.signal(df, i)
                if not sig.enter:
                    continue
                if self.membership is not None and not self.membership.is_member(sym, d):
                    skips["not_in_index"] += 1      # signal on a stock that wasn't in the index that day
                    continue
                if not regime_ok:
                    skips["regime"] += 1
                    continue
                reason = self.filters.check(df, i, sig.entry, sig.stop, symbol=sym,
                                            calendar=self.results_calendar)
                if reason:
                    skips[reason] += 1
                    continue
                pending_entries.append({
                    "symbol": sym, "stop": sig.stop, "score": sig.score,
                    "stop_pct": (sig.entry - sig.stop) / sig.entry * 100,
                    "rs": self.benchmark.relative_strength(df, i) if self.benchmark is not None else None,
                })

            # 6. Mark-to-market equity for the drawdown curve
            mtm = equity_now()
            equity_curve.append({"date": str(d), "equity": round(mtm, 2)})

            if progress and n_day % 60 == 0:
                print(f"  ...{d}  equity {mtm:,.0f}  open {len(open_positions)}  closed {len(closed_trades)}")

        # Close anything still open at the last available price
        for sym in list(open_positions):
            last_i = max(date_index[sym].values())
            finish(sym, arrays[sym]["close"][last_i], "end_of_backtest",
                   symbol_data[sym].index[last_i].date(), market_order=True)

        return BacktestResult(trades=closed_trades, equity_curve=equity_curve,
                               initial_capital=self.initial_capital, final_equity=cash,
                               skips=dict(skips))
