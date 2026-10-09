"""The test author approves each assembled fixture with an explicit hash pin.

Trust rejection tests use real entrypoints with an earlier externally captured
pin; these wrappers serve semantic focused tests only.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from scripts.query_opportunity_history import query_manifest as _query_manifest
from scripts.verify_opportunity_history import verify_catalog as _verify_catalog


def fixture_manifest_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def query_manifest(manifest_path: Path, code: str, date: str) -> dict[str, Any]:
    return _query_manifest(manifest_path, code, date, expected_manifest_sha256=fixture_manifest_sha256(manifest_path))


def verify_catalog(manifest_path: Path, params_path: Path | None = None) -> dict[str, Any]:
    return _verify_catalog(manifest_path, params_path=params_path, expected_manifest_sha256=fixture_manifest_sha256(manifest_path))
