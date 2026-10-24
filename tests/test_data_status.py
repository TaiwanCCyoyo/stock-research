"""Metadata-only data overview and private/public isolation contracts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api.data_status import create_data_status_router
from research_core import data_status, live_producer
from research_core.data_status import PRODUCER_NAMES, DataStatusView

NOW = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _producer(root: Path) -> dict[str, Any]:
    datasets: list[dict[str, object]] = [
        {
            "id": key,
            "name": "D:/private/source/hash",
            "data_period": {"from": "2020-01-01", "to": "2026-10-23"},
            "last_updated": NOW.isoformat(),
            "symbols": 10,
            "rows": 20,
            "status": "ok",
        }
        for key in PRODUCER_NAMES
    ]
    datasets[3]["data_period"] = {"from": "2020-01", "to": "2026-09"}
    document = {
        "schema": "producer-data-status.v1",
        "generated_at": NOW.isoformat(),
        "datasets": datasets,
    }
    _write(root / "data-status.json", document)
    return document


def _derived(root: Path, family: str = "prices-v1", **overrides: Any) -> Path:
    path = root / "derived" / family / "generations" / "one" / "status.json"
    status = {
        "family": family,
        "generation": "one",
        "calendar": {"first": "2020-01-01", "last": "2026-10-23"},
        "codes": 8,
        "bases": {"raw": {"rows": 30}},
        "built_at_utc": NOW.isoformat(),
        **overrides,
    }
    _write(path, status)
    _write(path.parents[2] / "current.json", {"generation": "one", "status_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return path


def _catalog(state: str = "complete", error: str | None = None) -> tuple[dict, None]:
    return {
        "entries": [
            {
                "data_id": "saved-study",
                "version_id": "private-digest",
                "status": state,
                "coverage": {"raw_input_period": {"start": "2019-01-01", "end": "2023-12-31"}},
                "viewer_metadata": {"security_count": 12},
                "metadata_error": error,
                "manifest": {"path": "private/path", "sha256": "secret-digest"},
            }
        ]
    }, None


@pytest.fixture
def view(tmp_path: Path) -> DataStatusView:
    producer = tmp_path / "producer"
    shared = tmp_path / "shared"
    _producer(producer)
    _derived(shared)
    return DataStatusView(
        producer_root=lambda: producer,
        shared_root=lambda: shared,
        catalog=_catalog,
        labels=lambda: {"prices-v1": {"display_title": "每日行情與技術指標"}, "saved-study": {"display_title": "第四版研究資料包"}},
        idle=lambda: None,
        now=lambda: NOW,
    )


def _client(view: DataStatusView) -> TestClient:
    app = FastAPI()
    app.include_router(create_data_status_router(view))
    return TestClient(app)


def test_three_sources_read_metadata_only(view: DataStatusView, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("overview attempted to open a data table")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(pq, "read_table", forbidden)
    monkeypatch.setattr(pq, "ParquetFile", forbidden)
    result = view.status()
    assert result["status"] == "ok"
    assert len(result["datasets"]) == 8
    assert {row["source"] for row in result["datasets"]} == {"producer", "derived", "catalog"}
    assert result["datasets"][6]["rows"] == 30
    assert result["datasets"][7]["symbols"] == 12
    assert result["datasets"][7]["rows"] is None
    assert result["datasets"][7]["last_updated"] is None
    assert result["datasets"][7]["name"] == "研究資料包"
    text = json.dumps(result, ensure_ascii=False)
    assert "private/path" not in text and "secret-digest" not in text
    assert all("/" not in row["name"] and "版" not in row["name"] for row in result["datasets"])


def test_all_families_discovered(view: DataStatusView) -> None:
    _derived(view._shared_root(), "another-v2", codes=5)
    rows = [item for item in view.status()["datasets"] if item["source"] == "derived"]
    assert len(rows) == 2
    assert {row["symbols"] for row in rows} == {5, 8}


def test_missing_status_is_explicit_without_database_fallback(view: DataStatusView) -> None:
    (view._producer_root() / "data-status.json").unlink()
    result = view.status()
    assert result["status"] == "partial"
    assert all(row["status"] == "missing" and row["rows"] is None for row in result["datasets"][:6])
    assert result["warnings"]


def test_corrupt_status_is_explicit(view: DataStatusView) -> None:
    (view._producer_root() / "data-status.json").write_text("{", encoding="utf-8")
    result = view.status()
    assert result["status"] == "partial"
    assert result["datasets"][0]["status"] == "missing"


@pytest.mark.parametrize(
    "changes",
    [
        {"rows": -1},
        {"rows": 0},
        {"symbols": 0},
        {"symbols": True},
        {"status": "unknown"},
        {"data_period": {"from": "2026-19-01", "to": "2026-10-23"}},
        {"last_updated": "not-a-time"},
    ],
)
def test_invalid_dataset_never_reports_healthy(view: DataStatusView, changes: dict) -> None:
    root = view._producer_root()
    document = _producer(root)
    document["datasets"][0].update(changes)
    _write(root / "data-status.json", document)
    result = view.status()
    assert result["datasets"][0]["status"] == "missing"
    assert result["datasets"][1]["status"] == "ok"


@pytest.mark.parametrize(
    "key,period",
    [
        ("monthly_revenue", {"from": "2020-01-01", "to": "2026-09-01"}),
        ("official_daily", {"from": "2020-01", "to": "2026-09"}),
    ],
)
def test_producer_period_granularity_matches_dataset(view: DataStatusView, key: str, period: dict) -> None:
    root = view._producer_root()
    document = _producer(root)
    next(item for item in document["datasets"] if item["id"] == key)["data_period"] = period
    _write(root / "data-status.json", document)
    rows = {item["id"]: item for item in view.status()["datasets"]}
    assert rows[key]["status"] == "missing"


def test_producer_metadata_uses_fourteen_day_freshness(view: DataStatusView) -> None:
    root = view._producer_root()
    document = _producer(root)
    for item in document["datasets"]:
        item["last_updated"] = "2026-10-13T00:00:00+00:00"
    _write(root / "data-status.json", document)
    rows = {item["id"]: item for item in view.status()["datasets"]}
    assert rows["symbol_meta"]["status"] == "ok"
    assert rows["monthly_revenue"]["status"] == "ok"
    assert rows["official_daily"]["status"] == "stale"


def test_old_producer_status_cannot_remain_healthy(view: DataStatusView) -> None:
    root = view._producer_root()
    document = _producer(root)
    document["generated_at"] = "2020-01-01T00:00:00+00:00"
    _write(root / "data-status.json", document)
    assert all(row["status"] == "stale" for row in view.status()["datasets"][:6])


def test_busy_declines_before_resolving_producer_root(view: DataStatusView) -> None:
    def busy() -> None:
        raise live_producer.ProducerBusyError("test writer")

    def forbidden() -> Path:
        pytest.fail("busy producer root resolved")

    view._idle = busy
    view._producer_root = forbidden
    result = view.status()
    assert result["status"] == "updating"
    assert all(row["status"] == "updating" for row in result["datasets"][:6])
    assert result["datasets"][6]["status"] == "ok"


def test_writer_starting_during_read_discards_producer_metadata(view: DataStatusView) -> None:
    calls = 0

    def race() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise live_producer.ProducerBusyError("started during read")

    view._idle = race
    result = view.status()
    assert result["status"] == "updating"
    assert all(row["rows"] is None for row in result["datasets"][:6])


@pytest.mark.parametrize("generation", ["../escape", "nested/escape", "C:/escape", "..\\escape"])
def test_derived_pointer_cannot_escape_family(view: DataStatusView, generation: str) -> None:
    path = view._shared_root() / "derived/prices-v1/current.json"
    _write(path, {"generation": generation, "status_sha256": "a" * 64})
    result = view.status()
    assert result["datasets"][6]["status"] == "missing"
    assert "escape" not in " ".join(result["warnings"])


@pytest.mark.parametrize("changes", [{"calendar": []}, {"bases": []}, {"codes": -1}, {"calendar": {"first": "2026-12-01", "last": "2026-01-01"}}])
def test_malformed_derived_metadata_is_missing(view: DataStatusView, changes: dict) -> None:
    _derived(view._shared_root(), **changes)
    assert view.status()["datasets"][6]["status"] == "missing"


@pytest.mark.parametrize(
    "changes",
    [
        {"calendar": {}},
        {"built_at_utc": None},
        {"calendar": {"first": "2020-01-01", "last": "2020-12-31"}, "asof": "2020-12-31"},
    ],
)
def test_derived_missing_or_old_coverage_cannot_be_healthy(view: DataStatusView, changes: dict) -> None:
    _derived(view._shared_root(), **changes)
    assert view.status()["datasets"][6]["status"] == "stale"


def test_derived_unknown_counts_preserve_fresh_coverage(view: DataStatusView) -> None:
    _derived(view._shared_root(), codes=None, bases={})
    row = view.status()["datasets"][6]
    assert row["status"] == "ok"
    assert row["symbols"] is None and row["rows"] is None


def test_derived_monthly_coverage_has_forty_five_day_grace(view: DataStatusView) -> None:
    _derived(view._shared_root(), calendar={"first": "2020-01", "last": "2026-09"})
    assert view.status()["datasets"][6]["status"] == "ok"


def test_derived_pin_mismatch_is_missing(view: DataStatusView) -> None:
    path = view._shared_root() / "derived/prices-v1/generations/one/status.json"
    path.write_text("{}", encoding="utf-8")
    assert view.status()["datasets"][6]["status"] == "missing"


@pytest.mark.parametrize("state", ["partial", "legacy"])
def test_partial_and_legacy_catalog_do_not_claim_healthy(view: DataStatusView, state: str) -> None:
    view._catalog = lambda: _catalog(state)
    result = view.status()
    assert result["datasets"][7]["status"] == "stale"
    assert result["warnings"]


def test_public_mode_never_constructs_private_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "public-synthetic")

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("public attempted private discovery")

    monkeypatch.setattr(data_status.DataStatusView, "status", forbidden)
    monkeypatch.setattr(data_status, "producer_data_root", forbidden)
    monkeypatch.setattr(data_status, "shared_data_root", forbidden)
    monkeypatch.setattr(data_status, "catalog_summary", forbidden)
    app = FastAPI()
    app.include_router(create_data_status_router())
    response = TestClient(app).get("/data-status")
    assert response.status_code == 200
    assert "虛構" in response.json()["datasets"][0]["name"]


def test_unknown_mode_fails_closed(view: DataStatusView, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "unexpected")
    assert _client(view).get("/data-status").status_code == 503


def test_private_route_returns_contract(view: DataStatusView, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")
    response = _client(view).get("/data-status")
    assert response.status_code == 200
    assert response.json()["schema"] == "research-data-status.v1"
