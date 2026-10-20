from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_core.evidence import EvidenceError
from research_core.study_presentation import project_study_history


def registration(tmp_path: Path) -> tuple[Path, dict]:
    task = tmp_path / "20261020-synthetic"
    task.mkdir()
    report = b"# Synthetic study\n\nNo accepted result.\n"
    (task / "report.md").write_bytes(report)
    value: dict = {
        "schema": "study-presentation.v1",
        "task_id": task.name,
        "publication": None,
        "section": "method",
        "report_path": "report.md",
        "report_sha256": hashlib.sha256(report).hexdigest(),
        "title": "Synthetic study",
        "summary": "No accepted result.",
        "web_report": False,
        "shared_data": [],
        "shared_data_reason": "No shared output.",
    }
    save(task, value)
    return task, value


def save(task: Path, value: dict) -> None:
    (task / "presentation.json").write_text(json.dumps(value), encoding="utf-8")


def test_projection_appends_verbatim_report_without_mutating_old_history(tmp_path: Path) -> None:
    task, _ = registration(tmp_path)
    original = {"items": [{"id": "older", "date": "2020-01-01", "outcome": "candidate_failed"}]}
    result = project_study_history(original, tmp_path)
    assert result["items"][0]["id"] == task.name
    assert result["items"][0]["conclusion"] == "No accepted result."
    assert result["items"][0]["outcome"] is None
    assert result["items"][0]["dateBasis"] == "task-identifier-date-not-certified-completion-date"
    assert len(original["items"]) == 1


def test_unregistered_malformed_publication_does_not_break_registered_history(tmp_path: Path) -> None:
    task, _ = registration(tmp_path)
    unregistered = tmp_path / "20261021-work-in-progress"
    unregistered.mkdir()
    (unregistered / "publications.json").write_text("{invalid", encoding="utf-8")
    result = project_study_history({"items": []}, tmp_path)
    assert [item["id"] for item in result["items"]] == [task.name]


@pytest.mark.parametrize(
    "identity",
    [
        "20261020-has space",
        "20261020-has#fragment",
        "20261020-has%20encoding",
        "20261020-中文",
    ],
)
def test_task_identity_must_be_report_route_safe(tmp_path: Path, identity: str) -> None:
    task, metadata = registration(tmp_path)
    destination = tmp_path / identity
    task.rename(destination)
    metadata["task_id"] = identity
    save(destination, metadata)
    with pytest.raises(EvidenceError, match="report-route-safe"):
        project_study_history({"items": []}, tmp_path)


@pytest.mark.parametrize("shared", [[], ["adjusted-daily-v1"]])
@pytest.mark.parametrize("reason", [{}, []])
def test_shared_reason_rejects_objects_for_all_reference_states(tmp_path: Path, shared: list[str], reason: object) -> None:
    task, metadata = registration(tmp_path)
    metadata.update(shared_data=shared, shared_data_reason=reason)
    save(task, metadata)
    with pytest.raises(EvidenceError, match="shared_data_reason must be text or null"):
        project_study_history({"items": []}, tmp_path)


def test_nonempty_references_allow_null_reason(tmp_path: Path) -> None:
    task, metadata = registration(tmp_path)
    metadata.update(shared_data=["adjusted-daily-v1"], shared_data_reason=None)
    save(task, metadata)
    assert project_study_history({"items": []}, tmp_path)["items"][0]["sharedDataReason"] is None


@pytest.mark.parametrize("reason", [{}, [], 1])
def test_web_report_reason_rejects_nontext(tmp_path: Path, reason: object) -> None:
    task, metadata = registration(tmp_path)
    metadata["web_report_reason"] = reason
    save(task, metadata)
    with pytest.raises(EvidenceError, match="web_report_reason must be text or null"):
        project_study_history({"items": []}, tmp_path)


@pytest.mark.parametrize("reason", [None, "Reading page deferred; saved report is preserved."])
def test_web_report_reason_is_optional_projection_metadata(tmp_path: Path, reason: str | None) -> None:
    task, metadata = registration(tmp_path)
    report = (task / "report.md").read_bytes()
    assert project_study_history({"items": []}, tmp_path)["items"][0]["webReportReason"] is None
    metadata["web_report_reason"] = reason
    save(task, metadata)
    item = project_study_history({"items": []}, tmp_path)["items"][0]
    assert item["webReportReason"] == reason
    assert item["webReportHref"] is None
    assert (task / "report.md").read_bytes() == report


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("summary", "Profitable strategy"),
        ("title", "Invented title"),
        ("report_sha256", "0" * 64),
        ("task_id", "20261021-another"),
        ("publication", "wrong"),
        ("report_path", "../report.md"),
        ("report_path", "C:/report.md"),
        ("section", "unknown"),
        ("web_report", "yes"),
        ("shared_data", ["../outside"]),
        ("shared_data_reason", ""),
    ],
)
def test_invalid_registration_fails_closed(tmp_path: Path, key: str, value: object) -> None:
    task, metadata = registration(tmp_path)
    metadata[key] = value
    save(task, metadata)
    with pytest.raises((EvidenceError, ValueError)):
        project_study_history({"items": []}, tmp_path)


