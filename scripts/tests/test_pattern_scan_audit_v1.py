from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core import pattern_scan_audit_v1 as audit
from research_core import pattern_scan_barrier_v1 as barrier_module
from research_core.artifact_store import canonical, describe_file, file_digest, object_digest, read_json, write_json
from research_core.pattern_scan_daily_values_v1 import calculate_common_values
from research_core.pattern_scan_event_conditions_v1 import event_conditions
from research_core.pattern_scan_event_outcomes_v1 import EventIdentity
from research_core.pattern_scan_indicators_v1 import prepare_detector_frame
from research_core.pattern_scan_stock_v1 import EVENT_COLUMNS
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_legacy import existing_entries
from research_core.research_data_paths import DataRoots

SOURCE: dict[str, Any] = {"source_id": "invented-source", "runtime": {"fixture": True}}


def _reseal(directory: Path) -> None:
    receipt = read_json(directory / "receipt.json")
    receipt["artifacts"] = [describe_file(directory, path) for path in sorted(directory.glob("*.parquet"))]
    (directory / "receipt.json").write_bytes(canonical(receipt))


@pytest.fixture
def inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Path], dict[str, dict[str, Path]], dict[str, Any], dict[str, Any]]:
    monkeypatch.setattr(barrier_module, "verify_source", lambda source: None)
    monkeypatch.setattr(audit, "verify_barrier", lambda receipt: tmp_path)
    dates = pd.bdate_range("2020-01-01", periods=160)
    # Monotone supplied prices keep SR_a's "none" category homogeneous in this
    # transport fixture; mixed numeric/category transport belongs to producer.
    close = 100 + np.arange(160) * 0.05
    prepared = pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "RawClose": close,
            "VolumeLots": 1000.0,
            "Turnover": close * 1000,
            "Quality": True,
            "quality_reason": "",
        },
        index=dates,
    )
    indicators, pivots = prepare_detector_frame(prepared)
    common = calculate_common_values(indicators, pivots)
    global_values = pd.DataFrame({"H": np.nan, "H_applicable": True, "J": 0, "K3": "middle", "MKT": "mixed", "PAT_other_B4": np.int8(0)}, index=dates)
    merged = common.copy()
    for name in global_values:
        merged[name] = global_values[name]
    rows: list[dict[str, Any]] = []
    for t in reversed(range(140, 152)):
        identity = EventIdentity("TW:0001", cast(pd.Timestamp, dates[t]).strftime("%Y-%m-%d"), "B4", "B4", SOURCE["source_id"], "invented-input")
        row: dict[str, Any] = dict.fromkeys(EVENT_COLUMNS)
        row.update(
            security_id="TW:0001",
            event_id=identity.event_id,
            t0=identity.t0,
            calendar_index=t,
            pattern_id="B4",
            subtype_id="B4",
            cohort_id="union",
            window_start=t - 60,
            pivot=100.0,
            support=100.0,
            lower=99.0,
            details_json=json.dumps({"confirmation_index": t}),
            definition_id=SOURCE["source_id"],
            input_id="invented-input",
        )
        rows.append(row)
    raw = pd.DataFrame(rows, columns=pd.Index(EVENT_COLUMNS))
    conditions = event_conditions(raw, indicators, merged, target_pattern="B4")
    part = tmp_path / "stock"
    part.mkdir()
    for name, frame in (("raw_events", raw), ("indicators", indicators), ("pivots", pivots), ("common_values", common)):
        frame.to_parquet(part / f"{name}.parquet")
    write_json(
        part / "receipt.json",
        {"code": "0001", "complete": True, "source_id": SOURCE["source_id"], "input_id": "invented-input", "output_path": str(part), "artifacts": []},
    )
    _reseal(part)
    directory = tmp_path / "event"
    directory.mkdir()
    event_rows = pd.concat(
        [raw.assign(horizon=h, effective_label="unknown", calendar_full=False, event_main_eligible=False) for h in (126, 252)], ignore_index=True
    )
    event_rows.to_parquet(directory / "events.parquet")
    conditions.to_parquet(directory / "conditions.parquet")
    pd.DataFrame({"group_id": "pattern:union", "event_id": raw.event_id}).to_parquet(directory / "group_memberships.parquet")
    write_json(directory / "receipt.json", {"complete": True, "identity": {"source_id": SOURCE["source_id"], "input_id": "invented-input"}, "artifacts": []})
    _reseal(directory)
    global_path = tmp_path / "global.parquet"
    global_values.to_parquet(global_path)
    selections = {
        "B4": {
            "candidates": [{"candidate_id": f"candidate-{i}", "atoms": [{"family": "MA", "feature_id": "MA_b", "bin_id": "true"}]} for i in reversed(range(6))]
        }
    }
    return {"0001": part}, {"B4": {"0001": directory}}, selections, {"global_files": {"0001": {"path": str(global_path), "sha256": file_digest(global_path)}}}


