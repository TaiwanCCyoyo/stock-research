"""Record a run's input fingerprint, code commit and result hashes; store no input bytes.

Owner policy 2026-10-15 (docs/en/decision-records/2026-10-15-drop-input-sealing.md):
results keep their SHA-256 so accidental edits are detectable; inputs keep an identity
only. Since 2026-10-19 that identity is information, not a hash: path, size, modification
time, rows and date range, producer as-of time. Receipts written before then also carry a
file SHA-256 for each input; they remain valid `run-receipt.v1` receipts, and a missing
input hash in a newer receipt is the current policy, not damage. A result that cannot be
reproduced later is rerun on current data, and the old receipt labels the old result.

Code identity is the Git commit plus a dirty flag. Loaded modules are deliberately not
hashed: that would tie the receipt to unrelated source edits and force rebuilds.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_core.artifact_store import file_digest, object_digest, read_json, write_json
from research_core.live_producer import ProducerChangedError, assert_producer_idle, read_stable, readonly_sqlite, stat_identity
from research_core.producer_data import REPO_ROOT, producer_data_root

LOGGER = logging.getLogger(__name__)
SCHEMA = "run-receipt.v1"


@dataclass(frozen=True)
class InputSpec:
    """One input a run read.

    SQLite inputs name the tables (and optional date column) read; a directory input names a
    glob `pattern` and is identified by its file listing's sizes and mtimes. `live_producer`
    is inferred from the producer root when it can be resolved. Without a resolvable root an
    input must be declared: `False` for a task-owned input, `True` for live producer data.
    An `optional` file that is missing is recorded as absent, so one that appears during the
    run is caught by `assert_inputs_unchanged` instead of being read untracked.
    """

    name: str
    path: Path
    date_column: str | None = None
    tables: Mapping[str, str | None] | None = None
    pattern: str | None = None
    live_producer: bool | None = None
    optional: bool = False


def _file_fingerprint(spec: InputSpec) -> dict[str, Any]:
    """Describe a file input (size, time, rows, date range); its bytes are not hashed.

    Owner decision 2026-10-19: only final results are hashed; inputs are recorded as
    information about what was read.
    """

    def observe(path: Path) -> dict[str, Any]:
        record: dict[str, Any] = {}
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


def _listing(spec: InputSpec) -> list[list[Any]]:
    assert spec.pattern is not None
    return [[path.name, *stat_identity(path)] for path in sorted(spec.path.glob(spec.pattern)) if path.is_file()]


LISTING_FIELDS = ("files", "total_bytes", "newest_mtime_ns")


def _listing_summary(spec: InputSpec) -> dict[str, Any]:
    listing = _listing(spec)
    return {
        "files": len(listing),
        "total_bytes": sum(row[1] for row in listing),
        "newest_mtime_ns": max((row[2] for row in listing), default=None),
        # Name, size and mtime per file: a rename or an add-and-remove that leaves the
        # totals unchanged is still visible, and nothing is hashed.
        "listing": listing,
    }


def _glob_fingerprint(spec: InputSpec) -> dict[str, Any]:
    """Describe many files without hashing them: count, total bytes, newest mtime and the
    per-file listing (name, size, mtime).

    Receipts written before 2026-10-19 also carry a `listing_sha256`; the description
    alone identifies the read now (owner decision: inputs are information only).
    """
    return {"pattern": spec.pattern, **_listing_summary(spec)}


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
    """Fingerprint every input once; refuse live producer reads while a writer may run.

    Classification fails closed: an input that cannot be classified (no resolvable producer
    root and no declaration) is an error, never silently treated as task-owned.
    """
    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        raise ValueError("input names must be unique")
    try:
        root: Path | None = producer_data_root().resolve()
        root_error = None
    except (ValueError, OSError, RuntimeError) as error:
        root, root_error = None, error
    live: dict[str, bool] = {}
    for spec in specs:
        inferred = None if root is None else spec.path.resolve().is_relative_to(root)
        if spec.live_producer is None and inferred is None:
            raise ValueError(f"cannot classify input {spec.name!r}: producer root unavailable ({root_error}); declare live_producer explicitly")
        if spec.live_producer is False and inferred:
            raise ValueError(f"input {spec.name!r} is declared task-owned but lies under the producer root {root}")
        live[spec.name] = bool(spec.live_producer) or bool(inferred)
    if any(live.values()):
        assert_producer_idle(now)
    inputs = {}
    for spec in specs:
        if spec.pattern is not None:
            record = _glob_fingerprint(spec)
        elif spec.optional and not spec.path.exists():
            record = {"absent": True}
        elif spec.tables is not None:
            record = _sqlite_fingerprint(spec)
        else:
            record = _file_fingerprint(spec)
        inputs[spec.name] = {"path": str(spec.path.resolve()), "live_producer": live[spec.name], **record}
    LOGGER.info("Fingerprinted %d inputs (%d live producer)", len(inputs), sum(live.values()))
    under_root = root is not None and any(live[spec.name] and spec.path.resolve().is_relative_to(root) for spec in specs)
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "producer_as_of": producer_as_of(root) if under_root and root is not None else None,
        "inputs": inputs,
    }


def data_directory_inputs(data_path: Path, *, corporate_actions: Path | None = None) -> list[InputSpec]:
    """Every file a `DataLoader`-style reader may open for `data_path`, present or not.

    Missing optional files are recorded as absent and the `*_day.csv` listing is always
    recorded, even empty, so a file that appears mid-run fails the end-of-run check.
    `corporate_actions` is the database the reader actually resolved (`DataLoader` also
    accepts the parent and grandparent directories); pass it rather than assuming a location.
    A data directory under the resolvable producer root is inferred live; one that cannot
    be classified (no resolvable root) is declared live, so the idle gate applies.
    """
    try:
        producer_data_root()
        declared = None
    except (ValueError, OSError, RuntimeError):
        declared = True
    specs = [
        InputSpec("price_daily", data_path / "price_daily.parquet", date_column="Date", live_producer=declared, optional=True),
        InputSpec("dividends", data_path / "dividends.parquet", live_producer=declared, optional=True),
        InputSpec("symbol_meta", data_path / "symbol_meta.sqlite", tables={"symbol_meta": None}, live_producer=declared, optional=True),
        InputSpec("day_csv", data_path, pattern="*_day.csv", live_producer=declared),
    ]
    if corporate_actions is not None:
        specs.append(InputSpec("corporate_actions", corporate_actions, tables={"corporate_actions": "ex_date"}, live_producer=declared))
    return specs


def _input_changed(name: str, row: Mapping[str, Any]) -> bool:
    path = Path(row["path"])
    if "pattern" in row:
        current = _listing_summary(InputSpec(name, path, pattern=row["pattern"]))
        if "listing" in row:
            return [list(item) for item in current["listing"]] != [list(item) for item in row["listing"]]
        if "listing_sha256" in row:  # a fingerprint taken before 2026-10-19: compare, never store
            return object_digest(current["listing"]) != row["listing_sha256"]
        return any(current[field] != row.get(field) for field in LISTING_FIELDS)
    if row.get("absent"):
        return path.exists()
    if not path.is_file() or list(stat_identity(path)) != [row["bytes"], row["mtime_ns"]]:
        return True
    if "wal" in row:
        wal = path.with_name(path.name + "-wal")
        return (list(stat_identity(wal)) if wal.exists() else None) != row["wal"]
    return False


def changed_inputs(fingerprint: Mapping[str, Any]) -> list[str]:
    """Names of fingerprinted inputs (or a SQLite input's WAL) whose size or time changed since.

    A file removed or replaced while it is being checked counts as changed rather than
    raising, so a finished result is still saved with the change recorded.
    """
    changed = []
    for name, row in fingerprint["inputs"].items():
        try:
            if _input_changed(name, row):
                changed.append(name)
        except OSError:
            changed.append(name)
    return changed


def assert_inputs_unchanged(fingerprint: Mapping[str, Any]) -> None:
    """Fail if any fingerprinted input changed since it was fingerprinted.

    For a data builder that must not publish a mix of producer states (the shared family's
    update). A study's receipt records changes instead (`write_run_receipt`).
    """
    changed = changed_inputs(fingerprint)
    if changed:
        raise ProducerChangedError(f"inputs changed during the run: {changed}; rerun outside producer writes")


def _display_path(path: Path, repo_root: Path) -> str:
    resolved = path.resolve()
    return resolved.relative_to(repo_root.resolve()).as_posix() if resolved.is_relative_to(repo_root.resolve()) else str(resolved)


def code_identity(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    def git(*arguments: str) -> str:
        return subprocess.run(["git", "-C", str(repo_root), *arguments], capture_output=True, text=True, check=True).stdout.strip()

    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--untracked-files=no"))}


def _require_committed_preregistration(path: Path, repo_root: Path) -> None:
    """The receipt names the preregistration by path; the recorded commit must hold its exact content.

    Without a hash, only a tracked file unchanged from HEAD inside the repository is identified
    by the commit, so the rules are provably fixed before evaluation.
    """
    if not path.is_file():
        raise FileNotFoundError(f"preregistration {path} does not exist; a receipt names an existing file")
    resolved, root = path.resolve(), repo_root.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"preregistration {path} is outside the repository; the recorded commit cannot identify it")
    relative = resolved.relative_to(root).as_posix()
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", relative], capture_output=True, text=True, check=False)
    if tracked.returncode:
        raise ValueError(f"preregistration {relative} is not tracked by Git; commit it before writing the receipt")
    unchanged = subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--", relative], capture_output=True, text=True, check=False)
    if unchanged.returncode:
        raise ValueError(f"preregistration {relative} differs from the recorded commit; commit it before writing the receipt")


def _describe_shared_read(record: Mapping[str, Any]) -> dict[str, Any]:
    """A shared-data read as information: every field except digests (`sha256`, `*_sha256`).

    Readers return their files' SHA-256s for their own checks; a receipt hashes only the
    study's final results, so those digests are dropped at this boundary, nested ones too.
    A calendar the study supplies (`as_of=..., calendar=`) is the study's own input: its
    committed parameters and code identify it, so the receipt keeps only the calendar's
    description (source, sessions, first and last date) and no digest of it.
    """

    def describe(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {key: describe(item) for key, item in value.items() if not (key == "sha256" or str(key).endswith("_sha256"))}
        if isinstance(value, list):
            return [describe(item) for item in value]
        return value

    return describe(record)


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
    shared_data: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Write a new receipt (never replacing one): final-result SHA-256s plus what was read.

    Owner decision 2026-10-19: only final results are hashed. `inputs` (the fingerprint)
    and `shared_data` (records returned by shared-data readers such as
    `research_core.maintained_adjusted_daily`) describe the sources; they never block saving
    a finished result. An input that changed during the run is listed under
    `inputs_changed_during_run` and logged, not refused; a shared generation pruned since
    it was read does not matter.
    """
    if preregistration is not None:
        _require_committed_preregistration(preregistration, repo_root)
    changed = changed_inputs(inputs)
    if changed:
        LOGGER.warning("Inputs changed during run %s: %s; recorded in the receipt", run_id, changed)
    shared = [_describe_shared_read(record) for record in shared_data]
    receipt = {
        "schema": SCHEMA,
        "run_id": run_id,
        "definition": definition,
        "parameters": dict(parameters),
        # The preregistration is a source: its path plus the code commit identify it, unhashed.
        "preregistration": None if preregistration is None else {"path": _display_path(preregistration, repo_root)},
        "code": code_identity(repo_root),
        "input_fingerprint": dict(inputs),
        **({"shared_data": shared} if shared else {}),
        **({"inputs_changed_during_run": changed} if changed else {}),
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
