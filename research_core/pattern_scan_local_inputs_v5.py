"""Original PR17 inputs and bounded, unhashed continuation projections.

Old receipts are read as descriptions, never rehashed. The maintained technical
family and the retired preview are not inputs to this unfinished research run.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from research_core.artifact_store import read_json, write_json
from research_core.pattern_scan_classification_cache_v1 import ConditionClassificationCache
from research_core.pattern_scan_event_tables_v1 import EventTables, build_event_tables
from research_core.pattern_scan_holding_v1 import OUTPUT_COLUMNS, holding_values
from research_core.pattern_scan_parquet_v1 import read_frame, write_frame
from research_core.pattern_scan_receipt_io_v2 import read_scan_receipt
from research_core.research_data_paths import checked_path

LOGGER = logging.getLogger(__name__)
TABLES = ("indicators", "pivots", "common_values", "universe", "pattern_states", "raw_events", "cohort_events", "controls", "base_labels")
EVENT_FILES = ("events", "conditions", "group_memberships", "daily_groups", "formula_groups")
HOLDING_KEYS = ("security_id", "t0", "calendar_index", "horizon", "calendar_full", "censored", "endpoint_out_of_range", "observed_sessions")


def write_progress(path: Path, value: dict[str, Any]) -> None:
    """Replace one small mutable phase status atomically, without a digest."""
    staged = path.with_name(f".{path.name}-{uuid.uuid4().hex}")
    write_json(staged, value)
    os.replace(staged, path)


def group_frame(bound: EventTables, group: str, horizon: int) -> pd.DataFrame:
    """The original membership/outcome/condition join, without file verification."""
    events = bound.events.loc[bound.events.horizon.eq(horizon)]
    members = bound.group_memberships.loc[bound.group_memberships.group_id.eq(group)]
    result = members.merge(events, on="event_id", how="left", validate="one_to_one").merge(bound.conditions, on="event_id", how="left", validate="one_to_one")
    result["mkt"] = result["MKT"].fillna("unknown")
    return result


def industry_holding(
    close: pd.DataFrame,
    jumps: pd.DataFrame,
    industries: dict[str, str],
    benchmark: pd.DataFrame,
    context: pd.DataFrame,
    codes: tuple[str, ...],
    anchors: dict[str, list[int]],
) -> pd.DataFrame:
    """Reduce a complete reference-industry peer block in original column order.

    Peers outside this industry never enter the original reduction. Every peer
    inside it, including all-unknown stocks, stays present. Differential tests
    compare this partition with the full-grid public kernel exactly.
    """
    if not codes or any(industries[code] != industries[codes[0]] for code in codes):
        raise ValueError("one complete reference-industry block required")
    expected = tuple(code for code in close if industries[code] == industries[codes[0]])
    if codes != expected:
        raise ValueError("industry block must retain every peer in original order")
    retrospective = context.set_index("Date") if "Date" in context else context
    return holding_values(
        close.loc[:, list(codes)],
        {code: industries[code] for code in codes},
        cast(pd.Series, benchmark["Close"]),
        cast(pd.Series, retrospective["retrospective_state"]),
        jump_matrix=jumps.loc[:, list(codes)],
        benchmark_jump=cast(pd.Series, benchmark["quality_reason"]).fillna("").str.contains("unexplained.*jump", regex=True),
        anchors=anchors,
    )


def _cached_holding(
    path: Path,
    security: str,
    calendar: pd.DatetimeIndex,
    anchors: list[int],
    *,
    full: bool,
    exact_anchors: bool = False,
) -> pd.DataFrame | None:
    """Read a bounded stock cache only when its footer and fixed clocks agree."""
    try:
        metadata = pq.read_metadata(path)
        schema = metadata.schema.to_arrow_schema()
        if tuple(schema.names) != OUTPUT_COLUMNS:
            return None
        frame = read_frame(path, columns=None if full else list(HOLDING_KEYS))
    except PermissionError:
        raise
    except (OSError, ValueError, pa.ArrowException):
        return None
    if metadata.num_rows != len(frame):
        return None
    requested = set(anchors)
    if frame.empty:
        return frame if not requested else None
    if not bool(frame.security_id.eq(security).all()):
        return None
    if any(not pd.api.types.is_integer_dtype(frame[name]) for name in ("calendar_index", "horizon", "observed_sessions")):
        return None
    if any(not pd.api.types.is_bool_dtype(frame[name]) for name in ("calendar_full", "censored", "endpoint_out_of_range")):
        return None
    positions = frame.calendar_index.to_numpy(dtype=np.int64)
    horizons = frame.horizon.to_numpy(dtype=np.int64)
    if bool(((positions < 0) | (positions >= len(calendar))).any()) or not bool(np.isin(horizons, (126, 252)).all()):
        return None
    observed_anchors = set(int(position) for position in positions)
    if (exact_anchors and observed_anchors != requested) or not requested.issubset(observed_anchors):
        return None
    pairs = set(zip(positions.tolist(), horizons.tolist(), strict=True))
    if len(pairs) != len(frame) or pairs != {(position, horizon) for position in observed_anchors for horizon in (126, 252)}:
        return None
    if frame.t0.tolist() != calendar[positions].strftime("%Y-%m-%d").tolist():
        return None
    full_clock = positions + horizons < len(calendar)
    if not np.array_equal(frame.calendar_full.to_numpy(), full_clock):
        return None
    if not np.array_equal(frame.censored.to_numpy(), ~full_clock) or not np.array_equal(frame.endpoint_out_of_range.to_numpy(), ~full_clock):
        return None
    if not np.array_equal(frame.observed_sessions.to_numpy(), np.minimum(horizons, len(calendar) - positions - 1)):
        return None
    return frame


class LocalInputs:
    """Read completed stock/global tables in place and reuse existing events.

    Only one stock is cached in memory. A target's missing projections may be
    materialized in an owned temporary directory once; completion is a stock
    list, not a manifest of file hashes. No latest/shared-price reader is used.
    """

    group_frame = staticmethod(group_frame)

    def __init__(self, stock_result: Path, temporary: Path) -> None:
        self.stock_result = checked_path(stock_result)
        self.run = self.stock_result.parent
        self.temporary = checked_path(temporary)
        if self.temporary == self.run or self.temporary.is_relative_to(self.run) or self.run.is_relative_to(self.temporary):
            raise ValueError("continuation temporary files must be separate from original inputs")
        self.temporary.mkdir(parents=True, exist_ok=True)
        stock = read_scan_receipt(self.stock_result)
        prepared = read_scan_receipt(self.run / "derived-preparation.json")
        self.barrier = read_scan_receipt(self.run / "global/receipt.json")
        rows = stock["pool"]["results"]
        self.source_id, self.input_id = prepared["source"]["source_id"], prepared["input_id"]
        self.original_code = prepared["source"].get("code")
        self.parts = {row["code"]: checked_path(Path(row["output_path"])) for row in rows}
        self.codes = tuple(sorted(self.parts))
        if (
            stock.get("phase") != "full_stock_checkpoints"
            or stock["pool"].get("complete") is not True
            or len(self.codes) != len(rows)
            or len(rows) != prepared["ordinary_reference_n"]
            or self.barrier.get("complete") is not True
            or set(self.barrier["global_files"]) != set(self.codes)
            or self.barrier["source_id"] != self.source_id
            or self.barrier["input_id"] != self.input_id
        ):
            raise ValueError("original completed stock/global coverage differs")
        self.calendar = pd.DatetimeIndex(pd.to_datetime(self.barrier["calendar"]))
        self.existing: dict[tuple[str, str], Path] = {}
        label_pins: list[dict[str, str]] = []
        for path in sorted((self.run / "analysis/event-parts").glob("*/receipt.json")):
            if path.parent.name.startswith("."):
                continue
            saved = read_json(path)
            identity = saved["identity"]
            if (
                saved.get("complete") is not True
                or identity["source_id"] != self.source_id
                or identity["input_id"] != self.input_id
                or identity["code"] not in self.parts
            ):
                raise ValueError("original completed event metadata differs")
            key = identity["target"], identity["code"]
            if key in self.existing:
                raise ValueError("ambiguous completed event projection")
            self.existing[key] = path.parent
            label_pins.append(identity["shared_pins"]["labels"])
        if not label_pins or any(pin != label_pins[0] for pin in label_pins):
            raise ValueError("original label identity requires consistent retained event metadata")
        self.label_pin = label_pins[0]
        self._last_code: str | None = None
        self._last_stock: dict[str, pd.DataFrame] = {}
        self._sidecars: dict[str, pd.DataFrame] = {}
        self._industries: dict[str, str] | None = None
        self._target_roots: dict[str, Path] = {}
        self._cached_codes: dict[str, set[str]] = {}
        self.workers = 1
        self.projection_build_allowed = True
        handoff = read_scan_receipt(self.run / "shared-price-handoff.json")
        reference = handoff["reference"]
        self.shared_record = {
            "family": "adjusted-daily-v1",
            "generation": reference["generation"],
            "as_of": reference["cutoff"],
            "basis": reference["basis"],
            "use": "original price lineage; continuation reads completed original derivatives",
        }
        LOGGER.info("Original inputs stocks=%d reusable_event_parts=%d generation=%s", len(self.codes), len(self.existing), reference["generation"])

    def stock(self, code: str) -> dict[str, pd.DataFrame]:
        if self._last_code != code:
            directory = self.parts[code]
            tables = {name: read_frame(directory / f"{name}.parquet") for name in TABLES}
            if any(not tables[name].index.equals(self.calendar) for name in ("indicators", "common_values", "universe", "pattern_states", "controls")):
                raise ValueError("original stock calendar differs")
            # Event binding only consumes prices.index and quality_reason.
            # Both are already present verbatim in the original indicators.
            tables["prices"] = tables["indicators"]
            self._last_code, self._last_stock = code, tables
        return self._last_stock

    def global_values(self, code: str) -> pd.DataFrame:
        result = read_frame(Path(self.barrier["global_files"][code]["path"]))
        if not result.index.equals(self.calendar):
            raise ValueError("original global calendar differs")
        return result

    def sidecar(self, name: str) -> pd.DataFrame:
        if name not in self._sidecars:
            self._sidecars[name] = read_frame(Path(self.barrier["sidecars"][name]["path"]))
        return self._sidecars[name]

    @property
    def industries(self) -> dict[str, str]:
        if self._industries is None:
            self._industries = {
                f"TW:{code}": str(read_frame(directory / "common_values.parquet", columns=["industry_ref"])["industry_ref"].iloc[0])
                for code, directory in self.parts.items()
            }
        return self._industries

    def _read_bound(self, directory: Path) -> EventTables:
        daily, formula = (read_frame(directory / f"{name}.parquet") for name in ("daily_groups", "formula_groups"))
        states: list[dict[str, pd.Series]] = []
        for frame in (daily, formula):
            if "t0" in frame:
                if frame.t0.tolist() != self.calendar.strftime("%Y-%m-%d").tolist():
                    raise ValueError("projection daily calendar differs")
                frame = frame.drop(columns="t0")
            if len(frame) != len(self.calendar):
                raise ValueError("projection daily row count differs")
            frame.index = self.calendar
            states.append({str(name): cast(pd.Series, frame[name]) for name in frame})
        return EventTables(
            events=read_frame(directory / "events.parquet"),
            conditions=read_frame(directory / "conditions.parquet"),
            group_memberships=read_frame(directory / "group_memberships.parquet"),
            daily_groups=states[0],
            formula_groups=states[1],
        )

    def bound(self, target: str, code: str) -> EventTables:
        prior = self.existing.get((target, code))
        if prior is not None:
            return self._read_bound(prior)
        if code in self._cached_codes.get(target, set()):
            directory = self._target_roots[target] / code
            if all((directory / f"{name}.parquet").is_file() for name in EVENT_FILES):
                return self._read_bound(directory)
        if getattr(self, "projection_build_allowed", True) is False:
            raise ValueError("read-only projection cache is missing a stock")
        return build_event_tables(
            target,
            self.stock(code),
            self.global_values(code),
            security_id=f"TW:{code}",
            definition_id=self.source_id,
            input_id=self.input_id,
            base_label_version_id=self.label_pin["version_id"],
            base_label_manifest_sha256=self.label_pin["manifest_sha256"],
            classification_cache=ConditionClassificationCache(),
        )

    def attach_target(self, target: str, output: Path, *, require_complete: bool = False) -> None:
        """Attach to an existing projection cache without changing it."""
        output = checked_path(output)
        if not output.is_relative_to(self.temporary):
            raise ValueError("projection cache must be below this continuation's temporary root")
        progress_path = output / "progress.json"
        if not progress_path.is_file():
            raise ValueError("temporary projection progress is missing")
        expected = {"target": target, "source_id": self.source_id, "input_id": self.input_id}
        progress = read_json(progress_path)
        if not isinstance(progress, dict):
            raise ValueError("temporary projection progress is invalid")
        if any(progress.get(key) != value for key, value in expected.items()):
            raise ValueError("temporary projection scope differs")
        completed_value = progress.get("completed")
        if not isinstance(completed_value, list) or any(not isinstance(code, str) for code in completed_value):
            raise ValueError("temporary projection completion list is invalid")
        completed = set(completed_value)
        if not completed.issubset(self.codes):
            raise ValueError("temporary projection completion list contains unknown stocks")
        self._target_roots[target] = output
        self._cached_codes[target] = completed
        if require_complete:
            missing = [
                code
                for code in self.codes
                if (target, code) not in self.existing
                and (code not in completed or not all((output / code / f"{name}.parquet").is_file() for name in EVENT_FILES))
            ]
            if missing:
                raise ValueError(f"temporary projection cache is incomplete: {len(missing)} stocks")

    def write_projection(self, target: str, code: str, directory: Path) -> None:
        """Write one stock projection into its unique temporary staging directory."""
        directory = checked_path(directory)
        if not directory.is_relative_to(self.temporary):
            raise ValueError("projection cache must be below this continuation's temporary root")
        bound = self.bound(target, code)
        directory.mkdir(exist_ok=True)
        for name in EVENT_FILES:
            frame = getattr(bound, name)
            if not isinstance(frame, pd.DataFrame):
                frame = pd.DataFrame(frame)
                frame.insert(0, "t0", self.calendar.strftime("%Y-%m-%d"))
            write_frame(frame, directory / f"{name}.parquet", index=False)

    def cache_target(self, target: str, output: Path) -> Path:
        output = checked_path(output)
        if not output.is_relative_to(self.temporary):
            raise ValueError("projection cache must be below this continuation's temporary root")
        output.mkdir(parents=True, exist_ok=True)
        progress_path = output / "progress.json"
        expected = {"target": target, "source_id": self.source_id, "input_id": self.input_id}
        if progress_path.exists():
            self.attach_target(target, output)
            progress = read_json(progress_path)
        else:
            progress = {**expected, "completed": []}
            write_progress(progress_path, progress)
            self.attach_target(target, output)
        completed = set(progress["completed"])
        self._cached_codes[target] = completed
        pending = [
            code
            for code in self.codes
            if (target, code) not in self.existing and not (code in completed and all((output / code / f"{name}.parquet").is_file() for name in EVENT_FILES))
        ]

        def mark_completed(code: str) -> None:
            completed.add(code)
            write_progress(progress_path, {**expected, "completed": sorted(completed)})

        if self.workers > 1:
            from research_core.pattern_scan_local_parallel_v5 import project_in_parallel

            project_in_parallel(self, target, output, pending, workers=self.workers, on_completed=mark_completed)
        else:
            for number, code in enumerate(pending, 1):
                self.write_projection(target, code, output / code)
                mark_completed(code)
                if number == 1 or number % 50 == 0:
                    LOGGER.info("Target projection target=%s stock=%s position=%d/%d", target, code, number, len(pending))
        return output

    def holding(self, code: str, anchors: list[int]) -> pd.DataFrame:
        output = self.temporary / "holding"
        output.mkdir(exist_ok=True)
        path = output / f"{code}.parquet"
        security_id = f"TW:{code}"
        frame = _cached_holding(path, security_id, self.calendar, anchors, full=True)
        if frame is None:
            close = self.sidecar("close_matrix")
            industry = self.industries[security_id]
            peers = tuple(stock for stock in close if self.industries[stock] == industry)
            requested = {}
            for security in peers:
                events = read_frame(self.parts[security.removeprefix("TW:")] / "cohort_events.parquet", columns=["calendar_index"])
                requested[security] = sorted(set(int(value) for value in events.calendar_index))
            repair = [
                security
                for security in peers
                if security == security_id
                or _cached_holding(
                    output / f"{security.removeprefix('TW:')}.parquet", security, self.calendar, requested[security], full=False, exact_anchors=True
                )
                is None
            ]
            result = industry_holding(close, self.sidecar("jump_matrix"), self.industries, self.sidecar("benchmark"), self.sidecar("context"), peers, requested)
            for security in repair:
                destination = output / f"{security.removeprefix('TW:')}.parquet"
                staged = destination.with_name(f".{destination.name}-{uuid.uuid4().hex}.tmp")
                write_frame(result.loc[result.security_id.eq(security)].reset_index(drop=True), staged, index=False)
                os.replace(staged, destination)
            LOGGER.info("Holding peer block stocks=%d rows=%d repaired_peers=%d", len(peers), len(result), len(repair))
            frame = _cached_holding(path, security_id, self.calendar, anchors, full=True)
            if frame is None:
                raise ValueError("holding cache lacks an original cohort anchor or valid fixed clock")
        result = frame.loc[frame.calendar_index.isin(anchors)].copy()
        if set(anchors) != set(result.calendar_index):
            raise ValueError("holding cache lacks an original cohort anchor")
        return result
