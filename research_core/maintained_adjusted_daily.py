"""One maintained, full-market daily price family on the shared data root.

Owner decision 2026-10-15 (docs/en/decision-records/2026-10-15-maintained-shared-data.md):
reusable derived data is one current copy that whoever needs fresher data updates, not
a new hash-named version per input change. Studies record which generation they read
(``run_receipt``), not the bytes.

Layout under ``<shared root>/derived/adjusted-daily-v1/``::

    current.json                  pointer: generation id + status.json SHA-256
    generations/<id>/status.json  as-of, definition, input fingerprint, counts, timings
    generations/<id>/<basis>.parquet  one file per price basis, sorted by Code, Date

Every new ex-date restates the whole earlier history of that symbol, so an update builds
a complete new generation and then flips ``current.json`` with ``os.replace`` (atomic on
Windows, unlike replacing a directory). The previous generation is kept for rollback and
for readers still holding it; older ones are pruned. A failed build never touches
``current.json``. A definition change gets a new family name (``adjusted-daily-v2``),
never an in-place rewrite of this one.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from research_core import price_basis
from research_core.artifact_store import file_digest, publish_noreplace, read_json, write_json
from research_core.live_producer import read_stable, readonly_sqlite
from research_core.run_receipt import InputSpec, assert_inputs_unchanged, code_identity, fingerprint_inputs
from research_core.shared_data import shared_data_root

LOGGER = logging.getLogger(__name__)
SCHEMA = "maintained-adjusted-daily.v1"
FAMILY = "adjusted-daily-v1"
BASES: tuple[price_basis.PriceBasis, ...] = ("raw", "permanent_adjusted", "reference_factor_adjusted")
CALENDAR_BASIS = "source-date-union: every Date of an official row in the producer price_daily.parquet"
SOURCE_POLICY = "official"
ROW_POLICY = "each symbol from its first to its last observed quote; missing sessions inside that span are kept as invalid rows"
ARROW_SCHEMA = pa.schema([
    ("Code", pa.string()),
    ("Date", pa.timestamp("ns")),
    *((name, pa.float64()) for name in ("Open", "High", "Low", "Close", "RawOpen", "RawHigh", "RawLow", "RawClose", "VolumeLots", "Turnover")),
    ("Quality", pa.bool_()),
    ("quality_reason", pa.string()),
    ("volume_status", pa.string()),
    ("corporate_action_types", pa.string()),
    ("restatement_factor", pa.float64()),
])


def family_dir(root: Path | None = None) -> Path:
    return (shared_data_root() if root is None else root) / "derived" / FAMILY


def _load_inputs(producer_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    """Fingerprint (which refuses a busy producer) and read the two live producer inputs."""
    prices_path, actions_path = producer_root / "price_daily.parquet", producer_root / "corporate_actions.sqlite"
    fingerprint = fingerprint_inputs([
        InputSpec("price_daily", prices_path, date_column="Date", live_producer=True),
        InputSpec("corporate_actions", actions_path, tables={"corporate_actions": "ex_date"}, live_producer=True),
    ])
    columns = ["Code", "Date", *price_basis.PRICE_COLUMNS, "Volume", "Source"]
    bars = read_stable(prices_path, lambda path: pd.read_parquet(path, columns=columns))
    connection = readonly_sqlite(actions_path)
    try:
        actions = pd.read_sql_query("SELECT code, ex_date, event_type, price_factor FROM corporate_actions", connection)
    finally:
        connection.close()
    # Official quotes only, filtered before any calculation: shioaji minute-to-daily rows
    # would otherwise shape neighbouring official rows' jump and quality checks.
    official = bars["Source"].eq(SOURCE_POLICY)
    excluded = bars.loc[~official]
    source_policy = {
        "kept": SOURCE_POLICY,
        "excluded_rows": int(len(excluded)),
        "excluded_codes": int(excluded["Code"].nunique()),
        "codes_without_official_rows": sorted(set(excluded["Code"].astype(str)) - set(bars.loc[official, "Code"].astype(str))),
    }
    bars = bars.loc[official].drop(columns="Source").reset_index(drop=True)
    bars["Code"] = bars["Code"].astype(str)
    bars["Date"] = pd.to_datetime(bars["Date"]).dt.normalize()
    actions["code"] = actions["code"].astype(str)
    LOGGER.info("Loaded %d price rows over %d codes and %d corporate actions", len(bars), bars["Code"].nunique(), len(actions))
    return bars, actions, fingerprint, source_policy


def _prepare_symbol(
    code: str, raw: pd.DataFrame, events: pd.DataFrame, calendar: pd.DatetimeIndex, basis: price_basis.PriceBasis, cutoff: pd.Timestamp
) -> pd.DataFrame:
    prepared = price_basis.prepare_prices(raw, events, calendar, basis=basis, cutoff=cutoff)
    observed = raw["Date"]
    prepared = prepared.loc[observed.min() : observed.max()]
    frame = prepared.rename_axis("Date").reset_index()
    frame.insert(0, "Code", code)
    return frame


def compute(bars: pd.DataFrame, actions: pd.DataFrame, writers: dict[str, Any] | None = None, *, codes: Sequence[str] | None = None) -> dict[str, Any]:
    """Prepare every symbol for every basis; stream into `writers` when given.

    Returns calendar, cutoff and per-basis counts. Without writers it only measures.
    """
    calendar = pd.DatetimeIndex(sorted(bars["Date"].unique()))
    cutoff = cast(pd.Timestamp, calendar.max())
    by_code: dict[str, pd.DataFrame] = {str(code): frame for code, frame in bars.groupby("Code", sort=True)}
    events_by_code: dict[str, pd.DataFrame] = {str(code): frame for code, frame in actions.groupby("code", sort=False)}
    empty_events = cast(pd.DataFrame, actions.iloc[0:0])
    selected = sorted(by_code) if codes is None else list(codes)
    counts: dict[str, dict[str, Any]] = {basis: {"rows": 0, "valid_rows": 0, "quality_reasons": {}} for basis in BASES}
    for position, code in enumerate(selected, 1):
        raw, events = by_code[code], events_by_code.get(code, empty_events)
        for basis in BASES:
            frame = _prepare_symbol(code, raw, events, calendar, basis, cutoff)
            tally = counts[basis]
            tally["rows"] += len(frame)
            tally["valid_rows"] += int(frame["Quality"].sum())
            for reason, count in frame["quality_reason"].dropna().value_counts().items():
                tally["quality_reasons"][str(reason)] = tally["quality_reasons"].get(str(reason), 0) + int(count)
            if writers is not None:
                writers[basis].write_table(pa.Table.from_pandas(frame, schema=ARROW_SCHEMA, preserve_index=False))
        if position % 250 == 0:
            LOGGER.info("Prepared %d/%d symbols", position, len(selected))
    after_cutoff = int(pd.to_datetime(actions["ex_date"]).gt(cutoff).sum())
    unsupported = int((~actions["event_type"].isin(sorted(price_basis.PERMANENT_FACTOR_EVENTS | price_basis.CASH_WINDOW_EVENTS))).sum())
    return {
        "calendar": {
            "basis": CALENDAR_BASIS,
            "sessions": len(calendar),
            "first": cast(pd.Timestamp, calendar.min()).date().isoformat(),
            "last": cutoff.date().isoformat(),
        },
        "asof": cutoff.date().isoformat(),
        "codes": len(selected),
        "actions": {"rows": len(actions), "after_asof_excluded": after_cutoff, "unsupported_event_rows": unsupported},
        "bases": counts,
    }


def _acquire_lock(family: Path) -> Path:
    lock = family / ".writer.lock"
    try:
        with lock.open("x", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()} started_utc={datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")
    except FileExistsError as error:
        raise RuntimeError(f"another update holds {lock}; if no update is running, read it and remove it") from error
    return lock


def _write_current(family: Path, generation: str, status_sha256: str) -> None:
    pointer = {
        "schema": SCHEMA,
        "family": FAMILY,
        "generation": generation,
        "status_sha256": status_sha256,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    temporary = family / f".current-{os.getpid()}.json"
    write_json(temporary, pointer)
    os.replace(temporary, family / "current.json")


def _prune(family: Path, keep: list[str]) -> list[str]:
    """Best effort: a generation still open in a reader (Windows) is left for the next update."""
    removed = []
    for path in sorted((family / "generations").iterdir()):
        if path.is_dir() and path.name not in keep:
            try:
                shutil.rmtree(path)
            except OSError as error:
                LOGGER.warning("Could not prune generation %s, retrying on the next update: %s", path.name, error)
                continue
            removed.append(path.name)
    LOGGER.info("Pruned generations %s; kept %s", removed, keep)
    return removed


def update(*, producer_root: Path, root: Path | None = None) -> dict[str, Any]:
    """Build a complete new generation from live producer data and make it current."""
    started = time.monotonic()
    family = family_dir(root)
    (family / "generations").mkdir(parents=True, exist_ok=True)
    lock = _acquire_lock(family)
    staging: Path | None = None
    try:
        previous = read_json(family / "current.json")["generation"] if (family / "current.json").is_file() else None
        bars, actions, fingerprint, source_policy = _load_inputs(producer_root)
        loaded = time.monotonic()
        asof = cast(pd.Timestamp, bars["Date"].max()).date().isoformat()
        generation = f"{asof}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        staging = family / "generations" / f".staging-{generation}"
        staging.mkdir()
        writers: dict[str, Any] = {basis: pq.ParquetWriter(staging / f"{basis}.parquet", ARROW_SCHEMA, compression="zstd") for basis in BASES}
        try:
            summary = compute(bars, actions, writers)
        finally:
            for writer in writers.values():
                writer.close()
        computed = time.monotonic()
        assert_inputs_unchanged(fingerprint)
        for basis in BASES:
            path = staging / f"{basis}.parquet"
            summary["bases"][basis].update({"file": path.name, "bytes": path.stat().st_size, "sha256": file_digest(path)})
        status = {
            "schema": SCHEMA,
            "family": FAMILY,
            "generation": generation,
            "definition": {"prices": price_basis.DEFINITION_VERSION, "implementation": "research_core/price_basis.py::prepare_prices"},
            "source_policy": source_policy,
            "row_policy": ROW_POLICY,
            **summary,
            "input_fingerprint": fingerprint,
            "code": code_identity(),
            "previous_generation": previous,
            "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "timings_seconds": {
                "load": round(loaded - started, 1),
                "compute_write": round(computed - loaded, 1),
                "total": round(time.monotonic() - started, 1),
            },
        }
        write_json(staging / "status.json", status)
        final = family / "generations" / generation
        publish_noreplace(staging, final)
        staging = None
        _write_current(family, generation, file_digest(final / "status.json"))
        removed = _prune(family, [generation] + ([previous] if previous else []))
        LOGGER.info("Published %s generation %s asof=%s codes=%d", FAMILY, generation, asof, summary["codes"])
        return {
            "family": FAMILY,
            "generation": generation,
            "asof": asof,
            "previous": previous,
            "pruned": removed,
            "path": str(final),
            "timings_seconds": status["timings_seconds"],
        }
    except BaseException:
        if staging is not None and staging.exists():
            LOGGER.warning("Update failed; removing incomplete staging %s (current.json untouched)", staging)
            shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        lock.unlink()


def current_generation(root: Path | None = None, *, generation: str | None = None) -> dict[str, Any]:
    """The current (or an explicitly pinned) generation's status.

    Pass the `generation` from an earlier read to keep every stage of a study on the same
    generation; it fails once that generation has been pruned rather than switching.
    """
    family = family_dir(root)
    if generation is not None:
        directory = family / "generations" / generation
        if generation.startswith(".") or "/" in generation or "\\" in generation or not (directory / "status.json").is_file():
            raise FileNotFoundError(f"{FAMILY} generation {generation!r} is not available under {family}; it may have been pruned")
        return {**read_json(directory / "status.json"), "path": str(directory), "status_sha256": file_digest(directory / "status.json")}
    pointer_path = family / "current.json"
    if not pointer_path.is_file():
        raise FileNotFoundError(f"{FAMILY} has no current generation under {family}; run scripts.maintain_adjusted_daily update")
    pointer = read_json(pointer_path)
    directory = family / "generations" / pointer["generation"]
    if file_digest(directory / "status.json") != pointer["status_sha256"]:
        raise ValueError(f"status.json of {directory} does not match current.json")
    return {**read_json(directory / "status.json"), "path": str(directory), "status_sha256": pointer["status_sha256"]}


_VERIFIED: dict[tuple[Path, str], tuple[int, int, int, int]] = {}


def _file_identity(path: Path) -> tuple[int, int, int, int]:
    """Size, mtime and the file's own id: a same-size copy restored with the old mtime still differs."""
    info = path.stat()
    return info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino


