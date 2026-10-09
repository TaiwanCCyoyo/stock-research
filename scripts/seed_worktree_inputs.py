"""Seed producer read inputs and explicit legacy daily snapshots; never link data."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from research_core.artifact_store import copy_verified, describe_file, file_digest, publish_noreplace, safe_path, write_json

NAMES = {
    "price_daily.parquet",
    "data_quality_report.json",
    "corporate_actions.sqlite",
    "symbol_meta.sqlite",
    "stock_symbol_mapping.json5",
    "value_chain_classification.json",
    "dividends.parquet",
    "institutional.sqlite",
    "monthly_revenue.sqlite",
}
LEGACY_DAILY = Path("adjusted_prices/daily")
LEGACY_NAMES = {"price_daily.parquet", "dividends.parquet"}
SEED_PARTIAL = re.compile(r"\.(?P<formal>.+)\.seed-[0-9a-fA-F]{32}\.partial")


def _legacy_inputs(source: Path, destination: Path) -> list[Path]:
    """Only the legacy DataLoader's immediate daily read set is eligible."""
    incoming = safe_path(source / LEGACY_DAILY)
    outgoing = safe_path(destination / LEGACY_DAILY)
    if (incoming.exists() and not incoming.is_dir()) or (outgoing.exists() and not outgoing.is_dir()):
        raise ValueError("legacy daily snapshot paths must be directories")
    for directory in (incoming, outgoing):
        if directory.exists():
            for path in directory.iterdir():
                safe_path(path)
                if path.name.endswith((".partial", ".lock")):
                    diagnostic = SEED_PARTIAL.fullmatch(path.name)
                    formal = diagnostic.group("formal") if diagnostic is not None else ""
                    if directory == outgoing and diagnostic is not None and path.is_file() and (formal in LEGACY_NAMES or formal.endswith("_day.csv")):
                        continue  # Retain this seeder's diagnostic bytes; a fresh staging file may retry.
                    raise ValueError(f"unfinished legacy daily snapshot: {path}")
    return (
        sorted(path for path in incoming.iterdir() if path.is_file() and (path.name in LEGACY_NAMES or path.name.endswith("_day.csv")))
        if incoming.exists()
        else []
    )


def _publish_snapshot(source: Path, target: Path) -> None:
    """Publish verified bytes atomically under the worktree's single-writer contract."""
    source, target = safe_path(source), safe_path(target)
    lock = safe_path(target.with_name(f".{target.name}.seed.lock"))
    staging = safe_path(target.with_name(f".{target.name}.seed-{uuid.uuid4().hex}.partial"))
    with lock.open("x"):
        pass  # A competing seeder must not publish the same target concurrently.
    try:
        if safe_path(target).exists():
            raise FileExistsError(target)
        original = source.stat()
        copy_verified(source, staging, file_digest(source))
        observed = source.stat()
        if (observed.st_size, observed.st_mtime_ns) != (original.st_size, original.st_mtime_ns):
            raise ValueError(f"source metadata changed during worktree copy: {source}")
        os.utime(staging, ns=(original.st_atime_ns, original.st_mtime_ns))
        if safe_path(target).exists():
            raise FileExistsError(target)
        # Refuse an existing target atomically, including a writer arriving after
        # the last check; retain staging as evidence when publication fails.
        publish_noreplace(staging, target)
    finally:
        lock.unlink()  # This invocation exclusively created this lock.
        # Retain a failed staging file as evidence; never publish or delete it.


def _observed_descriptor(root: Path, path: Path) -> dict[str, Any]:
    """Capture hash and metadata from one stable observation of a file."""
    path = safe_path(path)
    before = path.stat()
    record = describe_file(root, path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"snapshot changed during observation: {path}")
    record["mtime_ns"] = after.st_mtime_ns
    return record


def _closed_sqlite(path: Path) -> None:
    """Check a self-contained snapshot without reading or creating sidecars."""
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = safe_path(path.with_name(path.name + suffix))
        if sidecar.exists():
            raise ValueError(f"SQLite snapshot has sidecar: {sidecar}")
    before = _observed_descriptor(path.parent, path)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=5)) as database:
        if database.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError(f"SQLite preserved snapshot failed quick_check: {path}")
    if _observed_descriptor(path.parent, path) != before:
        raise ValueError(f"SQLite snapshot changed during quick_check: {path}")
    for suffix in ("-wal", "-shm", "-journal"):
        if safe_path(path.with_name(path.name + suffix)).exists():
            raise ValueError(f"SQLite snapshot acquired sidecar: {path}")


