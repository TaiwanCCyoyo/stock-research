from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from research_core.opportunity_history_classifications import build_classifications
from research_core.opportunity_history_inputs import canonical_bytes, snapshot_inputs


def pinned_fixture(tmp_path: Path, *, packet: bool = False, source_id: str = "primary:2330:annual") -> tuple[Path, dict[str, Any], dict[str, Any]]:
    source = tmp_path / "來源 with spaces"
    source.mkdir()
    with sqlite3.connect(source / "symbol_meta.sqlite") as db:
        db.execute("CREATE TABLE symbol_meta (code TEXT, name TEXT, industry_category TEXT, security_category TEXT, fetched_at TEXT, listed_date TEXT)")
        db.execute("INSERT INTO symbol_meta VALUES ('2603','Evergreen','航運業','股票','2026-10-03','1990-01-01')")
        db.execute("INSERT INTO symbol_meta VALUES ('2330','TSMC','半導體業','股票','2026-10-03','1994-01-01')")
    taxonomy = {
        "schema_version": 1,
        "snapshot_id": "fixed-taxonomy",
        "fetched_at": "2026-10-01",
        "symbols": {
            code: {
                "listing_segments": ["本國上市公司"],
                "memberships": [{"chain_code": "T000", "node_code": "T100", "stage": "中游"}, {"chain_code": "T000", "node_code": "T200", "stage": "下游"}],
            }
            for code in ("2603", "2330", "9999", "0050")
        },
        "chains": [
            {
                "code": "T000",
                "name": "Transport",
                "source_url": "https://example.test/transport",
                "nodes": [
                    {"code": "T100", "name": "Container", "parent_code": None, "members": [{"code": code} for code in ("2603", "2330", "9999", "0050")]},
                    {"code": "T200", "name": "Other", "parent_code": "T100", "members": [{"code": "2603"}]},
                ],
            }
        ],
    }
    config = {
        "schema_version": "sector-groups.v1",
        "groups": [
            {
                "group_id": "transport",
                "label": "Transport",
                "selectors": [{"chain_code": "T000", "node_code": "T100"}],
                "exclude_selectors": [{"chain_code": "T000", "node_code": "T200"}],
            }
        ],
    }
    (source / "value_chain_classification.json").write_bytes(canonical_bytes(taxonomy))
    (source / "sector_groups.v1.json").write_bytes(canonical_bytes(config))
    assertion = {
        "assertion_id": "2330:annual-role",
        "label": "Foundry",
        "document_covered_period": {"from": "2021-01-01", "until_exclusive": "2022-01-01", "precision": "fiscal-year"},
        "temporal_scope": "retrospective-period-summary",
        "effective_interval": None,
        "published_at": None,
        "first_available_at": None,
        "source_refs": [{"source_id": source_id, "locator": "physical page 91"}],
    }
    if packet:
        packet_data = {
            "securities": [
                {
                    "security_id": "TW:2330",
                    "symbol": "2330",
                    "name": "TSMC",
                    "official_industry_snapshot": {"label": "Old observed label", "source_refs": [{"source_id": "catalog:old", "locator": "row2330"}]},
                    "official_value_chain_snapshot": {"memberships": []},
                    "research_group_snapshot": {"groups": []},
                    "company_business_assertions": [assertion],
                }
            ]
        }
        (source / "classification-v1.json").write_bytes(canonical_bytes(packet_data))
        (source / "sources-v1.json").write_bytes(
            canonical_bytes({
                "sources": [
                    {"source_id": "primary:2330:annual", "url": "https://example.test/annual.pdf", "content_digest": {"value": "recorded-hash"}},
                    {"source_id": "catalog:old", "local_path": "D:\\previous catalog\\chunk.json.gz"},
                ],
                "retrieval_gaps": [{"url": "https://example.test/missing.pdf", "result": "404"}],
            })
        )
        (source / "gaps-v1.json").write_bytes(canonical_bytes({"securities": [{"security_id": "TW:2330", "company_source_first_available_missing": True}]}))
    snapshot = tmp_path / "snapshot"
    snapshot_inputs({path.name: path for path in source.iterdir()}, snapshot)
    manifest = {
        "count": 4,
        "rows": [
            {"security_id": f"TW:{code}", "code": code, "instrument_role": role}
            for code, role in [("2603", "stock"), ("2330", "stock"), ("9999", "unresolved_identity"), ("0050", "benchmark")]
        ],
    }
    return snapshot, manifest, assertion


