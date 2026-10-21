from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from research_core.evidence import EvidenceError
from research_core.study_presentation import project_study_history, read_study_presentation


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
        read_study_presentation(destination)


@pytest.mark.parametrize("shared", [[], ["adjusted-daily-v1"]])
@pytest.mark.parametrize("reason", [{}, []])
def test_shared_reason_rejects_objects_for_all_reference_states(tmp_path: Path, shared: list[str], reason: object) -> None:
    task, metadata = registration(tmp_path)
    metadata.update(shared_data=shared, shared_data_reason=reason)
    save(task, metadata)
    with pytest.raises(EvidenceError, match="shared_data_reason must be text or null"):
        read_study_presentation(task)


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
        read_study_presentation(task)


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
        read_study_presentation(task)


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
        read_study_presentation(task)
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
        read_study_presentation(task)
    (task / "web-report").mkdir()
    (task / "web-report/index.html").write_text("<h1>Synthetic</h1>", encoding="utf-8")
    assert project_study_history({"items": []}, tmp_path)["items"][0]["webReportHref"] == f"#report/{task.name}"


def test_report_change_requires_registration_refresh(tmp_path: Path) -> None:
    task, _ = registration(tmp_path)
    (task / "report.md").write_text("# New report\n\nNo accepted result.", encoding="utf-8")
    with pytest.raises(EvidenceError, match="digest"):
        read_study_presentation(task)


def test_registration_size_bound(tmp_path: Path) -> None:
    task, _ = registration(tmp_path)
    (task / "presentation.json").write_bytes(b" " * (64 * 1024 + 1))
    with pytest.raises(EvidenceError, match="size bound"):
        read_study_presentation(task)


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


REGISTERED_TASKS = sorted((Path(__file__).resolve().parents[2] / "tasks").glob("*/presentation.json"))


@pytest.mark.parametrize("path", REGISTERED_TASKS, ids=lambda path: path.parent.name)
def test_repository_registrations_strictly_match_report_bytes(path: Path) -> None:
    assert read_study_presentation(path.parent)["id"] == path.parent.name


