"""One maintained, full-market daily price family on the shared data root.

Owner decision 2026-10-15 (docs/en/decision-records/2026-10-15-maintained-shared-data.md):
reusable derived data is one current copy that whoever needs fresher data updates, not
a new hash-named version per input change. Studies record which generation they read
(``run_receipt``), not the bytes.

Layout under ``<shared root>/derived/adjusted-daily-v1/``::

    current.json                  pointer: generation id + status.json SHA-256
    generations/<id>/status.json  as-of, definition, input fingerprint, counts, timings
    generations/<id>/<basis>.parquet  one file per price basis, sorted by Code, Date
    generations/<id>/actions.parquet  the corporate actions this generation was built from
    generations/<id>/calendar.parquet the generation's session calendar
    generations/<id>/technical_daily.parquet   technical-daily.v1 indicators, one row per
                                               reference_factor_adjusted row
    generations/<id>/technical_pivots.parquet  confirmed 1.5/4 ATR highs and lows
    holds/<holder>.json           a generation a running study marked in use; never pruned

Every new ex-date restates the whole earlier history of that symbol, so an update builds
a complete new generation and then flips ``current.json`` with ``os.replace`` (atomic on
Windows, unlike replacing a directory). The previous generation is kept for rollback and
for readers still holding it; older ones are pruned unless a study holds them. A failed build never touches
``current.json``. A definition change gets a new family name (``adjusted-daily-v2``),
never an in-place rewrite of this one.

``read_adjusted_daily(..., as_of=cutoff, calendar=...)`` recomputes a symbol as it was at
an earlier cutoff. Truncating the latest generation is not that: later ex-dates restate,
or (when their factor is missing or ambiguous) mask, the whole earlier history. The
reader therefore rebuilds the official quotes from the raw basis, takes the generation's
own actions snapshot, and runs ``price_basis.prepare_prices`` at the cutoff. Rows outside
a symbol's first..last quote need no stored row: they are calendar positions with no quote.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sys
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any, TypeVar, cast

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from research_core import price_basis, technical_daily_v1
from research_core.artifact_store import file_digest, object_digest, publish_noreplace, read_json, write_json
from research_core.live_producer import read_stable, readonly_sqlite
from research_core.run_receipt import InputSpec, assert_inputs_unchanged, code_identity, fingerprint_inputs
from research_core.shared_data import shared_data_root

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")
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
ACTIONS_FILE, CALENDAR_FILE = "actions.parquet", "calendar.parquet"
ACTIONS_SCHEMA = pa.schema([("code", pa.string()), ("ex_date", pa.string()), ("event_type", pa.string()), ("price_factor", pa.float64())])
CALENDAR_SCHEMA = pa.schema([("Date", pa.timestamp("ns"))])
TECHNICAL_TABLES = {
    "daily": ("technical_daily.parquet", technical_daily_v1.DAILY_SCHEMA),
    "pivots": ("technical_pivots.parquet", technical_daily_v1.PIVOTS_SCHEMA),
}
RAW_QUOTE_COLUMNS = {"RawOpen": "Open", "RawHigh": "High", "RawLow": "Low", "RawClose": "Close", "VolumeLots": "Volume"}


def family_dir(root: Path | None = None) -> Path:
    return (shared_data_root() if root is None else root) / "derived" / FAMILY


def load_inputs(producer_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
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


def session_calendar(bars: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(sorted(bars["Date"].unique()))


def compute(bars: pd.DataFrame, actions: pd.DataFrame, writers: dict[str, Any] | None = None, *, codes: Sequence[str] | None = None) -> dict[str, Any]:
    """Prepare every symbol for every basis and its technical tables; stream into `writers`.

    `writers` maps each basis and each `TECHNICAL_TABLES` name to an open ParquetWriter.
    Returns calendar, cutoff and per-basis and per-table counts. Without writers it only
    measures.
    """
    calendar = session_calendar(bars)
    cutoff = cast(pd.Timestamp, calendar.max())
    by_code: dict[str, pd.DataFrame] = {str(code): frame for code, frame in bars.groupby("Code", sort=True)}
    events_by_code: dict[str, pd.DataFrame] = {str(code): frame for code, frame in actions.groupby("code", sort=False)}
    empty_events = cast(pd.DataFrame, actions.iloc[0:0])
    selected = sorted(by_code) if codes is None else list(codes)
    counts: dict[str, dict[str, Any]] = {basis: {"rows": 0, "valid_rows": 0, "quality_reasons": {}} for basis in BASES}
    technical: dict[str, dict[str, Any]] = {name: {"rows": 0} for name in TECHNICAL_TABLES}
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
            if basis == technical_daily_v1.BASIS:
                tables = dict(zip(TECHNICAL_TABLES, technical_daily_v1.compute_technical(code, frame.set_index("Date"))))
                for name, table in tables.items():
                    technical[name]["rows"] += len(table)
                    if writers is not None:
                        writers[name].write_table(pa.Table.from_pandas(table, schema=TECHNICAL_TABLES[name][1], preserve_index=False))
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
        "technical": {"definition": technical_daily_v1.definition_metadata(), "tables": technical},
    }


def _write_as_of_inputs(directory: Path, bars: pd.DataFrame, actions: pd.DataFrame) -> dict[str, Any]:
    """Persist what an as_of read needs besides the raw basis: the actions and the calendar.

    Actions keep every row the build saw (including ex-dates after asof); price factors are
    stored as `prepare_prices` reads them (numeric, unparseable as null).
    """
    snapshot = pd.DataFrame({
        "code": actions["code"].astype(str),
        "ex_date": actions["ex_date"].map(lambda value: None if value is None else str(value)),
        "event_type": actions["event_type"].map(lambda value: None if value is None else str(value)),
        "price_factor": cast(pd.Series, pd.to_numeric(actions["price_factor"], errors="coerce")).astype("float64"),
    })
    calendar = pd.DataFrame({"Date": session_calendar(bars)})
    recorded: dict[str, Any] = {}
    for name, frame, schema, file in (("actions", snapshot, ACTIONS_SCHEMA, ACTIONS_FILE), ("calendar", calendar, CALENDAR_SCHEMA, CALENDAR_FILE)):
        path = directory / file
        pq.write_table(pa.Table.from_pandas(frame, schema=schema, preserve_index=False), path, compression="zstd")
        recorded[name] = {"file": file, "rows": len(frame), "bytes": path.stat().st_size, "sha256": file_digest(path)}
    return recorded


def _acquire_lock(family: Path) -> IO[bytes]:
    """Take the single-writer OS lock on `.writer.lock` without waiting.

    The OS releases it when the update ends, however it ends (reboot, kill, task time
    limit), so a scheduled retry is never blocked by a lock left from a dead update.
    """
    lock = family / ".writer.lock"
    handle = lock.open("a+b")
    if not _try_os_lock(handle):
        handle.close()
        raise RuntimeError(f"another update holds {lock}; wait for it to finish")
    return handle


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


HOLDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


# Windows treats these as devices whatever the extension, so `<holder>.json` cannot be a file.
WINDOWS_DEVICE_NAMES = frozenset({"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))})


def _hold_path(family: Path, holder: str) -> Path:
    if not HOLDER_PATTERN.match(holder):
        raise ValueError(f"holder must match {HOLDER_PATTERN.pattern}, got {holder!r}")
    if holder in WINDOWS_DEVICE_NAMES:
        raise ValueError(f"holder {holder!r} is a Windows device name; choose another")
    return family / "holds" / f"{holder}.json"


def held_generations(root: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """Generations a running study marked in use, mapped to their holds; the updater keeps them."""
    holds: dict[str, list[dict[str, Any]]] = {}
    directory = family_dir(root) / "holds"
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            if not HOLDER_PATTERN.match(path.stem):
                continue  # only `<holder>.json`; never a temporary or foreign file
            try:
                record = read_json(path)
            except FileNotFoundError:
                continue  # released between listing and reading
            holds.setdefault(str(record["generation"]), []).append(record)
    return holds


HOLDS_LOCK_WAIT_SECONDS = 120.0


def _try_os_lock(handle: IO[bytes]) -> bool:
    """Take an exclusive OS lock on the first byte; the OS drops it when the process ends."""
    handle.seek(0)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _release_os_lock(handle: IO[bytes]) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _holds_lock(family: Path) -> Iterator[None]:
    """Serialize hold changes with pruning, so a hold is either seen by the prune or refused.

    An OS lock on `.holds.lock`, not the file's existence: the file stays, and a killed
    holder's lock is released by the OS, so no age-based reclaim can break a live holder.
    Held only for a hold write or one prune pass, never for a whole update.
    """
    lock = family / ".holds.lock"
    family.mkdir(parents=True, exist_ok=True)
    handle = lock.open("a+b")
    try:
        deadline = time.monotonic() + HOLDS_LOCK_WAIT_SECONDS
        while not _try_os_lock(handle):
            if time.monotonic() >= deadline:
                raise RuntimeError(f"{lock} is locked by a running update, hold or release; retry when it finishes")
            time.sleep(0.5)
        try:
            yield
        finally:
            _release_os_lock(handle)
    finally:
        handle.close()


def hold_generation(generation: str, *, holder: str, reason: str, root: Path | None = None) -> dict[str, Any]:
    """Mark `generation` in use by `holder` so updates keep it until `release_generation(holder)`.

    One hold per holder; holding again moves it. Kept generations cost disk (about 1-2 GB
    each), so release as soon as the study no longer reads it.
    """
    family = family_dir(root)
    path = _hold_path(family, holder)
    if not reason.strip():
        raise ValueError("a hold needs a reason another session can act on")
    record = {"holder": holder, "generation": generation, "reason": reason.strip(), "held_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with _holds_lock(family):
        # Under the lock no prune runs, so a generation that exists now is kept.
        current_generation(root, generation=generation)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Under the lock no other hold write runs, so this holder's leftover temporaries
        # (a write killed before os.replace) are safe to remove; a fresh name never collides.
        for leftover in path.parent.glob(f".{holder}-*.tmp"):
            leftover.unlink(missing_ok=True)
        temporary = path.with_name(f".{holder}-{uuid.uuid4().hex}.tmp")
        write_json(temporary, record)
        os.replace(temporary, path)
    LOGGER.info("Held %s generation %s for %s: %s", FAMILY, generation, holder, record["reason"])
    return record


def release_generation(holder: str, *, root: Path | None = None) -> dict[str, Any] | None:
    """Remove `holder`'s hold; the next update prunes the generation unless someone else holds it."""
    family = family_dir(root)
    path = _hold_path(family, holder)
    with _holds_lock(family):
        if not path.is_file():
            return None
        record = read_json(path)
        path.unlink()
    LOGGER.info("Released %s generation %s held by %s", FAMILY, record["generation"], holder)
    return record


