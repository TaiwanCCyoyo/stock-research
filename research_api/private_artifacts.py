"""Allowlisted local reads of external private presentation artifacts."""

from __future__ import annotations

import gzip
import json
import os
import zlib
from pathlib import Path

from fastapi import APIRouter, HTTPException

MAX_BYTES = 32 * 1024 * 1024
NAMES = {"opportunity-explorer", "saved-research-runs"}


def read_private_artifact(name: str, root: Path) -> object:
    if name not in NAMES:
        raise ValueError("unknown artifact")
    if not root.is_absolute():
        raise ValueError("private artifact root must be absolute")
    root = root.resolve(strict=True)
    path = root / f"{name}.json.gz"
    if path.resolve(strict=True).parent != root:
        raise ValueError("artifact escapes private root")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("compressed artifact exceeds limit")
    with gzip.open(path, "rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("decoded artifact exceeds limit")
    return json.loads(raw)


def create_private_artifact_router() -> APIRouter:
    router = APIRouter(prefix="/private-artifacts/v1")

    @router.get("/{name}")
    def artifact(name: str) -> object:
        if name not in NAMES:
            raise HTTPException(404, "unknown artifact")
        root = os.environ.get("STOCK_PRIVATE_ARTIFACT_ROOT")
        if os.environ.get("STOCK_RESEARCH_DATA_MODE", "public-synthetic") != "local-private" or not root:
            raise HTTPException(503, "private data unavailable", headers={"X-Research-Evidence-Error": "unavailable"})
        try:
            value = read_private_artifact(name, Path(root))
            if not isinstance(value, dict):
                raise ValueError("artifact must be an object")
            return {**value, "dataMode": "local-private", "synthetic": False}
        except (OSError, ValueError, EOFError, zlib.error):
            raise HTTPException(503, "private data unavailable or invalid", headers={"X-Research-Evidence-Error": "unavailable"}) from None

    return router
