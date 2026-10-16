"""Caller-supplied integer cohort accumulation in an exclusive scratch database."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import date
from numbers import Integral
from pathlib import Path
from statistics import median
from types import TracebackType
from typing import Any

import numpy as np
import pandas as pd

from research_core.artifact_store import canonical, object_digest
from research_core.pattern_scan_rates_v1 import Summary, summarize_events
from research_core.research_data_paths import _checked_path as physical_path

LOGGER = logging.getLogger(__name__)
YEARS = tuple(range(2010, 2027))
COUNT_FIELDS = (
    "event_n",
    "known_n",
    "unknown_n",
    "censored_n",
    "excluded_known_n",
    "hit_n",
    "loss_n",
    "flat_win_n",
    "observed_hit_n",
    "full_calendar_n",
    "full_calendar_unknown_n",
    "full_calendar_observed_hit_n",
    "censored_unknown_n",
    "censored_observed_hit_n",
    "full_main_potential_n",
    "full_eligibility_excluded_n",
    "censored_eligibility_excluded_n",
    "censored_potential_n",
    "full_potential_unknown_n",
    "censored_potential_hit_n",
    "censored_potential_unknown_n",
)


def _checked_path(path: Path, scratch_root: Path) -> Path:
    if not scratch_root.is_absolute() or ".tmp" not in scratch_root.parts:
        raise ValueError("scratch_root must be absolute with a .tmp component")
    scratch = physical_path(scratch_root)
    if not scratch.is_dir():
        raise ValueError("scratch_root must be an existing directory")
    target = physical_path(path)
    if not target.is_relative_to(scratch) or target == scratch:
        raise ValueError("summary database must be inside scratch_root")
    return target


class SummaryStore:
    """No database resume: each context creates a new exclusive schema."""

    def __init__(self, path: Path | str, *, scratch_root: Path | None = None) -> None:
        self.scratch_root = Path.cwd() / ".tmp" if scratch_root is None else scratch_root
        self.path = _checked_path(Path(path), self.scratch_root)
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> SummaryStore:
        if self._connection is not None:
            raise ValueError("store is already open")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _checked_path(self.path, self.scratch_root)
        with self.path.open("xb"):
            pass
        connection = sqlite3.connect(self.path)
        try:
            columns = ", ".join(f"{field} INTEGER NOT NULL CHECK({field} >= 0)" for field in COUNT_FIELDS)
            with connection:
                connection.execute("CREATE TABLE cells (cell_id TEXT PRIMARY KEY, metadata BLOB NOT NULL, horizon INTEGER)")
                connection.execute(
                    "CREATE TABLE feeds (cell_id TEXT NOT NULL, security_id TEXT NOT NULL, "
                    "PRIMARY KEY(cell_id,security_id), FOREIGN KEY(cell_id) REFERENCES cells(cell_id))"
                )
                connection.execute(
                    "CREATE TABLE counts (cell_id TEXT NOT NULL, security_id TEXT NOT NULL, "
                    "year INTEGER NOT NULL CHECK(year BETWEEN 2010 AND 2026), "
                    f"{columns}, PRIMARY KEY(cell_id,security_id,year))"
                )
        except Exception:
            connection.close()
            raise
        self._connection = connection
        LOGGER.debug("Opened new scratch summary database %s", self.path)
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise ValueError("store requires an open context")
        return self._connection

    def _cell(self, cell_id: str) -> tuple[bytes, int | None]:
        record = self._db().execute("SELECT metadata,horizon FROM cells WHERE cell_id=?", (cell_id,)).fetchone()
        if record is None:
            raise ValueError("unknown cell_id")
        return bytes(record[0]), None if record[1] is None else int(record[1])

    def register_cell(self, metadata: Mapping[str, Any]) -> str:
        """Canonical caller-owned facets define a cell, including empty cells."""
        content = canonical(dict(metadata))
        cell_id = object_digest(dict(metadata))
        with self._db():
            self._db().execute("INSERT OR IGNORE INTO cells(cell_id,metadata) VALUES (?,?)", (cell_id, content))
            if self._cell(cell_id)[0] != content:
                raise ValueError("cell metadata identity collision")
        return cell_id

    def register_cells(self, metadata: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
        """Register ordered canonical cells atomically, including duplicate IDs."""
        ordered: list[str] = []
        contents: dict[str, bytes] = {}
        for supplied in metadata:
            facets = dict(supplied)
            cell_id, content = object_digest(facets), canonical(facets)
            if cell_id in contents and contents[cell_id] != content:
                raise ValueError("cell metadata identity collision")
            contents[cell_id] = content
            ordered.append(cell_id)
        db = self._db()
        with db:
            db.executemany("INSERT OR IGNORE INTO cells(cell_id,metadata) VALUES (?,?)", contents.items())
            ids = tuple(contents)
            for start in range(0, len(ids), 500):
                batch = ids[start : start + 500]
                placeholders = ",".join("?" for _ in batch)
                for cell_id, content in db.execute(f"SELECT cell_id,metadata FROM cells WHERE cell_id IN ({placeholders})", batch):
                    if bytes(content) != contents[str(cell_id)]:
                        raise ValueError("cell metadata identity collision")
        LOGGER.debug("Registered summary cells supplied=%d unique=%d", len(ordered), len(contents))
        return tuple(ordered)

    def add_count_matrix(self, matrix: pd.DataFrame) -> None:
        """Feed complete caller-counted cell/stock/year integer batches atomically.

        A cell/stock feed must contain all its intended years in this call. This
        API validates identities and integer storage; upstream event accumulation
        owns count semantics. Stored stock/cell feeds cannot be appended later.
        """
        required = {"cell_id", "security_id", "year", "horizon", *COUNT_FIELDS}
        if not matrix.columns.is_unique or not required.issubset(matrix):
            raise ValueError("count matrix requires unique identity/count columns")
        db = self._db()
        if matrix.empty:
            return
        if matrix.duplicated(["cell_id", "security_id", "year"]).any():
            raise ValueError("duplicate cell/stock/year matrix rows")
        horizons: dict[str, int] = {}
        feeds: set[tuple[str, str]] = set()
        records: list[tuple[object, ...]] = []
        for supplied in matrix.loc[:, ["cell_id", "security_id", "year", "horizon", *COUNT_FIELDS]].itertuples(index=False, name=None):
            cell_id, stock, year_value, horizon_value, *counts = supplied
            if not isinstance(cell_id, str) or not cell_id.strip() or not isinstance(stock, str) or not stock.strip():
                raise ValueError("matrix identities require nonblank strings")
            values = (year_value, horizon_value, *counts)
            if any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) for value in values):
                raise ValueError("matrix year/horizon/counts require integers")
            year, horizon = int(year_value), int(horizon_value)
            integers = tuple(int(value) for value in counts)
            if year not in YEARS or not 1 <= horizon <= 2**63 - 1:
                raise ValueError("matrix year/horizon outside approved storage range")
            if any(not 0 <= value <= 2**63 - 1 for value in integers):
                raise ValueError("matrix counts outside SQLite positive range")
            if cell_id in horizons and horizons[cell_id] != horizon:
                raise ValueError("matrix cell horizon cannot change")
            horizons[cell_id] = horizon
            feeds.add((cell_id, stock))
            records.append((cell_id, stock, year, *integers))
        ids = tuple(horizons)
        existing: dict[str, int | None] = {}
        for start in range(0, len(ids), 500):
            batch = ids[start : start + 500]
            placeholders = ",".join("?" for _ in batch)
            for cell_id, horizon in db.execute(f"SELECT cell_id,horizon FROM cells WHERE cell_id IN ({placeholders})", batch):
                existing[str(cell_id)] = None if horizon is None else int(horizon)
        for cell_id, horizon in horizons.items():
            if cell_id not in existing:
                raise ValueError("unknown cell_id")
            if existing[cell_id] is not None and existing[cell_id] != horizon:
                raise ValueError("cell horizon cannot change")
        ordered_feeds = tuple(sorted(feeds))
        for start in range(0, len(ordered_feeds), 400):
            batch_feeds = ordered_feeds[start : start + 400]
            placeholders = ",".join("(?,?)" for _ in batch_feeds)
            parameters = tuple(value for pair in batch_feeds for value in pair)
            if db.execute(f"SELECT 1 FROM feeds WHERE (cell_id,security_id) IN ({placeholders}) LIMIT 1", parameters).fetchone() is not None:
                raise ValueError("duplicate stock feed")
        try:
            with db:
                db.executemany("INSERT INTO feeds(cell_id,security_id) VALUES (?,?)", ordered_feeds)
                db.executemany("UPDATE cells SET horizon=? WHERE cell_id=?", ((horizon, cell_id) for cell_id, horizon in horizons.items()))
                placeholders = ",".join("?" for _ in range(3 + len(COUNT_FIELDS)))
                db.executemany(f"INSERT INTO counts VALUES ({placeholders})", records)
        except sqlite3.IntegrityError as error:
            raise ValueError("duplicate stock feed or invalid matrix counts") from error
        LOGGER.debug("Added count matrix rows=%d stock/cell feeds=%d cells=%d", len(records), len(feeds), len(horizons))

    def metadata(self, cell_id: str) -> dict[str, Any]:
        """Return a detached copy of the fixed caller facets."""
        value = json.loads(self._cell(cell_id)[0])
        if not isinstance(value, dict):
            raise ValueError("invalid stored summary facets")
        return value

    def cell_ids(self) -> tuple[str, ...]:
        """Deterministic cell inventory, including zero-event cells."""
        return tuple(str(row[0]) for row in self._db().execute("SELECT cell_id FROM cells ORDER BY cell_id"))

    def add_stock(self, cell_id: str, frame: pd.DataFrame) -> None:
        """Feed one complete stock/cell once; failure rolls back the whole feed."""
        _, previous_horizon = self._cell(cell_id)
        summarize_events(frame)
        if frame.empty or frame["security_id"].nunique() != 1 or frame["horizon"].nunique() != 1:
            raise ValueError("add_stock requires exactly one stock and horizon")
        stock = str(frame["security_id"].iloc[0])
        horizon = int(frame["horizon"].iloc[0])
        if previous_horizon is not None and previous_horizon != horizon:
            raise ValueError("cell horizon cannot change")
        event_years = frame["t0"].map(lambda value: date.fromisoformat(value).year)
        if not bool(event_years.isin(YEARS).all()):
            raise ValueError("event years must be 2010..2026")
        records: list[tuple[object, ...]] = []
        for year in YEARS:
            rows = frame.loc[event_years.eq(year)]
            if rows.empty:
                continue
            summary = summarize_events(rows)
            full, unknown, eligible = rows["calendar_full"].astype(bool), rows["effective_label"].eq("unknown"), rows["event_main_eligible"].astype(bool)
            excluded = rows["event_eligibility_excluded"].astype(bool) if "event_eligibility_excluded" in rows else full & ~unknown & ~eligible
            extra = {
                "full_potential_unknown_n": int((full & ~excluded & unknown).sum()),
                "censored_potential_hit_n": int((~full & ~excluded & rows["effective_label"].eq("hit")).sum()),
                "censored_potential_unknown_n": int((~full & ~excluded & unknown).sum()),
            }
            values: list[int] = []
            for field in COUNT_FIELDS:
                value = extra[field] if field in extra else summary[field]
                if not isinstance(value, int) or not 0 <= value <= 2**63 - 1:
                    raise ValueError("summary integer outside SQLite positive range")
                values.append(value)
            records.append((cell_id, stock, year, *values))
        db = self._db()
        try:
            with db:
                db.execute("INSERT INTO feeds(cell_id,security_id) VALUES (?,?)", (cell_id, stock))
                db.execute("UPDATE cells SET horizon=? WHERE cell_id=?", (horizon, cell_id))
                placeholders = ",".join("?" for _ in range(3 + len(COUNT_FIELDS)))
                db.executemany(f"INSERT INTO counts VALUES ({placeholders})", records)
        except sqlite3.IntegrityError as error:
            raise ValueError("duplicate stock feed or invalid integer counts") from error
        LOGGER.debug("Added cell=%s stock=%s events=%d years=%d", cell_id, stock, len(frame), len(records))

    def _summary(self, cell_id: str, *, exclude_year: int | None = None, only_year: int | None = None) -> Summary:
        self._cell(cell_id)
        where, parameters = "cell_id=?", [cell_id]
        if exclude_year is not None:
            where += " AND year<>?"
            parameters.append(str(exclude_year))
        if only_year is not None:
            where += " AND year=?"
            parameters.append(str(only_year))
        sums = ",".join(f"COALESCE(SUM({field}),0)" for field in COUNT_FIELDS)
        record = self._db().execute(f"SELECT {sums} FROM counts WHERE {where}", parameters).fetchone()
        assert record is not None
        totals = dict(zip(COUNT_FIELDS, (int(value) for value in record), strict=True))
        stock_counts = [
            int(row[0]) for row in self._db().execute(f"SELECT SUM(event_n) FROM counts WHERE {where} GROUP BY security_id HAVING SUM(event_n)>0", parameters)
        ]
        result: Summary = {
            field: value
            for field, value in totals.items()
            if field not in ("full_potential_unknown_n", "censored_potential_hit_n", "censored_potential_unknown_n")
        }
        result.update(
            distinct_stock_n=len(stock_counts),
            per_stock_event_count_median=float(median(stock_counts)) if stock_counts else None,
            per_stock_event_count_max=max(stock_counts, default=0),
        )
        known, full, censored = totals["known_n"], totals["full_main_potential_n"], totals["censored_potential_n"]
        result.update(
            hit_rate=totals["hit_n"] / known if known else None,
            loss_rate=totals["loss_n"] / known if known else None,
            full_calendar_hit_lower_bound=totals["hit_n"] / full if full else None,
            full_calendar_hit_upper_bound=(totals["hit_n"] + totals["full_potential_unknown_n"]) / full if full else None,
            censored_hit_lower_bound=totals["censored_potential_hit_n"] / censored if censored else None,
            censored_hit_upper_bound=(totals["censored_potential_hit_n"] + totals["censored_potential_unknown_n"]) / censored if censored else None,
        )
        return result

    def summary(self, cell_id: str, exclude_year: int | None = None) -> Summary:
        if exclude_year is not None and (isinstance(exclude_year, bool) or exclude_year not in YEARS):
            raise ValueError("exclude_year must be an approved year")
        return self._summary(cell_id, exclude_year=exclude_year)

    def annual_summary(self, cell_id: str) -> tuple[Summary, ...]:
        """Return 17 summaries in YEARS order, including explicit zero cells."""
        return tuple(self._summary(cell_id, only_year=year) for year in YEARS)

    def drop_best_year(self, cell_id: str) -> tuple[int | None, Summary]:
        total = self.summary(cell_id)
        if total["event_n"] == 0:
            return None, total
        annual = self.annual_summary(cell_id)
        year = min(YEARS, key=lambda value: (-int(annual[value - 2010]["hit_n"] or 0), value))
        return year, self.summary(cell_id, exclude_year=year)
