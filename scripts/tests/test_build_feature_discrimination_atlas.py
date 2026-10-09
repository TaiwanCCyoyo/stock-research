"""Synthetic end-to-end builder verification without market snapshot reads."""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_core.feature_atlas_dataset import load_analysis, verify_dataset
from research_core.jobs import file_digest
from scripts import build_feature_discrimination_atlas as builder
from scripts.query_feature_discrimination_atlas import comparison_rows, recompute


@pytest.fixture
def synthetic_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[pd.DatetimeIndex, list[Path]]:
    calendar = pd.bdate_range("2019-01-02", periods=220)
    frames = []
    for code, daily_growth in (("2330", 0.008), ("6488", 0.001), ("0050", 0.002)):
        close = 100 * np.exp(np.arange(len(calendar)) * daily_growth)
        frames.append(
            pd.DataFrame({
                "Date": calendar,
                "Code": code,
                "Open": close,
                "High": close * 1.01,
                "Low": close * 0.99,
                "Close": close,
                "Volume": 10.0,
                "Source": "official",
            })
        )
    prices = pd.concat(frames, ignore_index=True)
    meta = pd.DataFrame([
        {"code": "2330", "name": "Synthetic ordinary A", "market": "TWSE", "is_etf": 0, "security_category": "股票", "industry_category": "semiconductor"},
        {"code": "6488", "name": "Synthetic ordinary B", "market": "TPEX", "is_etf": 0, "security_category": "股票", "industry_category": None},
        {"code": "0050", "name": "Synthetic benchmark ETF", "market": "TWSE", "is_etf": 1, "security_category": "ETF", "industry_category": None},
    ])
    actions = pd.DataFrame(columns=pd.Index(["code", "ex_date", "event_type", "price_factor"]))
    paths = {}
    for name in ("prices", "metadata", "actions"):
        path = tmp_path / f"synthetic-{name}.txt"
        path.write_text(f"synthetic source identity: {name}\n", encoding="utf-8")
        paths[name] = path
    inventory = {
        "source_sha256": {name: file_digest(path) for name, path in paths.items()},
        "read_window": {"start": calendar.strftime("%Y-%m-%d")[0], "end": calendar.strftime("%Y-%m-%d")[-1]},
        "membership_basis": "current_metadata_reference_not_historical_PIT",
        "historical_universe_complete": False,
    }
    calls: list[Path] = []

    def load_snapshot(root: Path):
        calls.append(root)
        return prices.copy(), meta.copy(), actions.copy(), inventory.copy()

    monkeypatch.setattr(builder, "load_snapshot", load_snapshot)
    monkeypatch.setattr(builder, "input_paths", lambda root: paths)
    return calendar, calls


def read_json(output: Path, filename: str):
    return json.loads((output / filename).read_text(encoding="utf-8"))


