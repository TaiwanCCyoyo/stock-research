"""Pure in-memory alignment boundary for entry-window.v1 (E1-B2b).

Callers supply every calendar position and every canonical label. Metadata is an
upstream declaration, not independent source, coverage or historical PIT proof.
No loader, default root, label construction or execution inference lives here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from research_core import entry_window_v1 as entry
from research_core import momentum_only_v1 as canonical

DEFINITION_ID = "entry-window-inputs.v1"


@dataclass(frozen=True, kw_only=True)
class InputRequest:
    security_id: str
    generation: str
    study_as_of: pd.Timestamp
    common_calendar: pd.DatetimeIndex
    universe_id: str
    calendar_id: str


@dataclass(frozen=True, kw_only=True)
class _Packet:
    security_id: str
    generation: str
    study_as_of: pd.Timestamp
    calendar: pd.DatetimeIndex
    universe_id: str
    calendar_id: str
    source: str


@dataclass(frozen=True, kw_only=True)
class CanonicalPacket(_Packet):
    stock: canonical.StockDaily
    definition: str
    basis: str
    availability_note: str


@dataclass(frozen=True, kw_only=True)
class RawQuotePacket(_Packet):
    basis: str
    raw_open: NDArray[np.float64]
    raw_high: NDArray[np.float64]
    raw_low: NDArray[np.float64]
    raw_close: NDArray[np.float64]


@dataclass(frozen=True, kw_only=True)
class IntervalPacket(_Packet):
    """States at i describe (t_i,t_{i+1}], never the previous interval.

    Coverage: 1 explicit whole-interval coverage, 0 known incomplete, -1 unknown.
    A known event may survive incomplete coverage; that does not make it clean.
    The final row has no next session regardless of its declared states.
    """

    action_to_next: NDArray[np.int8]
    event_quality_to_next: NDArray[np.int8]
    quote_quality_to_next: NDArray[np.int8]
    event_coverage: NDArray[np.int8]
    coverage_note: str


@dataclass(frozen=True, kw_only=True)
class OfficialLimitsPacket(_Packet):
    """Official raw bounds and quality indexed on their quote session."""

    basis: str
    lower: NDArray[np.float64]
    upper: NDArray[np.float64]
    quality: NDArray[np.int8]


@dataclass(frozen=True)
class StagedInputs:
    """Validated, borrowed inputs: the caller must not mutate them during use.

    Staging never sorts, casts, fills, copies labels, or writes input arrays. The
    immutable record contains metadata only, not price/label vectors or a verdict.
    """

    calendar: pd.DatetimeIndex
    stock: canonical.StockDaily
    quotes: entry.Quotes
    alignment_record: Mapping[str, str | int | None]


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an explicit nonempty string")


def _date(value: pd.Timestamp, name: str) -> None:
    if not isinstance(value, pd.Timestamp) or pd.isna(value) or value.tz is not None or value != value.normalize():
        raise ValueError(f"{name} must be a normalized timezone-naive Timestamp without NaT")


def _calendar(value: pd.DatetimeIndex, name: str) -> None:
    if not isinstance(value, pd.DatetimeIndex) or value.tz is not None or value.hasnans:
        raise ValueError(f"{name} must be an explicit timezone-naive DatetimeIndex without NaT")
    if not value.is_unique or not value.is_monotonic_increasing or not value.equals(pd.DatetimeIndex(pd.Series(value).dt.normalize())):
        raise ValueError(f"{name} must contain unique increasing normalized session dates")
    if len(value) and canonical.calendar_years(value)[0] < 2010:
        raise ValueError(f"{name} must use entry-window eras (2010+)")


def _identity(request: InputRequest, packet: _Packet, name: str) -> None:
    for field in ("security_id", "generation", "universe_id", "calendar_id"):
        value = getattr(packet, field)
        _text(value, f"{name}.{field}")
        if value != getattr(request, field):
            raise ValueError(f"{name}.{field} differs from request")
    _date(packet.study_as_of, f"{name}.study_as_of")
    if packet.study_as_of != request.study_as_of:
        raise ValueError(f"{name}.study_as_of differs from request")
    _text(packet.source, f"{name}.source")
    _calendar(packet.calendar, f"{name}.calendar")
    if not packet.calendar.equals(request.common_calendar):
        raise ValueError(f"{name}.calendar differs from request at original positions")


def _vector(values: np.ndarray, n: int, name: str, kind: str, states: tuple[int, ...] | None = None) -> None:
    if not isinstance(values, np.ndarray) or values.ndim != 1 or len(values) != n or values.dtype.kind not in kind:
        raise ValueError(f"{name} must be a one-dimensional {kind} array of length {n}")
    if states is not None and not np.isin(values, states).all():
        raise ValueError(f"{name} contains an invalid state")


def _prices(values: NDArray[np.float64], n: int, name: str) -> None:
    _vector(values, n, name, "f")
    if values.dtype != np.dtype(np.float64):
        raise ValueError(f"{name} must have dtype np.float64; staging never casts prices")


def _stock(stock: canonical.StockDaily, request: InputRequest) -> None:
    """Check the full public StockDaily contract without calculating outcomes."""
    if not isinstance(stock, canonical.StockDaily) or stock.code != request.security_id:
        raise ValueError("canonical.stock security ID differs from request")
    n = len(request.common_calendar)
    for field in ("eligible", "jump", "c52w"):
        _vector(getattr(stock, field), n, f"canonical.stock.{field}", "b")
    _vector(stock.ret120, n, "canonical.stock.ret120", "f")
    if not {"A1", "A2", "A3"}.issubset(stock.atoms):
        raise ValueError("canonical.stock requires A1, A2, A3 atoms")
    for name, values in stock.atoms.items():
        _vector(values, n, f"canonical.stock.atoms[{name}]", "iu", (-1, 0, 1))
    for horizon in canonical.HORIZONS:
        if horizon not in stock.calendar_full:
            raise ValueError(f"canonical.stock missing calendar_full[{horizon}]")
        _vector(stock.calendar_full[horizon], n, f"canonical.stock.calendar_full[{horizon}]", "b")
    for label in canonical.LABELS:
        if label not in stock.labels or label not in stock.main_eligible:
            raise ValueError(f"canonical.stock missing label or main_eligible[{label}]")
        _vector(stock.labels[label], n, f"canonical.stock.labels[{label}]", "iu", (0, 1, 2, 3))
        _vector(stock.main_eligible[label], n, f"canonical.stock.main_eligible[{label}]", "b")


def stage_stock_inputs(
    request: InputRequest,
    *,
    canonical: CanonicalPacket,
    raw: RawQuotePacket,
    intervals: IntervalPacket,
    limits: OfficialLimitsPacket | None = None,
) -> StagedInputs:
    """Validate exact identities/calendar and assemble B1 inputs without I/O.

    Metadata consistency does not prove a real source or complete event coverage.
    Missing/nonpositive float64 bars stay in place for B1's Q/diagnostics. Nothing
    interprets an empty event table or factor=1 as evidence of no action.
    """
    for field in ("security_id", "generation", "universe_id", "calendar_id"):
        _text(getattr(request, field), f"request.{field}")
    _date(request.study_as_of, "request.study_as_of")
    _calendar(request.common_calendar, "request.common_calendar")
    for name, packet in (("canonical", canonical), ("raw", raw), ("intervals", intervals)):
        _identity(request, packet, name)
    if canonical.definition != "momentum-only.v1" or canonical.basis != "reference_factor_adjusted":
        raise ValueError("canonical requires momentum-only.v1 and reference_factor_adjusted basis")
    _text(canonical.availability_note, "canonical.availability_note")
    if raw.basis != "raw":
        raise ValueError("raw requires raw basis")
    _stock(canonical.stock, request)
    n = len(request.common_calendar)
    for field in ("raw_open", "raw_high", "raw_low", "raw_close"):
        _prices(getattr(raw, field), n, f"raw.{field}")
    for field in ("action_to_next", "event_quality_to_next", "quote_quality_to_next", "event_coverage"):
        _vector(getattr(intervals, field), n, f"intervals.{field}", "iu", (-1, 0, 1))
    if intervals.event_coverage.dtype != np.dtype(np.int8):
        raise ValueError("intervals.event_coverage must have dtype np.int8")
    _text(intervals.coverage_note, "intervals.coverage_note")
    claims_complete = (intervals.action_to_next[:-1] == 0) | (intervals.event_quality_to_next[:-1] == 1)
    if np.any(claims_complete & (intervals.event_coverage[:-1] != 1)):
        raise ValueError("no-action or good event quality requires explicit full interval event_coverage=1")
    official = None
    if limits is not None:
        _identity(request, limits, "limits")
        if limits.basis != "raw":
            raise ValueError("official limits require raw basis")
        _prices(limits.lower, n, "limits.lower")
        _prices(limits.upper, n, "limits.upper")
        _vector(limits.quality, n, "limits.quality", "iu", (-1, 0, 1))
        official = entry.OfficialLimits(limits.source, limits.lower, limits.upper, limits.quality)
    quotes = entry.Quotes(
        request.security_id,
        request.common_calendar,
        raw.raw_open,
        raw.raw_high,
        raw.raw_low,
        raw.raw_close,
        intervals.action_to_next,
        intervals.event_quality_to_next,
        intervals.quote_quality_to_next,
        official,
    )
    record: dict[str, str | int | None] = {
        "definition": DEFINITION_ID,
        "security_id": request.security_id,
        "generation": request.generation,
        "study_as_of": request.study_as_of.date().isoformat(),
        "universe_id": request.universe_id,
        "calendar_id": request.calendar_id,
        "session_count": n,
        "calendar_alignment": "exact_original_positions",
        "interval_index": "t: (t,t1] on common_calendar",
        "canonical_definition": canonical.definition,
        "canonical_basis": canonical.basis,
        "canonical_source": canonical.source,
        "canonical_availability_note": canonical.availability_note,
        "raw_basis": raw.basis,
        "raw_source": raw.source,
        "interval_source": intervals.source,
        "event_coverage_note": intervals.coverage_note,
        "official_limits_source": None if limits is None else limits.source,
        "validation_scope": "metadata_consistency_only; source_and_coverage_not_independently_verified",
    }
    return StagedInputs(request.common_calendar, canonical.stock, quotes, MappingProxyType(record))
