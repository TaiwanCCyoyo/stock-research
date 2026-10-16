"""Actual owned Windows worker compilation from a physically sealed snapshot."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_core import pattern_scan_execution_v1 as execution
from research_core.artifact_store import file_digest, object_digest, read_json, verify_files, write_json
from research_core.pattern_scan_parquet_v1 import read_frame
from research_core.pattern_scan_source_snapshot_v1 import materialize_archive
from research_core.windows_process_job import WindowsProcessJob


@pytest.mark.skipif(sys.platform != "win32", reason="Actual startup-gated owned Windows Job worker")
def test_fresh_worker_compiles_materialized_archive_despite_later_source_copy_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    production_root = execution.ROOT
    closure = execution.source_identity(("research_core/pattern_scan_stock_v1.py",))
    source_copy = tmp_path / "synthetic-working-source"
    for name in closure["sources"]:
        path = source_copy / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((production_root / name).read_bytes())
    stock_copy = source_copy / "research_core" / "pattern_scan_stock_v1.py"
    # Instrument only the disposable copied module: the real stock calculation
    # remains intact, while its output witnesses the compiled module's path.
    stock_copy.write_bytes(
        stock_copy.read_bytes()
        + b"""

_synthetic_original_stock_phase = stock_phase
def stock_phase(*args, **kwargs):
    phase = _synthetic_original_stock_phase(*args, **kwargs)
    phase.prices["synthetic_compiled_source_path"] = __file__
    return phase
"""
    )
    monkeypatch.setattr(execution, "ROOT", source_copy)
    source = execution.source_identity(("research_core/pattern_scan_stock_v1.py",))
    archive = tmp_path / "executed-sources.zip"
    archive_sha256 = execution.write_source_archive(archive, source)
    implementation = materialize_archive(archive, tmp_path / "sealed-implementation", source, archive_sha256)
    assert implementation != source_copy
    snapshot_source = implementation / "research_core" / "pattern_scan_stock_v1.py"
    assert file_digest(snapshot_source) == source["sources"]["research_core/pattern_scan_stock_v1.py"]
    snapshot_before = {name: file_digest(implementation / name) for name in source["sources"]}
    # The mutable disposable copy is now unusable. Successful worker output
    # proves the dispatch did not import this later version of its source.
    stock_copy.write_bytes(b"raise RuntimeError('synthetic mutable source must not be loaded')\n")

    primary = tmp_path / "synthetic-primary"
    (primary / ".git").mkdir(parents=True)
    run = primary / ".tmp" / "pattern-scan-execution" / "snapshot-dispatch"
    prepared_directory = run / "prepared"
    prepared_directory.mkdir(parents=True)
    close = 30 + np.arange(80) * 0.1
    frame = pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 0.4,
            "Low": close - 0.4,
            "Close": close,
            "RawOpen": close - 0.1,
            "RawHigh": close + 0.4,
            "RawLow": close - 0.4,
            "RawClose": close,
            "VolumeLots": 1000.0,
            "Turnover": close * 1000,
            "Quality": True,
            "quality_reason": None,
        },
        index=pd.bdate_range("2020-01-01", periods=80),
    )
    prepared = prepared_directory / "0001.parquet"
    frame.to_parquet(prepared)
    prepared_sha256 = file_digest(prepared)
    stock_request = {
        "calculation_authorized": True,
        "source": source,
        "primary": str(primary),
        "data": str(primary / "research_data"),
        "run_root": str(run),
        "prepared_path": str(prepared),
        "prepared_sha256": prepared_sha256,
        "code": "0001",
        "industry_ref": "invented",
        "input_id": "synthetic-snapshot-dispatch.v1",
    }
    worker_directory = run / "workers" / "snapshot-worker"
    worker_directory.mkdir(parents=True)
    request_path, response_path = worker_directory / "request.json", worker_directory / "response.json"
    write_json(request_path, {"source": source, "stocks": [stock_request], "response_path": str(response_path)})
    job = WindowsProcessJob()
    try:
        process = job.start([sys.executable, "-c", execution.BOOTSTRAP, str(implementation), str(request_path)], implementation)
        assert process.wait(timeout=90) == 0
        response = read_json(response_path)
    finally:
        job.terminate_and_confirm()
        job.close()

    assert response["complete"] is True and response["schema"] == "pattern-scan-worker.v1"
    assert len(response["results"]) == 1
    receipt = response["results"][0]
    assert receipt["complete"] is True and receipt["code"] == "0001"
    assert receipt["source_id"] == source["source_id"]
    assert receipt["input_id"] == stock_request["input_id"]
    assert receipt["request_id"] == object_digest(stock_request)
    assert receipt["rows"]["prices"] == 80 and receipt["rows"]["base_labels"] == 160
    output = Path(receipt["output_path"])
    verify_files(output, receipt["artifacts"])
    assert read_json(output / "receipt.json") == receipt
    prices = read_frame(output / "prices.parquet")
    assert prices.synthetic_compiled_source_path.eq(str(snapshot_source)).all()
    compiled = response["loaded_project_sources"]
    assert {"research_core/pattern_scan_execution_v1.py", "research_core/pattern_scan_stock_v1.py", "research_core/cache_execution.py"} <= set(compiled)
    assert all(source["sources"][name] == digest for name, digest in compiled.items())
    assert snapshot_before == {name: file_digest(implementation / name) for name in source["sources"]}
    assert not list(implementation.rglob("__pycache__"))
    assert {path.relative_to(implementation).as_posix() for path in implementation.rglob("*") if path.is_file()} == set(source["sources"])
    assert file_digest(prepared) == prepared_sha256 and file_digest(archive) == archive_sha256
