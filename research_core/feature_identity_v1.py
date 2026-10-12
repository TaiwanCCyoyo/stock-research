"""Exact feature identities and additive counts, without calculation policy."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from research_core.artifact_store import canonical, object_digest, relative_name

LOGGER = logging.getLogger(__name__)
_FIELDS = {
    "schema",
    "feature_id",
    "definition",
    "stock_code",
    "scope",
    "inputs",
    "implementation",
    "calendar",
    "semantics",
    "parameters",
    "runtime",
    "context",
}
_SEMANTICS = {
    "price_basis",
    "gap",
    "warmup",
    "pivot_availability",
    "calendar_policy",
    "quality_policy",
}


def _string(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")


def _object(value: Any, label: str, *, nonempty: bool = True) -> None:
    if not isinstance(value, dict) or (nonempty and not value):
        raise ValueError(f"{label} must be a {'nonempty ' if nonempty else ''}JSON object")


def _json_types(value: Any) -> None:
    """Reject values that JSON encoding would silently coerce."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            _json_types(item)
    elif isinstance(value, list):
        for item in value:
            _json_types(item)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("identity must contain only JSON values")


def _sha256(value: Any, label: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} must be a lowercase SHA256")


def _count(value: Any, label: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a nonnegative Python integer")


def validate_identity(value: dict[str, Any]) -> dict[str, Any]:
    """Validate and detach a finite JSON identity; preserve original strings.

    Nested metadata remains part of the identity. No compatibility inference or
    default calculation semantics are applied.
    """
    _object(value, "identity")
    if set(value) != _FIELDS:
        raise ValueError("identity requires exactly the schema fields")
    _json_types(value)
    # The public canonical encoder also rejects NaN and infinities.
    detached = json.loads(canonical(value))
    if detached["schema"] != "research-feature-block.v1":
        raise ValueError("unsupported feature identity schema")
    for name in ("feature_id", "stock_code"):
        _string(detached[name], name)
    _object(detached["definition"], "definition")
    for name in ("id", "version"):
        _string(detached["definition"].get(name), f"definition.{name}")
    if detached["scope"] not in ("stock", "cross_section"):
        raise ValueError("scope must be stock or cross_section")
    for field in ("inputs", "implementation"):
        _object(detached[field], field)
        for name, digest in detached[field].items():
            _string(name, f"{field} name")
            if field == "implementation":
                relative_name(name)
            _sha256(digest, f"{field}.{name}")
    calendar = detached["calendar"]
    _object(calendar, "calendar")
    _sha256(calendar.get("sha256"), "calendar.sha256")
    _count(calendar.get("rows"), "calendar.rows")
    for name in ("start", "end"):
        day = calendar.get(name)
        if not isinstance(day, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) is None:
            raise ValueError(f"calendar.{name} must be an ISO date")
        date.fromisoformat(day)
    _object(detached["semantics"], "semantics")
    for name in _SEMANTICS:
        _string(detached["semantics"].get(name), f"semantics.{name}")
    _object(detached["parameters"], "parameters", nonempty=False)
    _object(detached["runtime"], "runtime")
    if detached["context"] is not None:
        _object(detached["context"], "context")
    elif detached["scope"] == "cross_section":
        raise ValueError("cross_section requires nonnull context")
    LOGGER.debug("Validated feature identity with scope %s", detached["scope"])
    return detached


def identity_digest(value: dict[str, Any]) -> str:
    """Digest the complete validated identity, without compatibility aliases."""
    return object_digest(validate_identity(value))


def merge_count_batches(batches: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Sum counts for one slice and union stock codes; never average rates."""
    seen: set[str] = set()
    stocks: set[str] = set()
    counts: dict[str, int] = {}
    slice_id: str | None = None
    for batch in batches:
        _object(batch, "batch")
        if set(batch) != {"batch_id", "slice_id", "counts", "stocks"}:
            raise ValueError("batch requires exactly batch_id, slice_id, counts, stocks")
        for name in ("batch_id", "slice_id"):
            _string(batch[name], name)
        if batch["batch_id"] in seen:
            raise ValueError("duplicate batch_id")
        if slice_id is not None and batch["slice_id"] != slice_id:
            raise ValueError("cannot merge mixed slice_id values")
        slice_id = batch["slice_id"]
        seen.add(batch["batch_id"])
        _object(batch["counts"], "counts", nonempty=False)
        for name, count in batch["counts"].items():
            _string(name, "count name")
            _count(count, f"counts.{name}")
            counts[name] = counts.get(name, 0) + count
        codes = batch["stocks"]
        if not isinstance(codes, Sequence) or isinstance(codes, (str, bytes, bytearray)):
            raise ValueError("stocks must be a sequence of original string codes")
        for code in codes:
            _string(code, "stock code")
            stocks.add(code)
    LOGGER.debug("Merged %d count batches with %d unique stocks", len(seen), len(stocks))
    return {
        "slice_id": slice_id,
        "counts": dict(sorted(counts.items())),
        "stocks": sorted(stocks),
        "stock_n": len(stocks),
        "batch_n": len(seen),
    }
