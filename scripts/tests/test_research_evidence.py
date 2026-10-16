import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from research_core.evidence import (
    REGISTRY_VERSION,
    RESULT_VERSION,
    EvidenceError,
    exposure_status,
    task_catalog,
    task_publications,
    validate_registry,
    validate_result,
)


def result(**overrides):
    value = {
        "schema_version": RESULT_VERSION,
        "study_id": "study-1",
        "candidate_id": "candidate-1",
        "run_id": "run-1",
        "phase": "confirmation",
        "outcome": "incomplete",
        "identities": {
            "owner_contract": "owner-v1",
            "metric_contract": "metric-v1",
            "execution_contract": "execution-v1",
            "data_snapshot": "data-v1",
            "code": "code-v1",
            "runtime": "runtime-v1",
        },
        "window": {"start": "2026-01-01", "end": "2026-01-31"},
        "metrics": {"return": {"unit": "fraction", "value": None, "unavailable_reason": "run incomplete"}},
        "artifacts": [],
        "limitations": ["synthetic fixture"],
        "supersedes": [],
    }
    value.update(overrides)
    return value


def registry(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": REGISTRY_VERSION, "history_complete": False, "events": events}


def exposure(event_id: str, scope: str = "task-a", start: str = "2026-01-01", end: str = "2026-01-31", source: str = "agent-a") -> dict[str, Any]:
    return {
        "id": event_id,
        "source": source,
        "recorded_on": "2026-02-01",
        "note": "synthetic exposure",
        "kind": "exposure",
        "scope": scope,
        "state": "viewed",
        "window": {"start": start, "end": end},
    }


def test_catalog_lists_report_and_legacy_summary_without_reading_json(tmp_path: Path) -> None:
    report_task = tmp_path / "report-only"
    summary_task = tmp_path / "legacy-summary"
    result_task = tmp_path / "registered"
    for task in (report_task, summary_task, result_task):
        task.mkdir()
    (report_task / "report.md").write_text("report", encoding="utf-8")
    (summary_task / "summary.json").write_text("{ malformed", encoding="utf-8")
    (result_task / "research_result.json").write_text("sealed", encoding="utf-8")
    os.utime(report_task, (10, 10))
    os.utime(summary_task, (20, 20))
    os.utime(result_task, (30, 30))

    rows = task_catalog(tmp_path)
    assert [row["task"] for row in rows] == ["registered", "legacy-summary", "report-only"]
    assert rows[0]["evidence_state"] == "registered_unread"
    assert rows[0]["outcome"] == "unknown"
    assert rows[1]["artifacts"]["summary.json"] is True
    assert rows[1]["evidence_state"] == "legacy_unregistered"
    assert rows[2]["artifacts"]["report.md"] is True


def publication_fixture(root: Path) -> dict[str, Any]:
    current = root / "publications/completion-v2"
    current.mkdir(parents=True)
    for directory in (root, current):
        (directory / "report.md").write_text(f"report: {directory.name}", encoding="utf-8")
        (directory / "research_result.json").write_text("sealed; catalog must not parse this", encoding="utf-8")
    return {
        "schema": "research-publications.v1",
        "study_id": root.name,
        "current": "completion-v2",
        "publications": [
            {"id": "v1", "report": "report.md", "result": "research_result.json"},
            {"id": "completion-v2", "report": "publications/completion-v2/report.md", "result": "publications/completion-v2/research_result.json"},
        ],
    }


def test_catalog_uses_explicit_current_and_preserves_history_without_reading_cards(tmp_path: Path):
    task = tmp_path / "20261013-study"
    index = publication_fixture(task)
    originals = {name: (task / name).read_bytes() for name in ("report.md", "research_result.json")}
    (task / "publications.json").write_text(json.dumps(index), encoding="utf-8")
    row = task_catalog(tmp_path)[0]
    assert row["current_publication"] == "completion-v2"
    assert row["report_path"] == "publications/completion-v2/report.md"
    assert row["result_path"] == "publications/completion-v2/research_result.json"
    assert row["publications"][0] == {"id": "v1", "report_path": "report.md", "result_path": "research_result.json"}
    assert row["outcome"] == "unknown"
    assert originals == {name: (task / name).read_bytes() for name in originals}
    (task / "publications.json").unlink()
    assert task_publications(task) is None
    assert "current_publication" not in task_catalog(tmp_path)[0]


@pytest.mark.parametrize("damage", ["unknown_current", "duplicate", "missing", "escape", "foreign_study", "schema"])
def test_publication_index_fails_closed(tmp_path: Path, damage: str):
    task = tmp_path / "20261013-study"
    index = publication_fixture(task)
    if damage == "unknown_current":
        index["current"] = "unlisted"
    elif damage == "duplicate":
        index["publications"].append(index["publications"][0])
    elif damage == "missing":
        (task / "publications/completion-v2/report.md").unlink()
    elif damage == "escape":
        index["publications"][1]["result"] = "../foreign/research_result.json"
    elif damage == "foreign_study":
        index["study_id"] = "another-study"
    else:
        index["schema"] = "unsupported"
    (task / "publications.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(EvidenceError):
        task_catalog(tmp_path)


@pytest.mark.parametrize(
    "value",
    [
        result(schema_version="research-result.v0"),
        result(identities={}),
        result(metrics={"x": {"unit": "percent", "value": None}}),
        result(metrics={"x": {"unit": "fraction", "value": float("nan")}}),
        result(supersedes=["old", "old"]),
    ],
)
def test_validate_result_rejects_version_identity_metric_and_correction_errors(value: dict[str, Any]) -> None:
    with pytest.raises(EvidenceError):
        validate_result(value)


def test_validate_result_accepts_explicit_null_metric_reason() -> None:
    assert validate_result(result())["metrics"]["return"]["unavailable_reason"] == "run incomplete"


def test_registry_exposure_is_positive_and_other_task_or_agent_cannot_reset_it() -> None:
    viewed = exposure("seen", scope="task-a", source="agent-a")
    other = exposure("other", scope="task-b", source="agent-b")
    valid = registry([viewed, other])
    assert exposure_status(valid, "task-a", {"start": "2026-01-15", "end": "2026-02-15"}) == {
        "state": "viewed_overlap",
        "events": ["seen"],
        "certifies_unseen": False,
    }
    assert exposure_status(valid, "task-a", {"start": "2026-03-01", "end": "2026-03-02"}) == {
        "state": "unknown",
        "events": [],
        "certifies_unseen": False,
    }
    reset = dict(other, id="reset", state="unseen")
    with pytest.raises(EvidenceError, match="never a reset"):
        validate_registry(registry([viewed, reset]))


def test_registry_rejects_duplicate_ids_and_duplicate_correction_targets() -> None:
    first = exposure("seen")
    with pytest.raises(EvidenceError, match="duplicate registry event id"):
        validate_registry(registry([first, dict(first)]))
    correction = {
        "id": "fix-1",
        "source": "agent-a",
        "recorded_on": "2026-02-02",
        "note": "synthetic correction",
        "kind": "correction",
        "supersedes": ["seen", "seen"],
    }
    with pytest.raises(EvidenceError, match="duplicate correction target"):
        validate_registry(registry([first, correction]))


def test_result_rejects_numeric_zero_with_unavailable_reason() -> None:
    # Start from the module's existing minimal valid result fixture.
    value = {
        "schema_version": RESULT_VERSION,
        "study_id": "s",
        "candidate_id": "c",
        "run_id": "r",
        "phase": "discovery",
        "outcome": "not_evaluated",
        "window": {"start": "2026-01-01", "end": "2026-01-31"},
        "identities": {key: "v1" for key in ("owner_contract", "metric_contract", "execution_contract", "data_snapshot", "code", "runtime")},
        "metrics": {"return": {"value": 0, "unit": "fraction", "unavailable_reason": "missing"}},
        "artifacts": [],
        "limitations": [],
        "supersedes": [],
    }
    with pytest.raises(EvidenceError, match="cannot also be unavailable"):
        validate_result(value)


def test_cli_catalog_and_registry_use_only_synthetic_artifacts(tmp_path: Path) -> None:
    task = tmp_path / "tasks" / "synthetic-task"
    task.mkdir(parents=True)
    (task / "summary.json").write_text("{ bad", encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry([exposure("seen")])), encoding="utf-8")
    script = Path(__file__).parents[1] / "research_evidence.py"

    catalog = subprocess.run(
        [sys.executable, str(script), "catalog", "--tasks-root", str(tmp_path / "tasks")],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(catalog.stdout)["tasks"][0]["task"] == "synthetic-task"
    checked = subprocess.run(
        [sys.executable, str(script), "registry", str(registry_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(checked.stdout)["schema_version"] == REGISTRY_VERSION
