"""Aligned, past-only detector inputs and explicit raw candidate observations."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias, cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

Scalar: TypeAlias = str | int | float | bool | None
FloatArray: TypeAlias = NDArray[np.float64]
StateArray: TypeAlias = NDArray[np.int8]
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Bars:
    """One stock on the common calendar; missing rows remain in position.

    Numeric arrays are private copies made read-only. Indicators must have been
    computed with the approved gap/warmup policies before constructing inputs.
    Price quality is an event overlay: this class checks numeric OHLC, not jumps.
    """

    dates: tuple[str, ...]
    columns: Mapping[str, FloatArray]
    invalid_prefix: NDArray[np.int64]

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> Bars:
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise ValueError("bars require the common DatetimeIndex")
        if frame.index.tz is not None or frame.index.hasnans or not frame.index.is_unique or not frame.index.is_monotonic_increasing:
            raise ValueError("calendar must be unique sorted naive dates")
        if any(day != day.normalize() for day in frame.index):
            raise ValueError("calendar must use midnight dates")
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(frame.columns):
            raise ValueError(f"missing bar columns: {sorted(required - set(frame.columns))}")
        if any(not pd.api.types.is_numeric_dtype(frame[name]) or pd.api.types.is_bool_dtype(frame[name]) for name in required):
            raise ValueError("bar prices and volume must be numeric, not boolean")
        columns: dict[str, FloatArray] = {}
        for name in frame.columns:
            if pd.api.types.is_numeric_dtype(frame[name]):
                values = frame[name].to_numpy(dtype=np.float64, copy=True, na_value=np.nan)
                values.setflags(write=False)
                columns[str(name)] = values
        o, h, low, c = (columns[name] for name in ("Open", "High", "Low", "Close"))
        valid = np.isfinite(o) & np.isfinite(h) & np.isfinite(low) & np.isfinite(c)
        valid &= (low > 0) & (h >= low) & (o >= low) & (o <= h) & (c >= low) & (c <= h)
        prefix = np.concatenate((np.zeros(1, dtype=np.int64), np.cumsum(~valid, dtype=np.int64)))
        prefix.setflags(write=False)
        LOGGER.debug("Detector bars: rows=%d missing/invalid=%d", len(frame), int((~valid).sum()))
        return cls(tuple(day.date().isoformat() for day in frame.index), columns, prefix)

    def __len__(self) -> int:
        return len(self.dates)

    def values(self, name: str) -> FloatArray:
        try:
            return self.columns[name]
        except KeyError as error:
            raise ValueError(f"missing supplied detector column: {name}") from error

    def complete(self, start: int, end: int, *, columns: Sequence[str] = ()) -> bool:
        """Inclusive window; no deletion or bridging of missing calendar rows."""
        if start < 0 or end < start or end >= len(self):
            return False
        if self.invalid_prefix[end + 1] != self.invalid_prefix[start]:
            return False
        return all(bool(np.isfinite(self.values(name)[start : end + 1]).all()) for name in columns)


@dataclass(frozen=True)
class DetectorEvent:
    pattern_id: str
    subtype_id: str
    t0: int
    window_start: int
    pivot: float | None
    support: float | None
    lower: float | None
    details: tuple[tuple[str, Scalar], ...] = ()

    def __post_init__(self) -> None:
        if not self.pattern_id.strip() or not self.subtype_id.strip():
            raise ValueError("pattern/subtype must be nonblank")
        if self.window_start < 0 or self.t0 < self.window_start:
            raise ValueError("invalid event calendar positions")
        for value in (self.pivot, self.support, self.lower):
            if value is not None and (not np.isfinite(value) or value <= 0):
                raise ValueError("price metadata must be positive finite or unknown")
        if len(dict(self.details)) != len(self.details):
            raise ValueError("duplicate event detail keys")
        for _, detail_value in self.details:
            if isinstance(detail_value, float) and not np.isfinite(detail_value):
                raise ValueError("detail missing values must use None")


@dataclass(frozen=True)
class DetectorScan:
    pattern_id: str
    subtype_ids: tuple[str, ...]
    states: StateArray
    events: tuple[DetectorEvent, ...]
    unknown_reasons: tuple[tuple[str, int, str], ...]


def finish_scan(
    pattern_id: str,
    subtype_ids: Sequence[str],
    states: StateArray,
    events: Sequence[DetectorEvent],
    unknown_reasons: Sequence[tuple[str, int, str]],
) -> DetectorScan:
    """Validate raw (uncooldowned) candidates; -1 unknown, 0 false, 1 true."""
    subtypes = tuple(subtype_ids)
    if not subtypes or len(set(subtypes)) != len(subtypes) or any(not value.strip() for value in subtypes):
        raise ValueError("subtypes must be unique nonblank IDs")
    if states.ndim != 2 or states.shape[1] != len(subtypes) or not np.isin(states, (-1, 0, 1)).all():
        raise ValueError("invalid detector states")
    result = np.array(states, dtype=np.int8, copy=True)
    result.setflags(write=False)
    ordered = tuple(sorted(events, key=lambda event: (event.t0, subtypes.index(event.subtype_id))))
    identities = [(event.subtype_id, event.t0) for event in ordered]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate subtype/date raw candidate")
    for event in ordered:
        if event.pattern_id != pattern_id or not 0 <= event.t0 < len(result) or result[event.t0, subtypes.index(event.subtype_id)] != 1:
            raise ValueError("event does not match its true daily state")
    expected = {(subtypes[col], int(day)) for day, col in np.argwhere(result == -1)}
    observed = {(subtype, day) for subtype, day, _ in unknown_reasons}
    if expected != observed or any(not reason.strip() for _, _, reason in unknown_reasons):
        raise ValueError("every unknown state requires its reason")
    if len(identities) != int((result == 1).sum()):
        raise ValueError("every true state requires one raw candidate")
    LOGGER.debug("%s candidates=%d unknown=%d", pattern_id, len(ordered), len(expected))
    return DetectorScan(pattern_id, subtypes, result, ordered, tuple(unknown_reasons))


def prior_mean(values: FloatArray, sessions: int) -> FloatArray:
    """Previous full window, excludes t0; missing values remain unknown."""
    return cast(pd.Series, pd.Series(values).rolling(sessions, min_periods=sessions).mean()).shift(1).to_numpy(dtype=np.float64)


def prior_max(values: FloatArray, sessions: int) -> FloatArray:
    return pd.Series(values).rolling(sessions, min_periods=sessions).max().shift(1).to_numpy(dtype=np.float64)


def prior_min(values: FloatArray, sessions: int) -> FloatArray:
    return pd.Series(values).rolling(sessions, min_periods=sessions).min().shift(1).to_numpy(dtype=np.float64)