def _preserved_record(source: Path, destination: Path, target: Path) -> dict[str, Any]:
    """Inventory a consumer-visible preserved file, even without a current source."""
    path = safe_path(source / target.relative_to(destination))
    if target.suffix == ".sqlite":
        _closed_sqlite(target)
    record = _observed_descriptor(destination, target)
    record.update({"source_ref": str(path), "mode": "existing_snapshot_preserved", "original_source_identity": "unknown"})
    if not path.exists():
        record["current_source_reference"] = {"path": str(path), "status": "missing"}
        record["current_source_byte_match"] = None
    elif path.suffix == ".sqlite":
        record["current_source_reference"] = {
            "path": str(path),
            "status": "present",
            "logical_match": None,
            "limitation": "Current SQLite main file does not identify live WAL contents or the original snapshot source.",
        }
    else:
        reference = _observed_descriptor(source, path)
        reference["status"] = "present"
        record["current_source_reference"] = reference
        record["current_source_byte_match"] = (record["bytes"], record["sha256"]) == (reference["bytes"], reference["sha256"])
    record["current_source_reference_role"] = "current_observation_not_original_source_identity"
    return record


def seed_inputs(primary: Path, worktree: Path) -> dict[str, Any]:
    primary, worktree = safe_path(primary), safe_path(worktree)
    if primary == worktree or worktree in primary.parents:
        raise ValueError("independent worktree required")
    source = safe_path(primary / "stock-data-downloader/data")
    destination = safe_path(worktree / "stock-data-downloader/data")
    if not source.is_dir() or not destination.is_dir():
        raise ValueError("initialized producer data directories required")
    scratch = safe_path(worktree / ".tmp" / f"worktree-seed-{uuid.uuid4().hex}")
    scratch.mkdir(parents=True)
    records: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    skipped: list[str] = []
    read_paths = sorted(source.iterdir()) + _legacy_inputs(source, destination)
    for path in read_paths:
        safe_path(path)
        if not path.is_file() or not (path.name in NAMES or path.name.endswith("_day.csv")):
            continue
        relative = path.relative_to(source)
        target = safe_path(destination / relative)
        if target.exists():
            if not target.is_file():
                raise ValueError(f"existing snapshot is not a file: {target}")
            skipped.append(relative.as_posix())
            preserved.append(_preserved_record(source, destination, target))
            continue  # Preserve an existing explicit snapshot, even if older.
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "stable_file_copy"
        if path.suffix == ".sqlite":
            snapshot = scratch / path.name
            started = time.monotonic()

            def progress(status: int, remaining: int, total: int) -> None:
                if time.monotonic() - started > 30:
                    raise TimeoutError("SQLite snapshot exceeded 30-second budget")

            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as incoming:
                with closing(sqlite3.connect(snapshot)) as outgoing:
                    incoming.backup(outgoing, pages=256, progress=progress, sleep=0.05)
                    if outgoing.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise ValueError("SQLite worktree snapshot failed quick_check")
            _publish_snapshot(snapshot, target)
            mode = "consistent_sqlite_backup_not_live_db_file_copy"
        else:
            _publish_snapshot(path, target)
        record = _observed_descriptor(destination, target)
        record.update({"source": str(path), "mode": mode})
        records.append(record)
    # Consumers can still read destination files whose producer counterpart was
    # removed. Inventory the explicit read set, never unrelated derived trees.
    _legacy_inputs(source, destination)  # Recheck destination safety, including optional-source absence.
    destination_paths = sorted(destination.iterdir())
    legacy_destination = safe_path(destination / LEGACY_DAILY)
    if legacy_destination.exists():
        destination_paths += sorted(path for path in legacy_destination.iterdir() if path.name in LEGACY_NAMES or path.name.endswith("_day.csv"))
    recorded = {row["path"] for row in [*records, *preserved]}
    for target in destination_paths:
        safe_path(target)
        if not target.is_file() or not (target.name in NAMES or target.name.endswith("_day.csv")):
            continue
        relative_name = target.relative_to(destination).as_posix()
        if relative_name not in recorded:
            skipped.append(relative_name)
            preserved.append(_preserved_record(source, destination, target))
            recorded.add(relative_name)
    for record in [*records, *preserved]:
        target = safe_path(destination / record["path"])
        if target.suffix == ".sqlite":
            _closed_sqlite(target)
        observed = _observed_descriptor(destination, target)
        if any(observed[key] != record[key] for key in ("path", "bytes", "sha256", "mtime_ns")):
            raise ValueError(f"snapshot changed before receipt: {target}")
    receipt = {
        "schema": "worktree-input-snapshot.v1",
        "files": records,
        "existing_preserved": skipped,
        "preserved_inventory": preserved,
        "input_set_coherence": "not_certified_by_file_seeding",
        "source_alignment_required": any(row["original_source_identity"] == "unknown" or row.get("current_source_byte_match") is False for row in preserved),
        "immutable_cache": "absolute read-only primary research_cache versions; not copied or linked",
        "bytes_copied": sum(row["bytes"] for row in records),
    }
    receipt_path = scratch / "receipt.json"
    write_json(receipt_path, receipt)
    return {**receipt, "receipt_path": str(receipt_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    args = parser.parse_args()
    receipt = seed_inputs(args.primary, args.worktree)
    summary = {
        "files": len(receipt["files"]),
        "bytes_copied": receipt["bytes_copied"],
        "existing_preserved": len(receipt["existing_preserved"]),
        "receipt_path": receipt["receipt_path"],
        "source_alignment_required": receipt["source_alignment_required"],
    }
    print(json.dumps(summary, ensure_ascii=False))  # noqa: T201 - CLI summary on stdout
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
