from typing import Any

from engine.strategy_base import StrategyBase


class SimpleBuyHold(StrategyBase):
    """
    A simple buy and hold strategy for testing the CLI.
    """

    def on_bar(self, date: Any, data_dict: Any):
        for code, bar in data_dict.items():
            # If no position, buy 1000 shares
            if self.broker.get_position(code) == 0:
                self.buy_affordable_lot(code, bar["Close"], date)
