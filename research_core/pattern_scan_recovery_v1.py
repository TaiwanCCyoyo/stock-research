"""Bounded recovery of L1 union outcomes from retained scan checkpoints."""

from __future__ import annotations

import logging
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core.artifact_store import object_digest, read_json, verify_files
from research_core.pattern_scan_conditions_v1 import classify_column
from research_core.pattern_scan_parquet_v1 import read_frame
from research_core.pattern_scan_projection_v1 import project_outcomes
from research_core.pattern_scan_receipt_io_v2 import read_scan_receipt
from research_core.pattern_scan_stock_v1 import EVENT_COLUMNS
from research_core.research_data_paths import checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample
from research_core.stock_feature_pool_v1 import runtime_identity

LOGGER = logging.getLogger(__name__)


def _legacy_checkpoint_label_pin(source: dict[str, Any], rows: dict[str, dict[str, Any]], input_id: str) -> dict[str, str]:
    """Match barrier_v1.checkpoint_label_entry's legacy v3 descriptor, not a new label definition."""
    required = {"schema", "code", "runtime", "platform", "numerical_thread_limits", "source_id"}
    body = {key: value for key, value in source.items() if key != "source_id"}
    code = source.get("code")
    if (
        set(source) != required
        or source.get("schema") != "pattern-scan-source.git.v2"
        or object_digest(body) != source.get("source_id")
        or not isinstance(code, dict)
        or set(code) != {"commit", "dirty"}
        or not isinstance(code.get("commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", code["commit"]) is None
        or type(code.get("dirty")) is not bool
        or not isinstance(source.get("runtime"), dict)
        or set(source["runtime"]) != {"python", "numpy", "pandas", "pyarrow"}
        or any(not isinstance(value, str) or not value for value in source["runtime"].values())
        or not isinstance(source.get("platform"), str)
        or not source["platform"]
        or not isinstance(source.get("numerical_thread_limits"), dict)
        or set(source["numerical_thread_limits"]) != {"OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS"}
        or any(not isinstance(value, str) or not value for value in source["numerical_thread_limits"].values())
    ):
        raise ValueError("invalid historical Git source identity")
    labels = {}
    for stock_code, row in sorted(rows.items()):
        matches = [record for record in row["artifacts"] if record.get("path") == "base_labels.parquet"]
        if len(matches) != 1:
            raise ValueError("checkpoint requires exactly one base-label descriptor")
        labels[stock_code] = matches[0]
    digest = object_digest({"schema": "pattern-scan-label-checkpoints.v3", "source_id": source["source_id"], "input_id": input_id, "labels": labels})
    return {"version_id": f"checkpoint-only:{digest}", "manifest_sha256": digest}


class _Reads:
    """Track observations for one run; path safety is rechecked at every gate."""

    def __init__(self, purpose: str = "input") -> None:
        if purpose not in {"input", "output"}:
            raise ValueError("observation purpose must be input or output")
        self.purpose = purpose
        self.observed: dict[Path, tuple[int, ...]] = {}
        self._directories: set[Path] = set()
        self._ancestors: dict[Path, tuple[int, int, int]] = {}
        self.metrics = {"full_sweeps": 0, "scoped_sweeps": 0, "file_observations": 0, "directory_observations": 0, "ancestor_observations": 0}

    def _directory(self, path: Path) -> tuple[int, int, int]:
        info = path.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
        ):
            raise ValueError(f"linked/reparse or non-directory ancestor forbidden: {path}")
        identity = (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))
        previous = self._ancestors.setdefault(path, identity)
        if previous != identity:
            raise ValueError(f"{self.purpose} ancestor changed: {path}")
        self.metrics["ancestor_observations"] += 1
        return identity

    def observe(self, path: Path) -> None:
        path = checked_path(path)
        for ancestor in path.parents:
            self._directory(ancestor)
        stamp: tuple[int, ...]
        if path in self._directories:
            stamp = self._directory(path)
            self.metrics["directory_observations"] += 1
        else:
            info = path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink > 1
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
            ):
                raise ValueError(f"linked/reparse or non-file input forbidden: {path}")
            stamp = (info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))
            self.metrics["file_observations"] += 1
        if path in self.observed and self.observed[path] != stamp:
            raise ValueError(f"recovery {self.purpose} changed: {path}")
        self.observed[path] = stamp

    def observe_directory(self, path: Path) -> None:
        path = checked_path(path)
        if path in self.observed and path not in self._directories:
            raise ValueError(f"observed file cannot become directory: {path}")
        self._directories.add(path)
        self.observe(path)

    def json(self, path: Path, *, scan: bool = False) -> dict[str, Any]:
        self.observe(path)
        value = read_scan_receipt(path) if scan else read_json(path)
        self.observe(path)
        return value

    def verify(self, root: Path, records: list[dict[str, Any]]) -> None:
        for record in records:
            self.observe(root / record["path"])
        verify_files(root, records)
        for record in records:
            self.observe(root / record["path"])

    def frame(self, root: Path, record: dict[str, Any], *, columns: list[str] | None = None) -> pd.DataFrame:
        self.verify(root, [record])
        path = root / record["path"]
        result = read_frame(path, **({"columns": columns} if columns is not None else {}))
        self.observe(path)
        return result

    def unchanged(self, paths: set[Path] | None = None) -> None:
        if paths is None:
            self.metrics["full_sweeps"] += 1
            selected = tuple(self.observed)
        else:
            self.metrics["scoped_sweeps"] += 1
            selected = tuple(Path(path).absolute() for path in paths)
            if any(path not in self.observed for path in selected):
                raise ValueError("scoped check requires already observed paths")
        for path in selected:
            self.observe(path)


