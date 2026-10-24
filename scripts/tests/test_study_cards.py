"""Study-card validation, isolated warnings and private/public HTTP boundaries."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import zlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from research_api.saved_research_studio import create_studio_router
from research_api.studies import create_studies_router
from research_core import scratch_runs
from research_core.saved_research_studio import synthetic_studio_package
from research_core.study_cards import SCHEMA_PATH, StudyCardError, StudyCards, read_study_card


def registration(root: Path, identity: str = "20261024-fictional-study") -> tuple[Path, dict]:
    task = root / identity
    task.mkdir(parents=True)
    report = b"# Fictional study\n\nThe fictional sample contains 12 examples.\n\nOnly fictional examples were examined.\n"
    (task / "report.md").write_bytes(report)
    value: dict = {
        "schema": "study-card.v2",
        "task_id": identity,
        "kind": "study",
        "question": "What happened in the fictional sample?",
        "answer": "The fictional sample contains twelve examples.",
        "verdict": "not_evaluated",
        "data_period": None,
        "key_numbers": [
            {
                "label": "Fictional examples",
                "value": 12,
                "unit": "count",
                "highlight": True,
                "source_excerpt": "The fictional sample contains 12 examples.",
            }
        ],
        "limitation": "Only fictional examples were examined.",
        "report": {"web_report": None, "markdown": "report.md"},
        "account_run": None,
        "delivery_state": None,
        "scratch_run": None,
        "provenance": {
            "answer_source": "The fictional sample contains 12 examples.",
            "report_sha256": hashlib.sha256(report).hexdigest(),
            "publication": None,
            "shared_data": [],
            "legacy_history_id": None,
        },
    }
    save(task, value)
    return task, value


def save(task: Path, value: dict) -> None:
    (task / "study.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def saved_package(path: Path, identity: str, quote: str) -> Path:
    value = synthetic_studio_package()
    value["researchHistory"]["items"] = [
        {
            "id": identity,
            "date": "2026-10-24",
            "title": "Archived fictional study",
            "status": "Archived fictional result",
            "evidenceState": "fictional_saved_result",
            "conclusion": quote,
            "originalSummary": quote,
            "reportPath": f"tasks/{identity}/report.md",
            "reviewConfirmed": False,
            "registryEventIds": [],
        }
    ]
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def client(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    *,
    mode: str = "local-private",
    package: Path | None = None,
) -> TestClient:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", mode)
    app = FastAPI()
    app.include_router(create_studies_router(tasks_root=root, package_path=package))
    return TestClient(app)


def test_valid_card_preserves_source_and_registration_bytes(tmp_path: Path) -> None:
    task, value = registration(tmp_path)
    original = {name: (task / name).read_bytes() for name in ("study.json", "report.md")}
    card, warnings = read_study_card(task)
    assert card["task_id"] == value["task_id"]
    assert card["answer"] == value["answer"]
    assert warnings == []
    assert all((task / name).read_bytes() == raw for name, raw in original.items())
    assert "progress" not in json.loads((task / "study.json").read_bytes())


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("schema", "study-card.v1"),
        ("kind", "research"),
        ("verdict", "approved"),
        ("delivery_state", "merged"),
        ("question", ""),
        ("answer", "x" * 161),
        ("limitation", "x" * 121),
        ("progress", {"step": 1, "total": 2}),
        ("data_period", {"from": "2026-02-30", "to": "2026-10-24"}),
        ("scratch_run", {"run": "../another-run"}),
    ],
)
def test_schema_rejects_invalid_fields(tmp_path: Path, field: str, invalid: object) -> None:
    task, value = registration(tmp_path)
    value[field] = invalid
    save(task, value)
    with pytest.raises(StudyCardError):
        read_study_card(task)


def test_schema_rejects_a_missing_required_field(tmp_path: Path) -> None:
    task, value = registration(tmp_path)
    del value["limitation"]
    save(task, value)
    with pytest.raises(StudyCardError):
        read_study_card(task)


def test_task_id_must_match_its_directory(tmp_path: Path) -> None:
    task, value = registration(tmp_path)
    value["task_id"] = "20261024-another-study"
    save(task, value)
    with pytest.raises(StudyCardError):
        read_study_card(task)


@pytest.mark.parametrize("field", ["answer", "number"])
def test_excerpts_must_be_contiguous_report_text(tmp_path: Path, field: str) -> None:
    task, value = registration(tmp_path)
    invented = "The fictional sample contains 12 examples. Only fictional examples were examined."
    if field == "answer":
        value["provenance"]["answer_source"] = invented
    else:
        value["key_numbers"][0]["source_excerpt"] = invented
    save(task, value)
    with pytest.raises(StudyCardError):
        read_study_card(task)


def test_report_excerpt_may_be_a_contiguous_substring(tmp_path: Path) -> None:
    task, value = registration(tmp_path)
    value["provenance"]["answer_source"] = "fictional sample contains 12"
    value["key_numbers"][0]["source_excerpt"] = "contains 12 examples."
    save(task, value)
    assert read_study_card(task)[1] == []


def test_number_value_cannot_be_a_boolean(tmp_path: Path) -> None:
    task, value = registration(tmp_path)
    value["key_numbers"][0]["value"] = True
    save(task, value)
    with pytest.raises(StudyCardError):
        read_study_card(task)


def test_legacy_excerpts_use_the_same_saved_history_item(tmp_path: Path) -> None:
    task, value = registration(tmp_path)
    quote = "The saved fictional study has 12 examples."
    value["provenance"].update(answer_source=quote, legacy_history_id=task.name)
    value["key_numbers"][0]["source_excerpt"] = quote
    save(task, value)
    history = {task.name: {"id": task.name, "originalSummary": quote}}
    previous = copy.deepcopy(history)
    assert read_study_card(task, legacy_history=history)[1] == []
    assert history == previous


@pytest.mark.parametrize("damage", ["missing-id", "different-item", "report-only", "joined-fields"])
def test_legacy_excerpt_cannot_fall_back_or_join_fields(tmp_path: Path, damage: str) -> None:
    task, value = registration(tmp_path)
    quote = value["provenance"]["answer_source"]
    value["provenance"]["legacy_history_id"] = task.name
    history = {task.name: {"id": task.name, "originalSummary": quote}}
    if damage == "missing-id":
        history = {}
    elif damage == "different-item":
        history = {"20261024-another": {"id": "20261024-another", "originalSummary": quote}}
    elif damage == "report-only":
        history[task.name]["originalSummary"] = "A different saved conclusion."
    else:
        history[task.name] = {"id": task.name, "originalTitle": "The fictional sample", "originalSummary": "contains 12 examples."}
    save(task, value)
    with pytest.raises(StudyCardError):
        read_study_card(task, legacy_history=history)


def test_null_sources_and_reports_are_valid_when_no_excerpts_are_claimed(tmp_path: Path) -> None:
    task, value = registration(tmp_path)
    value["report"] = {"web_report": None, "markdown": None}
    value["key_numbers"] = []
    value["provenance"].update(answer_source=None, report_sha256=None)
    save(task, value)
    result = StudyCards(task.parent).read()
    assert result["cards"][0]["verdict"] == "not_evaluated"
    assert [warning["code"] for warning in result["warnings"]] == ["source_unavailable"]


def test_digest_mismatch_warns_without_hiding_card_or_changing_report(tmp_path: Path) -> None:
    task, _ = registration(tmp_path)
    report = task / "report.md"
    changed = report.read_bytes() + b"\nA later fictional appendix.\n"
    report.write_bytes(changed)
    card, warnings = read_study_card(task)
    assert card["task_id"] == task.name
    assert any(warning["code"] == "report_sha256_mismatch" and warning["task_id"] == task.name for warning in warnings)
    assert report.read_bytes() == changed


@pytest.mark.parametrize("field", ["markdown", "web_report"])
@pytest.mark.parametrize("path", ["../outside.md", "/outside.md", "C:/outside.md", "C:outside.md", r"..\outside.md"])
def test_report_paths_reject_escape_and_nonportable_names(tmp_path: Path, field: str, path: str) -> None:
    task, value = registration(tmp_path)
    value["report"][field] = path
    save(task, value)
    with pytest.raises(StudyCardError):
        read_study_card(task)


def test_report_file_must_exist(tmp_path: Path) -> None:
    task, value = registration(tmp_path)
    value["report"]["web_report"] = "web-report/missing.html"
    save(task, value)
    with pytest.raises(StudyCardError):
        read_study_card(task)


@pytest.mark.skipif(os.name != "nt", reason="NTFS junction safety requires Windows")
def test_report_rejects_a_real_windows_junction(tmp_path: Path) -> None:
    task, value = registration(tmp_path / "tasks")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "report.md").write_text("External content.", encoding="utf-8")
    link = task / "linked"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    value["report"]["web_report"] = "linked/report.md"
    save(task, value)
    with pytest.raises(StudyCardError):
        read_study_card(task)
    assert (outside / "report.md").read_text(encoding="utf-8") == "External content."


@pytest.mark.parametrize(
    "raw",
    [
        "{invalid",
        '{"schema":"study-card.v2","schema":"study-card.v2"}',
        '{"number":NaN}',
        '{"nested":' + "[" * 1500 + "null" + "]" * 1500 + "}",
    ],
    ids=["syntax", "duplicate-key", "nonfinite", "too-deep"],
)
def test_bad_card_is_isolated_from_other_studies(tmp_path: Path, raw: str) -> None:
    good, _ = registration(tmp_path, "20261024-good")
    bad, _ = registration(tmp_path, "20261024-bad")
    (bad / "study.json").write_text(raw, encoding="utf-8")
    result = StudyCards(tmp_path).read()
    assert [card["task_id"] for card in result["cards"]] == [good.name]
    assert any(warning["task_id"] == bad.name for warning in result["warnings"])


def test_tooling_is_opt_in(tmp_path: Path) -> None:
    study, _ = registration(tmp_path, "20261024-study")
    tooling, value = registration(tmp_path, "20261024-tooling")
    value["kind"] = "tooling"
    save(tooling, value)
    view = StudyCards(tmp_path)
    assert [card["task_id"] for card in view.read()["cards"]] == [study.name]
    assert {card["task_id"] for card in view.read(include_tooling=True)["cards"]} == {study.name, tooling.name}


def test_scratch_progress_is_merged_and_refreshed_without_editing_card(tmp_path: Path) -> None:
    task, value = registration(tmp_path / "tasks")
    shared = tmp_path / "shared"
    scratch = shared / "scratch"
    scratch.mkdir(parents=True)
    value["scratch_run"] = {"run": "fictional-run"}
    value["verdict"] = "running"
    save(task, value)
    original = (task / "study.json").read_bytes()
    with scratch_runs.create_run(task.name, "fictional-run", purpose="test progress", owner="test", root=scratch, repo_root=tmp_path) as run:
        first = {"step": 1, "total": 4, "label": "First fictional phase"}
        run.heartbeat(progress=first)
        reader = StudyCards(task.parent, shared_root=shared)
        card = reader.read()["cards"][0]
        assert card["progress"] == first
        assert card["run_state"] == "running"
        second = {"step": 2, "total": 4, "label": "Second fictional phase"}
        run.heartbeat(progress=second)
        assert reader.read()["cards"][0]["progress"] == second
    assert (task / "study.json").read_bytes() == original


def test_missing_scratch_run_warns_and_keeps_card(tmp_path: Path) -> None:
    task, value = registration(tmp_path / "tasks")
    value["scratch_run"] = {"run": "missing"}
    save(task, value)
    shared = tmp_path / "shared"
    shared.mkdir()
    result = StudyCards(task.parent, shared_root=shared).read()
    assert [card["task_id"] for card in result["cards"]] == [task.name]
    assert any(warning["code"] == "scratch_unavailable" and warning["task_id"] == task.name for warning in result["warnings"])


def test_private_http_route_hides_tooling_and_returns_isolated_warnings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    study, _ = registration(tmp_path, "20261024-study")
    tooling, value = registration(tmp_path, "20261024-tooling")
    value["kind"] = "tooling"
    save(tooling, value)
    (study / "report.md").write_bytes((study / "report.md").read_bytes() + b"\nExtra fictional text.\n")
    http = client(monkeypatch, tmp_path)
    response = http.get("/studies", headers={"X-Research-Data-Mode": "local-private"})
    assert response.status_code == 200
    assert [card["task_id"] for card in response.json()["cards"]] == [study.name]
    assert any(warning["code"] == "report_sha256_mismatch" for warning in response.json()["warnings"])
    assert len(http.get("/studies?include_tooling=1").json()["cards"]) == 2


def test_synthetic_http_returns_four_fictional_cases_without_reading_local_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Neither a local card nor the package is valid: demo mode must ignore both.
    task = tmp_path / "20261024-private-content"
    task.mkdir()
    (task / "study.json").write_text("PRIVATE DATA MUST NOT BE READ", encoding="utf-8")
    package = tmp_path / "private-package.json"
    package.write_text("PRIVATE PACKAGE MUST NOT BE READ", encoding="utf-8")
    http = client(monkeypatch, tmp_path, mode="public-synthetic", package=package)
    response = http.get("/studies?include_tooling=1")
    assert response.status_code == 200
    result = response.json()
    assert result["warnings"] == []
    assert len(result["cards"]) == 4
    assert any(card["delivery_state"] == "delivered" for card in result["cards"])
    assert any(card["verdict"] == "running" and card.get("progress") for card in result["cards"])
    assert any(card["kind"] == "tooling" for card in result["cards"])
    assert any(card["verdict"] == "archived" and card["account_run"] for card in result["cards"])
    assert all("虛構" in " ".join((card["question"], card["answer"], card["limitation"])) for card in result["cards"])
    assert "PRIVATE" not in response.text
    assert len(http.get("/studies").json()["cards"]) == 3


@pytest.mark.parametrize("actual,requested", [("local-private", "public-synthetic"), ("public-synthetic", "local-private")])
def test_http_data_mode_mismatch_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, actual: str, requested: str) -> None:
    http = client(monkeypatch, tmp_path, mode=actual)
    assert http.get("/studies", headers={"X-Research-Data-Mode": requested}).status_code == 503


def test_unknown_http_data_mode_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    http = client(monkeypatch, tmp_path, mode="unknown")
    assert http.get("/studies").status_code == 503


def test_private_package_uses_original_history_instead_of_current_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task, value = registration(tmp_path / "tasks")
    current_quote = value["provenance"]["answer_source"]
    archived_quote = "The archived fictional sample contains 12 examples."
    value["provenance"].update(answer_source=archived_quote, legacy_history_id=task.name)
    value["key_numbers"][0]["source_excerpt"] = archived_quote
    save(task, value)
    package = saved_package(tmp_path / "saved-package.json", task.name, archived_quote)
    original_package = package.read_bytes()
    http = client(monkeypatch, task.parent, package=package)

    original = http.get("/studies").json()
    assert original["warnings"] == []
    assert original["cards"][0]["provenance"]["answer_source"] == archived_quote
    assert archived_quote not in (task / "report.md").read_text(encoding="utf-8")

    # A current-report quote is not evidence for a card tied to the saved history.
    value["provenance"]["answer_source"] = current_quote
    value["key_numbers"][0]["source_excerpt"] = current_quote
    save(task, value)
    replaced = http.get("/studies").json()
    assert replaced["cards"] == []
    assert any(warning["task_id"] == task.name and warning["code"] == "invalid_card" for warning in replaced["warnings"])
    assert package.read_bytes() == original_package


def test_missing_and_corrupt_packages_only_hide_legacy_cards(tmp_path: Path) -> None:
    good, _ = registration(tmp_path / "tasks", "20261024-current")
    legacy, value = registration(tmp_path / "tasks", "20261024-legacy")
    value["provenance"]["legacy_history_id"] = legacy.name
    save(legacy, value)
    missing = tmp_path / "missing-package.json"
    corrupt = tmp_path / "corrupt-package.json"
    corrupt.write_text("{broken", encoding="utf-8")
    for package in (missing, corrupt):
        result = StudyCards(good.parent, package_path=package).read()
        assert [card["task_id"] for card in result["cards"]] == [good.name]
        assert result["warnings"]
        assert all(warning["task_id"] == legacy.name and warning["code"] == "legacy_unavailable" for warning in result["warnings"])


def test_registration_in_an_undated_directory_is_reported_not_silently_skipped(tmp_path: Path) -> None:
    task, _ = registration(tmp_path / "tasks")
    renamed = task.with_name("undated-study")
    task.rename(renamed)
    result = StudyCards(renamed.parent).read()
    assert result["cards"] == []
    assert [(warning["task_id"], warning["code"]) for warning in result["warnings"]] == [(renamed.name, "invalid_card")]


def test_damaged_compression_is_isolated_to_legacy_cards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import study_cards

    current, _ = registration(tmp_path / "tasks", "20261024-current")
    legacy, value = registration(tmp_path / "tasks", "20261024-legacy")
    value["provenance"]["legacy_history_id"] = legacy.name
    save(legacy, value)

    def damaged_package(path: Path) -> dict:
        raise zlib.error("damaged compressed data")

    monkeypatch.setattr(study_cards, "read_studio_package", damaged_package)
    result = StudyCards(current.parent, package_path=tmp_path / "saved-package.json").read()
    assert [card["task_id"] for card in result["cards"]] == [current.name]
    assert [warning["code"] for warning in result["warnings"]] == ["legacy_unavailable"]


def test_synthetic_cards_match_the_saved_card_schema_after_response_fields_are_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    http = client(monkeypatch, tmp_path, mode="public-synthetic")
    cards = http.get("/studies?include_tooling=1").json()["cards"]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert len(cards) == 4
    for card in cards:
        saved_form = {key: value for key, value in card.items() if key not in {"progress", "run_state"}}
        validator.validate(saved_form)


def test_synthetic_account_card_opens_an_existing_fictional_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "public-synthetic")
    app = FastAPI()
    app.include_router(create_studies_router(tasks_root=tmp_path / "unavailable-private-tasks"))
    app.include_router(create_studio_router())
    http = TestClient(app)
    cards = http.get("/studies").json()["cards"]
    account = next(card["account_run"] for card in cards if card["account_run"] is not None)
    response = http.get("/saved-research-studio/v1/run", params={"run_id": account["run_id"]})
    assert response.status_code == 200
    assert response.json()["synthetic"] is True
