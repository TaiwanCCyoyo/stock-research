"""Synthetic one-phase continuation protocol, native Job ownership and CLI."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core import pattern_scan_analysis_v1 as analysis
from research_core import pattern_scan_barrier_v1 as barrier_module
from research_core import pattern_scan_continuation_v4 as continuation
from research_core import pattern_scan_execution_v1 as execution
from research_core import pattern_scan_git_source_v2 as git_source
from research_core import pattern_scan_stock_v1 as stock_module
from research_core.artifact_store import canonical, describe_file, file_digest, object_digest, read_json, write_json
from research_core.research_data_paths import DataRoots
from scripts import continue_pattern_scan as cli

GIB = 1024**3


def _completed_analysis(case: dict[str, Any]) -> tuple[Path, Path, Path, Path]:
    executor = {
        "schema": git_source.SCHEMA,
        "code": case["executor"]["code"],
        "runtime": git_source.runtime_identity(),
        "platform": sys.platform,
        "numerical_thread_limits": git_source.NUMERICAL_THREADS,
    }
    case["executor"] = {**executor, "source_id": object_digest(executor)}
    request_path = _coordinator_request(case, "analysis")
    (case["run"] / continuation.ACTIVE).unlink()
    request = read_json(request_path)
    computed_path = case["run"] / "computed-results.json"
    write_json(
        computed_path,
        {
            "schema": "pattern-scan-computed-results.v3",
            "complete": True,
            "state": "computed_unpublished",
            "run_root": str(case["run"]),
            "source": case["source"],
            "input_id": "original-input",
            "provenance": {"executor": request["executor"], "stock_reference": request["stock_reference"], "shared_price_reference": request["reference"]},
        },
    )
    response_path = case["control"] / "response-analysis.json"
    write_json(
        response_path,
        {
            "schema": continuation.SCHEMA,
            "complete": True,
            "phase": "analysis",
            "request_id": object_digest(request),
            "source": case["source"],
            "executor": case["executor"],
            "input_id": "original-input",
            "results": {"computed_results": _pin(computed_path)},
            "result": {"expanded_stock_metadata": "must never be copied into bounded completion audit"},
        },
    )
    job_path = response_path.with_suffix(".job-memory.json")
    write_json(
        job_path,
        {
            "schema": "pattern-scan-continuation-job-memory.v4",
            "complete": True,
            "request_id": object_digest(request),
            "response_sha256": file_digest(response_path),
            "job_memory": {"limit_bytes": 3 * GIB, "peak_committed_bytes": 123456, "scope": "virtual memory committed across this owned Windows job"},
        },
    )
    return request_path, response_path, job_path, computed_path


def test_analysis_completion_retains_small_actual_evidence_and_reuses_without_current_code(
    case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, response, job, computed = _completed_analysis(case)
    monkeypatch.setattr(continuation, "assert_current_code", _forbidden)
    monkeypatch.setattr(continuation, "require_continuation_capacity", _forbidden)
    before = {path: (file_digest(path), path.stat().st_mtime_ns) for path in (request, response, job, computed)}
    descriptor = continuation.record_analysis_completion(request)
    audit_path = case["run"] / "analysis/audits/continuation-completion.json"
    assert descriptor == _pin(audit_path)
    audit = read_json(audit_path)
    assert audit["schema"] == "pattern-scan-continuation-completion.v4" and audit["complete"] is True
    assert audit["source"] == case["source"] and audit["executor"] == case["executor"]
    assert audit["input_id"] == "original-input" and audit["shared_reference"] == case["reference"]
    assert audit["computed_results"] == _pin(computed)
    assert audit["request"] == {"descriptor": _pin(request), "contents": read_json(request)}
    assert audit["job"] == {"descriptor": _pin(job), "contents": read_json(job)}
    assert audit["response"]["descriptor"] == _pin(response)
    assert "result" not in audit["response"]["identity"]
    assert "expanded_stock_metadata" not in audit_path.read_text(encoding="utf-8")
    assert audit["native_job_memory"]["peak_committed_bytes"] == 123456
    stamp = audit_path.stat().st_mtime_ns
    assert continuation.record_analysis_completion(request) == descriptor
    assert audit_path.stat().st_mtime_ns == stamp
    assert before == {path: (file_digest(path), path.stat().st_mtime_ns) for path in before}


@pytest.mark.parametrize(
    "damage",
    [
        "active",
        "request_phase",
        "request_source",
        "request_reference",
        "response_incomplete",
        "response_phase",
        "response_drift",
        "request_drift",
        "computed_drift",
        "computed_incomplete",
        "computed_source",
        "computed_input",
        "foreign_computed",
        "extra_result",
        "job_missing",
        "job_incomplete",
        "job_schema",
        "job_hash",
        "job_peak",
        "bad_executor",
        "foreign_stock",
        "computed_executor",
        "computed_reference",
        "computed_stock",
        "request_primary",
        "request_data",
    ],
)
def test_analysis_completion_refuses_partial_drift_or_foreign_evidence(case: dict[str, Any], damage: str) -> None:
    request, response, job, computed = _completed_analysis(case)
    if damage == "active":
        write_json(case["run"] / continuation.ACTIVE, {"owner": "still-active"})
    elif damage == "job_missing":
        job.unlink()
    elif damage in {"request_drift", "response_drift", "computed_drift"}:
        target = {"request_drift": request, "response_drift": response, "computed_drift": computed}[damage]
        target.write_bytes(target.read_bytes() + b" ")
        # Request identity is canonical; whitespace alone is not identity drift.
        if damage == "request_drift":
            packet = read_json(request)
            packet["active_owner"] = "foreign-request"
            request.write_bytes(canonical(packet))
    else:
        if damage.startswith("request_") or damage in {"bad_executor", "foreign_stock"}:
            target = request
        elif damage.startswith("computed_"):
            target = computed
        elif damage.startswith("job_"):
            target = job
        else:
            target = response
        packet = read_json(target)
        if damage in {"request_phase", "response_phase"}:
            packet["phase"] = "barrier"
        elif damage == "request_source":
            packet["source"] = {"source_id": "foreign-source"}
        elif damage == "request_reference":
            packet["reference"] = {"generation": "foreign-generation"}
        elif damage == "request_primary":
            packet["primary"] = str(case["control"])
        elif damage == "request_data":
            packet["data"] = str(case["control"])
        elif damage == "bad_executor":
            packet["executor"]["source_id"] = "invalid-executor"
        elif damage == "foreign_stock":
            foreign = case["control"] / "foreign-stock.json"
            foreign.write_bytes((case["run"] / "phase-stock-result.json").read_bytes())
            packet["stock_reference"] = _pin(foreign)
        elif damage in {"response_incomplete", "computed_incomplete", "job_incomplete"}:
            packet["complete"] = False
        elif damage == "computed_source":
            packet["source"] = {"source_id": "foreign-source"}
        elif damage == "computed_input":
            packet["input_id"] = "foreign-input"
        elif damage == "computed_executor":
            packet["provenance"]["executor"] = {"source_id": "foreign-executor"}
        elif damage == "computed_reference":
            packet["provenance"]["shared_price_reference"] = {"generation": "foreign-generation"}
        elif damage == "computed_stock":
            packet["provenance"]["stock_reference"] = {"path": "foreign-stock"}
        elif damage == "foreign_computed":
            foreign = case["control"] / "foreign-computed.json"
            foreign.write_bytes(computed.read_bytes())
            packet["results"]["computed_results"] = _pin(foreign)
        elif damage == "extra_result":
            packet["results"]["unexpected"] = _pin(computed)
        elif damage == "job_schema":
            packet["schema"] = "foreign-job"
        elif damage == "job_hash":
            packet["response_sha256"] = "0" * 64
        elif damage == "job_peak":
            packet["job_memory"]["peak_committed_bytes"] = 0
        target.write_bytes(canonical(packet))
        # Re-pin deliberately invalid semantics so rejection is not just stale hashes.
        if target == computed:
            packet = read_json(response)
            packet["results"]["computed_results"] = _pin(computed)
            response.write_bytes(canonical(packet))
        if target in {computed, response}:
            packet = read_json(job)
            packet["response_sha256"] = file_digest(response)
            job.write_bytes(canonical(packet))
    before = {path: (file_digest(path), path.stat().st_mtime_ns) for path in (request, response, job, computed) if path.exists()}
    with pytest.raises((ValueError, FileNotFoundError)):
        continuation.record_analysis_completion(request)
    assert not (case["run"] / "analysis/audits/continuation-completion.json").exists()
    assert before == {path: (file_digest(path), path.stat().st_mtime_ns) for path in before}


def test_analysis_completion_retry_refuses_changed_completed_evidence_without_replacing_audit(case: dict[str, Any]) -> None:
    request, response, job, _ = _completed_analysis(case)
    descriptor = continuation.record_analysis_completion(request)
    path = Path(descriptor["path"])
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    packet = read_json(job)
    packet["job_memory"]["peak_committed_bytes"] += 1
    job.write_bytes(canonical(packet))
    with pytest.raises(ValueError, match="existing handoff identity differs"):
        continuation.record_analysis_completion(request)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_analysis_completion_reads_large_handoff_with_scan_reader_without_retaining_large_body(
    case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = case["run"] / continuation.HANDOFF
    handoff.write_bytes(canonical({"reference": case["reference"], "large_handoff_only": "x" * (8 * 1024**2 + 1)}))
    assert handoff.stat().st_size > 8 * 1024**2
    request, _, _, _ = _completed_analysis(case)
    original_scan_reader = continuation.read_scan_receipt
    original_small_reader = continuation.read_json
    calls: list[Path] = []

    def scan_reader(path: Path) -> dict[str, Any]:
        calls.append(path)
        return original_scan_reader(path)

    def small_reader(path: Path) -> dict[str, Any]:
        assert path != handoff
        return original_small_reader(path)

    monkeypatch.setattr(continuation, "read_scan_receipt", scan_reader)
    monkeypatch.setattr(continuation, "read_json", small_reader)
    descriptor = continuation.record_analysis_completion(request)
    audit = Path(descriptor["path"])
    assert handoff in calls and descriptor["bytes"] < 100_000
    assert "large_handoff_only" not in audit.read_text(encoding="utf-8")
    assert read_json(audit)["shared_reference"] == case["reference"]


def _forbidden(*args: Any, **kwargs: Any) -> Any:
    pytest.fail("unexpected stock kernel, source calculation or native child")


def _pin(path: Path) -> dict[str, Any]:
    return {**describe_file(path.parent, path), "path": str(path)}


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    roots = DataRoots(primary, primary / "research_data")
    run = primary / ".tmp/pattern-scan-execution/completed-stock"
    run.mkdir(parents=True)
    control = run.parent / "continuation-control"
    control.mkdir()
    source = {"source_id": "original-stock-source", "code": {"commit": "a" * 40, "dirty": True}}
    executor = {"source_id": "current-executor", "code": {"commit": "b" * 40, "dirty": False}}
    reference = {"schema": "synthetic-reference", "generation": "fixed-generation"}
    write_json(run / "derived-preparation.json", {"source": source, "input_id": "original-input", "producer_fingerprint": {"inputs": {}}})
    write_json(run / "phase-stock-result.json", {"pool": {"results": [{"code": "0001"}]}})
    write_json(run / continuation.HANDOFF, {"reference": reference})
    capacity = tmp_path / "capacity.json"
    write_json(capacity, {"synthetic_capacity": True})
    calls: list[dict[str, Any]] = []

    def admission(path: Path, **kwargs: Any) -> dict[str, Any]:
        assert path == capacity and kwargs["run"] == run
        assert kwargs["phase"] in {"prices", "barrier", "events", "analysis"}
        assert kwargs["executor"] == executor
        assert kwargs["source_id"] == source["source_id"] and kwargs["input_id"] == "original-input"
        calls.append(kwargs)
        return {"phase_only": True, "full_study_admitted": False, "memory": {"job_limit_bytes": 3 * GIB}}

    monkeypatch.setattr(DataRoots, "validate_worktree", lambda *args: None)
    monkeypatch.setattr(continuation, "git_source_identity", lambda root: executor)
    monkeypatch.setattr(continuation, "assert_current_code", lambda actual, root: None if actual == executor else _forbidden())
    monkeypatch.setattr(continuation, "require_continuation_capacity", admission)
    monkeypatch.setattr(continuation, "shared_data_root", lambda: tmp_path / "shared")
    monkeypatch.setattr(continuation, "read_preparation_pins", lambda path: {"price_observation": {"calendar": {"dates": ["2010-01-04", "2026-10-12"]}}})

    def bind(root: Path, generation: str, calendar: pd.DatetimeIndex, **kwargs: Any) -> dict[str, Any]:
        assert generation == reference["generation"] and kwargs["expected_fingerprint"] == {"inputs": {}}
        return reference

    monkeypatch.setattr(continuation, "make_price_reference", bind)
    for name in ("_execute_stock_in_process", "worker_main", "run_requests"):
        monkeypatch.setattr(execution, name, _forbidden)
    monkeypatch.setattr(stock_module, "stock_phase", _forbidden)
    monkeypatch.setattr(continuation, "_MemoryBoundJob", _forbidden)
    return {
        "roots": roots,
        "run": run,
        "control": control,
        "capacity": capacity,
        "source": source,
        "executor": executor,
        "reference": reference,
        "admissions": calls,
    }


def _launch(case: dict[str, Any], phase: str = "barrier", **kwargs: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "run_id": case["run"].name,
        "control_id": case["control"].name,
        "phase": phase,
        "capacity_path": case["capacity"],
        "generation": "fixed-generation" if phase == "prices" else None,
        "calculation_authorized": True,
        "retirement_authorized": phase == "retire-prices",
        "timeout_seconds": 60,
    }
    arguments.update(kwargs)
    return continuation.launch(case["roots"], **arguments)


def _native_job(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, *, outcome: str = "success") -> list[Any]:
    events: list[Any] = []

    class Job:
        def __init__(self, limit: int) -> None:
            assert limit == 3 * GIB
            events.append(("limit", limit))

        def start(self, command: list[str], cwd: Path) -> Any:
            events.append(("start", command, cwd))
            assert command[1:3] == ["-c", continuation.BOOTSTRAP] and cwd == continuation.ROOT
            request_path = Path(command[-1])
            packet = read_json(request_path)
            marker = case["run"] / continuation.ACTIVE
            assert read_json(marker) == {"request_id": object_digest(packet), "owner": packet["active_owner"]}
            if outcome == "start_failure":
                raise RuntimeError("synthetic native Job start failure")
            if outcome in {"success", "foreign_marker"}:
                payload = request_path.parent / f"synthetic-{packet['phase']}-result.json"
                write_json(payload, {"synthetic": True, "phase": packet["phase"]})
                write_json(
                    request_path.with_name(f"response-{packet['phase']}.json"),
                    {
                        "schema": continuation.SCHEMA,
                        "complete": True,
                        "phase": packet["phase"],
                        "request_id": object_digest(packet),
                        "source": packet["source"],
                        "executor": packet["executor"],
                        "input_id": packet["input_id"],
                        "result": {"synthetic": True},
                        "results": {"synthetic": _pin(payload)},
                    },
                )
            if outcome == "foreign_marker":
                marker.write_bytes(canonical({"request_id": "another-request", "owner": "another-owner"}))

            class Process:
                returncode = None if outcome == "timeout" else 17 if outcome == "failure" else 0

                def poll(self) -> int | None:
                    return self.returncode

            return Process()

        def memory_receipt(self) -> dict[str, Any]:
            return {"limit_bytes": 3 * GIB, "peak_committed_bytes": 1024, "scope": "virtual memory committed across this owned Windows job"}

        def terminate_and_confirm(self) -> None:
            assert (case["run"] / continuation.ACTIVE).is_file()
            events.append("terminated")

        def close(self) -> None:
            assert (case["run"] / continuation.ACTIVE).is_file()
            events.append("closed")

    monkeypatch.setattr(continuation, "_MemoryBoundJob", Job)
    return events


@pytest.mark.parametrize("phase", continuation.PHASES)
def test_launch_exact_phase_reuses_completed_stocks_and_verifies_results_job_evidence(
    case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    stock_hash = file_digest(case["run"] / "phase-stock-result.json")
    events = _native_job(case, monkeypatch)
    result = _launch(case, phase)
    assert result["complete"] is True and result["phase"] == phase
    assert result["source"] == case["source"] and result["executor"] == case["executor"]
    assert result["coordinator_job_memory"]["peak_committed_bytes"] == 1024
    assert [row["phase"] for row in case["admissions"]] == ["prices" if phase == "retire-prices" else phase]
    assert events[-2:] == ["terminated", "closed"]
    assert not (case["run"] / continuation.ACTIVE).exists()
    assert file_digest(case["run"] / "phase-stock-result.json") == stock_hash
    before = {path: (file_digest(path), path.stat().st_mtime_ns) for path in case["control"].iterdir() if path.is_file()}
    monkeypatch.setattr(continuation, "_MemoryBoundJob", _forbidden)
    monkeypatch.setattr(continuation, "require_continuation_capacity", _forbidden)
    assert _launch(case, phase) == result
    assert before == {path: (file_digest(path), path.stat().st_mtime_ns) for path in before}


@pytest.mark.parametrize("change", ["timeout", "generation", "retirement", "capacity_path", "capacity_bytes"])
def test_retry_drift_never_starts_another_job(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, change: str) -> None:
    _native_job(case, monkeypatch)
    _launch(case)
    monkeypatch.setattr(continuation, "_MemoryBoundJob", _forbidden)
    kwargs: dict[str, Any] = {}
    if change == "timeout":
        kwargs["timeout_seconds"] = 61
    elif change == "generation":
        kwargs["generation"] = "another-generation"
    elif change == "retirement":
        kwargs["retirement_authorized"] = True
    elif change == "capacity_path":
        other = tmp_path / "other-capacity.json"
        write_json(other, {"synthetic": "different"})
        kwargs["capacity_path"] = other
    else:
        # Completed historical output is readable without requiring current
        # capacity bytes. Exercise the incomplete retry path for this drift.
        (case["control"] / "response-barrier.json").unlink()
        case["capacity"].write_bytes(b"changed capacity bytes")
    with pytest.raises(ValueError, match="retry|capacity"):
        _launch(case, **kwargs)


@pytest.mark.parametrize("outcome", ["failure", "timeout", "start_failure"])
def test_child_failures_and_timeout_terminate_confirm_close_before_marker_removal(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, outcome: str) -> None:
    events = _native_job(case, monkeypatch, outcome=outcome)
    if outcome == "timeout":
        clock = iter((0.0, 61.0))
        monkeypatch.setattr(continuation.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(continuation.time, "sleep", _forbidden)
    expected = TimeoutError if outcome == "timeout" else RuntimeError if outcome == "start_failure" else ValueError
    with pytest.raises(expected, match="timeout|exit=17|start failure"):
        _launch(case)
    assert events[-2:] == ["terminated", "closed"]
    assert not (case["run"] / continuation.ACTIVE).exists()
    assert (case["control"] / "request-barrier.json").is_file()
    assert not (case["control"] / "response-barrier.job-memory.json").exists()
    assert (case["run"] / "phase-stock-result.json").is_file()


@pytest.mark.parametrize("matching", [False, True])
def test_existing_active_marker_blocks_second_job_even_for_same_request(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, matching: bool) -> None:
    _native_job(case, monkeypatch, outcome="start_failure")
    with pytest.raises(RuntimeError, match="start failure"):
        _launch(case)
    packet = read_json(case["control"] / "request-barrier.json")
    token = {"request_id": object_digest(packet), "owner": packet["active_owner"]} if matching else {"request_id": "other", "owner": "other"}
    marker = case["run"] / continuation.ACTIVE
    write_json(marker, token)
    before = (file_digest(marker), marker.stat().st_mtime_ns)
    monkeypatch.setattr(continuation, "_MemoryBoundJob", _forbidden)
    with pytest.raises(ValueError, match="active"):
        _launch(case)
    assert (file_digest(marker), marker.stat().st_mtime_ns) == before


def test_teardown_does_not_remove_replaced_foreign_active_marker(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    events = _native_job(case, monkeypatch, outcome="foreign_marker")
    _launch(case)
    assert events[-2:] == ["terminated", "closed"]
    assert read_json(case["run"] / continuation.ACTIVE) == {"request_id": "another-request", "owner": "another-owner"}


@pytest.mark.parametrize("damage", ["result_bytes", "response_source", "job_response_hash", "job_limit", "job_peak", "job_scope", "missing_job"])
def test_completed_output_and_native_evidence_tampering_block_resume(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, damage: str) -> None:
    _native_job(case, monkeypatch)
    _launch(case)
    response = case["control"] / "response-barrier.json"
    memory = response.with_suffix(".job-memory.json")
    if damage == "result_bytes":
        record = next(iter(read_json(response)["results"].values()))
        Path(record["path"]).write_bytes(b"changed synthetic result")
    elif damage == "response_source":
        packet = read_json(response)
        packet["source"] = {"source_id": "wrong"}
        response.write_bytes(canonical(packet))
    elif damage == "missing_job":
        memory.unlink()
    else:
        packet = read_json(memory)
        if damage == "job_response_hash":
            packet["response_sha256"] = "0" * 64
        elif damage == "job_limit":
            packet["job_memory"]["limit_bytes"] = True
        elif damage == "job_peak":
            packet["job_memory"]["peak_committed_bytes"] = 4 * GIB
        else:
            packet["job_memory"]["scope"] = "not a native owned Job"
        memory.write_bytes(canonical(packet))
    monkeypatch.setattr(continuation, "_MemoryBoundJob", _forbidden)
    with pytest.raises(ValueError):
        _launch(case)


@pytest.mark.parametrize("timeout", [True, None, 0, -1, float("nan"), float("inf"), 8 * 3600 + 1])
def test_launch_timeout_is_finite_and_authorization_is_explicit(case: dict[str, Any], timeout: Any) -> None:
    with pytest.raises(ValueError, match="finite"):
        _launch(case, timeout_seconds=timeout)
    assert not list(case["control"].iterdir()) and not case["admissions"]
    with pytest.raises(PermissionError, match="approved"):
        _launch(case, calculation_authorized=False)
    with pytest.raises(PermissionError, match="retirement"):
        _launch(case, "retire-prices", retirement_authorized=False)


def _coordinator_request(case: dict[str, Any], phase: str) -> Path:
    path = case["control"] / f"request-{phase}.json"
    request = {
        "schema": continuation.SCHEMA,
        "phase": phase,
        "calculation_authorized": True,
        "retirement_authorized": phase == "retire-prices",
        "run_root": str(case["run"]),
        "control_root": str(case["control"]),
        "primary": str(case["roots"].primary),
        "data": str(case["roots"].data),
        "source": case["source"],
        "input_id": "original-input",
        "executor": case["executor"],
        "stock_reference": _pin(case["run"] / "phase-stock-result.json"),
        "reference": case["reference"],
        "price_handoff": None if phase == "prices" else _pin(case["run"] / continuation.HANDOFF),
        "capacity_path": str(case["capacity"]),
        "capacity_sha256": file_digest(case["capacity"]),
        "timeout_seconds": 60,
        "active_owner": "synthetic-active-owner",
    }
    write_json(path, request)
    write_json(case["run"] / continuation.ACTIVE, {"request_id": object_digest(request), "owner": request["active_owner"]})
    return path


def _full_events_case(case: dict[str, Any]) -> tuple[dict[str, Path], dict[str, Any]]:
    codes = [f"{index:04d}" for index in range(1, 1943)]
    calendar = [*pd.bdate_range("2010-01-04", periods=4109).strftime("%Y-%m-%d"), "2026-10-12"]
    case["reference"]["calendar"] = {"dates": calendar}
    (case["run"] / continuation.HANDOFF).write_bytes(canonical({"reference": case["reference"]}))
    (case["run"] / "phase-stock-result.json").write_bytes(canonical({"pool": {"results": [{"code": code} for code in codes]}}))
    parts = {code: case["run"] / "original-stock" / code for code in codes}
    barrier = {
        "synthetic_barrier": True,
        "source_id": case["source"]["source_id"],
        "input_id": "original-input",
        "calendar": calendar,
        "global_files": {code: {"synthetic_global_pin": code} for code in codes},
    }
    return parts, barrier


@pytest.mark.parametrize("phase", continuation.PHASES)
def test_coordinator_dispatches_exactly_one_phase_with_original_ancestry_and_current_executor(
    case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    if phase == "events":
        parts, full_barrier = _full_events_case(case)
    else:
        parts, full_barrier = {"0001": case["run"] / "synthetic-stock-part"}, {"synthetic_barrier": True}
    request_path = _coordinator_request(case, phase)
    request = read_json(request_path)
    called: list[str] = []
    original_stock = file_digest(case["run"] / "phase-stock-result.json")

    def price_handoff(run: Path, reference: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        assert phase == "prices" and run == case["run"] and reference == case["reference"]
        assert kwargs == {"executor": case["executor"], "calculation_authorized": True, "active_owner": request["active_owner"]}
        called.append("prices")
        write_json(run / continuation.EQUALITY, {"synthetic_equality": True})
        return {"complete": True}

    def retire(run: Path, descriptor: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        assert phase == "retire-prices" and run == case["run"]
        assert descriptor == {key: request["price_handoff"][key] for key in ("path", "sha256")}
        assert kwargs == {"retirement_authorized": True, "active_owner": request["active_owner"]}
        called.append("retire-prices")
        write_json(run / continuation.RETIRED, {"synthetic_retirement": True})
        return {"complete": True}

    def verified(results: list[dict[str, Any]], **kwargs: Any) -> dict[str, Path]:
        assert results == [{"code": code} for code in parts] and kwargs == {"source": case["source"], "input_id": "original-input"}
        return parts

    event_maps: dict[str, dict[str, Path]] = {}
    event_pins: dict[Path, dict[str, Any]] = {}
    original_descriptor = continuation._descriptor
    original_checked_path = continuation._checked_path
    event_root = case["run"] / "analysis/event-parts"

    def prepare_events(
        actual_parts: dict[str, Path], barrier: dict[str, Any], entries: dict[str, Any], output: Path, **kwargs: Any
    ) -> dict[str, dict[str, Path]]:
        assert phase == "events" and actual_parts == parts and barrier == full_barrier
        assert entries == {"labels": {"synthetic_labels": True}} and output == case["run"] / "analysis/event-parts"
        assert kwargs == {"source": case["source"], "input_id": "original-input"}
        called.append("events")
        # Full logical scope, but no synthetic 23k directory/payload creation.
        # Only explicitly expected event-receipt descriptors are mocked.
        for target in analysis.PATTERNS:
            event_maps[target] = {}
            for code in parts:
                directory = output / object_digest({"target": target, "code": code})
                event_maps[target][code] = directory
                path = directory / "receipt.json"
                event_pins[path] = {"path": str(path), "bytes": 1, "sha256": object_digest({"synthetic_event_receipt": target, "code": code})}
        return event_maps

    def event_descriptor(path: Path) -> dict[str, Any]:
        if path in event_pins:
            return event_pins[path]
        return original_descriptor(path)

    def checked_path(path: Path) -> Path:
        # These nonexistent paths already have exact synthetic descriptors.
        # Keep all real paths and the coordinator's containment checks intact.
        if path != event_root and path.is_relative_to(event_root) and (path in event_pins or path / "receipt.json" in event_pins):
            return path.absolute()
        return original_checked_path(path)

    benchmark = pd.DataFrame({"Close": [1.0]})

    def build(actual_parts: dict[str, Path], actual_benchmark: pd.DataFrame, output: Path) -> dict[str, Any]:
        assert phase == "barrier" and actual_parts == parts and output == case["run"] / "global"
        pd.testing.assert_frame_equal(actual_benchmark, benchmark)
        called.append("barrier")
        output.mkdir()
        packet = {"synthetic_barrier": True}
        write_json(output / "receipt.json", packet)
        return packet

    def analyze(
        roots: DataRoots, actual_parts: dict[str, Path], barrier: dict[str, Any], entries: dict[str, Any], output: Path, **kwargs: Any
    ) -> dict[str, Any]:
        assert phase == "analysis" and roots == case["roots"] and actual_parts == parts
        assert barrier == {"synthetic_barrier": True} and entries == {"labels": {"synthetic_labels": True}}
        assert kwargs == {"source": case["source"], "input_id": "original-input", "defer_publication": True, "continuation_request": request_path}
        called.append("analysis")
        output.mkdir()
        index = output / "computed-results.json"
        write_json(index, {"synthetic_computed_results": True})
        return {"retained_result": {"path": str(index)}}

    monkeypatch.setattr(continuation, "create_price_handoff", price_handoff)
    monkeypatch.setattr(continuation, "retire_own_prices", retire)
    monkeypatch.setattr(continuation, "read_benchmark", lambda run: benchmark)
    monkeypatch.setattr(barrier_module, "verified_parts", verified)
    monkeypatch.setattr(barrier_module, "build_barrier", build)
    monkeypatch.setattr(barrier_module, "verify_barrier", lambda value: None)
    monkeypatch.setattr(barrier_module, "checkpoint_label_entry", lambda actual, **kwargs: {"synthetic_labels": True})
    monkeypatch.setattr(analysis, "run_analysis", analyze)
    monkeypatch.setattr(analysis, "prepare_event_parts", prepare_events)
    monkeypatch.setattr(continuation, "_descriptor", event_descriptor)
    if phase == "events":
        monkeypatch.setattr(continuation, "_checked_path", checked_path)
    if phase in {"events", "analysis"}:
        (case["run"] / "global").mkdir()
        write_json(case["run"] / "global/receipt.json", full_barrier)
    continuation.coordinator_main(request_path)
    assert called == [phase]
    response = read_json(case["control"] / f"response-{phase}.json")
    assert response["source"] == case["source"] and response["executor"] == case["executor"]
    assert response["phase"] == phase and response["input_id"] == "original-input"
    assert response["request_id"] == object_digest(request)
    for descriptor in response["results"].values():
        assert descriptor == _pin(Path(descriptor["path"]))
    assert [entry["phase"] for entry in case["admissions"]] == ["prices" if phase == "retire-prices" else phase]
    assert file_digest(case["run"] / "phase-stock-result.json") == original_stock
    assert read_json(case["run"] / continuation.ACTIVE)["owner"] == request["active_owner"]
    assert not (case["control"] / f"response-{phase}.job-memory.json").exists()  # Parent native Job owns this evidence.
    if phase == "events":
        checkpoint_path = case["run"] / "event-checkpoint.json"
        checkpoint = continuation.read_scan_receipt(checkpoint_path)
        assert checkpoint["schema"] == "pattern-scan-event-checkpoint.v4" and checkpoint["complete"] is True
        assert checkpoint["phase_only"] is True and checkpoint["full_study_admitted"] is False
        assert checkpoint["source"] == case["source"] and checkpoint["executor"] == case["executor"] and checkpoint["input_id"] == "original-input"
        assert checkpoint["stock_reference"] == request["stock_reference"] and checkpoint["price_handoff"] == request["price_handoff"]
        assert checkpoint["barrier_receipt"] == _pin(case["run"] / "global/receipt.json")
        assert checkpoint["label_checkpoint"] == {"synthetic_labels": True}
        assert set(checkpoint["event_parts"]) == set(analysis.PATTERNS)
        assert all(set(by_code) == set(parts) for by_code in checkpoint["event_parts"].values())
        assert checkpoint["event_receipts"] == {
            target: {code: event_pins[directory / "receipt.json"] for code, directory in by_code.items()} for target, by_code in event_maps.items()
        }
        assert response["results"] == {"event_checkpoint": _pin(checkpoint_path)}
        assert response["result"]["stock_n"] == 1942 and response["result"]["target_n"] == len(analysis.PATTERNS)
        assert response["result"]["full_study_admitted"] is False
        assert not (case["run"] / "analysis/selection.json").exists()


@pytest.mark.parametrize("damage", ["active_owner", "capacity", "stock_reference", "response_exists"])
def test_coordinator_refuses_unowned_or_changed_inputs_before_data_helpers(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, damage: str) -> None:
    path = _coordinator_request(case, "barrier")
    monkeypatch.setattr(continuation, "read_benchmark", _forbidden)
    monkeypatch.setattr(barrier_module, "verified_parts", _forbidden)
    if damage == "active_owner":
        (case["run"] / continuation.ACTIVE).write_bytes(canonical({"request_id": "wrong", "owner": "wrong"}))
    elif damage == "capacity":
        case["capacity"].write_bytes(b"changed capacity")
    elif damage == "stock_reference":
        stock = case["run"] / "phase-stock-result.json"
        stock.write_bytes(stock.read_bytes() + b" ")
    else:
        write_json(case["control"] / "response-barrier.json", {"unverified_existing": True})
    with pytest.raises(ValueError):
        continuation.coordinator_main(path)


def _argv(case: dict[str, Any], phase: str) -> list[str]:
    args = [
        "continue_pattern_scan",
        phase,
        "--primary-root",
        str(case["roots"].primary),
        "--data-root",
        str(case["roots"].data),
        "--run-id",
        case["run"].name,
        "--control-id",
        case["control"].name,
        "--capacity-plan",
        str(case["capacity"]),
        "--timeout-seconds",
        "60",
        "--calculation-authorized",
    ]
    if phase == "prices":
        args.extend(["--generation", "fixed-generation"])
    if phase == "retire-prices":
        args.append("--retirement-authorized")
    return args


@pytest.mark.parametrize("phase", continuation.PHASES)
def test_cli_forwards_explicit_roots_phase_scope_authorizations_generation_and_timeout(
    case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    phase: str,
) -> None:
    shared_root = case["roots"].primary.parent / "external-shared"
    monkeypatch.setenv(cli.ENV_KEY, "previous process value")
    captured = []
    order: list[str] = []
    completion_pin = {"path": str(case["run"] / "analysis/audits/continuation-completion.json"), "bytes": 123, "sha256": "f" * 64}

    def launch(roots: DataRoots, **kwargs: Any) -> dict[str, Any]:
        assert roots == case["roots"] and os.environ[cli.ENV_KEY] == str(shared_root)
        captured.append(kwargs)
        order.append("launch-returned")
        return {"complete": True, "phase": phase, "source": case["source"], "executor": case["executor"]}

    def completion(request: Path) -> dict[str, Any]:
        assert phase == "analysis" and order == ["launch-returned"]
        assert request == case["control"] / "request-analysis.json"
        order.append("completion-audit")
        return completion_pin

    monkeypatch.setattr(cli, "launch", launch)
    monkeypatch.setattr(cli, "record_analysis_completion", completion if phase == "analysis" else _forbidden)
    monkeypatch.setattr(sys, "argv", [*_argv(case, phase), "--shared-root", str(shared_root)])
    cli.main()
    assert captured == [
        {
            "run_id": case["run"].name,
            "control_id": case["control"].name,
            "phase": phase,
            "capacity_path": case["capacity"],
            "generation": "fixed-generation" if phase == "prices" else None,
            "calculation_authorized": True,
            "retirement_authorized": phase == "retire-prices",
            "timeout_seconds": 60.0,
        }
    ]
    assert json.loads(capsys.readouterr().out) == {
        "complete": True,
        "phase": phase,
        "source_id": "original-stock-source",
        "executor_source_id": "current-executor",
        **({"completion_audit": completion_pin} if phase == "analysis" else {}),
    }
    assert order == (["launch-returned", "completion-audit"] if phase == "analysis" else ["launch-returned"])


@pytest.mark.parametrize("failure", ["launch", "completion"])
def test_cli_analysis_failures_never_print_false_completion(
    case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    calls: list[str] = []

    def launch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append("launch")
        if failure == "launch":
            raise ValueError("synthetic launch failed")
        return {"complete": True, "phase": "analysis", "source": case["source"], "executor": case["executor"]}

    def completion(request: Path) -> dict[str, Any]:
        assert calls == ["launch"] and request == case["control"] / "request-analysis.json"
        calls.append("completion")
        raise ValueError("synthetic completion audit failed")

    monkeypatch.setattr(cli, "launch", launch)
    monkeypatch.setattr(cli, "record_analysis_completion", completion if failure == "completion" else _forbidden)
    monkeypatch.setattr(sys, "argv", _argv(case, "analysis"))
    with pytest.raises(ValueError, match=f"synthetic {'launch' if failure == 'launch' else 'completion audit'} failed"):
        cli.main()
    assert capsys.readouterr().out == ""
    assert calls == (["launch"] if failure == "launch" else ["launch", "completion"])


@pytest.mark.parametrize(
    "problem", ["calculation", "retirement", "generation", "timeout_nan", "timeout_inf", "timeout_zero", "timeout_large", "relative_shared"]
)
def test_cli_invalid_authorization_generation_or_timeout_never_launches(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, problem: str) -> None:
    phase = "retire-prices" if problem == "retirement" else "prices"
    argv = _argv(case, phase)
    if problem == "calculation":
        argv.remove("--calculation-authorized")
    elif problem == "retirement":
        argv.remove("--retirement-authorized")
    elif problem == "generation":
        position = argv.index("--generation")
        del argv[position : position + 2]
    elif problem == "relative_shared":
        argv.extend(["--shared-root", "relative"])
    else:
        argv[argv.index("--timeout-seconds") + 1] = {"timeout_nan": "nan", "timeout_inf": "inf", "timeout_zero": "0", "timeout_large": "28801"}[problem]
    monkeypatch.setattr(cli, "launch", _forbidden)
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


def test_capacity_rejection_never_creates_active_marker_or_native_job(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(path: Path, **kwargs: Any) -> Any:
        assert kwargs["phase"] == "analysis" and kwargs["executor"] == case["executor"]
        raise ValueError("synthetic pending_phase=analysis capacity insufficient")

    monkeypatch.setattr(continuation, "require_continuation_capacity", refused)
    with pytest.raises(ValueError, match="pending_phase=analysis"):
        _launch(case, "analysis")
    assert not (case["run"] / continuation.ACTIVE).exists()
    assert not (case["control"] / "response-analysis.json").exists()
    assert (case["run"] / "phase-stock-result.json").is_file()


def test_cli_preserves_configured_shared_root_without_override(
    case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configured = str(case["roots"].primary.parent / "configured-external-shared")
    monkeypatch.setenv(cli.ENV_KEY, configured)

    def launch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert os.environ[cli.ENV_KEY] == configured
        return {"complete": True, "phase": "barrier", "source": case["source"], "executor": case["executor"]}

    monkeypatch.setattr(cli, "launch", launch)
    monkeypatch.setattr(sys, "argv", _argv(case, "barrier"))
    cli.main()
    assert os.environ[cli.ENV_KEY] == configured and json.loads(capsys.readouterr().out)["phase"] == "barrier"


@pytest.mark.parametrize("damage", ["stock_scope", "duplicate_stock", "global_codes", "source", "input", "calendar"])
def test_events_requires_the_original_complete_full_market_barrier_before_projection(
    case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    parts, barrier = _full_events_case(case)
    if damage == "stock_scope":
        parts.pop(next(iter(parts)))
    elif damage == "duplicate_stock":
        stock_path = case["run"] / "phase-stock-result.json"
        stock = read_json(stock_path)
        stock["pool"]["results"][1] = stock["pool"]["results"][0]
        stock_path.write_bytes(canonical(stock))
    elif damage == "global_codes":
        barrier["global_files"].pop(next(iter(parts)))
    elif damage == "source":
        barrier["source_id"] = "different-source"
    elif damage == "input":
        barrier["input_id"] = "different-input"
    else:
        barrier["calendar"] = list(reversed(barrier["calendar"]))
    (case["run"] / "global").mkdir()
    write_json(case["run"] / "global/receipt.json", barrier)
    request_path = _coordinator_request(case, "events")
    verified: list[dict[str, Any]] = []
    monkeypatch.setattr(barrier_module, "verified_parts", lambda *args, **kwargs: parts)
    monkeypatch.setattr(barrier_module, "verify_barrier", lambda body: verified.append(body))
    monkeypatch.setattr(barrier_module, "checkpoint_label_entry", _forbidden)
    monkeypatch.setattr(analysis, "prepare_event_parts", _forbidden)
    monkeypatch.setattr(analysis, "run_analysis", _forbidden)
    before = {path: file_digest(path) for path in case["run"].rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="full-market"):
        continuation.coordinator_main(request_path)
    assert verified == [barrier]
    assert before == {path: file_digest(path) for path in case["run"].rglob("*") if path.is_file()}
    assert not (case["run"] / "event-checkpoint.json").exists()
    assert not (case["control"] / "response-events.json").exists()
