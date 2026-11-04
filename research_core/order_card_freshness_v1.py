"""Pure declared-input freshness prerequisite for future operation cards.

Contract: tasks/20261102-order-card-freshness/data-contract.md. A passing result
does not certify source truth, complete strategy inputs, or permission to trade.
There are no readers, clocks, callbacks, card generation or persistence here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Literal

import pandas as pd

from research_core import multi_timeframe_ma_weeks_v1 as calendar_evidence

DEFINITION_ID = "order-card-freshness.v1"
VALIDATION_SCOPE = "declared_metadata_consistency_only; source_authenticity_and_strategy_readiness_not_certified"
DatasetStatus = Literal["complete", "missing", "unknown", "updating"]


@dataclass(frozen=True, kw_only=True)
class DatasetRequirement:
    dataset_id: str
    definition: str
    generation: str


@dataclass(frozen=True, kw_only=True)
class DatasetObservation:
    dataset_id: str
    definition: str
    generation: str
    calendar_id: str
    universe_id: str
    as_of_session: pd.Timestamp | None
    available_at: pd.Timestamp | None
    status: DatasetStatus
    source_ref: str


@dataclass(frozen=True, kw_only=True)
class FreshnessRequest:
    expected_session: pd.Timestamp
    universe_id: str
    requirements: tuple[DatasetRequirement, ...]


@dataclass(frozen=True, kw_only=True)
class DatasetAssessment:
    requirement: DatasetRequirement
    observation: DatasetObservation | None
    reasons: tuple[str, ...]
    freshness_ready: bool


@dataclass(frozen=True, kw_only=True)
class FreshnessAssessment:
    freshness_ready: bool
    reasons: tuple[str, ...]
    expected_session: pd.Timestamp
    universe_id: str
    calendar_id: str
    decision_at: pd.Timestamp
    calendar_availability_note: str
    calendar_days: tuple[calendar_evidence.DayCoverage, ...]
    datasets: tuple[DatasetAssessment, ...]
    validation_scope: str


def _text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be explicit nonempty text")


def _date(value: object, name: str) -> None:
    if not isinstance(value, pd.Timestamp) or pd.isna(value) or value.tz is not None or value != value.normalize():
        raise ValueError(f"{name} must be a normalized timezone-naive Timestamp")


def _instant(value: pd.Timestamp, name: str) -> pd.Timestamp:
    if not isinstance(value, pd.Timestamp) or pd.isna(value) or value.tz is None:
        raise ValueError(f"{name} must be an explicit timezone-aware Timestamp")
    return value.tz_convert("Asia/Taipei")


def _requirements(request: FreshnessRequest) -> tuple[DatasetRequirement, ...]:
    if not isinstance(request, FreshnessRequest):
        raise ValueError("explicit FreshnessRequest required")
    _date(request.expected_session, "expected_session")
    _text(request.universe_id, "universe_id")
    if not isinstance(request.requirements, tuple) or not request.requirements:
        raise ValueError("requirements must be a nonempty tuple of DatasetRequirement values")
    seen: set[str] = set()
    for item in request.requirements:
        if not isinstance(item, DatasetRequirement):
            raise ValueError("explicit DatasetRequirement required")
        for field in ("dataset_id", "definition", "generation"):
            _text(getattr(item, field), f"requirement.{field}")
        if item.dataset_id in seen:
            raise ValueError("duplicate dataset requirement ID")
        seen.add(item.dataset_id)
    return tuple(sorted(request.requirements, key=lambda item: item.dataset_id))


def _observations(observations: Iterable[DatasetObservation], requirements: tuple[DatasetRequirement, ...]) -> dict[str, DatasetObservation]:
    expected = {item.dataset_id for item in requirements}
    result = {}
    for item in observations:
        if not isinstance(item, DatasetObservation):
            raise ValueError("explicit DatasetObservation required")
        for field in ("dataset_id", "definition", "generation", "calendar_id", "universe_id", "source_ref"):
            _text(getattr(item, field), f"observation.{field}")
        if item.dataset_id not in expected:
            raise ValueError("unexpected dataset observation ID")
        if item.dataset_id in result:
            raise ValueError("duplicate dataset observation ID")
        if item.status not in ("complete", "missing", "unknown", "updating"):
            raise ValueError("observation.status must be complete/missing/unknown/updating")
        if item.as_of_session is not None:
            _date(item.as_of_session, "observation.as_of_session")
        available = None if item.available_at is None else _instant(item.available_at, "observation.available_at")
        result[item.dataset_id] = replace(item, available_at=available)
    return result


def _dataset(
    requirement: DatasetRequirement, observation: DatasetObservation | None, request: FreshnessRequest, calendar: calendar_evidence.CalendarSnapshot
) -> DatasetAssessment:
    reasons: list[str] = []
    if observation is None:
        reasons.append("missing_observation")
    else:
        for field, expected in (
            ("definition", requirement.definition),
            ("generation", requirement.generation),
            ("calendar_id", calendar.calendar_id),
            ("universe_id", request.universe_id),
        ):
            if getattr(observation, field) != expected:
                reasons.append(f"{field}_mismatch")
        if observation.status != "complete":
            reasons.append(f"status_{observation.status}")
        if observation.as_of_session is None:
            reasons.append("as_of_session_unknown")
        elif observation.as_of_session != request.expected_session:
            reasons.append("as_of_session_mismatch")
        if observation.available_at is None:
            reasons.append("available_at_unknown")
        elif observation.available_at > calendar.decision_at:
            reasons.append("not_yet_available")
    return DatasetAssessment(requirement=requirement, observation=observation, reasons=tuple(reasons), freshness_ready=not reasons)


def assess_card_freshness(
    request: FreshnessRequest, calendar: calendar_evidence.CalendarSnapshot, observations: Iterable[DatasetObservation]
) -> FreshnessAssessment:
    """Withhold unless calendar coverage and every declared daily source agree.

    The expected session through the decision's Taipei civil date is assessed
    inclusively. The expected day must be a known closed session; later dates
    must be known closures. Data availability equal to the decision and a close
    exactly at that instant are permitted. Unknowns always remain diagnostic.
    """
    requirements = _requirements(request)
    if type(calendar) is not calendar_evidence.CalendarSnapshot:
        raise ValueError("explicit CalendarSnapshot required")
    calendar = calendar_evidence.CalendarSnapshot(calendar.calendar_id, calendar.decision_at, calendar.facts, calendar.availability_note)
    indexed = _observations(observations, requirements)
    decision_day = calendar.decision_at.tz_localize(None).normalize()
    reasons: list[str] = []
    days: tuple[calendar_evidence.DayCoverage, ...] = ()
    if request.expected_session > decision_day:
        reasons.append("expected_session_future")
    else:
        days = calendar_evidence.assess_calendar_range(calendar, first_day=request.expected_session, last_day=decision_day)
        expected = days[0]
        if expected.session_state != 1:
            reasons.append("expected_session_not_known_session")
        for day in days:
            reasons.extend(day.reasons)
            if day.date > request.expected_session and day.session_state == 1:
                reasons.append("newer_session")
    datasets = tuple(_dataset(item, indexed.get(item.dataset_id), request, calendar) for item in requirements)
    if any(not item.freshness_ready for item in datasets):
        reasons.append("dataset_not_ready")
    stable_reasons = tuple(dict.fromkeys(reasons))
    return FreshnessAssessment(
        freshness_ready=not stable_reasons,
        reasons=stable_reasons,
        expected_session=request.expected_session,
        universe_id=request.universe_id,
        calendar_id=calendar.calendar_id,
        decision_at=calendar.decision_at,
        calendar_availability_note=calendar.availability_note,
        calendar_days=days,
        datasets=datasets,
        validation_scope=VALIDATION_SCOPE,
    )
