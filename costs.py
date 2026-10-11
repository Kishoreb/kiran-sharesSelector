"""
Transaction cost + slippage model for Indian equity DELIVERY trades
(swing holds of days/weeks, not intraday).

IMPORTANT: the defaults below are my best estimate of typical
discount-broker delivery charges. Regulatory rates change and brokers
differ (especially brokerage and the DP charge) -- check them against a
recent contract note from your own broker and edit the numbers here.

Slippage is applied as an adverse price move on market-type fills (entries,
stop exits, time-stop exits). Target exits are limit orders: no slippage.
"""

from dataclasses import dataclass


@dataclass
class CostModel:
    brokerage_pct: float = 0.0        # % of turnover per side (0 for most discount brokers on delivery)
    brokerage_flat: float = 0.0       # Rs per order
    stt_pct: float = 0.1              # delivery: charged on both buy and sell
    exchange_txn_pct: float = 0.00297 # NSE transaction charge
    sebi_pct: float = 0.0001
    stamp_duty_pct: float = 0.015     # buy side only
    gst_pct: float = 18.0             # on brokerage + exchange + SEBI charges
    dp_charge_per_sell: float = 15.34 # Rs per scrip sold, all-in; broker-specific
    slippage_pct: float = 0.10        # adverse move per market fill

    @classmethod
    def zero(cls) -> "CostModel":
        return cls(0, 0, 0, 0, 0, 0, 0, 0, 0)

    def _common(self, value: float) -> float:
        brokerage = value * self.brokerage_pct / 100 + self.brokerage_flat
        txn = value * self.exchange_txn_pct / 100
        sebi = value * self.sebi_pct / 100
        gst = (brokerage + txn + sebi) * self.gst_pct / 100
        return brokerage + txn + sebi + gst + value * self.stt_pct / 100

    def buy_cost(self, value: float) -> float:
        return self._common(value) + value * self.stamp_duty_pct / 100

    def sell_cost(self, value: float) -> float:
        return self._common(value) + self.dp_charge_per_sell

    def adjust_buy_price(self, price: float) -> float:
        return price * (1 + self.slippage_pct / 100)

    def adjust_sell_price(self, price: float) -> float:
        return price * (1 - self.slippage_pct / 100)
