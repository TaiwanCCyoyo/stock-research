"""Regressions for issuer annotation assembly without any price/cache access."""

from __future__ import annotations

import json
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from research_core.sector_role_evidence import SectorRoleEvidenceError, validate_packet
from scripts.tests.test_sector_role_evidence import catalog, packet
from scripts.tests.test_sector_role_evidence import scope_registry as scope_registry

builder = import_module("tasks.20261002-sector-role-evidence.build_packet")
REPO_ROOT = Path(__file__).resolve().parents[2]
SUBPROCESS_PUBLISH = """
import json
import sys
from importlib import import_module
from pathlib import Path

import research_core.sector_role_evidence as evidence

packet_path, task_dir, catalog_dir, scratch_dir, registry_path = map(Path, sys.argv[1:])
evidence.SCOPE_REGISTRY_PATH = registry_path
builder = import_module("tasks.20261002-sector-role-evidence.build_packet")
try:
    builder.publish_packet(json.loads(packet_path.read_text(encoding="utf-8")), task_dir, catalog_dir, scratch_dir)
except RuntimeError as error:
    print(error)
    raise SystemExit(0 if "publication lock" in str(error) else 2)
raise SystemExit(3)
"""


def security(code: str, groups: list[str], status: str) -> dict[str, Any]:
    return {"code": code, "security_id": f"TW:{code}", "group_ids": groups, "coverage_status": status, "official_industry": "known"}


def test_unclassified_episode_and_outside_seed_survive_review_queue() -> None:
    rows = [security("X", [], "source_missing"), security("Y", [], "source_missing"), security("3189", ["official:D000"], "official_only")]
    queue = builder.review_scope(rows, {"TW:X"}, {"TW:3189"})
    by_id = {row["security_id"]: row for row in queue}
    assert set(by_id) == {"TW:X", "TW:3189"}
    assert by_id["TW:X"]["official_industry"] == "known"
    assert by_id["TW:X"]["group_ids"] == []
    assert by_id["TW:X"]["review_status"] == "pending"
    assert by_id["TW:X"]["unknown_reason"]
    assert by_id["TW:3189"]["review_status"] == "source_verified"


def test_diversified_issuer_does_not_spread_products_to_every_role() -> None:
    assert builder.role_products("2421", "fan-manufacturer", {"fan", "liquid-cooling"}) == ["fan"]
    assert builder.role_products("8046", "ic-substrate-manufacturer", {"pcb"}) == []
    assert builder.role_products("5381", "transformer-manufacturer", {"pcb-drilling-materials", "distribution-transformer"}) == ["distribution-transformer"]


def test_role_sources_exclude_unrelated_sources_and_keep_product_only_evidence() -> None:
    sources = [
        {"evidence_id": "factory", "supported_role_ids": ["pcb-manufacturer"], "supported_products_by_role": {"pcb-manufacturer": ["pcb"]}},
        {
            "evidence_id": "report",
            "supported_role_ids": ["pcb-manufacturer", "ic-substrate-manufacturer"],
            "supported_products_by_role": {"pcb-manufacturer": ["pcb"]},
        },
        {"evidence_id": "products", "supported_role_ids": [], "supported_products_by_role": {"memory-chip-manufacturer": ["dram"]}},
    ]
    assert builder.role_evidence_refs("ic-substrate-manufacturer", [], sources) == ["report"]
    assert builder.role_evidence_refs("pcb-manufacturer", ["pcb"], sources) == ["factory", "report"]
    assert builder.role_evidence_refs("memory-chip-manufacturer", ["dram"], sources) == ["products"]


def test_reviewed_source_products_preserve_diversified_and_product_only_context() -> None:
    assert builder.source_products_by_role(
        "5381", ["electronic-material-supplier", "transformer-manufacturer"], ["pcb-drilling-materials", "distribution-transformer"]
    ) == {
        "electronic-material-supplier": ["pcb-drilling-materials"],
        "transformer-manufacturer": ["distribution-transformer"],
    }
    assert builder.source_products_by_role("2344", [], ["dram"]) == {"memory-chip-manufacturer": ["dram"]}


def test_role_product_mapping_requires_reviewed_issuer_role_pairs() -> None:
    with pytest.raises(ValueError, match="unreviewed issuer-role product mapping"):
        builder.source_products_by_role("unknown", ["first-role", "second-role"], ["first-tag", "second-tag"])
    with pytest.raises(ValueError, match="unreviewed issuer-role product mapping"):
        builder.role_products("5381", "unreviewed-role", {"pcb-drilling-materials"})
    assert builder.source_products_by_role("5381", ["electronic-material-supplier", "transformer-manufacturer"], ["pcb-drilling-materials"]) == {
        "electronic-material-supplier": ["pcb-drilling-materials"],
        "transformer-manufacturer": [],
    }


def _candidate(catalog_dir: Path, packet_id: str) -> dict[str, Any]:
    value = json.loads(json.dumps(packet(catalog_dir)))
    value["packet_id"] = packet_id
    return value


def _published_paths(task_dir: Path) -> tuple[Path, Path]:
    return task_dir / "evidence-v1.json", task_dir / "completion-receipt.json"


