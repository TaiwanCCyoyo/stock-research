"""Reading-edition safety and original-source HTTP boundaries with synthetic files."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api.studies import create_studies_router
from research_core import report_reading
from research_core.report_reading import MAX_MARKDOWN_BYTES, MAX_RECORD_BYTES, ReportReadingError, ReportReadings

IDENTITY = "20261102-fictional-reading"


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def setup_reading(root: Path) -> tuple[Path, dict]:
    task = root / IDENTITY
    task.mkdir()
    (task / "original.md").write_text("# Original\nA fictional source, not market evidence.\n", encoding="utf-8")
    (task / "reading-report.md").write_text("# What happened?\nNo reliable difference was established.\nOnly fictional examples.\n", encoding="utf-8")
    record = {
        "schema": "report-reading.v1",
        "task_id": IDENTITY,
        "state": "ready",
        "reason": "Reading checked against the fictional source.",
        "updated_at": "2026-11-02",
        "edition": "reading-report.md",
        "question": "What happened?",
        "answer": "No reliable difference was established.",
        "limitation": "Only fictional examples.",
        "data_period": {"from": "2020-01-01", "to": "2020-12-31"},
        "sources": [{"label": "Original", "path": f"{IDENTITY}/original.md"}],
    }
    write_json(task / "reading.json", record)
    return task, record


def original_card(task: Path) -> dict:
    value: dict = {
        "schema": "study-card.v2",
        "task_id": IDENTITY,
        "kind": "study",
        "question": "What happened?",
        "answer": "Old wording.",
        "verdict": "mixed",
        "data_period": None,
        "key_numbers": [],
        "limitation": "Only fictional examples.",
        "report": {"web_report": None, "markdown": "original.md"},
        "account_run": None,
        "delivery_state": None,
        "scratch_run": None,
        "provenance": {"answer_source": None, "report_sha256": "0" * 64, "publication": None, "shared_data": [], "legacy_history_id": None},
    }
    write_json(task / "study.json", value)
    return value


def client(monkeypatch: pytest.MonkeyPatch, root: Path, mode: str = "local-private") -> TestClient:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", mode)
    app = FastAPI()
    app.include_router(create_studies_router(tasks_root=root))
    return TestClient(app)


def test_history_original_capability_requires_a_valid_safe_document(tmp_path: Path) -> None:
    task, record = setup_reading(tmp_path)
    record.update(state="history", edition=None)
    write_json(task / "reading.json", record)
    original_card(task)
    assert ReportReadings(tmp_path).read()["original_reports"] == [IDENTITY]
    (task / "original.md").unlink()
    assert ReportReadings(tmp_path).read()["original_reports"] == []


def test_ready_is_independent_of_old_card_and_keeps_original_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task, record = setup_reading(tmp_path)
    (task / "study.json").write_text('{"broken": true}', encoding="utf-8")
    originals = {p.name: p.read_bytes() for p in task.iterdir()}
    http = client(monkeypatch, tmp_path)
    result = http.get("/studies").json()
    assert result["cards"] == []
    assert result["warnings"][0]["code"] == "invalid_card"
    assert result["readings"] == [record]
    assert result["reading_warnings"] == []
    reading = http.get(f"/studies/{IDENTITY}/reading").json()
    assert reading["reading"] == record
    assert reading["state"] == "ready"
    assert "No reliable difference" in reading["markdown"]
    source = http.get(f"/studies/{IDENTITY}/source?index=0").json()
    assert source["label"] == "Original"
    assert source["markdown"].startswith("# Original")
    assert {p.name: p.read_bytes() for p in task.iterdir()} == originals


@pytest.mark.parametrize(
    "path", ["../secret.md", "C:/secret.md", "original.md", f"{IDENTITY}/../secret.md", f"{IDENTITY}/original.txt", f"{IDENTITY}\\original.md"]
)
def test_declared_sources_cannot_escape_tasks_or_read_other_formats(tmp_path: Path, path: str) -> None:
    task, value = setup_reading(tmp_path)
    value["sources"][0]["path"] = path
    write_json(task / "reading.json", value)
    with pytest.raises((ValueError, OSError)):
        ReportReadings(tmp_path).record(IDENTITY)


@pytest.mark.parametrize("path", ["../original.md", "C:/secret.md", "/secret.md", "reading-report.md/../original.md", "original.txt"])
def test_edition_path_is_task_relative_markdown(tmp_path: Path, path: str) -> None:
    task, value = setup_reading(tmp_path)
    value["edition"] = path
    write_json(task / "reading.json", value)
    assert ReportReadings(tmp_path).read()["readings"] == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("state", "approved"),
        ("updated_at", "2026-02-30"),
        ("reason", "  "),
        ("question", ""),
        ("answer", "Unsupported new conclusion"),
        ("limitation", "No limitations"),
        ("sources", []),
        ("edition", None),
        ("data_period", {"from": "2021-01-01", "to": "2020-01-01"}),
        ("task_id", "20261102-other-task"),
    ],
)
def test_ready_registration_rejects_incomplete_or_unmatched_metadata(tmp_path: Path, key: str, value: object) -> None:
    task, record = setup_reading(tmp_path)
    record[key] = value
    write_json(task / "reading.json", record)
    result = ReportReadings(tmp_path).read()
    assert result["readings"] == []
    assert result["reading_warnings"][0]["task_id"] == IDENTITY
    assert "Unsupported new conclusion" not in json.dumps(result)


def test_missing_source_fails_closed_instead_of_falling_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task, _ = setup_reading(tmp_path)
    original_card(task)
    (task / "original.md").unlink()
    http = client(monkeypatch, tmp_path)
    assert http.get(f"/studies/{IDENTITY}/reading").status_code == 404
    assert http.get(f"/studies/{IDENTITY}/source?index=0").status_code == 404


def test_source_selection_is_only_by_registered_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_reading(tmp_path)
    http = client(monkeypatch, tmp_path)
    for index in [-1, 32, "wrong"]:
        assert http.get(f"/studies/{IDENTITY}/source?index={index}").status_code == 422
    assert http.get(f"/studies/{IDENTITY}/source?index=1").status_code == 404
    assert http.get(f"/studies/{IDENTITY}/source?path=original.md").status_code == 422


def test_original_report_fallback_preserves_mismatch_warning_without_rehash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task, _ = setup_reading(tmp_path)
    (task / "reading.json").unlink()
    original_card(task)
    http = client(monkeypatch, tmp_path)
    listing = http.get("/studies").json()
    assert listing["warnings"][0]["code"] == "report_sha256_mismatch"
    result = http.get(f"/studies/{IDENTITY}/reading").json()
    assert result["reading"] is None
    assert result["state"] == "history"
    assert "尚未完成閱讀版核對" in result["reason"]
    assert result["markdown"].startswith("# Original")


def test_original_fallback_rejects_invalid_schema_and_unsafe_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task, _ = setup_reading(tmp_path)
    (task / "reading.json").unlink()
    base = original_card(task)
    http = client(monkeypatch, tmp_path)
    for change in ({"kind": "not-a-kind"}, {"report": {"markdown": "../secret.md", "web_report": None}}, {"task_id": "20261102-other"}):
        write_json(task / "study.json", {**copy.deepcopy(base), **change})
        assert http.get(f"/studies/{IDENTITY}/reading").status_code == 404


@pytest.mark.parametrize("which", ["metadata", "edition", "source", "encoding", "duplicate"])
def test_file_size_encoding_and_duplicate_key_bounds(tmp_path: Path, which: str) -> None:
    task, _ = setup_reading(tmp_path)
    if which == "metadata":
        (task / "reading.json").write_bytes(b" " * (MAX_RECORD_BYTES + 1))
    elif which in {"edition", "source"}:
        (task / ("reading-report.md" if which == "edition" else "original.md")).write_bytes(b"x" * (MAX_MARKDOWN_BYTES + 1))
    elif which == "encoding":
        (task / "reading-report.md").write_bytes(b"\xff")
    else:
        (task / "reading.json").write_text('{"schema":"report-reading.v1","schema":"other"}', encoding="utf-8")
    assert ReportReadings(tmp_path).read()["readings"] == []


def test_public_mode_never_constructs_or_reads_private_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("private reader accessed")

    monkeypatch.setattr("research_api.studies.ReportReadings", forbidden)
    monkeypatch.setattr("research_api.studies.StudyCards", forbidden)
    http = client(monkeypatch, tmp_path, "public-synthetic")
    assert http.get("/studies").json()["readings"] == []
    assert http.get(f"/studies/{IDENTITY}/reading").status_code == 404
    assert http.get(f"/studies/{IDENTITY}/source?index=0").status_code == 404


@pytest.mark.parametrize("route", ["/studies", f"/studies/{IDENTITY}/reading", f"/studies/{IDENTITY}/source?index=0"])
def test_mode_mismatch_precedes_reader_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str) -> None:
    http = client(monkeypatch, tmp_path)
    assert http.get(route, headers={"X-Research-Data-Mode": "public-synthetic"}).status_code == 503


def test_reading_task_count_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_reading(tmp_path)
    monkeypatch.setattr(report_reading, "MAX_RECORDS", 0)
    result = ReportReadings(tmp_path).read()
    assert result["readings"] == []
    assert result["reading_warnings"][0]["code"] == "readings_unavailable"


def test_reparse_markdown_is_rejected_with_portable_lstat_simulation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task, _ = setup_reading(tmp_path)
    target = task / "original.md"
    original = Path.lstat

    class ReparseStat:
        st_file_attributes = 1024
        st_mode = original(target).st_mode

    def fake_lstat(path: Path):
        return ReparseStat() if path == target else original(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises((ValueError, ReportReadingError), match="reparse"):
        ReportReadings(tmp_path).record(IDENTITY)
