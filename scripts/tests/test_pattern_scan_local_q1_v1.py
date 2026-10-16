from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, TypedDict

import numpy as np
import pandas as pd
import pytest

from research_core import pattern_scan_analysis_v1 as analysis
from research_core import pattern_scan_barrier_v1 as barrier_module
from research_core import pattern_scan_local_q1_v1 as local_q1
from research_core import run_receipt
from research_core.artifact_store import describe_file, file_digest, read_json, write_json
from research_core.pattern_scan_parquet_v1 import read_frame, write_frame
from research_core.pattern_scan_stock_v1 import StockPhase, stock_phase
from scripts import run_pattern_scan_local_q1 as cli

SOURCE: dict[str, str] = {"source_id": "synthetic-source", "schema": "synthetic"}
INPUT_ID = "synthetic-input"


class Q1Fixture(TypedDict):
    repo: Path
    run: Path
    stock_result: Path
    stock_part: Path
    global_path: Path
    legacy_root: Path
    calendar: pd.DatetimeIndex


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Q1Fixture:
    repo = tmp_path / "repo"
    run = repo / "original-run"
    stock_part = run / "stocks" / "0001"
    global_dir = run / "global"
    stock_part.mkdir(parents=True)
    global_dir.mkdir(parents=True)
    monkeypatch.setattr(barrier_module, "verify_source", lambda source: None)
    monkeypatch.setattr(analysis, "verify_source", lambda source: None)
    monkeypatch.setattr(local_q1, "code_identity", lambda repo_root: {"commit": "a" * 40, "dirty": False})
    monkeypatch.setattr(run_receipt, "code_identity", lambda repo_root: {"commit": "a" * 40, "dirty": False})
    monkeypatch.setattr(local_q1, "PATTERNS", ("B1",))
    monkeypatch.setattr(analysis, "PATTERNS", ("B1",))

    calendar = pd.bdate_range("2020-01-01", periods=365, name="date")
    close = 30.0 + np.arange(len(calendar), dtype=float) * 0.08
    raw = pd.DataFrame(
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
        index=calendar,
    )
    phase = stock_phase(
        raw,
        security_id="TW:0001",
        industry_ref="synthetic",
        ordinary_reference=True,
        definition_id=SOURCE["source_id"],
        input_id=INPUT_ID,
    )
    artifacts = []
    for field in fields(StockPhase):
        path = stock_part / f"{field.name}.parquet"
        with path.open("xb") as stream:
            write_frame(getattr(phase, field.name), stream, index=True)
        artifacts.append(describe_file(stock_part, path))
    stock_row: dict[str, Any] = {
        "code": "0001",
        "complete": True,
        "source_id": SOURCE["source_id"],
        "input_id": INPUT_ID,
        "request_id": "synthetic-request",
        "output_path": str(stock_part),
        "rows": {"cohort_events": len(phase.cohort_events)},
        "artifacts": artifacts,
    }
    write_json(stock_part / "receipt.json", stock_row)
    preparation = {
        "source": SOURCE,
        "input_id": INPUT_ID,
        "producer_fingerprint": {"inputs": {"synthetic": "fingerprint"}},
        "ordinary_reference_n": 1,
        "calendar_n": len(calendar),
    }
    write_json(run / "derived-preparation.json", preparation)
    stock_result = run / "phase-stock-result.json"
    write_json(stock_result, {"phase": "full_stock_checkpoints", "pool": {"complete": True, "results": [stock_row]}})

    global_path = global_dir / "0001.parquet"
    global_frame = pd.DataFrame(
        {
            "security_id": "TW:0001",
            "t0": calendar.strftime("%Y-%m-%d"),
            "calendar_index": np.arange(len(calendar)),
            "H": np.nan,
            "H_applicable": True,
            "J": 0,
            "K3": "middle",
            "MKT": "mixed",
        },
        index=calendar,
    )
    with global_path.open("xb") as stream:
        write_frame(global_frame, stream, index=True)
    write_json(
        global_dir / "receipt.json",
        {
            "complete": True,
            "source_id": SOURCE["source_id"],
            "input_id": INPUT_ID,
            "calendar": calendar.strftime("%Y-%m-%d").tolist(),
            "global_files": {"0001": {"path": str(global_path), "sha256": file_digest(global_path)}},
        },
    )
    legacy_root = run / "legacy-events"
    labels = barrier_module.checkpoint_label_entry({"0001": stock_part}, source=SOURCE, input_id=INPUT_ID)
    analysis.prepare_event_parts(
        {"0001": stock_part},
        {"global_files": {"0001": {"path": str(global_path), "sha256": file_digest(global_path)}}},
        {"labels": labels},
        legacy_root,
        source=SOURCE,
        input_id=INPUT_ID,
    )
    return {
        "repo": repo,
        "run": run,
        "stock_result": stock_result,
        "stock_part": stock_part,
        "global_path": global_path,
        "legacy_root": legacy_root,
        "calendar": calendar,
    }