def _publish_existing_pair(tmp_path: Path) -> tuple[Path, Path, Path, Path, bytes, bytes]:
    catalog_dir = catalog(tmp_path)
    task_dir = tmp_path / "task"
    scratch_dir = tmp_path / "scratch"
    task_dir.mkdir()
    builder.publish_packet(_candidate(catalog_dir, "first"), task_dir, catalog_dir, scratch_dir)
    packet_path, receipt_path = _published_paths(task_dir)
    validate_packet(packet_path, catalog_dir, receipt_path)
    return catalog_dir, task_dir, scratch_dir, packet_path, packet_path.read_bytes(), receipt_path.read_bytes()


def test_publish_refuses_corrupt_catalog_without_overwriting_existing_pair(tmp_path: Path) -> None:
    catalog_dir, task_dir, scratch_dir, packet_path, original_packet, original_receipt = _publish_existing_pair(tmp_path)
    _, receipt_path = _published_paths(task_dir)
    (catalog_dir / "chunks" / "other-0001.json.gz").write_bytes(b"corrupt catalog chunk")

    with pytest.raises(SectorRoleEvidenceError):
        builder.publish_packet(_candidate(catalog_dir, "second"), task_dir, catalog_dir, scratch_dir)

    assert packet_path.read_bytes() == original_packet
    assert receipt_path.read_bytes() == original_receipt


def test_publish_rolls_back_packet_when_receipt_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog_dir, task_dir, scratch_dir, packet_path, original_packet, original_receipt = _publish_existing_pair(tmp_path)
    _, receipt_path = _published_paths(task_dir)
    real_replace = builder.os.replace
    calls = 0

    def fail_receipt_replace(source: str | Path, target: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("receipt replacement failed")
        real_replace(source, target)

    monkeypatch.setattr(builder.os, "replace", fail_receipt_replace)
    with pytest.raises(OSError, match="receipt replacement failed"):
        builder.publish_packet(_candidate(catalog_dir, "second"), task_dir, catalog_dir, scratch_dir)

    assert packet_path.read_bytes() == original_packet
    assert receipt_path.read_bytes() == original_receipt
    builder.publish_packet(_candidate(catalog_dir, "third"), task_dir, catalog_dir, scratch_dir)
    assert json.loads(packet_path.read_text(encoding="utf-8"))["packet_id"] == "third"
    validate_packet(packet_path, catalog_dir, receipt_path)
    assert not (task_dir / ".sector-role-publication.lock").exists()


def test_publish_retains_recovery_backups_when_rollback_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog_dir, task_dir, scratch_dir, _, original_packet, original_receipt = _publish_existing_pair(tmp_path)
    real_replace = builder.os.replace
    calls = 0

    def fail_receipt_and_rollback(source: str | Path, target: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise OSError("replace and rollback failed")
        real_replace(source, target)

    monkeypatch.setattr(builder.os, "replace", fail_receipt_and_rollback)
    with pytest.raises(OSError, match="replace and rollback failed"):
        builder.publish_packet(_candidate(catalog_dir, "second"), task_dir, catalog_dir, scratch_dir)

    recovery_dirs = list(scratch_dir.glob("role-packet-*"))
    assert len(recovery_dirs) == 1
    assert (recovery_dirs[0] / "old-packet.json").read_bytes() == original_packet
    assert (recovery_dirs[0] / "old-receipt.json").read_bytes() == original_receipt


def test_publish_rejects_concurrent_publisher_while_replacing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog_dir = catalog(tmp_path)
    task_dir = tmp_path / "task"
    scratch_dir = tmp_path / "scratch"
    task_dir.mkdir()
    second_path = tmp_path / "second-packet.json"
    second_path.write_text(json.dumps(_candidate(catalog_dir, "second")), encoding="utf-8")
    validate_packet(second_path, catalog_dir)
    real_replace = builder.os.replace
    second_result: subprocess.CompletedProcess[str] | None = None

    def start_second_publisher(source: str | Path, target: str | Path) -> None:
        nonlocal second_result
        if second_result is None:
            second_result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    SUBPROCESS_PUBLISH,
                    str(second_path),
                    str(task_dir),
                    str(catalog_dir),
                    str(scratch_dir),
                    str(tmp_path / "scope-registry.json"),
                ],
                capture_output=True,
                check=False,
                cwd=REPO_ROOT,
                text=True,
                timeout=10,
            )
        real_replace(source, target)

    monkeypatch.setattr(builder.os, "replace", start_second_publisher)
    builder.publish_packet(_candidate(catalog_dir, "first"), task_dir, catalog_dir, scratch_dir)

    assert second_result is not None
    assert second_result.returncode == 0, second_result.stderr
    assert "publication lock" in second_result.stdout
    packet_path, receipt_path = _published_paths(task_dir)
    assert json.loads(packet_path.read_text(encoding="utf-8"))["packet_id"] == "first"
    validate_packet(packet_path, catalog_dir, receipt_path)
    assert not (task_dir / ".sector-role-publication.lock").exists()
