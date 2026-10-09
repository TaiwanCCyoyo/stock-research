from __future__ import annotations

import copy

import pytest

from research_core.sector_groups import SectorGroupError, build_groups


def snapshot() -> dict:
    return {
        "schema_version": 1,
        "snapshot_id": "synthetic-v1",
        "symbols": {},
        "chains": [
            {
                "code": "memory",
                "name": "Memory",
                "source_url": "https://example/memory",
                "nodes": [
                    {"code": "root", "name": "Root", "parent_code": None, "members": []},
                    {"code": "dram", "name": "DRAM", "parent_code": "root", "members": [{"code": "A", "name": "A"}, {"code": "B", "name": "B"}]},
                    {"code": "nand", "name": "NAND", "parent_code": "root", "members": [{"code": "B", "name": "B"}]},
                ],
            },
            {
                "code": "cooling",
                "name": "Cooling",
                "source_url": "https://example/cooling",
                "nodes": [
                    {"code": "dram", "name": "Same code", "parent_code": None, "members": [{"code": "C", "name": "C"}]},
                ],
            },
        ],
    }


def config() -> dict:
    return {
        "schema_version": "sector-groups.v1",
        "groups": [
            {
                "group_id": "memory-core",
                "label": "Memory core",
                "selectors": [{"chain_code": "memory", "node_code": "root"}],
                "exclude_selectors": [{"chain_code": "memory", "node_code": "nand"}],
            },
            {"group_id": "cooling-dram", "label": "Cooling dram", "selectors": [{"chain_code": "cooling", "node_code": "dram"}]},
        ],
    }


def securities() -> list[dict]:
    return [
        {"security_id": "TW:A", "code": "A", "name": "A", "market": "TWSE", "official_industry": "x"},
        {"security_id": "TW:B", "code": "B", "name": "B", "market": "TWSE", "official_industry": "x"},
        {"security_id": "TW:C", "code": "C", "name": "C", "market": "TPEX", "official_industry": "y"},
        {"security_id": "TW:D", "code": "D", "name": "D", "market": "TWSE", "official_industry": "z"},
    ]


def test_build_expands_empty_parent_deduplicates_memberships_and_excludes() -> None:
    groups, rows, nodes = build_groups(snapshot(), config(), securities())
    by_id = {item["group_id"]: item for item in groups}
    assert by_id["memory-core"]["member_security_ids"] == ["TW:A"]
    assert by_id["official:memory"]["member_security_ids"] == ["TW:A", "TW:B"]
    assert by_id["official:cooling"]["member_security_ids"] == ["TW:C"]
    root = next(node for node in nodes if node["node_id"] == "official:memory:root")
    assert root["direct_member_security_ids"] == []
    assert root["expanded_member_security_ids"] == ["TW:A", "TW:B"]
    b = next(row for row in rows if row["code"] == "B")
    assert b["group_ids"] == ["official:memory"]
    assert b["coverage_status"] == "official_only"


def test_cross_chain_node_codes_and_missing_source_coverage() -> None:
    _, rows, nodes = build_groups(snapshot(), config(), securities())
    assert {node["node_id"] for node in nodes if node["node_code"] == "dram"} == {"official:memory:dram", "official:cooling:dram"}
    d = next(row for row in rows if row["code"] == "D")
    assert d["official_memberships"] == []
    assert d["coverage_status"] == "source_missing"
    assert d["coverage_reason"] == "security_code_not_in_source_members"


def test_whole_chain_selector_and_same_parent_ancestors() -> None:
    raw_config = config()
    raw_config["groups"][0]["selectors"][0]["node_code"] = None
    raw_config["groups"][0]["exclude_selectors"] = []
    groups, rows, _ = build_groups(snapshot(), raw_config, securities())
    assert next(g for g in groups if g["group_id"] == "memory-core")["member_security_ids"] == ["TW:A", "TW:B"]
    assert next(r for r in rows if r["code"] == "A")["official_memberships"][0]["ancestor_node_codes"] == ["root"]


@pytest.mark.parametrize("mutation", ["unknown_selector", "node_cycle", "group_parent_cycle"])
def test_rejects_malformed_selector_and_cycles(mutation: str) -> None:
    raw_snapshot, raw_config = snapshot(), config()
    if mutation == "unknown_selector":
        raw_config["groups"][0]["selectors"] = [{"chain_code": "memory", "node_code": "missing"}]
    elif mutation == "node_cycle":
        raw_snapshot["chains"][0]["nodes"][0]["parent_code"] = "dram"
    else:
        raw_config["groups"][0]["parent_id"] = "cooling-dram"
        raw_config["groups"][1]["parent_id"] = "memory-core"
    with pytest.raises(SectorGroupError):
        build_groups(copy.deepcopy(raw_snapshot), copy.deepcopy(raw_config), securities())
