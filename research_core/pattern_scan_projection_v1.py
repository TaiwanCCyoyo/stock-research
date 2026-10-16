"""Event-scoped jump projections over supplied immutable base-label rows."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.pattern_scan_event_outcomes_v1 import BaseOutcome, EventIdentity, Label, LabelReference, apply_event_overlay

LOGGER = logging.getLogger(__name__)
IDENTITY_COLUMNS = ("security_id", "t0", "pattern_id", "subtype_id", "definition_id", "input_id")
PROJECTION_COLUMNS = (
    "horizon",
    "base_label_version_id",
    "base_label_manifest_sha256",
    "base_label",
    "base_main_eligible",
    "calendar_full",
    "effective_label",
    "event_main_eligible",
    "event_eligibility_excluded",
    "detection_quality_reasons_json",
    "result_quality_reasons_json",
    "event_eligibility_reasons_json",
    "effective_unknown_reasons_json",
    "detection_scope_json",
    "result_scope_json",
)


def _position(value: Any, size: int, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or not 0 <= value < size:
        raise ValueError(f"{name} must be a valid integer calendar position")
    return int(value)


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be boolean")
    return bool(value)


def _reason(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    if not isinstance(value, str):
        raise ValueError("reason must be text or missing")
    return value


def _tokens(value: Any) -> tuple[str, ...]:
    reason = _reason(value)
    return () if reason is None else tuple(sorted({token.strip() for token in reason.split("|") if token.strip()}))


def _json(values: Any) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def project_outcomes(
    events: pd.DataFrame,
    base_labels: pd.DataFrame,
    quality_reason: pd.Series,
    *,
    base_label_version_id: str,
    base_label_manifest_sha256: str,
) -> pd.DataFrame:
    """Project detection/result jumps without rewriting base first decisions.

    Only unexplained_adjusted_jump/unexplained_jump activate the approved
    quality overlay. Ordinary missing-price reasons remain base-label evidence.
    Detection includes window_start through t0; results start strictly after
    t0 and end at the supplied horizon or last common-calendar position.
    """
    if not isinstance(base_label_version_id, str) or not base_label_version_id.strip():
        raise ValueError("base label version must be nonblank")
    if not isinstance(base_label_manifest_sha256, str) or re.fullmatch(r"[0-9a-fA-F]{64}", base_label_manifest_sha256) is None:
        raise ValueError("base label manifest must be a 64-character hexadecimal SHA256")
    if not isinstance(quality_reason, pd.Series) or not isinstance(quality_reason.index, pd.DatetimeIndex):
        raise ValueError("quality_reason requires the common DatetimeIndex")
    dates = quality_reason.index
    if dates.tz is not None or dates.hasnans or not dates.is_unique or not dates.is_monotonic_increasing or any(day != day.normalize() for day in dates):
        raise ValueError("quality calendar must be sorted unique timezone-naive midnight dates")
    event_required = {*IDENTITY_COLUMNS, "event_id", "calendar_index", "window_start", "base_eligible", "eligibility_reason"}
    label_required = {"security_id", "t0", "calendar_index", "horizon", "label", "calendar_full", "main_eligible", "unknown_reason"}
    if not events.columns.is_unique or not event_required.issubset(events):
        raise ValueError("events require canonical event fields")
    if not base_labels.columns.is_unique or not label_required.issubset(base_labels):
        raise ValueError("base labels require canonical label fields")
    if set(events.columns) & set(PROJECTION_COLUMNS):
        raise ValueError("event columns collide with projection fields")
    if events.event_id.duplicated().any() or base_labels.duplicated(["security_id", "t0", "horizon"]).any():
        raise ValueError("duplicate event or base-label identity")
    securities = set(events.security_id) | set(base_labels.security_id)
    if len(securities) > 1:
        raise ValueError("projection accepts one stock common calendar")
    jump_flags = np.array([bool(set(_tokens(value)) & {"unexplained_adjusted_jump", "unexplained_jump"}) for value in quality_reason], dtype=bool)
    by_start: dict[tuple[str, str], list[BaseOutcome]] = {}
    for supplied in base_labels.itertuples(index=False):
        row = cast(Any, supplied)
        index = _position(row.calendar_index, len(dates), "label calendar_index")
        if row.t0 != dates[index].strftime("%Y-%m-%d"):
            raise ValueError("label t0 does not match common calendar")
        if isinstance(row.horizon, (bool, np.bool_)) or not isinstance(row.horizon, (int, np.integer)):
            raise ValueError("horizon must be a positive integer")
        reference = LabelReference(row.security_id, row.t0, int(row.horizon), base_label_version_id)
        base = BaseOutcome(
            reference, cast(Label, row.label), _bool(row.calendar_full, "calendar_full"), _bool(row.main_eligible, "main_eligible"), _reason(row.unknown_reason)
        )
        by_start.setdefault((reference.security_id, reference.t0), []).append(base)
    rows: list[dict[str, Any]] = []
    for supplied_event in events.to_dict(orient="records"):
        event = cast(dict[str, Any], supplied_event)
        identity = EventIdentity(**{column: event[column] for column in IDENTITY_COLUMNS})
        if event["event_id"] != identity.event_id:
            raise ValueError("event_id does not match canonical EventIdentity")
        t0 = _position(event["calendar_index"], len(dates), "event calendar_index")
        start = _position(event["window_start"], len(dates), "window_start")
        if start > t0 or identity.t0 != dates[t0].strftime("%Y-%m-%d"):
            raise ValueError("event lookback or t0 does not match common calendar")
        eligible = _bool(event["base_eligible"], "base_eligible")
        eligibility = _tokens(event["eligibility_reason"])
        if eligible and eligibility or not eligible and not eligibility:
            raise ValueError("base eligibility must match its exclusion reasons")
        matches = by_start.get((identity.security_id, identity.t0))
        if not matches:
            raise ValueError("event has no matching immutable base labels")
        detection = ("unexplained_jump",) if jump_flags[start : t0 + 1].any() else ()
        for base in matches:
            horizon = base.reference.horizon
            end = min(t0 + horizon, len(dates) - 1)
            result_reasons = ("unexplained_jump",) if jump_flags[t0 + 1 : end + 1].any() else ()
            projected = apply_event_overlay(
                base, identity, detection_quality_reasons=detection, result_quality_reasons=result_reasons, event_eligibility_reasons=eligibility
            )
            rows.append({
                **event,
                "horizon": horizon,
                "base_label_version_id": base_label_version_id,
                "base_label_manifest_sha256": base_label_manifest_sha256,
                "base_label": base.label,
                "base_main_eligible": base.main_eligible,
                "calendar_full": base.calendar_full,
                "effective_label": projected.effective_label,
                "event_main_eligible": projected.event_main_eligible,
                "event_eligibility_excluded": bool(eligibility),
                "detection_quality_reasons_json": _json(projected.detection_quality_reasons),
                "result_quality_reasons_json": _json(projected.result_quality_reasons),
                "event_eligibility_reasons_json": _json(projected.event_eligibility_reasons),
                "effective_unknown_reasons_json": _json(projected.effective_unknown_reasons),
                "detection_scope_json": _json({"start": start, "end": t0}),
                "result_scope_json": _json({"start": t0 + 1, "end": end}),
            })
    output = pd.DataFrame(rows, columns=pd.Index([*events.columns, *PROJECTION_COLUMNS]))
    if output.duplicated(["event_id", "horizon"]).any():
        raise ValueError("duplicate event/horizon projection")
    LOGGER.debug("Projected scan outcomes events=%d labels=%d rows=%d jump_sessions=%d", len(events), len(base_labels), len(output), int(jump_flags.sum()))
    return output
