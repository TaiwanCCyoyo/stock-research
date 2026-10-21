"""Bounded candidate reconstruction from original local PR17 inputs.

The numerical oracle is v2, unchanged. Only completed comparison tables receive
hashes. No event projection, input snapshot or parent hash chain is written.
"""

from __future__ import annotations

import io
import logging
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import pandas as pd
import pyarrow.parquet as pq

from research_core.artifact_store import canonical, file_digest, publish_noreplace, read_json, release_os_lock, try_os_lock, write_json
from research_core.pattern_scan_candidate_audit_v2 import compare_candidate, reconstruct_candidate, select_audit_candidates
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_event_tables_v1 import EventTables
from research_core.pattern_scan_local_inputs_v5 import group_frame, write_progress
from research_core.pattern_scan_rates_v1 import REQUIRED_COLUMNS
from research_core.research_data_paths import checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample
from research_core.run_receipt import InputSpec, code_identity, fingerprint_inputs, write_run_receipt

LOGGER = logging.getLogger(__name__)
GROUPS = ("pattern:union", "C-base-no-pattern", "C-base-all", "C-52w")
DEFINITION = "pattern-scan-local-candidate-audit.v5"


class AuditInputs(Protocol):
    codes: tuple[str, ...]
    source_id: str
    input_id: str
    original_code: dict[str, Any] | None
    shared_record: dict[str, Any]

    def bound(self, target: str, code: str) -> EventTables: ...


def _write_case(
    destination: Path,
    tables: Mapping[str, pd.DataFrame],
    parameters: dict[str, Any],
    fingerprint: dict[str, Any],
    inputs: AuditInputs,
    repo_root: Path,
    started_code: dict[str, Any],
) -> None:
    staging = checked_path(destination.with_name(f".staging-{destination.name}-{uuid.uuid4().hex}"))
    staging.mkdir()
    results = {}
    for name in ("summary", "annual"):
        path = staging / f"{name}.parquet"
        with path.open("xb") as stream:
            tables[name].to_parquet(stream, index=False, compression="zstd")
        results[path.name] = path
    mission = repo_root / "tasks/20261013-pattern-scan/mission.md"
    sources = (Path(__file__).resolve(),) if Path(__file__).resolve().is_relative_to(repo_root) else ()
    receipt = write_run_receipt(
        staging / "run-receipt.json",
        run_id=destination.name,
        definition=DEFINITION,
        parameters=parameters,
        inputs=fingerprint,
        results=results,
        repo_root=repo_root,
        shared_data=[inputs.shared_record],
        expected_code=started_code if started_code.get("commit") else None,
        preregistration=mission if mission.is_file() else None,
        sources=sources,
    )
    # This is our new unpublished receipt; move its locators with the same bytes.
    for name, record in receipt["results"].items():
        record["path"] = str(destination / name)
    (staging / "run-receipt.json").write_bytes(canonical(receipt))
    publish_noreplace(staging, destination)


def _reuse_case(destination: Path, parameters: dict[str, Any]) -> dict[str, Any] | None:
    if not destination.exists():
        return None
    receipt = read_json(destination / "run-receipt.json")
    if receipt.get("definition") != DEFINITION or receipt.get("parameters", {}).get("scope") != parameters["scope"]:
        raise ValueError("completed audit case belongs to a different original scope")
    if set(receipt.get("results", {})) != {"summary.parquet", "annual.parquet"}:
        raise ValueError("completed audit case final inventory differs")
    case = receipt.get("parameters", {}).get("case", {})
    scope = parameters["scope"]
    expected = {
        "candidate_id": scope["candidate"]["candidate_id"],
        "group": scope["group"],
        "horizon": scope["horizon"],
        "summary_rows": 144,
        "annual_rows": 1224,
        "aggregate_checks": 1368,
    }
    if any(case.get(name) != value for name, value in expected.items()):
        raise ValueError("completed audit case comparison coverage differs")
    for name, row in receipt["results"].items():
        path = checked_path(destination / name)
        if Path(row["path"]).resolve() != path or path.stat().st_size != row["bytes"] or file_digest(path) != row["sha256"]:
            raise ValueError("completed audit final result differs")
    return dict(case)


