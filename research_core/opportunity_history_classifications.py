"""Separate pinned classification observations from historical business claims."""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from research_core.opportunity_history_inputs import _physical, _read_table, canonical_bytes, file_hash
from research_core.sector_groups import build_groups

LOGGER = logging.getLogger(__name__)
REQUIRED = ("symbol_meta.sqlite", "value_chain_classification.json", "sector_groups.v1.json")
PACKET_FILES = ("classification-v1.json", "sources-v1.json", "gaps-v1.json")
BUSINESS_CODES = frozenset({"2002", "2330", "2498", "2609", "3017", "3481", "4743", "9919"})


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _table(schema: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": schema, "rows": rows}


def _validate_source_refs(value: Any, source_ids: set[str]) -> None:
    if isinstance(value, dict):
        if "source_ids" in value:
            for source_id in value["source_ids"]:
                if source_id not in source_ids:
                    raise ValueError(f"Unregistered source reference: {source_id}")
        for reference in value.get("source_refs", []):
            if reference["source_id"] not in source_ids:
                raise ValueError(f"Unregistered source reference: {reference['source_id']}")
        for child in value.values():
            _validate_source_refs(child, source_ids)
    elif isinstance(value, list):
        for child in value:
            _validate_source_refs(child, source_ids)


def build_classifications(snapshot_dir: Path, series_manifest: dict[str, Any]) -> dict[str, Any]:
    """Return finite tables without writing or extending snapshot time claims."""
    _physical(snapshot_dir)
    receipt = _read_json(snapshot_dir / "input-receipt.json")
    inputs = {item["name"]: item for item in receipt["files"]}
    for name in REQUIRED:
        if name not in inputs:
            raise ValueError(f"Required classification input not pinned: {name}")
    for name, item in inputs.items():
        path = snapshot_dir / name
        _physical(path)
        if file_hash(path) != item["snapshot_sha256"]:
            raise ValueError(f"Snapshot hash mismatch: {name}")
    present_packet = [name for name in PACKET_FILES if name in inputs]
    if present_packet and len(present_packet) != len(PACKET_FILES):
        raise ValueError("Evidence packet requires classification, sources and gaps together")
    for name in PACKET_FILES:
        if (snapshot_dir / name).exists() and name not in inputs:
            raise ValueError(f"Evidence packet file not pinned: {name}")
    securities = series_manifest["rows"]
    if len({row["code"] for row in securities}) != len(securities):
        raise ValueError("Duplicate security codes in series manifest")
    if series_manifest.get("count") != len(securities):
        raise ValueError("Series manifest count mismatch")
    sources: list[dict[str, Any]] = []
    for name, item in sorted(inputs.items()):
        sources.append({
            "source_id": f"snapshot:{name}",
            "kind": "pinned_local_snapshot",
            "snapshot_path": name,
            "sha256": item["snapshot_sha256"],
            "original_source_sha256": item["source_sha256"],
            "original_source_path": item["source_path"],
            "source_observed_at": item["source_observed_at"],
            "first_available_at": None,
            "historical_validity": "not_established",
        })
    taxonomy = _read_json(snapshot_dir / "value_chain_classification.json")
    config = _read_json(snapshot_dir / "sector_groups.v1.json")
    stocks = [row for row in securities if row["instrument_role"] == "stock"]
    groups, enriched, nodes = build_groups(taxonomy, config, stocks)
    enrichment = {row["code"]: row for row in enriched}
    node_by_key = {(row["chain_code"], row["node_code"]): row for row in nodes}
    group_refs = ["snapshot:value_chain_classification.json", "snapshot:sector_groups.v1.json"]
    for row in groups:
        row.update({
            "source_ids": group_refs.copy(),
            "classification_mode": "snapshot",
            "historical_effective_from": None,
            "historical_effective_to": None,
            "first_available_at": None,
            "historical_validity": "not_established",
        })
    for row in nodes:
        row["source_ids"] = ["snapshot:value_chain_classification.json"]
    metadata = {str(row["code"]): row for row in _read_table(snapshot_dir / "symbol_meta.sqlite", "symbol_meta")}
    classifications = []
    gaps = []
    for security in securities:
        code = security["code"]
        meta = metadata.get(code, {})
        symbol = taxonomy.get("symbols", {}).get(code, {})
        memberships = copy.deepcopy(symbol.get("memberships", []))
        for membership in memberships:
            node = node_by_key.get((membership["chain_code"], membership["node_code"]))
            membership["ancestor_node_codes"] = node["ancestor_node_codes"].copy() if node else []
            membership["source_ids"] = ["snapshot:value_chain_classification.json"]
        enriched_row = enrichment.get(code, {})
        group_ids = enriched_row.get("group_ids", [])
        has_research = any(not group_id.startswith("official:") for group_id in group_ids)
        industry = meta.get("industry_category")
        common = {
            "historical_effective_from": None,
            "historical_effective_to": None,
            "first_available_at": None,
            "availability_reason": "unknown_first_availability",
            "historical_validity": "not_established",
        }
        classifications.append({
            "security_id": security["security_id"],
            "code": code,
            "instrument_role": security["instrument_role"],
            "official_industry_snapshot": common
            | {
                "label": industry,
                "code": meta.get("industry_code"),
                "fetched_at": meta.get("fetched_at"),
                "listed_date": meta.get("listed_date"),
                "security_category": meta.get("security_category"),
                "source_ids": ["snapshot:symbol_meta.sqlite"],
                "query_locator": {"path": "symbol_meta.sqlite", "table": "symbol_meta", "key": {"code": code}},
            },
            "official_value_chain_snapshot": common
            | {
                "snapshot_id": taxonomy.get("snapshot_id"),
                "fetched_at": taxonomy.get("fetched_at"),
                "memberships": memberships,
                "listing_segments": copy.deepcopy(symbol.get("listing_segments", [])),
                "source_ids": ["snapshot:value_chain_classification.json"],
                "query_locator": {"path": "value_chain_classification.json", "pointer": f"/symbols/{code}"},
            },
            "research_group_snapshot": common
            | {"group_ids": group_ids, "source_ids": group_refs.copy(), "automatic_membership_eligible": security["instrument_role"] == "stock"},
            "company_business_assertions": [],
            "coverage_status": "research_classification" if has_research else "official_only" if industry or memberships else "source_missing",
            "business_status": "business_pending",
        })
        gaps.append({
            "gap_id": f"classification-time:{code}",
            "security_id": security["security_id"],
            "kind": "historical_classification_not_established",
            "reason": "Current snapshot and listing claims do not establish historical membership or first availability",
            "source_ids": ["snapshot:symbol_meta.sqlite", "snapshot:value_chain_classification.json"],
        })
    if present_packet:
        packet = _read_json(snapshot_dir / "classification-v1.json")
        packet_sources = _read_json(snapshot_dir / "sources-v1.json")
        packet_gaps = _read_json(snapshot_dir / "gaps-v1.json")
        existing_ids = {row["source_id"] for row in sources}
        for original in packet_sources["sources"]:
            source = copy.deepcopy(original)
            if source["source_id"] in existing_ids:
                raise ValueError(f"Duplicate source ID: {source['source_id']}")
            existing_ids.add(source["source_id"])
            source["inherited_provenance"] = {"source_ids": ["snapshot:sources-v1.json"], "historical_validity": "not_established"}
            sources.append(source)
        by_security = {row["security_id"]: row for row in classifications}
        seen = set()
        for evidence in packet["securities"]:
            code = evidence["symbol"]
            security_id = evidence["security_id"]
            if code not in BUSINESS_CODES or security_id != f"TW:{code}" or security_id in seen:
                raise ValueError(f"Unexpected or duplicate business evidence identity: {security_id}")
            seen.add(security_id)
            classification_row = by_security.get(security_id)
            if classification_row is None:
                raise ValueError(f"Evidence security absent from series manifest: {security_id}")
            classification_row["company_business_assertions"] = copy.deepcopy(evidence["company_business_assertions"])
            classification_row["business_evidence_provenance"] = {
                "source_ids": ["snapshot:classification-v1.json"],
                "historical_validity": "source_context_only_not_continuous_membership",
                "history_backfill": False,
            }
            classification_row["inherited_classification_evidence"] = copy.deepcopy(evidence)
            classification_row["business_status"] = "explicit_evidence" if classification_row["company_business_assertions"] else "business_pending"
        for i, gap in enumerate(packet_gaps.get("gaps", packet_gaps.get("securities", []))):
            gaps.append(
                copy.deepcopy(gap) | {"gap_id": f"inherited-business:{i}", "source_ids": ["snapshot:gaps-v1.json"], "historical_validity": "not_established"}
            )
        for i, gap in enumerate(packet_sources.get("retrieval_gaps", [])):
            gaps.append(copy.deepcopy(gap) | {"gap_id": f"inherited-retrieval:{i}", "source_ids": ["snapshot:sources-v1.json"]})
    gaps.append({
        "gap_id": "business-evidence-queue",
        "kind": "business_evidence_incomplete",
        "reason": "This export does not complete the earlier 200 pending issuers or evidence backup ownership decision",
        "source_ids": ["snapshot:gaps-v1.json"] if present_packet else [],
    })
    result = {
        "classifications": _table("opportunity-classifications.v1", classifications),
        "groups": _table("opportunity-groups.v1", groups),
        "taxonomy_nodes": _table("opportunity-taxonomy-nodes.v1", nodes),
        "sources": _table("opportunity-sources.v1", sources),
        "gaps": _table("opportunity-gaps.v1", gaps),
    }
    _validate_source_refs(result, {row["source_id"] for row in sources})
    canonical_bytes(result)
    LOGGER.info("Built snapshot classifications for %d securities; business evidence remains pending", len(classifications))
    return result
