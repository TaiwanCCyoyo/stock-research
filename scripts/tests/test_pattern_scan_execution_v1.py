"""Synthetic fresh-process source sealing and bounded stock execution."""

from __future__ import annotations

import sys
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core import pattern_scan_execution_v1 as execution
from research_core.artifact_store import file_digest, object_digest


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    original_root = execution.ROOT
    identity = execution.source_identity(("research_core/pattern_scan_stock_v1.py",))
    implementation = tmp_path / "implementation"
    for name in identity["sources"]:
        target = implementation / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((original_root / name).read_bytes())
    monkeypatch.setattr(execution, "ROOT", implementation)
    assert execution.source_identity(("research_core/pattern_scan_stock_v1.py",)) == identity
    return identity


def _requests(tmp_path: Path, source: dict[str, Any], name: str) -> list[dict[str, Any]]:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True, exist_ok=True)
    run = primary / ".tmp" / "pattern-scan-execution" / name
    (run / "prepared").mkdir(parents=True)
    result = []
    for ordinal, code in enumerate(("0001", "0020")):
        close = 30 + ordinal + np.arange(80) * 0.1
        frame = pd.DataFrame(
            {
                "Open": close - 0.1,
                "High": close + 0.4,
                "Low": close - 0.4,
                "Close": close,
                "RawClose": close,
                "RawOpen": close - 0.1,
                "RawHigh": close + 0.4,
                "RawLow": close - 0.4,
                "VolumeLots": 1000.0,
                "Turnover": close * 1000,
                "Quality": True,
                "quality_reason": None,
            },
            index=pd.bdate_range("2020-01-01", periods=80),
        )
        path = run / "prepared" / f"{code}.parquet"
        frame.to_parquet(path)
        result.append({
            "calculation_authorized": True,
            "source": source,
            "primary": str(primary),
            "data": str(primary / "research_data"),
            "run_root": str(run),
            "prepared_path": str(path),
            "prepared_sha256": file_digest(path),
            "code": code,
            "industry_ref": "invented",
            "input_id": "synthetic-input.v1",
        })
    return result


def _run(requests: list[dict[str, Any]], workers: int) -> dict[str, Any]:
    return execution.run_requests(requests, workers=workers, memory_bytes=1024**3, estimated_worker_bytes=256 * 1024**2, timeout_seconds=60)


def test_closure_has_parent_h1_raw_sources_and_lazy_imports(sealed: dict[str, Any]) -> None:
    expected = {
        "research_core/__init__.py",
        "research_core/pattern_scan_stock_v1.py",
        "research_core/patterns/h1/__init__.py",
        "research_core/patterns/hhhl/sources.json",
        "research_core/patterns/hhhl/v4/sources.zip",
        "research_core/cache_execution.py",
    }
    assert expected <= sealed["sources"].keys()
    entry = execution.ROOT / "research_core/synthetic_entry.py"
    lazy = execution.ROOT / "research_core/synthetic_lazy.py"
    entry.write_bytes(b"def call():\n    from research_core.synthetic_lazy import answer\n    return answer\n")
    lazy.write_bytes(b"answer = 42\n")
    identity = execution.source_identity(("research_core/synthetic_entry.py",))
    assert identity["sources"]["research_core/synthetic_lazy.py"] == file_digest(lazy)


def test_archive_preserves_raw_bytes_and_is_deterministic(sealed: dict[str, Any], tmp_path: Path) -> None:
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    assert execution.write_source_archive(first, sealed) == execution.write_source_archive(second, sealed)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == set(sealed["sources"])
        for name in archive.namelist():
            assert archive.read(name) == (execution.ROOT / name).read_bytes()


def test_invalid_identity_runtime_and_changed_copy_fail(sealed: dict[str, Any]) -> None:
    invalid = {**sealed, "source_id": "wrong"}
    with pytest.raises(ValueError, match="identity"):
        execution.verify_source(invalid)
    runtime = deepcopy(sealed)
    runtime["runtime"] = {"unavailable": True}
    runtime["source_id"] = object_digest({key: value for key, value in runtime.items() if key != "source_id"})
    with pytest.raises(ValueError, match="runtime"):
        execution.verify_source(runtime)
    (execution.ROOT / "research_core/pattern_scan_stock_v1.py").write_bytes(b"# modified synthetic copy\n")
    with pytest.raises(ValueError, match="source changed"):
        execution.verify_source(sealed)


