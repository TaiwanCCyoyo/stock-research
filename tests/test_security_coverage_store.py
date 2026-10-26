from __future__ import annotations

import json
from pathlib import Path

from research_core.security_coverage import project_security_coverage
from research_core.security_coverage_store import CoverageStore, publish_coverage


def _row(code: str, *, market: str = "TWSE", etf: bool = False, listed: str | None = None):
    metadata = {"market": market, "code": code, "name": f"公司 {code}", "security_category": "股票", "is_etf": int(etf)}
    if listed:
        metadata["listing_status"] = listed
        metadata["listing_evidence"] = "fixture"
    return metadata


def _document():
    metadata = [_row("A001"), _row("B002", market="TPEx", listed="delisted"), _row("C003", etf=True)]
    return project_security_coverage({}, metadata, built_at="2026-10-24T00:00:00+00:00", as_of="2026-10-24")


def test_native_publication_is_compact_and_supports_queries(tmp_path: Path):
    document = _document()
    pointer = publish_coverage(document, root=tmp_path)
    generation = tmp_path / "derived/security-coverage-v1/generations" / pointer["generation"]
    metadata = json.loads((generation / "coverage.json").read_text(encoding="utf-8"))
    assert "securities" not in metadata
    assert (generation / "coverage.sqlite").stat().st_size < 2_000_000
    assert len((generation / "coverage.json").read_bytes()) < 20_000

    store = CoverageStore(tmp_path)
    result = store.list(kind="stock", size=1)
    assert result["total"] == 2
    assert result["unknown"] == 2
    assert store.list(q="A001")["rows"][0]["code"] == "A001"
    assert store.list(market="TPEx")["rows"][0]["code"] == "B002"
    assert store.list(status="delisted")["total"] == 1
    key = result["rows"][0]["key"]
    detail = store.detail(key)
    assert detail is not None
    assert detail["security"]["code"] == result["rows"][0]["code"]
    assert [row["code"] for row in store.resolve("B002")["candidates"]] == ["B002"]


def test_filter_counts_are_computed_before_pagination(tmp_path: Path):
    document = _document()
    publish_coverage(document, root=tmp_path)
    result = CoverageStore(tmp_path).list(kind="stock", size=1, page=2)
    assert len(result["rows"]) == 1
    assert result["total"] == 2
    assert result["unknown"] == 2
    assert result["hidden"]["delisted"] == 1


def test_load_override_keeps_synthetic_document_fallback():
    document = _document()

    class SyntheticStore(CoverageStore):
        def load(self):
            return document

    assert SyntheticStore().list(size=1)["total"] == 3
    detail = SyntheticStore().detail(document["securities"][0]["key"])
    assert detail is not None
    assert detail["security"]["code"] == document["securities"][0]["code"]
    assert SyntheticStore().resolve("A001")["candidates"][0]["code"] == "A001"


def test_database_tampering_fails_closed(tmp_path: Path):
    pointer = publish_coverage(_document(), root=tmp_path)
    database = tmp_path / "derived/security-coverage-v1/generations" / pointer["generation"] / "coverage.sqlite"
    database.write_bytes(database.read_bytes() + b"tamper")
    result = CoverageStore(tmp_path).list()
    assert result["status"] == "unavailable"
    assert result["rows"] == []


def test_native_unavailable_list_preserves_filter_metadata_shape(tmp_path: Path):
    result = CoverageStore(tmp_path).list()
    assert result["status"] == "unavailable"
    assert set(result) == {
        "schema",
        "status",
        "reason",
        "generation",
        "built_at",
        "as_of",
        "datasets",
        "sources",
        "rows",
        "total",
        "page",
        "size",
        "hidden",
        "confirmed_missing",
        "unknown",
    }
    assert result["datasets"] == []
    assert result["sources"] == {}
    assert result["built_at"] is None
    assert result["as_of"] is None


def test_warm_cache_detects_database_mutation(tmp_path: Path):
    pointer = publish_coverage(_document(), root=tmp_path)
    database = tmp_path / "derived/security-coverage-v1/generations" / pointer["generation"] / "coverage.sqlite"
    store = CoverageStore(tmp_path)
    assert store.list()["status"] == "partial"

    database.write_bytes(database.read_bytes() + b"tamper")
    result = store.list()
    assert result["status"] == "unavailable"
    assert result["rows"] == []
