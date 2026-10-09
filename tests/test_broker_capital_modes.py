from __future__ import annotations

from typing import Any

from StockProject.engine.broker import Broker
from StockProject.engine.strategy_base import StrategyBase


class DummyStrategy(StrategyBase):
    def on_bar(self, date: Any, data_dict: Any) -> None:
        return None


def test_shared_mode_rejects_buy_when_cash_is_short() -> None:
    broker = Broker(initial_cash=100, fee_rate=0, tax_rate=0)

    assert broker.buy("2330", 101, 1, "2025-01-02") is False
    assert broker.cash == 100
    assert broker.positions == {}
    assert broker.cash_blocked_entry_count == 1


def test_per_stock_mode_isolates_cash_buckets() -> None:
    broker = Broker(initial_cash=200, fee_rate=0, tax_rate=0, capital_mode="per_stock", codes=["A", "B"])

    assert broker.buy("A", 100, 1, "2025-01-02") is True
    assert broker.cash_buckets["A"] == 0
    assert broker.cash_buckets["B"] == 100

    assert broker.buy("B", 100, 1, "2025-01-02") is True
    assert broker.buy("A", 1, 1, "2025-01-03") is False

    assert broker.sell("A", 100, 1, "2025-01-04") is True
    assert broker.cash_buckets["A"] == 100
    assert broker.buy("A", 100, 1, "2025-01-05") is True


def test_unconstrained_mode_allows_negative_cash() -> None:
    broker = Broker(initial_cash=0, fee_rate=0, tax_rate=0, capital_mode="unconstrained")

    assert broker.buy("2330", 100, 1, "2025-01-02") is True
    assert broker.cash == -100
    assert broker.positions["2330"] == 1
    assert broker.cash_blocked_entry_count == 0


def test_strategy_affordable_lot_uses_per_stock_bucket() -> None:
    broker = Broker(initial_cash=200, fee_rate=0, tax_rate=0, capital_mode="per_stock", codes=["A", "B"])
    strategy = DummyStrategy(broker)

    assert broker.buy("A", 100, 1, "2025-01-02") is True
    assert strategy.calculate_affordable_quantity(50, lot_size=1, code="A") == 0
    assert strategy.calculate_affordable_quantity(50, lot_size=1, code="B") == 2
    assert strategy.buy_affordable_lot("B", 50, "2025-01-03", lot_size=1) is True
    assert broker.positions["B"] == 2


def test_buy_affordable_lot_counts_zero_quantity_as_cash_blocked() -> None:
    broker = Broker(initial_cash=99, fee_rate=0, tax_rate=0)
    strategy = DummyStrategy(broker)

    assert strategy.buy_affordable_lot("2330", 100, "2025-01-02", lot_size=1) is False

    assert broker.cash_blocked_entry_count == 1


def test_unconstrained_affordable_lot_uses_one_lot_without_cash_gate() -> None:
    broker = Broker(initial_cash=0, fee_rate=0, tax_rate=0, capital_mode="unconstrained")
    strategy = DummyStrategy(broker)

    assert strategy.calculate_affordable_quantity(100, lot_size=10, code="2330") == 10
    assert strategy.buy_affordable_lot("2330", 100, "2025-01-02", lot_size=10) is True

    assert broker.positions["2330"] == 10
    assert broker.cash == -1000
    assert broker.cash_blocked_entry_count == 0
