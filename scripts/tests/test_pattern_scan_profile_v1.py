"""Invented profile receipts verify measured modes, native limits and work."""

from copy import deepcopy
from typing import Any
from unittest.mock import Mock

import pytest

from research_core import pattern_scan_profile_v1 as validation

SOURCE = {"source_id": "invented-source"}
INPUT_ID = "invented-input"
GIB = 1024**3


def phase(name: str) -> dict[str, Any]:
    return {"phase": name, "wall_seconds": 1.0, "cpu_seconds": 0.5, "native": None}


def stock(code: str) -> dict[str, Any]:
    return {
        "schema": "pattern-scan-stock-receipt.v1",
        "complete": True,
        "source_id": SOURCE["source_id"],
        "input_id": INPUT_ID,
        "code": code,
        "artifacts": [{"path": "prices.parquet", "bytes": 20, "sha256": "a" * 64}],
        "rows": {"prices": 10},
        "measurements": [phase(name) for name in ("load_prepared", "stock_calculation", "serialize")],
    }


@pytest.fixture
def profile(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], Mock, Mock]:
    source_spy, parts_spy = Mock(), Mock(return_value={})
    monkeypatch.setattr(validation, "verify_source", source_spy)
    monkeypatch.setattr(validation, "verified_parts", parts_spy)
    codes = ["0001", "0020", "3010", "4000"]
    pools = []
    for workers in (1, 2, 4):
        rows = [stock(code) for code in codes]
        receipts = [
            {
                "schema": "pattern-scan-worker.v1",
                "complete": True,
                "results": [row],
                "measurement": phase("worker_total"),
                "process_wall_seconds": 2.0,
                "job_memory": {
                    "limit_bytes": 6 * GIB // workers,
                    "peak_committed_bytes": GIB,
                    "scope": "virtual memory committed across this owned Windows job",
                },
            }
            for row in rows
        ]
        pools.append({
            "schema": "pattern-scan-pool.v1",
            "complete": True,
            "workers": workers,
            "stocks_per_process": 1,
            "peak_inflight": workers,
            "memory_cap_bytes": 6 * GIB,
            "estimated_worker_bytes": GIB,
            "host_before": {"physical_available_bytes": 12 * GIB, "physical_total_bytes": 16 * GIB},
            "coordinator_measurement": phase("pool"),
            "workers_receipts": receipts,
            "results": rows,
        })
    global_preflight = {
        "schema": "pattern-scan-preflight.v1",
        "complete": True,
        "source_id": SOURCE["source_id"],
        "input_id": INPUT_ID,
        "security_codes": codes,
        "phases": [phase(name) for name in validation.GLOBAL_PHASES],
        "sample_event_ids": {code: [f"event-{code}"] for code in codes},
        "artifacts": [{"path": "invented.parquet", "bytes": 100, "sha256": "b" * 64}],
        "work_sizes": {
            "representative_security_n": 4,
            "calendar_n": 10,
            "stock_calendar_rows": 40,
            "bound_targets_n": 12,
            "summary_groups_n": 1,
            "summary_horizons": [126],
            "summary_cell_n": 20,
            "summary_event_n": 4,
            "membership_rows": 40,
            "stock_cell_year_rows": 30,
            "dense_numeric_bytes": 100,
            "sample_event_n": 4,
            "event_cap_per_stock": 4,
            "followup_flag_rows": 40,
            "landmark_rows": 20,
            "holding_rows": 4,
            "followup_summary_rows": 20,
            "serialized_bytes": 100,
        },
    }
    value = {
        "schema": "pattern-scan-resource-profile.v1",
        "source_id": SOURCE["source_id"],
        "input_id": INPUT_ID,
        "codes": codes,
        "same_file_identities": True,
        "serial_reference_workers": 1,
        "profiles": pools,
        "global_preflight": global_preflight,
        "selected": {
            "workers": 4,
            "stocks_per_process": 1,
            "inflight_processes": 4,
            "active_stock_calculations_per_process": 1,
            "memory_cap_bytes": 6 * GIB,
            "estimated_worker_bytes": 5 * GIB // 4,
            "observed_peak_job_committed_bytes": GIB,
            "timeout_seconds": 60.0,
        },
    }
    return value, source_spy, parts_spy


def test_valid_profile_reverifies_source_and_every_measured_part_without_mutation(profile: tuple[dict[str, Any], Mock, Mock]) -> None:
    value, source_spy, parts_spy = profile
    before = deepcopy(value)
    validation.validate_profile(value, source=SOURCE, input_id=INPUT_ID)
    assert value == before
    assert source_spy.call_count == 2
    source_spy.assert_called_with(SOURCE)
    assert parts_spy.call_count == 3
    for call, pool in zip(parts_spy.call_args_list, value["profiles"], strict=True):
        assert call.args == (pool["results"],)
        assert call.kwargs == {"source": SOURCE, "input_id": INPUT_ID}


def test_omitted_expected_input_still_binds_observed_fixed_input(profile: tuple[dict[str, Any], Mock, Mock]) -> None:
    value, _, parts_spy = profile
    validation.validate_profile(value, source=SOURCE)
    assert all(call.kwargs["input_id"] == INPUT_ID for call in parts_spy.call_args_list)


@pytest.mark.parametrize("boundary", ["source", "parts"])
def test_current_byte_verification_failure_is_not_masked(profile: tuple[dict[str, Any], Mock, Mock], boundary: str) -> None:
    value, source_spy, parts_spy = profile
    (source_spy if boundary == "source" else parts_spy).side_effect = ValueError("invented bytes drift")
    with pytest.raises(ValueError, match="invented bytes drift"):
        validation.validate_profile(value, source=SOURCE)


