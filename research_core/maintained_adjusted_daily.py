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

Every new ex-date restates the whole earlier history of that symbol, so an update builds
a complete new generation and then flips ``current.json`` with ``os.replace`` (atomic on
Windows, unlike replacing a directory). The previous generation is kept for rollback and
for readers still holding it; older ones are pruned. A failed build never touches
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
import shutil
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar, cast

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from research_core import price_basis
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
    """Prepare every symbol for every basis; stream into `writers` when given.

    Returns calendar, cutoff and per-basis counts. Without writers it only measures.
    """
    calendar = session_calendar(bars)
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
        bars, actions, fingerprint, source_policy = load_inputs(producer_root)
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
    cutoff = cast(pd.Timestamp, pd.Timestamp(as_of))
    if pd.isna(cutoff) or cutoff.tzinfo is not None or cutoff != cutoff.normalize():
        raise ValueError(f"as_of must be a naive date, got {as_of!r}")
    if cutoff > pd.Timestamp(status["asof"]):
        raise ValueError(f"as_of {cutoff.date()} is after generation {status['generation']} asof {status['asof']}; its later quotes and actions are unknown")
    inputs = status.get("as_of_inputs")
    if inputs is None:
        raise ValueError(f"generation {status['generation']} has no actions snapshot and cannot be read as_of; run scripts.maintain_adjusted_daily update")
    directory = Path(status["path"])
    if calendar is None:
        sessions = _read_verified(directory / inputs["calendar"]["file"], inputs["calendar"], lambda source: pq.read_table(source).to_pandas())
        calendar = pd.DatetimeIndex(sessions["Date"])
        calendar = calendar[calendar <= cutoff]
        calendar_source = "generation"
    else:
        calendar_source = "caller"
    actions = _read_verified(directory / inputs["actions"]["file"], inputs["actions"], lambda source: pq.read_table(source).to_pandas())
    filters: list[Any] = [("Date", "<=", cutoff)]
    if codes is not None:
        filters.append(("Code", "in", [str(code) for code in codes]))
    stored = _read_verified(
        directory / "raw.parquet",
        status["bases"]["raw"],
        lambda source: pq.read_table(source, columns=["Code", "Date", *RAW_QUOTE_COLUMNS, "quality_reason"], filters=filters).to_pandas(),
    )
    quotes = _stored_quotes(stored)
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
    days = [day.date().isoformat() for day in calendar]
    record = {
        **_record(status, basis),
        "as_of": cutoff.date().isoformat(),
        "as_of_method": "price_basis.prepare_prices at as_of from the generation's raw quotes and actions snapshot",
        "definition": status["definition"]["prices"],
        "actions_sha256": inputs["actions"]["sha256"],
        "calendar": {
            "source": calendar_source,
            "sessions": len(days),
            "first": days[0] if days else None,
            "last": days[-1] if days else None,
            "sha256": object_digest(days),
        },
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
        len(days),
        len(result),
        time.monotonic() - started,
    )
    return result, record
