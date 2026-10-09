"""Read-only snapshot adapter for the bounded descriptive feature atlas.

Research-specific restated price factors are not accounting entitlements or
total returns. Unknown data is retained as quality state, never interpolated.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.jobs import file_digest
from StockProject.engine.data_loader import CASH_WINDOW_EVENTS, PERMANENT_FACTOR_EVENTS

LOGGER = logging.getLogger(__name__)
START, END = "2019-01-02", "2026-08-14"
TASK_ID = "20261004-feature-discrimination-atlas"
SCHEMA = "feature-discrimination-atlas.v1"
DEFINITION = "daily-close-features-38-forward-63-126.v1"
PRICE_COLUMNS = ["Open", "High", "Low", "Close"]


def write_json(path: Path, value: Any) -> None:
    """Write only a fresh artifact; callers must provide JSON-safe values."""
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def digest_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def readonly_sqlite(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ValueError(f"Missing snapshot: {path}")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def input_paths(root: Path) -> dict[str, Path]:
    return {
        name: root / "shioaji_stock_prices" / "data" / filename
        for name, filename in (
            ("prices", "price_daily.parquet"),
            ("metadata", "symbol_meta.sqlite"),
            ("actions", "corporate_actions.sqlite"),
        )
    }


def load_snapshot(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load fixed-window raw observations, without requesting any outcome."""
    paths = input_paths(root)
    identities = {name: file_digest(path) for name, path in paths.items()}
    prices = pd.read_parquet(
        paths["prices"],
        columns=["Code", "Date", *PRICE_COLUMNS, "Volume", "Source"],
        filters=[("Date", ">=", pd.Timestamp(START)), ("Date", "<=", pd.Timestamp(END))],
    )
    prices["Code"] = prices["Code"].astype(str)
    prices["Date"] = pd.to_datetime(prices["Date"])
    dates = cast(pd.Series, prices["Date"])
    if bool(dates.isna().any()) or not bool(dates.eq(dates.dt.normalize()).all()):
        raise ValueError("Non-daily or missing date in snapshot")
    with closing(readonly_sqlite(paths["metadata"])) as connection:
        meta = pd.read_sql_query("SELECT * FROM symbol_meta ORDER BY code", connection)
    with closing(readonly_sqlite(paths["actions"])) as connection:
        actions = pd.read_sql_query(
            "SELECT * FROM corporate_actions WHERE ex_date >= ? AND ex_date <= ? ORDER BY code, ex_date", connection, params=[START, END]
        )
    meta["code"] = meta["code"].astype(str)
    actions["code"] = actions["code"].astype(str)
    if meta["code"].duplicated().any():
        raise ValueError("Duplicate security metadata")
    official = prices["Source"].eq("official")
    inventory = {
        "source_sha256": identities,
        "source_paths": {key: path.relative_to(root).as_posix() for key, path in paths.items()},
        "read_window": {"start": START, "end": END},
        "source_row_counts": {str(k): int(v) for k, v in prices.groupby("Source", dropna=False).size().items()},
        "excluded_nonofficial_rows": int((~official).sum()),
        "metadata_rows": len(meta),
        "membership_basis": "current_metadata_reference_not_historical_PIT",
        "historical_universe_complete": False,
    }
    LOGGER.info("Read bounded snapshot: %d quotes, %d metadata rows", len(prices), len(meta))
    return prices.loc[official].copy(), meta, actions, inventory


def security_inventory(prices: pd.DataFrame, meta: pd.DataFrame) -> list[dict[str, Any]]:
    """Keep excluded, absent-price and absent-metadata securities in inventory."""
    by_code = meta.set_index("code").to_dict("index")
    price_codes = set(prices["Code"])
    result = []
    for code in sorted(price_codes | set(by_code)):
        row = {key: None if pd.isna(value) else value for key, value in by_code.get(code, {}).items()}
        ordinary = row.get("is_etf") == 0 and row.get("security_category") == "股票" and str(row.get("market")).upper() in {"上市", "上櫃", "TWSE", "TPEX"}
        reason = (
            None
            if ordinary and code in price_codes
            else ("metadata_unavailable" if not row else "not_ordinary_reference" if not ordinary else "no_official_prices_in_window")
        )
        result.append({
            "security_id": f"TW:{code}",
            "code": code,
            "included": reason is None,
            "exclusion_reason": reason,
            "name": row.get("name"),
            "market_reference": row.get("market"),
            "industry_ref": row.get("industry_category") or "unknown",
            "classification_basis": "current_metadata_reference",
            "metadata_fetched_at": row.get("fetched_at"),
            "historical_membership_known": False,
        })
    return result


