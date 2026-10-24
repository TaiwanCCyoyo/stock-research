"""Atomic publication and indexed, metadata-only querying of security-coverage-v1."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import uuid
import zlib
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
MAX_DATABASE_BYTES = 512_000_000
METADATA_MAX_BYTES = 1_000_000
KEY_PATTERN = re.compile(r"s_[0-9a-f]{24}")
MARKS = frozenset(("present", "partial", "missing", "not_applicable", "unknown"))


def family_path(root: Path | None = None) -> Path:
    return safe_path((root if root is not None else shared_data_root()) / "derived" / FAMILY)


def _database_bytes(securities: list[dict[str, Any]]) -> bytes:
    connection = sqlite3.connect(":memory:")
    try:
        dataset_columns = ", ".join(f"m_{name} TEXT NOT NULL" for name in sorted(DATASET_IDS))
        connection.execute(
            f"CREATE TABLE securities (ordinal INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, market TEXT NOT NULL, "
            f"kind TEXT NOT NULL, listing_status TEXT NOT NULL, identity_status TEXT NOT NULL, activity TEXT NOT NULL, "
            f"code TEXT NOT NULL, name TEXT NOT NULL, search TEXT NOT NULL, any_missing INTEGER NOT NULL, "
            f"any_unknown INTEGER NOT NULL, {dataset_columns}, payload BLOB NOT NULL)"
        )
        connection.execute("CREATE INDEX security_code_idx ON securities(code)")
        connection.execute("CREATE INDEX security_market_kind_idx ON securities(market, kind, ordinal)")
        connection.execute("CREATE INDEX security_status_idx ON securities(listing_status, identity_status, activity, ordinal)")
        columns = ["ordinal", "key", "market", "kind", "listing_status", "identity_status", "activity", "code", "name", "search", "any_missing", "any_unknown"]
        columns += [f"m_{name}" for name in sorted(DATASET_IDS)] + ["payload"]
        placeholders = ",".join("?" for _ in columns)
        insert = f"INSERT INTO securities ({','.join(columns)}) VALUES ({placeholders})"
        for ordinal, row in enumerate(securities):
            cells = {cell["dataset"]: cell["mark"] for cell in row["coverage"]}
            if set(cells) != DATASET_IDS:
                raise ValueError("coverage row has invalid dataset set")
            values = [
                ordinal,
                row["key"],
                row["market"],
                row["kind"],
                row["listing_status"],
                row["identity_status"],
                row["activity"],
                row["code"],
                row.get("name") or "",
                f"{row['code']} {row.get('name') or ''}".casefold(),
                int(any(mark == "missing" for mark in cells.values())),
                int(any(mark == "unknown" for mark in cells.values())),
            ]
            values.extend(cells[name] for name in sorted(DATASET_IDS))
            values.append(zlib.compress(canonical(row), level=6))
            connection.execute(insert, values)
        connection.commit()
        data = connection.serialize()
        if len(data) > MAX_DATABASE_BYTES:
            raise ValueError("coverage database exceeds publication limit")
        return data
    finally:
        connection.close()


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
            securities = document.get("securities")
            if not isinstance(securities, list):
                raise ValueError("invalid coverage securities")
            database = _database_bytes(securities)
            metadata = {key: value for key, value in document.items() if key != "securities"}
            metadata.update({
                "generation": generation,
                "storage": {"kind": "sqlite-zlib-v1", "database": "coverage.sqlite", "database_bytes": len(database), "rows": len(securities)},
            })
            metadata_payload = canonical(metadata)
            if len(metadata_payload) > METADATA_MAX_BYTES:
                raise ValueError("coverage metadata exceeds publication limit")
            coverage_digest = object_digest(metadata)
            database_digest = hashlib.sha256(database).hexdigest()
            status = {
                "schema": SCHEMA,
                "family": FAMILY,
                "generation": generation,
                "built_at_utc": document["built_at"],
                "codes": len(securities),
                "rows": sum(len(row["coverage"]) for row in securities),
                "calendar": {"first": document["as_of"], "last": document["as_of"]},
                "data_kind": "observation_summary",
                "coverage_sha256": coverage_digest,
                "database_sha256": database_digest,
                "database_bytes": len(database),
            }
            status_bytes = canonical(status)
            publish_new_directory(
                family / "generations" / generation, {"coverage.json": metadata_payload, "coverage.sqlite": database, "status.json": status_bytes}
            )
            pointer = {
                "schema": SCHEMA,
                "family": FAMILY,
                "generation": generation,
                "coverage_sha256": coverage_digest,
                "database_sha256": database_digest,
                "status_sha256": object_digest(status),
            }
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
        self._cache: (
            tuple[
                tuple[str, str, str, str],
                dict[str, Any],
                tuple[int, int, int, int],
                tuple[int, int, int, int],
            ]
            | None
        ) = None
        self._lock = threading.Lock()

    @staticmethod
    def _file_identity(path: Path) -> tuple[int, int, int, int]:
        stat = path.stat()
        return stat.st_size, stat.st_mtime_ns, getattr(stat, "st_ino", 0), getattr(stat, "st_dev", 0)

    def _native_load(self) -> tuple[dict[str, Any], Path]:
        family = family_path(self.root)
        pointer = read_json(safe_path(family / "current.json"), max_bytes=4096)
        generation = pointer["generation"]
        digest = pointer["coverage_sha256"]
        db_digest = pointer["database_sha256"]
        status_digest = pointer["status_sha256"]
        if pointer.get("schema") != SCHEMA or pointer.get("family") != FAMILY:
            raise ValueError("unsupported coverage pointer")
        if not isinstance(generation, str) or not re.fullmatch(r"[0-9]{8}T[0-9]{6}-[0-9a-f]{12}", generation):
            raise ValueError("invalid generation")
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in (digest, db_digest, status_digest)):
            raise ValueError("invalid digest")
        identity = (generation, digest, db_digest, status_digest)
        with self._lock:
            metadata_path = safe_path(family / "generations" / generation / "coverage.json")
            db_path = safe_path(family / "generations" / generation / "coverage.sqlite")
            metadata_file_identity = self._file_identity(metadata_path)
            database_file_identity = self._file_identity(db_path)
            if self._cache and self._cache[0] == identity and self._cache[2:] == (metadata_file_identity, database_file_identity):
                return self._cache[1], db_path
            if metadata_file_identity[0] > METADATA_MAX_BYTES or file_digest(metadata_path) != digest:
                raise ValueError("invalid coverage metadata")
            metadata = read_json(metadata_path, max_bytes=METADATA_MAX_BYTES)
            if metadata.get("schema") != SCHEMA or metadata.get("generation") != generation or not isinstance(metadata.get("storage"), dict):
                raise ValueError("invalid coverage metadata")
            info = metadata["storage"]
            if info.get("kind") != "sqlite-zlib-v1" or info.get("database") != "coverage.sqlite" or database_file_identity[0] != info.get("database_bytes"):
                raise ValueError("invalid coverage database metadata")
            if database_file_identity[0] > MAX_DATABASE_BYTES or file_digest(db_path) != db_digest:
                raise ValueError("invalid coverage database")
            if file_digest(metadata_path) != digest:
                raise ValueError("coverage metadata changed during read")
            status_path = safe_path(family / "generations" / generation / "status.json")
            status = read_json(status_path, max_bytes=METADATA_MAX_BYTES)
            if object_digest(status) != pointer.get("status_sha256"):
                raise ValueError("invalid coverage status")
            self._cache = (identity, metadata, metadata_file_identity, database_file_identity)
            return metadata, db_path

    def load(self) -> dict[str, Any]:
        """Return verified compact metadata; row payloads are fetched by query methods."""
        try:
            metadata, _ = self._native_load()
            return metadata
        except (OSError, ValueError, TypeError, KeyError) as exc:
            LOGGER.warning("Coverage summary unavailable: %s", exc)
            return {
                "schema": SCHEMA,
                "status": "unavailable",
                "reason": "summary_unavailable",
                "generation": None,
                "built_at": None,
                "as_of": None,
                "securities": [],
                "datasets": [],
                "sources": {},
            }

    def _connection(self) -> tuple[dict[str, Any], sqlite3.Connection]:
        metadata, path = self._native_load()
        uri = path.as_uri() + "?mode=ro&immutable=1"
        return metadata, sqlite3.connect(uri, uri=True)

    @staticmethod
    def _row(payload: bytes) -> dict[str, Any]:
        value = json.loads(zlib.decompress(payload))
        if not isinstance(value, dict):
            raise ValueError("invalid security payload")
        return value

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
        # Synthetic subclasses intentionally retain the historical in-memory contract.
        if type(self).load is not CoverageStore.load:
            return self._list_document(self.load(), market=market, kind=kind, status=status, q=q, dataset=dataset, mark=mark, page=page, size=size)
        try:
            metadata, connection = self._connection()
            try:
                clauses: list[str] = []
                params: list[str | int] = []
                if market:
                    clauses.append("market = ?")
                    params.append(market)
                if kind:
                    clauses.append("kind = ?")
                    params.append(kind)
                if q:
                    clauses.append("instr(search, ?) > 0")
                    params.append(q.casefold())
                if dataset and mark:
                    clauses.append(f"m_{dataset} = ?")
                    params.append(mark)
                base = " WHERE " + " AND ".join(clauses) if clauses else ""
                hidden_row = connection.execute(
                    "SELECT COUNT(*), "
                    "COALESCE(SUM(CASE WHEN listing_status = ? THEN 1 ELSE 0 END), 0), "
                    "COALESCE(SUM(CASE WHEN identity_status = ? THEN 1 ELSE 0 END), 0), "
                    "COALESCE(SUM(CASE WHEN listing_status = ? THEN 1 ELSE 0 END), 0) "
                    "FROM securities" + base,
                    ["delisted", "unresolved", "unknown", *params],
                ).fetchone()
                hidden = {"delisted": hidden_row[1], "unresolved": hidden_row[2], "listing_unknown": hidden_row[3]}
                if status in ("recent", "historical"):
                    clauses.append("activity = ?")
                    params.append(status)
                elif status in ("listed", "delisted", "unknown"):
                    clauses.append("listing_status = ?")
                    params.append(status)
                elif status == "unresolved":
                    clauses.append("identity_status = ?")
                    params.append("unresolved")
                final_where = " WHERE " + " AND ".join(clauses) if clauses else ""
                totals = connection.execute(
                    "SELECT COUNT(*), COALESCE(SUM(any_missing), 0), COALESCE(SUM(any_unknown), 0) FROM securities" + final_where,
                    params,
                ).fetchone()
                total, confirmed_missing, unknown = totals
                rows = [
                    self._row(record[0])
                    for record in connection.execute(
                        "SELECT payload FROM securities" + final_where + " ORDER BY ordinal LIMIT ? OFFSET ?",
                        [*params, size, (page - 1) * size],
                    )
                ]
            finally:
                connection.close()
            return {
                "schema": SCHEMA,
                "status": metadata.get("status", "ok"),
                "reason": metadata.get("reason"),
                "generation": metadata.get("generation"),
                "built_at": metadata.get("built_at"),
                "as_of": metadata.get("as_of"),
                "datasets": metadata.get("datasets", []),
                "sources": metadata.get("sources", {}),
                "rows": rows,
                "total": total,
                "page": page,
                "size": size,
                "hidden": hidden,
                "confirmed_missing": confirmed_missing,
                "unknown": unknown,
            }
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, zlib.error) as exc:
            LOGGER.warning("Coverage summary unavailable: %s", exc)
            return {
                "schema": SCHEMA,
                "status": "unavailable",
                "reason": "summary_unavailable",
                "generation": None,
                "built_at": None,
                "as_of": None,
                "datasets": [],
                "sources": {},
                "rows": [],
                "total": 0,
                "page": page,
                "size": size,
                "hidden": {"delisted": 0, "unresolved": 0, "listing_unknown": 0},
                "confirmed_missing": 0,
                "unknown": 0,
            }

    def _list_document(
        self, document: dict[str, Any], *, market: str, kind: str, status: str, q: str, dataset: str, mark: str, page: int, size: int
    ) -> dict[str, Any]:
        candidates = [row for row in document["securities"] if (not market or row["market"] == market) and (not kind or row["kind"] == kind)]
        candidates = [
            row
            for row in candidates
            if (not q or q.casefold() in (row["code"] + " " + (row.get("name") or "")).casefold())
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
        if type(self).load is not CoverageStore.load:
            document = self.load()
            if document.get("status") == "unavailable":
                return {"schema": SCHEMA, "status": "unavailable", "reason": document["reason"], "security": None}
            row = next((row for row in document["securities"] if row["key"] == key), None)
            if row is None:
                return None
            return {
                "schema": SCHEMA,
                "status": "ok",
                "generation": document.get("generation"),
                "built_at": document.get("built_at"),
                "security": deepcopy(row),
            }
        try:
            metadata, connection = self._connection()
            try:
                record = connection.execute("SELECT payload FROM securities WHERE key = ?", (key,)).fetchone()
            finally:
                connection.close()
            if record is None:
                return None
            return {
                "schema": SCHEMA,
                "status": "ok",
                "generation": metadata.get("generation"),
                "built_at": metadata.get("built_at"),
                "security": self._row(record[0]),
            }
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, zlib.error) as exc:
            LOGGER.warning("Coverage summary unavailable: %s", exc)
            return {"schema": SCHEMA, "status": "unavailable", "reason": "summary_unavailable", "security": None}

    def resolve(self, code: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9]{1,16}", code):
            raise ValueError("invalid security code")
        if type(self).load is not CoverageStore.load:
            document = self.load()
            rows = [row for row in document["securities"] if row["code"] == code]
            return {"schema": SCHEMA, "status": document.get("status", "ok"), "generation": document.get("generation"), "candidates": deepcopy(rows)}
        try:
            metadata, connection = self._connection()
            try:
                rows = [
                    self._row(record[0])
                    for record in connection.execute(
                        "SELECT payload FROM securities WHERE code = ? ORDER BY ordinal",
                        (code,),
                    )
                ]
            finally:
                connection.close()
            return {
                "schema": SCHEMA,
                "status": metadata.get("status", "ok"),
                "generation": metadata.get("generation"),
                "candidates": rows,
            }
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, zlib.error) as exc:
            LOGGER.warning("Coverage summary unavailable: %s", exc)
            return {"schema": SCHEMA, "status": "unavailable", "generation": None, "candidates": []}
