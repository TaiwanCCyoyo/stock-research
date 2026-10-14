"""Seal the producer research read-set once into an immutable bundle; read it only by pin.

A sealed version lives at `<primary>/research_cache/producer-inputs/<version_id>/`:

    manifest.json                     research-data-bundle.v1; version_id == its SHA-256
    stock-data-downloader/data/...    payload, mirroring the producer layout

The payload mirrors the producer's relative layout so readers that take a data
directory (`DataLoader`, `--data-path`) use `data_root`, and pinned readers that join
`<root>/stock-data-downloader/data/<file>` use `root` without changing their bytes.
Worktrees read a version in place through an explicit absolute root. Nothing is
copied into a worktree or linked; there is no fallback to live producer data.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import sqlite3
import stat
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_core.artifact_store import copy_verified, file_digest, object_digest, publish_noreplace, read_json, relative_name, safe_path, write_json
from research_core.research_data_catalog import CATALOG_FIELDS, DIGEST, DataCatalog
from research_core.research_data_paths import DataRoots, check_tree

LOGGER = logging.getLogger(__name__)
DATA_ID = "producer-inputs"
DEFINITION = "producer-research-read-set.v1"
FAMILY = "research_cache/producer-inputs"
PAYLOAD = "stock-data-downloader/data"
BUNDLE_SCHEMA = "research-data-bundle.v1"
RECEIPT_SCHEMA = "producer-inputs-seal-receipt.v1"
# The read set `scripts/seed_worktree_inputs.py` copied per worktree, sealed once instead.
NAMES = frozenset({
    "price_daily.parquet",
    "data_quality_report.json",
    "corporate_actions.sqlite",
    "symbol_meta.sqlite",
    "stock_symbol_mapping.json5",
    "value_chain_classification.json",
    "dividends.parquet",
    "institutional.sqlite",
    "monthly_revenue.sqlite",
})
DAY_SUFFIX = "_day.csv"
LEGACY_DAILY = "adjusted_prices/daily"
LEGACY_NAMES = frozenset({"price_daily.parquet", "dividends.parquet"})
SIDECARS = ("-wal", "-shm", "-journal")


def select_read_set(source: Path) -> list[str]:
    """Relative names of the whitelisted files present under a producer data root."""
    source = safe_path(source)
    if not source.is_dir():
        raise FileNotFoundError(f"producer data root is unavailable: {source}")
    names = [path.name for path in source.iterdir() if path.is_file() and (path.name in NAMES or path.name.endswith(DAY_SUFFIX))]
    legacy = safe_path(source / LEGACY_DAILY)
    if legacy.exists():
        if not legacy.is_dir():
            raise ValueError(f"legacy daily input must be a directory: {legacy}")
        for path in legacy.iterdir():
            if path.name.endswith((".partial", ".lock")):
                raise ValueError(f"unfinished legacy daily input: {path}")
            if path.is_file() and (path.name in LEGACY_NAMES or path.name.endswith(DAY_SUFFIX)):
                names.append(f"{LEGACY_DAILY}/{path.name}")
    if "price_daily.parquet" not in names:
        raise FileNotFoundError(f"price_daily.parquet missing from producer data root: {source}")
    return sorted(relative_name(name) for name in names)


def _copy_stable(source: Path, target: Path) -> tuple[str, dict[str, Any]]:
    """Copy one file whose size and mtime stay unchanged across the copy."""
    before = source.stat()
    digest = file_digest(source)
    copy_verified(source, target, digest)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"producer file changed during seal: {source}")
    return digest, {"source_bytes": after.st_size, "source_mtime_ns": after.st_mtime_ns, "method": "stable_file_copy"}


def _backup_sqlite(source: Path, target: Path) -> tuple[str, dict[str, Any]]:
    """Consistent online backup of committed state (WAL included), never a live file copy.

    One backup step is one read transaction, so a concurrent writer cannot restart it.
    The copy is converted to rollback-journal mode so a read-only sealed file opens
    without creating `-wal`/`-shm` next to the sealed bytes.
    """
    before = source.stat()
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=30)) as incoming:
        with closing(sqlite3.connect(target)) as outgoing:
            incoming.backup(outgoing)
            mode = outgoing.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if str(mode).lower() != "delete":
                raise ValueError(f"sealed SQLite could not leave WAL mode: {target}")
            if outgoing.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError(f"sealed SQLite failed quick_check: {source}")
    for suffix in SIDECARS:
        if target.with_name(target.name + suffix).exists():
            raise ValueError(f"sealed SQLite left a sidecar: {target}{suffix}")
    observation = {"source_bytes": before.st_size, "source_mtime_ns": before.st_mtime_ns, "method": "sqlite_online_backup_journal_delete_quick_check"}
    return file_digest(target), observation


def _price_period(path: Path) -> dict[str, Any]:
    import pandas as pd

    dates = pd.to_datetime(pd.read_parquet(path, columns=["Date"])["Date"])
    if dates.empty or bool(dates.isna().any()):
        return {"start": None, "end": None, "reason": "price_daily.parquet has no dates or missing dates"}
    return {"start": dates.min().date().isoformat(), "end": dates.max().date().isoformat(), "reason": None}


def _metadata(artifacts: list[dict[str, Any]], period: dict[str, Any]) -> dict[str, Any]:
    """Deterministic for the sealed content, so identical content gets the same version."""
    not_applicable = {"start": None, "end": None, "reason": "not applicable: raw producer inputs, no indicators or labels"}
    return {
        "data_id": DATA_ID,
        # An existing kind: a new one would make catalog readers on older code reject the whole catalog.
        "kind": "prices",
        "definition_version": DEFINITION,
        "parameters": {
            "names": sorted(NAMES),
            "day_csv_suffix": DAY_SUFFIX,
            "legacy_daily": LEGACY_DAILY,
            "legacy_names": sorted(LEGACY_NAMES),
            "payload_root": PAYLOAD,
            "sqlite": "online backup API, journal_mode=DELETE, quick_check ok",
        },
        "inputs": {"producer_files_sha256": object_digest(artifacts), "file_count": len(artifacts), "bytes": sum(row["bytes"] for row in artifacts)},
        "coverage": {
            "scope": "producer research read-set whitelist at seal time; price period from price_daily.parquet",
            "raw_input_period": period,
            "valid_indicator_period": not_applicable,
            "complete_label_period": not_applicable,
        },
        "status": "complete",
        "limitations": [
            "Files are observed one after another; the bundle is not a cross-file point-in-time transaction. Seal only while producer writers are idle.",
            "SQLite members are online-backup snapshots of committed state in rollback-journal mode; byte equality with the live file is not expected.",
            "price_daily.parquet dates bound the raw period; other members keep their own coverage.",
            "Legacy adjusted_prices/daily inputs are included only when present at seal time.",
        ],
        "backup": {"status": "unknown", "reason": "research_cache is in artifact_backup scope; no backup receipt covers this version yet"},
    }


def _remove_staging(staging: Path) -> None:
    """Remove this invocation's own unpublished staging tree; it holds no link or read-only file."""
    check_tree(staging)
    shutil.rmtree(staging)
    LOGGER.info("Removed unpublished staging: %s", staging)


