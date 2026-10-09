"""Content-addressed additive backup and verified, new-destination restore."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from research_core.artifact_store import (
    copy_verified,
    file_digest,
    object_digest,
    publish_noreplace,
    read_json,
    relative_name,
    safe_path,
    verify_files,
    write_json,
)

LOGGER = logging.getLogger(__name__)
SCHEMA = "stock-research-backup.v1"
DIGEST = re.compile(r"[0-9a-f]{64}")


def default_sources(project: Path) -> dict[str, Path]:
    """Only Stock cache and formal task datasets/owner labels; not broker data."""
    project = safe_path(project)
    sources: dict[str, Path] = {}
    cache = project / "research_cache"
    if cache.is_dir():
        sources["research_cache"] = cache
    tasks = project / "tasks"
    if tasks.is_dir():
        for task in sorted(tasks.iterdir()):
            safe_path(task)
            if not task.is_dir():
                continue
            datasets = task / "datasets"
            if datasets.is_dir():
                sources[f"tasks/{task.name}/datasets"] = datasets
            if task.name == "20261010-owner-hhhl-labels":
                sources[f"tasks/{task.name}"] = task
                sources.pop(f"tasks/{task.name}/datasets", None)
    if not sources:
        raise ValueError("no research datasets/cache/owner labels found")
    return sources


def _inventory(sources: dict[str, Path], frozen_sqlite: dict[Path, str] | None = None) -> list[dict[str, Any]]:
    frozen_sqlite = {safe_path(path): digest for path, digest in (frozen_sqlite or {}).items()}
    records: list[dict[str, Any]] = []
    for name, root in sorted(sources.items()):
        relative_name(name)
        root = safe_path(root)
        if not root.is_dir():
            raise ValueError(f"source directory missing: {root}")
        for path in sorted(root.rglob("*")):
            safe_path(path)
            if path.is_dir():
                continue
            database = path.suffix.lower() in {".sqlite", ".db", ".sqlite3"}
            frozen_hash = frozen_sqlite.get(path)
            if database and frozen_hash is not None:
                if (
                    not DIGEST.fullmatch(frozen_hash)
                    or file_digest(path) != frozen_hash
                    or any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))
                ):
                    raise ValueError(f"frozen SQLite identity/closed-state mismatch: {path}")
            if path.name.startswith(".env") or ".git" in path.parts or (database and frozen_hash is None) or path.name.endswith(("-wal", "-shm", "-journal")):
                raise ValueError(f"private or potentially live database requires separate snapshot procedure: {path}")
            if any(part.startswith(".staging-") or part.endswith(".lock") for part in path.relative_to(root).parts):
                raise ValueError(f"unfinished cache build blocks coherent backup: {path}")
            records.append({
                "path": relative_name(f"{name}/{path.relative_to(root).as_posix()}"),
                "source": str(path),
                "bytes": path.stat().st_size,
                "sha256": file_digest(path),
            })
    paths = [row["path"] for row in records]
    if not paths or len(paths) != len(set(paths)):
        raise ValueError("backup requires nonempty nonoverlapping file inventory")
    return records


def verify_backup(manifest_path: Path) -> dict[str, Any]:
    """Verify all content objects without writing or repairing anything."""
    manifest_path = safe_path(manifest_path)
    manifest = read_json(manifest_path, max_bytes=64_000_000)
    files = manifest.get("files")
    if manifest.get("schema") != SCHEMA or manifest.get("complete") is not True or not isinstance(files, list) or not files:
        raise ValueError("incomplete backup")
    if object_digest({"schema": SCHEMA, "files": files}) != manifest.get("snapshot_id") or manifest_path.stem != manifest["snapshot_id"]:
        raise ValueError("backup snapshot identity mismatch")
    root = manifest_path.parent.parent
    names: set[str] = set()
    for entry in files:
        name = relative_name(entry["path"])
        digest = entry.get("sha256")
        size = entry.get("bytes")
        if name in names or not isinstance(digest, str) or not DIGEST.fullmatch(digest) or isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("invalid backup descriptor")
        names.add(name)
        path = safe_path(root / "objects" / digest)
        if path.stat().st_size != size or file_digest(path) != digest:
            raise ValueError(f"backup object corrupt: {name}")
    return manifest


def _seed_object(source: Path, destination: Path, digest: str, size: int) -> None:
    """Publish verified bytes once; preserve interrupted copies for inspection."""
    lock = safe_path(destination.parent / f".{digest}.lock")
    # Acquisition is outside finally: a competing writer's lock is never ours.
    with lock.open("x", encoding="utf-8"):
        pass
    try:
        if destination.exists():
            raise FileExistsError(f"backup object appeared before copy: {destination}")
        partial = safe_path(destination.parent / f".{digest}.backup-{uuid.uuid4().hex}.partial")
        copy_verified(source, partial, digest)
        if partial.stat().st_size != size or file_digest(partial) != digest:
            raise ValueError(f"backup partial hash/size mismatch: {partial}")
        safe_path(destination)
        if destination.exists():
            raise FileExistsError(f"backup object appeared during copy: {destination}")
        publish_noreplace(partial, destination)
    finally:
        lock.unlink()


def _publish_manifest(destination: Path, manifest: dict[str, Any]) -> None:
    """Publish complete canonical JSON once without stranding a partial final."""
    snapshot_id = destination.stem
    lock = safe_path(destination.parent / f".{snapshot_id}.lock")
    with lock.open("x", encoding="utf-8"):
        pass
    try:
        if destination.exists():
            raise FileExistsError(f"backup snapshot appeared before write: {destination}")
        partial = safe_path(destination.parent / f".{snapshot_id}.snapshot-{uuid.uuid4().hex}.partial")
        write_json(partial, manifest)
        if file_digest(partial) != object_digest(manifest):
            raise ValueError(f"backup snapshot partial hash mismatch: {partial}")
        safe_path(destination)
        if destination.exists():
            raise FileExistsError(f"backup snapshot appeared during write: {destination}")
        publish_noreplace(partial, destination)
    finally:
        lock.unlink()


def backup_sources(sources: dict[str, Path], root: Path, *, frozen_sqlite: dict[Path, str] | None = None) -> dict[str, Any]:
    """Add new content/snapshot only; retain an incomplete attempt on failure."""
    root = safe_path(root)
    for source in sources.values():
        source = safe_path(source)
        if source == root or source in root.parents or root in source.parents:
            raise ValueError("backup/source trees must not overlap")
    records = _inventory(sources, frozen_sqlite)
    files = [{key: row[key] for key in ("path", "bytes", "sha256")} for row in records]
    snapshot_id = object_digest({"schema": SCHEMA, "files": files})
    objects, snapshots, attempts, completions = root / "objects", root / "snapshots", root / "attempts", root / "completions"
    for directory in (objects, snapshots, attempts, completions):
        directory.mkdir(parents=True, exist_ok=True)
    attempt = attempts / f"{uuid.uuid4().hex}.json"
    write_json(
        attempt,
        {"schema": SCHEMA, "state": "started", "complete": False, "snapshot_id": snapshot_id, "sources": {name: str(path) for name, path in sources.items()}},
    )
    attempt_digest = file_digest(attempt)
    copied, reused = 0, 0
    for row in records:
        object_path = safe_path(objects / row["sha256"])
        if object_path.exists():
            if object_path.stat().st_size != row["bytes"] or file_digest(object_path) != row["sha256"]:
                raise ValueError("existing backup object corrupt; refusing overwrite")
            reused += 1
        else:
            _seed_object(Path(row["source"]), object_path, row["sha256"], row["bytes"])
            copied += 1
    # Includes additions/deletions and file-content changes, not just size.
    if _inventory(sources, frozen_sqlite) != records:
        raise ValueError("source changed during backup; attempt retained incomplete")
    manifest_path = snapshots / f"{snapshot_id}.json"
    if not manifest_path.exists():
        _publish_manifest(manifest_path, {"schema": SCHEMA, "complete": True, "snapshot_id": snapshot_id, "files": files})
    manifest_digest = file_digest(manifest_path)
    verify_backup(manifest_path)
    if file_digest(manifest_path) != manifest_digest or file_digest(attempt) != attempt_digest:
        raise ValueError("backup snapshot/attempt changed before completion")
    completion = completions / attempt.name
    _publish_manifest(
        completion,
        {
            "schema": "stock-research-backup-completion.v1",
            "state": "completed",
            "complete": True,
            "attempt": {"path": attempt.relative_to(root).as_posix(), "sha256": attempt_digest},
            "snapshot": {"path": manifest_path.relative_to(root).as_posix(), "id": snapshot_id, "sha256": manifest_digest},
            "copied": copied,
            "reused": reused,
            "files": len(files),
            "bytes": sum(row["bytes"] for row in files),
        },
    )
    LOGGER.info("Backup verified files=%d copied=%d reused=%d bytes=%d", len(files), copied, reused, sum(row["bytes"] for row in files))
    return {
        "manifest_path": str(manifest_path),
        "attempt_path": str(attempt),
        "completion_path": str(completion),
        "snapshot_id": snapshot_id,
        "files": len(files),
        "copied": copied,
        "reused": reused,
        "bytes": sum(row["bytes"] for row in files),
        "same_drive_limitation": "D-drive local backup cannot protect against D-drive failure",
    }


def restore_backup(manifest_path: Path, destination: Path) -> dict[str, Any]:
    """Publish a verified new restore tree; retain failed staging for diagnosis."""
    manifest_path = safe_path(manifest_path)
    manifest_digest = file_digest(manifest_path)
    manifest = verify_backup(manifest_path)
    if file_digest(manifest_path) != manifest_digest:
        raise ValueError("backup manifest changed during restore verification")
    destination = safe_path(destination)
    if destination.exists():
        raise ValueError("restore destination must not exist")
    backup_root = manifest_path.parent.parent
    if destination == backup_root or backup_root in destination.parents or destination in backup_root.parents:
        raise ValueError("restore cannot overlap backup")
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = safe_path(destination.parent / f".{destination.name}.restore.lock")
    # A failed acquisition never removes another writer's lock.
    with lock.open("x", encoding="utf-8"):
        pass
    try:
        safe_path(destination)
        if destination.exists():
            raise FileExistsError(f"restore destination appeared before copy: {destination}")
        staging = safe_path(destination.parent / f".staging-restore-{uuid.uuid4().hex}")
        staging.mkdir()
        for row in manifest["files"]:
            copy_verified(backup_root / "objects" / row["sha256"], staging / relative_name(row["path"]), row["sha256"])
        receipt = {
            "schema": "stock-research-restore.v1",
            "complete": True,
            "snapshot_id": manifest["snapshot_id"],
            "files": len(manifest["files"]),
            "backup_manifest_sha256": manifest_digest,
        }
        receipt_path = staging / "restore-receipt.json"
        write_json(receipt_path, receipt)
        verify_files(staging, manifest["files"])
        if file_digest(receipt_path) != object_digest(receipt):
            raise ValueError("restore receipt hash mismatch")
        expected = {row["path"] for row in manifest["files"]} | {"restore-receipt.json"}
        actual = set()
        for path in staging.rglob("*"):
            safe_path(path)
            if path.is_file():
                actual.add(path.relative_to(staging).as_posix())
        if actual != expected:
            raise ValueError("restore staged inventory mismatch")
        if verify_backup(manifest_path) != manifest or file_digest(manifest_path) != manifest_digest:
            raise ValueError("backup manifest changed during restore")
        safe_path(staging)
        safe_path(destination)
        if destination.exists():
            raise FileExistsError(f"restore destination appeared during copy: {destination}")
        publish_noreplace(staging, destination)
        return receipt
    finally:
        lock.unlink()