@pytest.mark.parametrize(
    ("damage", "reason"),
    [
        ("digest", "報告 SHA-256 與登錄不符"),
        ("title", "登錄標題或摘要與報告原文不符"),
        ("schema", "JSON／schema 無效"),
        ("json", "JSON／schema 無效"),
        ("escape", "非法或越界路徑"),
        ("section", "登錄欄位格式不符合契約"),
        ("missing", "登錄或來源檔案無法讀取"),
        ("publication", "JSON／schema 無效"),
        ("publication-version", "目前 publication 不一致"),
        ("utf8", "不是有效的 UTF-8"),
    ],
)
def test_bad_card_is_isolated_and_http_history_still_serves_valid_and_legacy(
    tmp_path: Path, damage: str, reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from research_api.saved_research_studio import create_studio_router
    from research_core.saved_research_studio import synthetic_studio_package

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    bad, metadata = registration(tasks)
    valid = tasks / "20261021-valid"
    valid.mkdir()
    (valid / "report.md").write_bytes((bad / "report.md").read_bytes())
    save(valid, {**metadata, "task_id": valid.name})
    legacy = {**read_study_presentation(valid), "id": "20200101-legacy", "date": "2020-01-01"}
    if damage == "digest":
        metadata["report_sha256"] = "0" * 64
    elif damage == "title":
        metadata["title"] = "<script>private-secret</script>"
    elif damage == "schema":
        metadata["schema"] = "<script>private-secret</script>"
    elif damage == "escape":
        metadata["report_path"] = "../private-secret"
    elif damage == "section":
        metadata["section"] = {}
    elif damage == "missing":
        (bad / "report.md").unlink()
    elif damage == "publication":
        (bad / "publications.json").write_text('{"schema":"private-secret"}', encoding="utf-8")
    elif damage == "publication-version":
        metadata["publication"] = "private-secret"
    elif damage == "utf8":
        (bad / "report.md").write_bytes(b"\xff")
        metadata["report_sha256"] = hashlib.sha256(b"\xff").hexdigest()
    save(bad, metadata)
    if damage == "json":
        (bad / "presentation.json").write_text("{invalid-private-secret", encoding="utf-8")
    package = tmp_path / "studio.json"
    payload = synthetic_studio_package()
    payload["researchHistory"]["items"] = [legacy]
    package.write_text(json.dumps(payload), encoding="utf-8")
    app = FastAPI()
    app.include_router(create_studio_router(package, history_presentation_path=None, history_tasks_root=tasks))
    response = TestClient(app).get("/saved-research-studio/v1/research-history")
    assert response.status_code == 200
    rows = {item["id"]: item for item in response.json()["items"]}
    assert set(rows) == {bad.name, valid.name, legacy["id"]}
    assert rows[bad.name]["status"] == "登錄需更新"
    assert reason in rows[bad.name]["sourceNote"]
    assert reason in caplog.text
    assert rows[valid.name]["conclusion"] == "No accepted result."
    assert rows[legacy["id"]]["conclusion"] == legacy["conclusion"]
    assert "private-secret" not in response.text
    assert "private-secret" not in caplog.text
    assert "Study registration needs update" in caplog.text


def test_unexpected_programming_error_is_not_hidden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import research_core.study_presentation as presentation

    registration(tmp_path)

    def broken_reader(root: Path) -> dict:
        raise TypeError("unexpected implementation defect")

    monkeypatch.setattr(presentation, "read_study_presentation", broken_reader)
    with pytest.raises(TypeError, match="unexpected implementation defect"):
        project_study_history({"items": []}, tmp_path)


def history_scenario(tmp_path: Path) -> tuple[Path, Path, Path, dict]:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    bad, metadata = registration(tasks)
    metadata["web_report"] = True
    (bad / "web-report").mkdir()
    (bad / "web-report/index.html").write_text("<h1>Synthetic report</h1>", encoding="utf-8")
    save(bad, metadata)
    valid = tasks / "20261021-valid"
    valid.mkdir()
    (valid / "report.md").write_bytes((bad / "report.md").read_bytes())
    save(valid, {**metadata, "task_id": valid.name, "web_report": False})
    previous = {**read_study_presentation(bad), "outcome": "candidate_failed"}
    legacy = {**read_study_presentation(valid), "id": "20200101-legacy", "date": "2020-01-01"}
    history = {"schema": "saved-research-history.v1", "historyComplete": False, "items": [previous, legacy]}
    return tasks, bad, valid, history


def http_history(tmp_path: Path, tasks: Path, history: dict) -> dict:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from research_api.saved_research_studio import create_studio_router
    from research_core.saved_research_studio import synthetic_studio_package

    payload = synthetic_studio_package()
    payload["researchHistory"] = history
    package = tmp_path / "studio.json"
    package.write_text(json.dumps(payload), encoding="utf-8")
    app = FastAPI()
    app.include_router(create_studio_router(package, history_presentation_path=None, history_tasks_root=tasks))
    response = TestClient(app).get("/saved-research-studio/v1/research-history")
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("missing", ["report.md", "web-report/index.html"])
def test_unavailable_existing_card_clears_link_without_rewriting_saved_provenance(tmp_path: Path, missing: str) -> None:
    tasks, bad, valid, history = history_scenario(tmp_path)
    original = copy.deepcopy(history)
    previous, legacy = original["items"]
    assert previous["webReportHref"] == f"#report/{bad.name}"
    (bad / missing).unlink()
    for projected in (project_study_history(history, tasks), http_history(tmp_path, tasks, history)):
        rows = {item["id"]: item for item in projected["items"]}
        assert set(rows) == {bad.name, valid.name, legacy["id"]}
        failed = rows[bad.name]
        assert failed["status"] == "登錄需更新"
        assert failed.get("webReportHref") is None
        for field in (
            "title",
            "originalTitle",
            "conclusion",
            "originalSummary",
            "outcome",
            "reportPath",
            "reportSha256",
            "currentPublication",
            "registryEventIds",
        ):
            assert failed[field] == previous[field]
        assert rows[valid.name]["conclusion"] == "No accepted result."
        assert rows[legacy["id"]]["conclusion"] == legacy["conclusion"]
    assert history == original


@pytest.mark.parametrize("source", ["presentation.json", "publications.json", "research_result.json"])
def test_deep_json_source_is_rejected_strictly_but_isolated_in_history(tmp_path: Path, source: str) -> None:
    tasks, bad, valid, history = history_scenario(tmp_path)
    # Keep only a distinct legacy card, so the bad registration creates a placeholder.
    history["items"] = history["items"][1:]
    nested = "[" * 1500 + "0" + "]" * 1500
    assert len(nested.encode()) < 64 * 1024
    (bad / source).write_text(nested, encoding="utf-8")
    with pytest.raises(EvidenceError):
        read_study_presentation(bad)
    for projected in (project_study_history(history, tasks), http_history(tmp_path, tasks, history)):
        rows = {item["id"]: item for item in projected["items"]}
        assert set(rows) == {bad.name, valid.name, "20200101-legacy"}
        assert rows[bad.name]["status"] == "登錄需更新"
        assert rows[bad.name].get("webReportHref") is None
        assert rows[valid.name]["conclusion"] == "No accepted result."
        assert rows["20200101-legacy"]["conclusion"] == "No accepted result."


def deep_json_tree() -> object:
    tree: object = 0
    for _ in range(1500):
        tree = [tree]
    return tree


def test_public_finite_json_rejects_excessive_python_tree_depth() -> None:
    from research_core.evidence import finite_json

    with pytest.raises(EvidenceError):
        finite_json(deep_json_tree())


def test_read_json_translates_recursion_in_finite_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import research_core.evidence as evidence

    path = tmp_path / "synthetic.json"
    path.write_text("{}", encoding="utf-8")
    tree = deep_json_tree()
    monkeypatch.setattr(evidence.json, "loads", lambda *args, **kwargs: tree)
    with pytest.raises(EvidenceError):
        evidence.read_json(path)
