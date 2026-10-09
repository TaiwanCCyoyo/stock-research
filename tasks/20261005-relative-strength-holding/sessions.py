"""Source-bound interruption marks and review states, never filled price bars.

Only the retained single-session halt cases and the bound 2316 capital halt are
supported. The ordinary H05 feature panel remains unchanged and gaps still reset
its averages. A later unexplained gap never inherits the named-halt exception.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

import pandas as pd

from research_core.decision import CloseObservation

LOGGER = logging.getLogger(__name__)
TAIPEI = timezone(timedelta(hours=8))
Key = tuple[date, str]


@dataclass(frozen=True)
class SessionPlan:
    calendar: tuple[date, ...]
    marks: Mapping[Key, CloseObservation]
    statuses: Mapping[Key, tuple[str, str]]
    confirmed_halts: Mapping[Key, str]

    def __post_init__(self) -> None:
        for name in ("marks", "statuses", "confirmed_halts"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("interruption source must have a nonempty identity")
    return value


def _number(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        raise ValueError("interruption numeric input cannot be bool")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("invalid interruption numeric input") from error
    if not result.is_finite():
        raise ValueError("interruption numeric input must be finite")
    return result


def _availability(value: Any, day: date) -> datetime:
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(hours=8) or value.date() != day or not time(13, 30) <= value.time() <= time(20):
        raise ValueError("reference observation must be available on its own review day")
    return value


def _reference(raw: Mapping[str, Any], panel: Mapping[str, Any], day: date) -> CloseObservation:
    if raw.get("Market") != "TWSE" or panel.get("Market") != "TWSE":
        raise ValueError("named interruption evidence is TWSE-only")
    source = _text(raw.get("source_id"))
    if panel.get("source_id") != source:
        raise ValueError("reference raw/panel source mismatch")
    close, signal = _number(raw.get("Close")), _number(panel.get("signal_close"))
    if close is None or signal is None or close <= 0 or signal <= 0 or close * 100 != (close * 100).to_integral_value():
        raise ValueError("halt reference requires real positive raw and signal closes")
    available = _availability(raw.get("available_at"), day)
    if _availability(panel.get("available_at"), day) < available:
        raise ValueError("reference derived observation precedes its raw input")
    return CloseObservation(int(close * 100), signal, datetime.combine(day, time(13, 30), TAIPEI), available, source)


def build_session_plan(
    modules: Mapping[str, Any],
    *,
    raw_by_key: Mapping[Key, Mapping[str, Any]],
    panel_by_key: Mapping[Key, Mapping[str, Any]],
    calendar: tuple[date, ...],
    halt_cases: tuple[Any, ...] = (),
    capital_events: tuple[Any, ...] = (),
) -> SessionPlan:
    """Bind only injected named evidence; do not inspect files or market outcomes."""
    if (
        not isinstance(calendar, tuple)
        or not calendar
        or any(type(day) is not date for day in calendar)
        or any(left >= right for left, right in zip(calendar, calendar[1:]))
    ):
        raise ValueError("interruption calendar must be strictly ordered date values")
    if set(raw_by_key) != set(panel_by_key) or any(day not in calendar for day, _code in raw_by_key):
        raise ValueError("interruption raw/panel keys must agree inside the supplied calendar")
    valuation = modules["valuation"]
    marks: dict[Key, CloseObservation] = {}
    statuses: dict[Key, tuple[str, str]] = {}
    halts: dict[Key, str] = {}
    index = {day: position for position, day in enumerate(calendar)}

    def reference(day: date, code: str) -> CloseObservation:
        key = (day, code)
        if key not in raw_by_key:
            raise ValueError(f"named halt reference is unavailable: {key}")
        return _reference(raw_by_key[key], panel_by_key[key], day)

    def add_halt(day: date, code: str, source: str, mark: CloseObservation, expected_row_source: str | None = None) -> None:
        key = (day, code)
        if key in statuses:
            raise ValueError(f"overlapping named interruptions: {key}")
        row = raw_by_key.get(key)
        if row is None and expected_row_source is not None:
            raise ValueError(f"named single-session halt row unavailable: {key}")
        if row is not None:
            if row.get("Market") != "TWSE" or any(_number(row.get(field)) is not None for field in ("Open", "High", "Low", "Close")):
                raise ValueError(f"named halt conflicts with market price observations: {key}")
            if _number(row.get("Volume")) != 0 or (expected_row_source is not None and row.get("source_id") != expected_row_source):
                raise ValueError(f"named halt volume/source differs: {key}")
            if _number(panel_by_key[key].get("signal_close")) is not None:
                raise ValueError(f"halt price must not be filled in the signal panel: {key}")
        marks[key] = mark
        statuses[key] = ("confirmed_halt", source)
        halts[key] = source

    def rewarming(resumed: date, code: str, source: str) -> None:
        if resumed not in index:
            return
        for expected, day in enumerate(calendar[index[resumed] :], start=1):
            key = (day, code)
            row, panel = raw_by_key.get(key), panel_by_key.get(key)
            # Unknown continuation keeps the existing missing-mark/feature stop.
            # It is not another source-confirmed halt or a filled observation.
            if row is None or panel is None or _number(row.get("Close")) is None or _number(panel.get("signal_close")) is None:
                break
            if panel.get("consecutive_usable") != expected:
                raise ValueError(f"named halt must reset contiguous feature history: {key}")
            if expected >= 60:
                break
            if key in statuses:
                raise ValueError(f"overlapping named interruption recovery: {key}")
            statuses[key] = ("resumed_rewarming", source)

    for case in halt_cases:
        if not calendar[0] <= case.halt_day <= calendar[-1] and case.resumed_day not in index:
            continue
        if any(day not in index for day in (case.reference_day, case.halt_day)):
            raise ValueError("named halt needs its reference and halted sessions in the slice")
        if index[case.halt_day] != index[case.reference_day] + 1:
            raise ValueError("named halt reference is not the preceding calendar session")
        prior = reference(case.reference_day, case.code)
        if prior.raw_close_cents != case.reference_close_cents or prior.source_id != case.reference_source_id:
            raise ValueError("named halt reference price/source contradicts its bound case")
        source = _text(case.halt_source_id)
        add_halt(
            case.halt_day,
            case.code,
            source,
            valuation.halt_mark(prior=prior, day=case.halt_day, code=case.code, source_id=source),
            case.halt_price_source_id,
        )
        if case.resumed_day in index:
            if index[case.resumed_day] != index[case.halt_day] + 1:
                raise ValueError("named resume is not the next calendar session")
            row = raw_by_key.get((case.resumed_day, case.code))
            if row is None or row.get("source_id") != case.resumed_source_id or row.get("Market") != "TWSE":
                raise ValueError("named resumed row/source contradicts its bound case")
            rewarming(case.resumed_day, case.code, source)

    for event in capital_events:
        if event.code != "2316" or event.stopped_on != date(2019, 9, 26) or event.resumed_on != date(2019, 10, 7):
            raise ValueError("only the already-bound 2316 capital halt is supported")
        days = tuple(day for day in calendar if event.stopped_on <= day < event.resumed_on)
        if not days:
            continue
        prior = reference(date(2019, 9, 25), event.code)
        source = _text(event.source_id)
        for day in days:
            add_halt(day, event.code, source, valuation.capital_halt_mark(prior=prior, day=day, source_id=source))
        rewarming(event.resumed_on, event.code, source)
    LOGGER.info("Bound interruption marks=%d recovery states=%d; raw and signal tables unchanged", len(marks), len(statuses) - len(marks))
    return SessionPlan(calendar, marks, statuses, halts)
