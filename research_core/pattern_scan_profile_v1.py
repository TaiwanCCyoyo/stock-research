"""Fail-closed validation of measured fixed-source stock and global profiles."""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from research_core.artifact_store import relative_name
from research_core.pattern_scan_barrier_v1 import verified_parts
from research_core.pattern_scan_execution_v1 import verify_source

LOGGER = logging.getLogger(__name__)
MAX_MEMORY = 6 * 1024**3
HOST_RESERVE = 4 * 1024**3
SHA256 = re.compile(r"[0-9a-f]{64}")
GLOBAL_PHASES = (
    "representative_global_barrier",
    "representative_event_binding",
    "representative_one_group_integer_feed",
    "representative_one_group_summary_serialization",
    "representative_first_by_date_followup",
    "representative_first_by_date_holding",
    "representative_followup_summary_serialization",
)


def _integer(value: Any, label: str, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"invalid profile integer: {label}")
    return value


def _finite(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError(f"invalid finite profile measurement: {label}")
    return float(value)


def _codes(value: Any, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(code, str) or not code or code != code.strip() for code in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"invalid profile stock codes: {label}")
    return sorted(value)


def _phase(receipt: Any, expected: str) -> None:
    if not isinstance(receipt, dict) or receipt.get("phase") != expected:
        raise ValueError(f"missing measured profile phase: {expected}")
    _finite(receipt["wall_seconds"], expected + " wall")
    _finite(receipt["cpu_seconds"], expected + " cpu")
    native = receipt["native"]
    if native is not None:
        working = _integer(native["working_set_after_bytes"], expected + " working set")
        _integer(native["peak_working_set_process_lifetime_bytes"], expected + " lifetime peak", working)
        if not isinstance(native["io_delta"], dict) or not native["io_delta"]:
            raise ValueError("native I/O measurement must retain observed counters")
        for value in native["io_delta"].values():
            _integer(value, expected + " native I/O")


def _stock_identity(row: dict[str, Any], source: dict[str, Any], input_id: str) -> dict[str, Any]:
    if (
        row.get("schema") != "pattern-scan-stock-receipt.v1"
        or row.get("complete") is not True
        or row["source_id"] != source["source_id"]
        or row["input_id"] != input_id
    ):
        raise ValueError("profile stock receipt source/input or completion differs")
    phases = row["measurements"]
    expected_phases = ("load_prepared", "stock_calculation", "serialize")
    if not isinstance(phases, list) or len(phases) != len(expected_phases):
        raise ValueError("profile requires complete stock phase measurements")
    for phase, expected in zip(phases, expected_phases, strict=True):
        _phase(phase, expected)
    if not isinstance(row["rows"], dict) or not row["rows"] or not isinstance(row["artifacts"], list) or not row["artifacts"]:
        raise ValueError("profile stock row and artifact identities required")
    for count in row["rows"].values():
        _integer(count, "stock table rows")
    names = []
    for artifact in row["artifacts"]:
        names.append(relative_name(artifact["path"]))
        _integer(artifact["bytes"], "artifact bytes")
        if not isinstance(artifact["sha256"], str) or not SHA256.fullmatch(artifact["sha256"]):
            raise ValueError("invalid profile artifact digest")
    if len(names) != len(set(names)):
        raise ValueError("duplicate profile artifact")
    return {"code": row["code"], "artifacts": sorted(row["artifacts"], key=lambda value: value["path"]), "rows": row["rows"]}


def _global(preflight: dict[str, Any], source: dict[str, Any], input_id: str, measured_codes: list[str]) -> None:
    if (
        preflight.get("schema") != "pattern-scan-preflight.v1"
        or preflight.get("complete") is not True
        or preflight["source_id"] != source["source_id"]
        or preflight["input_id"] != input_id
    ):
        raise ValueError("global preflight source/input or completion differs")
    codes = _codes(preflight["security_codes"], "global preflight")
    if len(codes) > 4 or not set(codes).issubset(measured_codes):
        raise ValueError("global preflight must use measured representative stocks")
    phases = preflight["phases"]
    if not isinstance(phases, list) or len(phases) != len(GLOBAL_PHASES):
        raise ValueError("all global preflight measured phases required")
    for phase, name in zip(phases, GLOBAL_PHASES, strict=True):
        _phase(phase, name)
    work = preflight["work_sizes"]
    required = (
        "representative_security_n",
        "calendar_n",
        "stock_calendar_rows",
        "bound_targets_n",
        "summary_groups_n",
        "summary_cell_n",
        "summary_event_n",
        "membership_rows",
        "stock_cell_year_rows",
        "dense_numeric_bytes",
        "sample_event_n",
        "event_cap_per_stock",
        "followup_flag_rows",
        "landmark_rows",
        "holding_rows",
        "followup_summary_rows",
        "serialized_bytes",
    )
    for name in required:
        _integer(work[name], "global " + name)
    if (
        work["representative_security_n"] != len(codes)
        or work["calendar_n"] <= 0
        or work["stock_calendar_rows"] != len(codes) * work["calendar_n"]
        or work["bound_targets_n"] != 12
        or work["summary_groups_n"] != 1
        or work["summary_horizons"] != [126]
        or work["summary_cell_n"] <= 0
        or work["dense_numeric_bytes"] <= 0
        or work["serialized_bytes"] <= 0
        or work["event_cap_per_stock"] != 4
    ):
        raise ValueError("global preflight measured work sizes are inconsistent")
    samples = preflight["sample_event_ids"]
    if not isinstance(samples, dict) or set(samples) != set(codes):
        raise ValueError("global sample identity must cover measured stocks")
    observed = []
    for ids in samples.values():
        if not isinstance(ids, list) or len(ids) > 4 or any(not isinstance(identifier, str) or not identifier for identifier in ids):
            raise ValueError("invalid global sampled event identities")
        observed.extend(ids)
    if len(observed) != len(set(observed)) or len(observed) != work["sample_event_n"] or work["sample_event_n"] > work["summary_event_n"]:
        raise ValueError("global sampled event work count differs")
    if work["holding_rows"] != work["sample_event_n"]:
        raise ValueError("global holding work does not match selected anchors")
    artifacts = preflight["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("measured global serialized artifact descriptors required")
    names = []
    serialized = 0
    for artifact in artifacts:
        names.append(relative_name(artifact["path"]))
        serialized += _integer(artifact["bytes"], "global serialized bytes")
        if not isinstance(artifact["sha256"], str) or not SHA256.fullmatch(artifact["sha256"]):
            raise ValueError("invalid global serialized artifact digest")
    if len(names) != len(set(names)) or serialized != work["serialized_bytes"]:
        raise ValueError("global serialized work count differs from descriptors")


def validate_profile(profile: dict[str, Any], *, source: dict[str, Any], input_id: str | None = None) -> None:
    """Validate current pins, all measured modes and bounded selected limits."""
    try:
        _validate(profile, source=source, input_id=input_id)
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError(f"malformed measured pattern-scan profile: {error}") from error


def _validate(profile: dict[str, Any], *, source: dict[str, Any], input_id: str | None) -> None:
    verify_source(source)
    if (
        profile.get("schema") != "pattern-scan-resource-profile.v1"
        or profile.get("source_id") != source["source_id"]
        or profile.get("same_file_identities") is not True
        or type(profile.get("serial_reference_workers")) is not int
        or profile["serial_reference_workers"] != 1
    ):
        raise ValueError("measured same-source resource profile required")
    observed_input = profile["input_id"]
    if not isinstance(observed_input, str) or not observed_input or (input_id is not None and observed_input != input_id):
        raise ValueError("profile input identity differs")
    codes = _codes(profile["codes"], "profile")
    selected = profile["selected"]
    cap = _integer(selected["memory_cap_bytes"], "selected memory", 1, MAX_MEMORY)
    workers = _integer(selected["workers"], "selected workers", 1, 4)
    batch = _integer(selected["stocks_per_process"], "selected batch", 1, 8)
    estimate = _integer(selected["estimated_worker_bytes"], "selected estimate", 1, cap)
    timeout = _finite(selected["timeout_seconds"], "selected timeout", positive=True)
    if (
        timeout >= 86400
        or selected["inflight_processes"] != workers
        or type(selected["inflight_processes"]) is not int
        or type(selected["active_stock_calculations_per_process"]) is not int
        or selected["active_stock_calculations_per_process"] != 1
        or workers * estimate > cap
    ):
        raise ValueError("selected profile limits are not admissible")
    pools = profile["profiles"]
    if not isinstance(pools, list) or len(pools) != 3:
        raise ValueError("measured 1/2/4-worker profiles required")
    modes, peaks, baseline_estimates = [], [], []
    expected = None
    for pool in pools:
        mode = _integer(pool["workers"], "measured workers", 1, 4)
        modes.append(mode)
        if (
            pool.get("schema") != "pattern-scan-pool.v1"
            or pool.get("complete") is not True
            or type(pool["memory_cap_bytes"]) is not int
            or pool["memory_cap_bytes"] != cap
            or type(pool["stocks_per_process"]) is not int
            or pool["stocks_per_process"] != batch
        ):
            raise ValueError("measured pool limits or completion differ")
        _integer(pool["peak_inflight"], "measured inflight", 1, mode)
        baseline_estimates.append(_integer(pool["estimated_worker_bytes"], "measured estimate", 1, cap // mode))
        available = _integer(pool["host_before"]["physical_available_bytes"], "measured host available", cap + HOST_RESERVE)
        _integer(pool["host_before"]["physical_total_bytes"], "measured host total", available)
        _phase(pool["coordinator_measurement"], "pool")
        results = pool["results"]
        if not isinstance(results, list) or _codes([row["code"] for row in results], "pool") != codes:
            raise ValueError("measured stock pool differs")
        identities = sorted((_stock_identity(row, source, observed_input) for row in results), key=lambda row: row["code"])
        if expected is None:
            expected = identities
        elif expected != identities:
            raise ValueError("serial/parallel artifact bytes or row identities differ")
        receipts = pool["workers_receipts"]
        if not isinstance(receipts, list) or not receipts:
            raise ValueError("native measured worker receipts required")
        flattened = []
        for receipt in receipts:
            if (
                receipt.get("schema") != "pattern-scan-worker.v1"
                or receipt.get("complete") is not True
                or not isinstance(receipt["results"], list)
                or not 1 <= len(receipt["results"]) <= batch
            ):
                raise ValueError("measured worker batch or completion differs")
            _phase(receipt["measurement"], "worker_total")
            _finite(receipt["process_wall_seconds"], "measured process duration")
            if receipt["job_memory"].get("scope") != "virtual memory committed across this owned Windows job":
                raise ValueError("native job peak must retain its committed-memory observation scope")
            limit = _integer(receipt["job_memory"]["limit_bytes"], "native job limit", 1, cap // mode)
            peaks.append(_integer(receipt["job_memory"]["peak_committed_bytes"], "native committed peak", 1, limit))
            flattened.extend(receipt["results"])
        if sorted(flattened, key=lambda row: row["code"]) != sorted(results, key=lambda row: row["code"]):
            raise ValueError("worker receipts do not exactly cover measured results")
        verified_parts(results, source=source, input_id=observed_input)
    if sorted(modes) != [1, 2, 4] or workers not in modes:
        raise ValueError("selected mode must be measured among unique 1/2/4 modes")
    peak = _integer(selected["observed_peak_job_committed_bytes"], "selected native peak", 1)
    if peak != max(peaks) or estimate < max(max(baseline_estimates), (max(peaks) * 5 + 3) // 4):
        raise ValueError("selected memory estimate lacks measured native peak headroom")
    _global(profile["global_preflight"], source, observed_input, codes)
    verify_source(source)
    LOGGER.debug("Validated measured scan profile stocks=%d workers=%d cap=%d", len(codes), workers, cap)
