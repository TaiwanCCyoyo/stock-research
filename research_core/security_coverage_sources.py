"""Explicit maintenance-time scans; HTTP never imports or invokes this module."""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.dataset as ds

from research_core import live_producer
from research_core.artifact_store import safe_path
from research_core.data_series import SPECS
from research_core.security_coverage import normalized_market

LOGGER = logging.getLogger(__name__)
SQLITE_SPECS = {
    "official_daily": ("official_daily.sqlite", "official_daily_price", "date"),
    "institutional": (SPECS["institutional"].filename, SPECS["institutional"].table, SPECS["institutional"].period),
    "monthly_revenue": (SPECS["monthly-revenue"].filename, SPECS["monthly-revenue"].table, SPECS["monthly-revenue"].period),
    "corporate_actions": ("corporate_actions.sqlite", "corporate_actions", "ex_date"),
}


def _identity(path: Path) -> list[dict[str, Any]]:
    """Include absent sidecars so appearance of a WAL also invalidates a scan."""
    items = []
    for source in (path, path.with_name(path.name + "-wal")):
        try:
            stat = safe_path(source).stat()
            items.append({"file": source.name, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
        except FileNotFoundError:
            items.append({"file": source.name, "absent": True})
    return items


def _code_filter(codes: tuple[str, ...] | None) -> tuple[str, tuple[str, ...]]:
    if not codes:
        return "", ()
    return f"code IN ({','.join('?' for _ in codes)})", codes


def _sqlite_members(
    path: Path,
    table: str,
    period: str,
    *,
    deadline: float,
    gaps: bool,
    codes: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    connection = live_producer.readonly_sqlite(safe_path(path), timeout=min(5, max(0.1, deadline - time.monotonic())))
    try:
        connection.row_factory = sqlite3.Row
        connection.set_progress_handler(lambda: time.monotonic() >= deadline, 10_000)
        # Identifiers only come from static SQL specs, never from a user query.
        code_filter, parameters = _code_filter(codes)
        if gaps:
            query = f"""
                WITH ordered AS (
                    SELECT market, code, {period} AS d,
                           LAG({period}) OVER (PARTITION BY market, code ORDER BY {period}) AS prior
                    FROM {table}{f" WHERE {code_filter}" if code_filter else ""}
                )
                SELECT market, code, MIN(d) AS first, MAX(d) AS last, COUNT(*) AS rows,
                    GROUP_CONCAT(CASE WHEN julianday(d) - julianday(prior) > 366 THEN prior || '/' || d END) AS gaps
                FROM ordered GROUP BY market, code
            """
        else:
            query = f"SELECT market, code, MIN({period}) AS first, MAX({period}) AS last, COUNT(*) AS rows FROM {table}"
            if code_filter:
                query += f" WHERE {code_filter}"
            query += " GROUP BY market, code"
        members = []
        for row in connection.execute(query, parameters):
            value = dict(row)
            value["market"] = normalized_market(value["market"])
            value["code"] = str(value["code"])
            value["gaps"] = [item.split("/") for item in (value.get("gaps") or "").split(",") if item]
            members.append(value)
        if time.monotonic() > deadline:
            raise TimeoutError("coverage query exceeded its budget")
        return members
    finally:
        connection.close()


def _metadata(path: Path, deadline: float, codes: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    connection = live_producer.readonly_sqlite(safe_path(path), timeout=5)
    try:
        connection.row_factory = sqlite3.Row
        connection.set_progress_handler(lambda: time.monotonic() >= deadline, 1000)
        records = []
        code_filter, parameters = _code_filter(codes)
        query = "SELECT code,name,market,listed_date,is_etf,security_category,fetched_at FROM symbol_meta"
        if code_filter:
            query += f" WHERE {code_filter}"
        for record in connection.execute(query, parameters):
            row = dict(record)
            listed = str(row.get("listed_date") or "").replace("/", "-")
            try:
                row["listed_date"] = datetime.strptime(listed, "%Y-%m-%d").date().isoformat()
            except ValueError:
                row["listed_date"] = None
            records.append(row)
        return records
    finally:
        connection.close()


def parquet_members(
    path: Path,
    markets: dict[str, set[str]],
    *,
    deadline: float,
    codes: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Read only Code/Date in bounded batches, reducing before Python materialization."""
    members: dict[tuple[str, str], dict[str, Any]] = {}
    parquet_path = safe_path(path)
    parquet_filter = ds.field("Code").isin(list(codes)) if codes else None
    scanner = ds.dataset(parquet_path, format="parquet").scanner(columns=["Code", "Date"], filter=parquet_filter, batch_size=65_536, use_threads=False)
    for batch in scanner.to_batches():
        if time.monotonic() > deadline:
            raise TimeoutError("coverage parquet scan exceeded its budget")
        table = pa.Table.from_batches([batch])
        if table.column("Code").null_count or table.column("Date").null_count:
            raise ValueError("null code/date in price identity")
        reduced = table.group_by("Code", use_threads=False).aggregate([("Date", "min"), ("Date", "max"), ("Date", "count")])
        for row in reduced.to_pylist():
            code = str(row["Code"])
            candidates = markets.get(code, set())
            market = next(iter(candidates)) if len(candidates) == 1 else "unknown"
            key = market, code
            low, high = str(row["Date_min"])[:10], str(row["Date_max"])[:10]
            item = members.setdefault(key, {"market": market, "code": code, "rows": 0, "first": low, "last": high, "gaps": []})
            item["rows"] += int(row["Date_count"])
            item["first"], item["last"] = min(item["first"], low), max(item["last"], high)
    return sorted(members.values(), key=lambda item: (item["market"], item["code"]))


def collect_sources(
    producer_root: Path,
    *,
    seconds_per_source: float = 180,
    codes: tuple[str, ...] | None = None,
    measure_resources: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Guard each scan and retain change/failure as unknown rather than measured zero."""
    if not 1 <= seconds_per_source <= 1800:
        raise ValueError("source budget must be between 1 and 1800 seconds")
    if codes is not None and (not codes or len(codes) > 100 or any(not code for code in codes)):
        raise ValueError("selected-code scans require 1 to 100 non-empty codes")
    live_producer.assert_producer_idle(task_timeout=5)
    root = safe_path(producer_root)
    sources: dict[str, Any] = {}
    metadata: list[dict[str, Any]] = []
    scanned: dict[Path, list[dict[str, Any]]] = {}

    def record(dataset: str, path: Path, reader: Any) -> Any:
        started = time.monotonic()
        cpu = time.process_time()
        resource_before = None
        if measure_resources:
            from research_core.research_measurement_v1 import resource_sample

            resource_before = resource_sample()
        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            live_producer.assert_producer_idle(task_timeout=5)
            before = _identity(path)
            result = reader(time.monotonic() + seconds_per_source)
            live_producer.assert_producer_idle(task_timeout=5)
            if _identity(path) != before:
                raise live_producer.ProducerChangedError("coverage input changed")
            scanned[path] = before
            sources[dataset] = {"status": "ok", "checked_at": checked_at, "input_fingerprint": before}
            return result
        except (OSError, ValueError, sqlite3.Error, TimeoutError, RuntimeError) as exc:
            LOGGER.warning("Coverage source unavailable dataset=%s: %s", dataset, exc)
            sources[dataset] = {"status": "unavailable", "checked_at": checked_at, "reason": "source_unavailable"}
            return None
        finally:
            sources[dataset]["timing"] = {
                "wall_seconds": time.monotonic() - started,
                "cpu_seconds": time.process_time() - cpu,
                "memory_bytes": None,
                "io_bytes": None,
            }
            if measure_resources and resource_before is not None:
                from research_core.research_measurement_v1 import phase_receipt, resource_sample

                sources[dataset]["measurement"] = phase_receipt(f"security_coverage_source:{dataset}", resource_before, resource_sample())
                sources[dataset]["measurement"]["selected_codes"] = list(codes) if codes else None
                sources[dataset]["measurement"]["scan_scope"] = (
                    (
                        "selected codes; Parquet batches filtered, physical reads may include full row groups"
                        if dataset == "price_daily"
                        else "selected codes; SQLite rows filtered by bound code parameters"
                    )
                    if codes
                    else "full source"
                )
            LOGGER.info("Coverage source=%s status=%s wall=%.3fs", dataset, sources[dataset]["status"], time.monotonic() - started)

    values = record("symbol_meta", root / "symbol_meta.sqlite", lambda deadline: _metadata(root / "symbol_meta.sqlite", deadline, codes))
    if values is not None:
        metadata = values
        sources["symbol_meta"]["members"] = [
            {
                "market": normalized_market(row["market"]),
                "code": str(row["code"]),
                "rows": 1,
                "first": (row.get("fetched_at") or "")[:10] or None,
                "last": (row.get("fetched_at") or "")[:10] or None,
            }
            for row in metadata
        ]
    for dataset, (filename, table, period) in SQLITE_SPECS.items():
        path = root / filename
        members = record(
            dataset,
            path,
            lambda deadline, p=path, t=table, col=period, ds_name=dataset: _sqlite_members(
                p, t, col, deadline=deadline, gaps=ds_name == "official_daily", codes=codes
            ),
        )
        if members is not None:
            sources[dataset]["members"] = members
            sources[dataset]["first"] = min((item["first"] for item in members if item["first"]), default=None)
            sources[dataset]["last"] = max((item["last"] for item in members if item["last"]), default=None)
            sources[dataset]["first_by_market"] = {
                market: min(item["first"] for item in members if item["market"] == market and item["first"])
                for market in sorted({item["market"] for item in members if item["first"]})
            }
    markets: dict[str, set[str]] = {}
    for source in sources.values():
        for member in source.get("members", []):
            if member["market"] != "unknown":
                markets.setdefault(member["code"], set()).add(member["market"])
    members = record(
        "price_daily",
        root / "price_daily.parquet",
        lambda deadline: parquet_members(root / "price_daily.parquet", markets, deadline=deadline, codes=codes),
    )
    if members is not None:
        sources["price_daily"]["members"] = members
    collect_adjusted_summary(
        sources,
        markets,
        seconds_per_source=seconds_per_source,
        codes=codes,
        measure_resources=measure_resources,
    )
    # Recheck all source/WAL identities before publishing a cross-source summary.
    live_producer.assert_producer_idle(task_timeout=5)
    for path, before in scanned.items():
        if _identity(path) != before:
            raise live_producer.ProducerChangedError("input changed across coverage maintenance")
    return sources, metadata


def collect_adjusted_summary(
    sources: dict[str, Any],
    markets: dict[str, set[str]],
    *,
    seconds_per_source: float,
    codes: tuple[str, ...] | None = None,
    measure_resources: bool = False,
) -> None:
    """Pin and verify one existing maintained generation; never rebuild prices."""
    from research_core import maintained_adjusted_daily as maintained
    from research_core.artifact_store import file_digest

    started = time.monotonic()
    resource_before = None
    if measure_resources:
        from research_core.research_measurement_v1 import resource_sample

        resource_before = resource_sample()
    held = False
    holder = f"security-coverage-{uuid.uuid4().hex}"
    try:
        status = maintained.current_generation()
        maintained.hold_generation(status["generation"], holder=holder, reason="coverage metadata maintenance")
        held = True
        pinned = maintained.current_generation(generation=status["generation"])
        path = safe_path(Path(pinned["path"]) / "reference_factor_adjusted.parquet")
        expected = pinned["bases"]["reference_factor_adjusted"]
        if path.stat().st_size != expected["bytes"] or file_digest(path) != expected["sha256"]:
            raise ValueError("adjusted price generation failed verification")
        members = parquet_members(path, markets, deadline=time.monotonic() + seconds_per_source, codes=codes)
        if file_digest(path) != expected["sha256"]:
            raise ValueError("adjusted price generation changed")
        sources["adjusted_daily"] = {
            "status": "ok",
            "generation": pinned["generation"],
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "input_identifier": {"generation": pinned["generation"], "sha256": expected["sha256"]},
            "members": members,
            "timing": {"wall_seconds": time.monotonic() - started, "memory_bytes": None, "io_bytes": None},
        }
        if measure_resources and resource_before is not None:
            from research_core.research_measurement_v1 import phase_receipt, resource_sample

            sources["adjusted_daily"] = {
                **sources["adjusted_daily"],
                "measurement": phase_receipt("security_coverage_source:adjusted_daily", resource_before, resource_sample()),
            }
            sources["adjusted_daily"]["measurement"].update(
                selected_codes=list(codes) if codes else None,
                scan_scope=("selected codes; Parquet row batches filtered, physical reads may include full row groups" if codes else "full Parquet source"),
            )
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        LOGGER.warning("Adjusted coverage unavailable: %s", exc)
        sources["adjusted_daily"] = {"status": "unavailable", "reason": "source_unavailable"}
    finally:
        if held:
            maintained.release_generation(holder)
        if measure_resources and resource_before is not None and "adjusted_daily" in sources and "measurement" not in sources["adjusted_daily"]:
            from research_core.research_measurement_v1 import phase_receipt, resource_sample

            # Failure paths still produce a complete phase receipt for diagnosis.
            sources["adjusted_daily"] = {
                **sources["adjusted_daily"],
                "measurement": phase_receipt("security_coverage_source:adjusted_daily", resource_before, resource_sample()),
            }
