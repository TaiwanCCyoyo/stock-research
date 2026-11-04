"""Shared declared-input checks for the two E1 maintained-price adapters.

Only raw and reference-factor-adjusted reads are supported. This module performs
no reads, normalization, calculation, logging, or source-authenticity checks.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

import numpy as np
import pandas as pd

from research_core import entry_window_inputs_v1 as inputs
from research_core.artifact_store import object_digest

AS_OF_METHOD = "price_basis.prepare_prices at as_of from the generation's raw quotes and actions snapshot"
PriceBasis = Literal["raw", "reference_factor_adjusted"]
NUMERIC_COLUMNS = {
    "raw": ("RawOpen", "RawHigh", "RawLow", "RawClose"),
    "reference_factor_adjusted": ("Open", "High", "Low", "Close", "RawClose", "VolumeLots", "Turnover"),
}


def validate_price_request(request: inputs.InputRequest) -> None:
    """Reuse staging identity checks and reject calendar dates after the cutoff."""
    if not isinstance(request, inputs.InputRequest):
        raise ValueError("explicit InputRequest required")
    inputs.validate_input_request(request)
    if len(request.common_calendar) and request.common_calendar[-1] > request.study_as_of:
        raise ValueError("common calendar must not extend after study_as_of")


def validate_price_root(root: Path) -> None:
    """Require an explicit absolute root without probing or resolving it."""
    if not isinstance(root, Path) or not root.is_absolute():
        raise ValueError("root must be an explicit absolute Path")


def _iso_date(value: object, name: str) -> pd.Timestamp:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError(f"record.{name} must be an ISO date")
    try:
        return cast(pd.Timestamp, pd.Timestamp(value))
    except ValueError as error:
        raise ValueError(f"record.{name} must be a valid ISO date") from error


def _freeze(value: Any) -> Any:
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


def _record(request: inputs.InputRequest, record: Mapping[str, Any], basis: PriceBasis) -> Mapping[str, Any]:
    if not isinstance(record, Mapping):
        raise ValueError("explicit maintained reader source record required")
    expected = {
        "family": "adjusted-daily-v1",
        "generation": request.generation,
        "basis": basis,
        "definition": "price-basis.v2",
        "as_of": request.study_as_of.date().isoformat(),
        "as_of_method": AS_OF_METHOD,
    }
    for name, value in expected.items():
        if record.get(name) != value:
            raise ValueError(f"record.{name} differs from the requested maintained {basis} read")
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


def validate_price_read(request: inputs.InputRequest, frame: pd.DataFrame, record: Mapping[str, Any], *, basis: PriceBasis) -> Mapping[str, Any]:
    """Validate one exact frame/record pair and return a detached frozen record.

    Frame values stay untouched, including missing and invalid prices. Each
    caller snapshots the validated numeric values it actually consumes.
    """
    validate_price_request(request)
    if basis not in NUMERIC_COLUMNS:
        raise ValueError("only raw and reference_factor_adjusted E1 inputs are supported")
    source_record = _record(request, record, basis)
    columns = NUMERIC_COLUMNS[basis]
    required = {"Code", "Date", *columns, "Quality", "quality_reason"}
    if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique or not required.issubset(frame.columns):
        role = "Raw OHLC" if basis == "raw" else "canonical numeric"
        raise ValueError(f"frame requires unique Code/Date/{role}/Quality/quality_reason columns")
    if len(frame) != len(request.common_calendar):
        raise ValueError("frame must retain every common calendar position")
    if any(not isinstance(code, str) or code != request.security_id for code in frame["Code"]):
        raise ValueError("frame Code differs from the requested security")
    if not isinstance(frame["Date"].dtype, np.dtype) or not pd.api.types.is_datetime64_dtype(frame["Date"].dtype):
        raise ValueError("frame Date must contain explicit timezone-naive datetime values")
    if not pd.DatetimeIndex(frame["Date"]).equals(request.common_calendar):
        raise ValueError("frame dates differ from common calendar at original positions")
    for name in columns:
        if not isinstance(frame[name].dtype, np.dtype) or frame[name].dtype != np.dtype(np.float64):
            raise ValueError(f"frame {name} must have native dtype np.float64 without casting")
        if frame[name].to_numpy().dtype != np.dtype(np.float64):
            raise ValueError(f"frame {name} must have dtype np.float64 without casting")
    if not isinstance(frame["Quality"].dtype, np.dtype) or frame["Quality"].dtype != np.dtype(np.bool_):
        raise ValueError("frame Quality must have native bool dtype")
    if frame["Quality"].to_numpy().dtype != np.dtype(np.bool_):
        raise ValueError("frame Quality must have exact bool dtype")
    reasons = tuple(frame["quality_reason"])
    if any(reason is not None and not isinstance(reason, str) for reason in reasons):
        raise ValueError("quality_reason values must be text or None")
    if any(reason is not None and "duplicate_date" in reason.split("|") for reason in reasons):
        raise ValueError(f"duplicate_date cannot be recovered; refuse the entire {basis} quote read")
    return source_record
