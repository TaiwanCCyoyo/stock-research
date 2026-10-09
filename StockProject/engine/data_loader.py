from __future__ import annotations

import glob
import os
import sqlite3
from pathlib import Path
from typing import Any, cast

import pandas as pd

PRICE_COLUMNS = ["Open", "High", "Low", "Close"]
CASH_DIVIDEND = "CASH_DIVIDEND"
SPLIT_EVENTS = {"ETF_SPLIT", "ETF_REVERSE_SPLIT"}
RIGHTS_EVENTS = {"EX_RIGHT", "EX_RIGHT_AND_DIVIDEND"}
CAPITAL_REDUCTION_EVENTS = {"CASH_CAPITAL_REDUCTION", "LOSS_OFFSET_CAPITAL_REDUCTION", "CAPITAL_REDUCTION"}
CASH_WINDOW_EVENTS = {CASH_DIVIDEND, "EX_RIGHT_AND_DIVIDEND"}
# Events adjusted via the same permanent multiplicative price_factor mechanism as splits.
PERMANENT_FACTOR_EVENTS = SPLIT_EVENTS | RIGHTS_EVENTS | CAPITAL_REDUCTION_EVENTS
# Events that also change held share count on the same date (splits and capital
# reductions change real share count same-day; rights issues do not -- new shares
# from a rights subscription list weeks later, on a date this data does not track).
SHARE_COUNT_EVENTS = SPLIT_EVENTS | CAPITAL_REDUCTION_EVENTS

# Process-wide per-file frame cache keyed by (absolute path, mtime_ns) so that
# repeated per-symbol loads (dashboard K-line switches, API requests) skip disk.
_SYMBOL_FRAME_CACHE: dict[tuple[str, int], pd.DataFrame] = {}


def _read_day_csv(filename: str) -> pd.DataFrame | None:
    df = pd.read_csv(filename)
    df.columns = [column.strip() for column in df.columns]
    if "Date" not in df.columns and "ts" in df.columns:
        df["Date"] = pd.to_datetime(df["ts"])
    elif "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
    else:
        return None
    df["Code"] = os.path.basename(filename).split("_")[0]
    # The parquet carries a Source column since 2026-08-30. A frame spliced in from a
    # CSV is Shioaji-derived by construction, so label it rather than leaving NaN in a
    # column a consumer may filter on.
    df["Source"] = "shioaji"
    return df


def _read_day_csv_cached(filename: str) -> pd.DataFrame | None:
    try:
        mtime_ns = os.stat(filename).st_mtime_ns
    except OSError:
        return None
    key = (os.path.abspath(filename), mtime_ns)
    cached = _SYMBOL_FRAME_CACHE.get(key)
    if cached is not None:
        return cached.copy()
    df = _read_day_csv(filename)
    if df is None:
        return None
    for stale_key in [existing for existing in _SYMBOL_FRAME_CACHE if existing[0] == key[0]]:
        del _SYMBOL_FRAME_CACHE[stale_key]
    _SYMBOL_FRAME_CACHE[key] = df.copy()
    return df


