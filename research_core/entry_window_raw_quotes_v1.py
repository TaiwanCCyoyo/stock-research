"""Explicit maintained raw-price reads adapted to E1's existing packet boundary.

The pure adapter validates declarations and snapshots evidence without I/O. The
loader delegates one explicit-generation, single-stock read to the maintained
family. Neither path constructs labels, interval quality, or official limits.
Contract: tasks/20261027-entry-window/raw-reader-handoff.md.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from research_core import entry_window_inputs_v1 as inputs
from research_core import maintained_adjusted_daily as maintained
from research_core.artifact_store import object_digest

DEFINITION_ID = "entry-window-raw-quotes.v1"
AS_OF_METHOD = "price_basis.prepare_prices at as_of from the generation's raw quotes and actions snapshot"
VALIDATION_SCOPE = (
    "declared_frame_record_consistency_only; maintained_numeric_coercion_precedes_this_boundary; "
    "source_precision_calendar_authenticity_and_interval_coverage_not_certified"
)
RAW_COLUMNS = ("RawOpen", "RawHigh", "RawLow", "RawClose")


@dataclass(frozen=True, kw_only=True)
class RawQuoteRead:
    packet: inputs.RawQuotePacket
    quality: NDArray[np.bool_]
    quality_reason: tuple[str | None, ...]
    source_record: Mapping[str, Any]
    validation_scope: str


def _request(request: inputs.InputRequest) -> None:
    if not isinstance(request, inputs.InputRequest):
        raise ValueError("explicit InputRequest required")
    inputs.validate_input_request(request)
    if len(request.common_calendar) and request.common_calendar[-1] > request.study_as_of:
        raise ValueError("common calendar must not extend after study_as_of")


def _iso_date(value: object, name: str) -> pd.Timestamp:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError(f"record.{name} must be an ISO date")
    try:
        return cast(pd.Timestamp, pd.Timestamp(value))
    except ValueError as error:
        raise ValueError(f"record.{name} must be a valid ISO date") from error


def _freeze(value: Any) -> Any:
    """Detach the reader's JSON metadata, refusing opaque mutable objects."""
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("source record requires string metadata keys")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("source record must contain finite JSON-compatible metadata")


