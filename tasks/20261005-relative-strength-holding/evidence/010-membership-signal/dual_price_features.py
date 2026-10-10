"""Pure, injected dual-price feature assembly for a single as-of cutoff.

``signal`` OHLC drives the six canonical price features.  ``raw`` Close and
official share Volume drive liquidity eligibility, after an explicit shares to
lots conversion.  This module deliberately does not validate a factor,
membership evidence, or corporate-action economics: it only records the
caller-supplied source identities and membership basis.  In particular, it is
not approval for a causal adjusted-price projector.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

TAIPEI = "Asia/Taipei"

SESSION_ROOT = Path(__file__).resolve().parents[1] / "006-artifacts-5fe106d423484ccf959cc4e2e5d6f6d3"
if str(SESSION_ROOT) not in sys.path:
    sys.path.insert(0, str(SESSION_ROOT))

from prototype.features_bridge import (  # noqa: E402
    LIQ_FLOOR,
    MIN_HISTORY,
    SIX_FEATURES,
    SIX_RANK_COLUMNS,
    canonical_table,
    rank_within_universe,
    strictly_prior_eligibility,
)

REQUIRED_COLUMNS = frozenset({"Market", "Code", "Date", "Open", "High", "Low", "Close", "Volume", "available_at", "source_id"})
PRICE_COLUMNS = ("Open", "High", "Low", "Close")


class DualPriceFeatureError(ValueError):
    """Injected evidence cannot safely produce an as-of feature table."""


def build_dual_price_features(
    raw: pd.DataFrame,
    signal: pd.DataFrame,
    *,
    universe: Mapping[date, frozenset[str]],
    membership_basis: str,
    decision_cutoff: datetime,
    raw_volume_unit: str,
    continuous_cross_market_codes: frozenset[str] = frozenset(),
) -> pd.DataFrame:
    """Return canonical six features ranked by raw-liquidity eligibility.

    Both inputs must have exact ``(Market, Code, Date)`` identity and a known,
    timezone-aware ``available_at`` no later than ``decision_cutoff``.  The
    This is one as-of prefix, so it returns only the Taipei cutoff-date rows;
    it must not be reused as a panel for earlier decisions.  A code can cross
    markets on disjoint dates only when listed in ``continuous_cross_market_codes``.
    ``raw_volume_unit`` is intentionally required to be ``"shares"``;
    canonical eligibility uses lots and this function divides by 1,000 once.
    """
    if raw_volume_unit != "shares":
        raise DualPriceFeatureError("raw_volume_unit must be declared as 'shares'")
    if not membership_basis.strip():
        raise DualPriceFeatureError("membership_basis must be nonempty")
    cutoff = _aware_timestamp(decision_cutoff, "decision_cutoff")
    cutoff_day = cutoff.tz_convert(TAIPEI).date()
    raw_frame = _validate_frame(raw, "raw", cutoff, continuous_cross_market_codes)
    signal_frame = _validate_frame(signal, "signal", cutoff, continuous_cross_market_codes)
    projection = _validate_signal_projection(signal.attrs, cutoff)
    _require_matching_keys(raw_frame, signal_frame)
    _require_matching_ohlc_nulls(raw_frame, signal_frame)
    _require_universe_coverage(cutoff_day, universe)

    # Volume equality is checked in declared shares before conversion.  Signal
    # volume is never price-adjusted.
    if not raw_frame["Volume"].equals(signal_frame["Volume"]):
        raise DualPriceFeatureError("signal Volume must exactly equal raw official shares")

    raw_lots = raw_frame[["Code", "Date", "Open", "High", "Low", "Close", "Volume"]].copy()
    raw_lots["Volume"] = raw_lots["Volume"] / 1000.0
    raw_eligibility = strictly_prior_eligibility(raw_lots)
    # Unlike the old merged cache, the source read-set retains no-close rows.
    # Those are date observations, not 120 observed price bars. Keep their gaps
    # in rolling windows, but do not count them toward the history requirement.
    valid_prior = raw_lots["Close"].notna().groupby(raw_lots["Code"], sort=False).transform(lambda values: values.cumsum().shift(1, fill_value=0))

    signal_lots = signal_frame[["Code", "Date", "Open", "High", "Low", "Close", "Volume"]].copy()
    signal_lots["Volume"] = signal_lots["Volume"] / 1000.0
    canonical = canonical_table(signal_lots)
    canonical = canonical.merge(
        raw_frame[["Market", "Code", "Date", "Open", "High", "Low", "Close", "Volume", "available_at", "source_id"]].rename(
            columns={
                "Open": "RawOpen",
                "High": "RawHigh",
                "Low": "RawLow",
                "Close": "RawClose",
                "Volume": "RawVolumeShares",
                "available_at": "raw_available_at",
                "source_id": "raw_source_id",
            }
        ),
        on=["Code", "Date"],
        how="left",
        validate="one_to_one",
    )
    canonical = canonical.merge(
        signal_frame[["Code", "Date", "Open", "High", "Low", "Close", "available_at", "source_id"]].rename(
            columns={
                "Open": "SignalOpen",
                "High": "SignalHigh",
                "Low": "SignalLow",
                "Close": "SignalClose",
                "available_at": "signal_available_at",
                "source_id": "signal_source_id",
            }
        ),
        on=["Code", "Date"],
        how="left",
        validate="one_to_one",
    )
    canonical["RawVolumeLots"] = canonical["RawVolumeShares"] / 1000.0
    canonical["raw_prior_rows"] = raw_eligibility["prior_bars"].to_numpy()
    canonical["raw_prior_bars"] = valid_prior.to_numpy()
    canonical["raw_liquidity"] = raw_eligibility["liquidity"].to_numpy()
    canonical["raw_eligible"] = (canonical["raw_prior_bars"] >= MIN_HISTORY) & (canonical["raw_liquidity"] >= LIQ_FLOOR)

    # ``compute`` can leave an OHLC-derived column populated after a current
    # input null through pandas skipna rules.  Make the row's current evidence
    # requirement explicit before any re-ranking.
    signal_current = signal_frame.set_index(["Code", "Date"])[list(PRICE_COLUMNS)].notna().all(axis=1)
    raw_current = raw_frame.set_index(["Code", "Date"])["Close"].notna()
    positive_volume = raw_frame.set_index(["Code", "Date"])["Volume"] > 0
    keys = pd.MultiIndex.from_frame(canonical[["Code", "Date"]])
    canonical["current_data_valid"] = signal_current.reindex(keys).to_numpy() & raw_current.reindex(keys).to_numpy() & positive_volume.reindex(keys).to_numpy()
    canonical["six_features_finite"] = canonical[list(SIX_FEATURES)].apply(
        lambda row: all(pd.notna(value) and math.isfinite(float(value)) for value in row), axis=1
    )
    # Canonical TR uses skipna max: a missing historical High/Low can leave a
    # plausible ATR. Its 14-bar mean nested in a 60-bar mean needs 73 TR rows,
    # hence 73 High/Low and 74 Close rows (including the earliest prior close).
    # Preserve missing rows; neither shorten their windows nor fill them.
    required_windows = {"High": 73, "Low": 73, "Close": 74, "Volume": 21}
    input_valid = pd.Series(True, index=signal_lots.index)
    for column, window in required_windows.items():
        supplied = (
            signal_lots[column]
            .notna()
            .groupby(signal_lots["Code"], sort=False)
            .transform(lambda values, size=window: values.rolling(size, min_periods=size).sum().eq(size))
        )
        input_valid &= supplied
    canonical["feature_inputs_valid"] = input_valid.to_numpy()
    canonical["eligible"] = canonical["raw_eligible"] & canonical["current_data_valid"] & canonical["six_features_finite"] & canonical["feature_inputs_valid"]
    ranked = rank_within_universe(canonical, universe, membership_basis=membership_basis)
    ranked.loc[~ranked["eligible"], list(SIX_RANK_COLUMNS)] = float("nan")
    # Cohort rank values belong to a different population and are never output
    # as candidates by this adapter.
    ranked = ranked[ranked["Date"].dt.date == cutoff_day].copy()
    result = ranked.drop(columns=[column for column in ("cohort_ret_20", "cohort_breadth", "r_cohort_ret_20", "r_cohort_breadth") if column in ranked])
    if projection is not None:
        result.attrs["signal_projection"] = dict(projection)
    return result


def _validate_frame(
    frame: pd.DataFrame,
    name: str,
    cutoff: pd.Timestamp,
    continuous_cross_market_codes: frozenset[str],
) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise DualPriceFeatureError(f"{name} is missing required columns: {sorted(missing)}")
    out = frame.copy()
    if out[["Market", "Code"]].isna().any().any():
        raise DualPriceFeatureError(f"{name} has a missing Market or Code")
    out["Market"] = out["Market"].astype(str)
    out["Code"] = out["Code"].astype(str)
    if (out["Market"].str.strip() == "").any() or (out["Code"].str.strip() == "").any():
        raise DualPriceFeatureError(f"{name} has an empty Market or Code")
    dates: list[pd.Timestamp] = []
    for value in out["Date"]:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp) or stamp.tzinfo is not None or stamp.hour or stamp.minute or stamp.second or stamp.microsecond or stamp.nanosecond:
            raise DualPriceFeatureError(f"{name}.Date must be a non-null, naive midnight session date")
        dates.append(stamp)
    out["Date"] = pd.DatetimeIndex(dates)
    if out.duplicated(["Market", "Code", "Date"]).any():
        raise DualPriceFeatureError(f"{name} has duplicate Market/Code/Date identity")
    if out.duplicated(["Code", "Date"]).any():
        raise DualPriceFeatureError(f"{name} has a duplicate Code/Date across markets")
    cross_market = set(out.groupby("Code")["Market"].nunique().loc[lambda counts: counts.gt(1)].index)
    if cross_market - continuous_cross_market_codes:
        raise DualPriceFeatureError(f"{name} has a Code on multiple markets without an explicit same-series mapping")
    if (out["Date"].dt.date > cutoff.tz_convert(TAIPEI).date()).any():
        raise DualPriceFeatureError(f"{name} contains a bar after the decision cutoff")
    out["available_at"] = out["available_at"].map(lambda value: _aware_timestamp(value, f"{name}.available_at"))
    if (out["available_at"] > cutoff).any():
        raise DualPriceFeatureError(f"{name} contains evidence available after the decision cutoff")
    if out["source_id"].map(lambda value: not isinstance(value, str) or not value.strip()).any():
        raise DualPriceFeatureError(f"{name} has an empty source_id")
    for column in (*PRICE_COLUMNS, "Volume"):
        for value in out[column].dropna():
            try:
                numeric = float(value)
            except (TypeError, ValueError) as error:
                raise DualPriceFeatureError(f"{name}.{column} has a non-numeric value") from error
            if not math.isfinite(numeric) or (column != "Volume" and numeric <= 0) or (column == "Volume" and numeric < 0):
                raise DualPriceFeatureError(f"{name}.{column} must be finite and {'positive' if column != 'Volume' else 'nonnegative'}")
        out[column] = pd.to_numeric(out[column], errors="raise")
    return out.sort_values(["Code", "Date"]).reset_index(drop=True)


def _require_matching_keys(raw: pd.DataFrame, signal: pd.DataFrame) -> None:
    keys = ["Market", "Code", "Date"]
    if not raw[keys].equals(signal[keys]):
        raise DualPriceFeatureError("raw and signal must have exactly matching Market/Code/Date keys")


def _require_matching_ohlc_nulls(raw: pd.DataFrame, signal: pd.DataFrame) -> None:
    if (raw[list(PRICE_COLUMNS)].isna() != signal[list(PRICE_COLUMNS)].isna()).any().any():
        raise DualPriceFeatureError("signal OHLC null pattern must exactly match raw OHLC")


def _require_universe_coverage(cutoff_day: date, universe: Mapping[date, frozenset[str]]) -> None:
    if cutoff_day not in universe:
        raise DualPriceFeatureError(f"universe has no explicit membership entry for cutoff date: {cutoff_day.isoformat()}")


def _aware_timestamp(value: Any, label: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise DualPriceFeatureError(f"{label} must be timezone-aware")
    return stamp


def _validate_signal_projection(attrs: Mapping[str, Any], cutoff: pd.Timestamp) -> Mapping[str, Any] | None:
    metadata = attrs.get("signal_projection")
    if metadata is None:
        return None
    if not isinstance(metadata, Mapping) or "decision_cutoff" not in metadata:
        raise DualPriceFeatureError("signal_projection must contain decision_cutoff")
    projected = _aware_timestamp(metadata["decision_cutoff"], "signal_projection.decision_cutoff")
    if projected != cutoff:
        raise DualPriceFeatureError("signal_projection.decision_cutoff must equal decision_cutoff")
    return metadata


__all__ = ["DualPriceFeatureError", "build_dual_price_features"]