@dataclass
class RecoveryInventory:
    root: Path
    requested_codes: tuple[str, ...]
    calendar: pd.DatetimeIndex
    rows: dict[str, dict[str, Any]]
    barrier: dict[str, Any]
    source_id: str
    input_id: str
    label_pin: dict[str, str]
    retained: dict[str, tuple[Path, dict[str, Any]]]
    measurement: dict[str, Any]
    runtime_audit: dict[str, Any]
    _reads: _Reads


@dataclass(frozen=True)
class RecoveryStock:
    events: pd.DataFrame
    conditions: pd.DataFrame
    memberships: pd.DataFrame
    markets: pd.Series
    audit: dict[str, Any]


def load_recovery_inventory(
    root: Path,
    *,
    requested_codes: tuple[str, ...],
    expected_input_id: str,
    expected_source_id: str,
    expected_label_version_id: str,
    expected_calendar_n: int,
    expected_stock_n: int,
    expected_retained_n: int,
) -> RecoveryInventory:
    """Verify ancestry and all retained L1 payload hashes, without reading their rows."""
    if (
        not isinstance(requested_codes, tuple)
        or not 1 <= len(requested_codes) <= 5
        or any(not isinstance(c, str) or not c.strip() for c in requested_codes)
        or len(set(requested_codes)) != len(requested_codes)
    ):
        raise ValueError("requested_codes must contain one to five unique stock codes")
    before = resource_sample()
    root = checked_path(root)
    reads = _Reads()
    stock = reads.json(root / "phase-stock-result.json", scan=True)
    prepared = reads.json(root / "derived-preparation.json", scan=True)
    barrier = reads.json(root / "global" / "receipt.json", scan=True)
    source = prepared["source"]
    if source["source_id"] != expected_source_id or prepared["input_id"] != expected_input_id:
        raise ValueError("fixed source/input identity differs")
    items = stock["pool"]["results"]
    rows = {row["code"]: row for row in items}
    if (
        stock.get("phase") != "full_stock_checkpoints"
        or stock["pool"].get("complete") is not True
        or len(rows) != len(items)
        or len(rows) != expected_stock_n
        or not set(requested_codes).issubset(rows)
    ):
        raise ValueError("stock pool or requested codes differ")
    if (
        barrier.get("complete") is not True
        or barrier["source_id"] != expected_source_id
        or barrier["input_id"] != expected_input_id
        or set(barrier["global_files"]) != set(rows)
        or prepared["ordinary_reference_n"] != len(rows)
        or prepared["calendar_n"] != expected_calendar_n
    ):
        raise ValueError("global ancestry or pool differs")
    calendar = pd.DatetimeIndex(pd.to_datetime(barrier["calendar"]))
    if (
        len(calendar) != expected_calendar_n
        or calendar.tz is not None
        or calendar.hasnans
        or not calendar.is_unique
        or not calendar.is_monotonic_increasing
        or any(x != x.normalize() for x in calendar)
    ):
        raise ValueError("invalid fixed calendar")
    for code, row in rows.items():
        directory = checked_path(Path(row["output_path"]))
        if (
            not directory.is_relative_to(root / "parts")
            or reads.json(directory / "receipt.json") != row
            or row.get("complete") is not True
            or row["source_id"] != expected_source_id
            or row["input_id"] != expected_input_id
        ):
            raise ValueError("stock receipt ancestry differs")
    pin = _legacy_checkpoint_label_pin(source, rows, expected_input_id)
    if pin["version_id"] != expected_label_version_id:
        raise ValueError("checkpoint label identity differs")
    retained: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted((root / "analysis" / "event-parts").glob("*/receipt.json")):
        receipt = reads.json(path)
        identity = receipt.get("identity", {})
        if identity.get("target") != "L1":
            continue
        code = identity.get("code")
        if code not in rows or code in retained:
            raise ValueError("unknown or duplicate retained L1 stock")
        expected = {
            "code": code,
            "target": "L1",
            "source_id": expected_source_id,
            "input_id": expected_input_id,
            "stock_request_id": rows[code]["request_id"],
            "global_sha256": barrier["global_files"][code]["sha256"],
            "shared_pins": {"labels": pin},
        }
        if receipt.get("schema") != "pattern-scan-event-part.v1" or receipt.get("complete") is not True or identity != expected:
            raise ValueError("retained L1 ancestry differs")
        names = {entry["path"] for entry in receipt["artifacts"]}
        if names != {"events.parquet", "conditions.parquet", "group_memberships.parquet", "daily_groups.parquet", "formula_groups.parquet"} or len(
            names
        ) != len(receipt["artifacts"]):
            raise ValueError("retained L1 payload inventory differs")
        reads.verify(path.parent, receipt["artifacts"])
        retained[code] = (path.parent, receipt)
    if len(retained) != expected_retained_n:
        raise ValueError("retained L1 stock coverage differs")
    reads.unchanged()
    measurement = phase_receipt("recovery_inventory", before, resource_sample())
    LOGGER.info("Verified recovery inventory stocks=%d retained_l1=%d", len(rows), len(retained))
    current_runtime = runtime_identity()
    runtime_audit = {
        "original_runtime": source["runtime"],
        "current_runtime": current_runtime,
        "original_platform": source["platform"],
        "current_platform": sys.platform,
        "runtime_differs": source["runtime"] != current_runtime or source["platform"] != sys.platform,
        "original_runtime_reexecuted": False,
    }
    return RecoveryInventory(
        root, requested_codes, calendar, rows, barrier, expected_source_id, expected_input_id, pin, retained, measurement, runtime_audit, reads
    )


