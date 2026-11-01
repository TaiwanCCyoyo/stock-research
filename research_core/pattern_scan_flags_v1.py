"""Fixed-event failure flags on supplied common-calendar prices and pivots."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from numbers import Integral
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.hhhl_variants_observations import classify_window, flag_history, landmark_riskset

LOGGER = logging.getLogger(__name__)
FLAG_IDS = ("Y1", "Y2", "Y3", "X5_MA20", "X5_MA60", "X6_10", "X6_15", "X7", "X8")


@dataclass(frozen=True)
class _Pivot:
    kind: str
    extreme: int
    confirmed: int
    extreme_date: str
    confirmed_at: str
    price: float


def _index(value: int, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _valid(value: float | None) -> bool:
    return value is not None and bool(np.isfinite(value) and value > 0)


def _level(value: float | None) -> float | None:
    if value is None:
        return None
    if not _valid(value):
        raise ValueError("fixed levels must be positive finite or None")
    return float(value)


def _pivots(frame: pd.DataFrame, pivots: pd.DataFrame) -> tuple[_Pivot, ...]:
    required = {"k", "kind", "extreme_index", "confirmation_index", "extreme_date", "confirmed_at", "price"}
    if not pivots.columns.is_unique or not required.issubset(pivots.columns):
        raise ValueError("pivots require the public confirmed-pivot schema")
    selected: list[_Pivot] = []
    seen: set[tuple[str, int, int]] = set()
    calendar = cast(pd.DatetimeIndex, frame.index)
    for raw_row in pivots.itertuples(index=False):
        row = cast(Any, raw_row)  # Schema and scalar values are validated at this boundary.
        extreme, confirmed = row.extreme_index, row.confirmation_index
        if isinstance(extreme, bool) or isinstance(confirmed, bool) or int(extreme) != extreme or int(confirmed) != confirmed:
            raise ValueError("pivot positions must be integers")
        extreme, confirmed = int(extreme), int(confirmed)
        if not 0 <= extreme <= confirmed < len(frame):
            raise ValueError("pivot positions must be valid ordered calendar positions")
        if pd.Timestamp(row.extreme_date) != frame.index[extreme] or pd.Timestamp(row.confirmed_at) != frame.index[confirmed]:
            raise ValueError("pivot dates must match the common calendar")
        if row.kind not in {"high", "low"} or not _valid(row.price) or not _valid(row.k):
            raise ValueError("pivot kind, price or k is invalid")
        if row.k != 1.5:
            continue
        identity = (str(row.kind), extreme, confirmed)
        if identity in seen:
            raise ValueError("duplicate confirmed pivot")
        seen.add(identity)
        selected.append(
            _Pivot(
                str(row.kind),
                extreme,
                confirmed,
                cast(pd.Timestamp, calendar[extreme]).date().isoformat(),
                cast(pd.Timestamp, calendar[confirmed]).date().isoformat(),
                float(row.price),
            )
        )
    return tuple(sorted(selected, key=lambda pivot: (pivot.confirmed, pivot.extreme, pivot.kind)))


def _compare(close: float, level: float | None, *, inclusive: bool = False) -> bool | None:
    if not _valid(close) or not _valid(level):
        return None
    assert level is not None
    return bool(close <= level if inclusive else close < level)


def event_flags(
    frame: pd.DataFrame,
    pivots: pd.DataFrame,
    t0: int,
    *,
    support: float | None = None,
    lower: float | None = None,
    confirmed_support: float | None = None,
) -> pd.DataFrame:
    """Return nullable daily flags at offsets 1..observed future length.

    Y1/Y2/Y3 and X6 levels are fixed at t0. Y3 defaults to the nearest
    strictly lower, already confirmed 1.5ATR low. X8 uses new confirmations,
    never extreme dates. Same-day highs are ordered by extreme position;
    any known lower high makes that day's flag true. A missing close between
    two confirmations makes their comparison unknown rather than bridging it.
    Result attributes retain fixed Y3 and observed/first lower-high metadata.
    No reader, benchmark, cooldown or outcome mutation runs here.
    """
    required = {"Close", "SMA20", "SMA60", "BBLower"}
    if (
        not isinstance(frame.index, pd.DatetimeIndex)
        or frame.index.tz is not None
        or frame.index.hasnans
        or not frame.index.is_unique
        or not frame.index.is_monotonic_increasing
    ):
        raise ValueError("frame requires a sorted unique naive common DatetimeIndex")
    if any(day != day.normalize() for day in frame.index) or not frame.columns.is_unique or not required.issubset(frame.columns):
        raise ValueError("frame requires midnight dates and unique required columns")
    t0 = _index(t0, "t0")
    if t0 >= len(frame):
        raise ValueError("t0 must be within the common calendar")
    support, lower, confirmed_support = (_level(value) for value in (support, lower, confirmed_support))
    return _flags_from_records(frame, _pivots(frame, pivots), t0, support=support, lower=lower, confirmed_support=confirmed_support)


def _flags_from_records(
    frame: pd.DataFrame,
    records: tuple[_Pivot, ...],
    t0: int,
    *,
    support: float | None = None,
    lower: float | None = None,
    confirmed_support: float | None = None,
) -> pd.DataFrame:
    supplied_confirmed_support = confirmed_support is not None
    support, lower, confirmed_support = (_level(value) for value in (support, lower, confirmed_support))
    close = frame["Close"].to_numpy(dtype=float, na_value=np.nan)
    anchor = float(close[t0])
    eligible_lows = [pivot for pivot in records if pivot.kind == "low" and pivot.confirmed <= t0 and _valid(anchor) and pivot.price < anchor]
    selected_low = max(eligible_lows, key=lambda pivot: (pivot.price, pivot.confirmed, pivot.extreme), default=None)
    if confirmed_support is None and selected_low is not None:
        confirmed_support = selected_low.price
    if confirmed_support is not None and _valid(anchor) and confirmed_support >= anchor:
        raise ValueError("confirmed support must be strictly below the t0 close")
    short_ma, long_ma, lower_bb = (frame[name].to_numpy(dtype=float, na_value=np.nan) for name in ("SMA20", "SMA60", "BBLower"))
    highs = [pivot for pivot in records if pivot.kind == "high"]
    by_confirmation: dict[int, list[_Pivot]] = {}
    for pivot in highs:
        by_confirmation.setdefault(pivot.confirmed, []).append(pivot)
    previous: _Pivot | None = None
    high_flags: dict[int, bool | None] = {}
    observed_lower: dict[int, dict[str, Any]] = {}
    invalid = np.concatenate(([0], np.cumsum(~(np.isfinite(close) & (close > 0)))))
    for day, new_highs in by_confirmation.items():
        comparisons: list[bool | None] = []
        for pivot in new_highs:
            known = previous is not None and invalid[day + 1] == invalid[previous.confirmed + 1] and _valid(float(close[day]))
            comparison = bool(pivot.price < previous.price) if known and previous is not None else None
            comparisons.append(comparison)
            if comparison and day > t0 and day not in observed_lower:
                assert previous is not None
                observed_lower[day] = {
                    "extreme_index": pivot.extreme,
                    "confirmation_index": day,
                    "extreme_date": pivot.extreme_date,
                    "confirmed_at": pivot.confirmed_at,
                    "price": pivot.price,
                    "previous_extreme_index": previous.extreme,
                    "previous_confirmation_index": previous.confirmed,
                    "previous_price": previous.price,
                }
            previous = pivot
        high_flags[day] = True if any(value is True for value in comparisons) else None if any(value is None for value in comparisons) else False
    vectors: dict[str, list[bool | None]] = {flag: [] for flag in FLAG_IDS}
    for day in range(t0 + 1, len(frame)):
        value = float(close[day])
        levels = {
            "Y1": support,
            "Y2": lower,
            "Y3": confirmed_support,
            "X5_MA20": float(short_ma[day]),
            "X5_MA60": float(long_ma[day]),
            "X7": float(lower_bb[day]),
        }
        for flag, level in levels.items():
            vectors[flag].append(_compare(value, level))
        for flag, fraction in (("X6_10", 0.9), ("X6_15", 0.85)):
            vectors[flag].append(_compare(value, anchor * fraction if _valid(anchor) else None, inclusive=True))
        vectors["X8"].append(high_flags.get(day, False) if _valid(value) else None)
    result = pd.DataFrame({flag: pd.array(values, dtype="boolean") for flag, values in vectors.items()}, index=pd.RangeIndex(1, len(frame) - t0, name="offset"))
    history = flag_history([None, *vectors["X8"]], len(frame) - t0 - 1)
    first_day = t0 + history.first_trigger_offset if history.first_trigger_offset is not None else None
    result.attrs["confirmed_support"] = confirmed_support
    result.attrs["confirmed_support_source"] = "caller" if supplied_confirmed_support else "confirmed_nearest_pivot"
    result.attrs["confirmed_support_pivot"] = asdict(selected_low) if selected_low is not None and selected_low.price == confirmed_support else None
    result.attrs["first_lower_high"] = {
        "state": history.state,
        "reason": history.reason,
        "first_trigger_offset": history.first_trigger_offset,
        "metadata": observed_lower.get(first_day) if first_day is not None else None,
    }
    result.attrs["first_observed_lower_high"] = observed_lower[min(observed_lower)] if observed_lower else None
    LOGGER.debug("Pattern flags t0=%d future=%d lower_high=%s", t0, len(result), history.state)
    return result


def event_flag_observations(
    frame: pd.DataFrame,
    pivots: pd.DataFrame,
    t0: int,
    *,
    support: float | None = None,
    lower: float | None = None,
    confirmed_support: float | None = None,
    horizons: Sequence[int] = (126, 252),
    landmarks: Sequence[int] = (5, 10, 20, 40),
) -> pd.DataFrame:
    """Observe nine flags using the unchanged public first-decision clocks."""
    horizon_values = tuple(_index(value, "horizon", minimum=1) for value in horizons)
    landmark_values = tuple(_index(value, "landmark", minimum=1) for value in landmarks)
    if len(set(horizon_values)) != len(horizon_values) or len(set(landmark_values)) != len(landmark_values):
        raise ValueError("horizons and landmarks must be unique")
    t0 = _index(t0, "t0")
    stop = min(len(frame), t0 + max(horizon_values, default=0) + 1)
    bounded = frame.iloc[:stop]
    if "confirmation_index" not in pivots.columns or not pivots.columns.is_unique:
        raise ValueError("pivots require the public confirmed-pivot schema")
    bounded_pivots = pivots.loc[pivots["confirmation_index"] < stop]
    flags = event_flags(bounded, bounded_pivots, t0, support=support, lower=lower, confirmed_support=confirmed_support)
    return _observations_from_flags(flags, bounded["Close"].to_numpy(dtype=float, na_value=np.nan)[t0:].tolist(), horizon_values, landmark_values)


def _observations_from_flags(
    flags: pd.DataFrame,
    closes: list[float],
    horizon_values: tuple[int, ...],
    landmark_values: tuple[int, ...],
) -> pd.DataFrame:
    vectors: dict[str, list[bool | None]] = {flag: [None, *[None if pd.isna(value) else bool(value) for value in flags[flag]]] for flag in FLAG_IDS}
    records: list[dict[str, Any]] = []
    for horizon in horizon_values:
        outcome = classify_window(closes, horizon)
        for landmark in (*[value for value in landmark_values if value < horizon], horizon):
            riskset = landmark_riskset(closes, landmark, 1.0)  # NEW riskset has no support dependency.
            for flag in FLAG_IDS:
                values = vectors[flag]
                raw = flag_history(values, landmark)
                before = flag_history(values, landmark, outcome.first_hit_offset)
                offset = before.first_trigger_offset
                trigger_return = float(closes[offset] / closes[0] - 1) if offset is not None and _valid(closes[0]) and _valid(closes[offset]) else None
                ratio = float(closes[landmark] / closes[0]) if landmark < len(closes) and _valid(closes[0]) and _valid(closes[landmark]) else None
                records.append({
                    "horizon": horizon,
                    "landmark": landmark,
                    "scope": "full" if landmark == horizon else "landmark",
                    "flag_id": flag,
                    "flag_state": before.state,
                    "first_trigger_offset": offset,
                    "unknown_reason": before.reason,
                    "through_offset": before.through_offset,
                    "trigger_return": trigger_return,
                    "raw_flag_state": raw.state,
                    "raw_first_trigger_offset": raw.first_trigger_offset,
                    "raw_unknown_reason": raw.reason,
                    "riskset_id": riskset.riskset_id,
                    "riskset_state": riskset.state,
                    "riskset_reason": riskset.reason,
                    "riskset_decision_offset": riskset.decision_offset,
                    "riskset_eligible": riskset.eligible,
                    "rise_ratio": ratio,
                    "rise_bin": None if ratio is None else "lt1" if ratio < 1 else "b1_1p10" if ratio < 1.1 else "b1p10_1p25" if ratio < 1.25 else "ge1p25",
                    "calendar_full": outcome.calendar_full,
                    "label": outcome.outcome,
                    "first_hit_offset": outcome.first_hit_offset,
                    "outcome_unknown_reason": outcome.reason,
                })
    return pd.DataFrame(records)


class _FollowupFlagPlan:
    """Per-call plan for followup's already validated, immutable stock frame.

    Parse newly visible pivots only when an event extends the observed prefix.
    Future pivots are not validated early. A later shorter horizon uses a filtered
    prefix, so preparation order cannot introduce future confirmations.
    """

    def __init__(self, frame: pd.DataFrame, pivots: pd.DataFrame) -> None:
        self.frame = frame
        self.pivots = pivots
        self.stop = 0
        self.records: tuple[_Pivot, ...] = ()

    def daily(self, t0: int, stop: int, **levels: float | None) -> pd.DataFrame:
        bounded = self.frame.iloc[:stop]
        # Preserve the original level rejection before pivot validation.
        for value in levels.values():
            _level(value)
        if stop > self.stop:
            visible = self.pivots.loc[self.pivots["confirmation_index"].lt(stop)]
            if self.stop:
                visible = visible.loc[visible["confirmation_index"].ge(self.stop)]
            added = _pivots(bounded, visible)
            self.records = tuple(sorted((*self.records, *added), key=lambda pivot: (pivot.confirmed, pivot.extreme, pivot.kind)))
            self.stop = stop
        records = tuple(pivot for pivot in self.records if pivot.confirmed < stop)
        return _flags_from_records(bounded, records, t0, **levels)

    def observations(self, daily: pd.DataFrame, t0: int, stop: int, horizon: int, landmarks: tuple[int, ...]) -> pd.DataFrame:
        closes = self.frame["Close"].iloc[t0:stop].to_numpy(dtype=float, na_value=np.nan).tolist()
        return _observations_from_flags(daily, closes, (horizon,), landmarks)
