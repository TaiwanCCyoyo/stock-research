"""Immutable local inputs and calendar-aligned descriptive price exports."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import math
import shutil
import sqlite3
import stat
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

LOGGER = logging.getLogger(__name__)
PRICE_HASH = "67ee9e48260d0ffe73180d0628d6a7f60238a3c576afce30b1ff6537c6ac8003"
ACTION_HASH = "3d53a4a7b9790ea2c2b5c4818523abcff530e8750b77db63428244eec30bfffc"
PERMANENT_EVENTS = frozenset({
    "ETF_SPLIT",
    "ETF_REVERSE_SPLIT",
    "EX_RIGHT",
    "EX_RIGHT_AND_DIVIDEND",
    "CASH_CAPITAL_REDUCTION",
    "LOSS_OFFSET_CAPITAL_REDUCTION",
    "CAPITAL_REDUCTION",
})
OHLC = ("Open", "High", "Low", "Close")
CAVEATS = [
    "early_action_coverage_incomplete",
    "retrospective_capture",
    "unknown_first_availability",
    "board_history_unknown",
    "classification_snapshot_not_historical",
    "delisted_coverage_unknown",
]


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _physical(path: Path) -> None:
    """Check every existing ancestor, including Windows junction/reparse points."""
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            attributes = getattr(item.lstat(), "st_file_attributes", 0)
            if item.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise ValueError(f"Links/reparse points are forbidden: {item}")


def require_empty_target(path: Path) -> None:
    _physical(path)
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise FileExistsError(f"Refusing nonempty target: {path}")


def _write_json(path: Path, value: Any) -> None:
    with path.open("xb") as stream:
        stream.write(canonical_bytes(value))


def _read_table(path: Path, table: str) -> list[dict[str, Any]]:
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]


def _file_identity(path: Path) -> tuple[int, int, int, int]:
    observed = path.stat()
    return observed.st_size, observed.st_mtime_ns, observed.st_dev, observed.st_ino


def _wal_identity(source: Path) -> tuple[int, int, int, int, str] | None:
    wal = Path(str(source) + "-wal")
    _physical(wal)
    try:
        identity = _file_identity(wal)
    except FileNotFoundError:
        return None
    if identity[0] > 0:
        raise ValueError(
            f"Nonempty source WAL is not authorized by the pinned main-file hash: {wal}; "
            "choose a checkpointed coherent source snapshot through the source project. "
            "Any partial task snapshot must be preserved; retry only with a new target."
        )
    return *identity, file_hash(wal)


def snapshot_inputs(source_paths: dict[str, Path], snapshot_dir: Path, expected_hashes: dict[str, str] | None = None) -> dict[str, Any]:
    """Pin main-file bytes only; refuse unpinned WAL and changing SQLite inputs."""
    require_empty_target(snapshot_dir)
    hashes: dict[str, str] = {}
    sqlite_identities: dict[str, tuple[tuple[int, int, int, int], tuple[int, int, int, int, str] | None]] = {}
    for name, source in source_paths.items():
        if Path(name).name != name or name in {".", "..", "input-receipt.json"}:
            raise ValueError(f"Invalid snapshot filename: {name}")
        _physical(source)
        if not source.is_file():
            raise FileNotFoundError(source)
        if source.suffix == ".sqlite":
            sqlite_identities[name] = _file_identity(source), _wal_identity(source)
        hashes[name] = file_hash(source)
        expected = (expected_hashes or {}).get(name)
        if expected is not None and hashes[name] != expected:
            raise ValueError(f"Source hash mismatch: {source}")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for name, source in sorted(source_paths.items()):
        target = snapshot_dir / name
        observed = datetime.now(UTC).isoformat()
        check = None
        if source.suffix == ".sqlite":
            main_identity, wal_identity = sqlite_identities[name]
            if _file_identity(source) != main_identity or _wal_identity(source) != wal_identity or file_hash(source) != hashes[name]:
                raise ValueError(f"SQLite main/WAL identity changed before backup: {source}; preserve partial snapshot {snapshot_dir}, use a new target")
            with target.open("xb"):
                pass
            with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
                # Initialize a pinned read transaction before recording its sidecar.
                # SQLite can create an empty WAL on the first read in mode=ro.
                src.execute("BEGIN")
                journal_mode = src.execute("PRAGMA journal_mode").fetchone()
                src.execute("SELECT name FROM sqlite_schema LIMIT 1").fetchall()
                reader_wal_identity = _wal_identity(source)
                reader_created_wal = wal_identity is None and reader_wal_identity is not None and journal_mode == ("wal",)
                if reader_created_wal:
                    wal_identity = reader_wal_identity
                    LOGGER.debug("Read-only SQLite initialization created an empty WAL: %s", source)
                if _file_identity(source) != main_identity or reader_wal_identity != wal_identity or file_hash(source) != hashes[name]:
                    raise ValueError(
                        f"SQLite main/WAL identity changed during reader initialization: {source}; preserve partial snapshot {snapshot_dir}, use a new target"
                    )
                with closing(sqlite3.connect(target)) as dst:
                    src.backup(dst)
                    check = dst.execute("PRAGMA quick_check").fetchall()
                    if check != [("ok",)]:
                        raise ValueError(f"SQLite quick_check failed: {target}: {check}")
                if _file_identity(source) != main_identity or _wal_identity(source) != wal_identity:
                    raise ValueError(f"SQLite main/WAL identity changed during backup: {source}; preserve partial snapshot {snapshot_dir}, use a new target")
            closed_wal_identity = _wal_identity(source)
            # Closing the reader can naturally remove only its own empty WAL.
            # A close-time writer commit or a changed pre-existing WAL still fails.
            reader_removed_wal = reader_created_wal and closed_wal_identity is None
            if _file_identity(source) != main_identity or (closed_wal_identity != wal_identity and not reader_removed_wal):
                raise ValueError(f"SQLite main/WAL identity changed while closing reader: {source}; preserve partial snapshot {snapshot_dir}, use a new target")
            if reader_removed_wal:
                LOGGER.debug("Reader-created empty WAL disappeared during close: %s", source)
        else:
            with source.open("rb") as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst)
        if file_hash(source) != hashes[name]:
            raise ValueError(f"Source changed during snapshot: {source}")
        snapshot_hash = file_hash(target)
        if source.suffix != ".sqlite" and snapshot_hash != hashes[name]:
            raise ValueError(f"Snapshot copy hash mismatch: {target}")
        files.append({
            "name": name,
            "source_path": str(source.resolve()),
            "source_sha256": hashes[name],
            "snapshot_sha256": snapshot_hash,
            "source_observed_at": observed,
            "source_mtime_ns": source.stat().st_mtime_ns,
            "copy_method": "sqlite_backup" if check else "physical_copy",
            "quick_check": "ok" if check else None,
        })
        LOGGER.info("Pinned %s via %s", name, files[-1]["copy_method"])
    receipt = {"schema_version": "opportunity-input-receipt.v1", "files": files}
    _write_json(snapshot_dir / "input-receipt.json", receipt)
    return receipt


def _number(value: Any, *, positive: bool = False) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and (not positive or number > 0) else None


def build_series(
    frame: pd.DataFrame,
    dates: list[str],
    *,
    code: str,
    metadata: dict[str, Any],
    name: str | None,
    calendar_id: str,
    events: list[dict[str, Any]],
    cutoff: str,
    listing_segments: list[str] | None = None,
) -> dict[str, Any]:
    """Keep missing calendar slots and raw/adjusted numeric validity separate."""
    index = {date: i for i, date in enumerate(dates)}
    raw: dict[str, list[float | None]] = {column: [None] * len(dates) for column in OHLC}
    adjusted: dict[str, list[float | None]] = {column: [None] * len(dates) for column in OHLC}
    volume: list[float | None] = [None] * len(dates)
    sources: list[str | None] = [None] * len(dates)
    flags: dict[str, list[str]] = {}
    volume_flags: dict[str, list[str]] = {}
    rows = frame.to_dict("records")
    quote_dates = sorted(str(row["Date"]) for row in rows)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        date = str(event["ex_date"])
        if date <= cutoff and event.get("event_type") != "CASH_DIVIDEND":
            grouped[date].append(event)
    factors: list[tuple[str, float]] = []
    barriers = []
    for date, records in sorted(grouped.items()):
        signatures = {(item.get("event_type"), _number(item.get("price_factor"), positive=True)) for item in records}
        event_type, factor = next(iter(signatures))
        reason = None
        if len(signatures) > 1:
            reason = "conflicting_action_records"
        elif event_type not in PERMANENT_EVENTS:
            reason = "unsupported_action_type"
        elif factor is None:
            reason = "unresolved_action_factor"
        if reason:
            has_prior_quote = any(quote < date for quote in quote_dates)
            affected = next((quote for quote in quote_dates if quote >= date), None) if has_prior_quote else None
            affected_index = index.get(affected) if affected else None
            barriers.append({
                "ex_date": date,
                "index": affected_index,
                "reason": reason,
                "continuity_edge_observed": affected_index is not None,
                "records": [{"event_type": item.get("event_type"), "price_factor": _number(item.get("price_factor"))} for item in records],
            })
            if affected_index is not None:
                flags.setdefault(str(affected_index), []).append("action_barrier")
        else:
            assert factor is not None
            factors.append((date, factor))
    for row in rows:
        date = str(row["Date"])
        i = index[date]
        factor = math.prod(event_factor for event_date, event_factor in factors if date < event_date <= cutoff)
        for column in OHLC:
            value = _number(row[column], positive=True)
            raw[column][i] = value
            scaled = _number(value * factor, positive=True) if value is not None else None
            rounded = round(scaled, 4) if scaled is not None else None
            adjusted[column][i] = rounded if rounded is not None and rounded > 0 else None
        if raw["Close"][i] is None:
            flags.setdefault(str(i), []).append("invalid_raw_close")
        elif adjusted["Close"][i] is None:
            flags.setdefault(str(i), []).append("unusable_adjusted_close")
        volume_value = _number(row["Volume"])
        volume[i] = volume_value
        if volume_value is None or volume_value < 0:
            volume_flags[str(i)] = ["invalid_volume"]
        sources[i] = None if pd.isna(row["Source"]) else str(row["Source"])
    category = metadata.get("security_category")
    role = "benchmark" if code == "0050" else "stock" if category in {"股票", "創新板"} else "unresolved_identity"
    cohort = (
        "benchmark"
        if role == "benchmark"
        else "metadata_stock"
        if category == "股票"
        else "innovation_board"
        if category == "創新板"
        else "unresolved_identity"
    )
    coverage = {
        "first_date": quote_dates[0] if quote_dates else None,
        "last_date": quote_dates[-1] if quote_dates else None,
        "date_count": len(rows),
        "missing_count": len(dates) - len(rows),
        "source_counts": dict(sorted(Counter(str(row["Source"]) for row in rows if not pd.isna(row["Source"])).items())),
        "source_missing_count": sum(1 for row in rows if pd.isna(row["Source"])),
        "usable_adjusted_count": sum(value is not None and str(i) not in flags for i, value in enumerate(adjusted["Close"])),
        "eligible": role == "stock",
    }
    result: dict[str, Any] = {
        "schema_version": "opportunity-series.v1",
        "security_id": f"TW:{code}",
        "code": code,
        "name": name,
        "cohort": cohort,
        "instrument_role": role,
        "calendar_id": calendar_id,
        "raw": raw["Close"],
        "adjusted": adjusted["Close"],
        "raw_ohlc": raw,
        "adjusted_ohlc": adjusted,
        "volume": volume,
        "sources": sources,
        "numeric_flags": flags,
        "volume_flags": volume_flags,
        "action_barriers": barriers,
        "coverage_caveats": CAVEATS.copy(),
        "coverage": coverage,
        "listing_segments_snapshot_clue": listing_segments or [],
        "corporate_actions": [
            {
                "ex_date": str(e["ex_date"]),
                "event_type": e.get("event_type"),
                "price_factor": _number(e.get("price_factor")),
                "source": e.get("source"),
                "market": e.get("market"),
                "evidence_status": e.get("evidence_status"),
                "fetched_at": e.get("fetched_at"),
                "sql_locator": {
                    "path": "corporate_actions.sqlite",
                    "table": "corporate_actions",
                    "key": {"source": e.get("source"), "market": e.get("market"), "code": code, "ex_date": str(e["ex_date"])},
                },
                "first_available_at": None,
                "availability_reason": "unknown_first_availability",
            }
            for e in events
        ],
    }
    if any(not barrier["continuity_edge_observed"] for barrier in barriers):
        result["coverage_caveats"].append("unresolved_action_without_observed_continuity_edge")
    result["series_id"] = "sha256:" + hashlib.sha256(canonical_bytes(result)).hexdigest()
    return result


def export_series(snapshot_dir: Path, output_dir: Path, *, start: str = "2010-01-04", end: str = "2026-10-02") -> dict[str, Any]:
    require_empty_target(output_dir)
    _physical(snapshot_dir)
    receipt = json.loads((snapshot_dir / "input-receipt.json").read_text(encoding="utf-8"))
    for item in receipt["files"]:
        if file_hash(snapshot_dir / item["name"]) != item["snapshot_sha256"]:
            raise ValueError(f"Snapshot hash mismatch: {item['name']}")
    frame = pd.read_parquet(snapshot_dir / "price_daily.parquet")
    required = {"Code", "Date", *OHLC, "Volume", "Source"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Missing price columns: {sorted(required - set(frame.columns))}")
    frame["Code"] = frame["Code"].astype(str)
    all_codes = sorted(frame["Code"].unique())
    frame["Date"] = pd.to_datetime(frame["Date"], errors="raise").dt.strftime("%Y-%m-%d")
    frame = frame.loc[frame["Date"].between(start, end)].copy()
    if frame.duplicated(["Code", "Date"]).any():
        raise ValueError("Duplicate Code/Date in pinned Parquet")
    dates = sorted(frame["Date"].unique())
    calendar = {"schema_version": "opportunity-calendar.v1", "name": "source-date-union", "dates": dates, "start": start, "end": end, "timezone": "Asia/Taipei"}
    calendar_id = "sha256:" + hashlib.sha256(canonical_bytes(calendar)).hexdigest()
    calendar["calendar_id"] = calendar_id
    metadata = {str(row["code"]): row for row in _read_table(snapshot_dir / "symbol_meta.sqlite", "symbol_meta")}
    actions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _read_table(snapshot_dir / "corporate_actions.sqlite", "corporate_actions"):
        actions[str(row["code"])].append(row)
    names = json.loads((snapshot_dir / "stock_symbol_mapping.json5").read_text(encoding="utf-8-sig"))
    taxonomy_path = snapshot_dir / "value_chain_classification.json"
    clues: dict[str, set[str]] = defaultdict(set)
    if taxonomy_path.exists():
        taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
        for code, symbol in taxonomy.get("symbols", {}).items():
            for segment in symbol.get("listing_segments", []):
                clues[str(code)].add(str(segment))
        for chain in taxonomy.get("chains", []):
            for node in chain.get("nodes", []):
                for member in node.get("members", []):
                    if member.get("listing_segment"):
                        clues[str(member["code"])].add(member["listing_segment"])
    for code in all_codes:
        if not code.isascii() or not code.isalnum():
            raise ValueError(f"Unsafe code for file export: {code}")
    output_dir.mkdir(parents=True, exist_ok=True)
    series_dir = output_dir / "series"
    series_dir.mkdir()
    _write_json(series_dir / "calendar.json", calendar)
    rows = []
    by_code = {code: group.sort_values("Date") for code, group in frame.groupby("Code")}
    for code in all_codes:
        meta = metadata.get(code, {})
        series = build_series(
            by_code.get(code, frame.iloc[:0]),
            dates,
            code=code,
            metadata=meta,
            name=meta.get("name") or names.get(code),
            calendar_id=calendar_id,
            events=actions.get(code, []),
            cutoff=end,
            listing_segments=sorted(clues[code]),
        )
        path = series_dir / f"{code}.json.gz"
        with path.open("xb") as stream:
            with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
                compressed.write(canonical_bytes(series))
        rows.append(
            {key: series[key] for key in ("security_id", "code", "name", "cohort", "instrument_role", "series_id", "coverage")}
            | {"path": path.relative_to(output_dir).as_posix(), "sha256": file_hash(path)}
        )
        if len(rows) % 50 == 0:
            LOGGER.info("Export progress: %d/%d securities", len(rows), len(all_codes))
    manifest = {
        "schema_version": "opportunity-series-manifest.v1",
        "calendar_id": calendar_id,
        "calendar": {"path": "series/calendar.json", "sha256": file_hash(series_dir / "calendar.json"), "count": len(dates)},
        "price_basis": "permanent-reference-factor-close.preview.v1",
        "currency": "TWD",
        "volume_unit": "lots",
        "input_receipt": receipt,
        "count": len(rows),
        "rows": rows,
    }
    _write_json(output_dir / "series-manifest.json", manifest)
    LOGGER.info("Exported %d securities across %d calendar dates", len(rows), len(dates))
    return manifest