def test_known_industry_unknown_code_and_full_multimembership(tmp_path: Path) -> None:
    snapshot, manifest, _ = pinned_fixture(tmp_path)
    original = copy.deepcopy(manifest)
    payload = build_classifications(snapshot, manifest)
    rows = {row["code"]: row for row in payload["classifications"]["rows"]}
    industry = rows["2603"]["official_industry_snapshot"]
    assert industry["label"] == "航運業"
    assert industry["code"] is None
    assert industry["listed_date"] == "1990-01-01"
    assert industry["historical_effective_from"] is None
    assert industry["first_available_at"] is None
    memberships = rows["2603"]["official_value_chain_snapshot"]["memberships"]
    assert [(m["chain_code"], m["node_code"]) for m in memberships] == [("T000", "T100"), ("T000", "T200")]
    assert memberships[1]["ancestor_node_codes"] == ["T100"]
    assert rows["2603"]["coverage_status"] == "official_only"
    assert rows["2603"]["business_status"] == "business_pending"
    assert rows["2330"]["coverage_status"] == "research_classification"
    assert manifest == original
    json.dumps(payload, allow_nan=False)


def test_unknown_and_benchmark_retain_chain_clues_without_stock_groups(tmp_path: Path) -> None:
    snapshot, manifest, _ = pinned_fixture(tmp_path)
    payload = build_classifications(snapshot, manifest)
    rows = {row["code"]: row for row in payload["classifications"]["rows"]}
    for code in ("9999", "0050"):
        assert rows[code]["official_value_chain_snapshot"]["memberships"]
        assert rows[code]["research_group_snapshot"]["group_ids"] == []
        assert not rows[code]["research_group_snapshot"]["automatic_membership_eligible"]
    assert rows["9999"]["instrument_role"] == "unresolved_identity"
    assert all("TW:9999" not in group["member_security_ids"] and "TW:0050" not in group["member_security_ids"] for group in payload["groups"]["rows"])


def test_exact_business_assertion_and_inherited_sources_not_history_backfill(tmp_path: Path) -> None:
    snapshot, manifest, assertion = pinned_fixture(tmp_path, packet=True)
    payload = build_classifications(snapshot, manifest)
    row = next(row for row in payload["classifications"]["rows"] if row["code"] == "2330")
    assert row["company_business_assertions"] == [assertion]
    assert row["official_industry_snapshot"]["label"] == "半導體業"
    assert row["business_status"] == "explicit_evidence"
    assert row["business_evidence_provenance"]["history_backfill"] is False
    assert row["company_business_assertions"][0]["effective_interval"] is None
    assert row["company_business_assertions"][0]["first_available_at"] is None
    sources = {source["source_id"]: source for source in payload["sources"]["rows"]}
    assert sources["primary:2330:annual"]["url"] == "https://example.test/annual.pdf"
    assert sources["primary:2330:annual"]["inherited_provenance"]["historical_validity"] == "not_established"
    assert any(gap["gap_id"] == "business-evidence-queue" for gap in payload["gaps"]["rows"])
    assert any(gap.get("result") == "404" for gap in payload["gaps"]["rows"])


def test_reject_unregistered_inherited_reference(tmp_path: Path) -> None:
    snapshot, manifest, _ = pinned_fixture(tmp_path, packet=True, source_id="missing-source")
    with pytest.raises(ValueError, match="Unregistered source reference"):
        build_classifications(snapshot, manifest)


def test_reject_changed_snapshot_and_manifest_count(tmp_path: Path) -> None:
    snapshot, manifest, _ = pinned_fixture(tmp_path)
    with pytest.raises(ValueError, match="count mismatch"):
        build_classifications(snapshot, manifest | {"count": 5})
    (snapshot / "sector_groups.v1.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Snapshot hash mismatch"):
        build_classifications(snapshot, manifest)