@pytest.mark.parametrize(
    "field,value",
    [
        ("workers", 3),
        ("workers", True),
        ("workers", 5),
        ("stocks_per_process", 9),
        ("stocks_per_process", 0),
        ("inflight_processes", 3),
        ("active_stock_calculations_per_process", 2),
        ("memory_cap_bytes", 6 * GIB + 1),
        ("memory_cap_bytes", True),
        ("estimated_worker_bytes", GIB),
        ("estimated_worker_bytes", 2 * GIB),
        ("observed_peak_job_committed_bytes", GIB - 1),
        ("timeout_seconds", float("nan")),
        ("timeout_seconds", float("inf")),
        ("timeout_seconds", 0),
        ("timeout_seconds", 86400),
    ],
)
def test_selected_limits_must_be_measured_bounded_and_have_native_headroom(profile: tuple[dict[str, Any], Mock, Mock], field: str, value: Any) -> None:
    measured, _, _ = profile
    measured["selected"][field] = value
    with pytest.raises(ValueError):
        validation.validate_profile(measured, source=SOURCE)


@pytest.mark.parametrize(
    "damage",
    [
        "hash",
        "rows",
        "bytes",
        "code",
        "duplicate",
        "missing",
        "mode",
        "cap",
        "batch",
        "complete",
        "phase",
        "native_peak",
        "host_reserve",
        "worker_subset",
        "worker_complete",
        "native_scope",
    ],
)
def test_pool_identity_measurements_and_native_receipts_fail_closed(profile: tuple[dict[str, Any], Mock, Mock], damage: str) -> None:
    measured, _, _ = profile
    pool = measured["profiles"][1]
    row = pool["results"][0]
    if damage == "hash":
        row["artifacts"][0]["sha256"] = "b" * 64
    elif damage == "rows":
        row["rows"]["prices"] = 11
    elif damage == "bytes":
        row["artifacts"][0]["bytes"] = 21
    elif damage == "code":
        row["code"] = "foreign"
    elif damage == "duplicate":
        pool["results"].append(row)
    elif damage == "missing":
        pool["results"].pop()
    elif damage == "mode":
        pool["workers"] = 1
    elif damage == "cap":
        pool["memory_cap_bytes"] = 5 * GIB
    elif damage == "batch":
        pool["stocks_per_process"] = 2
    elif damage == "complete":
        pool["complete"] = False
    elif damage == "phase":
        row["measurements"].pop()
    elif damage == "native_peak":
        pool["workers_receipts"][0]["job_memory"]["peak_committed_bytes"] = 4 * GIB
    elif damage == "host_reserve":
        pool["host_before"]["physical_available_bytes"] = 10 * GIB - 1
    elif damage == "worker_subset":
        pool["workers_receipts"].pop()
    elif damage == "native_scope":
        pool["workers_receipts"][0]["job_memory"]["scope"] = "working_set"
    else:
        pool["workers_receipts"][0]["complete"] = False
    with pytest.raises(ValueError):
        validation.validate_profile(measured, source=SOURCE)


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "source",
        "input",
        "phase_missing",
        "nan_wall",
        "inf_cpu",
        "missing_work",
        "grid",
        "sample_count",
        "sample_cap",
        "foreign_code",
        "holding_count",
        "serialized_count",
    ],
)
def test_global_preflight_requires_complete_measured_work_and_honest_sizes(profile: tuple[dict[str, Any], Mock, Mock], damage: str) -> None:
    measured, _, _ = profile
    preflight = measured["global_preflight"]
    if damage == "missing":
        del measured["global_preflight"]
    elif damage in {"source", "input"}:
        preflight[damage + "_id"] = "different"
    elif damage == "phase_missing":
        preflight["phases"].pop()
    elif damage == "nan_wall":
        preflight["phases"][0]["wall_seconds"] = float("nan")
    elif damage == "inf_cpu":
        preflight["phases"][0]["cpu_seconds"] = float("inf")
    elif damage == "missing_work":
        del preflight["work_sizes"]["followup_flag_rows"]
    elif damage == "grid":
        preflight["work_sizes"]["stock_calendar_rows"] = 41
    elif damage == "sample_count":
        preflight["work_sizes"]["sample_event_n"] = 3
    elif damage == "sample_cap":
        preflight["sample_event_ids"]["0001"] = [f"event-{number}" for number in range(5)]
    elif damage == "foreign_code":
        preflight["security_codes"][0] = "foreign"
    elif damage == "serialized_count":
        preflight["work_sizes"]["serialized_bytes"] = 101
    else:
        preflight["work_sizes"]["holding_rows"] = 3
    with pytest.raises(ValueError):
        validation.validate_profile(measured, source=SOURCE)


@pytest.mark.parametrize("damage", ["wrong_input", "missing_source", "false_same_files", "no_modes", "bool_rows", "missing_native_peak", "malformed"])
def test_malformed_or_unbound_profiles_are_value_errors(profile: tuple[dict[str, Any], Mock, Mock], damage: str) -> None:
    measured, _, _ = profile
    if damage == "wrong_input":
        measured["input_id"] = "different"
    elif damage == "missing_source":
        del measured["source_id"]
    elif damage == "false_same_files":
        measured["same_file_identities"] = False
    elif damage == "no_modes":
        measured["profiles"] = []
    elif damage == "bool_rows":
        measured["profiles"][0]["results"][0]["rows"]["prices"] = True
    elif damage == "missing_native_peak":
        del measured["profiles"][0]["workers_receipts"][0]["job_memory"]["peak_committed_bytes"]
    else:
        measured["selected"] = None
    with pytest.raises(ValueError):
        validation.validate_profile(measured, source=SOURCE, input_id=INPUT_ID)
