"""Bounded receipt I/O for full-market scan inventories and phase results."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from research_core.artifact_store import publish_noreplace, read_json, write_json
from research_core.research_data_paths import _checked_path

LOGGER = logging.getLogger(__name__)
MAX_SCAN_RECEIPT_BYTES = 512_000_000


def read_scan_receipt(path: Path) -> dict[str, Any]:
    """Read a retained scan index under an explicit finite metadata budget."""
    return read_json(_checked_path(path), max_bytes=MAX_SCAN_RECEIPT_BYTES)


def publish_scan_receipt(path: Path, value: dict[str, Any]) -> None:
    """Check serialized size before atomic no-replace publication.

    Interrupted or oversized staging stays available for diagnosis. The shared
    JSON writer and publication primitive retain their existing byte contracts.
    """
    path = _checked_path(path)
    staging = _checked_path(path.with_name(f".staging-{path.name}-{uuid.uuid4().hex}"))
    write_json(staging, value)
    size = staging.stat().st_size
    if size > MAX_SCAN_RECEIPT_BYTES:
        raise ValueError(f"scan receipt exceeds finite metadata budget: bytes={size} retained={staging}")
    publish_noreplace(staging, path)
    LOGGER.info("Published scan receipt path=%s bytes=%d", path, size)