def test_current_publication_required_and_nested_report_supported(tmp_path: Path) -> None:
    task, metadata = registration(tmp_path)
    nested = task / "publications/v2"
    nested.mkdir(parents=True)
    (nested / "report.md").write_bytes((task / "report.md").read_bytes())
    (nested / "research_result.json").write_text(
        json.dumps({
            "schema_version": "research-result.v1",
            "study_id": task.name,
            "candidate_id": "synthetic",
            "run_id": "synthetic",
            "phase": "exploration",
            "outcome": "candidate_failed",
            "identities": {key: "synthetic" for key in ("owner_contract", "metric_contract", "execution_contract", "data_snapshot", "code", "runtime")},
            "window": {"start": "2020-01-01", "end": "2020-01-02"},
            "metrics": {},
            "artifacts": [],
            "limitations": [],
            "supersedes": [],
        }),
        encoding="utf-8",
    )
    (task / "publications.json").write_text(
        json.dumps({
            "schema": "research-publications.v1",
            "study_id": task.name,
            "current": "v2",
            "publications": [{"id": "v2", "report": "publications/v2/report.md", "result": "publications/v2/research_result.json"}],
        }),
        encoding="utf-8",
    )
    with pytest.raises(EvidenceError, match="current publication"):
        project_study_history({"items": []}, tmp_path)
    metadata.update(publication="v2", report_path="publications/v2/report.md")
    save(task, metadata)
    result = project_study_history({"items": []}, tmp_path)
    assert result["items"][0]["currentPublication"] == "v2"
    assert result["items"][0]["outcome"] == "candidate_failed"


def test_existing_formal_outcome_is_not_erased(tmp_path: Path) -> None:
    task, _ = registration(tmp_path)
    original = {"items": [{"id": task.name, "date": "2026-10-20", "outcome": "candidate_failed", "registryEventIds": ["event"]}]}
    item = project_study_history(original, tmp_path)["items"][0]
    assert item["outcome"] == "candidate_failed"
    assert item["registryEventIds"] == ["event"]


def test_web_report_link_requires_real_local_entry(tmp_path: Path) -> None:
    task, metadata = registration(tmp_path)
    metadata["web_report"] = True
    save(task, metadata)
    with pytest.raises(EvidenceError):
        project_study_history({"items": []}, tmp_path)
    (task / "web-report").mkdir()
    (task / "web-report/index.html").write_text("<h1>Synthetic</h1>", encoding="utf-8")
    assert project_study_history({"items": []}, tmp_path)["items"][0]["webReportHref"] == f"#report/{task.name}"


def test_report_change_requires_registration_refresh(tmp_path: Path) -> None:
    task, _ = registration(tmp_path)
    (task / "report.md").write_text("# New report\n\nNo accepted result.", encoding="utf-8")
    with pytest.raises(EvidenceError, match="digest"):
        project_study_history({"items": []}, tmp_path)


def test_registration_size_bound(tmp_path: Path) -> None:
    task, _ = registration(tmp_path)
    (task / "presentation.json").write_bytes(b" " * (64 * 1024 + 1))
    with pytest.raises(EvidenceError, match="size bound"):
        project_study_history({"items": []}, tmp_path)


def test_saved_reader_projects_only_private_and_keeps_package_bytes(tmp_path: Path) -> None:
    from research_core.saved_research_studio import SavedResearchStudio, synthetic_studio_package

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    task, _ = registration(tasks)
    package = tmp_path / "studio.json"
    package.write_text(json.dumps(synthetic_studio_package()), encoding="utf-8")
    original = package.read_bytes()
    private = SavedResearchStudio(package, history_tasks_root=tasks)
    history = private.history()
    assert history["items"][0]["id"] == task.name
    assert package.read_bytes() == original
    assert private.source_metadata(history)["version"] != private.source_metadata()["version"]
    public = SavedResearchStudio(None, history_tasks_root=tasks)
    assert public.history()["items"] == []


def test_legacy_title_integrity_check_precedes_new_registration(tmp_path: Path) -> None:
    from research_core.saved_research_studio import SavedResearchStudio, StudioError, synthetic_studio_package

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    registration(tasks)
    package = tmp_path / "studio.json"
    package.write_text(json.dumps(synthetic_studio_package()), encoding="utf-8")
    origins = tmp_path / "origins.json"
    origins.write_text(
        json.dumps({
            "schema": "research-history-title-origins.v1",
            "historySha256": "0" * 64,
            "sourceRevision": "a" * 40,
            "titles": {},
        }),
        encoding="utf-8",
    )
    with pytest.raises(StudioError, match="do not match saved history"):
        SavedResearchStudio(package, history_title_origins_path=origins, history_tasks_root=tasks).history()
