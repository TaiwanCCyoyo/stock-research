"""Strict explicit-JSON boundary for the declared operation-card prerequisite.

Only the caller-named packet is read. This adapter neither discovers source
roots nor verifies the authenticity of the supplied source declarations.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core.artifact_store import safe_path
from research_core.json_integrity import strict_json_object
from research_core.multi_timeframe_ma_weeks_v1 import CalendarFact, CalendarSnapshot, DayCoverage
from research_core.order_card_freshness_v1 import (
    DEFINITION_ID,
    DatasetAssessment,
    DatasetObservation,
    DatasetRequirement,
    DatasetStatus,
    FreshnessAssessment,
    FreshnessRequest,
    assess_card_freshness,
)

MAX_PACKET_BYTES = 1_000_000
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z")


def _object(value: object, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be a JSON object")
    missing, extra = keys - value.keys(), value.keys() - keys
    if missing or extra:
        raise ValueError(f"{name} fields differ: missing={sorted(missing)}, unknown={sorted(extra)}")
    return value


def _array(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be explicit nonempty text")
    return value


def _day(value: object, name: str) -> pd.Timestamp:
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        raise ValueError(f"{name} must be an exact YYYY-MM-DD date")
    try:
        return cast(pd.Timestamp, pd.Timestamp(date.fromisoformat(value)))
    except ValueError as error:
        raise ValueError(f"{name} must be a valid YYYY-MM-DD date") from error


def _instant(value: object, name: str) -> pd.Timestamp:
    if not isinstance(value, str) or _INSTANT.fullmatch(value) is None:
        raise ValueError(f"{name} must be an ISO timestamp with explicit timezone")
    try:
        instant = cast(pd.Timestamp, pd.Timestamp(value))
        if pd.isna(instant) or instant.tz is None:
            raise ValueError("timezone required")
        return instant.tz_convert("Asia/Taipei")
    except (ValueError, OverflowError) as error:
        raise ValueError(f"{name} must be a valid timezone-aware timestamp") from error


def _fact(value: object, index: int) -> CalendarFact:
    name = f"calendar.facts[{index}]"
    row = _object(value, {"date", "session_state", "known_at", "close_at", "source_ref"}, name)
    state = row["session_state"]
    if type(state) is not int or state not in (-1, 0, 1):
        raise ValueError(f"{name}.session_state must be an int -1/0/1")
    source = row["source_ref"]
    if source is not None or state != -1:
        source = _text(source, f"{name}.source_ref")
    return CalendarFact(
        date=_day(row["date"], f"{name}.date"),
        session_state=state,
        known_at=None if row["known_at"] is None else _instant(row["known_at"], f"{name}.known_at"),
        close_at=None if row["close_at"] is None else _instant(row["close_at"], f"{name}.close_at"),
        source_ref=source,
    )


def _requirement(value: object, index: int) -> DatasetRequirement:
    name = f"request.requirements[{index}]"
    row = _object(value, {"dataset_id", "definition", "generation"}, name)
    return DatasetRequirement(**{key: _text(row[key], f"{name}.{key}") for key in ("dataset_id", "definition", "generation")})


def _observation(value: object, index: int) -> DatasetObservation:
    name = f"observations[{index}]"
    identity_keys = ("dataset_id", "definition", "generation", "calendar_id", "universe_id", "source_ref")
    row = _object(value, {*identity_keys, "as_of_session", "available_at", "status"}, name)
    status = _text(row["status"], f"{name}.status")
    if status not in ("complete", "missing", "unknown", "updating"):
        raise ValueError(f"{name}.status must be complete/missing/unknown/updating")
    return DatasetObservation(
        **{key: _text(row[key], f"{name}.{key}") for key in identity_keys},
        as_of_session=None if row["as_of_session"] is None else _day(row["as_of_session"], f"{name}.as_of_session"),
        available_at=None if row["available_at"] is None else _instant(row["available_at"], f"{name}.available_at"),
        status=cast(DatasetStatus, status),
    )


def parse_packet(document: object) -> tuple[FreshnessRequest, CalendarSnapshot, tuple[DatasetObservation, ...]]:
    """Validate every declared field without defaults, repair or source loading."""
    packet = _object(document, {"schema", "request", "calendar", "observations"}, "packet")
    if packet["schema"] != DEFINITION_ID:
        raise ValueError(f"packet.schema must equal {DEFINITION_ID!r}")
    request = _object(packet["request"], {"expected_session", "universe_id", "requirements"}, "request")
    calendar = _object(packet["calendar"], {"calendar_id", "decision_at", "availability_note", "facts"}, "calendar")
    return (
        FreshnessRequest(
            expected_session=_day(request["expected_session"], "request.expected_session"),
            universe_id=_text(request["universe_id"], "request.universe_id"),
            requirements=tuple(_requirement(item, index) for index, item in enumerate(_array(request["requirements"], "request.requirements"))),
        ),
        CalendarSnapshot(
            calendar_id=_text(calendar["calendar_id"], "calendar.calendar_id"),
            decision_at=_instant(calendar["decision_at"], "calendar.decision_at"),
            availability_note=_text(calendar["availability_note"], "calendar.availability_note"),
            facts=tuple(_fact(item, index) for index, item in enumerate(_array(calendar["facts"], "calendar.facts"))),
        ),
        tuple(_observation(item, index) for index, item in enumerate(_array(packet["observations"], "observations"))),
    )


def _optional_instant(value: pd.Timestamp | None) -> str | None:
    return None if value is None else value.isoformat()


def _requirement_document(value: DatasetRequirement) -> dict[str, str]:
    return {"dataset_id": value.dataset_id, "definition": value.definition, "generation": value.generation}


def _dataset_document(value: DatasetAssessment) -> dict[str, object]:
    observation = value.observation
    observed = None
    if observation is not None:
        observed = {
            "dataset_id": observation.dataset_id,
            "definition": observation.definition,
            "generation": observation.generation,
            "calendar_id": observation.calendar_id,
            "universe_id": observation.universe_id,
            "as_of_session": None if observation.as_of_session is None else observation.as_of_session.date().isoformat(),
            "available_at": _optional_instant(observation.available_at),
            "status": observation.status,
            "source_ref": observation.source_ref,
        }
    return {
        "requirement": _requirement_document(value.requirement),
        "observation": observed,
        "reasons": list(value.reasons),
        "freshness_ready": value.freshness_ready,
    }


def _day_document(value: DayCoverage) -> dict[str, object]:
    return {
        "date": value.date.date().isoformat(),
        "declared_state": value.declared_state,
        "session_state": value.session_state,
        "known_at": _optional_instant(value.known_at),
        "close_at": _optional_instant(value.close_at),
        "source_ref": value.source_ref,
        "reasons": list(value.reasons),
    }


def result_to_json_document(result: FreshnessAssessment) -> dict[str, object]:
    """Project public evidence explicitly, preserving nulls and source identities."""
    return {
        "schema": DEFINITION_ID,
        "freshness_ready": result.freshness_ready,
        "reasons": list(result.reasons),
        "expected_session": result.expected_session.date().isoformat(),
        "universe_id": result.universe_id,
        "calendar_id": result.calendar_id,
        "decision_at": result.decision_at.isoformat(),
        "calendar_availability_note": result.calendar_availability_note,
        "calendar_days": [_day_document(day) for day in result.calendar_days],
        "datasets": [_dataset_document(dataset) for dataset in result.datasets],
        "validation_scope": result.validation_scope,
    }


def assess_packet(document: object) -> dict[str, object]:
    """Assess a validated manual declaration; no source adapters are consulted."""
    request, calendar, observations = parse_packet(document)
    return result_to_json_document(assess_card_freshness(request, calendar, observations))


def read_and_assess_packet(path: Path) -> dict[str, object]:
    """Read only this explicit, bounded JSON object and assess its declarations."""
    with safe_path(path).open("rb") as stream:
        raw = stream.read(MAX_PACKET_BYTES + 1)
    if len(raw) > MAX_PACKET_BYTES:
        raise ValueError("freshness packet exceeds size limit")
    return assess_packet(strict_json_object(raw))
