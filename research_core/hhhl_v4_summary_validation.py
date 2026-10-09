"""Validate saved v4 descriptive payloads without recomputing market outcomes."""

from __future__ import annotations

import logging
import math
from typing import Any

from research_core.hhhl_v4_outcomes import TARGETS

LOGGER = logging.getLogger(__name__)
COUNT_FIELDS = ("rows", "eligible", "ineligible", "securities", "known_securities", "known", "hits", "nonhits", "unknown")
QUANTILE_POPULATIONS = {
    "nonhit_min_return_median": "nonhits",
    "nonhit_min_return_p10": "nonhits",
    "nonhit_max_drawdown_median": "nonhits",
    "hit_wait_median": "hits",
    "hit_wait_p10": "hits",
    "hit_wait_p90": "hits",
}
RATE_FIELDS = ("rate", "unknown_lower", "unknown_upper", "all_day_base_rate", "no_event_control_rate")
LIFT_FIELDS = ("lift_all_days", "lift_no_event_control")
REQUIRED_FIELDS = (*COUNT_FIELDS, *QUANTILE_POPULATIONS, *RATE_FIELDS, *LIFT_FIELDS, "unknown_reasons", "small_sample")


def _count(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _number(value: Any, label: str) -> int | float | None:
    if value is None:
        return None
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{label} must be a finite number or null")
    return value


def _matches(actual: int | float | None, expected: int | float | None, label: str) -> None:
    if actual is None or expected is None:
        matches = actual is expected
    else:
        matches = math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
    if not matches:
        raise ValueError(f"{label} does not match its descriptive formula")


def validate_summary_payload(row: dict[str, Any], index: int) -> None:
    """Check schema and arithmetic only; this does not authenticate source metrics."""
    label = f"summary cell {index}"
    missing = [field for field in REQUIRED_FIELDS if field not in row]
    if missing:
        raise ValueError(f"{label} is missing payload fields: {', '.join(missing)}")
    counts = {field: _count(row[field], f"{label}.{field}") for field in COUNT_FIELDS}
    if (
        counts["rows"] != counts["eligible"] + counts["ineligible"]
        or counts["eligible"] != counts["known"] + counts["unknown"]
        or counts["known"] != counts["hits"] + counts["nonhits"]
        or not counts["known_securities"] <= counts["securities"] <= counts["eligible"]
        or counts["known_securities"] > counts["known"]
    ):
        raise ValueError(f"{label} has inconsistent counts")
    numbers = {field: _number(row[field], f"{label}.{field}") for field in (*RATE_FIELDS, *LIFT_FIELDS)}
    for field in RATE_FIELDS:
        number = numbers[field]
        if number is not None and not 0 <= number <= 1:
            raise ValueError(f"{label}.{field} must be between zero and one or null")
    for field in LIFT_FIELDS:
        number = numbers[field]
        if number is not None and number < 0:
            raise ValueError(f"{label}.{field} must be nonnegative or null")
    for field, numerator, denominator in (
        ("rate", counts["hits"], counts["known"]),
        ("unknown_lower", counts["hits"], counts["eligible"]),
        ("unknown_upper", counts["hits"] + counts["unknown"], counts["eligible"]),
    ):
        _matches(numbers[field], numerator / denominator if denominator else None, f"{label}.{field}")
    reasons = row["unknown_reasons"]
    if not isinstance(reasons, dict) or any(type(reason) is not str for reason in reasons):
        raise ValueError(f"{label}.unknown_reasons must have string keys")
    if set(reasons) - _allowed_unknown_reasons(row):
        raise ValueError(f"{label}.unknown_reasons contains an undefined unknown reason")
    reason_counts = [_count(count, f"{label}.unknown_reasons[{reason!r}]") for reason, count in reasons.items()]
    if any(count == 0 for count in reason_counts):
        raise ValueError(f"{label}.unknown_reasons buckets must have positive counts")
    if sum(reason_counts) != counts["unknown"]:
        raise ValueError(f"{label}.unknown_reasons must sum to unknown")
    for field, population in QUANTILE_POPULATIONS.items():
        quantile = row[field]
        if not isinstance(quantile, dict) or any(key not in quantile for key in ("value", "known", "unknown")):
            raise ValueError(f"{label}.{field} must contain value, known and unknown")
        known = _count(quantile["known"], f"{label}.{field}.known")
        unknown = _count(quantile["unknown"], f"{label}.{field}.unknown")
        value = _number(quantile["value"], f"{label}.{field}.value")
        if known + unknown != counts[population] or (known == 0 and value is not None):
            raise ValueError(f"{label}.{field} has inconsistent quantile counts/value")
        # Both price bases assign waits with hits, and nonhits require a complete
        # observed path. A null/missing metric is not valid for these populations.
        if known != counts[population] or unknown != 0 or (known > 0 and value is None):
            LOGGER.warning("Incomplete saved quantile cell=%d field=%s population=%d known=%d unknown=%d", index, field, counts[population], known, unknown)
            raise ValueError(f"{label}.{field} has an incomplete quantile population/value")
        if field.startswith("hit_wait_") and value is not None:
            minimum_wait = (row.get("landmark") or 0) + 1
            if not minimum_wait <= value <= row["horizon"]:
                raise ValueError(f"{label}.{field} is outside the original-anchor waiting range")
        # Positive prices bound min(price / anchor - 1) and peak-to-trough loss.
        # Keep the rounded limiting endpoints (-1 and 1) valid.
        if field.startswith("nonhit_min_return_") and value is not None and not -1 <= value < TARGETS[row["horizon"]] - 1:
            raise ValueError(f"{label}.{field} is outside the positive-price return range")
        if field == "nonhit_max_drawdown_median" and value is not None and not 0 <= value <= 1:
            raise ValueError(f"{label}.{field} is outside the positive-price drawdown range")
    _validate_quantile_order(row, label)
    if type(row["small_sample"]) is not bool or row["small_sample"] != (counts["known"] < 30 or counts["known_securities"] < 10):
        raise ValueError(f"{label}.small_sample does not match its descriptive formula")
    for lift, base in (("lift_all_days", "all_day_base_rate"), ("lift_no_event_control", "no_event_control_rate")):
        rate, base_rate = numbers["rate"], numbers[base]
        expected = None if rate is None or base_rate is None or base_rate == 0 else rate / base_rate
        _matches(numbers[lift], expected, f"{label}.{lift}")


def _allowed_unknown_reasons(row: dict[str, Any]) -> frozenset[str]:
    """Enumerate the fixed producers, not strings observed in saved results."""
    if row.get("landmark") is not None:
        # Only active landmarks enter summaries; invalid anchors never get here.
        return frozenset(("missing_before_hit", "window_end"))
    if row["basis"] == "atlas_original":
        reasons = frozenset(("missing_or_invalid_path", "window_end"))
    else:
        reasons = frozenset(("invalid_anchor", "missing_before_hit", "window_end"))
    return reasons | {"no_shift_candidate"} if row["family"] == "noise" else reasons


def _validate_quantile_order(row: dict[str, Any], label: str) -> None:
    """Pandas quantile interpolation preserves order, not integer values."""
    for lower, upper in (
        ("hit_wait_p10", "hit_wait_median"),
        ("hit_wait_median", "hit_wait_p90"),
        ("nonhit_min_return_p10", "nonhit_min_return_median"),
    ):
        lower_value, upper_value = row[lower]["value"], row[upper]["value"]
        if lower_value is not None and upper_value is not None and lower_value > upper_value:
            raise ValueError(f"{label} has reversed quantile order: {lower} > {upper}")


def validate_summary_comparisons(rows: list[dict[str, Any]]) -> None:
    """Check references within a validated fixed grid, not against market sources."""
    bases = {
        (row["family"], row["slice"], row["value"], row["horizon"], row["basis"]): row["rate"]
        for row in rows
        if row["family"] in ("all_stock_days", "high_volume_no_event")
    }
    for index, row in enumerate(rows):
        label = f"summary cell {index}"
        if row.get("landmark") is not None:
            for field in ("all_day_base_rate", "no_event_control_rate", *LIFT_FIELDS):
                if row[field] is not None:
                    raise ValueError(f"{label}.{field} must be null for landmark cells")
            continue
        slice_name, scope = ("year", row["value"]) if row["slice"] == "year" else ("pooled", "all")
        for field, family in (("all_day_base_rate", "all_stock_days"), ("no_event_control_rate", "high_volume_no_event")):
            key = (family, slice_name, scope, row["horizon"], row["basis"])
            _matches(row[field], bases[key], f"{label}.{field} reference")
