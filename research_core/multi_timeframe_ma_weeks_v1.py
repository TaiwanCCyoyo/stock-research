"""Pure single-week calendar evidence and adjusted-close aggregation for S7.

The caller selects the applicable official fact versions. Their metadata does
not certify source authenticity or historical PIT completeness. No calendar
loader, first-confirmation clock, cross-week assembler or signal lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as civil_date
from typing import Literal, cast

import numpy as np
import pandas as pd

from research_core.multi_timeframe_ma_core_v1 import CutoffSeries

DEFINITION_ID = "multi-timeframe-ma-weeks.v1"
WeekStatus = Literal["unknown", "incomplete", "complete", "closed_no_sessions"]
BarStatus = Literal["withheld_calendar", "empty_closed_week", "valid_bar", "invalid_bar"]


def _text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be explicit nonempty text")


def _date(value: pd.Timestamp) -> None:
    if not isinstance(value, pd.Timestamp) or pd.isna(value) or value.tz is not None or value != value.normalize():
        raise ValueError("fact.date must be a normalized timezone-naive Timestamp")


def _taipei(value: pd.Timestamp, name: str) -> pd.Timestamp:
    if not isinstance(value, pd.Timestamp) or pd.isna(value) or value.tz is None:
        raise ValueError(f"{name} must be an explicit timezone-aware Timestamp")
    return value.tz_convert("Asia/Taipei")


@dataclass(frozen=True)
class CalendarFact:
    date: pd.Timestamp
    session_state: int
    known_at: pd.Timestamp | None
    close_at: pd.Timestamp | None
    source_ref: str | None

    def __post_init__(self) -> None:
        _date(self.date)
        if type(self.session_state) is not int or self.session_state not in (-1, 0, 1):
            raise ValueError("session_state must be an int -1/0/1, not bool or float")
        if self.known_at is not None:
            object.__setattr__(self, "known_at", _taipei(self.known_at, "known_at"))
        if self.close_at is not None:
            close = _taipei(self.close_at, "close_at")
            if self.session_state == 0:
                raise ValueError("closed facts cannot carry close_at")
            if self.session_state == 1 and close.tz_localize(None).normalize() != self.date:
                raise ValueError("session close_at must fall on fact.date in Asia/Taipei")
            object.__setattr__(self, "close_at", close)
        if self.session_state in (0, 1) or self.source_ref is not None:
            _text(self.source_ref, "source_ref")


@dataclass(frozen=True)
class CalendarSnapshot:
    calendar_id: str
    decision_at: pd.Timestamp
    facts: tuple[CalendarFact, ...]
    availability_note: str

    def __post_init__(self) -> None:
        _text(self.calendar_id, "calendar_id")
        _text(self.availability_note, "availability_note")
        object.__setattr__(self, "decision_at", _taipei(self.decision_at, "decision_at"))
        if not isinstance(self.facts, tuple) or any(type(fact) is not CalendarFact for fact in self.facts):
            raise ValueError("facts must be an explicit tuple of CalendarFact values")
        if any(left.date >= right.date for left, right in zip(self.facts, self.facts[1:])):
            raise ValueError("facts must have unique increasing dates; no sorting or latest-wins")


@dataclass(frozen=True)
class DayCoverage:
    date: pd.Timestamp
    declared_state: int | None
    session_state: int
    known_at: pd.Timestamp | None
    close_at: pd.Timestamp | None
    source_ref: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WeekAssessment:
    calendar_id: str
    decision_at: pd.Timestamp
    availability_note: str
    week_id: tuple[int, int]
    days: tuple[DayCoverage, ...]
    required_session_dates: tuple[pd.Timestamp, ...]
    last_session_date: pd.Timestamp | None
    status: WeekStatus
    reasons: tuple[str, ...]
    _snapshot: CalendarSnapshot = field(repr=False, compare=False)


def _coverage(day: pd.Timestamp, fact: CalendarFact | None, decision: pd.Timestamp) -> DayCoverage:
    if fact is None:
        return DayCoverage(day, None, -1, None, None, None, ("missing_fact",))
    reasons: list[str] = []
    if fact.session_state == -1:
        reasons.append("session_state_unknown")
    if fact.known_at is None:
        reasons.append("known_at_unknown")
    elif fact.known_at > decision:
        reasons.append("fact_not_yet_known")
    state = -1 if reasons else fact.session_state
    if state == 1:
        if fact.close_at is None:
            reasons.append("session_close_unknown")
        elif fact.close_at > decision:
            reasons.append("session_not_closed")
    return DayCoverage(day, fact.session_state, state, fact.known_at, fact.close_at, fact.source_ref, tuple(reasons))


def assess_week(snapshot: CalendarSnapshot, *, iso_year: int, iso_week: int) -> WeekAssessment:
    """Assess all seven civil days at one aware decision, without price inference.

    Unknown coverage takes precedence over an unclosed session. A partial known
    session list never certifies a completed week. Last-session identity is only
    resolved once all seven days and session close times are known.
    """
    if type(snapshot) is not CalendarSnapshot:
        raise TypeError("snapshot must be CalendarSnapshot")
    if type(iso_year) is not int or type(iso_week) is not int:
        raise ValueError("iso_year and iso_week must be ints, not bool or float")
    monday = cast(pd.Timestamp, pd.Timestamp(civil_date.fromisocalendar(iso_year, iso_week, 1)))
    week_dates = tuple(cast(pd.Timestamp, monday + pd.Timedelta(days=i)) for i in range(7))
    week_facts = tuple(fact for fact in snapshot.facts if monday <= fact.date <= week_dates[-1])
    facts = {fact.date: fact for fact in week_facts}
    days = tuple(_coverage(day, facts.get(day), snapshot.decision_at) for day in week_dates)
    sessions = tuple(day.date for day in days if day.session_state == 1)
    unknown = any(day.session_state == -1 or "session_close_unknown" in day.reasons for day in days)
    status: WeekStatus
    if unknown:
        status = "unknown"
    elif any("session_not_closed" in day.reasons for day in days):
        status = "incomplete"
    elif sessions:
        status = "complete"
    else:
        status = "closed_no_sessions"
    return WeekAssessment(
        snapshot.calendar_id,
        snapshot.decision_at,
        snapshot.availability_note,
        (iso_year, iso_week),
        days,
        sessions,
        sessions[-1] if sessions and not unknown else None,
        status,
        tuple(f"{day.date.date().isoformat()}:{reason}" for day in days for reason in day.reasons),
        CalendarSnapshot(snapshot.calendar_id, snapshot.decision_at, week_facts, snapshot.availability_note),
    )


@dataclass(frozen=True)
class SessionPriceAssessment:
    date: pd.Timestamp
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WeeklyBarAssessment:
    security_id: str
    generation: str
    decision_cutoff: pd.Timestamp
    price_basis: str
    calendar_id: str
    decision_at: pd.Timestamp
    availability_note: str
    week_id: tuple[int, int]
    calendar_status: WeekStatus
    status: BarStatus
    has_bar: bool
    bar_valid: bool
    close: float | None
    last_session_date: pd.Timestamp | None
    required_session_dates: tuple[pd.Timestamp, ...]
    prices: tuple[SessionPriceAssessment, ...]
    ignored_non_session_dates: tuple[pd.Timestamp, ...]
    reasons: tuple[str, ...]


def aggregate_week(daily_series: CutoffSeries, assessment: WeekAssessment) -> WeeklyBarAssessment:
    """Retain a complete week's position even when any required price is invalid.

    Only complete weeks inspect required prices. Unknown/incomplete and zero-
    session weeks have no bar. Explicitly closed in-week quotes are diagnostic
    only. This function does not join weeks or decide first confirmation.
    """
    if type(assessment) is not WeekAssessment or type(assessment._snapshot) is not CalendarSnapshot:
        raise TypeError("assessment must be produced by assess_week")
    if type(assessment.week_id) is not tuple or len(assessment.week_id) != 2:
        raise ValueError("assessment week_id must contain its ISO year and week")
    expected = assess_week(assessment._snapshot, iso_year=assessment.week_id[0], iso_week=assessment.week_id[1])
    if assessment != expected:
        raise ValueError("assessment differs from its seven-day evidence, week or decision cutoff")
    if not isinstance(daily_series, CutoffSeries):
        raise TypeError("daily_series must be CutoffSeries")
    if daily_series.bar_kind != "daily":
        raise ValueError("aggregate_week requires daily bar_kind")
    # Reuse the public constructor's exact dtype/date/basis contract and take a
    # private input snapshot. No core private helper or reader is imported.
    series = CutoffSeries(
        daily_series.security_id,
        daily_series.generation,
        daily_series.decision_cutoff,
        daily_series.price_basis,
        daily_series.bar_kind,
        daily_series.bar_dates,
        daily_series.close,
        daily_series.valid,
    )
    if series.decision_cutoff != assessment.decision_at.tz_localize(None).normalize():
        raise ValueError("daily decision_cutoff must equal decision_at's Asia/Taipei date")
    closed = {day.date for day in assessment.days if day.session_state == 0}
    ignored = tuple(day for day in series.bar_dates if day in closed)
    prices: list[SessionPriceAssessment] = []
    close: float | None = None
    has_bar = assessment.status == "complete"
    status: BarStatus
    if not has_bar:
        status = "empty_closed_week" if assessment.status == "closed_no_sessions" else "withheld_calendar"
        reasons = (status,) + assessment.reasons
    else:
        positions = {day: i for i, day in enumerate(series.bar_dates)}
        for day in assessment.required_session_dates:
            causes: list[str] = []
            position = positions.get(day)
            if position is None:
                causes.append("missing_price")
            else:
                if not series.valid[position]:
                    causes.append("invalid_upstream")
                value = series.close[position]
                if not np.isfinite(value):
                    causes.append("nonfinite_close")
                elif value <= 0:
                    causes.append("nonpositive_close")
            prices.append(SessionPriceAssessment(day, tuple(causes)))
        reasons = tuple(f"{price.date.date().isoformat()}:{reason}" for price in prices for reason in price.reasons)
        status = "invalid_bar" if reasons else "valid_bar"
        if status == "valid_bar":
            close = float(series.close[positions[assessment.required_session_dates[-1]]])
    return WeeklyBarAssessment(
        series.security_id,
        series.generation,
        series.decision_cutoff,
        series.price_basis,
        assessment.calendar_id,
        assessment.decision_at,
        assessment.availability_note,
        assessment.week_id,
        assessment.status,
        status,
        has_bar,
        status == "valid_bar",
        close,
        assessment.last_session_date,
        assessment.required_session_dates,
        tuple(prices),
        ignored,
        reasons,
    )
