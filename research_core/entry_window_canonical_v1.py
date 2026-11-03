"""E1 canonical packets wired to the existing public PR61 stock calculation.

No replacement indicator, eligibility or label method is defined. Actual market
labels/admission and frozen PR61 parity remain separate from this engineering
bridge. Contract: tasks/20261027-entry-window/canonical-reader-handoff.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from research_core import entry_window_inputs_v1 as inputs
from research_core import entry_window_price_inputs_v1 as price_inputs
from research_core import maintained_adjusted_daily as maintained
from research_core import momentum_only_v1 as canonical

DEFINITION_ID = "entry-window-canonical.v1"
VALIDATION_SCOPE = (
    "declared_frame_record_consistency_and_existing_stock_daily_calculation_only; "
    "maintained_numeric_coercion_precedes_this_boundary; "
    "source_precision_calendar_universe_authenticity_original_label_admission_and_interval_coverage_not_certified"
)


@dataclass(frozen=True, kw_only=True)
class CanonicalRead:
    packet: inputs.CanonicalPacket
    source_record: Mapping[str, Any]
    ordinary_reference: bool
    validation_scope: str


def _declarations(ordinary_reference: bool, availability_note: str) -> None:
    if type(ordinary_reference) is not bool:
        raise ValueError("ordinary_reference must be an explicit Python bool")
    if not isinstance(availability_note, str) or not availability_note.strip():
        raise ValueError("availability_note must be explicit nonempty text")


def adapt_canonical_read(
    request: inputs.InputRequest, frame: pd.DataFrame, record: Mapping[str, Any], *, ordinary_reference: bool, availability_note: str
) -> CanonicalRead:
    """Calculate canonical fields exactly once on detached, validated inputs.

    Unknown and invalid values remain where supplied for the original public
    calculation. The ordinary-reference declaration is passed unchanged; it is
    not an independent proof of historical universe membership. The calculation
    retains its existing diagnostic logging and host-handler behavior.
    """
    _declarations(ordinary_reference, availability_note)
    source_record = price_inputs.validate_price_read(request, frame, record, basis="reference_factor_adjusted")
    prepared = frame.copy(deep=True).drop(columns="Code").set_index("Date")
    stock = canonical.stock_daily(request.security_id, prepared, ordinary_reference=ordinary_reference)
    packet = inputs.CanonicalPacket(
        security_id=request.security_id,
        generation=request.generation,
        study_as_of=request.study_as_of,
        calendar=request.common_calendar.copy(deep=True),
        universe_id=request.universe_id,
        calendar_id=request.calendar_id,
        source=(
            f"adjusted-daily-v1 reference_factor_adjusted generation={request.generation} "
            f"as_of={source_record['as_of']} file={source_record['file']} sha256={source_record['sha256']}"
        ),
        stock=stock,
        definition="momentum-only.v1",
        basis="reference_factor_adjusted",
        availability_note=availability_note,
    )
    return CanonicalRead(packet=packet, source_record=source_record, ordinary_reference=ordinary_reference, validation_scope=VALIDATION_SCOPE)


def load_canonical_packet(request: inputs.InputRequest, *, root: Path, ordinary_reference: bool, availability_note: str) -> CanonicalRead:
    """Delegate one explicit fixed-generation read; callers own data admission."""
    _declarations(ordinary_reference, availability_note)
    price_inputs.validate_price_request(request)
    price_inputs.validate_price_root(root)
    frame, record = maintained.read_adjusted_daily(
        "reference_factor_adjusted",
        codes=[request.security_id],
        root=root,
        generation=request.generation,
        as_of=request.study_as_of,
        calendar=request.common_calendar,
    )
    return adapt_canonical_read(request, frame, record, ordinary_reference=ordinary_reference, availability_note=availability_note)
