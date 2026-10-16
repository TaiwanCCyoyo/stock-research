"""Synthetic continuation lineage, metadata pins and deferred analysis handoff."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

from research_core import pattern_scan_analysis_v1 as analysis
from research_core import pattern_scan_git_source_v2 as git_source
from research_core import pattern_scan_price_references_v4 as prices
from research_core.artifact_store import describe_file, read_json, write_json


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
