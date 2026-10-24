from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from research_api.data_coverage import create_data_coverage_router
from research_core.security_coverage import project_security_coverage, security_key
from research_core.security_coverage_store import CoverageStore, publish_coverage


def source(code: str = "2330", first: str = "2019-01-02", last: str = "2026-10-23", market: str = "TWSE", **extra: Any):
    return {
        "status": "ok",
        "first": first,
        "checked_at": "2026-10-24T00:00:00+00:00",
        "members": [{"market": market, "code": code, "first": first, "last": last, "rows": 42, **extra}],
    }


def build(sources: dict[str, Any] | None = None, metadata: list[dict[str, Any]] | None = None):
    return project_security_coverage(sources or {}, metadata or [], built_at="2026-10-24T00:00:00+00:00", as_of="2026-10-24")


def meta(code: str = "2330", listed: str = "1994-01-01", **extra: Any):
    return {"market": "TWSE", "code": code, "name": "測試公司", "listed_date": listed, "security_category": "股票", **extra}


def cell(document: dict[str, Any], dataset: str):
    return next(c for c in document["securities"][0]["coverage"] if c["dataset"] == dataset)


def test_global_gap_not_assigned_to_new_listing():
    old = build({"institutional": source()}, [meta()])
    assert cell(old, "institutional")["mark"] == "partial"
    new = build({"institutional": source(first="2023-01-02")}, [meta(listed="2023-01-02")])
    assert cell(new, "institutional")["mark"] == "present"
    assert cell(new, "institutional")["completeness"] == "unknown"


def test_backfilled_2019_boundary_is_not_hardcoded():
    doc = build({"institutional": source(first="2012-05-02")}, [meta()])
    assert "stored_history_before_2019_missing" not in cell(doc, "institutional")["reasons"]


def test_unreadable_is_unknown_and_no_records_is_not_red():
    broken = build({"institutional": {"status": "unavailable"}}, [meta()])
    assert cell(broken, "institutional")["rows"] is None
    empty = build({"corporate_actions": {"status": "ok", "members": []}}, [meta()])
    assert cell(empty, "corporate_actions")["rows"] == 0
    assert cell(empty, "corporate_actions")["mark"] == "unknown"


def test_union_includes_security_without_price():
    doc = build({"monthly_revenue": source(code="X123", first="2025-01")})
    assert doc["securities"][0]["code"] == "X123"
    assert doc["securities"][0]["can_view_prices"] is False
    assert cell(doc, "monthly_revenue")["mark"] == "present"


def test_synthetic_revenue_only_viewer_has_observations_without_real_code_attribution():
    from research_core.data_series import synthetic_series

    revenue = synthetic_series("monthly-revenue", "REVENUE", None, None, "TPEx")
    assert revenue["status"] == "ok" and revenue["rows"][0]["code"] == "REVENUE"
    assert synthetic_series("institutional", "REVENUE", None, None, "TPEx")["rows"] == []
    assert synthetic_series("monthly-revenue", "2330", None, None, "TWSE")["rows"] == []


def test_code_reuse_has_distinct_opaque_segments_and_no_name_leak():
    doc = build({"institutional": source(code="X123")}, [meta(code="X123", listed="2023-01-02")])
    rows = doc["securities"]
    assert len(rows) == 2
    assert len({row["key"] for row in rows}) == 2
    assert rows[0]["name"] is None
    assert rows[0]["segment"]["to"] == "2023-01-01"
    assert all(row["identity_status"] == "unresolved" and not row["can_view_prices"] for row in rows)
    assert all(c["rows"] is None for row in rows for c in row["coverage"])


def test_long_gap_is_unresolved_and_not_delisting_proof():
    doc = build({"official_daily": source(gaps=[["2020-01-02", "2023-01-02"]])}, [meta()])
    assert len(doc["securities"]) == 2
    assert all(row["listing_status"] == "unknown" for row in doc["securities"])
    assert all(row["period"] == {"from": None, "to": None} for row in doc["securities"])


def test_cells_separate_observation_from_assessment_and_input():
    observed = source(first="2023-01-02")
    observed["input_fingerprint"] = [{"file": "institutional.sqlite", "size": 12, "mtime_ns": 1}]
    value = cell(build({"institutional": observed}, [meta(listed="2023-01-02")]), "institutional")
    assert value["assessment_period"] == {"from": "2023-01-02", "to": "2026-10-24"}
    assert value["period"] == {"from": "2023-01-02", "to": "2026-10-23"}
    assert value["input_identity"] == observed["input_fingerprint"]
    assert value["assessment_scope"] == "presence_and_known_gaps"


def test_market_separation_and_explicit_delisting():
    doc = build({"institutional": source()}, [meta(listing_status="delisted", listing_evidence="official-record")])
    assert doc["securities"][0]["listing_status"] == "delisted"
    assert security_key("TWSE", "2330") != security_key("TPEx", "2330")


def test_atomic_generations_and_cache_switch(tmp_path: Path):
    doc = build({"institutional": source()}, [meta()])
    first = publish_coverage(doc, root=tmp_path)
    store = CoverageStore(tmp_path)
    assert store.list()["total"] == 1
    assert store.list()["confirmed_missing"] == 0
    assert store.resolve("2330")["candidates"][0]["key"]
    second = publish_coverage(build({}, [meta(code="X123")]), root=tmp_path)
    assert store.resolve("2330")["candidates"] == []
    assert first["generation"] != second["generation"]
    assert (tmp_path / "derived/security-coverage-v1/generations" / first["generation"]).exists()


