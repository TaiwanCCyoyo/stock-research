"""Complete, explicit disk estimates before a full pattern-scan execution."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from research_core.artifact_store import read_json

COMPONENTS = (
    "prepared_prices",
    "stock_checkpoints",
    "stock_publication",
    "global_barrier",
    "barrier_publication",
    "event_checkpoints",
    "event_publication",
    "summaries",
    "followup_observations",
    "episodes_publication",
    "report_publication",
    "retained_staging",
)


def assess_capacity(plan: dict[str, Any], *, available_bytes: int) -> dict[str, Any]:
    """Unknown components cannot certify capacity; estimates include coexisting copies."""
    if plan.get("schema") != "pattern-scan-capacity.v2" or type(available_bytes) is not int or available_bytes < 0:
        raise ValueError("explicit capacity plan and measured free bytes required")
    components = plan.get("components")
    reserve = plan.get("reserve_bytes")
    if not isinstance(components, dict) or set(components) != set(COMPONENTS) or type(reserve) is not int or reserve <= 0:
        raise ValueError("all disk components and positive reserve required")
    unknown = []
    measured = 0
    for name, record in components.items():
        if not isinstance(record, dict) or not isinstance(record.get("evidence"), str) or not record["evidence"].strip():
            raise ValueError(f"capacity evidence required: {name}")
        value = record.get("estimated_bytes")
        if value is None:
            unknown.append(name)
        elif type(value) is not int or value < 0:
            raise ValueError(f"invalid capacity estimate: {name}")
        else:
            measured += value
    required = measured + reserve
    return {
        "available_bytes": available_bytes,
        "known_estimate_bytes": measured,
        "reserve_bytes": reserve,
        "required_bytes": None if unknown else required,
        "unknown_components": sorted(unknown),
        "sufficient": not unknown and available_bytes >= required,
    }


def require_capacity(plan_path: Path | None, primary: Path) -> dict[str, Any]:
    if plan_path is None:
        raise ValueError("full-market execution requires an evidenced complete capacity plan; use a bounded profile first")
    result = assess_capacity(read_json(plan_path), available_bytes=shutil.disk_usage(primary).free)
    if not result["sufficient"]:
        raise ValueError(f"full-market capacity is not established: {result}")
    return result