def test_synthetic_build_has_complete_manifest_and_honest_unknown_panels(
    tmp_path: Path,
    synthetic_snapshot: tuple[pd.DatetimeIndex, list[Path]],
):
    calendar, calls = synthetic_snapshot
    output = tmp_path / "atlas"
    output.mkdir()
    # Root supplies executable/mission hashes only; all market reads are patched.
    root = Path(__file__).resolve().parents[2]
    builder.build_atlas(root, output, "synthetic-atlas")
    assert calls == [root]
    manifest = read_json(output, "manifest.json")
    assert {entry["security_id"] for entry in manifest["tables"]} == {"TW:2330", "TW:6488"}
    assert [entry["rows"] for entry in manifest["tables"]] == [220, 220]
    assert manifest["cross_section"]["rows"] == 440
    assert manifest["join_cardinality"] == "one_to_one_full_match"
    for entry in [*manifest["tables"], manifest["cross_section"], *manifest["artifacts"]]:
        assert file_digest(output / entry["path"]) == entry["sha256"]
    checked = verify_dataset(output)
    assert checked["tables"] == 2
    assert checked["table_rows"] == checked["cross_section_rows"] == checked["joined_rows"] == 440
    joined = load_analysis(output)
    assert len(joined) == 440
    assert not joined.duplicated(["security_id", "asof_date"]).any()
    assert set(joined.industry_ref) == {"semiconductor", "unknown"}
    for _, security in joined.groupby("security_id", observed=True):
        assert security.asof_date.tolist() == calendar.tolist()
        assert security.label_63.iloc[-63:].isna().all()
        assert security.label_126.iloc[-126:].isna().all()
        assert security.base_eligible.iloc[-126:].all()
        assert security.F36.iloc[-1] in (0, 1)
    first = joined.loc[(joined.security_id == "TW:2330") & (joined.calendar_index == 59)].iloc[0]
    second = joined.loc[(joined.security_id == "TW:6488") & (joined.calendar_index == 59)].iloc[0]
    assert first.label_63 == first.label_126 == 1
    assert second.label_63 == second.label_126 == 0

    summary = read_json(output, "summary.json")
    assert summary["strategy"]["kind"] == "descriptive_features_not_strategy"
    assert summary["portfolio"]["evaluated"] is False
    assert summary["trades"] == []
    assert summary["metrics"]["rows"] == 440
    assert summary["metrics"]["eligible_rows"] == 322
    assert summary["metrics"]["label_counts"]["63"] == {"known": 196, "positive": 98, "unknown": 126}
    assert summary["metrics"]["label_counts"]["126"] == {"known": 70, "positive": 35, "unknown": 252}
    assert "strategy_passed" not in summary

    comparisons = read_json(output, "comparisons.json")["comparisons"]
    assert {row["panel"] for row in comparisons} == {"daily", "grid126"}
    assert {row["feature"] for row in comparisons} == set(builder.FEATURES)
    assert {row["label"] for row in comparisons} == {"label_63", "label_126"}
    assert all(row["descriptive_not_independent"] for row in comparisons)
    industry_groups = {row["context_value"] for row in comparisons if row["context_column"] == "industry_ref"}
    assert industry_groups == {"semiconductor", "unknown"}
    grid = next(
        row for row in comparisons if row["panel"] == "grid126" and row["feature"] == "F01" and row["label"] == "label_126" and row["context_column"] is None
    )
    assert grid["n_eligible"] == grid["n_label_unknown"] == 2
    assert grid["n_label_known"] == 0
    assert grid["tp"] == grid["fp"] == grid["fn"] == grid["tn"] == 0
    assert grid["precision"] is None
    inventory = read_json(output, "inventory.json")
    assert inventory["included_securities"] == 2
    benchmark = next(row for row in inventory["securities"] if row["code"] == "0050")
    assert benchmark["included"] is False
    assert benchmark["name"] == "Synthetic benchmark ETF"
    recomputed = recompute(output)
    assert recomputed["status"] == "all_hashes_and_comparisons_verified"
    assert recomputed["sample_rows"] == 440
    assert recomputed["comparisons"] == len(comparisons)
    tampered = read_json(output, "comparisons.json")
    tampered["comparisons"][0]["tp"] += 1
    (output / "comparisons.json").write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="comparison hash mismatch"):
        comparison_rows(output)


def test_main_rejects_unregistered_output_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(builder, "REPO_ROOT", tmp_path)
    calls: list[tuple[Path, Path, str]] = []

    def record_build(root: Path, output: Path, run_id: str) -> None:
        calls.append((root, output, run_id))

    monkeypatch.setattr(builder, "build_atlas", record_build)
    monkeypatch.setattr(sys, "argv", ["builder", "--run-id", "synthetic-atlas", "--output-dir", str(tmp_path / "elsewhere")])
    with pytest.raises(SystemExit) as exc:
        builder.main()
    assert exc.value.code == 2
    assert calls == []


def test_prepare_packet_cli_only_prepares_and_does_not_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.setattr(builder, "REPO_ROOT", tmp_path)
    packet_path = tmp_path / "params" / "synthetic-atlas.json"
    calls: list[tuple[Path, str]] = []

    def record_packet(root: Path, run: str) -> tuple[Path, str]:
        calls.append((root, run))
        return packet_path, "a" * 64

    monkeypatch.setattr(builder, "prepare_packet", record_packet)

    def forbidden_execution(*args: object) -> None:
        pytest.fail("--prepare-packet must not execute the builder")

    monkeypatch.setattr(builder, "build_atlas", forbidden_execution)
    monkeypatch.setattr(sys, "argv", ["builder", "--prepare-packet", "--run-id", "synthetic-atlas"])
    builder.main()
    assert calls == [(tmp_path, "synthetic-atlas")]
    assert str(packet_path) in capsys.readouterr().out
