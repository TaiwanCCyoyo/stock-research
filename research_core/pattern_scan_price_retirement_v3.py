"""Two-stage owned-run retirement, with independently retained late evidence.

Publication is immutable. A later transition snapshots only the small equality
audit, binding it to that publication and the still-present prepared inventory.
Neither verification nor retries require the current shared-data generation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from research_core.artifact_store import canonical, file_digest, object_digest, publish_generated_bytes
from research_core.pattern_scan_receipt_io_v2 import read_scan_receipt
from research_core.pattern_scan_result_lifecycle_v3 import ACTIVE, POLICY, _run, _scratch_inventory
from research_core.research_data_catalog import DataCatalog, verify_entry
from research_core.research_data_paths import _artifact_name, _check_tree, _checked_path

LOGGER = logging.getLogger(__name__)
PROOF = "publication-handoff.json"
CLEANUP = "cleanup-receipt.json"
CLEANUP_PLAN = "cleanup-plan.json"
TRANSITION = "price-reader-transition.json"
PRICE_PLAN = "price-retirement-plan.json"
RETIRED = "price-retirement-receipt.json"
MAX_AUDIT_BYTES = 8_000_000


def _write(run: Path, name: str, value: dict[str, Any]) -> None:
    """Keep a failed metadata write outside both run inventory and final bundle."""
    path = run / name
    if path.exists():
        if read_scan_receipt(path) != value:
            raise ValueError(f"existing retirement identity differs: {path}")
        return
    scratch = run.parent / f".retirement-metadata-{uuid.uuid4().hex}"
    try:
        publish_generated_bytes(path, canonical(value), scratch=scratch)
    finally:
        # A partial write is diagnostic evidence, never automatically adopted or
        # recursively deleted. Successful transfers leave an empty directory.
        if scratch.is_dir() and not any(scratch.iterdir()):
            scratch.rmdir()


def _publication(run: Path, catalog: DataCatalog) -> dict[str, Any]:
    if (run / ACTIVE).exists():
        raise ValueError("cannot retire an actively executing scan")
    _check_tree(run)
    proof = read_scan_receipt(run / PROOF)
    if (
        proof.get("schema") != "pattern-scan-publication-handoff.v3"
        or proof.get("complete") is not True
        or proof.get("run_root") != str(run)
        or proof.get("retention_policy") != POLICY
    ):
        raise ValueError("verified formal publication and reference handoff required before cleanup")
    verify_entry(proof["entry"], catalog.roots)
    return proof


def _binding(run: Path, proof: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_root": str(run),
        "publication_handoff_sha256": file_digest(run / PROOF),
        "reference_source_id": proof["entry"]["inputs"]["source_id"],
        "reference_input_id": proof["entry"]["inputs"]["input_id"],
    }


def _matches(body: dict[str, Any], expected: dict[str, Any]) -> None:
    if not isinstance(body, dict) or canonical({key: body.get(key) for key in expected}) != canonical(expected):
        raise ValueError("retirement receipt publication/source/input/inventory binding differs")


def _prepared_inventory(run: Path, proof: dict[str, Any]) -> dict[str, Any]:
    prices = {name: info for name, info in proof["owned_scratch"].items() if name.startswith("prepared/")}
    result = {}
    for name, expected in prices.items():
        path = run / _artifact_name(name)
        if not path.is_file() or _scratch_inventory(run, [path])[name] != expected:
            raise ValueError("prepared price ownership changed before cleanup")
        result[name] = {**expected, "sha256": file_digest(path)}
    return result


def _check_inventory_identity(inventory: dict[str, Any], proof: dict[str, Any]) -> None:
    expected = {name: info for name, info in proof["owned_scratch"].items() if name.startswith("prepared/")}
    if set(inventory) != set(expected):
        raise ValueError("prepared inventory differs from publication handoff")
    for name, info in inventory.items():
        _artifact_name(name)
        if (
            {key: value for key, value in info.items() if key != "sha256"} != expected[name]
            or not isinstance(info.get("sha256"), str)
            or len(info["sha256"]) != 64
        ):
            raise ValueError("prepared inventory identity differs from owned prices")


def _cleanup(run: Path, proof: dict[str, Any]) -> dict[str, Any]:
    receipt = read_scan_receipt(run / CLEANUP)
    _matches(
        receipt,
        {
            **_binding(run, proof),
            "schema": "pattern-scan-cleanup.v3",
            "phase": "non_price_scratch",
            "complete": True,
            "entry": proof["entry"],
            "retention_policy": POLICY,
            "recovery_period_days": 0,
        },
    )
    inventory = receipt["prepared_inventory"]
    _check_inventory_identity(inventory, proof)
    _matches(receipt, {"prepared_inventory_sha256": object_digest(inventory), "prices_retained": bool(inventory)})
    return receipt


def _preflight(run: Path, inventory: dict[str, Any], envelopes: set[str], *, require_all: bool = False) -> list[Path]:
    """Validate the entire physical tree before the first destructive operation."""
    _check_tree(run)
    found = set()
    files = []
    for path in run.rglob("*"):
        if not path.is_file():
            continue
        name = path.relative_to(run).as_posix()
        if name in envelopes:
            continue
        expected = inventory.get(name)
        if expected is None:
            raise ValueError(f"unknown file ownership blocks cleanup: {path}")
        observed: dict[str, Any] = dict(_scratch_inventory(run, [path])[name])
        if "sha256" in expected:
            observed["sha256"] = file_digest(path)
        if observed != expected:
            raise ValueError(f"changed file ownership or contents blocks cleanup: {path}")
        found.add(name)
        files.append(path)
    if require_all and found != set(inventory):
        raise ValueError("registered prepared prices missing before retirement authorization")
    return files


def _prune_empty(run: Path) -> None:
    for path in sorted((path for path in run.rglob("*") if path.is_dir()), key=lambda path: len(path.parts), reverse=True):
        if not any(path.iterdir()):
            _checked_path(path).rmdir()


def _equivalence(packet: dict[str, Any], proof: dict[str, Any], cleanup: dict[str, Any]) -> None:
    _matches(
        packet,
        {
            "schema": "pattern-scan-price-reader-equivalence.v3",
            "complete": True,
            "reference_source_id": proof["entry"]["inputs"]["source_id"],
            "reference_input_id": proof["entry"]["inputs"]["input_id"],
            "calendar_n": 4110,
            "security_n": 1943,
            "cutoff": "2026-10-12",
            "all_columns_equal": True,
            "calendar_equal": True,
            "quality_equal": True,
            "mismatch_n": 0,
        },
    )
    optional = {
        "published_entry": proof["entry"],
        "prepared_inventory_sha256": cleanup["prepared_inventory_sha256"],
        "publication_handoff_sha256": cleanup["publication_handoff_sha256"],
    }
    _matches(packet, {key: value for key, value in optional.items() if key in packet})
    if not isinstance(packet.get("generation"), str) or not packet["generation"].strip():
        raise ValueError("shared-reader equivalence requires the tested generation")


def _transition(run: Path, proof: dict[str, Any], cleanup: dict[str, Any], descriptor: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _checked_path(run / TRANSITION)
    actual = {"path": str(path), "sha256": file_digest(path)}
    if descriptor is not None and descriptor != actual:
        raise ValueError("transition descriptor identity differs")
    body = read_scan_receipt(path)
    _matches(
        body,
        {
            **_binding(run, proof),
            "schema": "pattern-scan-price-reader-transition.v3",
            "complete": True,
            "published_entry": proof["entry"],
            "cleanup_receipt_sha256": file_digest(run / CLEANUP),
            "prepared_inventory_sha256": cleanup["prepared_inventory_sha256"],
            "owned_metadata": {},
        },
    )
    evidence = body["equivalence"]
    payload = evidence["contents"].encode("utf-8")
    if len(payload) > MAX_AUDIT_BYTES or len(payload) != evidence["bytes"] or hashlib.sha256(payload).hexdigest() != evidence["sha256"]:
        raise ValueError("equivalence snapshot identity differs")
    origin = Path(evidence["path"])
    if not origin.is_absolute() or origin.is_relative_to(run):
        raise ValueError("equivalence provenance must be outside the run")
    _equivalence(json.loads(payload), proof, cleanup)
    return actual, body


def _price_plan(run: Path, proof: dict[str, Any], cleanup: dict[str, Any], transition: dict[str, Any]) -> dict[str, Any]:
    return {
        **_binding(run, proof),
        "schema": "pattern-scan-price-retirement-plan.v3",
        "published_entry": proof["entry"],
        "transition": transition,
        "cleanup_receipt_sha256": file_digest(run / CLEANUP),
        "prepared_inventory_sha256": cleanup["prepared_inventory_sha256"],
        "retire_inventory": cleanup["prepared_inventory"],
    }


def _retirement(plan: dict[str, Any]) -> dict[str, Any]:
    inventory = plan["retire_inventory"]
    return {
        **{key: value for key, value in plan.items() if key not in {"schema", "retire_inventory"}},
        "schema": "pattern-scan-price-retirement.v3",
        "complete": True,
        "removed_files": len(inventory),
        "removed_bytes": sum(info["bytes"] for info in inventory.values()),
        "retention_policy": POLICY,
        "recovery_period_days": 0,
    }


def _cleanup_receipt(run: Path, proof: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    return {
        **_binding(run, proof),
        "schema": "pattern-scan-cleanup.v3",
        "phase": "non_price_scratch",
        "complete": True,
        "entry": proof["entry"],
        "prepared_inventory": plan["prepared_inventory"],
        "prepared_inventory_sha256": object_digest(plan["prepared_inventory"]),
        "prices_retained": bool(plan["prepared_inventory"]),
        "removed_files": len(plan["retire_inventory"]),
        "removed_bytes": sum(info["bytes"] for info in plan["retire_inventory"].values()),
        "retention_policy": POLICY,
        "recovery_period_days": 0,
    }


def _after_cleanup(run: Path, proof: dict[str, Any], cleanup: dict[str, Any]) -> list[Path]:
    """Read-only state verification, including interrupted phase-two deletions."""
    envelopes = {PROOF, CLEANUP}
    if (run / CLEANUP_PLAN).exists():
        pending = read_scan_receipt(run / CLEANUP_PLAN)
        _matches(pending, {**_binding(run, proof), "schema": "pattern-scan-cleanup-plan.v3", "entry": proof["entry"]})
        if _cleanup_receipt(run, proof, pending) != cleanup:
            raise ValueError("non-price retirement journal differs from cleanup receipt")
        envelopes.add(CLEANUP_PLAN)
    plan = None
    if (run / TRANSITION).exists():
        descriptor, _ = _transition(run, proof, cleanup)
        envelopes.add(TRANSITION)
        plan = _price_plan(run, proof, cleanup, descriptor)
    for name in (PRICE_PLAN, RETIRED):
        if (run / name).exists():
            if plan is None or read_scan_receipt(run / name) != (plan if name == PRICE_PLAN else _retirement(plan)):
                raise ValueError("price retirement journal differs from transition")
            envelopes.add(name)
    retired = RETIRED in envelopes
    files = _preflight(run, cleanup["prepared_inventory"], envelopes, require_all=PRICE_PLAN not in envelopes and not retired)
    if retired and files:
        raise ValueError("completed retirement still has prepared prices")
    return files


def cleanup_non_price_scratch(run: Path, catalog: DataCatalog) -> dict[str, Any]:
    """Phase one may complete before a shared-reader equality audit exists."""
    run = _run(run)
    proof = _publication(run, catalog)
    if (run / CLEANUP).exists():
        receipt = _cleanup(run, proof)
        _after_cleanup(run, proof, receipt)
        if (run / CLEANUP_PLAN).exists():
            (run / CLEANUP_PLAN).unlink()
        return receipt
    plan_path = run / CLEANUP_PLAN
    resuming = plan_path.exists()
    files: list[Path] = []
    if resuming:
        plan = read_scan_receipt(plan_path)
        _matches(plan, {**_binding(run, proof), "schema": "pattern-scan-cleanup-plan.v3", "entry": proof["entry"]})
        _check_inventory_identity(plan["prepared_inventory"], proof)
        if any(name.startswith("prepared/") or info != proof["owned_scratch"].get(name) for name, info in plan["retire_inventory"].items()):
            raise ValueError("non-price retirement plan ownership differs")
    else:
        files = _preflight(run, proof["owned_scratch"], {PROOF})
        plan = {
            **_binding(run, proof),
            "schema": "pattern-scan-cleanup-plan.v3",
            "entry": proof["entry"],
            "prepared_inventory": _prepared_inventory(run, proof),
            "retire_inventory": _scratch_inventory(run, [path for path in files if not path.is_relative_to(run / "prepared")]),
        }
        _write(run, CLEANUP_PLAN, plan)
    # Price files are mandatory in phase one even while resuming scratch deletion.
    if resuming:
        inventory = {**plan["retire_inventory"], **plan["prepared_inventory"]}
        files = _preflight(run, inventory, {PROOF, CLEANUP_PLAN})
    if any(not (run / name).is_file() for name in plan["prepared_inventory"]):
        raise ValueError("prepared prices must remain throughout phase-one cleanup")
    for path in files:
        if path.relative_to(run).as_posix() in plan["retire_inventory"]:
            _checked_path(path).unlink()
    _prune_empty(run)
    receipt = _cleanup_receipt(run, proof, plan)
    _write(run, CLEANUP, receipt)
    plan_path.unlink()
    LOGGER.info(
        "Retired non-price scratch files=%d bytes=%d; prepared prices retained=%s",
        receipt["removed_files"],
        receipt["removed_bytes"],
        receipt["prices_retained"],
    )
    return receipt


def record_transition(run: Path, catalog: DataCatalog, *, equivalence: Path) -> dict[str, Any]:
    """Snapshot a small external audit; never copy prices or edit publication."""
    run = _run(run)
    proof = _publication(run, catalog)
    cleanup = _cleanup(run, proof)
    _after_cleanup(run, proof, cleanup)
    return _record_evidence(run, proof, cleanup, equivalence)


def _record_evidence(run: Path, proof: dict[str, Any], cleanup: dict[str, Any], equivalence: Path) -> dict[str, Any]:
    """The caller holds the already verified publication and run inventory."""
    if not equivalence.is_absolute() or equivalence.is_relative_to(run):
        raise ValueError("explicit external equivalence evidence required")
    equivalence = _checked_path(equivalence)
    with equivalence.open("rb") as stream:
        payload = stream.read(MAX_AUDIT_BYTES + 1)
    if len(payload) > MAX_AUDIT_BYTES:
        raise ValueError("equivalence evidence exceeds small metadata budget")
    try:
        _equivalence(json.loads(payload), proof, cleanup)
    except ValueError as error:
        raise ValueError("shared-reader equivalence does not authorize prepared-price retirement") from error
    body = {
        **_binding(run, proof),
        "schema": "pattern-scan-price-reader-transition.v3",
        "complete": True,
        "published_entry": proof["entry"],
        "cleanup_receipt_sha256": file_digest(run / CLEANUP),
        "prepared_inventory_sha256": cleanup["prepared_inventory_sha256"],
        "equivalence": {"path": str(equivalence), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "contents": payload.decode("utf-8")},
        "owned_metadata": {},
    }
    _write(run, TRANSITION, body)
    descriptor, _ = _transition(run, proof, cleanup)
    LOGGER.info("Recorded late price-reader transition version=%s generation=%s", proof["entry"]["version_id"], json.loads(payload)["generation"])
    return descriptor


def retire_prices(run: Path, catalog: DataCatalog, *, transition: dict[str, Any] | None = None) -> dict[str, Any]:
    """Phase two: explicitly retire only prices bound to verified equality."""
    run = _run(run)
    proof = _publication(run, catalog)
    cleanup = _cleanup(run, proof)
    files = _after_cleanup(run, proof, cleanup)
    if not (run / TRANSITION).exists():
        pin = proof["entry"]["manifest"]
        final = catalog.roots.artifact_path(pin["scope"], pin["path"]).parent
        evidence = final / "audits/price-reader-equivalence.json"
        if transition is not None or not evidence.is_file():
            raise ValueError("prepared prices require shared-reader equivalence before retirement")
        transition = _record_evidence(run, proof, cleanup, evidence)
    descriptor, _ = _transition(run, proof, cleanup, transition)
    plan = _price_plan(run, proof, cleanup, descriptor)
    receipt = _retirement(plan)
    if (run / RETIRED).exists():
        return receipt
    # Freeze authorization before any unlink. Missing prices are accepted only
    # when this exact plan already exists, making interrupted deletion retryable.
    _write(run, PRICE_PLAN, plan)
    for path in files:
        _checked_path(path).unlink()
    _prune_empty(run)
    _write(run, RETIRED, receipt)
    LOGGER.info("Retired prepared prices files=%d bytes=%d", receipt["removed_files"], receipt["removed_bytes"])
    return receipt


def verify_status(run: Path, catalog: DataCatalog) -> dict[str, Any]:
    """Return publication/price state without any write, cleanup or live reader."""
    run = _run(run)
    proof = _publication(run, catalog)
    receipt = read_scan_receipt(run / CLEANUP)
    if "phase" not in receipt:
        # Existing all-at-once receipts keep their historical interpretation.
        _matches(receipt, {"schema": "pattern-scan-cleanup.v3", "complete": True, "run_root": str(run), "entry": proof["entry"]})
        _preflight(run, {}, {PROOF, CLEANUP})
        return {"entry": proof["entry"], "prices_retained": False}
    cleanup = _cleanup(run, proof)
    return {"entry": proof["entry"], "prices_retained": bool(_after_cleanup(run, proof, cleanup))}
