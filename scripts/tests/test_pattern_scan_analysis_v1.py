"""Synthetic event-part, preregistered selector and summary orchestration."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core import pattern_scan_analysis_v1 as analysis
from research_core.artifact_store import describe_file, file_digest, object_digest, write_json
from research_core.hhhl_variants_selection import SelectionResult, split_for_code
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_count_matrix_v1 import aggregate_memberships
from research_core.pattern_scan_rates_v1 import REQUIRED_COLUMNS, summarize_events
from research_core.pattern_scan_stock_v1 import StockPhase, stock_phase

SOURCE: dict[str, Any] = {"source_id": "synthetic-source", "runtime": {"fixture": True}}


@pytest.fixture
def stock_parts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Path], dict[str, Any], dict[str, Any]]:
    def verify_source(source: dict[str, Any]) -> None:
        if source != SOURCE:
            raise ValueError("synthetic source changed")

    monkeypatch.setattr(analysis, "verify_source", verify_source)
    dates = pd.bdate_range("2020-01-01", periods=80)
    close = 30 + np.arange(80) * 0.1
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
        index=dates,
    )
    phase = stock_phase(
        frame, security_id="TW:0001", industry_ref="synthetic", ordinary_reference=True, definition_id=SOURCE["source_id"], input_id="synthetic-input"
    )
    directory = tmp_path / "part"
    directory.mkdir()
    artifacts = []
    for field in fields(StockPhase):
        path = directory / f"{field.name}.parquet"
        getattr(phase, field.name).to_parquet(path)
        artifacts.append(describe_file(directory, path))
    write_json(
        directory / "receipt.json",
        {"complete": True, "source_id": SOURCE["source_id"], "input_id": "synthetic-input", "request_id": "synthetic-request", "artifacts": artifacts},
    )
    global_values = pd.DataFrame(
        {
            "security_id": "TW:0001",
            "t0": dates.strftime("%Y-%m-%d"),
            "calendar_index": np.arange(80),
            "H": np.nan,
            "H_applicable": True,
            "J": 0,
            "K3": "middle",
            "MKT": "mixed",
        },
        index=dates,
    )
    for pattern in PATTERNS:
        global_values[f"PAT_other_{pattern}"] = np.int8(0)
    global_path = tmp_path / "global.parquet"
    global_values.to_parquet(global_path)
    barrier = {"global_files": {"0001": {"path": str(global_path), "sha256": file_digest(global_path)}}}
    entries = {"labels": {"version_id": "synthetic-labels", "manifest": {"sha256": object_digest({"labels": "invented"})}}}
    return {"0001": directory}, barrier, entries


def test_all_twelve_event_parts_label_pins_exact_resume_and_drift(stock_parts: tuple[dict[str, Path], dict[str, Any], dict[str, Any]], tmp_path: Path) -> None:
    parts, barrier, entries = stock_parts
    output = tmp_path / "events"
    first = analysis.prepare_event_parts(parts, barrier, entries, output, source=SOURCE, input_id="synthetic-input")
    assert set(first) == set(PATTERNS)
    retained = {path: (file_digest(path), path.stat().st_mtime_ns) for path in output.rglob("*") if path.is_file()}
    for stocks in first.values():
        events = pd.read_parquet(stocks["0001"] / "events.parquet")
        assert not events.duplicated(["event_id", "horizon"]).any()
        assert events.base_label_version_id.eq(entries["labels"]["version_id"]).all()
        assert events.base_label_manifest_sha256.eq(entries["labels"]["manifest"]["sha256"]).all()
    assert analysis.prepare_event_parts(parts, barrier, entries, output, source=SOURCE, input_id="synthetic-input") == first
    assert retained == {path: (file_digest(path), path.stat().st_mtime_ns) for path in output.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="source changed"):
        analysis.prepare_event_parts(parts, barrier, entries, output, source={"source_id": "changed"}, input_id="synthetic-input")
    (parts["0001"] / "prices.parquet").write_bytes(b"corrupt invented ancestor")
    with pytest.raises(ValueError):
        analysis.prepare_event_parts(parts, barrier, entries, output, source=SOURCE, input_id="synthetic-input")


def test_selector_uses_eligible_union_only_and_preserves_code_crc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis, "PATTERNS", ("B4",))
    features = {atom.feature_id for atom in analysis.atoms_for_pattern("B4")}
    observed = []
    original_selector = analysis.select_pattern_candidates

    def selector(target: str, events: Any, atoms: Any, **kwargs: Any) -> SelectionResult:
        observed.extend(events)
        return original_selector(target, events, atoms, **kwargs)

    def group_frame(directory: Path, group: str, horizon: int) -> pd.DataFrame:
        assert group == "pattern:union" and horizon == 126
        rows = pd.DataFrame({
            "event_id": [f"{directory.name}:eligible", f"{directory.name}:excluded"],
            "event_main_eligible": [True, False],
            "calendar_full": [True, True],
            "effective_label": ["hit", "hit"],
        })
        for feature in features:
            rows[f"{feature}_status"] = "feature_unknown"
            rows[f"{feature}_bin"] = None
        rows["G_status"], rows["G_bin"] = "known", "300to500"
        return rows

    monkeypatch.setattr(analysis, "select_pattern_candidates", selector)
    monkeypatch.setattr(analysis, "group_frame", group_frame)
    result = analysis.select_all({"B4": {code: tmp_path / code for code in ("0001", "0020", "3010")}})["B4"]
    assert result["selected_atoms"] == () and result["candidates"] == ()
    assert [row.code for row in observed] == ["0001", "0020", "3010"]
    counts = result["development_counts"]
    assert sum(counts[field] for field in ("hit", "loss", "flat_win")) == sum(split_for_code(code) == "development" for code in ("0001", "0020", "3010"))


def _summary_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Path]]:
    monkeypatch.setattr(analysis, "PATTERNS", ("B4",))
    directory = tmp_path / "summary-input"
    directory.mkdir()
    pd.DataFrame({"t0": ["2010-01-04"], "pattern:union": [1]}).to_parquet(directory / "daily_groups.parquet")
    write_json(directory / "receipt.json", {"complete": True, "artifacts": [describe_file(directory, directory / "daily_groups.parquet")]})
    return {"B4": {"0001": directory}}


def test_real_dense_counts_full_annual_dropyear_and_na_null_rates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parts = _summary_setup(tmp_path, monkeypatch)
    feeds: list[pd.DataFrame] = []

    class ObservedCounts(analysis.DenseCounts):
        def add_stock(self, matrix: pd.DataFrame) -> None:
            feeds.append(matrix.copy())
            super().add_stock(matrix)

    monkeypatch.setattr(analysis, "DenseCounts", ObservedCounts)

    def inventory(base: dict[str, Any], candidates: Any) -> tuple[dict[str, Any], ...]:
        return tuple(
            {**base, "feature_id": "G", "bin_id": status, "condition_status": status, "split": "all", "era": "all", "mkt": "all"}
            for status in ("known", "feature_unknown", "not_applicable")
        )

    def group_frame(directory: Path, group: str, horizon: int) -> pd.DataFrame:
        return pd.DataFrame(
            [
                ("TW:0001", "hit", "2010-01-04", horizon, "hit", True, True),
                ("TW:0001", "loss", "2011-01-04", horizon, "loss", True, True),
                ("TW:0001", "unknown", "2012-01-04", horizon, "unknown", True, False),
            ],
            columns=pd.Index(REQUIRED_COLUMNS),
        )

    def members(frame: pd.DataFrame, registered: Any, **kwargs: Any) -> pd.DataFrame:
        rows: list[dict[str, str]] = []
        for meta in registered:
            selected = (
                frame
                if meta["condition_status"] == "not_applicable"
                else frame.loc[frame.effective_label.eq("unknown") if meta["condition_status"] == "feature_unknown" else frame.effective_label.ne("unknown")]
            )
            rows.extend({"event_id": event, "cell_id": object_digest(meta)} for event in selected.event_id)
        return pd.DataFrame(rows)

    monkeypatch.setattr(analysis, "membership_inventory", inventory)
    monkeypatch.setattr(analysis, "group_frame", group_frame)
    monkeypatch.setattr(
        analysis, "StockCountPlan", lambda inventory, **kwargs: SimpleNamespace(matrix=lambda frame: aggregate_memberships(frame, members(frame, inventory)))
    )
    receipt = analysis.summarize_all(parts, {"B4": {"candidates": []}}, tmp_path / "summaries")
    assert len(feeds) == 2  # One complete stock feed per group/horizon, not one per event batch.
    assert all(frame.security_id.nunique() == 1 and not frame.duplicated(["cell_id", "year"]).any() for frame in feeds)
    summaries = pd.concat([pd.read_parquet(path) for name, path in receipt["files"].items() if name.startswith("summary/")])
    known = summaries.loc[summaries.condition_status.eq("known") & summaries.row_kind.eq("full")]
    assert known.known_n.eq(2).all() and known.hit_n.eq(1).all() and known.loss_n.eq(1).all() and known.hit_rate.eq(0.5).all()
    dropped = summaries.loc[summaries.condition_status.eq("known") & summaries.row_kind.eq("drop_best_year")]
    assert dropped.removed_year.eq(2010).all() and dropped.known_n.eq(1).all() and dropped.hit_rate.eq(0).all()
    na = summaries.loc[summaries.condition_status.eq("not_applicable")]
    assert na.loc[na.row_kind.eq("full"), "event_n"].eq(3).all()
    assert na.loc[na.row_kind.eq("drop_best_year"), "event_n"].eq(2).all()
    assert na.hit_rate.isna().all() and na.full_calendar_hit_upper_bound.isna().all()
    annual = pd.concat([pd.read_parquet(path) for name, path in receipt["files"].items() if name.startswith("annual/")])
    assert annual.loc[annual.condition_status.eq("known") & annual.year.eq(2010), "hit_n"].eq(1).all()
    assert annual.loc[annual.condition_status.eq("not_applicable"), "hit_rate"].isna().all()
    output = tmp_path / "summaries"
    before = {path: (file_digest(path), path.stat().st_mtime_ns) for path in output.rglob("*") if path.is_file()}
    resumed = analysis.summarize_all(parts, {"B4": {"candidates": []}}, output)
    assert resumed["files"] == receipt["files"]
    assert before == {path: (file_digest(path), path.stat().st_mtime_ns) for path in output.rglob("*") if path.is_file()}
    summary_file = next(Path(path) for name, path in receipt["files"].items() if name.startswith("summary/"))
    summary_file.write_bytes(b"corrupt synthetic summary")
    with pytest.raises(ValueError):
        analysis.summarize_all(parts, {"B4": {"candidates": []}}, output)


def test_parquet_chunks_keep_late_candidate_and_nullable_year_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parts = _summary_setup(tmp_path, monkeypatch)
    zero = summarize_events(pd.DataFrame(columns=pd.Index(REQUIRED_COLUMNS)))

    class EmptyCounts:
        memory_nbytes = 0

        def __init__(self, identifiers: Any, horizon: int) -> None:
            self.identifiers = identifiers

        def add_stock(self, matrix: pd.DataFrame) -> None:
            pass

        def summarize(self, cell: str) -> dict[str, Any]:
            return dict(zero)

        def drop_best_year(self, cell: str) -> tuple[int | None, dict[str, Any]]:
            return (2010 if cell == self.identifiers[-1] else None), dict(zero)

        def annual_summary(self, cell: str) -> tuple[dict[str, Any], ...]:
            return tuple(dict(zero) for _ in analysis.YEARS)

    def inventory(base: dict[str, Any], candidates: Any) -> tuple[dict[str, Any], ...]:
        rows = [
            {**base, "feature_id": "unconditional", "bin_id": str(i), "condition_status": "known", "split": "cross-check", "era": "all", "mkt": "all"}
            for i in range(2050)
        ]
        rows[-1].update(feature_id="candidate", candidate_id="late", candidate_atoms=[{"family": "VOL", "feature_id": "G", "bin_id": "300to500"}])
        return tuple(rows)

    monkeypatch.setattr(analysis, "DenseCounts", EmptyCounts)
    monkeypatch.setattr(analysis, "membership_inventory", inventory)
    monkeypatch.setattr(analysis, "group_frame", lambda *args: pd.DataFrame())
    monkeypatch.setattr(analysis, "StockCountPlan", lambda *args, **kwargs: SimpleNamespace(matrix=lambda frame: pd.DataFrame()))
    receipt = analysis.summarize_all(parts, {"B4": {"candidates": []}}, tmp_path / "chunked")
    for name, path in receipt["files"].items():
        if name.startswith("candidate-coverage/"):
            continue
        frame = pd.read_parquet(path)
        assert "candidate_atoms_json" in frame
        serialized = cast(pd.Series, frame.loc[frame.feature_id.eq("candidate"), "candidate_atoms_json"])
        assert serialized.map(lambda value: bool(json.loads(value))).all()
        if name.startswith("summary/"):
            assert len(frame) == 4100 and frame.loc[frame.row_kind.eq("full"), "removed_year"].isna().all()


def test_interrupted_summary_publication_retains_staging_and_resumes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parts = _summary_setup(tmp_path, monkeypatch)

    def inventory(base: dict[str, Any], candidates: Any) -> tuple[dict[str, Any], ...]:
        return ({**base, "feature_id": "unconditional", "bin_id": "all", "condition_status": "known", "split": "all", "era": "all", "mkt": "all"},)

    monkeypatch.setattr(analysis, "membership_inventory", inventory)
    monkeypatch.setattr(analysis, "group_frame", lambda *args: pd.DataFrame(columns=pd.Index(REQUIRED_COLUMNS)))

    def empty_matrix(frame: pd.DataFrame) -> pd.DataFrame:
        members = pd.DataFrame(columns=pd.Index(["event_id", "cell_id"]))
        return aggregate_memberships(frame, members)

    monkeypatch.setattr(analysis, "StockCountPlan", lambda *args, **kwargs: SimpleNamespace(matrix=empty_matrix))
    original = analysis.publish_noreplace

    def interrupted(source: Path, destination: Path) -> None:
        raise ValueError("synthetic interrupted final publication")

    monkeypatch.setattr(analysis, "publish_noreplace", interrupted)
    output = tmp_path / "interrupted"
    with pytest.raises(ValueError, match="interrupted"):
        analysis.summarize_all(parts, {"B4": {"candidates": []}}, output)
    assert list(output.iterdir()) and all(path.name.startswith(".staging-") for path in output.iterdir())
    monkeypatch.setattr(analysis, "publish_noreplace", original)
    receipt = analysis.summarize_all(parts, {"B4": {"candidates": []}}, output)
    assert all(Path(path).is_file() for path in receipt["files"].values())
    assert any(path.name.startswith(".staging-") for path in output.iterdir())