def _prune(family: Path, keep: list[str]) -> list[str]:
    """Best effort: a generation still open in a reader (Windows) is left for the next update.

    Generations a study holds (`hold_generation`) are kept as well; the holds are read
    under the same lock a new hold takes, so none can appear mid-prune.
    """
    removed: list[str] = []
    try:
        with _holds_lock(family):
            keep = [*keep, *held_generations(family.parent.parent)]
            for path in sorted((family / "generations").iterdir()):
                if path.is_dir() and path.name not in keep:
                    try:
                        shutil.rmtree(path)
                    except OSError as error:
                        LOGGER.warning("Could not prune generation %s, retrying on the next update: %s", path.name, error)
                        continue
                    removed.append(path.name)
    except RuntimeError as error:
        LOGGER.warning("Skipped pruning this update, retrying on the next one: %s", error)
        return removed
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
        bars, actions, fingerprint, source_policy = load_inputs(producer_root)
        loaded = time.monotonic()
        asof = cast(pd.Timestamp, bars["Date"].max()).date().isoformat()
        generation = f"{asof}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        staging = family / "generations" / f".staging-{generation}"
        staging.mkdir()
        writers: dict[str, Any] = {basis: pq.ParquetWriter(staging / f"{basis}.parquet", ARROW_SCHEMA, compression="zstd") for basis in BASES}
        writers.update({name: pq.ParquetWriter(staging / file, schema, compression="zstd") for name, (file, schema) in TECHNICAL_TABLES.items()})
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
        for name, (file, _) in TECHNICAL_TABLES.items():
            path = staging / file
            summary["technical"]["tables"][name].update({"file": file, "bytes": path.stat().st_size, "sha256": file_digest(path)})
        as_of_inputs = _write_as_of_inputs(staging, bars, actions)
        status = {
            "schema": SCHEMA,
            "family": FAMILY,
            "generation": generation,
            "definition": {"prices": price_basis.DEFINITION_VERSION, "implementation": "research_core/price_basis.py::prepare_prices"},
            "source_policy": source_policy,
            "row_policy": ROW_POLICY,
            **summary,
            "as_of_inputs": as_of_inputs,
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
            "held": sorted(held_generations(root)),
            "path": str(final),
            "timings_seconds": status["timings_seconds"],
        }
    except BaseException:
        if staging is not None and staging.exists():
            LOGGER.warning("Update failed; removing incomplete staging %s (current.json untouched)", staging)
            shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        _release_os_lock(lock)
        lock.close()


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
    as_of: str | pd.Timestamp | None = None,
    calendar: pd.DatetimeIndex | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read one basis of the current generation, or of `generation`; return rows and record.

    Put the record (family, generation, asof, file, sha256) in the study's receipt, and pass
    its `generation` to later reads so the whole study uses one generation.

    `as_of=cutoff` returns each symbol as `price_basis.prepare_prices` computes it at that
    cutoff on `calendar` (default: the generation's sessions up to the cutoff), with every
    calendar position, including those before a symbol's first or after its last quote.
    See `_read_as_of`.
    """
    if basis not in BASES:
        raise ValueError(f"unknown basis {basis!r}; choose one of {BASES}")
    status = current_generation(root, generation=generation)
    if as_of is not None:
        return _read_as_of(status, cast(price_basis.PriceBasis, basis), as_of, calendar, codes, columns)
    if calendar is not None:
        raise ValueError("calendar= aligns a cutoff read; pass as_of= as well")
    path = Path(status["path"]) / f"{basis}.parquet"
    filters = None if codes is None else [("Code", "in", [str(code) for code in codes])]
    selected = None if columns is None else list(columns)
    table = _read_verified(path, status["bases"][basis], lambda source: pq.read_table(source, columns=selected, filters=filters))
    frame = cast(pd.DataFrame, table.to_pandas())
    LOGGER.debug("Read %s %s rows=%d generation=%s", FAMILY, basis, len(frame), status["generation"])
    return frame, _record(status, basis)


def read_technical(
    table: str = "daily",
    *,
    codes: Sequence[str] | None = None,
    columns: Sequence[str] | None = None,
    prices: Sequence[str] | None = None,
    root: Path | None = None,
    generation: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read a `technical-daily.v1` table of the current generation, or of `generation`.

    `table="daily"` has one row per `reference_factor_adjusted` row; `prices=["Close", ...]`
    joins those columns of that basis from the same generation on `Code, Date`, so the
    indicators and the prices they were computed from always match. `table="pivots"` is
    one row per confirmed high/low; it is known from `confirmed_at`, not `extreme_date`.
    These values are computed at the generation's asof. For an earlier cutoff, read the
    prices with `read_adjusted_daily(..., as_of=)` and call
    `technical_daily_v1.compute_technical` on them instead of truncating this table.
    """
    if table not in TECHNICAL_TABLES:
        raise ValueError(f"unknown technical table {table!r}; choose one of {tuple(TECHNICAL_TABLES)}")
    if prices is not None and table != "daily":
        raise ValueError("prices= joins daily rows; the pivots table has one row per pivot")
    status = current_generation(root, generation=generation)
    technical = status.get("technical")
    if technical is None:
        raise ValueError(f"generation {status['generation']} has no technical tables; run scripts.maintain_adjusted_daily update")
    expected = technical["tables"][table]
    path = Path(status["path"]) / expected["file"]
    filters = None if codes is None else [("Code", "in", [str(code) for code in codes])]
    selected = None if columns is None else list(dict.fromkeys(["Code", *(["Date"] if table == "daily" else []), *columns]))
    frame = cast(pd.DataFrame, _read_verified(path, expected, lambda source: pq.read_table(source, columns=selected, filters=filters)).to_pandas())
    record = {
        "family": FAMILY,
        "generation": status["generation"],
        "asof": status["asof"],
        "definition": technical["definition"]["version"],
        "table": table,
        "file": str(path),
        "sha256": expected["sha256"],
        "status_sha256": status["status_sha256"],
    }
    if prices:
        basis = technical["definition"]["basis"]
        quotes, price_record = read_adjusted_daily(basis, codes=codes, columns=["Code", "Date", *prices], root=root, generation=status["generation"])
        frame = frame.merge(quotes, on=["Code", "Date"], how="left", validate="one_to_one")
        record["prices"] = price_record
    LOGGER.debug("Read %s technical %s rows=%d generation=%s", FAMILY, table, len(frame), status["generation"])
    return frame, record


def _record(status: dict[str, Any], basis: str) -> dict[str, Any]:
    return {
        "family": FAMILY,
        "generation": status["generation"],
        "asof": status["asof"],
        "basis": basis,
        "file": str(Path(status["path"]) / f"{basis}.parquet"),
        "sha256": status["bases"][basis]["sha256"],
        "status_sha256": status["status_sha256"],
    }


def _read_verified(path: Path, expected: dict[str, Any], read: Callable[[Path], T]) -> T:
    key = _verify_once(path, expected)
    value = read_stable(path, read)
    if _file_identity(path) != _VERIFIED.get(key):
        raise ValueError(f"{path} changed after its SHA-256 was verified")
    return value


def _stored_quotes(stored: pd.DataFrame) -> pd.DataFrame:
    """Rebuild the official quote rows the build saw from raw-basis rows.

    A `missing_official_quote` row had no quote. A `duplicate_date` row had two or more
    quotes; `prepare_prices` kept the first and marked the date, so one repeated copy
    reproduces both.
    """
    tokens = stored["quality_reason"].fillna("").str.split("|")
    observed = ~tokens.map(lambda reasons: "missing_official_quote" in reasons).astype(bool)
    duplicated = tokens.map(lambda reasons: "duplicate_date" in reasons).astype(bool) & observed
    quotes = stored.loc[observed, ["Code", "Date", *RAW_QUOTE_COLUMNS]].rename(columns=RAW_QUOTE_COLUMNS)
    return pd.concat([quotes, quotes.loc[duplicated[observed]]]).sort_values(["Code", "Date"], kind="stable")


def _read_stored_quotes(status: dict[str, Any], cutoff: pd.Timestamp, codes: Sequence[str] | None) -> pd.DataFrame:
    """The verified official quotes on or before `cutoff` that this generation was built from."""
    filters: list[Any] = [("Date", "<=", cutoff)]
    if codes is not None:
        filters.append(("Code", "in", [str(code) for code in codes]))
    stored = _read_verified(
        Path(status["path"]) / "raw.parquet",
        status["bases"]["raw"],
        lambda source: pq.read_table(source, columns=["Code", "Date", *RAW_QUOTE_COLUMNS, "quality_reason"], filters=filters).to_pandas(),
    )
    return _stored_quotes(stored)


def _generation_calendar(status: dict[str, Any], inputs: dict[str, Any], cutoff: pd.Timestamp) -> pd.DatetimeIndex:
    sessions = _read_verified(Path(status["path"]) / inputs["calendar"]["file"], inputs["calendar"], lambda source: pq.read_table(source).to_pandas())
    calendar = pd.DatetimeIndex(sessions["Date"])
    return calendar[calendar <= cutoff]


def _cutoff_inputs(status: dict[str, Any], as_of: str | pd.Timestamp) -> tuple[pd.Timestamp, dict[str, Any]]:
    cutoff = cast(pd.Timestamp, pd.Timestamp(as_of))
    if pd.isna(cutoff) or cutoff.tzinfo is not None or cutoff != cutoff.normalize():
        raise ValueError(f"as_of must be a naive date, got {as_of!r}")
    if cutoff > pd.Timestamp(status["asof"]):
        raise ValueError(f"as_of {cutoff.date()} is after generation {status['generation']} asof {status['asof']}; its later quotes and actions are unknown")
    inputs = status.get("as_of_inputs")
    if inputs is None:
        raise ValueError(f"generation {status['generation']} has no actions snapshot and cannot be read as_of; run scripts.maintain_adjusted_daily update")
    return cutoff, inputs


def _calendar_record(calendar: pd.DatetimeIndex, source: str) -> dict[str, Any]:
    days = [day.date().isoformat() for day in calendar]
    return {"source": source, "sessions": len(days), "first": days[0] if days else None, "last": days[-1] if days else None, "sha256": object_digest(days)}


def read_official_quotes(
    *,
    codes: Sequence[str],
    as_of: str | pd.Timestamp,
    root: Path | None = None,
    generation: str | None = None,
) -> tuple[pd.DataFrame, pd.DatetimeIndex, dict[str, Any]]:
    """Official quotes and the session calendar on or before `as_of`, as this generation saw them.

    For a study that runs its own price model on source quotes (custom corporate-action
    terms, holding-window economics) instead of reading a prepared basis. The quotes are
    `Code, Date, Open, High, Low, Close, Volume` from the producer's `official` rows as
    `prepare_prices` stored them: numeric-coerced, a negative or non-finite `Volume` (the
    producer column, stored as `VolumeLots`) is NaN, and a duplicated date repeats its first
    row. `prepare_prices` gives the same result on these rows as on the source rows; a
    caller that reads quote values directly must accept those three normalizations. The
    calendar is the generation's official source-date union. Both are verified against `status.json`, so the
    study needs no scan or fingerprint of `price_daily.parquet`; put the record in the
    receipt (`write_run_receipt(shared_data=[record])`). Requested codes without a quote on
    or before the cutoff are listed in `record["absent_codes"]`, not refused: the caller
    decides what a missing history means. Corporate actions are not included; this family's
    actions snapshot keeps only the price factor.
    """
    status = current_generation(root, generation=generation)
    cutoff, inputs = _cutoff_inputs(status, as_of)
    calendar = _generation_calendar(status, inputs, cutoff)
    requested = list(dict.fromkeys(str(code) for code in codes))
    quotes = _read_stored_quotes(status, cutoff, requested).reset_index(drop=True)
    record = {
        **_record(status, "raw"),
        "as_of": cutoff.date().isoformat(),
        "method": "official quotes rebuilt from the raw basis (missing_official_quote rows dropped, duplicate_date rows repeated)",
        "calendar": {
            **_calendar_record(calendar, "generation"),
            "file": str(Path(status["path"]) / inputs["calendar"]["file"]),
            "file_sha256": inputs["calendar"]["sha256"],
        },
        "codes": requested,
        "absent_codes": sorted(set(requested) - set(quotes["Code"].astype(str))),
        "rows": len(quotes),
    }
    LOGGER.info("Read %s official quotes as_of=%s generation=%s codes=%d rows=%d", FAMILY, record["as_of"], status["generation"], len(requested), len(quotes))
    return quotes, calendar, record


def _read_as_of(
    status: dict[str, Any],
    basis: price_basis.PriceBasis,
    as_of: str | pd.Timestamp,
    calendar: pd.DatetimeIndex | None,
    codes: Sequence[str] | None,
    columns: Sequence[str] | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Recompute `basis` at `as_of` from this generation's raw quotes and actions snapshot.

    Equal by construction to `prepare_prices(official quotes <= as_of, actions, calendar,
    basis, as_of)`: actions after the cutoff are excluded, never divided back out of a
    restated factor. Refuses rather than guesses: a cutoff after the generation's asof
    (later quotes and actions are unknown to it), a generation without an actions snapshot,
    and a requested code with no official quote on or before the cutoff. Without `codes`,
    every symbol with such a quote is returned.
    """
    started = time.monotonic()
    cutoff, inputs = _cutoff_inputs(status, as_of)
    directory = Path(status["path"])
    if calendar is None:
        calendar = _generation_calendar(status, inputs, cutoff)
        calendar_source = "generation"
    else:
        calendar_source = "caller"
    actions = _read_verified(directory / inputs["actions"]["file"], inputs["actions"], lambda source: pq.read_table(source).to_pandas())
    quotes = _read_stored_quotes(status, cutoff, codes)
    by_code = {str(code): frame for code, frame in quotes.groupby("Code", sort=True)}
    events_by_code = {str(code): frame for code, frame in actions.groupby("code", sort=False)}
    empty_events = actions.iloc[0:0]
    if codes is not None:
        absent = sorted({str(code) for code in codes} - set(by_code))
        if absent:
            raise ValueError(f"no official quote on or before {cutoff.date()} in generation {status['generation']} for {absent}")
        selected = list(dict.fromkeys(str(code) for code in codes))
    else:
        selected = sorted(by_code)
    frames = []
    for code in selected:
        prepared = price_basis.prepare_prices(by_code[code], events_by_code.get(code, empty_events), calendar, basis=basis, cutoff=cutoff)
        frame = prepared.rename_axis("Date").reset_index()
        frame.insert(0, "Code", code)
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=ARROW_SCHEMA.names)
    if columns is not None:
        result = cast(pd.DataFrame, result[list(columns)])
    record = {
        **_record(status, basis),
        "as_of": cutoff.date().isoformat(),
        "as_of_method": "price_basis.prepare_prices at as_of from the generation's raw quotes and actions snapshot",
        "definition": status["definition"]["prices"],
        "actions_sha256": inputs["actions"]["sha256"],
        "calendar": _calendar_record(calendar, calendar_source),
        "codes": len(selected),
    }
    LOGGER.info(
        "Read %s %s as_of=%s generation=%s codes=%d calendar=%s/%d rows=%d in %.1fs",
        FAMILY,
        basis,
        record["as_of"],
        status["generation"],
        len(selected),
        calendar_source,
        len(calendar),
        len(result),
        time.monotonic() - started,
    )
    return result, record
