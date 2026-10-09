"""One preregistered interaction study using preserved atlas and context artifacts.

Prepare hashes only; market evaluation must run through run_registered_job.py.
The compressed packet is the portable, byte-preserved preregistration artifact.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_core.feature_atlas_dataset import load_analysis  # noqa: E402
from research_core.feature_atlas_io import write_json  # noqa: E402
from research_core.jobs import confined, digest, file_digest, runtime_identity, validate_packet  # noqa: E402
from research_core.market_context_artifact import load_context_rows  # noqa: E402
from research_core.method_environment_interactions import analyze, attach_context  # noqa: E402

LOGGER = logging.getLogger(__name__)
TASK = "20261005-method-environment-interactions"
ATLAS = "tasks/20261004-feature-discrimination-atlas/runs/registered/atlas-v2"
CONTEXT = "tasks/20261005-market-context-handoff/market-context-v2"
START, END = "2019-01-02", "2026-08-14"
COLUMNS = ["F10", "F32", "F33", "F37", "base_eligible", "calendar_index", "year"] + [
    f"{name}_{horizon}" for horizon in (63, 126) for name in ("forward_return", "min_return", "max_drawdown", "complete", "label", "wait_to_threshold")
]
OUTPUTS = ["summary.json", "results.json", "input-audit.json"]


def declared_artifacts(root: Path, relative: str, *, atlas: bool) -> list[str]:
    """Enumerate the exact reader read-set from a frozen manifest, without rows."""
    manifest = json.loads(confined(root, f"{relative}/manifest.json").read_text(encoding="utf-8"))
    entries = [*manifest["tables"], manifest["cross_section"], *manifest["artifacts"]] if atlas else manifest["artifacts"]
    paths = [f"{relative}/manifest.json", *[f"{relative}/{entry['path']}" for entry in entries]]
    if len({name.casefold() for name in paths}) != len(paths):
        raise ValueError("duplicate input artifact path")
    for name in paths:
        confined(root, name)
    return paths


def prepare_packet(root: Path, job_id: str) -> dict[str, Any]:
    """Hash complete inputs and exclusively save plain and compressed packets."""
    code = [
        "scripts/run_method_environment_interactions.py",
        "scripts/run_registered_job.py",
        "research_core/__init__.py",
        "research_core/jobs.py",
        "research_core/evidence.py",
        "research_core/method_environment_interactions.py",
        "research_core/feature_atlas_dataset.py",
        "research_core/feature_atlas_io.py",
        "research_core/feature_atlas_outcomes.py",
        "research_core/market_context_artifact.py",
        "StockProject/engine/data_loader.py",
        "StockProject/engine/__init__.py",
        "pyproject.toml",
        "uv.lock",
    ]
    if (root / "StockProject/__init__.py").is_file():
        code.append("StockProject/__init__.py")
    contracts = [
        f"tasks/{TASK}/mission.md",
        "docs/en/research-owner-contract.md",
        "docs/en/research-registry.json",
        "tasks/20261004-feature-discrimination-atlas/data-contract.md",
        "tasks/20261005-market-context-handoff/data-contract.md",
    ]
    data = declared_artifacts(root, ATLAS, atlas=True) + declared_artifacts(root, CONTEXT, atlas=False)
    packet: dict[str, Any] = {
        "schema_version": "research-job.v1",
        "job_id": job_id,
        "task_id": TASK,
        "phase": "exploration",
        "window": {"start": START, "end": END},
        "candidate_id": "three-methods-relative-strength.v1",
        "owner_contract_id": "research-owner-contract-current",
        "metric_contract_id": "common-support-method-environment.v1",
        "execution_contract_id": "descriptive-no-trades.v1",
        "scenario_id": "daily-grid126-past-only-0050",
        "params": {"families": ["F10", "F32", "F33"], "strength": "F37", "max_comparisons": 672, "maximum_attempts": 2},
        "timeout_seconds": 1800,
        "runtime": runtime_identity(),
        "inputs": {
            group: {name: file_digest(confined(root, name)) for name in names} for group, names in (("code", code), ("contracts", contracts), ("data", data))
        },
        "script": code[0],
        "args": ["--output-dir", "{output_dir}", "--run-id", job_id],
        "outputs": OUTPUTS,
        "summary": "summary.json",
    }
    validate_packet(packet)
    plain = confined(root, f"tasks/{TASK}/params/{job_id}.json")
    compressed = confined(root, f"tasks/{TASK}/preregistration/{job_id}.json.gz")
    plain.parent.mkdir(parents=True, exist_ok=True)
    compressed.parent.mkdir(parents=True, exist_ok=True)
    if plain.exists() or compressed.exists():
        raise ValueError("packet destination exists; preserve it and choose a new job ID")
    write_json(plain, packet)
    with compressed.open("xb") as stream:
        stream.write(gzip.compress(plain.read_bytes(), mtime=0))
    LOGGER.info("Prepared packet job=%s input_files=%d; no market rows evaluated", job_id, sum(map(len, packet["inputs"].values())))
    return {"packet": str(plain), "portable_packet": str(compressed), "packet_sha256": digest(packet), "files": sum(map(len, packet["inputs"].values()))}


def build(root: Path, output: Path, run_id: str) -> None:
    """Read fixed inputs, compute one bounded batch, and write fresh JSON evidence."""
    atlas_root, context_root = confined(root, ATLAS), confined(root, CONTEXT)
    atlas_manifest = json.loads((atlas_root / "manifest.json").read_text(encoding="utf-8"))
    context_manifest = json.loads((context_root / "manifest.json").read_text(encoding="utf-8"))
    LOGGER.info("Loading verified atlas projection dataset=%s", atlas_manifest["dataset_id"])
    frame = load_analysis(atlas_root, COLUMNS)
    if frame["asof_date"].min().strftime("%Y-%m-%d") != START or frame["asof_date"].max().strftime("%Y-%m-%d") != END:
        raise ValueError("atlas window differs from preregistration")
    context = load_context_rows(context_root, layer="past_only")
    # Whole published context package is verified, but only this fixed window joins.
    context = [row for row in context if START <= row["asof_date"] <= END]
    joined, join_audit = attach_context(frame, context)
    LOGGER.info("Evaluating rows=%d methods=3 panels=2; maximum comparisons=672", len(joined))
    result = analyze(joined)
    if len(result["comparisons"]) > 672:
        raise ValueError("preregistered comparison budget exceeded")
    audit = {
        "schema_version": "method-environment-inputs.v1",
        "source_datasets": {
            "atlas": {"dataset_id": atlas_manifest["dataset_id"], "manifest_sha256": file_digest(atlas_root / "manifest.json"), "path": ATLAS},
            "context": {
                "dataset_id": context_manifest["dataset_id"],
                "manifest_sha256": file_digest(context_root / "manifest.json"),
                "path": CONTEXT,
                "layer": "past_only",
            },
        },
        "window": {"start": START, "end": END},
        "projection": COLUMNS,
        "join": join_audit,
    }
    summary = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": {"task_id": TASK, "run_id": run_id, "phase": "exploration"},
        "strategy": {"kind": "descriptive_only", "methods": ["F10", "F32", "F33"], "strength": "F37"},
        "data": audit,
        "metrics": {"comparison_rows": len(result["comparisons"]), "triage": result["triage"]},
        "portfolio": {"simulated": False},
        "trades": [],
        "warnings": [
            "Already exposed, current-reference cohort; not survivorship-complete or PIT-certified.",
            "Dependent stock/date price labels, not independent opportunities or captured account returns.",
            "Unknown paths retained; permanent-factor closes exclude cash-dividend total return.",
            "Past-only 0050 state uses its preserved source vintage; no historical publication guarantee.",
            "Exploratory triage is not investment approval or permission to open confirmation/holdout.",
        ],
    }
    write_json(output / "results.json", {"schema_version": "method-environment-results.v1", **result})
    write_json(output / "input-audit.json", audit)
    write_json(output / "summary.json", summary)
    LOGGER.info("Completed run=%s comparisons=%d", run_id, len(result["comparisons"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", metavar="JOB_ID")
    modes.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.prepare:
        sys.stdout.write(json.dumps(prepare_packet(ROOT, args.prepare), indent=2) + "\n")
    elif args.run_id:
        build(ROOT, args.output_dir, args.run_id)
    else:
        parser.error("--run-id required for a registered execution")


if __name__ == "__main__":
    main()
