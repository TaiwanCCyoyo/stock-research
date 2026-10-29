"""Pure S7 complete-universe density ranking and one common comparison mask.

S6 and saved original-cutoff D/W states are caller-supplied facts. This module
does not certify their source, official calendar coverage or historical PIT.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from research_core import multi_timeframe_ma_core_v1 as core

LOGGER = logging.getLogger(__name__)
MASK_REASONS = (
    "not_s6",
    "daily_bull_unknown",
    "r_current_unknown",
    "r_previous_unknown",
    "weekly_current_unknown",
    "weekly_previous_unknown",
    "weekly_density_unknown",
    "rank_pool_unavailable",
)


def _identity(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be nonempty unpadded text")


def _cutoff(value: pd.Timestamp) -> None:
    if not isinstance(value, pd.Timestamp) or pd.isna(value) or value.tz is not None or value != value.normalize():
        raise ValueError("decision_cutoff must be a normalized timezone-naive Timestamp")


def _dates(value: pd.DatetimeIndex, name: str) -> None:
    if (
        not isinstance(value, pd.DatetimeIndex)
        or not len(value)
        or value.tz is not None
        or value.hasnans
        or not value.is_unique
        or not value.is_monotonic_increasing
    ):
        raise ValueError(f"{name} must be nonempty, unique, increasing, naive and nonmissing")
    if any(day != day.normalize() for day in value):
        raise ValueError(f"{name} must contain normalized day labels")


def _state(value: int, name: str) -> None:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value not in (core.UNKNOWN, core.FALSE, core.TRUE):
        raise ValueError(f"{name} must be an integer -1/0/1, not bool")


@dataclass(frozen=True, eq=False)
class PanelRequest:
    codes: tuple[str, ...]
    generation: str
    decision_cutoff: pd.Timestamp
    universe_id: str
    calendar_id: str
    common_calendar: pd.DatetimeIndex

    def __post_init__(self) -> None:
        if type(self.codes) is not tuple or not self.codes:
            raise ValueError("codes must be a nonempty sorted unique tuple")
        for code in self.codes:
            _identity(code, "code")
        if self.codes != tuple(sorted(set(self.codes))):
            raise ValueError("codes must be sorted and unique")
        for name in ("generation", "universe_id", "calendar_id"):
            _identity(getattr(self, name), name)
        _cutoff(self.decision_cutoff)
        _dates(self.common_calendar, "common_calendar")
        if self.common_calendar[-1] != self.decision_cutoff:
            raise ValueError("common_calendar must end exactly at decision_cutoff")
        object.__setattr__(self, "common_calendar", self.common_calendar.copy(deep=True))


@dataclass(frozen=True, eq=False)
class StockFeaturePacket:
    security_id: str
    generation: str
    decision_cutoff: pd.Timestamp
    universe_id: str
    calendar_id: str
    s6: bool
    daily_state_dates: pd.DatetimeIndex
    daily_states: NDArray[np.int8]
    w_current: int
    w_previous: int
    weekly_series: core.CutoffSeries
    weekly_ma: core.MovingAverages

    def __post_init__(self) -> None:
        for name in ("security_id", "generation", "universe_id", "calendar_id"):
            _identity(getattr(self, name), name)
        _cutoff(self.decision_cutoff)
        if not isinstance(self.s6, (bool, np.bool_)):
            raise ValueError("s6 must be a known boolean")
        _dates(self.daily_state_dates, "daily_state_dates")
        states = self.daily_states
        if type(states) is not np.ndarray or states.ndim != 1 or states.dtype != np.dtype("int8") or len(states) != len(self.daily_state_dates):
            raise ValueError("daily_states must be exact int8, one-dimensional and aligned to daily_state_dates")
        if not np.isin(states, (core.UNKNOWN, core.FALSE, core.TRUE)).all():
            raise ValueError("daily_states must contain only -1/0/1")
        _state(self.w_current, "w_current")
        _state(self.w_previous, "w_previous")
        if not isinstance(self.weekly_series, core.CutoffSeries) or not isinstance(self.weekly_ma, core.MovingAverages):
            raise ValueError("weekly inputs must be core CutoffSeries and MovingAverages")
        object.__setattr__(self, "s6", bool(self.s6))
        object.__setattr__(self, "daily_state_dates", self.daily_state_dates.copy(deep=True))
        # Immutable bytes also prevent callers from re-enabling this copy's writes.
        object.__setattr__(self, "daily_states", np.frombuffer(states.tobytes(), dtype=np.int8))


@dataclass(frozen=True)
class StockPanelState:
    security_id: str
    s6: bool
    p_member: bool
    density: float | None
    rank_percentile: float | None
    dense: int
    daily_state: int
    ratio: float | None
    previous_ratio: float | None
    cross50: int
    cross70: int
    w_current: int
    w_previous: int
    mask_reasons: tuple[str, ...]
    density_reasons: tuple[str, ...]


@dataclass(frozen=True)
class PanelCoverage:
    s6_n: int
    m_n: int
    excluded_s6_n: int
    outside_s6_n: int
    reason_counts_within_s6: tuple[tuple[str, int], ...]
    pool_n: int


@dataclass(frozen=True)
class PanelAtCutoff:
    codes: tuple[str, ...]
    generation: str
    decision_cutoff: pd.Timestamp
    universe_id: str
    calendar_id: str
    pool_status: Literal["ranked", "empty"]
    pool_n: int
    stocks: tuple[StockPanelState, ...]
    # The single M vector, in codes/stocks order; no per-arm mask is accepted.
    m: tuple[bool, ...]
    coverage: PanelCoverage


def _check_packet(request: PanelRequest, packet: StockFeaturePacket) -> None:
    for name in ("generation", "decision_cutoff", "universe_id", "calendar_id"):
        if getattr(packet, name) != getattr(request, name):
            raise ValueError(f"packet {name} differs from panel request")
    expected = request.common_calendar[-min(21, len(request.common_calendar)) :]
    if not packet.daily_state_dates.equals(expected):
        raise ValueError("daily_state_dates must exactly equal the common_calendar last min(21,n) positions")
    series = packet.weekly_series
    if series.bar_kind != "completed_weekly" or series.price_basis != "reference_factor_adjusted":
        raise ValueError("weekly_series must be completed_weekly reference_factor_adjusted")
    for name in ("security_id", "generation", "decision_cutoff"):
        if getattr(series, name) != getattr(packet, name):
            raise ValueError(f"weekly_series {name} differs from packet")


def _density(packet: StockFeaturePacket) -> core.DensityState:
    # Public core call enforces exact series/MA object lineage; no private check.
    density = core.density_at_cutoff(packet.weekly_series, packet.weekly_ma)
    if density.known:
        if density.density is None or not np.isfinite(density.density) or density.density < 0:
            raise ValueError("known core density must be finite and nonnegative")
        if density.denominator is None or not np.isfinite(density.denominator) or density.denominator <= 0:
            raise ValueError("known core density requires a positive finite denominator")
        if len(density.values) != 6 or any(value is None or not np.isfinite(value) for value in density.values):
            raise ValueError("known core density requires six finite averages")
    return density


def _optional(value: np.float64) -> float | None:
    return float(value) if np.isfinite(value) else None


def evaluate_panel(request: PanelRequest, packets: Iterable[StockFeaturePacket]) -> PanelAtCutoff:
    """Validate all codes, rank P, then derive M without outcomes or candidates.

    Missing/duplicate/extra packets or mixed lineage raise ValueError, producing
    no partial panel. Unknown feature operands retain overlapping reasons.
    """
    if not isinstance(request, PanelRequest):
        raise ValueError("request must be PanelRequest")
    by_code: dict[str, StockFeaturePacket] = {}
    for packet in packets:
        if not isinstance(packet, StockFeaturePacket):
            raise ValueError("every packet must be StockFeaturePacket")
        if packet.security_id in by_code:
            raise ValueError("duplicate packet security_id")
        _check_packet(request, packet)
        by_code[packet.security_id] = packet
    if set(by_code) != set(request.codes):
        raise ValueError("complete-universe barrier requires exactly one packet per requested code")
    ordered = tuple(by_code[code] for code in request.codes)
    densities = tuple(_density(packet) for packet in ordered)
    ratios = tuple(core.ratio_cross(packet.daily_states) for packet in ordered)
    pool = [i for i, packet in enumerate(ordered) if packet.s6 and densities[i].known]
    ranks = pd.Series([densities[i].density for i in pool], dtype="float64").rank(method="average", pct=True)
    percentiles = {i: float(rank) for i, rank in zip(pool, ranks)}
    rows: list[StockPanelState] = []
    mask: list[bool] = []
    for i, packet in enumerate(ordered):
        density, ratio = densities[i], ratios[i]
        current_r, previous_r = _optional(ratio.ratio[-1]), _optional(ratio.previous_ratio[-1])
        reasons = tuple(
            name
            for name, missing in zip(
                MASK_REASONS,
                (
                    not packet.s6,
                    packet.daily_states[-1] == core.UNKNOWN,
                    current_r is None,
                    previous_r is None,
                    packet.w_current == core.UNKNOWN,
                    packet.w_previous == core.UNKNOWN,
                    not density.known,
                    not pool,
                ),
            )
            if missing
        )
        percentile = percentiles.get(i)
        rows.append(
            StockPanelState(
                security_id=packet.security_id,
                s6=packet.s6,
                p_member=i in percentiles,
                density=float(density.density) if density.known and density.density is not None else None,
                rank_percentile=percentile,
                dense=core.UNKNOWN if percentile is None else int(percentile <= 0.10),
                daily_state=int(packet.daily_states[-1]),
                ratio=current_r,
                previous_ratio=previous_r,
                cross50=int(ratio.cross50[-1]),
                cross70=int(ratio.cross70[-1]),
                w_current=int(packet.w_current),
                w_previous=int(packet.w_previous),
                mask_reasons=reasons,
                density_reasons=tuple(density.reasons),
            )
        )
        mask.append(not reasons)
    s6_n, m_n = sum(packet.s6 for packet in ordered), sum(mask)
    coverage = PanelCoverage(
        s6_n=s6_n,
        m_n=m_n,
        excluded_s6_n=s6_n - m_n,
        outside_s6_n=len(ordered) - s6_n,
        reason_counts_within_s6=tuple((name, sum(row.s6 and name in row.mask_reasons for row in rows)) for name in MASK_REASONS),
        pool_n=len(pool),
    )
    LOGGER.debug("S7 panel cutoff=%s universe_n=%d pool_n=%d m_n=%d", request.decision_cutoff, len(ordered), len(pool), m_n)
    return PanelAtCutoff(
        codes=request.codes,
        generation=request.generation,
        decision_cutoff=request.decision_cutoff,
        universe_id=request.universe_id,
        calendar_id=request.calendar_id,
        pool_status="ranked" if pool else "empty",
        pool_n=len(pool),
        stocks=tuple(rows),
        m=tuple(mask),
        coverage=coverage,
    )
