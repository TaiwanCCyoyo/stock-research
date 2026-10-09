import logging
from typing import Any

import pandas as pd
from tqdm import tqdm


class BacktestEngine:
    """
    Event-driven backtest engine.
    """

    def __init__(self, broker: Any, data_loader: Any):
        self.broker = broker
        self.loader = data_loader
        self.data_cache: dict[str, pd.DataFrame] = {}
        self.equity_curve: list[dict[str, Any]] = []
        self.price_curve: list[dict[str, Any]] = []
        self.logger = logging.getLogger(__name__)

    def run(self, code_list: Any, strategy_class: Any, start_date: Any = None, end_date: Any = None, strategy_context: Any = None):
        self.data_cache = {}
        self.row_cache: dict[str, dict] = {}
        self.equity_curve = []
        self.price_curve = []
        latest_prices = {}
        self.loader.set_backtest_window(start_date, end_date)

        # 1. Load and cache market data.
        self.logger.info(f"Loading data for {len(code_list)} symbols...")
        all_dates = set()

        for code in code_list:
            df = self.loader.get_stock_data(code, adjust=True)
            if df.empty:
                continue

            if start_date:
                df = df[df["Date"] >= pd.to_datetime(start_date)]
            if end_date:
                df = df[df["Date"] <= pd.to_datetime(end_date)]

            if df.empty:
                continue

            self.data_cache[code] = df
            # A date -> row lookup, built once per symbol. The daily snapshot below used to
            # filter each symbol's whole frame with `df[df["Date"] == current_date]`, which
            # is a full scan per symbol per bar and therefore costs symbols x bars^2 for the
            # run. At twenty symbols that is invisible; at the 1,345 of `rotation_pit` a
            # single one-year cell did not finish in ten minutes, and the quadratic term
            # means a longer window is disproportionately worse rather than proportionately.
            # Rows are plain dicts rather than Series: strategies only ever index them by
            # column name or call `.get`, and dicts are far cheaper to materialise in bulk.
            # `keep="first"` preserves the old `row.iloc[0]` behaviour if a symbol ever
            # carries two rows for one date; a plain dict build would silently keep the last.
            unique = df.drop_duplicates(subset="Date", keep="first")
            self.row_cache[code] = dict(zip(unique["Date"], unique.to_dict("records"), strict=True))
            all_dates.update(df["Date"].tolist())

        if not all_dates:
            self.logger.error("No data found in the requested date range.")
            return

        sorted_dates = sorted(list(all_dates))

        # 2. Initialize the strategy.
        strategy = strategy_class(self.broker, context=strategy_context or {})

        # 3. Advance the simulation by date.
        self.logger.info(f"Running backtest: {sorted_dates[0].date()} -> {sorted_dates[-1].date()}")

        for current_date in tqdm(sorted_dates, desc="Backtesting"):
            # A. Apply dividends before strategy decisions.
            divs = self.loader.get_dividends_for_date(current_date)
            if not divs.empty:
                for _, row in divs.iterrows():
                    self.broker.handle_dividends(current_date, row)
            splits = self.loader.get_splits_for_date(current_date)
            if not splits.empty:
                for _, row in splits.iterrows():
                    self.broker.handle_split(current_date, row)

            # B. Build the daily market snapshot for the strategy.
            day_snapshot = {}
            execution_prices = {}
            for code, rows in self.row_cache.items():
                row = rows.get(current_date)
                if row is not None:
                    day_snapshot[code] = row
                    execution_price = row.get("RawClose", row["Close"])
                    execution_prices[code] = execution_price
                    latest_prices[code] = execution_price

            # C. Let the strategy react to the daily snapshot.
            if day_snapshot:
                self.broker.set_execution_prices(execution_prices)
                strategy.on_bar(current_date, day_snapshot)
                self.equity_curve.append({
                    "date": current_date,
                    "equity": self.broker.get_total_value(latest_prices),
                })
                self.price_curve.append({
                    "date": current_date,
                    "prices": latest_prices.copy(),
                })

        self.logger.info("Backtest completed.")

        # 4. Return performance based on final prices.
        final_prices = {}
        for code, df in self.data_cache.items():
            if not df.empty:
                final_prices[code] = df.iloc[-1].get("RawClose", df.iloc[-1]["Close"])

        return self.broker.get_performance(final_prices)