def _verify_once(path: Path, expected: dict[str, Any]) -> tuple[Path, str]:
    """Hash a generation file against status.json once per process per (file identity, expected digest)."""
    key = (path, expected["sha256"])
    identity = _file_identity(path)
    if _VERIFIED.get(key) == identity:
        return key
    if identity[0] != expected["bytes"] or file_digest(path) != expected["sha256"]:
        raise ValueError(f"{path} does not match the bytes/SHA-256 recorded in status.json; rebuild with scripts.maintain_adjusted_daily update")
    _VERIFIED[key] = identity
    LOGGER.debug("Verified %s sha256=%s", path, expected["sha256"])
    return key


def read_adjusted_daily(
    basis: str,
    *,
    codes: Sequence[str] | None = None,
    columns: Sequence[str] | None = None,
    root: Path | None = None,
    generation: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read one basis of the current generation, or of `generation`; return rows and record.

    Put the record (family, generation, asof, file, sha256) in the study's receipt, and pass
    its `generation` to later reads so the whole study uses one generation.
    """
    if basis not in BASES:
        raise ValueError(f"unknown basis {basis!r}; choose one of {BASES}")
    status = current_generation(root, generation=generation)
    path = Path(status["path"]) / f"{basis}.parquet"
    key = _verify_once(path, status["bases"][basis])
    filters = None if codes is None else [("Code", "in", [str(code) for code in codes])]
    selected = None if columns is None else list(columns)
    table = read_stable(path, lambda source: pq.read_table(source, columns=selected, filters=filters))
    if _file_identity(path) != _VERIFIED.get(key):
        raise ValueError(f"{path} changed after its SHA-256 was verified")
    frame = cast(pd.DataFrame, table.to_pandas())
    record = {
        "family": FAMILY,
        "generation": status["generation"],
        "asof": status["asof"],
        "basis": basis,
        "file": str(path),
        "sha256": status["bases"][basis]["sha256"],
        "status_sha256": status["status_sha256"],
    }
    LOGGER.debug("Read %s %s rows=%d generation=%s", FAMILY, basis, len(frame), status["generation"])
    return frame, record
