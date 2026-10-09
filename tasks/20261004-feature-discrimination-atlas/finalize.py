"""Preserve verified atlas artifacts and write compact, non-strategy evidence.

No recalculation of features, parameter selection, or destructive synchronization.
The additive copy is optional and must name a fresh ordinary directory.
"""

from __future__ import annotations

import argparse
import collections
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_core.evidence import read_json, validate_result  # noqa: E402
from research_core.feature_atlas_dataset import verify_dataset  # noqa: E402
from research_core.feature_atlas_io import TASK_ID, write_json  # noqa: E402
from research_core.jobs import confined, file_digest, validate_packet, verify_reuse  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--copy-root", type=Path)
    parser.add_argument("--archive-inputs", action="store_true")
    args = parser.parse_args()
    if args.archive_inputs and args.copy_root is None:
        parser.error("--archive-inputs requires --copy-root")
    task = ROOT / "tasks" / TASK_ID
    source = confined(task, f"runs/registered/{args.run_id}")
    packet_path = confined(task, f"params/{args.run_id}.json")
    packet = validate_packet(read_json(packet_path))
    if packet["task_id"] != TASK_ID or packet["job_id"] != args.run_id:
        raise ValueError("Packet does not identify the requested task and run")
    # Bind every published identity and archived input to the actual receipt,
    # including current input/runtime identity and the complete output set.
    verify_reuse(ROOT, packet)
    if args.copy_root:
        copy_root, source_root = args.copy_root.resolve(), source.resolve()
        if copy_root.is_relative_to(source_root) or source_root.is_relative_to(copy_root):
            raise ValueError("Copy root and source must be separate, non-nested directories")
    verified = verify_dataset(source)
    summary = read_json(source / "summary.json")
    inventory = read_json(source / "inventory.json")
    manifest = read_json(source / "manifest.json")
    comparisons = read_json(source / "comparisons.json")["comparisons"]
    backup = None
    input_archive = None
    if args.copy_root:
        # Keep every source file, including receipt and log. Never merge into or
        # overwrite an existing destination. Parent must supply an ordinary root.
        destination = confined(args.copy_root, args.run_id)
        destination.mkdir(parents=True, exist_ok=False)
        for path in source.rglob("*"):
            if path.is_file():
                relative = path.relative_to(source).as_posix()
                target = confined(destination, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                if file_digest(path) != file_digest(target):
                    raise ValueError(f"Backup hash mismatch: {relative}")
        backup = str(destination)
        if args.archive_inputs:
            input_root = confined(args.copy_root, f"{args.run_id}-inputs")
            input_root.mkdir(parents=True, exist_ok=False)
            for group in packet["inputs"].values():
                for relative, expected in group.items():
                    original = confined(ROOT, relative)
                    if file_digest(original) != expected:
                        raise ValueError(f"Input archive source changed: {relative}")
                    target = confined(input_root, relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, target)
                    if file_digest(target) != expected:
                        raise ValueError(f"Input archive copy mismatch: {relative}")
            shutil.copy2(packet_path, input_root / "packet.json")
            write_json(
                input_root / "input-archive.json",
                {
                    "schema_version": "research-input-archive.v1",
                    "inputs": packet["inputs"],
                    "packet_sha256": file_digest(packet_path),
                    "original_root": str(ROOT),
                },
            )
            input_archive = str(input_root)
    packet_ref = f"params/{args.run_id}.json"
    result = {
        "schema_version": "research-result.v1",
        "study_id": TASK_ID,
        "candidate_id": summary["strategy"]["definition_id"],
        "run_id": args.run_id,
        "phase": "exploration",
        "outcome": "not_evaluated",
        "identities": {
            "owner_contract": f"{packet_ref}#/inputs/contracts",
            "metric_contract": "mission.md",
            "execution_contract": "descriptive-no-trades.v1",
            "data_snapshot": manifest["dataset_id"],
            "code": f"{packet_ref}#/inputs/code",
            "runtime": f"{packet_ref}#/runtime",
        },
        "window": summary["data"]["window"],
        "metrics": {
            key: {"value": value, "unit": "count"}
            for key, value in {
                "sample_rows": summary["metrics"]["rows"],
                "eligible_rows": summary["metrics"]["eligible_rows"],
                "feature_count": 38,
                "comparison_rows": len(comparisons),
                "securities": summary["data"]["securities"],
            }.items()
        },
        "artifacts": [
            "mission.md",
            "data-contract.md",
            "sweep_results.json",
            "universe_build_report.json",
            packet_ref,
            f"runs/registered/{args.run_id}/manifest.json",
            f"runs/registered/{args.run_id}/receipt.json",
        ],
        "limitations": summary["warnings"],
        "supersedes": [],
        "organization_status": "completed_verified_descriptive_data",
        "strategy_evaluation_status": "not_evaluated",
        "same_machine_redundant_copy": backup,
        "same_machine_input_archive": input_archive,
    }
    validate_result(result)
    write_json(task / "research_result.json", result)
    write_json(
        task / "sweep_results.json",
        {
            "dataset_id": manifest["dataset_id"],
            "metrics": summary["metrics"],
            "pooled_comparisons": [row for row in comparisons if row["context_column"] is None],
            "full_comparisons": f"runs/registered/{args.run_id}/comparisons.json",
        },
    )
    exclusions = collections.Counter(row["exclusion_reason"] for row in inventory["securities"] if not row["included"])
    reasons: collections.Counter[str] = collections.Counter()
    for item in inventory["quality"]:
        reasons.update(item["quality_reasons"])
    write_json(
        task / "universe_build_report.json",
        {
            "dataset_id": manifest["dataset_id"],
            "window": summary["data"]["window"],
            "source_counts": inventory["source_row_counts"],
            "metadata_rows": inventory["metadata_rows"],
            "included": inventory["included_securities"],
            "exclusions": dict(exclusions),
            "quality_reasons": dict(reasons),
            "verified": verified,
            "historical_universe_complete": False,
            "same_machine_redundant_copy": backup,
        },
    )
    sys.stdout.write(f"Verified and retained {verified['table_rows']} rows; backup={backup}\n")


if __name__ == "__main__":
    main()