def run_candidate_audit(
    inputs: AuditInputs,
    conditions: Path,
    output: Path,
    *,
    repo_root: Path,
    groups: tuple[str, ...] | None = None,
    horizons: tuple[int, ...] = (126, 252),
    max_frame_bytes: int = 512 * 1024**2,
    max_seconds: float = 21600,
) -> dict[str, Any]:
    """Compare the fixed first five B1 candidates, one group/horizon at a time.

    Completed cases are small final evidence, reused without re-binding stocks.
    A limited call is a partial audit; only all 40 cases establish full scope.
    """
    groups = GROUPS if groups is None else groups
    if not groups or len(set(groups)) != len(groups) or not set(groups).issubset(GROUPS):
        raise ValueError("audit requires unique approved groups")
    if not horizons or len(set(horizons)) != len(horizons) or not set(horizons).issubset((126, 252)):
        raise ValueError("audit requires unique approved horizons")
    if max_frame_bytes <= 0 or max_seconds <= 0 or not inputs.codes or len(set(inputs.codes)) != len(inputs.codes):
        raise ValueError("audit requires positive limits and unique original stocks")
    conditions, output, repo_root = checked_path(conditions), checked_path(output), checked_path(repo_root)
    if not output.is_relative_to(repo_root) or output == repo_root or output.is_relative_to(conditions) or conditions.is_relative_to(output):
        raise ValueError("audit output must be isolated inside its own checkout")
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".audit.lock").open("a+b") as handle:
        if not try_os_lock(handle):
            raise RuntimeError("another local candidate audit owns this output")
        try:
            return _run(inputs, conditions, output, repo_root, groups, horizons, max_frame_bytes, max_seconds)
        finally:
            release_os_lock(handle)


