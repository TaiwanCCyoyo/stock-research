"""Full Q1--Q6 storage observations for at most four representative stocks.

This resource-only scratch run never publishes catalog versions or reads the
producer. It uses every event supplied in the verified representative parts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from research_core.artifact_store import describe_file, file_digest, object_digest, read_json, verify_files
from research_core.pattern_scan_analysis_v1 import select_all, summarize_all
from research_core.pattern_scan_barrier_v1 import verified_parts, verify_barrier
from research_core.pattern_scan_completion_v1 import complete_followup
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_run_v1 import _publish_json
from research_core.research_data_paths import _checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample

LOGGER = logging.getLogger(__name__)
SCOPE = {
    "purpose": "resource-only representative full Q1-Q6; not full-market research",
    "max_stocks": 4,
    "event_scope": "all supplied events; no per-stock event cap",
    "catalog_publication": False,
    "producer_reads": False,
}


def _ancestors(
    parts: dict[str, Path],
    barrier: dict[str, Any],
    event_parts: dict[str, dict[str, Path]],
    *,
    source: dict[str, Any],
    input_id: str,
) -> dict[str, Any]:
    if not 1 <= len(parts) <= 4:
        raise ValueError("storage profile requires one to four explicit representative stock parts")
    if set(event_parts) != set(PATTERNS) or any(set(pool) != set(parts) for pool in event_parts.values()):
        raise ValueError("storage profile event stock-set or approved patterns differ")
    if barrier.get("source_id") != source["source_id"] or barrier.get("input_id") != input_id or set(barrier.get("global_files", {})) != set(parts):
        raise ValueError("storage profile barrier source/input or stock pool differs")
    stock_receipts = [read_json(_checked_path(directory / "receipt.json")) for directory in parts.values()]
    receipts_by_code = {receipt["code"]: receipt for receipt in stock_receipts}
    verified = verified_parts(stock_receipts, source=source, input_id=input_id)
    if verified != {code: _checked_path(directory) for code, directory in parts.items()}:
        raise ValueError("storage profile stock receipt code/path differs")
    barrier_directory = verify_barrier(barrier)
    ancestors: dict[str, Any] = {}
    for code, directory in sorted(parts.items()):
        receipt_path = _checked_path(directory / "receipt.json")
        digest = file_digest(receipt_path)
        if barrier.get("identity", {}).get("stock_receipts", {}).get(code) != digest:
            raise ValueError("storage profile barrier stock ancestor differs")
        ancestors[f"stock:{code}"] = {"path": str(receipt_path), "sha256": digest}
        for target in PATTERNS:
            event_directory = _checked_path(event_parts[target][code])
            event_path = event_directory / "receipt.json"
            receipt = read_json(event_path)
            identity = receipt.get("identity", {})
            global_record = barrier["global_files"][code]
            if (
                receipt.get("schema") != "pattern-scan-event-part.v1"
                or receipt.get("complete") is not True
                or identity.get("source_id") != source["source_id"]
                or identity.get("input_id") != input_id
                or identity.get("code") != code
                or identity.get("target") != target
                or identity.get("stock_request_id") != receipts_by_code[code]["request_id"]
                or identity.get("global_sha256") != global_record["sha256"]
            ):
                raise ValueError("storage profile event receipt identity differs")
            verify_files(event_directory, receipt["artifacts"])
            ancestors[f"event:{target}:{code}"] = {"path": str(event_path), "sha256": file_digest(event_path)}
    path = barrier_directory / "receipt.json"
    ancestors["barrier"] = {"path": str(path), "sha256": file_digest(path)}
    return ancestors


def _measure(files: dict[str, Path]) -> dict[str, Any]:
    """Use metadata, never materialize Parquet payloads merely to count rows."""
    records = []
    seen: set[Path] = set()
    for name, raw_path in sorted(files.items()):
        path = _checked_path(raw_path)
        if path in seen:
            continue
        seen.add(path)
        records.append({
            "name": name,
            "path": str(path),
            "bytes": path.stat().st_size,
            "rows": pq.ParquetFile(path).metadata.num_rows if path.suffix == ".parquet" else None,
        })
    return {
        "file_n": len(records),
        "bytes": sum(row["bytes"] for row in records),
        "parquet_rows": sum(row["rows"] for row in records if row["rows"] is not None),
        "files": records,
    }


def _part_measure(directory: Path) -> dict[str, Any]:
    receipt = read_json(directory / "receipt.json")
    return _measure({
        **{record["path"]: directory / record["path"] for record in receipt["artifacts"]},
        "receipt.json": directory / "receipt.json",
    })


def profile_storage(
    parts: dict[str, Path],
    barrier: dict[str, Any],
    event_parts: dict[str, dict[str, Path]],
    output: Path,
    *,
    source: dict[str, Any],
    input_id: str,
) -> dict[str, Any]:
    """Measure full supplied Q1--Q6 work, preserving reusable scratch receipts."""
    started = resource_sample()
    ancestors = _ancestors(parts, barrier, event_parts, source=source, input_id=input_id)
    output = _checked_path(output)
    for descriptor in ancestors.values():
        directory = Path(descriptor["path"]).parent
        if output == directory or output.is_relative_to(directory) or directory.is_relative_to(output):
            raise ValueError("storage scratch output must be separate from supplied ancestor parts")
    identity = {"source_id": source["source_id"], "input_id": input_id, "scope": SCOPE, "stocks": sorted(parts), "ancestors": ancestors}
    receipt_path = output / "receipt.json"
    if receipt_path.exists():
        saved = read_json(receipt_path, max_bytes=64_000_000)
        if (
            saved.get("schema") != "pattern-scan-storage-profile.v2"
            or saved.get("complete") is not True
            or saved.get("identity") != identity
            or saved.get("source_id") != source["source_id"]
            or saved.get("input_id") != input_id
            or saved.get("scope") != SCOPE
            or saved.get("security_codes") != sorted(parts)
        ):
            raise ValueError("existing storage profile identity differs or incomplete")
        verify_files(output, saved["artifacts"])
        LOGGER.info("Reused resource-only storage profile stocks=%s input_id=%s", sorted(parts), input_id)
        return saved
    output.mkdir(parents=True, exist_ok=True)
    phases = []
    LOGGER.info("Profiling resource-only full Q1-Q6 stocks=%s source_id=%s input_id=%s", sorted(parts), source["source_id"], input_id)
    request_path = output / "request.json"
    if request_path.exists():
        if read_json(request_path) != identity:
            raise ValueError("partial storage profile request identity differs")
    else:
        _publish_json(request_path, identity)
    selection_path = output / "selection.json"
    before = resource_sample()
    if selection_path.exists():
        selection_record = read_json(selection_path)
        if selection_record.get("request_id") != object_digest(identity):
            raise ValueError("partial storage selection identity differs")
        selections = selection_record["selections"]
    else:
        selections = select_all(event_parts)
        _publish_json(selection_path, {"request_id": object_digest(identity), "selections": selections})
    phases.append(phase_receipt("full_representative_selection", before, resource_sample()))
    summary_index = output / "summary-index.json"
    before = resource_sample()
    if summary_index.exists():
        summary_record = read_json(summary_index, max_bytes=64_000_000)
        if summary_record.get("selection_sha256") != file_digest(selection_path):
            raise ValueError("partial storage summary selection differs")
        verify_files(output, summary_record["artifacts"])
        summaries = summary_record["summaries"]
    else:
        summaries = summarize_all(event_parts, selections, output / "summaries")
        summary_artifacts = [describe_file(output, _checked_path(Path(path))) for path in summaries["files"].values()]
        _publish_json(summary_index, {"summaries": summaries, "artifacts": summary_artifacts, "selection_sha256": file_digest(selection_path)})
    phases.append(phase_receipt("full_representative_q1_q3", before, resource_sample()))
    before = resource_sample()
    followup = complete_followup(parts, barrier, event_parts, selections, summaries, output / "followup", source=source, input_id=input_id)
    phases.append(phase_receipt("full_representative_q4_q6", before, resource_sample()))
    summary_files = {name: Path(path) for name, path in summaries["files"].items()}
    followup_files = {name: Path(path) for name, path in followup["files"].items()}
    episode_files = {name: Path(path) for name, path in followup["episodes"]["files"].items()}
    for path in [*summary_files.values(), *followup_files.values(), *episode_files.values()]:
        if not _checked_path(path).is_relative_to(output):
            raise ValueError("storage computation output escaped supplied scratch root")
    observation_files = {name: path for name, path in followup_files.items() if name.startswith("observations/")}
    holding_files = {name: path for name, path in followup_files.items() if name == "holding_context.parquet"}
    followup_summary_files = {name: path for name, path in followup_files.items() if name not in observation_files and name not in holding_files}
    components = {
        "checkpoints_by_stock": {code: _part_measure(directory) for code, directory in sorted(parts.items())},
        "events_by_stock": {
            code: _measure({
                f"{target}/{record['path']}": event_parts[target][code] / record["path"]
                for target in PATTERNS
                for record in [*read_json(event_parts[target][code] / "receipt.json")["artifacts"], {"path": "receipt.json"}]
            })
            for code in sorted(parts)
        },
        "barrier": _part_measure(Path(ancestors["barrier"]["path"]).parent),
        "summaries": _measure(summary_files),
        "followup_observations": _measure(observation_files),
        "followup_summaries": _measure(followup_summary_files),
        "holding_context": _measure(holding_files),
        "episodes": _measure(episode_files),
        "report_copy": {
            **_measure({**{f"q1-q3/{name}": path for name, path in summary_files.items()}, **{f"q5-q6/{name}": path for name, path in followup_files.items()}}),
            "scope": "additional payload bytes if report bundle copies Q1-Q3 and Q5-Q6 files; no copy performed; episodes excluded",
        },
    }
    if _ancestors(parts, barrier, event_parts, source=source, input_id=input_id) != ancestors:
        raise ValueError("storage profile ancestors changed during computation")
    # Include receipts and indexes as well as every retained completed payload.
    # Interrupted staging remains on disk, and is measured separately below.
    artifacts = [
        describe_file(output, _checked_path(path))
        for path in sorted(output.rglob("*"))
        if path.is_file() and not any(part.startswith(".staging-") for part in path.relative_to(output).parts)
    ]
    verify_files(output, artifacts)
    result = {
        "schema": "pattern-scan-storage-profile.v2",
        "complete": True,
        "identity": identity,
        "scope": SCOPE,
        "source_id": source["source_id"],
        "input_id": input_id,
        "representative_security_n": len(parts),
        "security_codes": sorted(parts),
        "components": components,
        "artifacts": artifacts,
        "retained_completed_output_bytes": sum(record["bytes"] for record in artifacts),
        "retained_completed_output_scope": "all completed scratch files except this final receipt; partial staging measured separately",
        "retained_partial_staging_bytes": sum(
            _checked_path(path).stat().st_size
            for path in output.rglob("*")
            if path.is_file() and any(part.startswith(".staging-") for part in path.relative_to(output).parts)
        ),
        "exact_quantile_memory_bytes": None,
        "exact_quantile_memory_reason": (
            "existing computation functions do not expose isolated exact-quantile memory; native process lifetime peaks are in phase measurements"
        ),
        "phases": phases,
        "measurement": phase_receipt("full_representative_q1_q6_storage", started, resource_sample()),
    }
    _publish_json(receipt_path, result)
    LOGGER.info("Completed resource-only storage profile stocks=%d bytes=%d", len(parts), result["retained_completed_output_bytes"])
    return result
