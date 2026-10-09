from abc import ABC, abstractmethod
from typing import Any


class StrategyBase(ABC):
    """
    Base class for strategy candidates.

    All generated strategies must inherit this class and implement on_bar.
    """

    def __init__(self, broker: Any, context: Any = None):
        self.broker = broker
        self.context = context or {}

    @abstractmethod
    def on_bar(self, date: Any, data_dict: Any):
        """
        Daily decision point.

        date: current date.
        data_dict: { 'code': dataframe_slice }.
        """
        pass

    def calculate_affordable_quantity(self, price: float, lot_size: Any = 1000, code: str | None = None) -> int:
        """Return the largest lot-sized quantity affordable with current cash."""
        if price <= 0:
            return 0
        if getattr(self.broker, "capital_mode", None) == "unconstrained":
            return int(lot_size)
        total_per_share = price * (1 + self.broker.fee_rate)
        cash = self.broker._available(code) if code and getattr(self.broker, "capital_mode", None) == "per_stock" else self.broker.cash
        lots = int(cash // (total_per_share * lot_size))
        return lots * lot_size

    def buy_affordable_lot(self, code: str, price: float, date: Any, lot_size: Any = 1000) -> bool:
        """Buy the largest affordable lot-sized quantity."""
        qty = self.calculate_affordable_quantity(price, lot_size=lot_size, code=code)
        if qty <= 0:
            if hasattr(self.broker, "cash_blocked_entry_count") and getattr(self.broker, "capital_mode", None) != "unconstrained":
                self.broker.cash_blocked_entry_count += 1
            return False
        return self.broker.buy(code, price, qty, date)