def test_unauthorized_and_changed_prepared_reject_before_workers(sealed: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    requests = _requests(tmp_path, sealed, "invalid")

    def forbidden_job() -> None:
        pytest.fail("invalid input must not create a worker")

    monkeypatch.setattr(execution, "WindowsProcessJob", forbidden_job)
    monkeypatch.setattr(execution, "host_resources", lambda: {"physical_available_bytes": 8 * 1024**3})
    requests[0]["calculation_authorized"] = False
    with pytest.raises(PermissionError, match="authorization"):
        _run(requests, 1)
    requests[0]["calculation_authorized"] = True
    Path(requests[0]["prepared_path"]).write_bytes(b"changed invented input")
    with pytest.raises(ValueError, match="prepared input"):
        _run(requests, 1)
    assert not (Path(requests[0]["run_root"]) / "parts").exists()
    assert not (Path(requests[0]["run_root"]) / "workers").exists()


def test_memory_reserve_and_stale_direct_entry_reject(sealed: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    requests = _requests(tmp_path, sealed, "stale")
    monkeypatch.setattr(execution, "host_resources", lambda: {"physical_available_bytes": None})
    with pytest.raises(ValueError, match="reserve"):
        _run(requests, 1)
    with pytest.raises(ValueError, match="loaded implementation"):
        execution._execute_stock_in_process(requests[0])
    assert not (Path(requests[0]["run_root"]) / "parts").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Actual owned Windows Job execution")
def test_actual_serial_parallel_compiled_bytes_cap_and_receipt_reuse(sealed: dict[str, Any], tmp_path: Path) -> None:
    serial_requests = _requests(tmp_path, sealed, "serial")
    parallel_requests = _requests(tmp_path, sealed, "parallel")
    serial, parallel = _run(serial_requests, 1), _run(parallel_requests, 2)
    assert serial["peak_inflight"] == 1 and parallel["peak_inflight"] <= 2
    for left, right in zip(serial["results"], parallel["results"], strict=True):
        assert left["code"] == right["code"] and left["rows"] == right["rows"]
        assert left["artifacts"] == right["artifacts"]
        assert left["rows"]["prices"] == 80
        assert left["rows"]["base_labels"] == 160
    for pool in (serial, parallel):
        for worker in pool["workers_receipts"]:
            assert worker["job_memory"]["limit_bytes"] == pool["memory_cap_bytes"] // pool["workers"]
            assert 0 < worker["job_memory"]["peak_committed_bytes"] <= worker["job_memory"]["limit_bytes"]
            compiled = worker["loaded_project_sources"]
            assert "research_core/pattern_scan_execution_v1.py" in compiled
            assert "research_core/pattern_scan_stock_v1.py" in compiled
            assert all(sealed["sources"][name] == digest for name, digest in compiled.items())
    retained = {
        str(path): (file_digest(path), path.stat().st_mtime_ns) for row in serial["results"] for path in Path(row["output_path"]).rglob("*") if path.is_file()
    }
    reused = _run(serial_requests, 1)
    assert reused["results"] == serial["results"]
    assert retained == {
        str(path): (file_digest(path), path.stat().st_mtime_ns) for row in reused["results"] for path in Path(row["output_path"]).rglob("*") if path.is_file()
    }


@pytest.mark.skipif(sys.platform != "win32", reason="Actual owned Windows Job execution")
def test_mid_calculation_source_mutation_never_publishes_success(sealed: dict[str, Any], tmp_path: Path) -> None:
    stock_source = execution.ROOT / "research_core/pattern_scan_stock_v1.py"
    stock_source.write_bytes(
        stock_source.read_bytes()
        + b"""

_original_stock_phase = stock_phase
def stock_phase(*args, **kwargs):
    from pathlib import Path
    phase = _original_stock_phase(*args, **kwargs)
    dependency = Path(__file__).parent / "pattern_scan_daily_values_v1.py"
    dependency.write_bytes(dependency.read_bytes() + b"\\n# synthetic mid-calculation change\\n")
    return phase
"""
    )
    source = execution.source_identity(("research_core/pattern_scan_stock_v1.py",))
    requests = _requests(tmp_path, source, "mid-source-change")
    prepared_before = {packet["prepared_path"]: file_digest(Path(packet["prepared_path"])) for packet in requests}
    with pytest.raises(ValueError, match="owned stock worker failed"):
        _run(requests, 1)
    assert prepared_before == {packet["prepared_path"]: file_digest(Path(packet["prepared_path"])) for packet in requests}
    run = Path(requests[0]["run_root"])
    parts = run / "parts"
    assert parts.exists() and list(parts.iterdir())
    assert all(path.name.startswith(".staging-") for path in parts.iterdir())
    assert not list(parts.rglob("receipt.json"))
    assert not list((run / "workers").rglob("response.json"))


@pytest.mark.parametrize("batch", (0, 9))
def test_invalid_batch_rejects_before_workers(sealed: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, batch: int) -> None:
    requests = _requests(tmp_path, sealed, "invalid-batch")

    def forbidden_job() -> None:
        pytest.fail("invalid batch must not create an owned process")

    monkeypatch.setattr(execution, "WindowsProcessJob", forbidden_job)
    with pytest.raises(ValueError, match="batch size"):
        execution.run_requests(requests, workers=1, memory_bytes=1024**3, estimated_worker_bytes=256 * 1024**2, timeout_seconds=60, stocks_per_process=batch)
    assert not (Path(requests[0]["run_root"]) / "workers").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Actual owned Windows Job execution")
def test_batched_reuse_has_one_worker_and_preserves_artifacts(sealed: dict[str, Any], tmp_path: Path) -> None:
    requests = _requests(tmp_path, sealed, "batch-reuse")
    original = _run(requests, 1)
    batched = execution.run_requests(requests, workers=1, memory_bytes=1024**3, estimated_worker_bytes=256 * 1024**2, timeout_seconds=60, stocks_per_process=2)
    assert batched["peak_inflight"] == 1 and len(batched["workers_receipts"]) == 1
    assert batched["results"] == original["results"]
    assert [row["code"] for row in batched["results"]] == ["0001", "0020"]