def recover_stock(inventory: RecoveryInventory, code: str) -> RecoveryStock:
    """Project one approved stock and compare its saved L1 rows when available."""
    if code not in inventory.requested_codes:
        raise ValueError("stock is outside the approved pilot")
    overall_before = resource_sample()
    phase_before = overall_before
    reads = inventory._reads
    row = inventory.rows[code]
    directory = Path(row["output_path"])
    local_paths = {
        inventory.root / "phase-stock-result.json",
        inventory.root / "derived-preparation.json",
        inventory.root / "global" / "receipt.json",
        directory / "receipt.json",
    }
    if code in inventory.retained:
        local_paths.add(inventory.retained[code][0] / "receipt.json")
    reads.unchanged(local_paths)
    records = {entry["path"]: entry for entry in row["artifacts"]}
    if len(records) != len(row["artifacts"]):
        raise ValueError("duplicate stock artifacts")
    cohort = reads.frame(directory, records["cohort_events.parquet"])
    raw = cohort.loc[cohort.pattern_id.eq("L1") & cohort.cohort_id.eq("union"), list(EVENT_COLUMNS)].reset_index(drop=True)
    if not raw.security_id.eq(f"TW:{code}").all() or not raw.definition_id.eq(inventory.source_id).all() or not raw.input_id.eq(inventory.input_id).all():
        raise ValueError("L1 cohort identity differs")
    labels = reads.frame(directory, records["base_labels.parquet"])
    if not labels.security_id.eq(f"TW:{code}").all():
        raise ValueError("base-label stock identity differs")
    quality = reads.frame(directory, records["indicators.parquet"], columns=["quality_reason"])
    common = reads.frame(directory, records["common_values.parquet"])
    local_paths.update(directory / records[f"{name}.parquet"]["path"] for name in ("cohort_events", "base_labels", "indicators", "common_values"))
    if not quality.index.equals(inventory.calendar) or not common.index.equals(inventory.calendar):
        raise ValueError("stock calendar differs")
    dates = inventory.calendar.strftime("%Y-%m-%d").tolist()
    for name, expected in (("security_id", f"TW:{code}"), ("definition_id", inventory.source_id), ("input_id", inventory.input_id)):
        if name in common and not bool(common[name].eq(expected).all()):
            raise ValueError("common values identity differs")
    if "t0" in common and common.t0.tolist() != dates:
        raise ValueError("common values dates differ")
    if "calendar_index" in common and common.calendar_index.tolist() != list(range(len(dates))):
        raise ValueError("common values calendar positions differ")
    global_record = inventory.barrier["global_files"][code]
    global_path = checked_path(Path(global_record["path"]))
    if not global_path.is_relative_to(inventory.root / "global"):
        raise ValueError("global path outside retained root")
    descriptor = {"path": global_path.name, "bytes": global_path.stat().st_size, "sha256": global_record["sha256"]}
    global_frame = reads.frame(global_path.parent, descriptor, columns=["security_id", "t0", "calendar_index", "MKT"])
    local_paths.add(global_path)
    if (
        not global_frame.index.equals(inventory.calendar)
        or not global_frame.security_id.eq(f"TW:{code}").all()
        or global_frame.t0.tolist() != dates
        or global_frame.calendar_index.tolist() != list(range(len(dates)))
        or not global_frame.MKT.isin(("up", "down", "consolidation", "mixed", "unknown")).all()
    ):
        raise ValueError("global calendar or identity differs")
    now = resource_sample()
    measurements = [phase_receipt("checkpoint_verify_read", phase_before, now)]
    phase_before = now
    events = project_outcomes(
        raw,
        labels,
        cast(pd.Series, quality.quality_reason),
        base_label_version_id=inventory.label_pin["version_id"],
        base_label_manifest_sha256=inventory.label_pin["manifest_sha256"],
    )
    if len(events) != len(raw) * 2 or not events.horizon.isin((126, 252)).all() or not events.groupby("event_id").horizon.nunique().eq(2).all():
        raise ValueError("each event requires both fixed horizons")
    now = resource_sample()
    measurements.append(phase_receipt("event_projection", phase_before, now))
    phase_before = now
    selected = common.iloc[raw.calendar_index.to_numpy(dtype=int)].reset_index(drop=True)
    conditions = raw[["event_id"]].copy()
    for feature in ("G", "VOL_a"):
        values = selected[feature].astype(object)
        reason = selected.get(f"{feature}_unknown_reason", pd.Series(None, index=selected.index, dtype=object))
        applicable = selected.get(f"{feature}_applicable", pd.Series(True, index=selected.index, dtype=bool))
        classified = classify_column(feature, values, applicable=applicable, unknown_reason=reason)
        conditions[feature] = values
        for key in ("bin_id", "status", "reason"):
            conditions[f"{feature}_{'bin' if key == 'bin_id' else key}"] = classified[key]
    memberships = pd.DataFrame({"group_id": "pattern:union", "event_id": raw.event_id})
    now = resource_sample()
    measurements.append(phase_receipt("condition_classification", phase_before, now))
    phase_before = now
    parity = False
    if code in inventory.retained:
        saved_dir, receipt = inventory.retained[code]
        saved_records = {entry["path"]: entry for entry in receipt["artifacts"]}
        saved_memberships = reads.frame(saved_dir, saved_records["group_memberships.parquet"])
        ids = saved_memberships.loc[saved_memberships.group_id.eq("pattern:union"), "event_id"]
        if ids.duplicated().any() or set(ids) != set(raw.event_id):
            raise ValueError("retained union event identity differs")
        saved = reads.frame(saved_dir, saved_records["events.parquet"])
        saved = saved.loc[saved.event_id.isin(ids), list(events.columns)].sort_values(["event_id", "horizon"]).reset_index(drop=True)
        actual = events.sort_values(["event_id", "horizon"]).reset_index(drop=True)
        try:
            pd.testing.assert_frame_equal(actual, saved, check_dtype=False, check_exact=True)
        except AssertionError as exc:
            raise ValueError("retained L1 event parity differs") from exc
        saved_conditions = reads.frame(saved_dir, saved_records["conditions.parquet"])
        local_paths.update(saved_dir / saved_records[name]["path"] for name in ("group_memberships.parquet", "events.parquet", "conditions.parquet"))
        saved_conditions = saved_conditions.loc[saved_conditions.event_id.isin(ids), list(conditions.columns)].sort_values("event_id").reset_index(drop=True)
        try:
            pd.testing.assert_frame_equal(conditions.sort_values("event_id").reset_index(drop=True), saved_conditions, check_dtype=False, check_exact=True)
        except AssertionError as exc:
            raise ValueError("retained L1 condition parity differs") from exc
        parity = True
        now = resource_sample()
        measurements.append(phase_receipt("retained_parity", phase_before, now))
    reads.unchanged(local_paths)
    markets = pd.Series(global_frame.MKT.to_numpy(), index=global_frame.t0)
    audit = {
        "code": code,
        "source": "shared_project_outcomes",
        "retained_part_present": code in inventory.retained,
        "historical_parity_verified": parity,
        "validation": "reprojection_and_retained_event_condition_parity" if parity else "reprojection_only_no_historical_event_golden",
        "event_count": len(raw),
        "projection_row_count": len(events),
        "payload_verified": True,
        "measurements": measurements,
        "overall_measurement": phase_receipt("recover_stock", overall_before, resource_sample()),
    }
    LOGGER.info("Recovered L1 stock=%s events=%d historical_parity=%s", code, len(raw), parity)
    return RecoveryStock(events, conditions, memberships, markets, audit)
