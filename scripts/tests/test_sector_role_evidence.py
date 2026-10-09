from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import research_core.sector_role_evidence as sector_role_evidence
from research_core.sector_role_evidence import ROLE_TAXONOMY_PATH, SectorRoleEvidenceError, validate_packet
from scripts.validate_sector_role_evidence import main as validate_cli

REAL_SCOPE_REGISTRY_PATH = sector_role_evidence.SCOPE_REGISTRY_PATH


def canonical(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


@pytest.fixture(autouse=True)
def scope_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sector_role_evidence, "SCOPE_REGISTRY_PATH", tmp_path / "scope-registry.json")


def catalog(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    root.mkdir()
    (root / "chunks").mkdir()
    rows: dict[str, list[dict[str, Any]]] = {
        "securities": [
            {"security_id": "TW:A", "code": "A", "official_industry": "IC", "group_ids": ["memory", "cooling"], "coverage_status": "classified"},
            {"security_id": "TW:B", "code": "B", "official_industry": "Other", "group_ids": [], "coverage_status": "source_missing"},
        ],
        "groups": [{"group_id": "memory"}, {"group_id": "cooling"}],
        "episodes": [{"episode_id": "episode-b", "security_id": "TW:B"}],
        "other": [{"x": 1}],
    }
    chunks = []
    for name, value in rows.items():
        path = root / "chunks" / f"{name}-0001.json.gz"
        with path.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
                zipped.write(json.dumps(value).encode("utf-8"))
        chunks.append({"table": name, "path": f"chunks/{path.name}", "rows": len(value), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {"schema_version": "sector-wave-catalog.v1", "counts": {name: len(value) for name, value in rows.items()}, "chunks": chunks}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    receipt = {"manifest_canonical_sha256": canonical(manifest), "counts": manifest["counts"]}
    (root / "completion-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    registry = json.loads(REAL_SCOPE_REGISTRY_PATH.read_text(encoding="utf-8"))
    profile = registry["profiles"][0]
    profile["base_manifest_canonical_sha256"] = canonical(manifest)
    profile["included_group_ids"] = ["memory", "cooling"]
    profile["seed_security_ids"] = []
    sector_role_evidence.SCOPE_REGISTRY_PATH.write_text(json.dumps(registry), encoding="utf-8")
    return root


def packet(root: Path) -> dict:
    excerpt = "Makes memory controllers."
    return {
        "schema_version": "sector-classification-evidence.v1",
        "packet_id": "p",
        "created_at": "2026-10-02T00:00:00+00:00",
        "limitations": ["Synthetic fixture is retrospective only; historical availability is unknown."],
        "scope_profile_id": "sector-role-review-20261002.v1",
        "base_catalog": {"schema_version": "sector-wave-catalog.v1", "manifest_canonical_sha256": canonical(json.loads((root / "manifest.json").read_text()))},
        "role_taxonomy": json.loads(ROLE_TAXONOMY_PATH.read_text(encoding="utf-8")),
        "scope": [
            {
                "security_id": "TW:A",
                "official_industry": "IC",
                "group_ids": ["memory", "cooling"],
                "scope_reasons": ["focused_memory_cooling_pcb"],
                "review_status": "source_verified",
                "unknown_reason": None,
            },
            {
                "security_id": "TW:B",
                "official_industry": "Other",
                "group_ids": [],
                "scope_reasons": ["source_missing_with_episode"],
                "review_status": "pending",
                "unknown_reason": "issuer source not reviewed",
            },
        ],
        "sources": [
            {
                "evidence_id": "e",
                "security_id": "TW:A",
                "url": "https://issuer.example/a",
                "title": "A",
                "source_kind": "issuer_page",
                "locator": "business",
                "inspection_method": "web_extracted_text",
                "retained_excerpt": excerpt,
                "retained_excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
                "retrieved_at": "2026-10-02T00:00:00+00:00",
                "published_at": None,
                "available_at": None,
                "covered_period": None,
                "unknown_reasons": {"published_at": "unknown", "available_at": "unknown", "covered_period": "unknown"},
                "supported_role_ids": ["memory-chip-manufacturer"],
                "supported_tag_ids": ["dram"],
                "supported_products_by_role": {"memory-chip-manufacturer": ["dram"]},
                "verification_status": "manually_verified",
            }
        ],
        "assertions": [
            {
                "assertion_id": "a",
                "security_id": "TW:A",
                "role_id": "memory-chip-manufacturer",
                "product_tag_ids": ["dram"],
                "evidence_refs": ["e"],
                "assertion_status": "source_verified",
                "effective_from": None,
                "effective_to": None,
                "unknown_reasons": {"effective_from": "unknown", "effective_to": "unknown", "business_relevance": "unknown", "exposure_path": "unknown"},
                "business_relevance": None,
                "business_relevance_evidence_refs": [],
                "business_relevance_basis": None,
                "exposure_path": None,
                "exposure_path_evidence_refs": [],
                "exposure_path_basis": None,
                "label_kind": "retrospective_annotation",
                "role_taxonomy_version": "sector-roles.v1",
            }
        ],
        "membership_reviews": [],
    }


def write(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_valid_packet_and_packet_tamper(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    summary = validate_packet(write(tmp_path, value), root)
    assert summary["sources"] == 1 and summary["original_validated_chunk_count"] == 4
    value["sources"][0]["retained_excerpt"] = "changed"
    with pytest.raises(SectorRoleEvidenceError, match="excerpt hash"):
        validate_packet(write(tmp_path, value), root)


@pytest.mark.parametrize("constant", [float("nan"), float("inf"), float("-inf")], ids=["NaN", "Infinity", "negative-Infinity"])
@pytest.mark.parametrize("nested", [False, True])
def test_nonstandard_json_metadata_is_rejected(tmp_path: Path, constant: float, nested: bool) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    value["optional_metadata"] = {"nested": [constant]} if nested else constant
    with pytest.raises(SectorRoleEvidenceError, match="non-finite"):
        validate_packet(write(tmp_path, value), root)


@pytest.mark.parametrize("constant", [float("nan"), float("inf"), float("-inf")], ids=["NaN", "Infinity", "negative-Infinity"])
def test_canonical_hash_cannot_serialize_nonfinite_numbers(constant: float) -> None:
    with pytest.raises(SectorRoleEvidenceError, match="canonical JSON"):
        sector_role_evidence._canonical({"nested": [constant]})


@pytest.mark.parametrize("constant", [float("nan"), float("inf"), float("-inf")], ids=["NaN", "Infinity", "negative-Infinity"])
def test_catalog_metadata_json_rejects_nonfinite_constants(tmp_path: Path, constant: float) -> None:
    root = catalog(tmp_path)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk = manifest["chunks"][0]
    chunk_path = root / chunk["path"]
    rows = json.loads(gzip.decompress(chunk_path.read_bytes()))
    rows[0]["optional_metadata"] = {"nested": [constant]}
    chunk_path.write_bytes(gzip.compress(json.dumps(rows).encode("utf-8"), mtime=0))
    chunk["sha256"] = hashlib.sha256(chunk_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (root / "completion-receipt.json").write_text(
        json.dumps({"manifest_canonical_sha256": canonical(manifest), "counts": manifest["counts"]}), encoding="utf-8"
    )
    with pytest.raises(SectorRoleEvidenceError, match="non-finite"):
        sector_role_evidence._catalog(root)


@pytest.mark.parametrize("number", ["1e400", "-1e400"])
def test_json_float_overflow_is_not_signed_as_a_finite_number(tmp_path: Path, number: str) -> None:
    path = tmp_path / "overflow.json"
    path.write_text('{"optional_metadata": ' + number + "}", encoding="utf-8")
    with pytest.raises(SectorRoleEvidenceError, match="non-finite"):
        sector_role_evidence._read_json(path)


def test_finite_json_and_nonfinite_names_in_strings_remain_compatible(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    value["optional_metadata"] = {"strings": ["NaN", "Infinity", "-Infinity"], "numbers": [0, -2, 1.25, 1e300], "missing": None}
    summary = validate_packet(write(tmp_path, value), root)
    assert summary["packet_canonical_sha256"] == canonical(value)


@pytest.mark.parametrize(
    ("created_at", "retrieved_at", "accepted"),
    [
        ("2026-10-02T00:00:00+00:00", "2026-10-02T00:00:00+00:00", True),
        ("2026-10-02T00:05:00+00:00", "2026-10-02T00:05:00+00:00", True),
        ("2026-10-02T00:05:01+00:00", "2026-10-02T00:00:00+00:00", False),
        ("2026-10-02T00:05:00+00:00", "2026-10-02T00:05:01+00:00", False),
        ("2999-01-01T00:00:00+00:00", "2026-10-02T00:00:00+00:00", False),
        ("2026-10-02T00:00:00+00:00", "2999-01-01T00:00:00+00:00", False),
        ("2999-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00", False),
    ],
)
def test_packet_and_source_times_allow_only_five_minutes_clock_skew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, created_at: str, retrieved_at: str, accepted: bool
) -> None:
    fixed_now = datetime(2026, 10, 2, tzinfo=UTC)
    monkeypatch.setattr(sector_role_evidence, "_utc_now", lambda: fixed_now)
    root = catalog(tmp_path)
    value = packet(root)
    value["created_at"] = created_at
    value["sources"][0]["retrieved_at"] = retrieved_at
    if accepted:
        assert validate_packet(write(tmp_path, value), root)["sources"] == 1
    else:
        with pytest.raises(SectorRoleEvidenceError, match="clock-skew cutoff"):
            validate_packet(write(tmp_path, value), root)


@pytest.mark.parametrize(
    ("url", "accepted"),
    [
        ("https://@/source", False),
        ("https://:443/source", False),
        ("https://issuer .example/source", False),
        ("https://issuer.\texample/source", False),
        ("https://issuer.example:not-a-port/source", False),
        ("https://issuer.example:70000/source", False),
        ("https://[bad/source", False),
        ("https://[v1.example]/source", False),
        ("https://issuer%zz.example/source", False),
        ("https://issuer%FF.example/source", False),
        ("https://issuer%20example/source", False),
        ("https://[fe80::1%25eth%00]/source", False),
        ("https://issuer!.example/source", False),
        ("https://issuer.example:443/source", True),
        ("https://issuer.example./source", True),
        ("https://\u4f8b\u5b50.\u6d4b\u8bd5/source", True),
        ("https://%E4%BE%8B%E5%AD%90.%E6%B5%8B%E8%AF%95/source", True),
        ("https://192.0.2.1/source", True),
        ("https://[2001:db8::1]/source", True),
    ],
)
def test_source_url_requires_valid_https_hostname_and_port(tmp_path: Path, url: str, accepted: bool) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    value["sources"][0]["url"] = url
    if accepted:
        assert validate_packet(write(tmp_path, value), root)["sources"] == 1
    else:
        with pytest.raises(SectorRoleEvidenceError, match="source URL"):
            validate_packet(write(tmp_path, value), root)


@pytest.mark.parametrize("inspection_method", [None, "", "   "])
def test_source_requires_nonempty_inspection_method(tmp_path: Path, inspection_method: str | None) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    value["sources"][0]["inspection_method"] = inspection_method
    with pytest.raises(SectorRoleEvidenceError, match="inspection_method"):
        validate_packet(write(tmp_path, value), root)


@pytest.mark.parametrize(("basis", "accepted"), [("annual report period", True), ("", False), ("   ", False)])
def test_covered_period_requires_nonempty_basis(tmp_path: Path, basis: str, accepted: bool) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    value["sources"][0]["covered_period"] = {"start": "2025-01-01", "end": "2025-12-31", "basis": basis}
    if accepted:
        assert validate_packet(write(tmp_path, value), root)["sources"] == 1
    else:
        with pytest.raises(SectorRoleEvidenceError, match="covered_period.basis"):
            validate_packet(write(tmp_path, value), root)


@pytest.mark.parametrize("limitations", [None, [], [1], ["  "]])
def test_packet_requires_nonempty_text_limitations(tmp_path: Path, limitations: object) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    if limitations is None:
        del value["limitations"]
    else:
        value["limitations"] = limitations
    with pytest.raises(SectorRoleEvidenceError, match="limitations|limitation"):
        validate_packet(write(tmp_path, value), root)


def test_rejects_role_taxonomy_label_change_with_same_id(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    value["role_taxonomy"]["roles"][0]["label"] = "changed label"
    with pytest.raises(SectorRoleEvidenceError, match="canonical taxonomy"):
        validate_packet(write(tmp_path, value), root)


@pytest.mark.parametrize(
    ("retrieved_at", "published_on", "accepted"),
    [
        ("2026-10-02T00:00:00+00:00", "2026-10-02", True),
        ("2026-10-01T23:30:00+00:00", "2026-10-02", True),
        ("2026-10-02T00:00:00+00:00", "2026-10-03", False),
        ("2026-10-02T00:00:00+00:00", "2999-01-01", False),
    ],
)
def test_published_on_respects_unknown_timezone_and_rejects_future_days(tmp_path: Path, retrieved_at: str, published_on: str, accepted: bool) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    value["created_at"] = retrieved_at
    value["sources"][0]["retrieved_at"] = retrieved_at
    value["sources"][0]["published_on"] = published_on
    if accepted:
        assert validate_packet(write(tmp_path, value), root)["sources"] == 1
    else:
        with pytest.raises(SectorRoleEvidenceError, match="published_on follows retrieval"):
            validate_packet(write(tmp_path, value), root)


def test_published_receipt_detects_packet_change_after_inner_hash_refresh(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    packet_path = write(tmp_path, value)
    receipt_path = tmp_path / "published-receipt.json"
    receipt_path.write_text(json.dumps(validate_packet(packet_path, root)), encoding="utf-8")
    assert validate_packet(packet_path, root, receipt_path)["packet_id"] == "p"
    value["sources"][0]["retained_excerpt"] = "Updated proof text."
    value["sources"][0]["retained_excerpt_sha256"] = hashlib.sha256(value["sources"][0]["retained_excerpt"].encode()).hexdigest()
    packet_path = write(tmp_path, value)
    with pytest.raises(SectorRoleEvidenceError, match="published packet receipt mismatch"):
        validate_packet(packet_path, root, receipt_path)


def test_assertion_rejects_same_security_source_without_role_or_tag_support(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    source = dict(value["sources"][0])
    source["evidence_id"] = "unrelated"
    source["supported_role_ids"] = ["pcb-manufacturer"]
    source["supported_tag_ids"] = []
    source["supported_products_by_role"] = {"pcb-manufacturer": []}
    value["sources"].append(source)
    value["assertions"][0]["evidence_refs"].append("unrelated")
    with pytest.raises(SectorRoleEvidenceError, match="irrelevant evidence"):
        validate_packet(write(tmp_path, value), root)


def test_products_supported_for_another_role_do_not_validate_assertion(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    source = value["sources"][0]
    source["supported_role_ids"].append("transformer-manufacturer")
    source["supported_tag_ids"].append("nand-flash")
    source["supported_products_by_role"]["transformer-manufacturer"] = ["nand-flash"]
    value["assertions"][0]["product_tag_ids"].append("nand-flash")
    with pytest.raises(SectorRoleEvidenceError, match="not supported by evidence"):
        validate_packet(write(tmp_path, value), root)


def test_product_only_source_can_supplement_same_role_products(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    source = dict(value["sources"][0])
    source.update(
        evidence_id="products",
        supported_role_ids=[],
        supported_tag_ids=["nand-flash"],
        supported_products_by_role={"memory-chip-manufacturer": ["nand-flash"]},
    )
    value["sources"].append(source)
    value["assertions"][0]["product_tag_ids"].append("nand-flash")
    value["assertions"][0]["evidence_refs"].append("products")
    assert validate_packet(write(tmp_path, value), root)["sources"] == 2


def test_source_requires_product_mapping_for_each_supported_role(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    source = value["sources"][0]
    source["supported_tag_ids"] = []
    source["supported_products_by_role"] = {"memory-chip-manufacturer": []}
    value["assertions"][0]["product_tag_ids"] = []
    assert validate_packet(write(tmp_path, value), root)["sources"] == 1
    del source["supported_products_by_role"]["memory-chip-manufacturer"]
    with pytest.raises(SectorRoleEvidenceError, match="role/product associations"):
        validate_packet(write(tmp_path, value), root)


@pytest.mark.parametrize(
    ("field", "refs", "basis"),
    [
        ("business_relevance", ["e"], None),
        ("exposure_path", ["e"], None),
        ("business_relevance", ["missing"], None),
        ("exposure_path", ["missing"], None),
        ("business_relevance", [], "unsupported basis"),
        ("exposure_path", [], "unsupported basis"),
    ],
)
def test_unknown_economic_assessments_require_empty_refs_and_null_basis(tmp_path: Path, field: str, refs: list[str], basis: str | None) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    assertion = value["assertions"][0]
    assertion[f"{field}_evidence_refs"] = refs
    assertion[f"{field}_basis"] = basis

    with pytest.raises(SectorRoleEvidenceError):
        validate_packet(write(tmp_path, value), root)


def test_populated_economic_assessments_accept_valid_assertion_evidence(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    assertion = value["assertions"][0]
    assertion.update(
        business_relevance="core",
        business_relevance_evidence_refs=["e"],
        business_relevance_basis="reviewed issuer description",
        exposure_path="direct",
        exposure_path_evidence_refs=["e"],
        exposure_path_basis="reviewed issuer description",
    )

    assert validate_packet(write(tmp_path, value), root)["assertions"] == 1


@pytest.mark.parametrize("field", ["business_relevance", "exposure_path"])
def test_populated_economic_assessment_rejects_nonassertion_evidence(tmp_path: Path, field: str) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    assertion = value["assertions"][0]
    assertion[field] = "core" if field == "business_relevance" else "direct"
    assertion[f"{field}_basis"] = "reviewed issuer description"
    assertion[f"{field}_evidence_refs"] = ["missing"]

    with pytest.raises(SectorRoleEvidenceError, match="evidence_refs"):
        validate_packet(write(tmp_path, value), root)


def test_membership_reviews_allow_distinct_groups_but_reject_duplicate_pair(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    value = packet(root)

    def review(group: str) -> dict:
        return {
            "security_id": "TW:A",
            "group_id": group,
            "review_status": "needs_role_review",
            "reason": "review",
            "evidence_refs": ["e"],
        }

    value["membership_reviews"] = [review("memory"), review("cooling")]
    assert validate_packet(write(tmp_path, value), root)["membership_reviews"] == 2
    value["membership_reviews"].append(review("memory"))
    with pytest.raises(SectorRoleEvidenceError, match="duplicate membership review"):
        validate_packet(write(tmp_path, value), root)


def test_pending_scope_can_consume_review_only_source(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    value["scope"][0]["review_status"] = "pending"
    value["scope"][0]["unknown_reason"] = "role evidence not classified"
    value["assertions"] = []
    value["membership_reviews"] = [
        {
            "security_id": "TW:A",
            "group_id": "memory",
            "review_status": "needs_role_review",
            "reason": "needs review",
            "evidence_refs": ["e"],
        }
    ]
    assert validate_packet(write(tmp_path, value), root)["verified_securities"] == 0


@pytest.mark.parametrize("change", ["remove_source_missing", "change_source_missing_reason", "unknown_profile"])
def test_scope_profile_requires_exact_queue_and_reasons(tmp_path: Path, change: str) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    if change == "remove_source_missing":
        value["scope"] = [value["scope"][0]]
    elif change == "change_source_missing_reason":
        value["scope"][1]["scope_reasons"] = ["registered_issuer_seed"]
    else:
        value["scope_profile_id"] = "unknown"
    with pytest.raises(SectorRoleEvidenceError, match="scope"):
        validate_packet(write(tmp_path, value), root)


def test_scope_profile_uses_its_included_group_reason(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    registry_path = sector_role_evidence.SCOPE_REGISTRY_PATH
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    custom_profile = dict(registry["profiles"][0])
    custom_profile.update(
        profile_id="cooling-only",
        included_group_ids=["cooling"],
        included_group_reason="focused_cooling_only",
        seed_security_ids=[],
    )
    registry["profiles"].append(custom_profile)
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    value = packet(root)
    value["scope_profile_id"] = "cooling-only"
    with pytest.raises(SectorRoleEvidenceError):
        validate_packet(write(tmp_path, value), root)
    value["scope"][0]["scope_reasons"] = ["focused_cooling_only"]

    assert validate_packet(write(tmp_path, value), root)["scope_securities"] == 2


@pytest.mark.parametrize("variant", ["missing", "none", "whitespace"])
def test_scope_profile_requires_nonempty_included_group_reason(tmp_path: Path, variant: str) -> None:
    root = catalog(tmp_path)
    registry_path = sector_role_evidence.SCOPE_REGISTRY_PATH
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    profile = registry["profiles"][0]
    if variant == "missing":
        del profile["included_group_reason"]
    else:
        profile["included_group_reason"] = None if variant == "none" else "   "
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    with pytest.raises(SectorRoleEvidenceError, match="included_group_reason"):
        validate_packet(write(tmp_path, packet(root)), root)


@pytest.mark.parametrize("reason", ["source_missing_with_episode", "registered_issuer_seed"])
def test_scope_profile_group_reason_cannot_impersonate_other_rules(tmp_path: Path, reason: str) -> None:
    root = catalog(tmp_path)
    registry_path = sector_role_evidence.SCOPE_REGISTRY_PATH
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["profiles"][0]["included_group_reason"] = reason
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(SectorRoleEvidenceError, match="included_group_reason collides"):
        validate_packet(write(tmp_path, packet(root)), root)


@pytest.mark.parametrize(
    ("field", "unknown", "message"),
    [("included_group_ids", "missing-group", "unknown profile group"), ("seed_security_ids", "TW:missing", "unknown profile seed")],
)
def test_scope_profile_rejects_unknown_catalog_references(tmp_path: Path, field: str, unknown: str, message: str) -> None:
    root = catalog(tmp_path)
    registry_path = sector_role_evidence.SCOPE_REGISTRY_PATH
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["profiles"][0][field].append(unknown)
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    with pytest.raises(SectorRoleEvidenceError, match=message):
        validate_packet(write(tmp_path, packet(root)), root)


def test_scope_profile_accepts_known_seed_and_requires_seed_reason(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    registry_path = sector_role_evidence.SCOPE_REGISTRY_PATH
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["profiles"][0]["seed_security_ids"] = ["TW:A"]
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    value = packet(root)
    with pytest.raises(SectorRoleEvidenceError):
        validate_packet(write(tmp_path, value), root)
    value["scope"][0]["scope_reasons"].append("registered_issuer_seed")

    assert validate_packet(write(tmp_path, value), root)["scope_securities"] == 2


def test_scope_profile_rejects_rewritten_catalog_and_matching_smaller_packet(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    security_chunk = next(chunk for chunk in manifest["chunks"] if chunk["table"] == "securities")
    chunk_path = root / security_chunk["path"]
    with gzip.open(chunk_path, "rt", encoding="utf-8") as handle:
        securities = json.load(handle)
    with chunk_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(json.dumps([securities[0]]).encode("utf-8"))
    security_chunk["rows"] = 1
    security_chunk["sha256"] = hashlib.sha256(chunk_path.read_bytes()).hexdigest()
    manifest["counts"]["securities"] = 1
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "completion-receipt.json").write_text(
        json.dumps({"manifest_canonical_sha256": canonical(manifest), "counts": manifest["counts"]}), encoding="utf-8"
    )
    value = packet(root)
    value["scope"] = [value["scope"][0]]

    with pytest.raises(SectorRoleEvidenceError, match="scope profile base catalog"):
        validate_packet(write(tmp_path, value), root)


def test_rejects_duplicate_security_role_assertions(tmp_path: Path) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    duplicate = dict(value["assertions"][0])
    duplicate["assertion_id"] = "a-duplicate"
    value["assertions"].append(duplicate)
    with pytest.raises(SectorRoleEvidenceError, match="duplicate assertion security/role"):
        validate_packet(write(tmp_path, value), root)


@pytest.mark.parametrize("target", ["packet", "packet_alias", "catalog_manifest", "catalog_chunk", "existing_file"])
def test_receipt_cli_rejects_artifact_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    root = catalog(tmp_path)
    packet_path = write(tmp_path, packet(root))
    existing = tmp_path / "existing.json"
    existing.write_text("preserve me", encoding="utf-8")
    targets = {
        "packet": packet_path,
        "packet_alias": packet_path.parent / "nested" / ".." / packet_path.name,
        "catalog_manifest": root / "manifest.json",
        "catalog_chunk": root / "chunks" / "securities-0001.json.gz",
        "existing_file": existing,
    }
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    monkeypatch.setattr("sys.argv", ["validate", str(packet_path), "--catalog", str(root), "--write-receipt", str(targets[target])])
    with pytest.raises(SystemExit) as error:
        validate_cli()
    assert error.value.code == 2
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_receipt_cli_writes_new_summary_and_preserves_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = catalog(tmp_path)
    packet_path = write(tmp_path, packet(root))
    output = tmp_path / "new-receipt.json"
    before = packet_path.read_bytes()
    monkeypatch.setattr("sys.argv", ["validate", str(packet_path), "--catalog", str(root), "--write-receipt", str(output)])
    validate_cli()
    assert packet_path.read_bytes() == before
    assert json.loads(output.read_text(encoding="utf-8")) == validate_packet(packet_path, root)


@pytest.mark.parametrize("change", ["bad_ref", "unsupported_known_tag", "retrieval_date", "scope", "traversal", "catalog_chunk"])
def test_rejects_contract_breaks(tmp_path: Path, change: str) -> None:
    root = catalog(tmp_path)
    value = packet(root)
    if change == "bad_ref":
        value["assertions"][0]["evidence_refs"] = ["missing"]
    elif change == "unsupported_known_tag":
        value["assertions"][0]["product_tag_ids"] = ["nand-flash"]
    elif change == "retrieval_date":
        value["assertions"][0]["effective_from"] = "2026-10-02"
        value["assertions"][0]["effective_to"] = None
    elif change == "scope":
        value["scope"][0]["group_ids"] = []
    elif change == "traversal":
        manifest = json.loads((root / "manifest.json").read_text())
        manifest["chunks"][0]["path"] = "../outside"
        (root / "manifest.json").write_text(json.dumps(manifest))
        (root / "completion-receipt.json").write_text(json.dumps({"manifest_canonical_sha256": canonical(manifest), "counts": manifest["counts"]}))
    else:
        (root / "chunks" / "other-0001.json.gz").write_bytes(b"bad")
    with pytest.raises(SectorRoleEvidenceError):
        validate_packet(write(tmp_path, value), root)