def prepare_prices(raw: pd.DataFrame, actions: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Return aligned research OHLC, raw turnover and separate quality reasons."""
    if not calendar.is_unique or not calendar.is_monotonic_increasing:
        raise ValueError("Calendar must be sorted and unique")
    duplicates = set(pd.to_datetime(raw.loc[raw["Date"].duplicated(keep=False), "Date"]))
    frame = raw.sort_values("Date", kind="stable").drop_duplicates("Date").set_index("Date").reindex(calendar)
    numeric = pd.DataFrame(frame[PRICE_COLUMNS + ["Volume"]].apply(pd.to_numeric, errors="coerce"))
    raw_prices = pd.DataFrame(numeric[PRICE_COLUMNS])
    valid = pd.Series(np.isfinite(raw_prices.to_numpy()).all(axis=1), index=calendar) & raw_prices.gt(0).all(axis=1)
    valid &= cast(pd.Series, numeric["High"]).ge(raw_prices.max(axis=1)) & cast(pd.Series, numeric["Low"]).le(raw_prices.min(axis=1))
    reasons = pd.Series("", index=calendar, dtype=object)
    reasons.loc[frame["Code"].isna()] = "missing_official_quote"
    reasons.loc[~valid & frame["Code"].notna()] = "invalid_ohlc"
    factors = pd.Series(1.0, index=calendar)
    event_kinds = pd.Series("", index=calendar, dtype=object)
    cash_event_dates = pd.Series(False, index=calendar)

    def mark(day: pd.Timestamp, reason: str) -> None:
        position = int(np.searchsorted(calendar.asi8, day.value))
        if position < len(calendar):
            old = reasons.iloc[position]
            reasons.iloc[position] = (old + "|" if old else "") + reason
            valid.iloc[position] = False

    for day in duplicates:
        mark(cast(pd.Timestamp, pd.Timestamp(day)), "duplicate_date")
    for day, events in actions.groupby("ex_date", sort=True):
        timestamp = cast(pd.Timestamp, pd.Timestamp(str(day)))
        if timestamp < cast(pd.Timestamp, calendar[0]) or timestamp > cast(pd.Timestamp, calendar[-1]):
            continue
        kinds = set(events["event_type"].astype(str))
        position = int(np.searchsorted(calendar.asi8, timestamp.value))
        if position < len(calendar):
            event_kinds.iloc[position] = ",".join(sorted(kinds))
            if calendar[position] == timestamp and kinds & CASH_WINDOW_EVENTS:
                cash_event_dates.iloc[position] = True
        if kinds - (PERMANENT_FACTOR_EVENTS | CASH_WINDOW_EVENTS):
            mark(timestamp, "unsupported_action")
        permanent = events.loc[events["event_type"].isin(list(PERMANENT_FACTOR_EVENTS))]
        if permanent.empty:
            continue
        unique_factors = cast(pd.Series, pd.to_numeric(permanent["price_factor"], errors="coerce"))
        usable = np.isfinite(unique_factors) & (unique_factors > 0)
        if not usable.all() or permanent["event_type"].nunique() != 1 or unique_factors.nunique() != 1:
            mark(timestamp, "ambiguous_or_missing_action_factor")
            continue
        factors.loc[calendar < timestamp] *= float(unique_factors.iloc[0])
    adjusted = pd.DataFrame(raw_prices.mul(factors, axis=0))
    observed_close = cast(pd.Series, adjusted["Close"]).where(valid)
    signed_change = observed_close.pct_change(fill_method=None)
    # Cash declines remain in research prices; only exact event dates explain
    # a negative jump. Other action and OHLC failures remain invalid above.
    jumps = signed_change.abs().ge(0.4) & ~(signed_change.le(-0.4) & cash_event_dates)
    for position in np.flatnonzero(jumps.to_numpy(dtype=bool)):
        mark(cast(pd.Timestamp, calendar[position]), "unexplained_adjusted_jump")
    # Invalid observations are retained in raw columns and reason fields, while
    # every affected feature window and forward outcome sees a true gap.
    output = pd.DataFrame(adjusted.where(valid, np.nan))
    for column in PRICE_COLUMNS:
        output[f"Raw{column}"] = numeric[column]
    vol = cast(pd.Series, numeric["Volume"])
    good_volume = np.isfinite(vol) & vol.ge(0)
    output["VolumeLots"] = vol.where(good_volume)
    output["Turnover"] = (cast(pd.Series, numeric["Close"]) * vol).where(good_volume & valid)
    output["Quality"] = valid
    output["quality_reason"] = reasons.where(reasons.ne(""), None)
    output["volume_status"] = np.where(~good_volume, "missing_or_invalid", np.where(vol.eq(0), "zero", "observed"))
    output["corporate_action_types"] = event_kinds
    output["restatement_factor"] = factors
    return output


def market_regime(features: pd.DataFrame) -> pd.Series:
    """Fixed 0050 descriptor; not a fitted classifier."""
    dist, slope = features["dist_ma60"], features["ma60_slope20"]
    known = dist.notna() & slope.notna()
    result = pd.Series("unknown", index=features.index, dtype=object)
    result.loc[known] = "mixed"
    result.loc[known & dist.gt(0) & slope.gt(0)] = "up"
    result.loc[known & dist.lt(0) & slope.lt(0)] = "down"
    return result


def cross_sectional_features(frame: pd.DataFrame, benchmark_ret60: pd.Series) -> pd.DataFrame:
    """Rank only today's eligible and feature-known names; no future filter."""
    output = pd.DataFrame(index=frame.index)
    for period, feature in ((20, "F36"), (60, "F37")):
        values = frame[f"ret{period}"].where(frame["base_eligible"])
        ranks = values.groupby(frame["asof_date"]).rank(method="average", pct=True)
        output[f"rs{period}_percentile"] = ranks
        output[feature] = ranks.ge(0.8).astype(float).where(ranks.notna())
    benchmark = frame["asof_date"].map(lambda day: benchmark_ret60.get(day, np.nan))
    difference = frame["ret60"] - benchmark
    output["relative_ret60_0050"] = difference
    output["F38"] = difference.gt(0).astype(float).where(difference.notna())
    return output


def continuous_distributions(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    result = []
    eligible = frame.loc[frame["base_eligible"]]
    for label in ("label_63", "label_126"):
        for value, group in eligible.groupby(label, dropna=False):
            for column in columns:
                values = group[column].dropna()
                quantiles = values.quantile([0.1, 0.25, 0.5, 0.75, 0.9]) if len(values) else pd.Series(dtype=float)
                result.append({
                    "feature": column,
                    "label": label,
                    "outcome": None if pd.isna(value) else int(value),
                    "count": len(values),
                    "missing": len(group) - len(values),
                    "quantiles": {str(q): float(v) if math.isfinite(v) else None for q, v in quantiles.items()},
                    "descriptive_only": True,
                })
    return result