def _build(inputs: tuple[dict[str, Path], dict[str, dict[str, Path]], dict[str, Any], dict[str, Any]]) -> audit.AuditTables:
    parts, event_parts, selections, barrier = inputs
    return audit.build_audit(parts, event_parts, selections, source=SOURCE, input_id="invented-input", barrier=barrier)


def test_deterministic_non_outcome_samples_conditions_and_candidate_loop(
    inputs: tuple[dict[str, Path], dict[str, dict[str, Path]], dict[str, Any], dict[str, Any]],
) -> None:
    result = _build(inputs)
    assert result.raw_events.calendar_index.tolist() == list(range(140, 150))
    assert result.cold_events.calendar_index.tolist() == list(range(140, 150))
    assert result.cold_events.effective_label.eq("unknown").all()
    assert result.conditions.matches.all()
    assert result.candidates.candidate_id.tolist() == [f"candidate-{i}" for i in range(5)]
    assert result.candidates.matches.all() and result.candidates.event_n.eq(12).all()
    assert all(len(json.loads(value)) == 12 for value in result.candidates.known_matching_event_ids_json)
    if not result.pivots.empty:
        assert (pd.to_datetime(result.pivots.confirmed_at) <= pd.to_datetime(result.pivots.t0)).all()


@pytest.mark.parametrize("damage", ("condition", "future_confirmation"))
def test_wrong_condition_or_future_confirmation_rejected(
    inputs: tuple[dict[str, Path], dict[str, dict[str, Path]], dict[str, Any], dict[str, Any]], damage: str
) -> None:
    directory = inputs[1]["B4"]["0001"]
    if damage == "condition":
        path = directory / "conditions.parquet"
        frame = pd.read_parquet(path)
        frame["G"] = 999.0
    else:
        path = directory / "events.parquet"
        frame = pd.read_parquet(path)
        frame["details_json"] = frame.calendar_index.map(lambda index: json.dumps({"confirmation_index": int(index) + 1}))
    frame.to_parquet(path)
    _reseal(directory)
    with pytest.raises(ValueError, match="condition differs|future.*confirmation"):
        _build(inputs)


def test_legacy_outer_overlap_keeps_missing_difference_and_unavailable() -> None:
    current = pd.DataFrame({"security_id": ["TW:0001", "TW:0001", "TW:0002"], "t0": ["2018-01-01", "2020-01-01", "2020-01-02"], "support": [10.0, 10.0, 20.0]})
    legacy = pd.DataFrame({"security_id": ["TW:0001", "TW:0003"], "t0": ["2020-01-01", "2020-01-03"], "support": [11.0, 30.0]})
    result = audit.legacy_overlap_audit(current, legacy)
    assert result.status.tolist() == ["different", "current_only", "legacy_only"]
    assert json.loads(result.metadata_differences_json.iloc[0])[0]["field"] == "support"
    unknown = audit.legacy_overlap_audit(current, None)
    assert unknown.status.tolist() == ["unknown"] and unknown.reason.tolist() == ["legacy_unavailable"]


