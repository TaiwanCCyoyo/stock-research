import json
from collections import defaultdict
from pathlib import Path
from typing import Any, TypedDict

from engine.strategy_base import StrategyBase


class PendingBreak(TypedDict):
    level: float
    expires: int


class TwoBMovingAverageConvergence(StrategyBase):
    """Daily MA/EMA convergence plus approximate 2B reversal candidate."""

    def __init__(self, broker: Any, context: dict[str, Any] | None = None) -> None:
        super().__init__(broker, context=context)
        self.history: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        self.pending_bottom_break: dict[str, PendingBreak] = {}
        self.pending_top_break: dict[str, PendingBreak] = {}
        self.entry_price: dict[str, float] = {}
        self.events: list[dict[str, Any]] = []
        self.task_root = Path(__file__).resolve().parents[1]

    def on_bar(self, date: Any, data_dict: dict[str, Any]) -> None:
        for code, bar in data_dict.items():
            current = self.make_bar(date, bar)
            prior = self.history[code]
            signal = self.calculate_signal(code, prior, current)
            position = self.broker.get_position(code)
            close = current["close"]

            if position > 0 and signal["full_exit"]:
                if self.broker.sell(code, close, position, date):
                    self.record_event(code, date, "sell", close, position, signal["exit_reason"])
                    self.entry_price.pop(code, None)
            elif position > 0 and signal["partial_exit"]:
                qty = self.partial_quantity(position)
                if qty > 0 and self.broker.sell(code, close, qty, date):
                    self.record_event(code, date, "partial_sell", close, qty, signal["exit_reason"])
            elif position > 0 and signal["add"]:
                qty = self.buy_by_allocation(code, close, date, float(self.context.get("add_allocation_pct", 0.12)))
                if qty > 0:
                    self.record_event(code, date, "add", close, qty, signal["entry_reason"])
                    self.update_entry_price(code, close, qty)
            elif position == 0 and signal["entry"]:
                qty = self.buy_by_allocation(code, close, date, float(self.context.get("initial_allocation_pct", 0.18)))
                if qty > 0:
                    self.record_event(code, date, "buy", close, qty, signal["entry_reason"])
                    self.entry_price[code] = close

            for event_name in signal["signals"]:
                self.record_event(code, date, event_name, close, 0, signal["signal_reason"])

            prior.append(current)

        self.write_signal_events()

    def make_bar(self, date: Any, bar: dict[str, Any]) -> dict[str, Any]:
        return {
            "date": date,
            "open": float(bar["Open"]),
            "high": float(bar["High"]),
            "low": float(bar["Low"]),
            "close": float(bar["Close"]),
        }

    def calculate_signal(self, code: str, prior: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "entry": False,
            "add": False,
            "partial_exit": False,
            "full_exit": False,
            "entry_reason": "",
            "exit_reason": "",
            "signal_reason": "",
            "signals": [],
        }
        windows = [int(value) for value in self.context.get("windows", [5, 10, 20])]
        swing_lookback = int(self.context.get("swing_lookback", 20))
        reclaim_window = int(self.context.get("reclaim_window", 5))
        required = max([*windows, swing_lookback + 1, int(self.context.get("exit_window", 10)) + 1])
        if len(prior) < required:
            return result

        closes = [item["close"] for item in [*prior, current]]
        highs = [item["high"] for item in prior]
        lows = [item["low"] for item in prior]
        close = current["close"]
        low = current["low"]
        high = current["high"]

        bottom_2b = self.detect_bottom_2b(code, low, close, lows[-swing_lookback:], reclaim_window)
        top_2b = self.detect_top_2b(code, high, close, highs[-swing_lookback:], reclaim_window)
        converged = self.is_converged(closes, windows)
        trend_ready = self.is_trend_ready(closes, windows)
        price_strength = close > max(self.average(closes, window) for window in windows) and close > prior[-1]["close"]

        if converged:
            result["signals"].append("ma_convergence")
        if bottom_2b:
            result["signals"].append("bottom_2b")
        if top_2b:
            result["signals"].append("top_2b")

        position = self.broker.get_position(code)
        if position == 0 and converged and trend_ready and (bottom_2b or price_strength):
            result["entry"] = True
            result["entry_reason"] = "bottom_2b_ma_convergence" if bottom_2b else "ma_convergence_price_strength"
        elif position > 0 and bottom_2b and converged and trend_ready:
            result["add"] = True
            result["entry_reason"] = "bottom_2b_add"

        exit_average = self.average(closes, int(self.context.get("exit_window", 10)))
        slow_exit_average = self.average(closes, int(self.context.get("slow_exit_window", 20)))
        stop_loss_pct = float(self.context.get("stop_loss_pct", 8.0))
        entry_price = self.entry_price.get(code)
        stop_loss = entry_price is not None and close <= entry_price * (1 - stop_loss_pct / 100)

        if position > 0 and (top_2b or stop_loss):
            result["full_exit"] = True
            result["exit_reason"] = "top_2b_exit" if top_2b else "stop_loss_exit"
        elif position > 0 and (close < exit_average or close < slow_exit_average):
            result["partial_exit"] = True
            result["exit_reason"] = "ma_break_partial_exit"

        result["signal_reason"] = ",".join(result["signals"])
        return result

    def detect_bottom_2b(self, code: str, low: float, close: float, prior_lows: list[float], reclaim_window: int) -> bool:
        break_pct = float(self.context.get("two_b_break_pct", 0.0))
        prior_low = min(prior_lows)
        pending = self.pending_bottom_break.get(code)
        if low < prior_low * (1 - break_pct / 100):
            self.pending_bottom_break[code] = {"level": prior_low, "expires": reclaim_window}
            return False
        if pending:
            pending["expires"] -= 1
            if close > pending["level"]:
                self.pending_bottom_break.pop(code, None)
                return True
            if pending["expires"] <= 0:
                self.pending_bottom_break.pop(code, None)
        return False

    def detect_top_2b(self, code: str, high: float, close: float, prior_highs: list[float], reclaim_window: int) -> bool:
        break_pct = float(self.context.get("two_b_break_pct", 0.0))
        prior_high = max(prior_highs)
        pending = self.pending_top_break.get(code)
        if high > prior_high * (1 + break_pct / 100):
            self.pending_top_break[code] = {"level": prior_high, "expires": reclaim_window}
            return False
        if pending:
            pending["expires"] -= 1
            if close < pending["level"]:
                self.pending_top_break.pop(code, None)
                return True
            if pending["expires"] <= 0:
                self.pending_top_break.pop(code, None)
        return False

    def is_converged(self, closes: list[float], windows: list[int]) -> bool:
        convergence_pct = float(self.context.get("convergence_pct", 2.0))
        averages = [self.average(closes, window) for window in windows]
        return ((max(averages) - min(averages)) / closes[-1]) * 100 <= convergence_pct

    def is_trend_ready(self, closes: list[float], windows: list[int]) -> bool:
        ma_type = str(self.context.get("ma_type", "sma")).lower()
        trend_window = int(self.context.get("trend_window", max(windows)))
        if len(closes) <= trend_window:
            return False
        if ma_type == "ema":
            ema_now = self.exponential_average(closes[-trend_window:])
            ema_prev = self.exponential_average(closes[-trend_window - 1 : -1])
            return ema_now >= ema_prev and closes[-1] >= ema_now
        return closes[-1] >= closes[-trend_window]

    def average(self, closes: list[float], window: int) -> float:
        ma_type = str(self.context.get("ma_type", "sma")).lower()
        values = closes[-window:]
        if ma_type == "ema":
            return self.exponential_average(values)
        if ma_type != "sma":
            raise ValueError(f"Unsupported ma_type: {ma_type}")
        return sum(values) / window

    def exponential_average(self, values: list[float]) -> float:
        multiplier = 2 / (len(values) + 1)
        average = values[0]
        for value in values[1:]:
            average = (value * multiplier) + (average * (1 - multiplier))
        return average

    def buy_by_allocation(self, code: str, price: float, date: Any, allocation_pct: float) -> int:
        lot_size = int(self.context.get("lot_size", 1000))
        budget = self.broker.cash * allocation_pct
        total_per_share = price * (1 + self.broker.fee_rate)
        qty = int(budget // (total_per_share * lot_size)) * lot_size
        if qty <= 0:
            return 0
        return qty if self.broker.buy(code, price, qty, date) else 0

    def partial_quantity(self, position: int) -> int:
        lot_size = int(self.context.get("lot_size", 1000))
        partial_pct = float(self.context.get("partial_sell_pct", 0.5))
        return int((position * partial_pct) // lot_size) * lot_size

    def update_entry_price(self, code: str, price: float, qty: int) -> None:
        current_qty = self.broker.get_position(code)
        previous_qty = max(current_qty - qty, 0)
        previous_price = self.entry_price.get(code, price)
        if current_qty > 0:
            self.entry_price[code] = ((previous_price * previous_qty) + (price * qty)) / current_qty

    def record_event(self, code: str, date: Any, event: str, price: float, qty: int, reason: str) -> None:
        self.events.append({
            "date": date.isoformat() if hasattr(date, "isoformat") else str(date),
            "code": code,
            "event": event,
            "price": price,
            "qty": qty,
            "reason": reason,
        })

    def write_signal_events(self) -> None:
        output = {
            "schema_version": "1.0",
            "strategy": "two_b_ma_convergence",
            "params": self.context,
            "events": self.events,
        }
        (self.task_root / "signal_events.json").write_text(
            json.dumps(output, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
