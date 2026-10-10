"""Explicit modeled signal timing; never create historical timestamps or coverage."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SIGNAL_ROOT = Path(__file__).resolve().parent.parent / "010-membership-signal"
if str(SIGNAL_ROOT) not in sys.path:
    sys.path.insert(0, str(SIGNAL_ROOT))

from asof_signal_prices import Adjustment  # noqa: E402

POLICY_ID = "development-reference-effective-evening-v1"
TAIPEI = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class ModeledAdjustment:
    adjustment: Adjustment
    timing_policy_id: str
    historical_available_at: None
    availability_basis: str = "assumed_effective_day_1800_taipei_not_observed"


def model_adjustments(records: Sequence[Mapping[str, Any]], *, policy_id: str) -> tuple[ModeledAdjustment, ...]:
    """Convert an explicitly supplied scope; unknown factors remain unknown.

    Caller must bind the evidence readset and policy before execution. This helper
    does not select securities, resolve overlapping sources or claim completeness.
    Use the returned timing provenance in the eventual run receipt, not just the
    bare Adjustment objects expected by the existing causal projector.
    """
    if policy_id != POLICY_ID:
        raise ValueError("explicit recognized development timing policy required")
    result: list[ModeledAdjustment] = []
    keys: set[tuple[str, date]] = set()
    event_ids: set[str] = set()
    for record in records:
        identity = {}
        for name in ("event_id", "code", "source", "raw_sha256"):
            value = record.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"missing source identity: {name}")
            identity[name] = value
        if "historical_available_at" not in record or record["historical_available_at"] is not None:
            raise ValueError("this model only accepts explicit unknown historical timestamps")
        day = date.fromisoformat(record["effective_date"])
        key = (identity["code"], day)
        if record.get("blocked_for_projection", False) or key in keys or identity["event_id"] in event_ids:
            raise ValueError("overlapping source events require upstream resolution")
        keys.add(key)
        event_ids.add(identity["event_id"])
        literal = record.get("prior_price_multiplier")
        ratio = record.get("factor_ratio")
        if literal is None:
            if ratio is not None or record.get("status") != "unresolved_reference_factor":
                raise ValueError("unresolved factor and status disagree")
            factor = None
        else:
            try:
                factor = Decimal(literal)
            except (InvalidOperation, TypeError) as error:
                raise ValueError("invalid factor") from error
            if not factor.is_finite() or factor <= 0 or record.get("status") != "resolved_reference_factor":
                raise ValueError("invalid positive factor or status")
            if not isinstance(ratio, Mapping) or any(type(ratio.get(name)) is not int or ratio[name] <= 0 for name in ("numerator", "denominator")):
                raise ValueError("positive exact factor ratio required")
            if factor != Decimal(ratio["numerator"]) / Decimal(ratio["denominator"]):
                raise ValueError("decimal factor and exact ratio disagree")
        modeled_at = datetime.combine(day, time(18), tzinfo=TAIPEI)
        source_id = f"{identity['source']}:{identity['raw_sha256']}|{policy_id}:assumed"
        adjustment = Adjustment(identity["event_id"], identity["code"], day, factor, modeled_at, source_id)
        result.append(ModeledAdjustment(adjustment, policy_id, None))
    return tuple(sorted(result, key=lambda item: (item.adjustment.effective_on, item.adjustment.code, item.adjustment.event_id)))
