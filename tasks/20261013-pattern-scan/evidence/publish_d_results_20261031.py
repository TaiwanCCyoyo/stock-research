"""Publish retained PR17 final bytes; never calculate research or clean inputs.

Run with PYTHONPATH set to this checkout. Absolute paths inside original receipts
are historical provenance; ZIP member paths resolve their result-name keys.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pyarrow.parquet as pq

from research_core.artifact_store import canonical, publish_new_directory, relative_name, safe_path
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_parquet_v1 import METADATA_KEY
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_file_bundle_v1 import publish_staged_bundle
from research_core.research_data_paths import DataRoots, checked_path

LOGGER = logging.getLogger(__name__)
TASK = "20261013-pattern-scan"
PARENT = f"tasks/{TASK}/d-results-v1"
SOURCE = "a3cfc677ef01547132ce5f3e5cd2a514201fecc02d65f4fa87aeb6fc69cc7ea4"  # pragma: allowlist secret
INPUT = "5c48eb999a81e42149c858331a601aff700a63af3c7f2fb8d642bf20b1370c05"  # pragma: allowlist secret
PHASES = ("conditions", "q4", "followup")
FOLLOWUP = {
    f"{name}.parquet"
    for name in (
        "exclusions",
        "first_flag_by_outcome",
        "first_flag_summary",
        "flag_summary",
        "holding_by_outcome",
        "landmark_summary",
        "path_by_outcome",
        "path_summary",
        "tradeoff_points",
    )
}
Q4 = {f"{name}.parquet" for name in ("admission-counts", "coverage", "draws", "examples", "quotas", "timing")}


def contained(root: Path, name: str) -> Path:
    """Reject aliases, traversal, missing files and physical hardlinks."""
    path = checked_path(root / relative_name(name))
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"not a contained regular file: {name}")
    return path


def load_receipt(root: Path, family: str, phase: str | None) -> tuple[Path, dict[str, Any]]:
    directory = root / family / phase if phase else root / family
    path = contained(root, path_name := f"{family}/{phase}/run-receipt.json" if phase else f"{family}/{family}-receipt.json")
    receipt = json.loads(path.read_bytes())
    parameters = receipt.get("parameters", {})
    definition = "pattern-scan-local-remaining.v5" if phase else "pattern-scan-local-q1.v1"
    if receipt.get("schema") != "run-receipt.v1" or receipt.get("definition") != definition or parameters.get("target") != family:
        raise ValueError(f"wrong receipt identity: {path_name}")
    source = parameters.get("original_source_id") if phase else parameters.get("numerical_source", {}).get("source_id")
    input_id = parameters.get("original_input_id") if phase else parameters.get("input_id")
    if (source, input_id) != (SOURCE, INPUT):
        raise ValueError(f"wrong source/input: {path_name}")
    if phase and (parameters.get("phase") != phase or parameters.get("cutoff") != "2026-10-12" or parameters.get("horizons") != [126, 252]):
        raise ValueError(f"wrong phase/cutoff/horizons: {path_name}")
    code = receipt.get("code", {})
    if not re.fullmatch(r"[0-9a-f]{40}", str(code.get("commit"))) or code.get("dirty") is not False:
        raise ValueError(f"missing executor provenance: {path_name}")
    results = receipt.get("results")
    if not isinstance(results, dict) or not results:
        raise ValueError(f"missing final inventory: {path_name}")
    exact = Q4 if phase == "q4" else FOLLOWUP if phase == "followup" else {f"{family}-summary.parquet", f"{family}-annual.parquet"} if phase is None else None
    if exact is not None and set(results) != exact:
        raise ValueError(f"unexpected final names: {path_name}")
    for name, descriptor in results.items():
        relative_name(name)
        if phase == "conditions" and name not in {f"{family}-selection.json", "top-candidates.json"}:
            if not re.fullmatch(rf"[^/]+-h(?:126|252)/{family}-[^/]+-(?:summary|annual|candidate-coverage)\.parquet", name):
                raise ValueError(f"unexpected conditions final: {name}")
        if (
            not isinstance(descriptor, dict)
            or type(descriptor.get("bytes")) is not int
            or descriptor["bytes"] < 0
            or not re.fullmatch(r"[0-9a-f]{64}", str(descriptor.get("sha256")))
        ):
            raise ValueError(f"invalid final descriptor: {name}")
        contained(directory, name)
    return path, receipt


def stream_member(archive: ZipFile, source: Path, name: str, expected: dict[str, Any] | None) -> dict[str, Any]:
    """Hash final results once while copying; provenance bytes receive no new pin."""
    info = ZipInfo(relative_name(name), date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    digest = hashlib.sha256() if expected is not None else None
    size = 0
    with source.open("rb") as reader, archive.open(info, "w", force_zip64=True) as writer:
        while chunk := reader.read(1024 * 1024):
            writer.write(chunk)
            size += len(chunk)
            if digest is not None:
                digest.update(chunk)
    row: dict[str, Any] = {"path": name, "bytes": size, "source_path": str(source)}
    if expected is not None:
        if size != expected["bytes"] or digest is None or digest.hexdigest() != expected["sha256"]:
            raise ValueError(f"saved final identity mismatch: {name}")
        row["sha256"] = expected["sha256"]
        if source.suffix == ".parquet":
            parquet = pq.ParquetFile(source)
            row["rows"] = parquet.metadata.num_rows
            row["compression"] = sorted({
                parquet.metadata.row_group(group).column(column).compression
                for group in range(parquet.metadata.num_row_groups)
                for column in range(parquet.metadata.num_columns)
            })
            codec = (parquet.schema_arrow.metadata or {}).get(METADATA_KEY)
            row["codec"] = json.loads(codec) if codec is not None else None
    return row


def package(q1: Path, remaining: Path, staging: Path, proofs: list[Path]) -> dict[str, Any]:
    receipts: list[tuple[str, str, str | None, Path, dict[str, Any]]] = [("Q1", family, None, *load_receipt(q1, family, None)) for family in PATTERNS]
    receipts += [("Q2-Q6", family, phase, *load_receipt(remaining, family, phase)) for family in PATTERNS for phase in PHASES]
    if sum(len(receipt["results"]) for section, _, _, _, receipt in receipts if section == "Q2-Q6") != 1032:
        raise ValueError("expected exactly 1032 remaining final files")
    completion = json.loads(proofs[0].read_bytes())
    observed = {(family, phase): len(receipt["results"]) for section, family, phase, _, receipt in receipts if section == "Q2-Q6"}
    recorded = {(row["target"], row["phase"]): row["files"] for row in completion["phases"]}
    if len(completion["phases"]) != 36 or recorded != observed:
        raise ValueError("completion proof differs from terminal inventories")
    inventory: dict[str, Any] = {
        "schema": "pattern-scan-d-delivery.v1",
        "task_id": TASK,
        "source_id": SOURCE,
        "input_id": INPUT,
        "receipt_count": 48,
        "final_count": 1056,
        "path_policy": "Original receipt bytes retained; absolute result paths are historical. Resolve result keys relative to each ZIP receipt directory.",
        "files": [],
        "executors": [],
    }
    archive_path = staging / "pattern-scan-d-finals.zip"
    with ZipFile(archive_path, "x", compression=ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
        for section, family, phase, path, receipt in receipts:
            prefix = f"{section}/{family}" + (f"/{phase}" if phase else "")
            inventory["files"].append(stream_member(archive, path, f"{prefix}/{path.name}", None))
            inventory["executors"].append({"receipt": f"{prefix}/{path.name}", "code": receipt["code"]})
            for name, descriptor in sorted(receipt["results"].items()):
                inventory["files"].append(stream_member(archive, contained(path.parent, name), f"{prefix}/{name}", descriptor))
            LOGGER.info("Packed %s %s %s", section, family, phase or "Q1")
        for number, proof in enumerate(proofs):
            inventory["files"].append(stream_member(archive, proof, f"provenance/{number}-{proof.name}", None))
        archive.writestr("inventory.json", canonical(inventory))
    with ZipFile(archive_path) as archive:
        expected_names = {row["path"] for row in inventory["files"]} | {"inventory.json"}
        if len(archive.namelist()) != len(expected_names) or set(archive.namelist()) != expected_names or archive.testzip() is not None:
            raise ValueError("ZIP inventory/CRC verification failed")
        if json.loads(archive.read("inventory.json")) != inventory:
            raise ValueError("ZIP inventory round-trip failed")
    (staging / "inventory.json").write_bytes(canonical(inventory))
    return inventory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--q1-root", required=True, type=Path)
    parser.add_argument("--remaining-root", required=True, type=Path)
    parser.add_argument("--completion-verification", required=True, type=Path)
    parser.add_argument("--job-receipt", required=True, type=Path)
    parser.add_argument("--metadata-output", required=True, type=Path, help="New directory outside the bundle, containing publication.json")
    parser.add_argument("--resume-staging", type=Path, help="Retry only a fully packaged staging/final directory after publication failure")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    checkout = Path(__file__).resolve().parents[3]
    catalog = DataCatalog(DataRoots.from_env(worktree=checkout))
    q1, remaining = (checked_path(path.absolute()) for path in (args.q1_root, args.remaining_root))
    output = safe_path(args.metadata_output.absolute())
    parent = catalog.roots.artifact_path("data", PARENT)
    if output.exists() or output.is_relative_to(parent) or parent.is_relative_to(output):
        raise ValueError("metadata output must be a new directory outside the publication tree")
    proofs = [checked_path(path.absolute()) for path in (args.completion_verification, args.job_receipt)]
    for proof in proofs:
        if not proof.is_file() or not isinstance(json.loads(proof.read_bytes()), dict):
            raise ValueError("completion/job provenance must be existing JSON objects")
    completion, job = (json.loads(proof.read_bytes()) for proof in proofs)
    required = {
        "complete": True,
        "terminal_receipts": 36,
        "final_files": 1032,
        "original_stocks": 1942,
        "input_identity_verified": True,
        "fixed_selection_verified": True,
    }
    if any(completion.get(key) != value for key, value in required.items()):
        raise ValueError("completion proof does not establish all final phases")
    if completion.get("job") != job or job.get("exit_code") != 0 or job.get("timed_out") is not False:
        raise ValueError("completion and successful job receipt must agree")
    if proofs[0].parent != proofs[1].parent or completion.get("attempt") != proofs[0].parent.name:
        raise ValueError("completion/job must belong to the named same attempt")
    parent.mkdir(parents=True, exist_ok=True)
    staging = checked_path(args.resume_staging.absolute()) if args.resume_staging else parent / f".staging-d-{uuid.uuid4().hex}"
    if staging.parent != parent:
        raise ValueError("staging must be a sibling under the managed publication parent")
    if args.resume_staging:
        inventory = json.loads((staging / "inventory.json").read_bytes())
        if (inventory.get("schema"), inventory.get("source_id"), inventory.get("input_id"), inventory.get("final_count"), inventory.get("receipt_count")) != (
            "pattern-scan-d-delivery.v1",
            SOURCE,
            INPUT,
            1056,
            48,
        ):
            raise ValueError("resume inventory identity mismatch")
        with ZipFile(staging / "pattern-scan-d-finals.zip") as archive:
            names = {row["path"] for row in inventory["files"]} | {"inventory.json"}
            if (
                len(archive.namelist()) != len(names)
                or set(archive.namelist()) != names
                or archive.testzip() is not None
                or json.loads(archive.read("inventory.json")) != inventory
            ):
                raise ValueError("resume ZIP failed verification")
            for row in inventory["files"]:
                if "sha256" not in row:
                    continue
                digest = hashlib.sha256()
                size = 0
                with archive.open(row["path"]) as member:
                    while chunk := member.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                if size != row["bytes"] or digest.hexdigest() != row["sha256"]:
                    raise ValueError(f"resume final identity mismatch: {row['path']}")
    else:
        staging.mkdir()
        LOGGER.info("Publication staging (retained on failure): %s", staging)
        inventory = package(q1, remaining, staging, proofs)
    unknown = {"start": None, "end": None, "reason": "Per-row eligibility and censoring are retained in the final tables; no new coverage inference."}
    metadata = {
        "data_id": "pattern-scan-d-results-v1",
        "kind": "patterns",
        "definition_version": "pattern-scan-local-remaining.v5",
        "parameters": {"horizons": [126, 252], "cutoff": "2026-10-12", "families": list(PATTERNS), "delivery_only": True},
        "inputs": {"source_id": SOURCE, "input_id": INPUT, "policy": "Existing terminal receipts; no input copies or new input hashes."},
        "coverage": {
            "scope": "Q1 and Q2-Q6 retained final results for all 12 families",
            "raw_input_period": {"start": "2010-01-04", "end": "2026-10-12", "reason": None},
            "valid_indicator_period": unknown,
            "complete_label_period": unknown,
        },
        "status": "complete",
        "limitations": [
            "Exploratory exposed cross-check; not unseen validation or strategy approval.",
            "Original receipt absolute paths are historical provenance; ZIP members resolve result-name keys.",
            "Delivery does not release holds, mark scratch delivered, or delete original data.",
        ],
        "backup": {
            "status": "local_copy_only",
            "offsite_verified": False,
            "restore_test": "ZIP reopen and CRC; source finals checked against saved receipt digests while streaming",
        },
    }
    entry = publish_staged_bundle(catalog, metadata, staging, managed_parent=PARENT)
    publish_new_directory(output, {"publication.json": canonical({"entry": entry, "inventory": inventory})})
    LOGGER.info("Published %s; originals preserved; metadata %s", entry["manifest"]["path"], output)


if __name__ == "__main__":
    main()