def _run(fixture: Q1Fixture, output: Path, reuse: tuple[Path, ...] = (), targets: tuple[str, ...] | None = None) -> dict[str, Any]:
    return local_q1.run_local_q1(fixture["stock_result"], output, repo_root=fixture["repo"], reuse_event_roots=reuse, targets=targets)


def test_local_q1_projects_and_reuses_original_event_parts_exactly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    direct, reused = fixture["repo"] / ".tmp" / "direct", fixture["repo"] / ".tmp" / "reused"
    direct_manifest = _run(fixture, direct)
    reused_manifest = _run(fixture, reused, (fixture["legacy_root"],), ("B1",))
    assert direct_manifest["targets"] == reused_manifest["targets"] == ["B1"]
    assert direct_manifest["observations"][0]["new_in_memory_projections"] == 1
    assert direct_manifest["observations"][0]["reused_stock_parts"] == 0
    assert reused_manifest["observations"][0]["new_in_memory_projections"] == 0
    assert reused_manifest["observations"][0]["reused_stock_parts"] == 1
    for output in (direct, reused):
        summary = read_frame(output / "B1-summary.parquet")
        annual = read_frame(output / "B1-annual.parquet")
        pd.testing.assert_frame_equal(summary, read_frame(direct / "B1-summary.parquet"), check_exact=True)
        pd.testing.assert_frame_equal(annual, read_frame(direct / "B1-annual.parquet"), check_exact=True)
        manifest = read_json(output / "manifest.json")
        receipt = read_json(output / "B1-receipt.json")
        for name, record in receipt["results"].items():
            result_path = Path(record["path"])
            assert not result_path.is_absolute()
            assert (output / result_path).is_file()
            assert file_digest(output / result_path) == record["sha256"]
        assert all((output / item["path"]).is_file() for item in manifest["artifacts"])
        assert (output / "run_receipt.json").is_file()
        assert {path.name for path in output.iterdir()} == {"B1-summary.parquet", "B1-annual.parquet", "B1-receipt.json", "manifest.json", "run_receipt.json"}
    reused_ref = reused_manifest["reused_event_receipts"]["B1/0001"]
    assert Path(reused_ref["path"]).is_absolute() and Path(reused_ref["path"]).is_file()


def test_local_q1_rejects_selected_source_hash_corruption_without_publishing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    with (fixture["stock_part"] / "cohort_events.parquet").open("ab") as stream:
        stream.write(b"corrupt synthetic source")
    output = fixture["repo"] / ".tmp" / "corrupt-result"
    with pytest.raises(ValueError):
        _run(fixture, output)
    assert not output.exists()


def test_local_q1_rejects_output_outside_repo_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    output = fixture["repo"] / "outside" / "result"
    with pytest.raises(ValueError, match=r"\.tmp"):
        _run(fixture, output)
    assert not output.exists()


def test_cli_passes_stock_result_output_and_reuse_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, Any] = {}

    def capture(stock_result: Path, output: Path, *, repo_root: Path, reuse_event_roots: tuple[Path, ...], targets: tuple[str, ...] | None) -> None:
        observed.update(stock_result=stock_result, output=output, repo_root=repo_root, reuse_event_roots=reuse_event_roots, targets=targets)

    monkeypatch.setattr(cli, "run_local_q1", capture)
    monkeypatch.setattr(
        "sys.argv", ["run_pattern_scan_local_q1", "--stock-result", "stock.json", "--output", ".tmp/q1", "--reuse-event-root", "legacy", "--target", "B1"]
    )
    cli.main()
    assert observed["stock_result"] == Path("stock.json")
    assert observed["output"] == Path(".tmp/q1")
    assert observed["reuse_event_roots"] == (Path("legacy"),)
    assert observed["repo_root"] == Path(cli.__file__).resolve().parents[1]
    assert observed["targets"] == ("B1",)


@pytest.mark.parametrize("targets", [("B1", "B1"), ("unregistered",), ()])
def test_local_q1_rejects_invalid_family_batch(tmp_path: Path, targets: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="registered"):
        local_q1.run_local_q1(tmp_path / "stock.json", tmp_path / ".tmp" / "result", repo_root=tmp_path, targets=targets)
