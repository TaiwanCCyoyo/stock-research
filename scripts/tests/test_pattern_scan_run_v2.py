"""Synthetic public live-input workflow, retention and launch-boundary checks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core import pattern_scan_capacity_v2 as capacity
from research_core import pattern_scan_run_v2 as run
from research_core import run_receipt
from research_core.artifact_store import canonical, describe_file, file_digest, object_digest, read_json, write_json
from research_core.live_producer import ProducerChangedError
from research_core.research_data_paths import DataRoots
from scripts import pattern_scan_live as cli


def _forbidden(*args: Any, **kwargs: Any) -> Any:
    pytest.fail("unexpected live read, numerical work or child start")


@pytest.fixture
def setup_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[DataRoots, Path, dict[str, Any]]:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    roots = DataRoots(primary, primary / "research_data")
    directory = primary / ".tmp" / "pattern-scan-execution" / "synthetic"
    directory.mkdir(parents=True)
    source = {"schema": "pattern-scan-source.git.v2", "source_id": "synthetic-source", "code": {"commit": "a" * 40, "dirty": False}}
    request = {
        "schema": "pattern-scan-coordinator-request.v2",
        "calculation_authorized": True,
        "mode": "prepare",
        "run_id": "synthetic",
        "primary": str(primary),
        "data": str(roots.data),
        "run_root": str(directory),
        "source": source,
        "capacity_path": None,
        "prepared_path": None,
        "profile_path": None,
        "producer_root": str(tmp_path / "producer"),
        "memory_bytes": 1024**3,
        "job_memory_bytes": 2 * 1024**3,
        "timeout_seconds": 60,
    }
    monkeypatch.setattr(run, "assert_current_code", lambda *args: None)
    monkeypatch.setattr(run, "require_capacity", lambda *args: {})
    monkeypatch.setattr(run, "load_live_inputs", _forbidden)
    monkeypatch.setattr(run, "producer_data_root", _forbidden)
    monkeypatch.setattr(run_receipt, "code_identity", lambda *args: {"commit": "a" * 40, "dirty": False})
    return roots, directory, request


def _prepared(directory: Path, request: dict[str, Any], *, scope: str = "full_ordinary_reference") -> Path:
    prepared = directory / "prepared"
    prepared.mkdir()
    benchmark = prepared / "benchmark.parquet"
    stock = prepared / "0001.parquet"
    benchmark.write_bytes(b"synthetic benchmark checkpoint")
    stock.write_bytes(b"synthetic stock checkpoint")
    index = directory / "derived-preparation.json"
    write_json(
        index,
        {
            "schema": "pattern-scan-derived-preparation.v2",
            "source": request["source"],
            "scope": scope,
            "input_id": "synthetic-input",
            "benchmark_path": str(benchmark),
            "strata": {},
            "producer_fingerprint": {"inputs": {}},
            "requests": [{"code": "0001", "prepared_path": str(stock), "source": request["source"]}],
            "artifacts": [describe_file(directory, path) for path in (benchmark, stock)],
        },
    )
    write_json(
        directory / "producer-read-receipt.json",
        {
            "schema": "run-receipt.v1",
            "run_id": "synthetic:producer-read",
            "results": {"derived_preparation": {"path": str(index), "bytes": index.stat().st_size, "sha256": file_digest(index)}},
        },
    )
    return index


def _stub_fingerprint(specs: list[Any]) -> dict[str, Any]:
    names = {spec.name for spec in specs}
    assert {"derived_preparation", "producer_read_receipt", "derived_prices"}.issubset(names)
    assert names.issubset({"derived_preparation", "producer_read_receipt", "derived_prices", "phase_request", "resource_profile", "capacity_plan"})
    assert all(spec.live_producer is False for spec in specs)
    assert all("producer" not in str(spec.path.name) or spec.name == "producer_read_receipt" for spec in specs)
    return {"inputs": {}}


@pytest.mark.parametrize("mode,scope", [("prepare", "full_ordinary_reference"), ("profile", "representative_resource_probe")])
def test_fresh_live_read_ends_with_receipt_before_derived_phase(setup_run: Any, monkeypatch: pytest.MonkeyPatch, mode: str, scope: str) -> None:
    roots, directory, request = setup_run
    request["mode"] = mode
    request["profile_path"] = str(directory / "synthetic-profile.json")
    write_json(Path(request["profile_path"]), {"scope": "synthetic resource profile"})
    monkeypatch.setattr(run, "validate_profile", lambda *args, **kwargs: None)
    events = []

    class Snapshot:
        inventory = pd.DataFrame({"included": [True, True], "code": ["0001", "0002"]})
        input_id = "synthetic-input"
        fingerprint: dict[str, Any] = {"inputs": {}}
        calendar = ["2020-01-01"]
        consumption_measurements: list[Any] = []

        def stock(self, code: str) -> None:
            assert code == "0050"
            events.append("benchmark-read")

        def verify_after(self) -> None:
            events.append("raw-fingerprint-verified")

    def live(*args: Any, **kwargs: Any) -> Snapshot:
        events.append("live-read")
        return Snapshot()

    def prepare(snapshot: Any, codes: tuple[str, ...], source: Any, directory: Path, **kwargs: Any) -> Any:
        assert codes == (("0001", "0002") if mode == "prepare" else ("0001",))
        prepared = directory / "prepared"
        prepared.mkdir()
        packets = []
        for code in codes:
            path = prepared / f"{code}.parquet"
            path.write_bytes(b"synthetic derived stock")
            packets.append({"code": code, "prepared_path": str(path)})
        return packets, {"phase": "synthetic-prepare"}

    monkeypatch.setattr(run, "producer_data_root", lambda: Path(request["producer_root"]))
    monkeypatch.setattr(run, "load_live_inputs", live)
    monkeypatch.setattr(run, "representative_codes", lambda snapshot: (("0001",), {}))
    monkeypatch.setattr(run, "prepare_requests", prepare)
    monkeypatch.setattr(run, "write_frame", lambda frame, stream, **kwargs: stream.write(b"synthetic benchmark"))
    record, index = run._prepare(roots, request, directory)
    assert record["scope"] == scope
    assert events == ["live-read", "benchmark-read", "raw-fingerprint-verified"]
    assert (directory / "producer-read-receipt.json").is_file()
    monkeypatch.setattr(run, "producer_data_root", _forbidden)
    monkeypatch.setattr(run, "load_live_inputs", _forbidden)
    monkeypatch.setattr(run, "fingerprint_inputs", _stub_fingerprint)
    assert run._derived_inputs(index, request)[0]["input_id"] == "synthetic-input"


def test_prepare_finishes_read_receipt_before_derived_computation(setup_run: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    roots, directory, request = setup_run
    events = []
    # A retained checkpoint exercises the real historical hash gates with no producer access.
    index = _prepared(directory, request)
    monkeypatch.setattr(run, "fingerprint_inputs", _stub_fingerprint)
    monkeypatch.setattr(run, "read_frame", lambda path: events.append("derived-read"))
    monkeypatch.setattr(run, "run_requests", _forbidden)
    path = directory / "request-prepare.json"
    write_json(path, request)
    run.coordinator_main(path)
    assert events == ["derived-read"]
    response = directory / "response-prepare.json"
    saved = run.verify_completion(response, request, roots)
    assert saved["result"]["phase"] == "derived_price_preparation"
    assert saved["result"]["prepared_path"] == str(index)
    assert (directory / "run-prepare-receipt.json").is_file()
    before = response.read_bytes()
    with pytest.raises((FileExistsError, ValueError)):
        run.coordinator_main(path)
    assert response.read_bytes() == before


def test_same_run_preparation_then_all_keeps_phase_specific_receipts(setup_run: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import pattern_scan_analysis_v1 as analysis

    _, directory, request = setup_run
    index = _prepared(directory, request)
    monkeypatch.setattr(run, "fingerprint_inputs", _stub_fingerprint)
    monkeypatch.setattr(run, "read_frame", lambda path: None)
    prepare_path = directory / "request-prepare.json"
    write_json(prepare_path, request)
    run.coordinator_main(prepare_path)
    retained = {name: (directory / name).read_bytes() for name in ("response-prepare.json", "run-prepare-receipt.json", "phase-prepare-result.json")}
    profile = directory / "resource-profile.json"
    write_json(
        profile,
        {"selected": {"workers": 1, "memory_cap_bytes": 1024**3, "estimated_worker_bytes": 256 * 1024**2, "stocks_per_process": 1, "timeout_seconds": 60}},
    )
    request = {**request, "mode": "all", "prepared_path": str(index), "profile_path": str(profile)}
    monkeypatch.setattr(run, "validate_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr(run, "run_requests", lambda *args, **kwargs: {"results": []})
    monkeypatch.setattr(run, "verified_parts", lambda *args, **kwargs: {})
    monkeypatch.setattr(run, "build_barrier", lambda *args, **kwargs: {})
    monkeypatch.setattr(run, "publish_stock_versions", lambda *args, **kwargs: {})
    monkeypatch.setattr(analysis, "run_analysis", lambda *args, **kwargs: {})
    path = directory / "request-all.json"
    write_json(path, request)
    run.coordinator_main(path)
    assert read_json(directory / "response-all.json")["result"]["phase"] == "complete_pattern_scan"
    assert (directory / "run-all-receipt.json").exists()
    assert (directory / "phase-all-result.json").exists()
    assert all((directory / name).read_bytes() == value for name, value in retained.items())


@pytest.mark.parametrize("mode", ["stock", "all", "prepare"])
def test_representative_profile_cannot_become_full_preparation(setup_run: Any, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    _, directory, request = setup_run
    index = _prepared(directory, request, scope="representative_resource_probe")
    request.update(mode=mode, prepared_path=str(index))
    monkeypatch.setattr(run, "fingerprint_inputs", _forbidden)
    monkeypatch.setattr(run, "run_requests", _forbidden)
    path = directory / f"request-{mode}.json"
    write_json(path, request)
    with pytest.raises(ValueError, match="representative|scope|full-market"):
        run.coordinator_main(path)


@pytest.mark.parametrize("mutation", ["source", "ownership"])
def test_derived_inputs_reject_mismatched_source_or_owner(setup_run: Any, mutation: str) -> None:
    _, directory, request = setup_run
    index = _prepared(directory, request)
    if mutation == "source":
        request["source"] = {"source_id": "different"}
    else:
        request["primary"] = str(directory.parent)
    with pytest.raises(ValueError, match="source|task-owned"):
        run._derived_inputs(index, request)


def test_missing_producer_receipt_blocks_numerical_work(setup_run: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _, directory, request = setup_run
    index = _prepared(directory, request)
    (directory / "producer-read-receipt.json").unlink()
    request.update(mode="all", prepared_path=str(index))
    monkeypatch.setattr(run, "run_requests", _forbidden)
    monkeypatch.setattr(run, "read_frame", _forbidden)
    path = directory / "request-all.json"
    write_json(path, request)
    with pytest.raises((FileNotFoundError, ValueError)):
        run.coordinator_main(path)


def test_interrupted_read_receipt_recovers_only_unchanged_fingerprint(setup_run: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    roots, directory, request = setup_run
    index = _prepared(directory, request)
    producer = tmp_path / "synthetic-raw-input"
    producer.write_bytes(b"original")
    stat = producer.stat()
    record = read_json(index)
    record["producer_fingerprint"] = {"inputs": {"raw": {"path": str(producer), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}}}
    index.unlink()
    write_json(index, record)
    receipt = directory / "producer-read-receipt.json"
    receipt.unlink()
    monkeypatch.setattr(run, "assert_producer_idle", lambda: None)
    producer.write_bytes(b"changed and longer")
    with pytest.raises(ProducerChangedError, match="changed"):
        run._prepare(roots, request, directory)
    assert not receipt.exists()
    producer.write_bytes(b"original")
    os.utime(producer, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert run._prepare(roots, request, directory)[1] == index
    assert receipt.is_file()


@pytest.mark.parametrize("mutation", [None, "request", "result", "receipt", "response", "source", "phase"])
def test_historical_completion_checks_hashes_without_current_producer(setup_run: Any, monkeypatch: pytest.MonkeyPatch, mutation: str | None) -> None:
    roots, directory, request = setup_run
    result_path = directory / "phase-prepare-result.json"
    write_json(result_path, {"phase": "derived_price_preparation"})
    receipt = directory / "run-prepare-receipt.json"
    write_json(
        receipt,
        {
            "schema": "run-receipt.v1",
            "run_id": request["run_id"],
            "code": request["source"]["code"],
            "parameters": {"source_id": request["source"]["source_id"], "input_id": "synthetic-input"},
            "results": {
                "phase_result": {"path": str(result_path), "bytes": result_path.stat().st_size, "sha256": file_digest(result_path)},
            },
        },
    )
    response = directory / "response-prepare.json"
    saved = {
        "schema": "pattern-scan-coordinator-receipt.v2",
        "complete": True,
        "request_id": object_digest(request),
        "source_id": request["source"]["source_id"],
        "input_id": "synthetic-input",
        "run_receipt_path": str(receipt),
        "run_receipt_sha256": file_digest(receipt),
        "result": {"phase": "derived_price_preparation"},
    }
    if mutation == "response":
        saved["complete"] = False
    elif mutation == "source":
        saved["source_id"] = "other-source"
    elif mutation == "phase":
        saved["result"] = {"phase": "fake-complete-study"}
    write_json(response, saved)
    monkeypatch.setattr(run, "assert_current_code", _forbidden)
    monkeypatch.setattr(run, "fingerprint_inputs", _forbidden)
    monkeypatch.setattr(run_receipt, "producer_data_root", _forbidden)
    if mutation == "request":
        request = {**request, "run_id": "other"}
    elif mutation == "result":
        result_path.write_bytes(b"corrupted result")
    elif mutation == "receipt":
        receipt.write_bytes(receipt.read_bytes() + b" ")
    if mutation is None:
        assert run.verify_completion(response, request, roots)["complete"] is True
    else:
        with pytest.raises(ValueError, match="identity|incomplete"):
            run.verify_completion(response, request, roots)


def test_large_phase_result_and_response_verify_real_hashes_without_producer(setup_run: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    roots, directory, request = setup_run
    # Reader-size fixture only: this is metadata, with no market payload or read.
    result = {"phase": "derived_price_preparation", "reader_size_fixture_diagnostic": "x" * 8_000_001}
    result_path = directory / "phase-prepare-result.json"
    write_json(result_path, result)
    receipt_path = directory / "run-prepare-receipt.json"
    write_json(
        receipt_path,
        {
            "schema": "run-receipt.v1",
            "run_id": request["run_id"],
            "code": request["source"]["code"],
            "parameters": {"source_id": request["source"]["source_id"], "input_id": "synthetic-input"},
            "results": {"phase_result": {"path": str(result_path), "bytes": result_path.stat().st_size, "sha256": file_digest(result_path)}},
        },
    )
    response = directory / "response-prepare.json"
    saved = {
        "schema": "pattern-scan-coordinator-receipt.v2",
        "complete": True,
        "request_id": object_digest(request),
        "source_id": request["source"]["source_id"],
        "input_id": "synthetic-input",
        "run_receipt_path": str(receipt_path),
        "run_receipt_sha256": file_digest(receipt_path),
        "result": result,
    }
    write_json(response, saved)
    for path in (result_path, response):
        assert path.stat().st_size > 8_000_000
        with pytest.raises(ValueError, match="size limit"):
            read_json(path)
    monkeypatch.setattr(run, "assert_current_code", _forbidden)
    monkeypatch.setattr(run, "fingerprint_inputs", _forbidden)
    monkeypatch.setattr(run, "load_live_inputs", _forbidden)
    monkeypatch.setattr(run, "producer_data_root", _forbidden)
    monkeypatch.setattr(run_receipt, "producer_data_root", _forbidden)
    original = run.read_scan_receipt
    observed: set[Path] = set()

    def scan_reader(path: Path) -> dict[str, Any]:
        observed.add(path)
        return original(path)

    monkeypatch.setattr(run, "read_scan_receipt", scan_reader)
    assert run.verify_completion(response, request, roots)["result"] == result
    assert {result_path, response}.issubset(observed)
    # Keep the response/result semantically equal while invalidating the real
    # retained byte hash. Equality checks alone would miss this legal whitespace.
    result_path.write_bytes(canonical(result) + b" ")
    with pytest.raises(ValueError, match="identity|incomplete"):
        run.verify_completion(response, request, roots)


@pytest.mark.parametrize("mode", ["prepare", "stock", "all"])
@pytest.mark.parametrize("plan_kind", ["missing", "unknown"])
def test_public_launch_refuses_unestablished_capacity_before_child(setup_run: Any, monkeypatch: pytest.MonkeyPatch, mode: str, plan_kind: str) -> None:
    roots, directory, request = setup_run
    monkeypatch.setattr(DataRoots, "validate_worktree", lambda *args: None)
    monkeypatch.setattr(run, "require_capacity", capacity.require_capacity)
    monkeypatch.setattr(run, "git_source_identity", lambda root: request["source"])
    monkeypatch.setattr(run, "producer_data_root", lambda: Path(request["producer_root"]))
    monkeypatch.setattr(run, "_MemoryBoundJob", _forbidden)
    plan_path = None
    if plan_kind == "unknown":
        plan_path = directory / "capacity.json"
        write_json(
            plan_path,
            {
                "schema": "pattern-scan-capacity.v2",
                "reserve_bytes": 1,
                "components": {name: {"estimated_bytes": None, "evidence": "unknown synthetic estimate"} for name in capacity.COMPONENTS},
            },
        )
    with pytest.raises(ValueError, match="capacity"):
        run.launch(roots, mode=mode, run_id="synthetic", calculation_authorized=True, capacity_path=plan_path)


def test_public_launch_uses_normal_git_bootstrap_and_bounded_job(setup_run: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    roots, directory, request = setup_run
    monkeypatch.setattr(DataRoots, "validate_worktree", lambda *args: None)
    monkeypatch.setattr(run, "git_source_identity", lambda root: request["source"])
    monkeypatch.setattr(run, "producer_data_root", lambda: Path(request["producer_root"]))
    monkeypatch.setattr(run, "host_resources", lambda: {"physical_available_bytes": 16 * 1024**3})
    events: list[Any] = []

    class Job:
        def __init__(self, limit: int) -> None:
            self.limit = limit
            events.append(("limit", limit))

        def start(self, command: list[str], cwd: Path) -> Any:
            events.append(("start", command, cwd))
            path = Path(command[-1])
            packet = read_json(path)
            result_path = path.with_name("phase-profile-result.json")
            write_json(result_path, {"phase": "resource_profile"})
            receipt = path.with_name("run-profile-receipt.json")
            write_json(
                receipt,
                {
                    "schema": "run-receipt.v1",
                    "run_id": packet["run_id"],
                    "code": packet["source"]["code"],
                    "parameters": {"source_id": packet["source"]["source_id"], "input_id": "synthetic-input"},
                    "results": {
                        "phase_result": {"path": str(result_path), "bytes": result_path.stat().st_size, "sha256": file_digest(result_path)},
                    },
                },
            )
            write_json(
                path.with_name("response-profile.json"),
                {
                    "schema": "pattern-scan-coordinator-receipt.v2",
                    "complete": True,
                    "request_id": object_digest(packet),
                    "source_id": packet["source"]["source_id"],
                    "input_id": "synthetic-input",
                    "run_receipt_path": str(receipt),
                    "run_receipt_sha256": file_digest(receipt),
                    "result": {"phase": "resource_profile"},
                },
            )

            class Process:
                returncode = 0

                def poll(self) -> int:
                    return 0

            return Process()

        def memory_receipt(self) -> dict[str, Any]:
            return {"limit_bytes": self.limit, "peak_committed_bytes": 1024, "scope": "virtual memory committed across this owned Windows job"}

        def terminate_and_confirm(self) -> None:
            events.append("terminated")

        def close(self) -> None:
            events.append("closed")

    monkeypatch.setattr(run, "_MemoryBoundJob", Job)
    kwargs: dict[str, Any] = {
        "mode": "profile",
        "run_id": "synthetic",
        "calculation_authorized": True,
        "memory_bytes": 1024**3,
        "job_memory_bytes": 2 * 1024**3,
        "timeout_seconds": 60,
    }
    saved = run.launch(roots, **kwargs)
    command, cwd = events[1][1:]
    assert command[2] == run.GIT_BOOTSTRAP
    assert command[3] == str(run.ROOT) and cwd == run.ROOT
    assert saved["coordinator_job_memory"]["limit_bytes"] == 2 * 1024**3
    assert events[-2:] == ["terminated", "closed"]
    assert (directory / "request-profile.json").is_file()
    monkeypatch.setattr(run, "_MemoryBoundJob", _forbidden)
    monkeypatch.setattr(run, "producer_data_root", _forbidden)
    assert run.launch(roots, **kwargs)["complete"] is True
    with pytest.raises(ValueError, match="parameters differ"):
        run.launch(roots, **{**kwargs, "timeout_seconds": 61})


def test_cli_forwards_explicit_paths_authorization_timeout_and_producer_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    producer = tmp_path / "producer"
    monkeypatch.setenv(cli.ENV_KEY, "old-process-value")
    captured = {}

    def launch(roots: DataRoots, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        assert roots.primary == primary
        assert os.environ[cli.ENV_KEY] == str(producer)
        return {"complete": True, "result": {"phase": "complete_pattern_scan"}, "source_id": "synthetic"}

    monkeypatch.setattr(cli, "launch", launch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pattern_scan_live",
            "all",
            "--primary-root",
            str(primary),
            "--data-root",
            str(primary / "research_data"),
            "--producer-root",
            str(producer),
            "--run-id",
            "same-run",
            "--prepared",
            str(tmp_path / "prepared.json"),
            "--profile",
            str(tmp_path / "profile.json"),
            "--capacity-plan",
            str(tmp_path / "capacity.json"),
            "--timeout-seconds",
            "123",
            "--calculation-authorized",
        ],
    )
    cli.main()
    assert captured == {
        "mode": "all",
        "run_id": "same-run",
        "calculation_authorized": True,
        "prepared_path": tmp_path / "prepared.json",
        "profile_path": tmp_path / "profile.json",
        "capacity_path": tmp_path / "capacity.json",
        "timeout_seconds": 123.0,
    }
    assert json.loads(capsys.readouterr().out) == {"complete": True, "phase": "complete_pattern_scan", "source_id": "synthetic"}


def _deferred_stock_case(setup_run: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[DataRoots, Path, dict[str, Any], list[Any]]:
    from research_core import pattern_scan_analysis_v1 as analysis

    roots, directory, request = setup_run
    index = _prepared(directory, request)
    profile_path = directory / "resource-profile.json"
    profile = {
        "selected": {
            "workers": 4,
            "memory_cap_bytes": 6 * 1024**3,
            "estimated_worker_bytes": 512 * 1024**2,
            "stocks_per_process": 1,
            "timeout_seconds": 600,
        },
        "observation_provenance": {"fixture": "retained stock measurement"},
    }
    write_json(profile_path, profile)
    request.update(
        mode="stock",
        publication_policy="results-only-deferred.v3",
        prepared_path=str(index),
        profile_path=str(profile_path),
        memory_bytes=6 * 1024**3,
        job_memory_bytes=8 * 1024**3,
    )
    events: list[Any] = []

    def capacity_gate(packet: dict[str, Any], supplied_roots: DataRoots, *, input_id: str | None = None) -> None:
        assert supplied_roots == roots and packet["source"] == request["source"]
        assert input_id in {None, "synthetic-input"}
        events.append(("capacity", input_id))

    def execution_profile(packet: dict[str, Any], prepared: dict[str, Any]) -> dict[str, Any]:
        assert packet == request and Path(packet["prepared_path"]) == index
        assert packet["profile_path"] == str(profile_path)
        assert prepared == read_json(index)
        events.append("profile")
        return profile

    def stock_pool(packets: list[dict[str, Any]], **limits: Any) -> dict[str, Any]:
        assert packets == [{**packet, "run_root": str(directory)} for packet in read_json(index)["requests"]]
        assert limits == {
            "workers": 4,
            "memory_bytes": 6 * 1024**3,
            "estimated_worker_bytes": 512 * 1024**2,
            "stocks_per_process": 1,
            "timeout_seconds": 600,
        }
        events.append("pool")
        return {"results": [{"code": "0001"}]}

    def verified(results: list[dict[str, Any]], *, source: dict[str, Any], input_id: str) -> dict[str, Path]:
        assert results == [{"code": "0001"}] and source == request["source"] and input_id == "synthetic-input"
        events.append("verified")
        return {"0001": directory / "parts/0001"}

    monkeypatch.setattr(run, "_capacity", capacity_gate)
    monkeypatch.setattr(run, "_execution_profile", execution_profile)
    monkeypatch.setattr(run, "fingerprint_inputs", _stub_fingerprint)
    monkeypatch.setattr(run, "read_frame", lambda path: None)
    monkeypatch.setattr(run, "run_requests", stock_pool)
    monkeypatch.setattr(run, "verified_parts", verified)
    monkeypatch.setattr(run, "build_barrier", _forbidden)
    monkeypatch.setattr(run, "publish_stock_versions", _forbidden)
    monkeypatch.setattr(analysis, "run_analysis", _forbidden)
    return roots, directory, request, events


def test_deferred_stock_stops_after_verified_parts_without_global_admission(setup_run: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    roots, directory, request, events = _deferred_stock_case(setup_run, monkeypatch)
    path = directory / "request-stock.json"
    write_json(path, request)
    run.coordinator_main(path)
    assert events == [("capacity", None), "profile", ("capacity", "synthetic-input"), "pool", "verified"]
    saved = run.verify_completion(directory / "response-stock.json", request, roots)
    result = saved["result"]
    assert result["phase"] == "full_stock_checkpoints" and result["global_analysis_admitted"] is False
    assert result["resource_observation"] == {"fixture": "retained stock measurement"}
    assert not {"barrier", "shared_versions", "analysis"}.intersection(result)
    assert not (directory / "global").exists()
    assert not (roots.primary / "research_cache").exists()


def test_deferred_prepare_actual_input_capacity_mismatch_precedes_any_price_write(setup_run: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from research_core import pattern_scan_capacity_v3 as phase_capacity

    roots, directory, request = setup_run
    profile = directory / "resource-profile.json"
    write_json(profile, {"input_id": "planned-input"})
    plan_path = directory / "capacity-prepare.json"
    write_json(
        plan_path,
        {
            "schema": phase_capacity.SCHEMA,
            "phase": "prepare",
            "publication_policy": "results-only-deferred.v3",
            "source_id": request["source"]["source_id"],
            "input_id": "planned-input",
            "profile": {"path": str(profile), "bytes": profile.stat().st_size, "sha256": file_digest(profile)},
            "geometry": {"calendar_n": 4110, "ordinary_reference_n": 1942},
            "reserve_bytes": 32 * 1024**3,
            "components": {name: {"estimated_bytes": 0, "evidence": "synthetic explicit budget"} for name in phase_capacity.PHASE_COMPONENTS["prepare"]},
        },
    )
    request.update(publication_policy="results-only-deferred.v3", profile_path=str(profile), capacity_path=str(plan_path))

    class Snapshot:
        inventory = pd.DataFrame({"included": [True] * 1942, "code": [f"{i:04}" for i in range(1942)]})
        input_id = "actual-changed-input"
        calendar = list(range(4110))

    events: list[Any] = []
    original_gate = run._capacity

    def capacity_gate(packet: dict[str, Any], supplied_roots: DataRoots, *, input_id: str | None = None) -> None:
        events.append(("capacity", input_id))
        original_gate(packet, supplied_roots, input_id=input_id)

    def execution_profile(packet: dict[str, Any], prepared: dict[str, Any]) -> dict[str, Any]:
        assert prepared == {"input_id": Snapshot.input_id, "calendar_n": 4110, "ordinary_reference_n": 1942}
        events.append("actual-input-profile-check")
        return {}

    monkeypatch.setattr(run, "_capacity", capacity_gate)
    monkeypatch.setattr(run, "_execution_profile", execution_profile)
    monkeypatch.setattr(phase_capacity.shutil, "disk_usage", lambda path: SimpleNamespace(free=64 * 1024**3))
    monkeypatch.setattr(run, "producer_data_root", lambda: Path(request["producer_root"]))
    monkeypatch.setattr(run, "load_live_inputs", lambda *args, **kwargs: Snapshot())
    monkeypatch.setattr(run, "representative_codes", lambda snapshot: (("0001",), {}))
    monkeypatch.setattr(run, "prepare_requests", _forbidden)
    monkeypatch.setattr(run, "write_frame", _forbidden)
    monkeypatch.setattr(run, "_derived_inputs", _forbidden)
    path = directory / "request-prepare.json"
    write_json(path, request)
    with pytest.raises(ValueError, match="source/input/phase/publication policy differs"):
        run.coordinator_main(path)
    assert events == [("capacity", None), "actual-input-profile-check", ("capacity", Snapshot.input_id)]
    assert not (directory / "prepared").exists()
    assert not (directory / "derived-preparation.json").exists()
    assert not (directory / "producer-read-receipt.json").exists()


def test_deferred_launch_existing_active_owner_blocks_job_start(setup_run: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    roots, directory, request = setup_run
    monkeypatch.setattr(DataRoots, "validate_worktree", lambda *args: None)
    monkeypatch.setattr(run, "git_source_identity", lambda root: request["source"])
    monkeypatch.setattr(run, "_capacity", lambda packet, roots: None)
    monkeypatch.setattr(run, "host_resources", lambda: {"physical_available_bytes": 16 * 1024**3})
    monkeypatch.setattr(run, "_MemoryBoundJob", _forbidden)
    marker = directory / ".scan-active.json"
    write_json(marker, {"owner": "existing-owner", "request_id": "existing-request"})
    before = marker.read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        run.launch(roots, mode="stock", run_id="synthetic", calculation_authorized=True)
    assert marker.read_bytes() == before


@pytest.mark.parametrize("child_exit", (0, 5))
def test_deferred_launch_job_owns_active_marker_until_confirmed_termination(setup_run: Any, monkeypatch: pytest.MonkeyPatch, child_exit: int) -> None:
    roots, directory, request, events = _deferred_stock_case(setup_run, monkeypatch)
    marker = directory / ".scan-active.json"
    monkeypatch.setattr(DataRoots, "validate_worktree", lambda *args: None)
    monkeypatch.setattr(run, "git_source_identity", lambda root: request["source"])
    monkeypatch.setattr(run, "host_resources", lambda: {"physical_available_bytes": 16 * 1024**3})
    write_json(directory / "request-stock.json", request)

    class Job:
        def __init__(self, limit: int) -> None:
            assert limit == 8 * 1024**3
            assert marker.is_file()

        def start(self, command: list[str], cwd: Path) -> Any:
            assert command[2] == run.GIT_BOOTSTRAP and cwd == run.ROOT
            packet = read_json(Path(command[-1]))
            assert read_json(marker)["request_id"] == object_digest(packet)
            if child_exit == 0:
                run.coordinator_main(Path(command[-1]))

            class Process:
                returncode = child_exit

                def poll(self) -> int:
                    return child_exit

            return Process()

        def memory_receipt(self) -> dict[str, Any]:
            assert marker.is_file()
            return {"limit_bytes": 8 * 1024**3, "peak_committed_bytes": 1024, "scope": "virtual memory committed across this owned Windows job"}

        def terminate_and_confirm(self) -> None:
            assert marker.is_file()
            events.append("terminated")

        def close(self) -> None:
            assert marker.is_file()
            events.append("closed")

    monkeypatch.setattr(run, "_MemoryBoundJob", Job)
    kwargs: dict[str, Any] = {
        "mode": "stock",
        "run_id": "synthetic",
        "calculation_authorized": True,
        "prepared_path": Path(request["prepared_path"]),
        "profile_path": Path(request["profile_path"]),
        "memory_bytes": 6 * 1024**3,
        "job_memory_bytes": 8 * 1024**3,
        "timeout_seconds": 60,
    }
    if child_exit == 0:
        saved = run.launch(roots, **kwargs)
        assert saved["result"]["phase"] == "full_stock_checkpoints"
        assert saved["result"]["global_analysis_admitted"] is False
        assert events[:3] == [("capacity", None), ("capacity", None), "profile"]
        assert ("capacity", "synthetic-input") in events
    else:
        with pytest.raises(ValueError, match="coordinator failed exit=5"):
            run.launch(roots, **kwargs)
    assert events[-2:] == ["terminated", "closed"]
    assert not marker.exists()
