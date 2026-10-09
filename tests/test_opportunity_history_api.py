"""HTTP snapshot and bounded-file regressions without requiring private data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api.history import history_router
from research_core.opportunity_history_store import HistoryStore, LazyHistoryStore
from scripts.query_opportunity_history import calendar_content_id, validate_calendar_identity


class Saved:
    series: dict[str, dict] = {"2609": {}}
    dates = ["2010-01-04", "2021-07-23"]

    def metadata(self):
        return {"catalogId": "fixed", "dates": self.dates}

    def frame(self, date: str):
        if date not in self.dates:
            raise ValueError("outside")
        return {"catalogId": "fixed", "date": date, "rows": []}

    def detail(self, code: str, date: str):
        return {"catalogId": "fixed", "date": date, "code": code}

    def directory(self):
        return {"schema": "opportunity-history-web.v1", "catalogId": "fixed", "method": "segments", "methodScale": "balanced", "rows": []}

    def options(self, date: str):
        if date not in self.dates:
            raise ValueError("outside")
        return {"schema": "opportunity-history-web.v1", "catalogId": "fixed", "date": date, "rows": []}


@pytest.mark.parametrize("day", ["20200104", "2019-W01-4", "2020-02-30", "2020-1-04"])
def test_calendar_rejects_noncanonical_or_impossible_dates_even_with_rebound_identity(day: str) -> None:
    calendar: dict[str, object] = {"dates": [day]}
    calendar["calendar_id"] = calendar_content_id(calendar)
    with pytest.raises(ValueError):
        validate_calendar_identity(calendar)


def test_calendar_accepts_real_leap_day_and_standard_dates() -> None:
    calendar: dict[str, object] = {"dates": ["2010-01-04", "2020-02-29", "2026-10-02"]}
    calendar["calendar_id"] = calendar_content_id(calendar)
    validate_calendar_identity(calendar)


def test_http_preserves_snapshot_date_and_rejects_unknown_dates_codes():
    provider = LazyHistoryStore()
    provider.store = Saved()  # type: ignore[assignment]
    app = FastAPI()
    app.include_router(history_router(provider), prefix="/history-api")
    client = TestClient(app)
    base = "/history-api/opportunity-history/v1"
    assert client.get(base + "/status").json()["state"] == "ready"
    assert client.get(base + "/metadata").json()["dates"][0] == "2010-01-04"
    assert client.get(base + "/frame", params={"date": "2021-07-23"}).json()["date"] == "2021-07-23"
    assert client.get(base + "/frame", params={"date": "2009-01-01"}).status_code == 422
    assert client.get(base + "/frame", params={"date": "arbitrary/path"}).status_code == 422
    assert client.get(base + "/directory").json()["methodScale"] == "balanced"
    assert client.get(base + "/options", params={"date": "2021-07-23"}).json()["date"] == "2021-07-23"
    assert client.get(base + "/options", params={"date": "2009-01-01"}).status_code == 422
    assert client.get(base + "/security/unknown", params={"date": "2010-01-04"}).status_code == 404
    assert client.get(base + "/security/2609", params={"date": "2021-07-23"}).json()["catalogId"] == "fixed"


def test_failed_initialization_is_not_silently_retried_or_synthetic(tmp_path: Path):
    provider = LazyHistoryStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        provider.get()
    with pytest.raises(RuntimeError, match="unavailable"):
        provider.get()
    app = FastAPI()
    app.include_router(history_router(provider))
    assert TestClient(app).get("/opportunity-history/v1/metadata").status_code == 503
    assert TestClient(app).get("/opportunity-history/v1/status").json()["state"] == "failed"


def test_startup_progress_does_not_trigger_or_wait_for_load():
    provider = LazyHistoryStore()
    provider.lock.acquire()
    try:
        provider._progress("核對各股價格與候選標記", 12, 20)
        assert provider.status() == {
            "schema": "opportunity-history-web.v1",
            "state": "loading",
            "stage": "核對各股價格與候選標記",
            "completed": 12,
            "total": 20,
        }
        assert provider.store is None
    finally:
        provider.lock.release()


def test_reference_containment_hash_and_count(tmp_path: Path):
    store = object.__new__(HistoryStore)
    store.bundle = tmp_path.resolve()
    store.root = tmp_path / "catalog-v2"
    store.root.mkdir()
    payload = json.dumps({"rows": [1]}).encode()
    (store.root / "rows.json").write_bytes(payload)
    reference = {"path": "rows.json", "sha256": hashlib.sha256(payload).hexdigest(), "count": 1}
    assert store.read(reference) == {"rows": [1]}
    with pytest.raises(ValueError, match="escapes"):
        store.read(reference | {"path": "../../outside.json"})
    with pytest.raises(ValueError, match="hash mismatch"):
        store.read(reference | {"sha256": "0" * 64})
    with pytest.raises(ValueError, match="count mismatch"):
        store.read(reference | {"count": True})


def test_wrong_manifest_hash_fails_before_dependency_loading(tmp_path: Path):
    (tmp_path / "catalog-v2").mkdir()
    (tmp_path / "catalog-v2/manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest hash mismatch"):
        HistoryStore(tmp_path)


def test_membership_endpoint_preserves_unknowns_fractional_units_and_filter_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    import research_core.strategy_map_capture as module

    class MembershipSaved(Saved):
        identity = "fixed"
        securities = {"2609": {"name": "陽明"}}
        catalog = {"securities": securities}

    provider = LazyHistoryStore()
    monkeypatch.setattr(provider, "store", MembershipSaved())
    monkeypatch.setattr(
        module,
        "build_frame",
        lambda *args: {
            "rows": [
                {
                    "name": "陽明",
                    "waveId": "wave",
                    "start": "2021-02-01",
                    "growth": {"basis": "actual", "sizingGainPct": 80},
                    "launchCandidate": {"date": "2021-02-01"},
                    "endConfirmedAt": None,
                }
            ]
        },
    )
    app = FastAPI()
    app.include_router(history_router(provider))
    client = TestClient(app)
    url = "/opportunity-history/v1/membership"
    params = {"code": "TW:2609", "date": "2021-07-23"}
    assert client.get(url, params=params).json()["onMap"] is False
    result = client.get(url, params=params | {"threshold": 60}).json()
    assert result["onMap"] is True
    assert result["metric"] == 0.8
    assert result["metricUnit"] == "fraction"
    assert client.get(url, params=params | {"code": "9999"}).json()["onMap"] is None
    assert client.get(url, params=params | {"date": "2009-01-01"}).json()["onMap"] is None
    assert client.get(url, params=params | {"threshold": "nan"}).status_code == 422


def test_loading_response_is_explicit_retryable_and_does_not_block():
    from research_core.opportunity_history_store import HistoryLoading

    class Background(LazyHistoryStore):
        def get_ready(self):
            raise HistoryLoading("loading")

    app = FastAPI()
    app.include_router(history_router(Background()))
    response = TestClient(app).get("/opportunity-history/v1/metadata")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json()["detail"]["state"] == "loading"
