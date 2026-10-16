"""Synthetic continuation lineage, metadata pins and deferred analysis handoff."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

from research_core import pattern_scan_analysis_v1 as analysis
from research_core import pattern_scan_git_source_v2 as git_source
from research_core import pattern_scan_price_references_v4 as prices
from research_core.artifact_store import describe_file, object_digest, read_json, write_json


def _pin(path: Path) -> dict[str, Any]:
    return {**describe_file(path.parent, path), "path": str(path)}


def _rewrite(path: Path, value: dict[str, Any]) -> None:
    path.unlink(missing_ok=True)
    write_json(path, value)


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    run = primary / ".tmp/pattern-scan-execution/original"
    control = run.parent / "continuation"
    run.mkdir(parents=True)
    control.mkdir()
    source = {"schema": "pattern-scan-source.git.v2", "source_id": "original", "code": {"commit": "a" * 40, "dirty": True}}
    executor = {**source, "source_id": "executor", "code": {"commit": "b" * 40, "dirty": False}}
    input_id = "original-input"
    reference = {
        "root": str(primary / "shared"),
        "generation": "fixed-generation",
        "status": "complete",
        "pins": {"calendar": "synthetic"},
        "basis": "as_of",
        "cutoff": "2026-10-12",
        "calendar_n": 4110,
    }
    codes = [f"synthetic-{index:04d}" for index in range(1942)]
    write_json(
        run / "derived-preparation.json",
        {
            "schema": "pattern-scan-derived-preparation.v2",
            "scope": "full_ordinary_reference",
            "source": source,
            "input_id": input_id,
            "calendar_n": 4110,
            "ordinary_reference_n": 1942,
            "requests": [{"code": code} for code in codes],
        },
    )
    write_json(
        run / "phase-stock-result.json",
        {
            "phase": "full_stock_checkpoints",
            "global_analysis_admitted": False,
            "pool": {"results": [{"code": code, "complete": True, "source_id": source["source_id"], "input_id": input_id} for code in codes]},
        },
    )
    names = (
        "derived-preparation.json",
        "producer-read-receipt.json",
        "phase-stock-result.json",
        "request-stock.json",
        "response-stock.json",
        "response-stock.job-memory.json",
        "run-stock-receipt.json",
    )
    for name in names:
        if not (run / name).exists():
            write_json(run / name, {"synthetic_original_envelope": name})
    write_json(run / prices.HANDOFF, {"synthetic_verified_handoff": True})
    write_json(
        run / prices.EQUALITY,
        {
            "schema": "pattern-scan-price-reader-equivalence.v3",
            "complete": True,
            "reference_source_id": source["source_id"],
            "reference_input_id": input_id,
            "reference": reference,
            "generation": reference["generation"],
            "calendar_n": 4110,
            "security_n": 1943,
            "cutoff": "2026-10-12",
            "all_columns_equal": True,
            "calendar_equal": True,
            "quality_equal": True,
            "mismatch_n": 0,
        },
    )
    write_json(
        run / prices.RETIRED,
        {
            "schema": "pattern-scan-own-price-retirement.v4",
            "complete": True,
            "run_root": str(run),
            "original_source_id": source["source_id"],
            "original_input_id": input_id,
            "generation": reference["generation"],
            "handoff": {"path": str(run / prices.HANDOFF), "sha256": _pin(run / prices.HANDOFF)["sha256"]},
            "other_stock_artifacts_retained": True,
        },
    )
    capacity = control / "capacity-analysis.json"
    write_json(
        capacity,
        {
            "schema": "pattern-scan-continuation-capacity.v4",
            "phase": "analysis",
            "executor_source_id": executor["source_id"],
            "ancestral_source_id": source["source_id"],
            "input_id": input_id,
        },
    )
    request_path = control / "request-analysis.json"
    request = {
        "schema": "pattern-scan-continuation.v4",
        "phase": "analysis",
        "calculation_authorized": True,
        "run_root": str(run),
        "control_root": str(control),
        "primary": str(primary),
        "data": str(primary / "research_data"),
        "source": source,
        "input_id": input_id,
        "executor": executor,
        "reference": reference,
        "stock_reference": _pin(run / "phase-stock-result.json"),
        "price_handoff": _pin(run / prices.HANDOFF),
        "capacity_path": str(capacity),
        "capacity_sha256": _pin(capacity)["sha256"],
    }
    write_json(request_path, request)
    verified = {
        "source": source,
        "input_id": input_id,
        "reference": deepcopy(reference),
        "executor": executor,
        "ancestors": {name: _pin(run / name) for name in names},
        "audit": _pin(run / prices.EQUALITY),
    }
    checked: list[Any] = []

    def current(value: dict[str, Any], root: Path) -> None:
        checked.append((value, root))
        if value != executor:
            raise ValueError("active executor differs")

    monkeypatch.setattr(git_source, "assert_current_code", current)
    monkeypatch.setattr(prices, "retired_preparation_reference", lambda path: verified)
    return locals()


def _select(case: dict[str, Any]) -> tuple[dict[str, Path], dict[str, Any]]:
    return analysis._continuation_execution_provenance(case["run"] / "analysis", case["source"], case["input_id"], case["request_path"])


def test_continuation_retains_small_metadata_and_separates_executor(case: dict[str, Any]) -> None:
    files, provenance = _select(case)
    excluded = {"phase-stock-result.json", "response-stock.json"}
    assert set(files) == {
        *(f"execution/{name}" for name in case["names"] if name not in excluded),
        "execution/continuation-request.json",
        "execution/continuation-capacity.json",
        "execution/shared-price-equivalence.json",
        "execution/own-price-retirement.json",
    }
    for name in excluded:
        assert case["run"] / name not in files.values()
        assert f"execution/{name}" not in files
    assert provenance["stock_reference"] == _pin(case["run"] / "phase-stock-result.json")
    assert case["run"] / prices.HANDOFF not in files.values()
    assert all(path.suffix == ".json" for path in files.values())
    assert provenance == {
        "stock_reference": _pin(case["run"] / "phase-stock-result.json"),
        "executor": case["executor"],
        "ancestral_stock_source": case["source"],
        "shared_price_reference": case["reference"],
        "price_handoff": _pin(case["run"] / prices.HANDOFF),
        "phase_execution": {},
        "phase_execution_unavailable": ["prices", "retire-prices", "barrier", "events"],
        "analysis_native_job_memory": {"status": "pending", "observation": None},
    }
    assert case["checked"] == [(case["executor"], analysis.ROOT)]
    assert not (case["run"] / "prepared").exists()
    assert not (case["run"] / "analysis").exists()
    assert analysis._report_execution_files(case["run"] / "analysis", case["source"], case["input_id"], case["request_path"]) == files


@pytest.mark.parametrize(
    "field,value",
    [
        ("phase", "prices"),
        ("source", {}),
        ("input_id", "different"),
        ("run_root", "different"),
        ("control_root", "different"),
        ("calculation_authorized", False),
        ("executor", {}),
    ],
)
def test_request_drift_rejected(case: dict[str, Any], field: str, value: Any) -> None:
    request = read_json(case["request_path"])
    request[field] = value
    _rewrite(case["request_path"], request)
    with pytest.raises(ValueError):
        _select(case)


@pytest.mark.parametrize(
    "name",
    ["producer-read-receipt.json", "response-stock.job-memory.json", "phase-stock-result.json", prices.HANDOFF, prices.EQUALITY, "capacity-analysis.json"],
)
def test_actual_metadata_pin_drift_rejected(case: dict[str, Any], name: str) -> None:
    path = (case["control"] if name == "capacity-analysis.json" else case["run"]) / name
    _rewrite(path, {"corrupted": True})
    with pytest.raises(ValueError):
        _select(case)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "incomplete", "source", "input"])
def test_complete_original_pool_required_even_with_matching_pins(case: dict[str, Any], fault: str) -> None:
    path = case["run"] / "phase-stock-result.json"
    stock = read_json(path)
    rows = stock["pool"]["results"]
    if fault == "missing":
        rows.pop()
    elif fault == "duplicate":
        rows[0] = rows[1]
    else:
        rows[0][{"incomplete": "complete", "source": "source_id", "input": "input_id"}[fault]] = False if fault == "incomplete" else "different"
    _rewrite(path, stock)
    case["verified"]["ancestors"][path.name] = _pin(path)
    request = read_json(case["request_path"])
    request["stock_reference"] = _pin(path)
    _rewrite(case["request_path"], request)
    with pytest.raises(ValueError, match="1942-stock"):
        _select(case)


@pytest.mark.parametrize("fault", ["reference", "equality", "retirement", "capacity", "preparation"])
def test_semantic_identity_drift_rejected_after_repinning(case: dict[str, Any], fault: str) -> None:
    if fault == "reference":
        case["verified"]["reference"]["generation"] = "different"
    else:
        path, field, value = {
            "equality": (case["run"] / prices.EQUALITY, "mismatch_n", 1),
            "retirement": (case["run"] / prices.RETIRED, "other_stock_artifacts_retained", False),
            "capacity": (case["capacity"], "ancestral_source_id", "different"),
            "preparation": (case["run"] / "derived-preparation.json", "ordinary_reference_n", 4),
        }[fault]
        body = read_json(path)
        body[field] = value
        _rewrite(path, body)
        if fault == "equality":
            case["verified"]["audit"] = _pin(path)
        elif fault == "capacity":
            request = read_json(case["request_path"])
            request["capacity_sha256"] = _pin(path)["sha256"]
            _rewrite(case["request_path"], request)
        elif fault == "preparation":
            case["verified"]["ancestors"][path.name] = _pin(path)
    with pytest.raises(ValueError):
        _select(case)


def test_run_analysis_records_continuation_provenance_once(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import pattern_scan_completion_v1 as completion
    from research_core import pattern_scan_result_lifecycle_v3 as lifecycle
    from research_core import pattern_scan_retained_v3 as retained

    monkeypatch.setattr(analysis, "verify_source", lambda source: None)
    monkeypatch.setattr(analysis, "prepare_event_parts", lambda *args, **kwargs: {})
    monkeypatch.setattr(analysis, "select_all", lambda *args: {"fixed": "selection"})
    monkeypatch.setattr(analysis, "_audits", lambda *args, **kwargs: {"files": {}})
    monkeypatch.setattr(analysis, "summarize_all", lambda *args: {"files": {}})
    monkeypatch.setattr(analysis, "metadata", lambda *args: {"inputs": {}})
    monkeypatch.setattr(completion, "complete_followup", lambda *args, **kwargs: {"files": {}})
    captured: dict[str, Any] = {}

    def collect(*args: Any, **kwargs: Any) -> dict[str, Path]:
        captured["execution_files"] = kwargs["execution_files"]
        return {}

    def record(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"synthetic": True}

    monkeypatch.setattr(retained, "collect_retained_files", collect)
    monkeypatch.setattr(lifecycle, "record_computed_results", record)
    labels = {"version_id": "original-labels", "manifest": {"sha256": "original-label-manifest"}}
    result = analysis.run_analysis(
        cast(Any, None),
        {},
        {"calendar": ["2020-01-02"]},
        {"labels": labels},
        case["run"] / "analysis",
        source=case["source"],
        input_id=case["input_id"],
        defer_publication=True,
        continuation_request=case["request_path"],
    )
    assert result["status"] == "computed_unpublished"
    assert captured["source"] == case["source"]
    assert captured["provenance"]["executor"] == case["executor"]
    assert captured["provenance"]["ancestral_stock_source"] == case["source"]
    assert captured["provenance"]["stock_reference"] == _pin(case["run"] / "phase-stock-result.json")
    assert captured["provenance"]["shared_price_reference"] == case["reference"]
    assert captured["provenance"]["label_checkpoint"] == labels
    assert captured["provenance"]["selection"] == {"fixed": "selection"}
    assert len(case["checked"]) == 1
    assert case["request_path"] in captured["execution_files"].values()


@pytest.mark.parametrize("deferred", [False, True])
def test_invalid_continuation_fails_before_computation(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, deferred: bool) -> None:
    monkeypatch.setattr(analysis, "verify_source", lambda source: None)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("invalid continuation reached numerical computation")

    monkeypatch.setattr(analysis, "prepare_event_parts", forbidden)
    if deferred:
        (case["run"] / "response-stock.job-memory.json").unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        analysis.run_analysis(
            cast(Any, None),
            {},
            {},
            {},
            case["run"] / "analysis",
            source=case["source"],
            input_id=case["input_id"],
            defer_publication=deferred,
            continuation_request=case["request_path"],
        )
    assert not (case["run"] / "analysis").exists()


@pytest.mark.parametrize("explicit_executor", [False, True])
def test_published_receipt_uses_executor_code_with_legacy_fallback(case: dict[str, Any], explicit_executor: bool) -> None:
    from research_core import pattern_scan_result_lifecycle_v3 as lifecycle
    from research_core.research_data_catalog import DataCatalog, verify_entry
    from research_core.research_data_paths import DataRoots

    run = case["run"]
    result = run / "aggregate.json"
    write_json(result, {"synthetic_integer_count": 3})
    provenance = {"executor": case["executor"]} if explicit_executor else {}
    descriptor = lifecycle.record_computed_results(
        run, {"aggregates/counts.json": result}, source=case["source"], input_id=case["input_id"], provenance=provenance
    )
    verification = run / "delivery.json"
    write_json(
        verification,
        {
            "schema": "pattern-scan-delivery-verification.v3",
            "complete": True,
            "source_id": case["source"]["source_id"],
            "input_id": case["input_id"],
            "event_audit_n": 10,
            "candidate_audit_n": 5,
            "candidate_comparison_rows": 54_720,
            "mismatch_n": 0,
        },
    )
    report = run / "report.md"
    report.write_text("Synthetic report.\n", encoding="utf-8")
    unavailable = {"start": None, "end": None, "reason": "synthetic only"}
    metadata = {
        "data_id": "synthetic-continuation-results",
        "kind": "patterns",
        "definition_version": "fixture.v1",
        "parameters": {"fixture": True},
        "inputs": {"source_id": case["source"]["source_id"], "input_id": case["input_id"]},
        "coverage": {"scope": "invented", "raw_input_period": unavailable, "valid_indicator_period": unavailable, "complete_label_period": unavailable},
        "status": "complete",
        "limitations": ["synthetic fixture"],
        "backup": {"status": "not_backed_up", "off_machine": False},
    }
    roots = DataRoots(case["primary"], case["primary"] / "research_data")
    proof = lifecycle.handoff_results(
        descriptor, DataCatalog(roots), metadata, managed_parent="bundles/synthetic-continuation-results", verification=verification, report=report
    )
    verify_entry(proof["entry"], roots)
    directory = roots.artifact_path("data", str(Path(proof["entry"]["manifest"]["path"]).parent).replace("\\", "/"))
    receipt = read_json(directory / "run-receipt.json")
    assert receipt["code"] == (case["executor"] if explicit_executor else case["source"])["code"]
    assert receipt["source"] == case["source"]
    assert receipt["provenance"] == provenance


def _historical_executor(commit: str = "c" * 40) -> dict[str, Any]:
    from research_core.pattern_scan_execution_v1 import NUMERICAL_THREADS
    from research_core.stock_feature_pool_v1 import runtime_identity

    body = {
        "schema": "pattern-scan-source.git.v2",
        "code": {"commit": commit, "dirty": False},
        "runtime": runtime_identity(),
        "platform": sys.platform,
        "numerical_thread_limits": dict(NUMERICAL_THREADS),
    }
    return {**body, "source_id": object_digest(body)}


def _resign_phase(case: dict[str, Any], phase: str, request: dict[str, Any], response: dict[str, Any] | None = None) -> None:
    """Rebind synthetic envelopes so semantic drift tests reach the intended guard."""
    control = case["control"]
    _rewrite(control / f"request-{phase}.json", request)
    response_path = control / f"response-{phase}.json"
    saved = read_json(response_path) if response is None else response
    saved.update({
        "request_id": object_digest(request),
        "phase": request["phase"],
        "source": request["source"],
        "input_id": request["input_id"],
        "executor": request["executor"],
    })
    _rewrite(response_path, saved)
    memory_path = control / f"response-{phase}.job-memory.json"
    memory = read_json(memory_path)
    memory.update({"request_id": object_digest(request), "response_sha256": _pin(response_path)["sha256"]})
    _rewrite(memory_path, memory)


def _add_phase(case: dict[str, Any], phase: str, executor: dict[str, Any] | None = None) -> dict[str, Any]:
    run, control = case["run"], case["control"]
    executor = _historical_executor() if executor is None else executor
    outputs = {
        "prices": {"price_handoff": run / prices.HANDOFF, "equivalence": run / prices.EQUALITY},
        "retire-prices": {"price_retirement": run / prices.RETIRED},
        "barrier": {"barrier": run / "global/receipt.json"},
        "events": {"event_checkpoint": run / "event-checkpoint.json"},
    }[phase]
    for path in outputs.values():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, {"synthetic": phase})
    capacity = control / f"capacity-{phase}.json"
    write_json(
        capacity,
        {
            "schema": "pattern-scan-continuation-capacity.v4",
            "phase": "prices" if phase == "retire-prices" else phase,
            "executor_source_id": executor["source_id"],
            "ancestral_source_id": case["source"]["source_id"],
            "input_id": case["input_id"],
            "memory": {"job_limit_bytes": 1024**3},
        },
    )
    request = {
        **read_json(case["request_path"]),
        "phase": phase,
        "executor": executor,
        "retirement_authorized": phase == "retire-prices",
        "price_handoff": None if phase == "prices" else _pin(run / prices.HANDOFF),
        "capacity_path": str(capacity),
        "capacity_sha256": _pin(capacity)["sha256"],
    }
    write_json(control / f"request-{phase}.json", request)
    response = control / f"response-{phase}.json"
    write_json(
        response,
        {
            "schema": "pattern-scan-continuation.v4",
            "complete": True,
            "phase": phase,
            "request_id": object_digest(request),
            "source": request["source"],
            "input_id": request["input_id"],
            "executor": executor,
            "results": {name: _pin(path) for name, path in outputs.items()},
        },
    )
    write_json(
        control / f"response-{phase}.job-memory.json",
        {
            "complete": True,
            "request_id": object_digest(request),
            "response_sha256": _pin(response)["sha256"],
            "job_memory": {"limit_bytes": 1024**3, "peak_committed_bytes": 123_456, "scope": "virtual memory committed across this owned Windows job"},
        },
    )
    return request


def test_prior_phases_retain_actual_historical_executor_and_job_evidence(case: dict[str, Any]) -> None:
    phases = ("prices", "retire-prices", "barrier", "events")
    # A completed price comparison and later retirement can execute different code.
    price_executor = _historical_executor("52f748afc9fdd08676b6f2e82e868023470f49cd")
    later_executor = _historical_executor("ec025ab6ec607f0ad4e0b2c9d143146f1baed7ec")
    executors = {phase: price_executor if phase == "prices" else later_executor for phase in phases}
    assert price_executor["source_id"] != later_executor["source_id"]
    for phase in phases:
        _add_phase(case, phase, executors[phase])
    files, provenance = _select(case)
    assert provenance["phase_execution_unavailable"] == []
    assert provenance["analysis_native_job_memory"] == {"status": "pending", "observation": None}
    assert case["checked"] == [(case["executor"], analysis.ROOT)]
    assert set(provenance["phase_execution"]) == set(phases)
    for phase in phases:
        evidence = provenance["phase_execution"][phase]
        assert evidence["executor"] == executors[phase]
        assert evidence["executor"] != case["executor"]
        assert evidence["job_memory"]["peak_committed_bytes"] == 123_456
        for kind in ("request", "response", "job-memory", "capacity"):
            row = evidence["metadata"][kind]
            logical = f"execution/phases/{phase}/{kind}.json"
            assert row == {"retained_path": logical, **_pin(files[logical])}
    assert case["run"] / prices.HANDOFF not in files.values()
    assert case["run"] / "phase-stock-result.json" not in files.values()
    assert case["run"] / "response-stock.json" not in files.values()


@pytest.mark.parametrize("phase", ["prices", "retire-prices", "barrier", "events"])
@pytest.mark.parametrize("missing", ["request", "response", "job-memory"])
def test_partial_prior_phase_fails_closed(case: dict[str, Any], phase: str, missing: str) -> None:
    _add_phase(case, phase)
    name = f"request-{phase}.json" if missing == "request" else f"response-{phase}{'.job-memory' if missing == 'job-memory' else ''}.json"
    (case["control"] / name).unlink()
    with pytest.raises(ValueError, match="incomplete prior"):
        _select(case)


@pytest.mark.parametrize(
    "fault",
    [
        "phase",
        "run_root",
        "control_root",
        "primary",
        "data",
        "source",
        "input_id",
        "stock_reference",
        "reference",
        "calculation_authorized",
        "retirement_authorized",
        "executor",
    ],
)
def test_prior_phase_request_drift_rejected_after_rebinding_envelopes(case: dict[str, Any], fault: str) -> None:
    phase = "retire-prices"
    request = _add_phase(case, phase)
    if fault in {"calculation_authorized", "retirement_authorized"}:
        request[fault] = False
    elif fault == "executor":
        request[fault] = {**request[fault], "source_id": "incorrect-digest"}
    elif fault in {"source", "stock_reference", "reference"}:
        request[fault] = {**request[fault], "sha256" if fault == "stock_reference" else "generation": "different"}
    else:
        request[fault] = "different"
    _resign_phase(case, phase, request)
    with pytest.raises(ValueError):
        _select(case)


@pytest.mark.parametrize("fault", ["phase", "executor_source_id", "ancestral_source_id", "input_id", "schema", "memory"])
def test_prior_capacity_drift_rejected_after_repinning(case: dict[str, Any], fault: str) -> None:
    request = _add_phase(case, "barrier")
    path = Path(request["capacity_path"])
    capacity = read_json(path)
    capacity[fault] = {"job_limit_bytes": 2 * 1024**3} if fault == "memory" else "different"
    _rewrite(path, capacity)
    request["capacity_sha256"] = _pin(path)["sha256"]
    _resign_phase(case, "barrier", request)
    with pytest.raises(ValueError, match="capacity or observed Job"):
        _select(case)


@pytest.mark.parametrize("fault", ["output-key", "locator", "output-hash", "response-hash", "job-request", "job-limit", "peak"])
def test_prior_result_and_native_observation_drift_rejected(case: dict[str, Any], fault: str) -> None:
    request = _add_phase(case, "barrier")
    response_path = case["control"] / "response-barrier.json"
    response = read_json(response_path)
    memory_path = case["control"] / "response-barrier.job-memory.json"
    if fault in {"output-key", "locator", "output-hash"}:
        if fault == "output-key":
            response["results"]["unexpected"] = response["results"].pop("barrier")
        else:
            response["results"]["barrier"]["path" if fault == "locator" else "sha256"] = "different"
        _resign_phase(case, "barrier", request, response)
    else:
        memory = read_json(memory_path)
        if fault in {"response-hash", "job-request"}:
            memory["response_sha256" if fault == "response-hash" else "request_id"] = "different"
        else:
            memory["job_memory"]["limit_bytes" if fault == "job-limit" else "peak_committed_bytes"] = 0
        _rewrite(memory_path, memory)
    with pytest.raises(ValueError):
        _select(case)
