"""Partial evidence must remain useful without fabricating full-period conclusions."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api.saved_research_studio import create_studio_router
from research_core.saved_research_studio import SavedResearchStudio, _capture_coverage, read_studio_package, research_history
from scripts.tests.test_saved_research_studio import history_projection_fixture, package


def exposure_row(weight: float | None = 0) -> dict[str, Any]:
    return {
        "known": True,
        "runawayWeight": weight,
        "otherStockWeight": 0,
        "unknownStockWeight": 0,
        "otherAssetsWeight": 0,
        "cashWeight": 1,
    }


def cycle(days: int | None, known: int, total: int, *, closed: bool = True) -> dict[str, Any]:
    return {
        "closeDate": "2020-01-03" if closed else None,
        "capture": {"days": days, "knownDays": known, "totalDays": total},
    }


def test_positive_participation_is_confirmed_despite_unknown_dates_but_absence_is_not() -> None:
    run = {
        "positions": [
            cycle(1, 1, 3),  # Any known positive date proves participation.
            cycle(0, 3, 3),
            cycle(0, 1, 3),  # Partial negative evidence cannot prove absence.
            cycle(None, 0, 3),
            cycle(0, 0, 0),  # An empty interval is not confirmed absence.
            cycle(3, 3, 3, closed=False),
        ]
    }
    rows = [exposure_row(0), exposure_row(0.6), {**exposure_row(), "known": False}]
    before = copy.deepcopy((run, rows))
    assert _capture_coverage(run, rows) == {
        "closedTradeTotal": 5,
        "confirmedCapturedClosedTradeCount": 1,
        "confirmedNotCapturedClosedTradeCount": 1,
        "undeterminedClosedTradeCount": 3,
        "completeExposureDays": 2,
        "totalExposureDays": 3,
        "knownDayAverageWeight": pytest.approx(0.3),
    }
    assert (run, rows) == before


@pytest.mark.parametrize("key", ["runawayWeight", "otherStockWeight", "unknownStockWeight", "otherAssetsWeight", "cashWeight"])
@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), True, "0"])
def test_incomplete_or_non_numeric_weight_excludes_whole_date(key: str, invalid: Any) -> None:
    incomplete = {**exposure_row(0.8), key: invalid}
    coverage = _capture_coverage({"positions": []}, [exposure_row(0), incomplete])
    assert coverage["completeExposureDays"] == 1
    assert coverage["totalExposureDays"] == 2
    assert coverage["knownDayAverageWeight"] == 0


def test_no_complete_dates_stay_unknown_and_empty_closed_set_is_explicit() -> None:
    incomplete = exposure_row(0.8)
    del incomplete["cashWeight"]
    cases: list[list[dict[str, Any]]] = [[], [incomplete], [{**exposure_row(), "known": False}], [{}]]
    for rows in cases:
        coverage = _capture_coverage({"positions": []}, rows)
        assert coverage["closedTradeTotal"] == 0
        assert coverage["completeExposureDays"] == 0
        assert coverage["totalExposureDays"] == len(rows)
        assert coverage["knownDayAverageWeight"] is None


def test_ready_api_exposes_partial_coverage_without_changing_saved_statistics(tmp_path: Path) -> None:
    path, run = package(tmp_path)
    saved = read_studio_package(path)
    saved_bytes = path.read_bytes()
    membership = {"2020-01-01": True, "2020-01-02": None, "2020-01-03": False, "2020-01-04": False}

    def provider(code: str, day: str) -> dict[str, Any]:
        return {"onMap": membership[day], "metric": 1.2}

    service = SavedResearchStudio(path, provider)
    projected = service.run(run["id"])
    assert projected["capturedClosedTradeCount"] is None
    assert projected["captureAvgWeight"] is None
    coverage = projected["captureCoverage"]
    assert coverage["closedTradeTotal"] == 1
    assert coverage["confirmedCapturedClosedTradeCount"] == 1
    assert coverage["confirmedNotCapturedClosedTradeCount"] == 0
    assert coverage["undeterminedClosedTradeCount"] == 0
    assert coverage["completeExposureDays"] == 3
    assert coverage["totalExposureDays"] == 4
    assert coverage["knownDayAverageWeight"] == pytest.approx((100 / 1000) / 3)
    assert service.index()["runs"][0]["captureCoverage"] == coverage
    assert service.exposure(run["id"])["rows"][1]["known"] is False
    for field in ["statistics", "reconciliation", "netReturn", "finalEquity", "method"]:
        assert projected[field] == run[field]
    assert read_studio_package(path) == saved
    assert path.read_bytes() == saved_bytes


@pytest.mark.parametrize("state", ["loading", "failed"])
def test_unready_provider_never_fabricates_known_coverage(tmp_path: Path, state: str) -> None:
    path, run = package(tmp_path)

    class Provider:
        def state(self) -> str:
            return state

        def __call__(self, code: str, day: str) -> dict:
            pytest.fail("unready membership must not be evaluated")

    service = SavedResearchStudio(path, Provider())
    assert service.run(run["id"])["captureState"] == state
    assert "captureCoverage" not in service.run(run["id"])
    assert service.index()["runs"][0]["captureAvgWeight"] is None


def test_history_runtime_overlay_keeps_formal_verdict_and_original_evidence(tmp_path: Path) -> None:
    path, metadata_path, saved = history_projection_fixture(tmp_path)
    original_bytes = path.read_bytes()
    metadata = json.loads(metadata_path.read_bytes())
    metadata["studies"]["20261007-failed-research"].update({
        "plainTitle": "好懂的名稱",
        "section": "design",
        "status": "已結案",
        "reviewConfirmed": False,
    })
    metadata["studies"]["20261006-no-category"].update({"section": "market", "status": "行不通"})
    metadata["studies"]["not-in-saved-package"] = {"plainTitle": "不會憑空加入"}
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    service = SavedResearchStudio(path, history_presentation_path=metadata_path)
    projected = service.history()
    failed = projected["items"][0]
    assert failed["title"] == "好懂的名稱"
    assert failed["savedTitle"] == "20261007-failed-research"
    assert failed["section"] == "design"
    assert failed["conclusion"] == "呈現摘要不能覆寫保存原文"
    for key in ["outcome", "status", "originalSummary", "reportPath", "sourceIds", "evidenceState", "registryEventIds"]:
        if key in saved["researchHistory"]["items"][1]:
            assert failed[key] == saved["researchHistory"]["items"][1][key]
    assert "draftStatus" not in failed
    unjudged = projected["items"][1]
    assert unjudged["draftStatus"] == "行不通"
    assert unjudged["outcome"] is None
    assert unjudged["status"] == "研究中"
    assert projected["excludedInfrastructureCount"] == 1
    assert len(projected["items"]) == 3
    assert projected["sourceIds"] == saved["researchHistory"]["sourceIds"]
    assert read_studio_package(path) == saved
    assert path.read_bytes() == original_bytes
    failed["title"] = "caller mutation"
    assert service.history()["items"][0]["title"] == "好懂的名稱"
    metadata["studies"]["20261007-failed-research"]["plainTitle"] = "更新呈現名稱"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    assert service.history()["items"][0]["title"] == "更新呈現名稱"
    assert service.history()["items"][0]["savedTitle"] == "20261007-failed-research"


@pytest.mark.parametrize("section", [None, "infrastructure", "Method", False, ["market"], {}])
def test_invalid_history_section_is_integrity_error_without_leaking_paths(tmp_path: Path, section: Any) -> None:
    path, metadata_path, saved = history_projection_fixture(tmp_path)
    metadata = json.loads(metadata_path.read_bytes())
    metadata["studies"]["20261006-no-category"]["section"] = section
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    app = FastAPI()
    app.include_router(create_studio_router(path, history_presentation_path=metadata_path))
    client = TestClient(app)
    response = client.get("/saved-research-studio/v1/research-history")
    assert response.status_code == 503
    assert response.headers["X-Research-Evidence-Error"] == "integrity"
    assert str(tmp_path) not in response.text
    assert client.get("/saved-research-studio/v1/runs").status_code == 200
    assert read_studio_package(path) == saved


def test_exported_overlay_can_be_changed_and_withdrawn_without_rewriting_package(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    task = tasks / "20261008-new-study"
    task.mkdir(parents=True)
    (task / "report.md").write_text("# 原始研究標題\n\n原文結論。尚未確認。\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema_version": "research-registry.v1", "history_complete": False, "events": []}))
    metadata_path = tmp_path / "presentation.json"
    metadata: dict[str, Any] = {
        "schema": "research-presentation.v1",
        "studies": {
            task.name: {
                "plainTitle": "舊白話標題",
                "plainConclusion": "舊改寫摘要",
                "section": "design",
                "status": "行不通",
                "reviewConfirmed": True,
                "sourceNote": "舊呈現證據",
            }
        },
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    history = research_history(tasks, registry, metadata_path)
    assert history["items"][0]["originalTitle"] == "原始研究標題"
    assert history["items"][0]["title"] == "舊白話標題"
    path, _ = package(tmp_path)
    saved = read_studio_package(path)
    saved["researchHistory"] = history
    path.write_bytes(gzip.compress(json.dumps(saved, ensure_ascii=False).encode("utf-8")))
    original_bytes = path.read_bytes()
    service = SavedResearchStudio(path, history_presentation_path=metadata_path)
    metadata["studies"][task.name] = {"plainTitle": "新版白話標題", "plainConclusion": "新版摘要", "section": "market"}
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    updated = service.history()["items"][0]
    assert updated["title"] == "新版白話標題"
    assert updated["savedTitle"] == "原始研究標題"
    assert updated["conclusion"] == "新版摘要"
    assert updated["reviewConfirmed"] is False
    assert updated["section"] == "market"
    assert "draftStatus" not in updated
    metadata["studies"] = {}
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    restored = service.history()["items"][0]
    assert restored["title"] == "原始研究標題"
    assert restored["conclusion"] == "原文結論。尚未確認。"
    assert restored["summarySource"] == "formal-report"
    assert restored["sourceNote"] is None
    assert restored["reviewConfirmed"] is False
    for field in ("savedTitle", "section", "draftStatus"):
        assert field not in restored
    for field in ("outcome", "status", "originalSummary", "reportPath", "evidenceState", "registryEventIds"):
        assert restored[field] == history["items"][0][field]
    assert read_studio_package(path) == saved
    assert path.read_bytes() == original_bytes


def legacy_history_origins(tmp_path: Path) -> tuple[Path, Path, Path, dict, dict]:
    path, metadata_path, saved = history_projection_fixture(tmp_path)
    row = saved["researchHistory"]["items"][1]
    row.update({
        "title": "舊改寫標題",
        "conclusion": "舊改寫結論",
        "summarySource": "presentation-metadata",
        "section": "design",
        "draftStatus": "舊示範判讀",
        "sourceNote": "舊呈現證據",
        "reviewConfirmed": True,
    })
    path.write_bytes(gzip.compress(json.dumps(saved, ensure_ascii=False).encode("utf-8")))
    history = saved["researchHistory"]
    origins = {
        "schema": "research-history-title-origins.v1",
        "historySha256": hashlib.sha256(json.dumps(history, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "sourceRevision": "a" * 40,
        "titles": {item["id"]: {"title": "報告版本：" + item["id"], "sourcePath": item["reportPath"], "sourceSha256": "b" * 64} for item in history["items"]},
    }
    origins_path = tmp_path / "title-origins.json"
    origins_path.write_text(json.dumps(origins, ensure_ascii=False), encoding="utf-8")
    return path, metadata_path, origins_path, saved, origins


def test_legacy_overlay_uses_pinned_report_titles_and_withdraws_cached_fields(tmp_path: Path) -> None:
    path, metadata_path, origins_path, saved, _ = legacy_history_origins(tmp_path)
    before = path.read_bytes()
    service = SavedResearchStudio(path, history_presentation_path=metadata_path, history_title_origins_path=origins_path)
    overlaid = service.history()["items"][0]
    assert overlaid["title"] == "報告版本：20261007-failed-research"
    assert overlaid["conclusion"] == "呈現摘要不能覆寫保存原文"
    metadata_path.write_text(json.dumps({"schema": "research-presentation.v1", "studies": {}}), encoding="utf-8")
    restored = service.history()["items"][1]
    assert restored["title"] == "報告版本：20261007-failed-research"
    assert restored["legacyPresentationTitle"] == "舊改寫標題"
    assert restored["conclusion"] == "原始失敗研究"
    assert restored["titleSourceRevision"] == "a" * 40
    assert restored["titleSourceSha256"] == "b" * 64
    assert restored["titleBasis"] == "versioned-report-heading-not-legacy-export-title"
    assert restored["summarySource"] == "formal-report"
    assert restored["sourceNote"] is None
    assert restored["outcome"] == "candidate_failed"
    assert restored["status"] == "行不通"
    for field in ("section", "draftStatus", "savedTitle"):
        assert field not in restored
    assert read_studio_package(path) == saved
    assert path.read_bytes() == before


def test_legacy_missing_title_is_unknown_and_retains_search_alias(tmp_path: Path) -> None:
    path, _, _, saved, _ = legacy_history_origins(tmp_path)
    restored = SavedResearchStudio(path).history()["items"][1]
    assert restored["title"] == restored["id"]
    assert restored["originalTitleUnavailable"] is True
    assert restored["legacyPresentationTitle"] == "舊改寫標題"
    assert restored["conclusion"] == "原始失敗研究"
    assert read_studio_package(path) == saved


@pytest.mark.parametrize("fault", ["json", "schema", "fingerprint", "revision", "titles-shape", "missing", "extra", "title", "path", "hash"])
def test_title_origins_integrity_failures_are_path_free_and_other_routes_work(tmp_path: Path, fault: str) -> None:
    path, metadata_path, origins_path, saved, origins = legacy_history_origins(tmp_path)
    task_id = "20261007-failed-research"
    if fault == "schema":
        origins["schema"] = "future"
    elif fault == "fingerprint":
        origins["historySha256"] = "0" * 64
    elif fault == "revision":
        origins["sourceRevision"] = "not-a-revision"
    elif fault == "titles-shape":
        origins["titles"] = []
    elif fault == "missing":
        del origins["titles"][task_id]
    elif fault == "extra":
        origins["titles"]["not-in-package"] = origins["titles"][task_id]
    elif fault == "title":
        origins["titles"][task_id]["title"] = " "
    elif fault == "path":
        origins["titles"][task_id]["sourcePath"] = "other/report.md"
    elif fault == "hash":
        origins["titles"][task_id]["sourceSha256"] = True
    origins_path.write_text("{" if fault == "json" else json.dumps(origins), encoding="utf-8")
    app = FastAPI()
    app.include_router(create_studio_router(path, history_presentation_path=metadata_path, history_title_origins_path=origins_path))
    client = TestClient(app)
    response = client.get("/saved-research-studio/v1/research-history")
    assert response.status_code == 503
    assert response.headers["X-Research-Evidence-Error"] == "integrity"
    assert str(tmp_path) not in response.text
    assert client.get("/saved-research-studio/v1/runs").status_code == 200
    assert read_studio_package(path) == saved


def test_missing_title_snapshot_is_unavailable_then_retryable(tmp_path: Path) -> None:
    path, metadata_path, origins_path, _, _ = legacy_history_origins(tmp_path)
    original = origins_path.read_bytes()
    origins_path.unlink()
    app = FastAPI()
    app.include_router(create_studio_router(path, history_presentation_path=metadata_path, history_title_origins_path=origins_path))
    client = TestClient(app)
    response = client.get("/saved-research-studio/v1/research-history")
    assert response.status_code == 503
    assert response.headers["X-Research-Evidence-Error"] == "unavailable"
    assert str(tmp_path) not in response.text
    origins_path.write_bytes(original)
    assert client.get("/saved-research-studio/v1/research-history").status_code == 200
