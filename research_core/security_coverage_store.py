"""Atomic publication and metadata-only querying of security-coverage-v1."""

from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_core.artifact_store import (
    canonical,
    file_digest,
    object_digest,
    publish_new_directory,
    read_json,
    release_os_lock,
    safe_path,
    try_os_lock,
    write_json,
)
from research_core.security_coverage import DATASET_IDS, FAMILY, SCHEMA
from research_core.shared_data import shared_data_root

LOGGER = logging.getLogger(__name__)
MAX_BYTES = 128_000_000
KEY_PATTERN = re.compile(r"s_[0-9a-f]{24}")
MARKS = frozenset(("present", "partial", "missing", "not_applicable", "unknown"))


def family_path(root: Path | None = None) -> Path:
    return safe_path((root if root is not None else shared_data_root()) / "derived" / FAMILY)


def publish_coverage(document: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Single writer, immutable generations, atomic current switch; no pruning."""
    if document.get("schema") != SCHEMA:
        raise ValueError("unsupported coverage schema")
    family = family_path(root)
    family.mkdir(parents=True, exist_ok=True)
    lock_path = safe_path(family / ".writer.lock")
    with lock_path.open("a+b") as lock:
        if not lock_path.stat().st_size:
            lock.write(b"0")
            lock.flush()
        if not try_os_lock(lock):
            raise RuntimeError("coverage maintenance is already running")
        try:
            generation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]
            payload = canonical({**document, "generation": generation})
            if len(payload) > MAX_BYTES:
                raise ValueError("coverage metadata exceeds publication limit")
            digest = object_digest({**document, "generation": generation})
            status = {
                "schema": SCHEMA,
                "family": FAMILY,
                "generation": generation,
                "built_at_utc": document["built_at"],
                "codes": len(document["securities"]),
                "rows": sum(len(row["coverage"]) for row in document["securities"]),
                "calendar": {"first": document["as_of"], "last": document["as_of"]},
                "data_kind": "observation_summary",
                "coverage_sha256": digest,
            }
            status_bytes = canonical(status)
            publish_new_directory(family / "generations" / generation, {"coverage.json": payload, "status.json": status_bytes})
            pointer = {"schema": SCHEMA, "family": FAMILY, "generation": generation, "coverage_sha256": digest, "status_sha256": object_digest(status)}
            staged = safe_path(family / (".current-" + uuid.uuid4().hex + ".json"))
            write_json(staged, pointer)
            os.replace(staged, safe_path(family / "current.json"))
            return pointer
        finally:
            release_os_lock(lock)


class CoverageStore:
    """Cache one verified immutable summary, never resolve or scan producer inputs."""

    def __init__(self, root: Path | None = None):
        self.root = root
        self._cache: tuple[tuple[str, str], dict[str, Any]] | None = None
        self._lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        try:
            family = family_path(self.root)
            pointer = read_json(safe_path(family / "current.json"), max_bytes=4096)
            generation, digest = pointer["generation"], pointer["coverage_sha256"]
            if pointer.get("schema") != SCHEMA or pointer.get("family") != FAMILY:
                raise ValueError("unsupported coverage pointer")
            if not isinstance(generation, str) or not re.fullmatch(r"[0-9]{8}T[0-9]{6}-[0-9a-f]{12}", generation):
                raise ValueError("invalid generation")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("invalid digest")
            identity = (generation, digest)
            with self._lock:
                if self._cache and self._cache[0] == identity:
                    return self._cache[1]
                path = safe_path(family / "generations" / generation / "coverage.json")
                if path.stat().st_size > MAX_BYTES or file_digest(path) != digest:
                    raise ValueError("invalid coverage content")
                document = read_json(path, max_bytes=MAX_BYTES)
                if document.get("schema") != SCHEMA or document.get("generation") != generation or not isinstance(document.get("securities"), list):
                    raise ValueError("invalid coverage document")
                if file_digest(path) != digest:
                    raise ValueError("coverage changed during read")
                self._cache = (identity, document)
                return document
        except (OSError, ValueError, TypeError, KeyError) as exc:
            LOGGER.warning("Coverage summary unavailable: %s", exc)
            return {"schema": SCHEMA, "status": "unavailable", "reason": "summary_unavailable", "securities": [], "datasets": [], "sources": {}}

    def list(
        self, *, market: str = "", kind: str = "", status: str = "", q: str = "", dataset: str = "", mark: str = "", page: int = 1, size: int = 50
    ) -> dict[str, Any]:
        if market not in ("", "TWSE", "TPEx", "unknown") or kind not in ("", "stock", "etf", "unknown"):
            raise ValueError("invalid market or instrument kind")
        if status not in ("", "all", "recent", "historical", "listed", "delisted", "unresolved", "unknown"):
            raise ValueError("invalid status")
        if dataset and dataset not in DATASET_IDS or mark and mark not in MARKS:
            raise ValueError("invalid coverage filter")
        if mark and not dataset:
            raise ValueError("mark requires a dataset")
        if not 1 <= page <= 100_000 or not 1 <= size <= 200 or len(q) > 100:
            raise ValueError("invalid pagination or query")
        document = self.load()
        candidates = [row for row in document["securities"] if (not market or row["market"] == market) and (not kind or row["kind"] == kind)]
        candidates = [
            row
            for row in candidates
            if (not q or q.casefold() in (row["code"] + " " + (row["name"] or "")).casefold())
            and (not dataset or not mark or any(cell["dataset"] == dataset and cell["mark"] == mark for cell in row["coverage"]))
        ]
        hidden = {
            "delisted": sum(row["listing_status"] == "delisted" for row in candidates),
            "unresolved": sum(row["identity_status"] == "unresolved" for row in candidates),
            "listing_unknown": sum(row["listing_status"] == "unknown" for row in candidates),
        }
        selected = []
        for row in candidates:
            if status in ("recent", "historical") and row["activity"] != status:
                continue
            if status in ("listed", "delisted", "unknown") and row["listing_status"] != status:
                continue
            if status == "unresolved" and row["identity_status"] != "unresolved":
                continue
            if q and q.casefold() not in (row["code"] + " " + (row["name"] or "")).casefold():
                continue
            if dataset:
                cell = next(cell for cell in row["coverage"] if cell["dataset"] == dataset)
                if mark and cell["mark"] != mark:
                    continue
            selected.append(row)
        start = (page - 1) * size
        return {
            "schema": SCHEMA,
            "status": document.get("status", "ok"),
            "reason": document.get("reason"),
            "generation": document.get("generation"),
            "built_at": document.get("built_at"),
            "as_of": document.get("as_of"),
            "datasets": document.get("datasets", []),
            "sources": document.get("sources", {}),
            "rows": deepcopy(selected[start : start + size]),
            "total": len(selected),
            "page": page,
            "size": size,
            "hidden": hidden,
            "confirmed_missing": sum(any(c["mark"] == "missing" for c in row["coverage"]) for row in selected),
            "unknown": sum(any(c["mark"] == "unknown" for c in row["coverage"]) for row in selected),
        }

    def detail(self, key: str) -> dict[str, Any] | None:
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError("invalid security key")
        document = self.load()
        if document.get("status") == "unavailable":
            return {"schema": SCHEMA, "status": "unavailable", "reason": document["reason"], "security": None}
        row = next((row for row in document["securities"] if row["key"] == key), None)
        if row is None:
            return None
        return {"schema": SCHEMA, "status": "ok", "generation": document.get("generation"), "built_at": document.get("built_at"), "security": deepcopy(row)}

    def resolve(self, code: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9]{1,16}", code):
            raise ValueError("invalid security code")
        document = self.load()
        rows = [row for row in document["securities"] if row["code"] == code]
        return {"schema": SCHEMA, "status": document.get("status", "ok"), "generation": document.get("generation"), "candidates": deepcopy(rows)}