def _receipt(roots: DataRoots, version_id: str, body: dict[str, Any]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = roots.artifact_path("primary", f"{FAMILY}/receipts/{version_id}/{stamp}-{uuid.uuid4().hex}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, body)
    return path


def catalog_entry(sealed: SealedProducerInputs) -> dict[str, Any]:
    return {
        **{key: sealed.manifest["metadata"][key] for key in CATALOG_FIELDS},
        "version_id": sealed.version_id,
        "reader": "bundle",
        "manifest": {"scope": "primary", "path": f"{FAMILY}/{sealed.version_id}/manifest.json", "sha256": sealed.manifest_sha256},
    }


def seal_producer_inputs(source: Path, roots: DataRoots, *, register: bool = True) -> dict[str, Any]:
    """Seal `source` into a new version, or reuse the identical existing one.

    Members are verified exactly once after publication: by catalog registration when
    `register` is true, otherwise by `verify_all`. A failed seal removes its own staging.
    """
    timings: dict[str, float] = {}
    clock = time.perf_counter()
    source = safe_path(source)
    names = select_read_set(source)
    family = roots.artifact_path("primary", FAMILY)
    family.mkdir(parents=True, exist_ok=True)
    staging = roots.artifact_path("primary", f"{FAMILY}/.staging-{uuid.uuid4().hex}")
    staging.mkdir()
    LOGGER.info("Sealing producer inputs: source=%s files=%d staging=%s", source, len(names), staging)
    published = False
    try:
        artifacts: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        for name in names:
            incoming = safe_path(source / name)
            outgoing = roots.artifact_path("primary", f"{staging.relative_to(roots.primary).as_posix()}/{PAYLOAD}/{name}")
            outgoing.parent.mkdir(parents=True, exist_ok=True)
            digest, observed = (_backup_sqlite if name.endswith(".sqlite") else _copy_stable)(incoming, outgoing)
            artifacts.append({"path": f"{PAYLOAD}/{name}", "bytes": outgoing.stat().st_size, "sha256": digest})
            observations.append({"path": name, **observed})
        timings["capture_seconds"] = round(time.perf_counter() - clock, 3)
        period = _price_period(staging / PAYLOAD / "price_daily.parquet")
        body: dict[str, Any] = {
            "schema": BUNDLE_SCHEMA,
            "complete": True,
            "metadata": _metadata(artifacts, period),
            "lineage": {"sealer": "research_core.producer_inputs", "definition_version": DEFINITION},
            "artifacts": artifacts,
        }
        version_id = object_digest(body)
        target = roots.artifact_path("primary", f"{FAMILY}/{version_id}")
        reused = target.exists()
        if reused:
            LOGGER.info("Identical sealed version already exists: %s", version_id)
            if read_json(target / "manifest.json", max_bytes=64_000_000) != body:
                raise ValueError(f"existing sealed version disagrees with its content id: {target}")
        else:
            write_json(staging / "manifest.json", body)
            publish_noreplace(staging, target)
            published = True
            for directory, _, files in os.walk(target, followlinks=False):
                for name in files:
                    path = Path(directory) / name
                    path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        clock = time.perf_counter()
        sealed = open_producer_inputs(roots, version_id, version_id)
        if register:
            DataCatalog(roots).register([catalog_entry(sealed)])
        else:
            sealed.verify_all()
        timings["verify_seconds"] = round(time.perf_counter() - clock, 3)
    finally:
        if not published and staging.exists():
            _remove_staging(staging)
    receipt = _receipt(
        roots,
        version_id,
        {
            "schema": RECEIPT_SCHEMA,
            "version_id": version_id,
            "reused_existing_version": reused,
            "registered": register,
            "source_root": str(source),
            "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_observations": observations,
            "timings": timings,
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
        },
    )
    LOGGER.info("Sealed producer inputs version=%s reused=%s timings=%s", version_id, reused, timings)
    return {
        "data_id": DATA_ID,
        "version_id": version_id,
        "manifest_sha256": version_id,
        "path": str(target),
        "reused_existing_version": reused,
        "registered": register,
        "receipt": str(receipt),
        "files": len(artifacts),
        "bytes": body["metadata"]["inputs"]["bytes"],
        "raw_input_period": period,
        "timings": timings,
    }


@dataclass(frozen=True)
class SealedProducerInputs:
    """One opened, pinned version. `path` verifies the bytes of each member it hands out."""

    version_id: str
    manifest_sha256: str
    root: Path
    manifest: dict[str, Any]
    _verified: set[str] = field(default_factory=set, compare=False, repr=False)

    @property
    def data_root(self) -> Path:
        """Directory with the producer layout, for readers that take a data directory."""
        return self.root / PAYLOAD

    def _entry(self, name: str) -> dict[str, Any]:
        key = f"{PAYLOAD}/{relative_name(name)}"
        for row in self.manifest["artifacts"]:
            if row["path"] == key:
                return row
        raise KeyError(f"{name} is not part of sealed producer inputs {self.version_id}")

    def path(self, name: str) -> Path:
        """Return a member path relative to `data_root`, hashing its bytes on first use."""
        row = self._entry(name)
        path = self.root / row["path"]
        if row["path"] not in self._verified:
            if path.stat().st_size != row["bytes"] or file_digest(path) != row["sha256"]:
                raise ValueError(f"sealed producer input hash/size mismatch: {row['path']}")
            self._verified.add(row["path"])
        return path

    def names(self) -> list[str]:
        return [row["path"].removeprefix(f"{PAYLOAD}/") for row in self.manifest["artifacts"]]

    def verify_all(self) -> None:
        """Hash every member not already verified by this instance."""
        for name in self.names():
            self.path(name)


def open_producer_inputs(roots: DataRoots, version_id: str, manifest_sha256: str) -> SealedProducerInputs:
    """Resolve one pinned version under the explicit primary root; never a live fallback.

    Checks the manifest pin and content id, rejects any link, hardlink, unlisted file or
    size difference, and defers member hashing to `path`/`verify_all`.
    """
    for value in (version_id, manifest_sha256):
        if not isinstance(value, str) or not DIGEST.fullmatch(value):
            raise ValueError("explicit 64-hex version_id and manifest_sha256 required")
    root = roots.artifact_path("primary", f"{FAMILY}/{version_id}")
    manifest_path = roots.artifact_path("primary", f"{FAMILY}/{version_id}/manifest.json")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"sealed producer inputs missing: {root}")
    if file_digest(manifest_path) != manifest_sha256:
        raise ValueError(f"sealed producer inputs manifest pin mismatch: {version_id}")
    manifest = read_json(manifest_path, max_bytes=64_000_000)
    if (
        object_digest(manifest) != version_id
        or manifest.get("schema") != BUNDLE_SCHEMA
        or manifest.get("complete") is not True
        or manifest.get("metadata", {}).get("data_id") != DATA_ID
    ):
        raise ValueError(f"sealed producer inputs identity mismatch: {version_id}")
    check_tree(root)
    listed = {relative_name(row["path"]) for row in manifest["artifacts"]}
    if any(not name.startswith(f"{PAYLOAD}/") for name in listed) or len(listed) != len(manifest["artifacts"]):
        raise ValueError(f"sealed producer inputs list an unexpected member: {version_id}")
    present = {(Path(directory) / name).relative_to(root).as_posix() for directory, _, files in os.walk(root, followlinks=False) for name in files}
    if present != listed | {"manifest.json"}:
        raise ValueError(f"sealed producer inputs members differ from manifest: {sorted(present ^ (listed | {'manifest.json'}))}")
    for row in manifest["artifacts"]:
        if (root / row["path"]).stat().st_size != row["bytes"]:
            raise ValueError(f"sealed producer input size mismatch: {row['path']}")
    LOGGER.debug("Opened sealed producer inputs version=%s files=%d", version_id, len(listed))
    return SealedProducerInputs(version_id, manifest_sha256, root, manifest)


def open_from_env(version_id: str, manifest_sha256: str) -> SealedProducerInputs:
    """`open_producer_inputs` with the primary root from STOCK_RESEARCH_DATA_ROOT."""
    return open_producer_inputs(DataRoots.from_env(), version_id, manifest_sha256)
