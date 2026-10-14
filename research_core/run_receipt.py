"""Record a run's input fingerprint, code commit and result hashes; store no input bytes.

Owner policy 2026-10-15 (docs/en/decision-records/2026-10-15-drop-input-sealing.md):
results keep their SHA-256 so accidental edits are detectable; inputs keep an identity
only (path, SHA-256 or row counts, date range, producer as-of time). A result that cannot
be reproduced later is rerun on current data, and the old receipt labels the old result.

Code identity is the Git commit plus a dirty flag. Loaded modules are deliberately not
hashed: that would tie the receipt to unrelated source edits and force rebuilds.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_core.artifact_store import file_digest, read_json, write_json
from research_core.live_producer import ProducerChangedError, assert_producer_idle, read_stable, readonly_sqlite, stat_identity
from research_core.producer_data import REPO_ROOT, producer_data_root

LOGGER = logging.getLogger(__name__)
SCHEMA = "run-receipt.v1"


@dataclass(frozen=True)
class InputSpec:
    """One input a run read. SQLite inputs name the tables (and optional date column) read."""

    name: str
    path: Path
    date_column: str | None = None
    tables: Mapping[str, str | None] | None = None


def _file_fingerprint(spec: InputSpec) -> dict[str, Any]:
    def observe(path: Path) -> dict[str, Any]:
        record: dict[str, Any] = {"sha256": file_digest(path)}
        if spec.date_column is not None and path.suffix == ".parquet":
            import pandas as pd

            dates = pd.to_datetime(pd.read_parquet(path, columns=[spec.date_column])[spec.date_column])
            record["rows"] = len(dates)
            record["date_range"] = None if dates.dropna().empty else [dates.min().date().isoformat(), dates.max().date().isoformat()]
        return record

    record = read_stable(spec.path, observe)
    info = spec.path.stat()
    return {"bytes": info.st_size, "mtime_ns": info.st_mtime_ns, **record}


def _sqlite_fingerprint(spec: InputSpec) -> dict[str, Any]:
    """Row counts and date ranges in one read transaction; a live WAL file makes a byte hash meaningless."""
    tables: dict[str, Any] = {}
    connection = readonly_sqlite(spec.path)
    try:
        connection.execute("BEGIN")
        for table, column in sorted((spec.tables or {}).items()):
            quoted = '"' + table.replace('"', '""') + '"'
            row: dict[str, Any] = {"rows": connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]}  # noqa: S608 - quoted identifier
            if column is not None:
                field = '"' + column.replace('"', '""') + '"'
                low, high = connection.execute(f"SELECT MIN({field}), MAX({field}) FROM {quoted}").fetchone()  # noqa: S608 - quoted identifier
                row["date_range"] = None if low is None else [str(low), str(high)]
            tables[table] = row
        connection.execute("COMMIT")
    finally:
        connection.close()
    info = spec.path.stat()
    wal = spec.path.with_name(spec.path.name + "-wal")
    return {"bytes": info.st_size, "mtime_ns": info.st_mtime_ns, "wal": list(stat_identity(wal)) if wal.exists() else None, "tables": tables}


def producer_as_of(root: Path) -> dict[str, Any]:
    """The producer's own report time, plus the newest mtime among top-level files."""
    report = root / "data_quality_report.json"
    generated = read_json(report).get("generated_at") if report.is_file() else None
    newest = max((path.stat().st_mtime for path in root.iterdir() if path.is_file()), default=None)
    return {
        "data_quality_generated_at": generated,
        "newest_file_mtime_utc": None if newest is None else datetime.fromtimestamp(newest, timezone.utc).isoformat(timespec="seconds"),
    }


def fingerprint_inputs(specs: list[InputSpec], *, now: datetime | None = None) -> dict[str, Any]:
    """Fingerprint every input once; refuse live producer reads while a writer may run."""
    root = producer_data_root()
    live = [spec for spec in specs if spec.path.resolve().is_relative_to(root.resolve())]
    if live:
        assert_producer_idle(now)
    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        raise ValueError("input names must be unique")
    inputs = {}
    for spec in specs:
        record = _sqlite_fingerprint(spec) if spec.tables is not None else _file_fingerprint(spec)
        inputs[spec.name] = {"path": str(spec.path.resolve()), "live_producer": spec in live, **record}
    LOGGER.info("Fingerprinted %d inputs (%d live producer)", len(inputs), len(live))
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "producer_as_of": producer_as_of(root) if live else None,
        "inputs": inputs,
    }


def assert_inputs_unchanged(fingerprint: Mapping[str, Any]) -> None:
    """Fail if any fingerprinted input (or a SQLite input's WAL) changed since it was fingerprinted.

    Called at the end of a run, this catches a producer writer that ran during the study,
    which a single idle probe before the reads cannot see.
    """
    changed = []
    for name, row in fingerprint["inputs"].items():
        path = Path(row["path"])
        if not path.is_file() or list(stat_identity(path)) != [row["bytes"], row["mtime_ns"]]:
            changed.append(name)
        elif "wal" in row:
            wal = path.with_name(path.name + "-wal")
            if (list(stat_identity(wal)) if wal.exists() else None) != row["wal"]:
                changed.append(name)
    if changed:
        raise ProducerChangedError(f"inputs changed during the run: {changed}; rerun outside producer writes")


def _display_path(path: Path, repo_root: Path) -> str:
    resolved = path.resolve()
    return resolved.relative_to(repo_root.resolve()).as_posix() if resolved.is_relative_to(repo_root.resolve()) else str(resolved)


def code_identity(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    def git(*arguments: str) -> str:
        return subprocess.run(["git", "-C", str(repo_root), *arguments], capture_output=True, text=True, check=True).stdout.strip()

    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--untracked-files=no"))}


def write_run_receipt(
    path: Path,
    *,
    run_id: str,
    definition: str,
    parameters: Mapping[str, Any],
    inputs: Mapping[str, Any],
    results: Mapping[str, Path],
    preregistration: Path | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Write a new receipt (never replacing one) with result SHA-256s and the input fingerprint.

    Refuses when an input changed after it was fingerprinted, so a receipt never labels a
    result with inputs other than those it read.
    """
    assert_inputs_unchanged(inputs)
    receipt = {
        "schema": SCHEMA,
        "run_id": run_id,
        "definition": definition,
        "parameters": dict(parameters),
        "preregistration": None if preregistration is None else {"path": _display_path(preregistration, repo_root), "sha256": file_digest(preregistration)},
        "code": code_identity(repo_root),
        "input_fingerprint": dict(inputs),
        "results": {
            name: {"path": _display_path(result, repo_root), "bytes": result.stat().st_size, "sha256": file_digest(result)}
            for name, result in sorted(results.items())
        },
        "written_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, receipt)
    LOGGER.info("Wrote run receipt %s for run=%s results=%d", path, run_id, len(results))
    return receipt


def changed_results(receipt_path: Path, repo_root: Path = REPO_ROOT) -> list[str]:
    """Names of recorded results whose bytes no longer match; a missing file counts as changed."""
    receipt = read_json(receipt_path)
    if receipt.get("schema") != SCHEMA:
        raise ValueError(f"not a {SCHEMA} receipt: {receipt_path}")
    changed = []
    for name, row in receipt["results"].items():
        path = Path(row["path"])
        path = path if path.is_absolute() else repo_root / path
        if not path.is_file() or path.stat().st_size != row["bytes"] or file_digest(path) != row["sha256"]:
            changed.append(name)
    return changed
