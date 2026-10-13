"""Pure event projections over immutable shared labels; no label calculation."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from research_core.artifact_store import object_digest

Label = Literal["hit", "loss", "flat-win", "unknown"]
log = logging.getLogger(__name__)


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


def _identity(security_id: str, t0: str) -> None:
    _text(security_id, "security_id")
    _text(t0, "t0")
    if date.fromisoformat(t0).isoformat() != t0:
        raise ValueError("t0 must be a canonical ISO date")


def _reasons(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("reasons must be an iterable of nonblank strings")
    result = tuple(values)
    for value in result:
        _text(value, "reason")
    return tuple(sorted(set(result)))


@dataclass(frozen=True)
class LabelReference:
    security_id: str
    t0: str
    horizon: int
    version_id: str

    def __post_init__(self) -> None:
        _identity(self.security_id, self.t0)
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int) or self.horizon < 1:
            raise ValueError("horizon must be a positive integer")
        _text(self.version_id, "version_id")


@dataclass(frozen=True)
class BaseOutcome:
    reference: LabelReference
    label: Label
    calendar_full: bool
    main_eligible: bool
    unknown_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reference, LabelReference):
            raise ValueError("reference must be a LabelReference")
        if self.label not in ("hit", "loss", "flat-win", "unknown"):
            raise ValueError("invalid base label")
        if not isinstance(self.calendar_full, bool) or not isinstance(self.main_eligible, bool):
            raise ValueError("calendar_full and main_eligible must be bool")
        if self.unknown_reason is not None:
            _text(self.unknown_reason, "unknown_reason")
        if (self.label == "unknown") != (self.unknown_reason is not None):
            raise ValueError("unknown label requires a reason; known label cannot have one")
        if self.main_eligible != (self.calendar_full and self.label != "unknown"):
            raise ValueError("main_eligible must match full-calendar known base outcome")

    @property
    def known(self) -> bool:
        return self.label != "unknown"


@dataclass(frozen=True)
class EventIdentity:
    security_id: str
    t0: str
    pattern_id: str
    subtype_id: str
    definition_id: str
    input_id: str

    def __post_init__(self) -> None:
        _identity(self.security_id, self.t0)
        for name in ("pattern_id", "subtype_id", "definition_id", "input_id"):
            _text(getattr(self, name), name)

    @property
    def event_id(self) -> str:
        return object_digest(asdict(self))


@dataclass(frozen=True)
class EventOutcome:
    event_id: str
    horizon: int
    base_reference: LabelReference
    base_label: Label
    base_known: bool
    effective_label: Label
    event_main_eligible: bool
    detection_quality_reasons: tuple[str, ...]
    result_quality_reasons: tuple[str, ...]
    event_eligibility_reasons: tuple[str, ...]
    effective_unknown_reasons: tuple[str, ...]

    @property
    def key(self) -> tuple[str, int]:
        return self.event_id, self.horizon

    @property
    def effective_known(self) -> bool:
        return self.effective_label != "unknown"


def apply_event_overlay(
    base: BaseOutcome,
    event: EventIdentity,
    *,
    detection_quality_reasons: Iterable[str] = (),
    result_quality_reasons: Iterable[str] = (),
    event_eligibility_reasons: Iterable[str] = (),
) -> EventOutcome:
    """Project an event without changing its base label or other events.

    Quality reasons make this event unknown. Eligibility reasons only exclude
    its main denominator. Unknown reasons are scoped; identical text in different
    scopes remains distinct. Base incomplete-calendar known outcomes stay known.
    """
    if (base.reference.security_id, base.reference.t0) != (event.security_id, event.t0):
        raise ValueError("event stock/t0 does not match base reference")
    detection = _reasons(detection_quality_reasons)
    result = _reasons(result_quality_reasons)
    eligibility = _reasons(event_eligibility_reasons)
    quality = bool(detection or result)
    unknown = tuple(
        sorted(
            ([f"base:{base.unknown_reason}"] if base.unknown_reason is not None else [])
            + [f"detection:{reason}" for reason in detection]
            + [f"result:{reason}" for reason in result]
        )
    )
    log.debug(
        "Projecting event %s H%d: quality=%s eligible=%s",
        event.event_id,
        base.reference.horizon,
        quality,
        base.main_eligible and not quality and not eligibility,
    )
    return EventOutcome(
        event.event_id,
        base.reference.horizon,
        base.reference,
        base.label,
        base.known,
        "unknown" if quality else base.label,
        base.main_eligible and not quality and not eligibility,
        detection,
        result,
        eligibility,
        unknown,
    )
