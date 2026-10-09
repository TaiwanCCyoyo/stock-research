"""Synthetic industry-role runner contracts; no market outcomes are accessed."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core.evidence import EvidenceError
from scripts import run_industry_role_comparison as runner


def test_declared_readset_includes_all_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    manifest = {
        "tables": [{"path": "tables/A.parquet"}, {"path": "tables/B.parquet"}],
        "cross_section": {"path": "cross.parquet"},
        "artifacts": [{"path": "summary.json"}, {"path": "definitions.json"}],
    }
    (source / "manifest.json").write_text(json.dumps(manifest))
    assert runner.declared_artifacts(tmp_path, "source", atlas=True) == [
        "source/manifest.json",
        "source/tables/A.parquet",
        "source/tables/B.parquet",
        "source/cross.parquet",
        "source/summary.json",
        "source/definitions.json",
    ]
    assert runner.declared_artifacts(tmp_path, "source", atlas=False) == ["source/manifest.json", "source/summary.json", "source/definitions.json"]


def test_manifest_enumeration_rejects_traversal_and_duplicate(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    manifest = source / "manifest.json"
    manifest.write_text(json.dumps({"artifacts": [{"path": "../escape.json"}]}))
    with pytest.raises(EvidenceError):
        runner.declared_artifacts(tmp_path, "source", atlas=False)
    manifest.write_text(json.dumps({"artifacts": [{"path": "a.json"}, {"path": "A.json"}]}))
    with pytest.raises(ValueError, match="duplicate"):
        runner.declared_artifacts(tmp_path, "source", atlas=False)


@pytest.mark.parametrize("existing", ["plain", "compressed", "both"])
def test_prepare_pins_inputs_without_evaluation_and_refuses_destinations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: str) -> None:
    monkeypatch.setattr(runner, "declared_artifacts", lambda root, relative, **kwargs: [f"{relative}/manifest.json", f"{relative}/all-inputs.bin"])
    monkeypatch.setattr(runner, "file_digest", lambda path: "a" * 64)
    monkeypatch.setattr(runner, "runtime_identity", lambda: {"python": "synthetic"})
    monkeypatch.setattr(runner, "load_analysis", lambda *args, **kwargs: pytest.fail("preparation must not load observations"))
    monkeypatch.setattr(runner, "load_context_rows", lambda *args, **kwargs: pytest.fail("preparation must not load contexts"))
    monkeypatch.setattr(runner, "analyze", lambda *args, **kwargs: pytest.fail("preparation must not analyze"))
    info = runner.prepare_packet(tmp_path, "fixture-v1")
    plain, compressed = Path(info["packet"]), Path(info["portable_packet"])
    assert gzip.decompress(compressed.read_bytes()) == plain.read_bytes()
    packet = json.loads(plain.read_text())
    assert set(packet["inputs"]["code"]) == {
        "scripts/run_industry_role_comparison.py",
        "scripts/run_method_environment_interactions.py",
        "scripts/publish_method_environment_interactions.py",
        "scripts/run_registered_job.py",
        "research_core/industry_role_comparison.py",
        "research_core/method_environment_interactions.py",
        "research_core/__init__.py",
        "research_core/jobs.py",
        "research_core/evidence.py",
        "research_core/feature_atlas_dataset.py",
        "research_core/feature_atlas_io.py",
        "research_core/feature_atlas_outcomes.py",
        "research_core/market_context_artifact.py",
        "StockProject/engine/data_loader.py",
        "StockProject/engine/__init__.py",
        "pyproject.toml",
        "uv.lock",
    }
    assert set(packet["inputs"]["contracts"]) == {
        f"tasks/{runner.TASK}/mission.md",
        f"tasks/{runner.TASK}/data-contract.md",
        "docs/en/research-owner-contract.md",
        "docs/en/research-registry.json",
        "tasks/20261004-feature-discrimination-atlas/data-contract.md",
        "tasks/20261005-market-context-handoff/data-contract.md",
    }
    assert len(packet["inputs"]["data"]) == 4
    assert packet["params"] == {
        "min_other_peers": 5,
        "peer_positive60_min": 0.6,
        "rank_cutoff": 0.8,
        "roles": runner.ROLES,
        "max_industries": 64,
        "max_comparisons": 2184,
        "maximum_attempts": 2,
    }
    assert packet["candidate_id"] == "industry-peer-role.v1"
    assert packet["metric_contract_id"] == "fixed-industry-role.v1"
    assert packet["scenario_id"] == "daily-grid126-peer-strength"
    assert packet["phase"] == "exploration"
    assert packet["timeout_seconds"] == 1800
    if existing == "plain":
        compressed.unlink()
    elif existing == "compressed":
        plain.unlink()
    before = {path: path.read_bytes() for path in (plain, compressed) if path.exists()}
    with pytest.raises(ValueError, match="destination exists"):
        runner.prepare_packet(tmp_path, "fixture-v1")
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.fixture
def execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    for relative, identity in ((runner.ATLAS, "synthetic-atlas"), (runner.CONTEXT, "synthetic-context")):
        source = tmp_path / relative
        source.mkdir(parents=True)
        (source / "manifest.json").write_text(json.dumps({"dataset_id": identity}))
    frame = pd.DataFrame({
        "security_id": ["TW:1234", "TW:1234"],
        "asof_date": pd.to_datetime([runner.START, runner.END]),
        "calendar_index": [0, 2000],
        "year": [2019, 2026],
    })
    context = [
        {"security_id": "TW:0050", "asof_date": day, "layer": "past_only", "state": "up", "information_cutoff": day, "missing_reason": None}
        for day in ("2018-12-31", runner.START, runner.END, "2026-08-15")
    ]
    result = {"comparisons": [{"synthetic": True}], "path_summaries": [], "paired_rows": [], "triage": {"status": "synthetic"}, "role_audit": {"rows": 2}}
    monkeypatch.setattr(runner, "file_digest", lambda path: "a" * 64)
    monkeypatch.setattr(runner, "load_analysis", lambda *args, **kwargs: frame)
    monkeypatch.setattr(runner, "load_context_rows", lambda *args, **kwargs: context)
    monkeypatch.setattr(runner, "analyze", lambda joined: result)
    output = tmp_path / "output"
    output.mkdir()
    return tmp_path, output, frame, context, result


def test_projection_same_date_join_and_compact_output(
    execution: tuple[Path, Path, pd.DataFrame, list[dict[str, Any]], dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, output, frame, context, result = execution

    def projected(path: Path, columns: list[str]) -> pd.DataFrame:
        assert path == root / runner.ATLAS
        assert columns == ["industry_ref", "classification_basis", "ret20", "ret60", "rs60_percentile", "base_eligible", "calendar_index", "year"] + [
            f"{name}_{horizon}" for horizon in (63, 126) for name in ("forward_return", "min_return", "max_drawdown", "complete", "label", "wait_to_threshold")
        ]
        return frame

    def analyze(joined: pd.DataFrame) -> dict[str, Any]:
        assert joined["market_state"].tolist() == ["up", "up"]
        assert joined["asof_date"].tolist() == frame["asof_date"].tolist()
        return result

    monkeypatch.setattr(runner, "load_analysis", projected)
    monkeypatch.setattr(runner, "analyze", analyze)
    runner.build(root, output, "fixture-v1")
    assert {path.name for path in output.iterdir()} == set(runner.OUTPUTS)
    results = json.loads((output / "results.json").read_text())
    assert results == {"schema_version": "industry-role-results.v1", **result}
    audit = json.loads((output / "input-audit.json").read_text())
    assert audit["schema_version"] == "industry-role-inputs.v1"
    assert audit["join"]["context_rows"] == 2
    assert audit["source_datasets"]["context"]["layer"] == "past_only"
    summary = json.loads((output / "summary.json").read_text())
    assert summary["metrics"]["comparison_rows"] == 1
    assert summary["portfolio"]["simulated"] is False
    assert summary["trades"] == []


def test_window_mismatch_rejected_before_analysis(
    execution: tuple[Path, Path, pd.DataFrame, list[dict[str, Any]], dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, output, frame, _, _ = execution
    frame.loc[0, "asof_date"] = pd.Timestamp("2019-01-03")
    monkeypatch.setattr(runner, "analyze", lambda joined: pytest.fail("wrong window must not evaluate"))
    with pytest.raises(ValueError, match="window differs"):
        runner.build(root, output, "fixture-v1")
    assert not list(output.iterdir())


def test_future_context_rejected(execution: tuple[Path, Path, pd.DataFrame, list[dict[str, Any]], dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    root, output, _, context, _ = execution
    context[1]["information_cutoff"] = "2019-01-03"
    monkeypatch.setattr(runner, "analyze", lambda joined: pytest.fail("future context must not evaluate"))
    with pytest.raises(ValueError, match="future information_cutoff"):
        runner.build(root, output, "fixture-v1")


@pytest.mark.parametrize("invalid", ["budget", "nonfinite", "schema"])
def test_invalid_result_rejected_before_outputs(execution: tuple[Path, Path, pd.DataFrame, list[dict[str, Any]], dict[str, Any]], invalid: str) -> None:
    root, output, _, _, result = execution
    if invalid == "budget":
        result["comparisons"] = [{}] * 2185
    elif invalid == "nonfinite":
        result["role_audit"]["bad"] = float("nan")
    else:
        result.pop("role_audit")
    with pytest.raises(ValueError):
        runner.build(root, output, "fixture-v1")
    assert not list(output.iterdir())
