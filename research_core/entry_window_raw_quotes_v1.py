"""Explicit maintained raw-price reads adapted to E1's existing packet boundary.

The pure adapter validates declarations and snapshots evidence without I/O. The
loader delegates one explicit-generation, single-stock read to the maintained
family. Neither path constructs labels, interval quality, or official limits.
Contract: tasks/20261027-entry-window/raw-reader-handoff.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from research_core import entry_window_inputs_v1 as inputs
from research_core import entry_window_price_inputs_v1 as price_inputs
from research_core import maintained_adjusted_daily as maintained
from research_core.entry_window_price_inputs_v1 import AS_OF_METHOD as AS_OF_METHOD

DEFINITION_ID = "entry-window-raw-quotes.v1"
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


def adapt_raw_quote_read(request: inputs.InputRequest, frame: pd.DataFrame, record: Mapping[str, Any]) -> RawQuoteRead:
    """Adapt raw, unmasked float64 columns with exact original date positions.

    Daily quality is retained separately and establishes no clean interval or
    no-action claim. A duplicate_date diagnostic rejects the entire call because
    the maintained family has already retained just the first source quote.
    """
    source_record = price_inputs.validate_price_read(request, frame, record, basis="raw")
    arrays: dict[str, NDArray[np.float64]] = {}
    for name in RAW_COLUMNS:
        copied = frame[name].to_numpy().copy()
        copied.flags.writeable = False
        arrays[name] = copied
    quality = frame["Quality"].to_numpy().copy()
    quality.flags.writeable = False
    reasons = tuple(frame["quality_reason"])
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
    price_inputs.validate_price_request(request)
    price_inputs.validate_price_root(root)
    frame, record = maintained.read_adjusted_daily(
        "raw", codes=[request.security_id], root=root, generation=request.generation, as_of=request.study_as_of, calendar=request.common_calendar
    )
    return adapt_raw_quote_read(request, frame, record)
