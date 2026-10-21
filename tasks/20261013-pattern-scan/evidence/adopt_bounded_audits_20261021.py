"""Record existing bounded PR17 audit results in place, without recomputation.

This retained one-off evidence entry point does not run numerical research.
The four input files are the existing final comparison outputs, not market
inputs or working event tables. Earlier scratch executors remain unavailable;
the receipt describes this adoption separately from those checks.
"""

from __future__ import annotations

import argparse
import json
import logging
import uuid
from pathlib import Path

from research_core.artifact_store import publish_noreplace
from research_core.research_data_paths import checked_path
from research_core.run_receipt import InputSpec, code_identity, fingerprint_inputs, write_run_receipt

LOGGER = logging.getLogger(__name__)
RESULT_NAMES = {
    "event_structure": "pr17-event-formula-readiness-20261021.json",
    "event_conditions": "pr17-event-condition-prefix-check-20261021.json",
    "event_globals": "pr17-event-global-check-20261021.json",
    "candidate_case_inspection": "pr17-audit-final-inspection-20261021.json",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    root = Path(__file__).resolve().parents[3]
    results_root = checked_path(args.results_root)
    destination = checked_path(args.output)
    if not destination.is_relative_to(root) or destination.parent != results_root:
        raise ValueError("adoption receipt must sit beside its existing result files in this checkout")
    if destination.exists():
        raise FileExistsError("existing audit evidence receipt is retained; do not overwrite")
    results = {name: results_root / filename for name, filename in RESULT_NAMES.items()}
    records = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in results.items()}
    if any(record["mismatch_n"] != 0 for record in records.values()):
        raise ValueError("bounded evidence contains a mismatch")
    structure, conditions, globals_, cases = (records[name] for name in RESULT_NAMES)
    if (structure["raw_n"], structure["cooled_n"], conditions["event_n"], conditions["condition_cells"]) != (10, 10, 10, 520):
        raise ValueError("original bounded event scope differs")
    event_ids = {row["event_id"] for row in conditions["availability"]}
    if {row["event_id"] for row in structure["results"] if row["kind"] == "cooled"} != event_ids:
        raise ValueError("structure and condition samples differ")
    if (globals_["original_stock_n"], globals_["date_n"], globals_["event_n"], globals_["global_cell_n"], globals_["event_condition_cells"]) != (
        1942,
        5,
        10,
        110,
        150,
    ):
        raise ValueError("bounded global reconstruction scope differs")
    if {row["event_id"] for row in globals_["event_conditions"]} != event_ids:
        raise ValueError("global and local event samples differ")
    if (cases["completed_case_n"], cases["comparison_rows"], cases["full_audit_available_at_inspection"]) != (15, 20520, False):
        raise ValueError("this dated inspection is a partial 15-case snapshot")
    code = code_identity(root, sources=[Path(__file__).resolve()])
    fingerprint = fingerprint_inputs([InputSpec(name, path, live_producer=False) for name, path in results.items()])
    staging = destination.with_name(f".staging-{destination.name}-{uuid.uuid4().hex}")
    receipt = write_run_receipt(
        staging,
        run_id="pr17-bounded-audit-evidence-20261021",
        definition="pattern-scan-bounded-audit-evidence.v1",
        parameters={
            "operation": "adopt existing final bounded comparison evidence in place; no recomputation or data copy",
            "full_study_acceptance": False,
            "candidate_full_audit_complete": False,
            "candidate_inspection_at_utc": cases["checked_at_utc"],
            "candidate_inspected_cases": 15,
            "candidate_expected_cases": 40,
            "candidate_inspected_comparison_rows": 20520,
            "event_sample": "original first-sorted B1/TW:1101/H126; ten cooled IDs at five dates, plus ten raw IDs",
            "event_structure_rows": 20,
            "event_condition_cells": 520,
            "additional_global_cells": 110,
            "additional_global_event_cells": 150,
            "upstream_limit": globals_["upstream_limit"],
            "provenance_limit": (
                "This commit describes evidence adoption, not earlier scratch-check executors. "
                "Earlier checks recorded no run receipt; their actual execution commit is unavailable. "
                "Retained scripts and output records remain local. Existing candidate cases retain their individual executor receipts."
            ),
            "new_source_or_intermediate_hashes": False,
            "shared_reads_or_writes": False,
            "original_research_restart_or_deletion": False,
        },
        inputs=fingerprint,
        results=results,
        repo_root=root,
        expected_code=code,
        preregistration=root / "tasks/20261013-pattern-scan/mission.md",
        sources=[Path(__file__).resolve()],
    )
    publish_noreplace(staging, destination)
    LOGGER.info(
        "Adopted bounded final evidence files=%d bytes=%d; full study/candidate audit remains incomplete",
        len(results),
        sum(row["bytes"] for row in receipt["results"].values()),
    )
    print(json.dumps({"receipt": str(destination), "code": receipt["code"], "final_result_n": len(results), "full_study_acceptance": False}))


if __name__ == "__main__":
    main()
