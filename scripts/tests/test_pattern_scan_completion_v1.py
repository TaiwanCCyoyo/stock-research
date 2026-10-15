"""Synthetic Q4--Q6 orchestration with real stock/event bindings."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core import (
    pattern_scan_analysis_v1 as analysis,
)
from research_core import (
    pattern_scan_barrier_v1 as barrier_module,
)
from research_core import (
    pattern_scan_completion_v1 as completion,
)
from research_core import (
    pattern_scan_episode_run_v1 as episode_module,
)
from research_core.artifact_store import canonical, describe_file, file_digest, object_digest, read_json, write_json
from research_core.pattern_scan_followup_summary_v1 import (
    EXCLUSION_COLUMNS,
    FIRST_COLUMNS,
    FLAG_COLUMNS,
    LANDMARK_COLUMNS,
    PATH_COLUMNS,
    TRADEOFF_COLUMNS,
    FollowupSummaryTables,
)
from research_core.pattern_scan_followup_v1 import FollowupTables
from research_core.pattern_scan_stock_v1 import StockPhase, stock_phase

SOURCE: dict[str, Any] = {"source_id": "synthetic-source", "runtime": {"fixture": True}}


class TinyAccumulator:
    memory_nbytes = 0

    def __init__(self, groups: dict[str, str]) -> None:
        self.groups = groups

    def add_stock(self, tables: FollowupTables) -> None:
        assert all("event_id" in getattr(tables, field.name) for field in fields(FollowupTables))

    def finalize(self) -> FollowupSummaryTables:
        frames = []
        for columns in (PATH_COLUMNS, FIRST_COLUMNS, FLAG_COLUMNS, LANDMARK_COLUMNS, TRADEOFF_COLUMNS, EXCLUSION_COLUMNS):
            row: dict[str, Any] = dict.fromkeys(columns)
            row.update(group_id="B4", target_pattern_id="B4", horizon=126, split_id="development", era="all", mkt="all")
            frames.append(pd.DataFrame([row], columns=pd.Index(columns)))
        return FollowupSummaryTables(*frames)


@pytest.fixture
def fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Path], dict[str, Any], dict[str, dict[str, Path]], dict[str, Any], dict[str, Any]]:
    def verify_source(source: dict[str, Any]) -> None:
        if source != SOURCE:
            raise ValueError("synthetic source changed")

    for module in (completion, analysis, barrier_module, episode_module):
        monkeypatch.setattr(module, "verify_source", verify_source)
    for module in (completion, analysis, episode_module):
        monkeypatch.setattr(module, "PATTERNS", ("B4",))
    monkeypatch.setattr(completion, "FollowupAccumulator", TinyAccumulator)
    dates = pd.bdate_range("2020-01-01", periods=80)
    close = 30.0 + np.arange(80) * 0.1
    prices = pd.DataFrame(
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
        index=dates,
    )
    phase = stock_phase(
        prices, security_id="TW:0001", industry_ref="invented", ordinary_reference=True, definition_id=SOURCE["source_id"], input_id="synthetic-input"
    )
    part = tmp_path / "part"
    part.mkdir()
    artifacts = []
    for field in fields(StockPhase):
        path = part / f"{field.name}.parquet"
        getattr(phase, field.name).to_parquet(path)
        artifacts.append(describe_file(part, path))
    write_json(
        part / "receipt.json",
        {"complete": True, "source_id": SOURCE["source_id"], "input_id": "synthetic-input", "request_id": "synthetic-request", "artifacts": artifacts},
    )
    parts = {"0001": part}
    benchmark = pd.DataFrame({"Close": 100.0 + np.arange(80), "Quality": True, "quality_reason": None, "security_id": "TW:0050"}, index=dates)
    global_receipt = barrier_module.build_barrier(parts, benchmark, tmp_path / "barrier")
    entries = {"labels": {"version_id": "invented-labels", "manifest": {"sha256": object_digest({"labels": "invented"})}}}
    events = analysis.prepare_event_parts(parts, global_receipt, entries, tmp_path / "event-parts", source=SOURCE, input_id="synthetic-input")

    def episodes(*args: Any, **kwargs: Any) -> dict[str, Any]:
        output = args[5]
        output.mkdir(parents=True, exist_ok=True)
        path = output / "invented-episodes.parquet"
        if not path.exists():
            pd.DataFrame({"episode_id": ["invented"], "unknown": [True]}).to_parquet(path)
        return {"complete": True, "files": {"episodes.parquet": str(path)}}

    monkeypatch.setattr(completion, "run_episodes", episodes)
    return parts, global_receipt, events, {"B4": {"candidates": []}}, {"confirmation_top_input": []}


def _run(fixture: tuple[dict[str, Path], dict[str, Any], dict[str, dict[str, Path]], dict[str, Any], dict[str, Any]], output: Path) -> dict[str, Any]:
    return completion.complete_followup(*fixture, output, source=SOURCE, input_id="synthetic-input")


def test_complete_file_map_and_exact_resume_without_rewrite(
    fixture: tuple[dict[str, Path], dict[str, Any], dict[str, dict[str, Path]], dict[str, Any], dict[str, Any]], tmp_path: Path
) -> None:
    output = tmp_path / "completion"
    first = _run(fixture, output)
    assert first["complete"] is True and tuple(first["top_candidates"]["B4"]) == ()
    assert all(Path(path).is_file() for path in first["files"].values())
    assert all(Path(path).is_file() for path in first["episodes"]["files"].values())
    before = {path: (file_digest(path), path.stat().st_mtime_ns) for path in output.rglob("*") if path.is_file()}
    assert object_digest(_run(fixture, output)) == object_digest(first)
    assert before == {path: (file_digest(path), path.stat().st_mtime_ns) for path in output.rglob("*") if path.is_file()}


@pytest.mark.parametrize("kind", ("observations/", "B4/"))
def test_corrupt_cached_raw_or_summary_part_rejected(
    fixture: tuple[dict[str, Path], dict[str, Any], dict[str, dict[str, Path]], dict[str, Any], dict[str, Any]], tmp_path: Path, kind: str
) -> None:
    output = tmp_path / "corrupt"
    receipt = _run(fixture, output)
    path = next(Path(path) for name, path in receipt["files"].items() if name.startswith(kind))
    path.write_bytes(b"corrupt synthetic followup table")
    with pytest.raises(ValueError):
        _run(fixture, output)


def test_legal_context_sidecar_tamper_rejected_before_holding(
    fixture: tuple[dict[str, Path], dict[str, Any], dict[str, dict[str, Path]], dict[str, Any], dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = Path(fixture[1]["sidecars"]["context"]["path"])
    frame = pd.read_parquet(path)
    frame["MKT"] = "changed"
    frame.to_parquet(path)

    def forbidden_holding(*args: Any, **kwargs: Any) -> None:
        pytest.fail("tampered context must fail before holding calculations")

    monkeypatch.setattr(completion, "holding_values", forbidden_holding)
    with pytest.raises(ValueError):
        _run(fixture, tmp_path / "invalid-context")


def test_confirmation_top_id_not_in_selection_rejected(
    fixture: tuple[dict[str, Path], dict[str, Any], dict[str, dict[str, Path]], dict[str, Any], dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture[4]["confirmation_top_input"] = [
        {
            "pattern_id": "B4",
            "candidate_id": "not-selected",
            "horizon": 252,
            "split": "cross-check",
            "era": "all",
            "mkt": "all",
            "control_id": "pattern",
            "cohort_id": "union",
            "known_n": 1,
            "hit_n": 1,
        }
    ]
    monkeypatch.setattr(completion, "run_episodes", episode_module.run_episodes)
    with pytest.raises(ValueError, match="selected candidates"):
        _run(fixture, tmp_path / "invalid-top")


def test_large_holding_target_and_final_receipts_resume_through_scan_reader(
    fixture: tuple[dict[str, Path], dict[str, Any], dict[str, dict[str, Path]], dict[str, Any], dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "large-completion"
    first = _run(fixture, output)
    holding_path = next(output.glob("holding-*/receipt.json"))
    target_path = next(output.glob("summary-*/receipt.json"))
    final_path = output / "receipt.json"
    paths = {holding_path, target_path, final_path}
    for path in paths:
        receipt = read_json(path)
        # Reader-size fixture only; identity and payload descriptors are intact.
        receipt["reader_size_fixture_diagnostic"] = "x" * 8_000_001
        path.write_bytes(canonical(receipt))
        assert path.stat().st_size > 8_000_000
        with pytest.raises(ValueError, match="size limit"):
            read_json(path)
    before = {path: (file_digest(path), path.stat().st_mtime_ns) for path in paths}
    original = completion.read_scan_receipt
    observed: set[Path] = set()

    def scan_reader(path: Path) -> dict[str, Any]:
        observed.add(path)
        return original(path)

    def no_recompute(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("completed followup metadata resume must not recompute holding or observations")

    monkeypatch.setattr(completion, "read_scan_receipt", scan_reader)
    monkeypatch.setattr(completion, "holding_values", no_recompute)
    monkeypatch.setattr(completion, "followup_values", no_recompute)
    monkeypatch.setattr(TinyAccumulator, "finalize", no_recompute)
    resumed = _run(fixture, output)
    assert resumed["files"] == first["files"]
    assert resumed["reader_size_fixture_diagnostic"] == "x" * 8_000_001
    assert paths.issubset(observed)
    assert before == {path: (file_digest(path), path.stat().st_mtime_ns) for path in paths}
    summary_payload = next(Path(path) for name, path in first["files"].items() if name.startswith("B4/"))
    with summary_payload.open("ab") as stream:
        stream.write(b"large receipt fixture payload drift")
    with pytest.raises(ValueError, match="mismatch"):
        _run(fixture, output)
    assert file_digest(final_path) == before[final_path][0]