def test_unselected_stocks_never_load_full_context_or_conditions(
    inputs: tuple[dict[str, Path], dict[str, dict[str, Path]], dict[str, Any], dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parts, event_parts, selections, global_barrier = inputs
    second_stock = tmp_path / "stock-second"
    second_stock.mkdir()
    raw = pd.read_parquet(parts["0001"] / "raw_events.parquet")
    raw["security_id"] = "TW:0020"
    raw["event_id"] = [EventIdentity("TW:0020", cast(Any, row).t0, "B4", "B4", SOURCE["source_id"], "invented-input").event_id for row in raw.itertuples()]
    raw.to_parquet(second_stock / "raw_events.parquet")
    write_json(
        second_stock / "receipt.json",
        {
            "code": "0020",
            "complete": True,
            "source_id": SOURCE["source_id"],
            "input_id": "invented-input",
            "output_path": str(second_stock),
            "artifacts": [describe_file(second_stock, second_stock / "raw_events.parquet")],
        },
    )
    second_event = tmp_path / "event-second"
    second_event.mkdir()
    projected = pd.concat([raw.assign(horizon=h) for h in (126, 252)], ignore_index=True)
    projected.to_parquet(second_event / "events.parquet")
    write_json(
        second_event / "receipt.json",
        {
            "complete": True,
            "identity": {"source_id": SOURCE["source_id"], "input_id": "invented-input"},
            "artifacts": [describe_file(second_event, second_event / "events.parquet")],
        },
    )
    parts["0020"] = second_stock
    event_parts["B4"]["0020"] = second_event
    selections["B4"]["candidates"] = []
    original_read = pd.read_parquet

    def bounded_read(path: Any, *args: Any, **kwargs: Any) -> pd.DataFrame:
        name = Path(path)
        if name.parent == second_stock and name.name != "raw_events.parquet" or name.parent == second_event and name.name != "events.parquet":
            pytest.fail("unselected stock context must not be materialized")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(audit.pd, "read_parquet", bounded_read)
    result = _build((parts, event_parts, selections, global_barrier))
    assert len(result.raw_events) == len(result.cold_events) == 10
    assert result.raw_events.security_id.eq("TW:0001").all()
    assert result.cold_events.security_id.eq("TW:0001").all()


@pytest.fixture
def legacy_catalog(tmp_path: Path) -> tuple[DataRoots, str, Path]:
    primary = tmp_path / "legacy-primary"
    (primary / ".git").mkdir(parents=True)
    roots = DataRoots(primary, primary / "research_data")
    directory = primary / "tasks/20261010-hhhl-v4-probability/datasets/hhhl-v4-descriptive-01"
    directory.mkdir(parents=True)
    path = directory / "events.parquet"
    pd.DataFrame({
        "security_id": ["TW:0001", "TW:0002", "TW:0003"],
        "asof_date": ["2020-01-01", "2020-01-02", "2020-01-03"],
        "pattern": [True, True, False],
        "base_eligible": [False, True, True],
        "has_old": [False, True, False],
        "has_recent_far": [False, False, False],
        "hz_top": [10.0, 20.0, 30.0],
        "Z2": [9.0, 19.0, 29.0],
    }).to_parquet(path)
    write_json(
        directory / "manifest.json",
        {
            "schema_version": "hhhl-probability.v4",
            "rule": "hhhl_rule_v4",
            "complete": True,
            "window": ["2019-01-02", "2026-08-14"],
            "identity": {"source": "invented"},
            "artifacts": {"events.parquet": {"bytes": path.stat().st_size, "sha256": file_digest(path)}},
        },
    )
    catalog = DataCatalog(roots)
    snapshot = catalog.register(existing_entries(catalog))
    return roots, snapshot["version_id"], path


def test_pinned_legacy_reader_retains_ineligible_raw_patterns_and_metadata(legacy_catalog: tuple[DataRoots, str, Path]) -> None:
    roots, snapshot, _ = legacy_catalog
    table, descriptor = audit.read_legacy_h1(roots, snapshot)
    assert table is not None
    assert table.security_id.tolist() == ["TW:0001", "TW:0002"]
    assert table.t0.tolist() == ["2020-01-01", "2020-01-02"]
    assert table.base_eligible.tolist() == [False, True]
    assert table.subtype_id.tolist() == ["P-clean", "P-over"]
    assert "support" not in table and "lower" not in table
    assert descriptor["status"] == "available" and descriptor["base_eligibility_filtered"] is False
    assert descriptor["legacy_window"] == ["2019-01-02", "2026-08-14"]


def test_missing_pinned_legacy_is_unknown_without_fallback(legacy_catalog: tuple[DataRoots, str, Path]) -> None:
    roots, snapshot, path = legacy_catalog
    table, descriptor = audit.read_legacy_h1(roots, object_digest({"unavailable": True}))
    assert table is None and descriptor["reason"] == "catalog_snapshot_unavailable"
    path.unlink()
    table, descriptor = audit.read_legacy_h1(roots, snapshot)
    assert table is None and descriptor["reason"] == "retained_legacy_events_unavailable"
    with pytest.raises(ValueError, match="explicit immutable"):
        audit.read_legacy_h1(roots, "latest")


def test_corrupt_known_legacy_payload_fails(legacy_catalog: tuple[DataRoots, str, Path]) -> None:
    roots, snapshot, path = legacy_catalog
    path.write_bytes(b"corrupt invented legacy")
    with pytest.raises(ValueError, match="hash/size"):
        audit.read_legacy_h1(roots, snapshot)


def test_legacy_reader_detects_change_after_read(legacy_catalog: tuple[DataRoots, str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    roots, snapshot, path = legacy_catalog
    original_read = pd.read_parquet

    def changed_read(source: Any, *args: Any, **kwargs: Any) -> pd.DataFrame:
        table = original_read(source, *args, **kwargs)
        Path(source).write_bytes(b"changed after legacy read")
        return table

    monkeypatch.setattr(audit.pd, "read_parquet", changed_read)
    with pytest.raises(ValueError, match="hash/size"):
        audit.read_legacy_h1(roots, snapshot)
