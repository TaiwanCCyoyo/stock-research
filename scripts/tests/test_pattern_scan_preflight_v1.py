"""Bounded synthetic API orchestration; no real market calculations or paths."""

from itertools import count
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from research_core.artifact_store import describe_file, object_digest, write_json
from research_core.pattern_scan_followup_summary_v1 import FollowupSummaryTables
from research_core.pattern_scan_followup_v1 import FollowupTables
from research_core.pattern_scan_preflight_v1 import profile_global, split_audit


def setup(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Path], pd.DataFrame, dict[str, Any]]:
    from research_core import pattern_scan_preflight_v1 as module

    calendar = pd.bdate_range("2020-01-06", periods=20)
    directory = root / "synthetic-stock"
    directory.mkdir()
    tables = {
        "base_labels": pd.DataFrame({"label": ["hit"]}),
        "indicators": pd.DataFrame({"Close": 100.0}, index=calendar),
        "pivots": pd.DataFrame({"kind": pd.Series(dtype=object)}),
        "common_values": pd.DataFrame({"industry_ref": "invented"}, index=calendar),
    }
    for name, frame in tables.items():
        frame.to_parquet(directory / f"{name}.parquet")
    write_json(
        directory / "receipt.json",
        {
            "complete": True,
            "source_id": "synthetic-source",
            "input_id": "synthetic-input",
            "artifacts": [describe_file(directory, directory / f"{name}.parquet") for name in tables],
        },
    )
    parts = {"001": directory}
    benchmark = pd.DataFrame({"Close": 100.0, "RawClose": 100.0, "Quality": True, "quality_reason": None}, index=calendar)
    observations: dict[str, Any] = {}
    monkeypatch.setattr(module, "verify_source", lambda source: None)
    clock = count()
    monkeypatch.setattr(module, "resource_sample", lambda: {"wall": float(next(clock)), "cpu": float(next(clock)), "native": None})

    def barrier(supplied: dict[str, Path], benchmark_frame: pd.DataFrame, output: Path) -> dict[str, Any]:
        assert supplied == parts and benchmark_frame is benchmark
        output.mkdir()
        pd.DataFrame({"TW:001": 100.0}, index=calendar).to_parquet(output / "close_matrix.parquet")
        pd.DataFrame({"TW:001": False}, index=calendar).to_parquet(output / "jump_matrix.parquet")
        pd.DataFrame({"retrospective_state": "unknown"}, index=calendar).to_parquet(output / "context.parquet")
        observations["barrier_calls"] = 1
        return {"representative": True}

    def bind(supplied: dict[str, Path], barrier_receipt: dict[str, Any], entries: dict[str, Any], output: Path, **kwargs: Any) -> dict[str, dict[str, Path]]:
        assert "preflight-only:" in entries["labels"]["version_id"]
        observations["label_pins"] = entries
        return {"H1": {"001": directory}}

    labels = ["loss", "hit", "unknown", "flat-win", "hit", "loss"]
    events = pd.DataFrame({
        "security_id": "TW:001",
        "event_id": [f"event:{index}" for index in range(6)],
        "t0": calendar[:6].strftime("%Y-%m-%d"),
        "calendar_index": np.arange(6),
        "horizon": 126,
        "effective_label": labels,
        "calendar_full": True,
        "event_main_eligible": [value != "unknown" for value in labels],
        "event_eligibility_excluded": False,
        "mkt": "unknown",
    })
    monkeypatch.setattr(module, "build_barrier", barrier)
    monkeypatch.setattr(module, "prepare_event_parts", bind)
    monkeypatch.setattr(module, "group_frame", lambda directory, group, horizon: events.iloc[::-1].copy())
    metadata = {
        "pattern_id": "H1",
        "control_id": "pattern",
        "cohort_id": "union",
        "horizon": 126,
        "feature_id": "unconditional",
        "bin_id": "all",
        "condition_status": "known",
        "split": "all",
        "era": "all",
        "mkt": "all",
    }
    monkeypatch.setattr(module, "membership_inventory", lambda base: (metadata,))
    monkeypatch.setattr(
        module, "stock_memberships", lambda supplied, inventory, **kwargs: pd.DataFrame({"event_id": supplied.event_id, "cell_id": object_digest(metadata)})
    )

    def followup(supplied: pd.DataFrame, indicators: pd.DataFrame, pivots: pd.DataFrame, **kwargs: Any) -> FollowupTables:
        observations["followup_ids"] = supplied.event_id.tolist()
        assert kwargs == {"horizons": (126,), "landmarks": (5,)}
        table = pd.DataFrame({"event_id": supplied.event_id.to_numpy()})
        return FollowupTables(table.copy(), table.copy(), table.copy(), table.copy())

    class Accumulator:
        def __init__(self, groups: dict[str, str], **kwargs: Any) -> None:
            assert groups == {"preflight:H1:original": "H1"}

        def add_stock(self, tables: FollowupTables) -> None:
            assert tables.paths.group_id.eq("preflight:H1:original").all()
            assert tables.paths.mkt.eq("unknown").all()

        def finalize(self) -> FollowupSummaryTables:
            blank = pd.DataFrame({"event_n": [4]})
            return FollowupSummaryTables(*(blank.copy() for _ in range(6)))

    def holding(*args: Any, **kwargs: Any) -> pd.DataFrame:
        observations["holding_anchors"] = kwargs["anchors"]
        return pd.DataFrame({"security_id": "TW:001", "calendar_index": kwargs["anchors"]["TW:001"]})

    monkeypatch.setattr(module, "followup_values", followup)
    monkeypatch.setattr(module, "FollowupAccumulator", Accumulator)
    monkeypatch.setattr(module, "holding_values", holding)
    return parts, benchmark, observations


