"""Results-only handoff and immediate retirement of an owned scan's scratch.

Computation can finish without choosing a permanent catalog location. No cleanup
is possible until a supplied catalog destination, completed audits and report
have been verified. Historical receipts describe consumed ancestors; retained
results are verified independently of retired prices and expanded event tables.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from research_core.artifact_store import describe_file, file_digest, relocate_noreplace
from research_core.pattern_scan_receipt_io_v2 import publish_scan_receipt, read_scan_receipt
from research_core.research_data_catalog import DataCatalog, verify_entry
from research_core.research_data_file_bundle_v1 import publish_staged_bundle
from research_core.research_data_paths import _artifact_name, _check_tree, _checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample

LOGGER = logging.getLogger(__name__)
POLICY = "aggregates-audits.v3"
ACTIVE = ".scan-active.json"


def _run(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("explicit absolute scan run required")
    path = _checked_path(path)
    if (
        not path.is_absolute()
        or path.parent.name != "pattern-scan-execution"
        or path.parent.parent.name != ".tmp"
        or not (path.parent.parent.parent / ".git").is_dir()
        or not path.is_dir()
    ):
        raise ValueError("explicit primary task-owned scan run required")
    _artifact_name(path.name)
    return path


def _retain(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        if read_scan_receipt(path) != value:
            raise ValueError(f"existing handoff identity differs: {path}")
    else:
        publish_scan_receipt(path, value)


def _descriptor(name: str, path: Path, run: Path) -> dict[str, Any]:
    _artifact_name(name)
    if name in {"manifest.json", "run-receipt.json"}:
        raise ValueError("retained envelope names are reserved")
    path = _checked_path(path)
    if not path.is_file():
        raise ValueError(f"retained result missing: {path}")
    record = {**describe_file(path.parent, path), "path": name, "source_path": str(path)}
    if path.is_relative_to(run):
        record["storage"] = "owned"
        if path.suffix == ".parquet":
            footer = pq.ParquetFile(path).metadata
            record["rows"] = footer.num_rows
            record["compression"] = sorted({footer.row_group(i).column(j).compression for i in range(footer.num_row_groups) for j in range(footer.num_columns)})
    elif name.startswith("execution/") and path.suffix == ".json" and path.is_relative_to(run.parent):
        # Small provenance records may belong to an older, retained profile.
        # Snapshot their text, never move or copy another run's price payload.
        record.update(storage="metadata_snapshot", contents=path.read_bytes().decode("utf-8"))
    else:
        raise ValueError("retained payload outside owned run; only explicit sibling-run JSON provenance is allowed")
    return record


def record_computed_results(
    run: Path,
    files: dict[str, Path],
    *,
    source: dict[str, Any],
    input_id: str,
    provenance: dict[str, Any],
    transient_files: Iterable[Path] = (),
) -> dict[str, Any]:
    """Record completed aggregates/audits without publication, copying or cleanup."""
    run = _run(run)
    before = resource_sample()
    if not files:
        raise ValueError("explicit retained results required")
    records = [_descriptor(name, path, run) for name, path in sorted(files.items())]
    if len({row["path"].casefold() for row in records}) != len(records):
        raise ValueError("retained result name collision")
    body = {
        "schema": "pattern-scan-computed-results.v3",
        "complete": True,
        "state": "computed_unpublished",
        "retention_policy": POLICY,
        "run_root": str(run),
        "source": source,
        "input_id": input_id,
        "provenance": provenance,
        "artifacts": records,
        "payload_bytes": sum(row["bytes"] for row in records),
        "permanent_location": None,
        "owned_scratch": _scratch_inventory(run, transient_files),
    }
    index = run / "computed-results.json"
    _retain(index, body)
    LOGGER.info("Recorded computed retained results files=%d bytes=%d; publication pending", len(records), body["payload_bytes"])
    return {
        "path": str(index),
        "sha256": file_digest(index),
        "payload_bytes": body["payload_bytes"],
        "measurement": phase_receipt("retained_result_inventory", before, resource_sample()),
    }


def _scratch_inventory(run: Path, files: Iterable[Path]) -> dict[str, dict[str, int]]:
    """Capture an explicit caller-owned inventory; directories grant no authority."""
    inventory = {}
    for path in files:
        path = _checked_path(path)
        if not path.is_relative_to(run) or not path.is_file():
            raise ValueError("scratch inventory must contain explicit owned files in this run")
        stat = path.stat()
        inventory[path.relative_to(run).as_posix()] = {
            "bytes": stat.st_size,
            "device": stat.st_dev,
            "inode": stat.st_ino,
            "mtime_ns": stat.st_mtime_ns,
        }
    return inventory


def verify_computed_results(descriptor: dict[str, Any]) -> dict[str, Any]:
    path = _checked_path(Path(descriptor["path"]))
    if file_digest(path) != descriptor["sha256"]:
        raise ValueError("computed result index identity changed")
    body = read_scan_receipt(path)
    run = _run(Path(body["run_root"]))
    if path != run / "computed-results.json" or body.get("schema") != "pattern-scan-computed-results.v3" or body.get("retention_policy") != POLICY:
        raise ValueError("invalid computed result envelope")
    for row in body["artifacts"]:
        if row["storage"] == "metadata_snapshot":
            import hashlib

            payload = row["contents"].encode("utf-8")
            valid = len(payload) == row["bytes"] and hashlib.sha256(payload).hexdigest() == row["sha256"]
        else:
            source = _checked_path(Path(row["source_path"]))
            valid = source.is_relative_to(run) and source.is_file() and source.stat().st_size == row["bytes"] and file_digest(source) == row["sha256"]
        if not valid:
            raise ValueError(f"retained result changed: {row['path']}")
    return body


def handoff_results(
    descriptor: dict[str, Any],
    catalog: DataCatalog,
    metadata: dict[str, Any],
    *,
    managed_parent: str,
    verification: Path,
    report: Path,
    audit_files: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Journal a no-copy move, sibling publication and result-reference handoff.

    A caller supplies the eventual managed catalog location. This never chooses
    a root, adds a legacy research_cache version, or reads current producer data.
    A crash after an individual move or final rename resumes the same journal.
    """
    index = _checked_path(Path(descriptor["path"]))
    run = _run(index.parent)
    if index != run / "computed-results.json" or file_digest(index) != descriptor["sha256"]:
        raise ValueError("computed result index identity changed")
    if (run / ACTIVE).exists():
        raise ValueError("cannot hand off an actively executing scan")
    before = resource_sample()
    plan_path, ready_path, done_path = (run / name for name in ("handoff-plan.json", "publication-ready.json", "publication-handoff.json"))
    parent = catalog.roots.artifact_path("data", managed_parent)
    parent.mkdir(parents=True, exist_ok=True)
    stage = parent / f".staging-scan-{descriptor['sha256']}"
    if plan_path.exists():
        plan = read_scan_receipt(plan_path)
        if plan["index"] != descriptor or plan["computed"] != read_scan_receipt(index) or plan["metadata"] != metadata or plan["managed_parent"] != str(parent):
            raise ValueError("handoff retry parameters differ")
    else:
        body = verify_computed_results(descriptor)
        if metadata.get("inputs", {}).get("source_id") != body["source"]["source_id"] or metadata.get("inputs", {}).get("input_id") != body["input_id"]:
            raise ValueError("publication metadata source/input differs from computed results")
        packet = read_scan_receipt(_checked_path(verification))
        if (
            packet.get("schema") != "pattern-scan-delivery-verification.v3"
            or packet.get("source_id") != body["source"]["source_id"]
            or packet.get("input_id") != body["input_id"]
            or packet.get("complete") is not True
            or packet.get("event_audit_n") != 10
            or packet.get("candidate_audit_n") != 5
            or packet.get("candidate_comparison_rows") != 54_720
            or packet.get("mismatch_n") != 0
        ):
            raise ValueError("completed ten-event/five-candidate verification is required before handoff")
        extra = {"report.md": report, "audits/delivery-verification.json": verification, **(audit_files or {})}
        if any(not name.startswith("audits/") for name in (audit_files or {})):
            raise ValueError("additional retained files must be explicit audit results")
        records = [*body["artifacts"], *(_descriptor(name, path, run) for name, path in sorted(extra.items()))]
        if len({row["path"].casefold() for row in records}) != len(records):
            raise ValueError("handoff name collision")
        if len({row["source_path"].casefold() for row in records}) != len(records):
            raise ValueError("handoff physical source collision")
        # Only named coordinator envelopes can appear after computed capture.
        # Additional reports/audits are explicit arguments, never whole folders.
        envelopes = [
            run / name
            for mode in ("prepare", "stock", "all")
            for name in (
                f"request-{mode}.json",
                f"response-{mode}.json",
                f"response-{mode}.job-memory.json",
                f"phase-{mode}-result.json",
                f"run-{mode}-receipt.json",
            )
            if (run / name).is_file()
        ]
        owned = {**body["owned_scratch"], **_scratch_inventory(run, [*envelopes, index, *extra.values()])}
        plan = {
            "schema": "pattern-scan-handoff-plan.v3",
            "index": descriptor,
            "metadata": metadata,
            "managed_parent": str(parent),
            "stage": str(stage),
            "computed": body,
            "artifacts": records,
            "owned_scratch": owned,
        }
        _retain(plan_path, plan)
    if not ready_path.exists():
        stage.mkdir(exist_ok=True)
        for row in plan["artifacts"]:
            target = _checked_path(stage / _artifact_name(row["path"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                if row["storage"] == "metadata_snapshot":
                    with target.open("xb") as stream:
                        stream.write(row["contents"].encode("utf-8"))
                else:
                    source = _checked_path(Path(row["source_path"]))
                    if not source.is_relative_to(run) or file_digest(source) != row["sha256"]:
                        raise ValueError("handoff source differs from owned retained inventory")
                    relocate_noreplace(source, target)
            if target.stat().st_size != row["bytes"] or file_digest(target) != row["sha256"]:
                raise ValueError("handoff target differs from retained result")
        receipt = {
            "schema": "pattern-scan-result-receipt.v3",
            "complete": True,
            "retention_policy": POLICY,
            "code": plan["computed"]["source"]["code"],
            "source": plan["computed"]["source"],
            "input_id": plan["computed"]["input_id"],
            "provenance": plan["computed"]["provenance"],
            "results": {row["path"]: {key: row[key] for key in ("path", "bytes", "sha256")} for row in plan["artifacts"]},
            "transient_ancestors": "consumed; retired only after verified publication and reference handoff",
        }
        _retain(stage / "run-receipt.json", receipt)
    ready = read_scan_receipt(ready_path) if ready_path.exists() else None
    if stage.exists():
        location = stage
    elif ready is not None:
        location = catalog.roots.artifact_path("data", str(Path(ready["entry"]["manifest"]["path"]).parent).replace("\\", "/"))
    else:
        raise ValueError("handoff staging and publication journal are both missing")

    def before_publish(entry: dict[str, Any]) -> None:
        _retain(ready_path, {"entry": entry, "stage": str(stage), "computed_index_sha256": descriptor["sha256"]})

    entry = publish_staged_bundle(catalog, metadata, location, managed_parent=managed_parent, before_publish=before_publish)
    ready = read_scan_receipt(ready_path)
    if entry != ready["entry"]:
        raise ValueError("published result differs from planned reference handoff")
    proof = {
        "schema": "pattern-scan-publication-handoff.v3",
        "complete": True,
        "computed_index_sha256": descriptor["sha256"],
        "entry": entry,
        "run_root": str(run),
        "retention_policy": POLICY,
        "owned_scratch": {**plan["owned_scratch"], **_scratch_inventory(run, [plan_path, ready_path])},
    }
    _retain(done_path, proof)
    LOGGER.info("Completed result reference handoff version=%s", entry["version_id"])
    return {**proof, "measurement": phase_receipt("single_copy_result_handoff", before, resource_sample())}


def cleanup_run(run: Path, catalog: DataCatalog) -> dict[str, Any]:
    """Immediately remove only this run after verifying final results and handoff."""
    run = _run(run)
    if (run / ACTIVE).exists():
        raise ValueError("cannot clean an actively executing scan")
    proof_path, cleanup_path = run / "publication-handoff.json", run / "cleanup-receipt.json"
    proof = read_scan_receipt(proof_path)
    if (
        proof.get("schema") != "pattern-scan-publication-handoff.v3"
        or proof.get("complete") is not True
        or proof.get("run_root") != str(run)
        or proof.get("retention_policy") != POLICY
    ):
        raise ValueError("verified formal publication and reference handoff required before cleanup")
    manifest = verify_entry(proof["entry"], catalog.roots)
    if (run / "prepared").exists():
        name = "audits/price-reader-equivalence.json"
        if name not in {row["path"] for row in manifest["artifacts"]}:
            raise ValueError("prepared prices require retained shared-reader equivalence before retirement")
        pin = proof["entry"]["manifest"]
        final = catalog.roots.artifact_path(pin["scope"], pin["path"]).parent
        equality = read_scan_receipt(final / name)
        if (
            equality.get("schema") != "pattern-scan-price-reader-equivalence.v3"
            or equality.get("complete") is not True
            or equality.get("reference_source_id") != proof["entry"]["inputs"]["source_id"]
            or equality.get("reference_input_id") != proof["entry"]["inputs"]["input_id"]
            or equality.get("calendar_n") != 4110
            or equality.get("security_n") != 1943
            or equality.get("cutoff") != "2026-10-12"
            or equality.get("all_columns_equal") is not True
            or equality.get("calendar_equal") is not True
            or equality.get("quality_equal") is not True
            or equality.get("mismatch_n") != 0
            or not isinstance(equality.get("generation"), str)
            or not equality["generation"].strip()
        ):
            raise ValueError("shared-reader equivalence does not authorize prepared-price retirement")
    _check_tree(run)
    retained = {proof_path, cleanup_path}
    files = [path for path in run.rglob("*") if path.is_file() and path not in retained]
    for path in files:
        name = path.relative_to(run).as_posix()
        expected = proof.get("owned_scratch", {}).get(name)
        if expected is None or _scratch_inventory(run, [path])[name] != expected:
            raise ValueError(f"unknown file ownership blocks cleanup: {path}")
    removed_bytes = sum(path.stat().st_size for path in files)
    for path in files:
        _checked_path(path).unlink()
    for path in sorted((path for path in run.rglob("*") if path.is_dir()), key=lambda path: len(path.parts), reverse=True):
        path.rmdir()
    receipt = {
        "schema": "pattern-scan-cleanup.v3",
        "complete": True,
        "run_root": str(run),
        "entry": proof["entry"],
        "removed_files": len(files),
        "removed_bytes": removed_bytes,
        "retention_policy": POLICY,
        "recovery_period_days": 0,
    }
    if not cleanup_path.exists():
        _retain(cleanup_path, receipt)
    else:
        receipt = read_scan_receipt(cleanup_path)
    LOGGER.info("Retired owned scan scratch files=%d bytes=%d", len(files), removed_bytes)
    return receipt
