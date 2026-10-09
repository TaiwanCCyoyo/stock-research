from __future__ import annotations

import logging
from typing import Any

_VALID_CAPITAL_MODES = ("shared", "per_stock", "unconstrained")


class Broker:
    """Taiwan stock broker simulator with fees and transaction tax.

    capital_mode controls how cash is allocated across symbols:
      "shared"        -- one pool for all symbols (default, preserves existing behaviour)
      "per_stock"     -- each symbol gets an equal slice of initial_cash; cash flows
                         are isolated per symbol so one stock cannot starve another
      "unconstrained" -- no cash gate; buys always succeed even if cash goes negative
                         (diagnostic mode for comparing signal quality in isolation)
    """

    def __init__(
        self,
        initial_cash: float = 1000000,
        fee_rate: float = 0.001425,
        tax_rate: float = 0.003,
        capital_mode: str = "shared",
        codes: list[str] | None = None,
    ):
        if capital_mode not in _VALID_CAPITAL_MODES:
            raise ValueError(f"capital_mode must be one of {_VALID_CAPITAL_MODES}; got {capital_mode!r}")
        self.capital_mode = capital_mode
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.positions: dict[str, int] = {}
        self.fee_rate = fee_rate
        self.tax_rate = tax_rate
        self.trades: list[dict[str, Any]] = []
        self.cash_blocked_entry_count = 0
        self.logger = logging.getLogger(__name__)
        self.execution_prices: dict[str, float] = {}

        if capital_mode == "per_stock":
            code_list = codes or []
            per_cash = initial_cash / len(code_list) if code_list else initial_cash
            self.cash_buckets: dict[str, float] = {c: per_cash for c in code_list}
            self.per_stock_initial_cash: float | None = per_cash
        else:
            self.cash_buckets = {}
            self.per_stock_initial_cash = None

    def set_execution_prices(self, prices: dict[str, Any]):
        self.execution_prices = dict(prices)

    def execution_price(self, code: str, fallback: float):
        return float(self.execution_prices.get(code, fallback))

    def _available(self, code: str) -> float:
        if self.capital_mode == "per_stock":
            return self.cash_buckets.get(code, self.per_stock_initial_cash or self.cash)
        return self.cash

    def _add_cash(self, code: str, amount: float) -> None:
        self.cash += amount
        if self.capital_mode == "per_stock":
            self.cash_buckets[code] = self._available(code) + amount

    def buy(self, code: str, price: float, qty: Any, date: Any):
        """Buy shares using the current execution price when available."""
        signal_price = price
        price = self.execution_price(code, price)
        cost = price * qty
        fee = round(cost * self.fee_rate)
        total_cost = cost + fee

        if self.capital_mode == "unconstrained" or self._available(code) >= total_cost:
            self._add_cash(code, -total_cost)
            self.positions[code] = self.positions.get(code, 0) + qty
            self.trades.append({
                "date": date,
                "code": code,
                "action": "BUY",
                "price": price,
                "signal_price": signal_price,
                "qty": qty,
                "fee": fee,
                "tax": 0,
                "total": -total_cost,
            })
            return True

        self.cash_blocked_entry_count += 1
        self.logger.warning(f"[{date}] {code} buy failed: required={total_cost}, cash={self._available(code)}")
        return False

    def sell(self, code: str, price: float, qty: Any, date: Any):
        """Sell shares using the current execution price when available."""
        signal_price = price
        price = self.execution_price(code, price)
        current_qty = self.positions.get(code, 0)
        if current_qty < qty:
            return False

        revenue = price * qty
        fee = round(revenue * self.fee_rate)
        tax = round(revenue * self.tax_rate)
        total_revenue = revenue - fee - tax

        self._add_cash(code, total_revenue)
        self.positions[code] -= qty
        if self.positions[code] == 0:
            del self.positions[code]

        self.trades.append({
            "date": date,
            "code": code,
            "action": "SELL",
            "price": price,
            "signal_price": signal_price,
            "qty": qty,
            "fee": fee,
            "tax": tax,
            "total": total_revenue,
        })
        return True

    def handle_dividends(self, date: Any, dividend_row: dict[str, Any]):
        """Credit cash dividends for current holdings."""
        code = dividend_row["Code"]
        div_amount = dividend_row["Dividends"]
        if code not in self.positions:
            return

        qty = self.positions[code]
        total_div = qty * div_amount
        self._add_cash(code, total_div)
        self.trades.append({
            "date": date,
            "code": code,
            "action": "DIVIDEND",
            "price": div_amount,
            "qty": qty,
            "fee": 0,
            "tax": 0,
            "total": total_div,
        })
        self.logger.info(f"[{date}] {code} dividend credited: {total_div:,.0f} for qty={qty}")

    def get_position(self, code: str):
        """Return current share quantity for a symbol."""
        return self.positions.get(code, 0)

    def handle_split(self, date: Any, split_row: dict[str, Any]):
        """Adjust held share count for split/reverse-split events."""
        code = split_row["Code"]
        price_factor = split_row["price_factor"]
        if code not in self.positions or price_factor <= 0:
            return

        old_qty = self.positions[code]
        new_qty = int(round(old_qty / price_factor))
        if new_qty <= 0:
            return

        self.positions[code] = new_qty
        self.trades.append({
            "date": date,
            "code": code,
            "action": "SPLIT",
            "price": 0,
            "signal_price": 0,
            "qty": new_qty - old_qty,
            "fee": 0,
            "tax": 0,
            "total": 0,
            "old_qty": old_qty,
            "new_qty": new_qty,
            "price_factor": price_factor,
            "evidence_status": split_row.get("evidence_status"),
        })

    def get_total_value(self, current_prices: dict[str, Any]):
        """Return current total account value: cash plus positions."""
        market_value = 0
        for code, qty in self.positions.items():
            price = current_prices.get(code, 0)
            market_value += price * qty
        return self.cash + market_value

    def get_performance(self, current_prices: dict[str, Any]):
        """Return final value and total return metrics."""
        total_value = self.get_total_value(current_prices)
        pnl = total_value - self.initial_cash
        return {
            "final_value": total_value,
            "total_pnl": pnl,
            "return_rate": (pnl / self.initial_cash) * 100,
        }
