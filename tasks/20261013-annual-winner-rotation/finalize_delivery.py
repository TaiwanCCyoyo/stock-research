"""Format new annual JSON delivery copies before hashing; preserve frozen evidence."""

# Direct task CLI; no imports from another script's private helpers.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
TASK = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from research_core.annual_publication import json_delivery_receipt, verified_result
from research_core.artifact_store import canonical, file_digest, publish_new_directory, safe_path, write_json
from research_core.research_data_builder import publish_bundle
from research_core.research_data_catalog import CATALOG_FIELDS, DataCatalog, verify_entry
from research_core.research_data_paths import DataRoots

SOURCES = {
    "input-pin-v1.json": TASK / "params/input-pin-v1.json",
    "measurement-v2.json": TASK / "params/measurement-v2.json",
    "original-results-v1.json": TASK / "params/original-results-v1.json",
    "sweep_results.json": TASK / "sweep_results.json",
}
CODE = [
    "research_core/annual_publication.py",
    "research_core/artifact_store.py",
    "research_core/research_data_builder.py",
    "research_core/research_data_catalog.py",
    "research_core/research_data_paths.py",
    "tasks/20261013-annual-winner-rotation/finalize_delivery.py",
]


def format_new_files(paths: list[Path]) -> None:
    """Run the configured formatter and require a subsequent unchanged pass."""
    command = [sys.executable, "-m", "pre_commit", "run", "prettier", "--files", *[str(path.relative_to(REPO)) for path in paths]]
    first = subprocess.run(command, cwd=REPO, check=False)
    if first.returncode not in (0, 1):
        raise ValueError("normal formatter failed")
    before = {str(path): file_digest(path) for path in paths}
    second = subprocess.run(command, cwd=REPO, check=False)
    if second.returncode != 0 or before != {str(path): file_digest(path) for path in paths}:
        raise ValueError("normal formatter is not stable")


def bindings(cat: DataCatalog, originals: dict[str, bytes]) -> dict[str, Any]:
    pin = json.loads(originals["input-pin-v1.json"])
    registered = cat.get(pin["data_id"], pin["version_id"], manifest_sha256=pin["manifest"]["sha256"])
    json_delivery_receipt(canonical(registered), originals["input-pin-v1.json"])
    original, original_root, _ = verified_result(SOURCES["original-results-v1.json"], cat)
    reviewed, _, reviewed_manifest = verified_result(SOURCES["sweep_results.json"], cat)
    if original["input_entry"] != registered or reviewed["input_entry"] != registered:
        raise ValueError("delivery references different input")
    if reviewed_manifest["lineage"]["ranking_reuse_entry"] != original["process_entry"]:
        raise ValueError("reviewed process does not reuse original process")
    json_delivery_receipt((original_root / "measurement.json").read_bytes(), originals["measurement-v2.json"])
    return {"input_entry": registered, "original_process_entry": original["process_entry"], "reviewed_process_entry": reviewed["process_entry"]}


def finalize(output: Path, pin_output: Path) -> dict[str, Any]:
    output = safe_path(output)
    if output != TASK / "delivery-v1":
        raise ValueError("new delivery must use this task's delivery-v1 directory")
    cat = DataCatalog(DataRoots.from_env(worktree=REPO))
    originals = {name: safe_path(path).read_bytes() for name, path in SOURCES.items()}
    source_pins = {name: file_digest(REPO / name) for name in CODE}
    refs = bindings(cat, originals)
    if not output.exists():
        publish_new_directory(output, originals)
    else:
        # Idempotent reuse accepts only equivalent generated copies, never a
        # different prior artifact or files not owned by this finalizer.
        if {path.name for path in output.iterdir()} - (set(SOURCES) | {"receipt.json"}):
            raise ValueError("unrecognized existing delivery member")
        for name, raw in originals.items():
            json_delivery_receipt(raw, (output / name).read_bytes())
    format_new_files([output / name for name in SOURCES])
    records = {name: json_delivery_receipt(raw, (output / name).read_bytes()) for name, raw in originals.items()}
    receipt = {
        "schema": "annual-json-delivery-set.v1",
        "formatter": {
            "hook": "prettier",
            "repository_revision": "v3.9.5",
            "precommit_config_sha256": file_digest(REPO / ".pre-commit-config.yaml"),
            "prettier_config_sha256": file_digest(REPO / ".prettierrc.json"),
        },
        "files": records,
        "references": refs,
        "implementation_sha256": source_pins,
        "market_recomputed": False,
    }
    receipt_path = output / "receipt.json"
    if not receipt_path.exists():
        write_json(receipt_path, receipt)
    else:
        json_delivery_receipt(canonical(receipt), receipt_path.read_bytes())
    format_new_files([receipt_path])
    # The finalized public results still bind to the sealed input/process/source.
    verified_result(output / "original-results-v1.json", cat)
    reviewed, _, _ = verified_result(output / "sweep_results.json", cat)
    if any(path.read_bytes() != originals[name] for name, path in SOURCES.items()) or source_pins != {name: file_digest(REPO / name) for name in CODE}:
        raise ValueError("source bytes changed during delivery finalization")
    payloads = {f"originals/{name}": raw for name, raw in originals.items()}
    payloads.update({f"delivery/{name}": (output / name).read_bytes() for name in [*SOURCES, "receipt.json"]})
    payloads.update({f"implementation/{name}": (REPO / name).read_bytes() for name in CODE})
    metadata = {key: reviewed["process_entry"][key] for key in CATALOG_FIELDS}
    metadata.update(
        data_id="annual-rotation-delivery",
        definition_version="annual-json-delivery.v1",
        parameters={"format": receipt["formatter"], "presentation_only": True},
        inputs={"references": refs, "source_file_sha256": {name: row["source_sha256"] for name, row in records.items()}, "implementation_sha256": source_pins},
    )
    entry = publish_bundle(cat, metadata, payloads, lineage={**refs, "relationship": "formatted_presentation_with_original_bytes_preserved"})
    verify_entry(entry, cat.roots)
    if pin_output.exists():
        json_delivery_receipt(canonical(entry), pin_output.read_bytes())
    else:
        write_json(pin_output, entry)
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=TASK / "delivery-v1")
    parser.add_argument("--pin-output", type=Path, default=TASK / "params/delivery-pin-v1.json")
    args = parser.parse_args()
    entry = finalize(args.output, args.pin_output)
    print(
        json.dumps(
            {"data_id": entry["data_id"], "version_id": entry["version_id"], "output": str(args.output), "pin_output": str(args.pin_output)}, ensure_ascii=True
        )
    )  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
