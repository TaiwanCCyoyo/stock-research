"""Causal forward index plus existing canonical six features, never execution prices."""

from __future__ import annotations

import math
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd

SIGNAL_ROOT = Path(__file__).resolve().parents[1] / "010-membership-signal"
if str(SIGNAL_ROOT) not in sys.path:
    sys.path.insert(0, str(SIGNAL_ROOT))

from asof_signal_prices import Adjustment, FactorCoverage, instant  # noqa: E402
from dual_price_features import _validate_frame  # noqa: E402
from prototype.features_bridge import (  # noqa: E402
    LIQ_FLOOR,
    MIN_HISTORY,
    SIX_FEATURES,
    SIX_RANK_COLUMNS,
    canonical_table,
    rank_within_universe,
    strictly_prior_eligibility,
)

POLICY_ID = "causal-forward-reference-index-v1"
TAIPEI = timezone(timedelta(hours=8))
OHLC = ("Open", "High", "Low", "Close")


class FeaturePanelError(ValueError):
    """The declared causal input scope is not supported or complete."""


def evening(day: date) -> datetime:
    return datetime.combine(day, time(20), tzinfo=TAIPEI)


def forward_signal(
    raw: pd.DataFrame,
    adjustments: Sequence[Adjustment],
    coverage: Sequence[FactorCoverage],
    *,
    policy_id: str,
    continuous_cross_market_codes: frozenset[str] = frozenset(),
) -> pd.DataFrame:
    """Price-index representation using only each bar's effective event prefix."""
    if policy_id != POLICY_ID or raw.empty:
        raise FeaturePanelError("explicit representation policy and nonempty raw frame required")
    last_day = pd.to_datetime(raw["Date"]).max().date()
    out = _validate_frame(raw, "raw", pd.Timestamp(evening(last_day)), continuous_cross_market_codes)
    if any(instant(at) > evening(day.date()) for at, day in zip(out["available_at"], out["Date"], strict=True)):
        raise FeaturePanelError("raw observation was unavailable on its own decision evening")
    claims: dict[str, FactorCoverage] = {}
    for claim in coverage:
        if claim.code in claims:
            raise FeaturePanelError("duplicate coverage claim")
        claims[claim.code] = claim
    applied: dict[str, list[str]] = {}
    for code, group in out.groupby("Code", sort=False):
        first, last = group["Date"].min().date(), group["Date"].max().date()
        claim = claims.get(code)
        if (
            claim is None
            or claim.complete is not True
            or not claim.source_id.strip()
            or claim.effective_from > first
            or claim.effective_through < last
            or instant(claim.available_at) > evening(first)
        ):
            raise FeaturePanelError(f"explicit factor coverage missing for {code}")
        events = sorted((event for event in adjustments if event.code == code and first < event.effective_on <= last), key=lambda item: item.effective_on)
        if len({event.event_id for event in events}) != len(events) or len({event.effective_on for event in events}) != len(events):
            raise FeaturePanelError("overlapping adjustment/revision factors")
        product = Fraction(1)
        scales = pd.Series(1.0, index=group.index)
        applied[code] = []
        for event in events:
            factor = event.prior_price_multiplier
            if (
                not event.event_id
                or not event.source_id
                or factor is None
                or not factor.is_finite()
                or factor <= 0
                or event.available_at is None
                or instant(event.available_at) > evening(event.effective_on)
            ):
                raise FeaturePanelError(f"unresolved or late adjustment: {event.event_id}")
            product *= Fraction(factor)
            scale = float(1 / product)
            if not math.isfinite(scale) or scale <= 0:
                raise FeaturePanelError("nonfinite index scale")
            scales.loc[group["Date"].dt.date >= event.effective_on] = scale
            applied[code].append(event.event_id)
        out.loc[group.index, list(OHLC)] = group[list(OHLC)].mul(scales, axis=0)
    prices = out[list(OHLC)].to_numpy(dtype=float)
    if np.isinf(prices).any() or (prices <= 0).any():
        raise FeaturePanelError("nonfinite or nonpositive signal index")
    out.attrs["signal_index"] = {"policy_id": policy_id, "applied_event_ids": applied, "price_role": "features_only_not_execution"}
    return out


def build_feature_panel(
    raw: pd.DataFrame,
    adjustments: Sequence[Adjustment],
    coverage: Sequence[FactorCoverage],
    *,
    universe: Mapping[date, frozenset[str]],
    membership_basis: str,
    policy_id: str,
    raw_volume_unit: str,
    continuous_cross_market_codes: frozenset[str] = frozenset(),
) -> pd.DataFrame:
    """One causal panel, then the same strict raw eligibility and dated ranks as 010."""
    if raw_volume_unit != "shares" or not membership_basis.strip():
        raise FeaturePanelError("explicit share unit and membership basis required")
    signal = forward_signal(raw, adjustments, coverage, policy_id=policy_id, continuous_cross_market_codes=continuous_cross_market_codes)
    last_day = pd.to_datetime(raw["Date"]).max().date()
    raw_sorted = _validate_frame(raw, "raw", pd.Timestamp(evening(last_day)), continuous_cross_market_codes)
    if any(day not in universe for day in raw_sorted["Date"].dt.date.unique()):
        raise FeaturePanelError("missing daily membership scope")
    prices = ["Code", "Date", *OHLC, "Volume"]
    raw_lots = raw_sorted[prices].copy()
    raw_lots["Volume"] = raw_lots["Volume"] / 1000.0
    eligibility = strictly_prior_eligibility(raw_lots)
    valid_prior = raw_lots["Close"].notna().groupby(raw_lots["Code"], sort=False).transform(lambda values: values.cumsum().shift(1, fill_value=0))
    signal_lots = signal[prices].copy()
    signal_lots["Volume"] = signal_lots["Volume"] / 1000.0
    table = canonical_table(signal_lots)
    table["raw_prior_rows"] = eligibility["prior_bars"].to_numpy()
    table["raw_prior_bars"] = valid_prior.to_numpy()
    table["raw_liquidity"] = eligibility["liquidity"].to_numpy()
    table["raw_eligible"] = (table["raw_prior_bars"] >= MIN_HISTORY) & (table["raw_liquidity"] >= LIQ_FLOOR)
    table["current_data_valid"] = raw_sorted[list(OHLC)].notna().all(axis=1).to_numpy() & (raw_sorted["Volume"].to_numpy() > 0)
    table["six_features_finite"] = np.isfinite(table[list(SIX_FEATURES)].to_numpy(dtype=float)).all(axis=1)
    valid = pd.Series(True, index=signal.index)
    for column, window in {"High": 73, "Low": 73, "Close": 74, "Volume": 21}.items():
        valid &= (
            signal[column]
            .notna()
            .groupby(signal["Code"], sort=False)
            .transform(lambda values, size=window: values.rolling(size, min_periods=size).sum().eq(size))
        )
    table["feature_inputs_valid"] = valid.to_numpy()
    table["eligible"] = table["raw_eligible"] & table["current_data_valid"] & table["six_features_finite"] & table["feature_inputs_valid"]
    result = rank_within_universe(table, universe, membership_basis=membership_basis)
    result.loc[~result["eligible"], list(SIX_RANK_COLUMNS)] = float("nan")
    result = result.drop(columns=[name for name in result if name.startswith("cohort_") or name.startswith("r_cohort_")])
    result.attrs["signal_index"] = signal.attrs["signal_index"]
    return result