def _record(request: inputs.InputRequest, record: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(record, Mapping):
        raise ValueError("explicit maintained reader source record required")
    expected = {
        "family": "adjusted-daily-v1",
        "generation": request.generation,
        "basis": "raw",
        "definition": "price-basis.v2",
        "as_of": request.study_as_of.date().isoformat(),
        "as_of_method": AS_OF_METHOD,
    }
    for name, value in expected.items():
        if record.get(name) != value:
            raise ValueError(f"record.{name} differs from the requested maintained raw read")
    if type(record.get("codes")) is not int or record["codes"] != 1:
        raise ValueError("record.codes must declare exactly one code")
    if _iso_date(record.get("asof"), "asof") < request.study_as_of:
        raise ValueError("generation asof is before the requested study_as_of")
    if not isinstance(record.get("file"), str) or not record["file"].strip():
        raise ValueError("record.file must be an explicit source reference")
    for name in ("sha256", "status_sha256", "actions_sha256"):
        value = record.get(name)
        if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
            raise ValueError(f"record.{name} must be a SHA-256 hex digest")
    days = [day.date().isoformat() for day in request.common_calendar]
    expected_calendar = {
        "source": "caller",
        "sessions": len(days),
        "first": days[0] if days else None,
        "last": days[-1] if days else None,
        "sha256": object_digest(days),
    }
    recorded_calendar = record.get("calendar")
    if not isinstance(recorded_calendar, Mapping) or any(recorded_calendar.get(key) != value for key, value in expected_calendar.items()):
        raise ValueError("record.calendar differs from the explicit common calendar")
    if type(recorded_calendar.get("sessions")) is not int:
        raise ValueError("record.calendar.sessions must be a Python integer")
    return _freeze(record)


def adapt_raw_quote_read(request: inputs.InputRequest, frame: pd.DataFrame, record: Mapping[str, Any]) -> RawQuoteRead:
    """Adapt raw, unmasked float64 columns with exact original date positions.

    Daily quality is retained separately and establishes no clean interval or
    no-action claim. A duplicate_date diagnostic rejects the entire call because
    the maintained family has already retained just the first source quote.
    """
    _request(request)
    source_record = _record(request, record)
    required = {"Code", "Date", *RAW_COLUMNS, "Quality", "quality_reason"}
    if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique or not required.issubset(frame.columns):
        raise ValueError("frame requires unique Code/Date/Raw OHLC/Quality/quality_reason columns")
    if len(frame) != len(request.common_calendar):
        raise ValueError("frame must retain every common calendar position")
    if any(not isinstance(code, str) or code != request.security_id for code in frame["Code"]):
        raise ValueError("frame Code differs from the requested security")
    if not isinstance(frame["Date"].dtype, np.dtype) or not pd.api.types.is_datetime64_dtype(frame["Date"].dtype):
        raise ValueError("frame Date must contain explicit timezone-naive datetime values")
    calendar = pd.DatetimeIndex(frame["Date"])
    if not calendar.equals(request.common_calendar):
        raise ValueError("frame dates differ from common calendar at original positions")
    arrays: dict[str, NDArray[np.float64]] = {}
    for name in RAW_COLUMNS:
        if not isinstance(frame[name].dtype, np.dtype) or frame[name].dtype != np.dtype(np.float64):
            raise ValueError(f"frame {name} must have native dtype np.float64 without casting")
        values = frame[name].to_numpy()
        if values.dtype != np.dtype(np.float64):
            raise ValueError(f"frame {name} must have dtype np.float64 without casting")
        copied = values.copy()
        copied.flags.writeable = False
        arrays[name] = copied
    if not isinstance(frame["Quality"].dtype, np.dtype) or frame["Quality"].dtype != np.dtype(np.bool_):
        raise ValueError("frame Quality must have native bool dtype")
    quality = frame["Quality"].to_numpy()
    if quality.dtype != np.dtype(np.bool_):
        raise ValueError("frame Quality must have exact bool dtype")
    quality = quality.copy()
    quality.flags.writeable = False
    reasons = tuple(frame["quality_reason"])
    if any(reason is not None and not isinstance(reason, str) for reason in reasons):
        raise ValueError("quality_reason values must be text or None")
    if any(reason is not None and "duplicate_date" in reason.split("|") for reason in reasons):
        raise ValueError("duplicate_date cannot be recovered; refuse the entire raw quote read")
    packet = inputs.RawQuotePacket(
        security_id=request.security_id,
        generation=request.generation,
        study_as_of=request.study_as_of,
        calendar=request.common_calendar.copy(deep=True),
        universe_id=request.universe_id,
        calendar_id=request.calendar_id,
        source=f"adjusted-daily-v1 raw generation={request.generation} as_of={record['as_of']} file={record['file']} sha256={record['sha256']}",
        basis="raw",
        raw_open=arrays["RawOpen"],
        raw_high=arrays["RawHigh"],
        raw_low=arrays["RawLow"],
        raw_close=arrays["RawClose"],
    )
    return RawQuoteRead(packet=packet, quality=quality, quality_reason=reasons, source_record=source_record, validation_scope=VALIDATION_SCOPE)


def load_raw_quote_packet(request: inputs.InputRequest, *, root: Path) -> RawQuoteRead:
    """Read one fixed generation under an explicit absolute shared root.

    Generation retention/holds and market-data admission remain the caller's
    responsibility. This delegates only to the existing maintained raw reader.
    """
    _request(request)
    if not isinstance(root, Path) or not root.is_absolute():
        raise ValueError("root must be an explicit absolute Path")
    frame, record = maintained.read_adjusted_daily(
        "raw", codes=[request.security_id], root=root, generation=request.generation, as_of=request.study_as_of, calendar=request.common_calendar
    )
    return adapt_raw_quote_read(request, frame, record)