class DataLoader:
    """
    Load price data and apply dividend adjustments.
    """

    def __init__(self, data_path: Path | str = "/app/data/processed"):
        self.price_file = os.path.join(data_path, "price_daily.parquet")
        self.div_file = os.path.join(data_path, "dividends.parquet")
        self.data_path = Path(data_path)
        self.corporate_action_db = self._resolve_corporate_action_db()
        self._price_df: pd.DataFrame | None = None
        self._price_by_code: dict[str, pd.DataFrame] = {}
        self._actions_by_code: dict[str, pd.DataFrame] | None = None
        self._div_df: pd.DataFrame | None = None
        self._corporate_actions_df: pd.DataFrame | None = None
        self._warnings: list[str] = []
        self._backtest_start = None
        self._backtest_end = None

    def set_backtest_window(self, start_date: str | None = None, end_date: str | None = None):
        """Limit diagnostics to the dates included in the current backtest."""
        self._backtest_start = pd.to_datetime(start_date) if start_date else None
        self._backtest_end = pd.to_datetime(end_date) if end_date else None
        self._warnings = []

    def load_all(self):
        """Load all available price and dividend data."""
        if os.path.exists(self.price_file):
            price_df = pd.read_parquet(self.price_file)
            price_df["Date"] = pd.to_datetime(price_df["Date"]).dt.tz_localize(None)
            price_df = self._refresh_stale_symbols(price_df)
            self._price_df = price_df
            self._index_by_code()
        else:
            csv_files = glob.glob(os.path.join(os.path.dirname(self.price_file), "*_day.csv"))
            dfs = []
            for filename in csv_files:
                df = _read_day_csv(filename)
                if df is not None and not df.empty:
                    dfs.append(df)
            if dfs:
                price_df = pd.concat(dfs, ignore_index=True)
                price_df["Date"] = pd.to_datetime(price_df["Date"]).dt.tz_localize(None)
                self._price_df = price_df
                self._index_by_code()

        if os.path.exists(self.div_file):
            div_df = pd.read_parquet(self.div_file)
            div_df["Date"] = pd.to_datetime(div_df["Date"]).dt.tz_localize(None)
            self._div_df = div_df
        self._load_corporate_actions()

    def _refresh_stale_symbols(self, price_df: pd.DataFrame) -> pd.DataFrame:
        """Replace parquet rows for symbols whose source CSV is newer than the parquet."""
        parquet_mtime_ns = os.stat(self.price_file).st_mtime_ns
        stale_frames = []
        stale_codes = []
        for filename in glob.glob(os.path.join(os.path.dirname(self.price_file), "*_day.csv")):
            if os.stat(filename).st_mtime_ns <= parquet_mtime_ns:
                continue
            df = _read_day_csv_cached(filename)
            if df is not None and not df.empty:
                stale_frames.append(df)
                stale_codes.append(os.path.basename(filename).split("_")[0])
        if not stale_frames:
            return price_df
        self._warnings.append(
            f"price_daily.parquet is stale for {len(stale_codes)} symbols; reloaded from CSV "
            "(rebuild by running shioaji_stock_prices/scripts/run_daily.py, "
            "or shioaji_stock_prices/scripts/build_price_parquet.py directly)"
        )
        # Merge per (Code, Date) rather than replacing the symbol wholesale. Since
        # 2026-08-30 the parquet is built from the official artifact and reaches
        # 2010-01-04, while a {code}_day.csv is Shioaji-derived and starts 2018-12-07 --
        # so dropping every parquet row for a stale symbol would silently delete eight
        # years of its history and revert the rest to a different volume definition.
        # The CSV still wins where it overlaps: that is the point of the refresh.
        refreshed = pd.concat([*stale_frames, price_df], ignore_index=True)
        refreshed["Date"] = pd.to_datetime(refreshed["Date"]).dt.tz_localize(None)
        refreshed = refreshed.drop_duplicates(subset=["Code", "Date"], keep="first")
        return refreshed

    def load_symbols(self, codes: list[str]):
        """Load price data for the requested codes only, plus corporate actions.

        Produces the same frames as load_all() filtered to `codes`, without
        scanning the full data directory. Per-file reads go through a
        process-wide (path, mtime) cache.
        """
        data_dir = os.path.dirname(self.price_file)
        dfs = []
        for code in dict.fromkeys(str(code) for code in codes):
            df = _read_day_csv_cached(os.path.join(data_dir, f"{code}_day.csv"))
            if df is not None and not df.empty:
                dfs.append(df)
        if dfs:
            price_df = pd.concat(dfs, ignore_index=True)
            price_df["Date"] = pd.to_datetime(price_df["Date"]).dt.tz_localize(None)
            self._price_df = price_df
        else:
            self._price_df = pd.DataFrame({
                "Date": pd.Series(dtype="datetime64[ns]"),
                "Code": pd.Series(dtype=str),
                **{column: pd.Series(dtype=float) for column in PRICE_COLUMNS},
            })
        # Both loading entry points must index, or `get_stock_data` finds nothing.
        self._index_by_code()
        self._load_corporate_actions()

    def _index_by_code(self) -> None:
        """Split the price frame by symbol once, instead of scanning it once per symbol.

        `get_stock_data` used to select with
        `self._price_df[self._price_df["Code"].astype(str) == str(code)]`, which rebuilds a
        string array over every row of the whole cache -- 3.4 million of them -- and compares
        all of it, for each symbol requested. At twenty symbols that is a rounding error; over
        the 1,345 of `rotation_pit` it is billions of string conversions and dominated the run.
        Grouping once turns each lookup into a dict access.

        Codes are normalised to `str` here so no caller has to convert, and so the group keys
        and the caller's key are the same type.
        """
        if self._price_df is None:
            return
        self._price_df["Code"] = self._price_df["Code"].astype(str)
        self._price_by_code = {str(code): group for code, group in self._price_df.groupby("Code", sort=False)}

    def _actions_for_code(self, code: str | None) -> pd.DataFrame:
        """Corporate actions for one symbol, from a per-symbol index built on first use."""
        frame = self._corporate_actions_df
        if frame is None:
            return pd.DataFrame()
        if self._actions_by_code is None:
            frame["Code"] = frame["Code"].astype(str)
            self._actions_by_code = {str(code_key): group for code_key, group in frame.groupby("Code", sort=False)}
        return self._actions_by_code.get(str(code), cast(pd.DataFrame, frame.iloc[0:0]))

    def get_stock_data(self, code: str | None, adjust: bool = True):
        """
        Return data for a single symbol, optionally adjusted for dividends.
        """
        if self._price_df is None:
            self.load_all()
        if self._price_df is None:
            return pd.DataFrame()

        df = self._price_by_code.get(str(code))
        if df is None:
            return pd.DataFrame()
        df = df.copy().sort_values("Date")

        if self._corporate_actions_df is not None:
            actions = self._actions_for_code(code)
            df = self._apply_corporate_action_policy(df, actions)
        elif adjust and self._div_df is not None:
            self._warnings.append(
                "corporate_actions.sqlite unavailable; falling back to deprecated yfinance dividend data (dividends.parquet) for signal-price adjustment"
            )
            divs = cast(pd.DataFrame, self._div_df[self._div_df["Code"] == code])
            df = self._apply_adjustment(df, divs)
        else:
            df = self._ensure_price_layers(df)

        return df

    def _apply_adjustment(self, df: pd.DataFrame, divs: pd.DataFrame):
        """
        Calculate backward-adjusted prices while keeping current prices unchanged.
        """
        df = df.sort_values("Date", ascending=False)
        df["Adj_Factor"] = 1.0

        for _, row in divs.iterrows():
            div_date = row["Date"]
            div_amt = row["Dividends"]

            pre_div_data = cast(pd.DataFrame, df[df["Date"] < div_date]).head(1)
            if not pre_div_data.empty:
                pre_close = cast(pd.Series, pre_div_data["Close"]).values[0]
                factor = (pre_close - div_amt) / pre_close
                df.loc[df["Date"] < div_date, "Adj_Factor"] *= factor

        df["Adj_Close"] = (df["Close"] * df["Adj_Factor"]).round(2)
        df["Adj_Open"] = (df["Open"] * df["Adj_Factor"]).round(2)
        df["Adj_High"] = (df["High"] * df["Adj_Factor"]).round(2)
        df["Adj_Low"] = (df["Low"] * df["Adj_Factor"]).round(2)

        return df.sort_values("Date")

    def get_dividends_for_date(self, date: Any):
        """Return all dividend rows for a specific date."""
        if self._corporate_actions_df is not None:
            rows = self._corporate_actions_df[
                (self._corporate_actions_df["Date"] == date)
                & (self._corporate_actions_df["event_type"] == CASH_DIVIDEND)
                & self._corporate_actions_df["Dividends"].notna()
            ]
            return rows[["Date", "Code", "Dividends"]].copy()
        if self._div_df is None:
            return pd.DataFrame()
        return self._div_df[self._div_df["Date"] == date]

    def get_splits_for_date(self, date: Any):
        """Return rows for a specific date whose share count changes that same day:
        splits/reverse-splits and capital reductions (both physically change share
        count same-day, unlike rights issues -- see SHARE_COUNT_EVENTS)."""
        if self._corporate_actions_df is None:
            return pd.DataFrame()
        return self._corporate_actions_df[
            (self._corporate_actions_df["Date"] == date)
            & self._corporate_actions_df["event_type"].isin(tuple(SHARE_COUNT_EVENTS))
            & self._corporate_actions_df["price_factor"].notna()
        ].copy()

    def get_corporate_actions(self, code: str | None):
        """Return corporate-action rows for a single symbol (empty frame if none)."""
        if self._corporate_actions_df is None:
            return pd.DataFrame()
        return self._actions_for_code(code).copy()

    def get_warnings(self):
        return list(dict.fromkeys(self._warnings))

    def _resolve_corporate_action_db(self):
        candidates = [
            self.data_path / "corporate_actions.sqlite",
            self.data_path.parent / "corporate_actions.sqlite",
            self.data_path.parent.parent / "corporate_actions.sqlite",
        ]
        for path in candidates:
            if path.is_file():
                return path
        return None

    def _load_corporate_actions(self):
        if self.corporate_action_db is None:
            return
        with sqlite3.connect(self.corporate_action_db) as conn:
            df = pd.read_sql_query(
                """
                SELECT code, ex_date, event_type, previous_close, reference_price,
                       cash_dividend_estimate, price_factor, evidence_status
                FROM corporate_actions
                WHERE event_type IN (
                    'CASH_DIVIDEND',
                    'ETF_SPLIT',
                    'ETF_REVERSE_SPLIT',
                    'EX_RIGHT',
                    'EX_RIGHT_AND_DIVIDEND',
                    'CASH_CAPITAL_REDUCTION',
                    'LOSS_OFFSET_CAPITAL_REDUCTION',
                    'CAPITAL_REDUCTION'
                )
                """,
                conn,
            )
        if df.empty:
            return
        df["Code"] = df["code"].astype(str)
        df["Date"] = pd.to_datetime(df["ex_date"]).dt.tz_localize(None)
        df["Dividends"] = df["cash_dividend_estimate"]
        self._corporate_actions_df = df

    def _ensure_price_layers(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        for column in PRICE_COLUMNS:
            raw_column = f"Raw{column}"
            if raw_column not in df.columns:
                df[raw_column] = df[column]
            split_column = f"SplitAdjusted{column}"
            if split_column not in df.columns:
                df[split_column] = df[raw_column]
            signal_column = f"Signal{column}"
            if signal_column not in df.columns:
                df[signal_column] = df[split_column]
            df[column] = df[signal_column]
        for column, default in [
            ("SplitAdjustmentFactor", 1.0),
            ("DividendSignalFactor", 1.0),
            ("DividendWindowActive", False),
            ("DividendFilled", False),
            ("SignalPricePolicy", "raw"),
            ("CorporateActionTypes", ""),
        ]:
            if column not in df.columns:
                df[column] = default
        return df

    def _apply_corporate_action_policy(self, df: pd.DataFrame, actions: pd.DataFrame):
        df = self._ensure_price_layers(df)
        df = df.sort_values("Date").reset_index(drop=True)
        actions = actions.sort_values("Date")

        # Splits, rights/stock-dividend events, and capital reductions all get the
        # same permanent multiplicative price_factor adjustment applied to prior-date
        # signal prices; share_factor is not used because it is never populated by
        # the upstream fetch (see design.md Decision 0 in expand-corporate-action-
        # adjustments).
        permanent_factor_actions = cast(pd.DataFrame, actions[actions["event_type"].isin(tuple(PERMANENT_FACTOR_EVENTS))])
        df["SplitAdjustmentFactor"] = 1.0
        event_types_by_date: dict[object, set[str]] = {}
        for _, action in permanent_factor_actions.iterrows():
            price_factor = cast(float, action["price_factor"])
            if pd.isna(price_factor) or price_factor <= 0:
                continue
            event_date = cast(pd.Timestamp, action["Date"])
            df.loc[df["Date"] < event_date, "SplitAdjustmentFactor"] *= float(price_factor)
            event_types_by_date.setdefault(event_date, set()).add(cast(str, action["event_type"]))

        for column in PRICE_COLUMNS:
            df[f"SplitAdjusted{column}"] = (df[f"Raw{column}"] * df["SplitAdjustmentFactor"]).round(4)
            df[f"Signal{column}"] = df[f"SplitAdjusted{column}"]

        df["DividendSignalFactor"] = 1.0
        df["DividendWindowActive"] = False
        df["DividendFilled"] = False
        df["SignalPricePolicy"] = "split_adjusted"

        # EX_RIGHT_AND_DIVIDEND rows run the cash-dividend fill-window logic too, on
        # top of the price-factor adjustment already applied above.
        cash_window_actions = cast(pd.DataFrame, actions[actions["event_type"].isin(tuple(CASH_WINDOW_EVENTS))])
        for _, action in cash_window_actions.iterrows():
            price_factor = cast(float, action["price_factor"])
            previous_close = cast(float, action["previous_close"])
            if pd.isna(price_factor) or price_factor <= 0 or pd.isna(previous_close):
                continue
            event_date = cast(pd.Timestamp, action["Date"])
            event_types_by_date.setdefault(event_date, set()).add(cast(str, action["event_type"]))
            event_indexes = df.index[df["Date"] >= event_date].tolist()[:5]
            for row_index in event_indexes:
                if float(df.at[row_index, "RawClose"]) >= float(previous_close):
                    df.at[row_index, "DividendFilled"] = True
                    break
                df.at[row_index, "DividendWindowActive"] = True
                df.at[row_index, "DividendSignalFactor"] *= 1 / float(price_factor)
                df.at[row_index, "SignalPricePolicy"] = "cash_dividend_window"

        for column in PRICE_COLUMNS:
            df[f"Signal{column}"] = (df[f"SplitAdjusted{column}"] * df["DividendSignalFactor"]).round(4)
            df[column] = df[f"Signal{column}"]

        # Residual unsupported set: rights/capital-reduction rows without a usable
        # price_factor. evidence_status has no "insufficient" tier distinct from
        # REFERENCE_PRICE_ONLY in current data, so the factor validity guard (the
        # same one used above) is the real sufficiency gate.
        min_date = self._backtest_start or df["Date"].min()
        max_date = self._backtest_end or df["Date"].max()
        unsupported_candidates = cast(
            pd.DataFrame,
            actions[
                actions["event_type"].isin(tuple(RIGHTS_EVENTS | CAPITAL_REDUCTION_EVENTS)) & (actions["Date"] >= min_date) & (actions["Date"] <= max_date)
            ],
        )
        for _, action in unsupported_candidates.iterrows():
            price_factor = cast(float, action["price_factor"])
            if not (pd.isna(price_factor) or price_factor <= 0):
                continue
            event_date = cast(pd.Timestamp, action["Date"])
            self._warnings.append(f"Unsupported corporate action for {action['Code']} on {event_date.date()}: {action['event_type']}")
            event_types_by_date.setdefault(event_date, set()).add(cast(str, action["event_type"]))

        df["CorporateActionTypes"] = df["Date"].map(lambda value: ",".join(sorted(event_types_by_date.get(value, set()))))
        return df
