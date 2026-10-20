"""Parse artifact JSON objects without silently discarding identity fields."""

from __future__ import annotations

import json
from typing import Any, NoReturn


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> NoReturn:
    raise ValueError(f"nonfinite JSON constant: {value}")


def strict_json_object(raw: str | bytes) -> dict[str, Any]:
    """Reject duplicate keys, nonfinite constants and a non-object root.

    Byte limits belong to the caller, which already owns the artifact bytes.
    """
    result = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    if not isinstance(result, dict):
        raise ValueError("JSON object required")
    return result
