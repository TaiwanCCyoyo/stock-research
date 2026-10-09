"""Assemble reviewed issuer excerpts with the immutable catalog's review queue.

This is an offline annotation assembler. It performs no acquisition or price reads.
Excerpt fragments separated by an ellipsis are non-contiguous source quotes.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from research_core.sector_role_evidence import validate_packet

ROOT = Path(__file__).resolve().parents[2]
TASK = Path(__file__).resolve().parent
CATALOG = ROOT / "tasks/20261002-sector-wave-catalog/catalog-v1"
BASE_SHA = "384ee53d22b70dc1650bf84e1887e8515565189c975c29c77ef5e6273c5138c9"
INSPECTED_AT = "2026-10-02T07:54:27+00:00"
CREATED_AT = "2026-10-02T08:18:49+00:00"
SEEDS = "2408 2344 2337 3006 6485 3260 3324 3017 6230 2421 8046 3189 3037 6274 2368 5381 5321 2614".split()

# Reviewed issuer/role associations; observed source products must still support every tag.
REVIEWED_ROLE_PRODUCTS: dict[str, dict[str, list[str]]] = {
    "2337": {"memory-chip-manufacturer": ["nand-flash", "nor-flash"]},
    "2344": {"memory-chip-manufacturer": ["dram", "nand-flash", "nor-flash"]},
    "2368": {"pcb-manufacturer": ["pcb"]},
    "2408": {"memory-chip-manufacturer": ["dram"]},
    "2421": {"fan-manufacturer": ["fan"], "thermal-solution-supplier": ["fan", "liquid-cooling"]},
    "2614": {"port-warehouse-operator": []},
    "3006": {"memory-ic-designer": ["dram", "nand-flash", "nor-flash"]},
    "3017": {"thermal-solution-supplier": []},
    "3037": {"ic-substrate-manufacturer": [], "pcb-manufacturer": ["pcb"]},
    "3189": {"ic-substrate-manufacturer": ["abf-substrate"]},
    "3260": {"memory-module-supplier": ["dram", "memory-module", "ssd"]},
    "3324": {"thermal-solution-supplier": ["air-cooling", "liquid-cooling"]},
    "5321": {"retail-ecommerce-operator": ["fashion-ecommerce"]},
    "5381": {"electronic-material-supplier": ["pcb-drilling-materials"], "transformer-manufacturer": ["distribution-transformer"]},
    "6230": {"thermal-solution-supplier": ["liquid-cooling"]},
    "6274": {
        "copper-clad-laminate-manufacturer": ["copper-clad-laminate", "prepreg"],
        "electronic-material-supplier": ["copper-clad-laminate", "prepreg"],
    },
    "6485": {"memory-controller-supplier": ["flash-controller"]},
    "8046": {"ic-substrate-manufacturer": [], "pcb-manufacturer": ["pcb"]},
}


def reviewed_sources() -> list[dict[str, Any]]:
    """Manual source judgments; list support separately from assertion construction."""
    rows: list[dict[str, Any]] = []

    def add(
        code: str,
        url: str,
        title: str,
        locator: str,
        excerpt: str,
        roles: list[str],
        tags: list[str],
        year: int | None = None,
        method: str = "web_extracted_text",
        published_on: str | None = None,
    ) -> None:
        rows.append({
            "evidence_id": f"issuer-{code}-{len([row for row in rows if row['security_id'] == f'TW:{code}']) + 1}",
            "security_id": f"TW:{code}",
            "url": url,
            "title": title,
            "source_kind": "issuer_report" if year is not None else "issuer_page",
            "locator": locator,
            "retained_excerpt": excerpt,
            "retained_excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            "retrieved_at": INSPECTED_AT,
            "inspection_method": method,
            "published_at": None,
            "published_on": published_on,
            "available_at": None,
            "covered_period": None if year is None else {"start": f"{year}-01-01", "end": f"{year}-12-31", "basis": "report_year; not role-effective interval"},
            "unknown_reasons": {
                "published_at": "Publication timestamp/timezone not established; printed day, if known, is separate.",
                "available_at": "First public availability not independently reconstructed.",
                **({"covered_period": "Undated company page; retrieval does not establish historical coverage."} if year is None else {}),
            },
            "supported_role_ids": roles,
            "supported_tag_ids": tags,
            "supported_products_by_role": source_products_by_role(code, roles, tags),
            "verification_status": "manually_verified",
        })

    add(
        "2408",
        "https://www.nanya.com/tw/About",
        "南亞科技－公司簡介",
        "公司簡介／關於南亞科技",
        "DRAM (動態隨機存取記憶體)的研發、設計、製造與銷售",
        ["memory-chip-manufacturer"],
        ["dram"],
    )
    add(
        "2344",
        "https://www.winbond.com.tw/hq/about-winbond/company-profile/overview/?__locale=zh_TW",
        "華邦電子－簡介",
        "簡介／第二段",
        "從產品設計、技術研發、晶圓製造到自有品牌行銷全球",
        ["memory-chip-manufacturer"],
        [],
    )
    add(
        "2344",
        "https://www.winbond.com.tw/export/sites/winbond/product-selection-guide/file/2022-Winbond-Product-Brochure-CHT.pdf",
        "2022 華邦電子產品型錄",
        "PDF pages 4, 10 (1-based); DRAM and Flash product overview",
        "提供高效能和低功耗的 DRAM 廣泛應用產品組合…1.2V SPI NOR…NOR+NAND",
        [],
        ["dram", "nor-flash", "nand-flash"],
        2022,
        "direct_https_pdf_text; normal TLS validation",
    )
    add(
        "2337",
        "https://www.macronix.com/zh-tw/about/Pages/company-overview.aspx",
        "旺宏電子－公司簡介",
        "公司簡介／產品及晶圓廠段落",
        "NOR型快閃記憶體以及NAND型快閃記憶體…生產製造",
        ["memory-chip-manufacturer"],
        ["nor-flash", "nand-flash"],
    )
    add(
        "3006",
        "https://www.esmt.com.tw/tw/about/introduction",
        "晶豪科技－晶豪簡介",
        "概況／創立",
        "IC 設計…DRAM 產品線…NOR Flash 及 NAND Flash 的開發",
        ["memory-ic-designer"],
        ["dram", "nor-flash", "nand-flash"],
    )
    add(
        "6485",
        "https://asolid-tek.com/%E9%97%9C%E6%96%BC%E9%BB%9E%E5%BA%8F/",
        "點序科技－關於點序",
        "關於點序／第一段",
        "為快閃記憶體控制晶片供應商。…SSD 控制晶片等。",
        ["memory-controller-supplier"],
        ["flash-controller"],
    )
    add(
        "3260",
        "https://webapi3.adata.com/storage/ir/adata_2023_annual_report_cn.pdf",
        "威剛科技112年度年報",
        "PDF page 81 (1-based); 營運概況／業務內容",
        "記憶體模組、快閃記憶體相關產品之製造及買賣。…DRAM 產品…固態硬碟",
        ["memory-module-supplier"],
        ["memory-module", "dram", "ssd"],
        2023,
    )
    add(
        "3324",
        "https://www.auras.com.tw/CMSFS/Shareholders/FinancialAnnualChinese/ed4475a3-db60-455c-9ce9-93699a2fe601.pdf",
        "雙鴻科技113年度年報",
        "PDF page 78 (1-based); 液冷方案／PDF page 65 product table",
        "氣冷模組…液冷技術整機櫃系統供應商",
        ["thermal-solution-supplier"],
        ["air-cooling", "liquid-cooling"],
        2024,
        "direct_https_pdf_text; normal TLS validation",
        "2025-03-18",
    )
    add(
        "3017",
        "https://www.avc.co/zh-tw/About-AVC/CompanyProfile",
        "奇鋐科技－公司介紹",
        "關於奇鋐／第一段",
        "整體散熱解決方案的專業供應商",
        ["thermal-solution-supplier"],
        [],
    )
    add(
        "6230",
        "https://www.ccic.com.tw/about/1",
        "尼得科超眾－關於我們",
        "關於尼得科超眾／第一段",
        "散傳熱產品的專業供應商…散熱片、熱管、熱板、散熱模組",
        ["thermal-solution-supplier"],
        [],
    )
    add(
        "6230",
        "https://www.ccic.com.tw/products/28/1",
        "尼得科超眾－Liquid Cooling System",
        "Product category heading and listed rack/server solutions",
        "Liquid Cooling System…Server level, Rack level.",
        [],
        ["liquid-cooling"],
    )
    add(
        "2421",
        "https://www.sunon.com/about.aspx",
        "建準－關於我們",
        "生產實力／產業實力",
        "生產全系列風扇…散熱模組及液冷系統",
        ["fan-manufacturer", "thermal-solution-supplier"],
        ["fan", "liquid-cooling"],
    )
    add(
        "8046",
        "https://www.nanyapcb.com.tw/nypcb/chinese/AboutNanYaPCB/CompanyProfile/Vision",
        "南亞電路板－經營理念及願景",
        "第一段; page footer provided date 2022/08/12 (not proven first availability)",
        "印刷電路板…IC載板…生產、製造及研發工作",
        ["pcb-manufacturer", "ic-substrate-manufacturer"],
        ["pcb"],
        published_on="2022-08-12",
    )
    add(
        "3189",
        "https://www.kinsus.com.tw/en/html/message_from_the_chairman/index",
        "Kinsus－Message from the Chairman",
        "Strategic Resilience / Green Intelligent Manufacturing",
        "large-area high-layer-count ABF substrates…the substrate manufacturing process’s high dependence on energy and water resources",
        ["ic-substrate-manufacturer"],
        ["abf-substrate"],
    )
    rows[-1]["covered_period"] = {
        "start": "2025-01-01",
        "end": "2025-12-31",
        "basis": "Body explicitly reviews year 2025 with a 2026 outlook; context year, not role-effective interval.",
    }
    rows[-1]["unknown_reasons"].pop("covered_period")
    add(
        "3037",
        "https://www.unimicron.com/about04.html",
        "欣興電子－全球生產基地",
        "台灣：蘆竹二廠／楊梅廠",
        "蘆竹二廠： 主力產品：(PCB/HDI)…楊 梅 廠： 主力產品：(CARRIER)",
        ["pcb-manufacturer"],
        ["pcb"],
        method="direct_https_html; Windows normal TLS validation",
    )
    add(
        "3037",
        "https://www.unimicron.com/files/money/Shareholders_Meeting/115年股東會年報.pdf",
        "欣興電子114年度年報",
        "PDF page 67 (1-based); 營運概況／業務範圍／所營業務之主要內容",
        "印刷電路板…載板(IC Carrier)之開發、製造、加工與銷售",
        ["pcb-manufacturer", "ic-substrate-manufacturer"],
        ["pcb"],
        2025,
        "direct_https_pdf_text; Windows normal TLS download validation",
        "2026-02-24",
    )
    rows[-1]["retrieved_at"] = CREATED_AT
    add(
        "6274",
        "https://www.tuc.com.tw/zh-tw/about",
        "台燿科技－關於台燿",
        "關於台燿／第一段",
        "銅箔基板…黏合片(Prepreg)之生產製造領域",
        ["copper-clad-laminate-manufacturer", "electronic-material-supplier"],
        ["copper-clad-laminate", "prepreg"],
    )
    add(
        "2368",
        "https://www.gce.com.tw/environment.html",
        "金像電子－環境政策",
        "公司業務介紹／第一段",
        "多層印刷電路板專業製造廠商",
        ["pcb-manufacturer"],
        ["pcb"],
    )
    add(
        "5381",
        "https://spe-group.com.tw/tw/about/company-overview",
        "光譜電工－公司概要",
        "公司簡介／第一段",
        "配電級變壓器及PCB鑽孔材料…研發、製造",
        ["electronic-material-supplier", "transformer-manufacturer"],
        ["pcb-drilling-materials", "distribution-transformer"],
    )
    add(
        "5321",
        "https://www.unitedrecommendation.com/overview",
        "美而快國際－集團概述",
        "集團背景／第一段; listed-entity transformation narrative",
        "服飾電商…企業轉型，發展電商業務",
        ["retail-ecommerce-operator"],
        ["fashion-ecommerce"],
    )
    add(
        "2614",
        "https://eng.emic.com.tw/warehousing.php",
        "EMI－Warehousing & Grain Trade",
        "Warehousing & Grain Trade／first paragraph (undated, potentially stale)",
        "EMI leveraged its expertise in professional portside warehousing and handling to set up a grain trading office.",
        ["port-warehouse-operator"],
        [],
    )
    return rows


def review_scope(securities: list[dict[str, Any]], episodes: set[str], verified: set[str]) -> list[dict[str, Any]]:
    """Retain unresolved securities and registered seeds across presentation groups."""
    scope = []
    for security in securities:
        reasons = []
        if {"memory", "cooling", "pcb"} & set(security["group_ids"]):
            reasons.append("focused_memory_cooling_pcb")
        if security["coverage_status"] == "source_missing" and security["security_id"] in episodes:
            reasons.append("source_missing_with_episode")
        if security["code"] in SEEDS:
            reasons.append("registered_issuer_seed")
        if reasons:
            scope.append({
                "security_id": security["security_id"],
                "official_industry": security["official_industry"],
                "group_ids": security["group_ids"],
                "scope_reasons": sorted(reasons),
                "review_status": "source_verified" if security["security_id"] in verified else "pending",
                "unknown_reason": None if security["security_id"] in verified else "issuer_role_source_not_reviewed_in_first_batch",
            })
    return scope


def role_products(code: str, role: str, observed_tags: set[str]) -> list[str]:
    """Require an explicit reviewed association and retain only observed products."""
    try:
        permitted_tags = REVIEWED_ROLE_PRODUCTS[code][role]
    except KeyError as error:
        raise ValueError(f"unreviewed issuer-role product mapping: {code}/{role}") from error
    return sorted(observed_tags & set(permitted_tags))


def role_evidence_refs(role: str, tags: list[str], sources: list[dict[str, Any]]) -> list[str]:
    """Keep role and product evidence without attaching unrelated issuer sources."""
    requested_tags = set(tags)
    return [row["evidence_id"] for row in sources if role in row["supported_role_ids"] or requested_tags & set(row["supported_products_by_role"].get(role, []))]


def source_products_by_role(code: str, roles: list[str], tags: list[str]) -> dict[str, list[str]]:
    """Reviewed associations; a product-only source does not establish a business role."""
    if not roles and tags:
        product_context_roles = {"2344": ["memory-chip-manufacturer"], "6230": ["thermal-solution-supplier"]}
        roles = product_context_roles[code]
    return {role: role_products(code, role, set(tags)) for role in roles}


def publish_packet(packet: dict[str, Any], task_dir: Path, catalog_dir: Path, scratch_dir: Path) -> dict[str, Any]:
    """Allow one publisher per resolved task directory, including validation and rollback."""
    task_dir = task_dir.resolve()
    lock_path = task_dir / ".sector-role-publication.lock"
    try:
        lock = lock_path.open("x", encoding="utf-8")
    except FileExistsError as error:
        raise RuntimeError(f"publication lock exists at {lock_path}; check the active publisher or interrupted publication before recovery") from error
    try:
        with lock:
            lock.write(f"pid={os.getpid()}\n")
            lock.flush()
            return _publish_packet_locked(packet, task_dir, catalog_dir, scratch_dir)
    finally:
        lock_path.unlink()


def _publish_packet_locked(packet: dict[str, Any], task_dir: Path, catalog_dir: Path, scratch_dir: Path) -> dict[str, Any]:
    """Validate staged files before per-file atomic replacement; retain failed recovery backups."""
    scratch_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="role-packet-", dir=scratch_dir)).resolve()
    if not staging.is_relative_to(scratch_dir.resolve()):
        raise ValueError("staging path outside task scratch directory")
    candidate = staging / "candidate-packet.json"
    candidate_receipt = staging / "candidate-receipt.json"
    old_packet = staging / "old-packet.json"
    old_receipt = staging / "old-receipt.json"
    owned_files = (candidate, candidate_receipt, old_packet, old_receipt, staging / "restore-evidence-v1.json", staging / "restore-completion-receipt.json")
    preserve_recovery = False
    try:
        candidate.write_text(json.dumps(packet, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
        receipt = validate_packet(candidate, catalog_dir)
        candidate_receipt.write_text(json.dumps(receipt, sort_keys=True, indent=4) + "\n", encoding="utf-8")
        validate_packet(candidate, catalog_dir, candidate_receipt)
        outputs = ((task_dir / "evidence-v1.json", candidate, old_packet), (task_dir / "completion-receipt.json", candidate_receipt, old_receipt))
        backups: dict[Path, Path | None] = {}
        for target, _, backup in outputs:
            if target.exists():
                backup.write_bytes(target.read_bytes())
                backups[target] = backup
            else:
                backups[target] = None
        replaced: list[Path] = []
        try:
            for target, staged, _ in outputs:
                replaced.append(target)
                os.replace(staged, target)
        except BaseException as error:
            # Retain backups if recovery itself is interrupted or cannot finish.
            preserve_recovery = True
            rollback_failed = False
            for target in reversed(replaced):
                try:
                    prior = backups[target]
                    if prior is None:
                        target.unlink(missing_ok=True)
                    else:
                        restoration = staging / f"restore-{target.name}"
                        restoration.write_bytes(prior.read_bytes())
                        os.replace(restoration, target)
                except OSError as rollback_error:
                    rollback_failed = True
                    error.add_note(f"Could not restore {target}: {rollback_error}; recovery files retained at {staging}")
            preserve_recovery = rollback_failed
            raise
        return receipt
    finally:
        if not preserve_recovery:
            for path in owned_files:
                path.unlink(missing_ok=True)
            staging.rmdir()


def main() -> None:
    manifest = json.loads((CATALOG / "manifest.json").read_text(encoding="utf-8"))
    canonical = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    if canonical != BASE_SHA:
        raise ValueError("registered base identity changed")
    tables: dict[str, list[dict[str, Any]]] = {"securities": [], "episodes": []}
    for chunk in manifest["chunks"]:
        if chunk["table"] in tables:
            tables[chunk["table"]].extend(json.loads(gzip.decompress((CATALOG / chunk["path"]).read_bytes())))
    episodes = {row["security_id"] for row in tables["episodes"]}
    sources = reviewed_sources()
    assertions = []
    for code in sorted(SEEDS):
        same_sources = [row for row in sources if row["security_id"] == f"TW:{code}"]
        role_ids = sorted({role for row in same_sources for role in row["supported_role_ids"]})
        for role in role_ids:
            tags = role_products(code, role, {tag for row in same_sources for tag in row["supported_tag_ids"]})
            assertions.append({
                "assertion_id": f"role-{code}-{role}",
                "security_id": f"TW:{code}",
                "role_id": role,
                "product_tag_ids": tags,
                "evidence_refs": role_evidence_refs(role, tags, same_sources),
                "assertion_status": "source_verified",
                "effective_from": None,
                "effective_to": None,
                "unknown_reasons": {
                    "effective_from": "Role onset/continuous historical validity not established by retained evidence.",
                    "effective_to": "Role end/continuous historical validity not established by retained evidence.",
                    "business_relevance": "No role-specific core/secondary assessment or revenue allocation in this packet.",
                    "exposure_path": "No separate direct/indirect economic exposure assessment in this packet.",
                },
                "business_relevance": None,
                "business_relevance_evidence_refs": [],
                "business_relevance_basis": None,
                "exposure_path": None,
                "exposure_path_evidence_refs": [],
                "exposure_path_basis": None,
                "label_kind": "retrospective_annotation",
                "role_taxonomy_version": "sector-roles.v1",
            })
    verified = {row["security_id"] for row in assertions}
    scope = review_scope(tables["securities"], episodes, verified)
    reviews = [
        {
            "security_id": "TW:5321",
            "group_id": "pcb-manufacturing",
            "review_status": "needs_role_review",
            "reason": (
                "Issuer describes listed-company transformation to fashion ecommerce. "
                "Original PCB membership needs dated business-history review; this is not exclusion proof."
            ),
            "evidence_refs": ["issuer-5321-1"],
        },
        {
            "security_id": "TW:5381",
            "group_id": "pcb-manufacturing",
            "review_status": "needs_role_review",
            "reason": (
                "Issuer explicitly describes PCB drilling materials and distribution transformers. "
                "Distinguish electronic materials from PCB board manufacturing; keep historical scope unresolved."
            ),
            "evidence_refs": ["issuer-5381-1"],
        },
        {
            "security_id": "TW:2614",
            "group_id": "shipping.bulk",
            "review_status": "needs_role_review",
            "reason": (
                "Undated issuer text supports portside warehousing/handling and grain trading. "
                "It does not establish pure bulk-vessel operation or an effective historical interval; page may be stale."
            ),
            "evidence_refs": ["issuer-2614-1"],
        },
    ]
    packet = {
        "schema_version": "sector-classification-evidence.v1",
        "packet_id": "sector-role-evidence-20261002-batch01",
        "created_at": CREATED_AT,
        "base_catalog": {"schema_version": manifest["schema_version"], "manifest_canonical_sha256": BASE_SHA},
        "scope_profile_id": "sector-role-review-20261002.v1",
        "role_taxonomy": json.loads((ROOT / "research_core/sector_roles.v1.json").read_text(encoding="utf-8")),
        "scope": sorted(scope, key=lambda row: row["security_id"]),
        "sources": sources,
        "assertions": assertions,
        "membership_reviews": reviews,
        "limitations": [
            "Current/undated issuer pages are source observations, not verified current-business freshness or continuous historical roles.",
            "Report-year coverage is not a role-effective interval; every assertion has unknown effective dates.",
            "Roles/product labels are neither investment scores nor explanations of an episode's price movement.",
            "Original catalog memberships, wave winners, prices, and return measurements are unchanged.",
        ],
    }
    publish_packet(packet, TASK, CATALOG, ROOT / ".tmp")


if __name__ == "__main__":
    main()