def _run(
    inputs: AuditInputs,
    conditions: Path,
    output: Path,
    repo_root: Path,
    groups: tuple[str, ...],
    horizons: tuple[int, ...],
    max_frame_bytes: int,
    max_seconds: float,
) -> dict[str, Any]:
    before = resource_sample()
    deadline = time.monotonic() + max_seconds
    source = read_json(conditions / "run-receipt.json")
    scope = source.get("parameters", {})
    if any(
        scope.get(name) != value
        for name, value in {"target": "B1", "phase": "conditions", "original_source_id": inputs.source_id, "original_input_id": inputs.input_id}.items()
    ):
        raise ValueError("original conditions receipt scope differs")
    verified: dict[Path, bytes] = {}

    def final_bytes(name: str) -> bytes:
        record = source["results"][name]
        locator = Path(record["path"])
        path = checked_path(locator if locator.is_absolute() else repo_root / locator)
        if not path.is_relative_to(conditions) or path != checked_path(conditions / name):
            raise ValueError("original final result escaped its conditions root")
        if path not in verified:
            import hashlib

            payload = path.read_bytes()
            if len(payload) != record["bytes"] or hashlib.sha256(payload).hexdigest() != record["sha256"]:
                raise ValueError("original final result differs from its receipt")
            verified[path] = payload
        return verified[path]

    # Selection itself is an original final result, not reselected from outcomes.
    import json

    if min(PATTERNS) != "B1":
        raise ValueError("local audit requires the original lexically first B1 family")
    selected = select_audit_candidates({"B1": json.loads(final_bytes("B1-selection.json"))})
    if not selected:
        raise ValueError("original selection has no candidate audit sample")
    fingerprint = fingerprint_inputs([
        InputSpec("original_conditions_receipt", conditions / "run-receipt.json", live_producer=False),
        InputSpec("original_selection", conditions / "B1-selection.json", live_producer=False),
    ])
    tracked_sources = [Path(__file__).resolve()] if Path(__file__).resolve().is_relative_to(repo_root) else []
    mission = repo_root / "tasks/20261013-pattern-scan/mission.md"
    if mission.is_file():
        tracked_sources.append(mission)
    started_code = code_identity(repo_root, sources=tracked_sources)
    cases = []
    for group in groups:
        for horizon in horizons:
            pending = []
            for index, candidate in enumerate(selected):
                scope = {
                    "target": "B1",
                    "candidate": candidate,
                    "group": group,
                    "horizon": horizon,
                    "original_source_id": inputs.source_id,
                    "original_input_id": inputs.input_id,
                    "stocks": list(inputs.codes),
                }
                destination = output / f"{quote(group, safe='')}-h{horizon}-c{index + 1}"
                reused = _reuse_case(destination, {"scope": scope})
                if reused is None:
                    pending.append((candidate, destination, scope))
                else:
                    cases.append({**reused, "reused": True})
                    LOGGER.info("Reuse completed candidate audit group=%s H=%d candidate=%s", group, horizon, candidate["candidate_id"])
            if not pending:
                continue
            feature_ids = sorted({atom["feature_id"] for candidate, _, _ in pending for atom in candidate["atoms"]})
            columns = list(
                dict.fromkeys([
                    *REQUIRED_COLUMNS,
                    "event_eligibility_excluded",
                    "mkt",
                    *(f"{feature}_{suffix}" for feature in feature_ids for suffix in ("bin", "status")),
                ])
            )
            frames, frame_bytes = [], 0
            binding_start = resource_sample()
            for number, code in enumerate(inputs.codes, 1):
                if time.monotonic() > deadline:
                    raise TimeoutError("local candidate audit exceeded its time limit")
                bound = inputs.bound("B1", code)
                frame = group_frame(bound, group, horizon).loc[:, columns].copy()
                frame_bytes += int(frame.memory_usage(index=True, deep=True).sum())
                if frame_bytes > max_frame_bytes:
                    raise ValueError("candidate audit collected frame bytes exceed memory limit")
                frames.append(frame)
                del bound, frame
                if number % 100 == 0 or number == len(inputs.codes):
                    LOGGER.info("Audit input group=%s H=%d stocks=%d/%d slim_bytes=%d", group, horizon, number, len(inputs.codes), frame_bytes)
            binding = phase_receipt("original_slim_group_read", binding_start, resource_sample())
            metadata = {"pattern_id": "B1", "control_id": "pattern" if group == "pattern:union" else group, "cohort_id": "union", "horizon": horizon}
            if group != "pattern:union":
                metadata["primary_control_id"] = "C-52w"
            for candidate, destination, scope in pending:
                if time.monotonic() > deadline:
                    raise TimeoutError("local candidate audit exceeded its time limit")
                started = resource_sample()
                rebuilt = reconstruct_candidate(frames, metadata=metadata, candidate_id=candidate["candidate_id"], atoms=candidate["atoms"])
                stored = {}
                for family in ("summary", "annual"):
                    filename = f"B1-{quote(group, safe='')}-h{horizon}-{family}.parquet"
                    matches = [name for name in source["results"] if Path(name).name == filename]
                    if len(matches) != 1:
                        raise ValueError("candidate audit source final table is missing or ambiguous")
                    stored[family] = pq.read_table(
                        io.BytesIO(final_bytes(matches[0])),
                        filters=[("feature_id", "==", "candidate"), ("candidate_id", "==", candidate["candidate_id"]), ("split", "==", "cross-check")],
                    ).to_pandas()
                counts = compare_candidate(rebuilt, stored_summary=stored["summary"], stored_annual=stored["annual"])
                if counts["aggregate_checks"] != 1368:
                    raise ValueError("candidate audit comparison coverage differs")
                case = {
                    "candidate_id": candidate["candidate_id"],
                    "group": group,
                    "horizon": horizon,
                    **counts,
                    "slim_frame_bytes": frame_bytes,
                    "input_measurement": binding,
                    "measurement": phase_receipt("independent_candidate_compare", started, resource_sample()),
                }
                _write_case(
                    destination, rebuilt, {"scope": scope, "case": case, "original_code": inputs.original_code}, fingerprint, inputs, repo_root, started_code
                )
                cases.append(case)
                LOGGER.info(
                    "Completed candidate audit group=%s H=%d rows=%d candidate=%s", group, horizon, counts["aggregate_checks"], candidate["candidate_id"]
                )
                del rebuilt, stored
            del frames
    overview = {
        "definition": DEFINITION,
        "audit_complete": len(selected) == 5 and set(groups) == set(GROUPS) and set(horizons) == {126, 252} and len(cases) == 40,
        "selected_candidate_n": len(selected),
        "completed_case_n": len(cases),
        "aggregate_checks": sum(case["aggregate_checks"] for case in cases),
        "original_stock_n": len(inputs.codes),
        "event_files_written": 0,
        "input_or_intermediate_hashes_added": False,
        "cases": cases,
        "measurement": phase_receipt("local_candidate_audit", before, resource_sample()),
    }
    write_progress(output / "progress.json", overview)
    if overview["audit_complete"]:
        path = output / "audit-summary.json"
        receipt_path = output / "run-receipt.json"
        if receipt_path.exists():
            saved = read_json(receipt_path)
            record = saved.get("results", {}).get(path.name, {})
            if (
                saved.get("definition") != DEFINITION
                or record.get("path") != str(path)
                or path.stat().st_size != record.get("bytes")
                or file_digest(path) != record.get("sha256")
            ):
                raise ValueError("completed audit summary final result differs")
        else:
            write_json(path, overview)
            write_run_receipt(
                receipt_path,
                run_id=output.name,
                definition=DEFINITION,
                parameters={
                    "expected_cases": 40,
                    "expected_comparison_rows": 54720,
                    "original_code": inputs.original_code,
                    "original_source_id": inputs.source_id,
                    "original_input_id": inputs.input_id,
                },
                inputs=fingerprint,
                results={path.name: path},
                repo_root=repo_root,
                shared_data=[inputs.shared_record],
                expected_code=started_code if started_code.get("commit") else None,
            )
    return overview