def test_corrupt_or_traversing_pointer_is_unavailable(tmp_path: Path):
    publish_coverage(build({}, [meta()]), root=tmp_path)
    pointer = tmp_path / "derived/security-coverage-v1/current.json"
    content = json.loads(pointer.read_text())
    content["generation"] = "../../outside"
    pointer.write_text(json.dumps(content))
    assert CoverageStore(tmp_path).list()["status"] == "unavailable"


def test_unavailable_never_opens_producer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("research_core.producer_data.producer_data_root", lambda: pytest.fail("producer opened"))
    assert CoverageStore(tmp_path).list()["status"] == "unavailable"


def test_filter_and_unknown_denominators_cover_all_pages(tmp_path: Path):
    doc = build({"institutional": source()}, [meta(), meta(code="X123"), meta(code="ETF", is_etf=1)])
    publish_coverage(doc, root=tmp_path)
    store = CoverageStore(tmp_path)
    assert store.list(kind="stock", size=1)["total"] == 2
    assert store.list(kind="stock", size=1)["unknown"] == 2
    assert store.list(q="X123")["total"] == 1
    with pytest.raises(ValueError):
        store.list(mark="unknown")


def endpoints(store: CoverageStore):
    router = create_data_coverage_router(store)
    return {route.path: route.endpoint for route in router.routes if isinstance(route, APIRoute)}


def test_api_demo_never_loads_private_store(monkeypatch: pytest.MonkeyPatch):
    class Forbidden(CoverageStore):
        def load(self):
            pytest.fail("private root touched")

    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "public-synthetic")
    fn = endpoints(Forbidden())["/data-coverage/securities"]
    result = fn(q="DEMO", page=1, size=50)
    assert result["synthetic"] is True
    assert result["rows"][0]["code"] == "DEMO"


def test_api_missing_summary_and_bad_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")
    api = endpoints(CoverageStore(tmp_path))
    assert api["/data-coverage/securities"](page=1, size=50)["status"] == "unavailable"
    with pytest.raises(HTTPException) as invalid:
        api["/data-coverage/resolve"](code="../x")
    assert invalid.value.status_code == 422
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "typo")
    with pytest.raises(HTTPException) as mode:
        api["/data-coverage/securities"](page=1, size=50)
    assert mode.value.status_code == 503


def test_source_scanner_streams_fixtures_and_finds_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from research_core.security_coverage_sources import collect_sources

    monkeypatch.setattr("research_core.security_coverage_sources.collect_adjusted_summary", lambda *args, **kwargs: None)
    monkeypatch.setattr("research_core.live_producer.assert_producer_idle", lambda **kwargs: None)
    db = tmp_path / "official_daily.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE official_daily_price(market TEXT, code TEXT, date TEXT)")
        conn.executemany("INSERT INTO official_daily_price VALUES ('TWSE','X123',?)", [("2010-01-04",), ("2023-01-02",)])
    sources, metadata = collect_sources(tmp_path, seconds_per_source=10)
    assert not metadata
    assert sources["official_daily"]["members"][0]["gaps"] == [["2010-01-04", "2023-01-02"]]
    assert sources["institutional"]["status"] == "unavailable"
    assert "members" not in sources["institutional"]


def test_partial_backfill_is_market_specific():
    sources = {"institutional": source(market="TPEx")}
    sources["institutional"]["first"] = "2012-05-02"
    sources["institutional"]["first_by_market"] = {"TWSE": "2012-05-02", "TPEx": "2019-01-02"}
    doc = build(sources, [meta(market="TPEx")])
    assert cell(doc, "institutional")["mark"] == "partial"


def test_coverage_family_is_visible_in_metadata_overview(tmp_path: Path):
    from research_core.data_status import DataStatusView

    publish_coverage(build({}, [meta()]), root=tmp_path)
    view = DataStatusView(
        producer_root=lambda: tmp_path / "producer", shared_root=lambda: tmp_path, catalog=lambda: ({"entries": []}, None), labels=lambda: {}, idle=lambda: None
    )
    entry = next(row for row in view.status()["datasets"] if row["id"] == "derived:security-coverage-v1")
    assert entry["symbols"] == 1
    assert entry["rows"] == 7


def test_no_usable_source_retains_previous_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import research_core.security_coverage_maintenance as maintenance

    monkeypatch.setattr(maintenance, "family_path", lambda: tmp_path)
    monkeypatch.setattr(maintenance, "producer_data_root", lambda: tmp_path)
    monkeypatch.setattr(maintenance, "collect_sources", lambda *args, **kwargs: ({"institutional": {"status": "unavailable"}}, []))
    monkeypatch.setattr(maintenance, "publish_coverage", lambda *args, **kwargs: pytest.fail("published empty replacement"))
    with pytest.raises(RuntimeError, match="No usable coverage source"):
        maintenance.update_coverage()


def test_catalog_time_labels_distinguish_version_and_manifest(tmp_path: Path):
    from research_core.data_status import DataStatusView

    metadata = {"version_created_at": "2026-01-02T00:00:00+00:00", "manifest_modified_at": "2026-10-24T00:00:00+00:00"}
    entry = {
        "data_id": "fixture",
        "version_id": "one",
        "status": "complete",
        "coverage": {"raw_input_period": {"start": "2020-01-01", "end": "2023-01-01"}},
        "viewer_metadata": metadata,
    }
    view = DataStatusView(
        producer_root=lambda: tmp_path, shared_root=lambda: tmp_path, catalog=lambda: ({"entries": [entry]}, None), labels=lambda: {}, idle=lambda: None
    )
    row = next(row for row in view.status()["datasets"] if row["source"] == "catalog")
    assert row["update_kind"] == "version_created_at"
    assert row["last_updated"].startswith("2026-01-02")
    metadata["version_created_at"] = "bad-time"
    row = next(row for row in view.status()["datasets"] if row["source"] == "catalog")
    assert row["update_kind"] == "manifest_modified_at"