def test_bounded_phases_scope_work_sizes_and_first_by_date_sample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parts, benchmark, observations = setup(tmp_path, monkeypatch)
    receipt = profile_global(parts, benchmark, tmp_path / "preflight", source={"source_id": "synthetic-source"}, input_id="synthetic-input")
    assert len(receipt["phases"]) == 7
    assert all(phase["wall_seconds"] > 0 and phase["native"] is None for phase in receipt["phases"])
    assert observations["followup_ids"] == ["event:0", "event:1", "event:2", "event:3"]
    assert observations["holding_anchors"] == {"TW:001": [0, 1, 2, 3]}
    assert receipt["work_sizes"]["summary_groups_n"] == 1
    assert receipt["work_sizes"]["sample_event_n"] == 4
    assert receipt["extrapolation"]["status"] == "unknown"
    assert "representative" in receipt["scope"] and "not a complete" in receipt["scope"]
    assert receipt["split_audit"]["status"] == "unknown"
    for artifact in receipt["artifacts"]:
        metadata = pq.read_metadata(tmp_path / "preflight" / artifact["path"])
        codecs = {
            metadata.row_group(row).column(column).compression
            for row in range(metadata.num_row_groups)
            for column in range(metadata.row_group(row).num_columns)
        }
        assert codecs <= {"ZSTD"}
        if metadata.num_rows:
            assert codecs == {"ZSTD"}
    assert (tmp_path / "preflight" / "receipt.json").is_file()
    assert not (tmp_path / "research_data").exists()


def test_caps_and_identity_reject_before_probing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parts, benchmark, _ = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="one to four"):
        profile_global(
            {str(index): parts["001"] for index in range(5)}, benchmark, tmp_path / "bad", source={"source_id": "synthetic-source"}, input_id="synthetic-input"
        )
    with pytest.raises(ValueError, match="different source/input"):
        profile_global(parts, benchmark, tmp_path / "bad", source={"source_id": "different-source"}, input_id="synthetic-input")
    assert not (tmp_path / "bad").exists()


def test_split_observation_reports_raw_adjusted_values_without_certifying() -> None:
    calendar = pd.to_datetime(["2025-06-17", "2025-06-18"])
    prepared = pd.DataFrame({"Close": [25.0, 25.5], "RawClose": [100.0, 25.5], "Quality": True, "quality_reason": None}, index=calendar)
    result = split_audit(prepared)
    assert result["status"] == "observed"
    assert result["adjusted_close_ratio"] == pytest.approx(1.02)
    assert result["raw_close_ratio"] == pytest.approx(0.255)
    assert "not_certified" in result["factor_validity"]
    assert split_audit(prepared.iloc[1:])["reason"] == "previous_common_session_unavailable"
    prepared.loc[prepared.index[1], "Close"] = np.nan
    assert split_audit(prepared)["status"] == "unknown"
