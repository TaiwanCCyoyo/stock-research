"""Synthetic evidence-copy finalization preserves sources and refuses overwrite."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
import pytest

from research_core.evidence import EvidenceError
from research_core.feature_atlas_io import TASK_ID, write_json
from research_core.jobs import digest, file_digest, output_hashes, runtime_identity
from scripts import build_feature_discrimination_atlas as builder
from scripts.tests.test_build_feature_discrimination_atlas import synthetic_snapshot  # noqa: F401

FinalizationCase = tuple[ModuleType, Path, Path, Path, Path, dict[Path, str], dict[str, Any]]


@pytest.fixture
def finalization_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, synthetic_snapshot: tuple[pd.DatetimeIndex, list[Path]]) -> FinalizationCase:  # noqa: F811
    project = tmp_path / "project"
    task = project / "tasks" / TASK_ID
    source = task / "runs" / "registered" / "synthetic-v1"
    source.mkdir(parents=True)
    builder.build_atlas(builder.REPO_ROOT, source, "synthetic-v1")
    # Synthetic fixture supplies the additional inventory fields used only by
    # finalization; the production snapshot loader supplies these itself.
    inventory_path = source / "inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory.update(source_row_counts={"official": 660}, metadata_rows=3)
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["artifacts"]:
        if entry["path"] == "inventory.json":
            entry["sha256"] = file_digest(inventory_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    location = builder.REPO_ROOT / "tasks" / TASK_ID / "finalize.py"
    spec = importlib.util.spec_from_file_location("atlas_finalize_under_test", location)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", project)
    copy_root = tmp_path / "backups"
    (task / "params").mkdir()
    original_input = project / "synthetic-input.txt"
    original_input.write_text("synthetic immutable input", encoding="utf-8")
    runner = project / "runner.py"
    runner.write_text("# Synthetic identity only; never executed.\n", encoding="utf-8")
    contract = project / "contract.md"
    contract.write_text("Synthetic contract\n", encoding="utf-8")
    packet = {
        "schema_version": "research-job.v1",
        "job_id": "synthetic-v1",
        "task_id": TASK_ID,
        "phase": "exploration",
        "window": {"start": "2020-01-01", "end": "2020-12-31"},
        "candidate_id": "synthetic",
        "owner_contract_id": "synthetic-owner",
        "metric_contract_id": "synthetic-metric",
        "execution_contract_id": "synthetic-execution",
        "scenario_id": "synthetic-scenario",
        "params": {},
        "runtime": runtime_identity(),
        "timeout_seconds": 60,
        "inputs": {
            "code": {"runner.py": file_digest(runner)},
            "data": {"synthetic-input.txt": file_digest(original_input)},
            "contracts": {"contract.md": file_digest(contract)},
        },
        "script": "runner.py",
        "args": ["{output_dir}"],
        "outputs": ["summary.json", "manifest.json"],
        "summary": "summary.json",
    }
    write_json(task / "params" / "synthetic-v1.json", packet)
    write_json(
        source / "receipt.json",
        {
            "schema_version": "research-receipt.v1",
            "status": "completed",
            "packet_sha256": digest(packet),
            "outputs": output_hashes(source, packet),
        },
    )
    hashes = {p.relative_to(source): file_digest(p) for p in source.rglob("*") if p.is_file()}
    monkeypatch.setattr(sys, "argv", [str(location), "--run-id", "synthetic-v1", "--copy-root", str(copy_root), "--archive-inputs"])
    return module, project, task, source, copy_root, hashes, packet


def test_verified_finalization_copies_all_artifacts_without_overwrite(finalization_case: FinalizationCase):
    module, project, task, source, copy_root, hashes, _ = finalization_case
    module.main()
    for relative, sha in hashes.items():
        assert file_digest(source / relative) == sha
        assert file_digest(copy_root / "synthetic-v1" / relative) == sha
    result = json.loads((task / "research_result.json").read_text(encoding="utf-8"))
    assert result["outcome"] == "not_evaluated"
    assert result["organization_status"] == "completed_verified_descriptive_data"
    assert file_digest(copy_root / "synthetic-v1-inputs" / "synthetic-input.txt") == file_digest(project / "synthetic-input.txt")
    assert (copy_root / "synthetic-v1-inputs" / "input-archive.json").is_file()
    with pytest.raises(FileExistsError):
        module.main()


@pytest.mark.parametrize("change", ["params", "task_id", "job_id", "data_input", "receipt_outputs"])
def test_finalization_rejects_packet_or_receipt_drift_before_writes(finalization_case: FinalizationCase, change: str):
    module, project, task, source, copy_root, _, packet = finalization_case
    expected = "completion receipt mismatch"
    if change == "params":
        packet["params"]["new_choice"] = True
    elif change in {"task_id", "job_id"}:
        packet[change] = "another-valid-id"
        expected = "requested task and run"
    elif change == "data_input":
        replacement = project / "replacement-input.txt"
        replacement.write_text("Another internally valid input", encoding="utf-8")
        packet["inputs"]["data"] = {"replacement-input.txt": file_digest(replacement)}
    else:
        receipt_path = source / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        del receipt["outputs"]["summary.json"]
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    (task / "params" / "synthetic-v1.json").write_text(json.dumps(packet), encoding="utf-8")
    with pytest.raises((EvidenceError, ValueError), match=expected):
        module.main()
    assert not copy_root.exists()
    assert not (task / "research_result.json").exists()
    assert not (task / "sweep_results.json").exists()
    assert not (task / "universe_build_report.json").exists()


@pytest.mark.parametrize("relationship", ["same", "descendant", "ancestor"])
def test_finalization_rejects_nested_copy_roots_before_writes(finalization_case: FinalizationCase, monkeypatch: pytest.MonkeyPatch, relationship: str):
    module, project, task, source, _, _, _ = finalization_case
    copy_root = {"same": source, "descendant": source / "nested-backup", "ancestor": source.parent}[relationship]
    monkeypatch.setattr(sys, "argv", ["finalize.py", "--run-id", "synthetic-v1", "--copy-root", str(copy_root)])
    before = {path.relative_to(project) for path in project.rglob("*")}
    with pytest.raises(ValueError, match="separate, non-nested"):
        module.main()
    assert {path.relative_to(project) for path in project.rglob("*")} == before
    assert not (task / "research_result.json").exists()
