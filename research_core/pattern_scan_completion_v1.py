"""Bounded Q4--Q6 follow-through with unchanged original-event price clocks."""

from __future__ import annotations

import logging
import uuid
from dataclasses import fields
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core.artifact_store import describe_file, file_digest, object_digest, publish_noreplace, read_json, verify_files, write_json
from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_analysis_v1 import group_frame
from research_core.pattern_scan_barrier_v1 import verify_barrier
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_episode_run_v1 import run_episodes
from research_core.pattern_scan_execution_v1 import verify_source
from research_core.pattern_scan_failure_summary_v1 import FailureAccumulator
from research_core.pattern_scan_followup_summary_v1 import FollowupAccumulator
from research_core.pattern_scan_followup_v1 import FollowupTables, followup_values
from research_core.pattern_scan_holding_v1 import holding_values
from research_core.pattern_scan_parquet_v1 import read_frame
from research_core.pattern_scan_reporting_v1 import candidate_membership, top_confirmation_candidates
from research_core.pattern_scan_shared_v1 import SharedInputs
from research_core.research_data_paths import _checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample

LOGGER = logging.getLogger(__name__)


def complete_followup(
    parts: dict[str, Path],
    barrier: dict[str, Any],
    event_parts: dict[str, dict[str, Path]],
    selections: dict[str, Any],
    summaries: dict[str, Any],
    output: Path,
    *,
    source: dict[str, Any],
    input_id: str,
    shared: SharedInputs | None = None,
) -> dict[str, Any]:
    """Reuse each original union event's observations in retained candidates."""
    verify_source(source)
    if shared is not None:
        shared.validate_scope(tuple(parts), source, input_id)
    output = _checked_path(output)
    output.mkdir(parents=True, exist_ok=True)
    before = resource_sample()
    confirmation = pd.DataFrame(summaries["confirmation_top_input"])
    top: dict[str, tuple[str, ...]] = top_confirmation_candidates(confirmation) if not confirmation.empty else {target: () for target in PATTERNS}
    for target in PATTERNS:
        top.setdefault(target, ())
    if sum(1 + len(top[target]) for target in PATTERNS) > 132:
        raise ValueError("Q4--Q6 registered group cap exceeded")
    episodes = run_episodes(
        parts,
        barrier,
        event_parts,
        selections,
        top,
        output / "episodes",
        source=source,
        input_id=input_id,
        **({"shared": shared} if shared is not None else {}),
    )
    global_directory = verify_barrier(barrier)
    context = (read_frame(global_directory / "context.parquet") if shared is None else shared.read_sidecar("context")).set_index("Date")
    close_matrix = read_frame(global_directory / "close_matrix.parquet") if shared is None else shared.read_sidecar("close_matrix")
    jump_matrix = read_frame(global_directory / "jump_matrix.parquet") if shared is None else shared.read_sidecar("jump_matrix")
    benchmark = read_frame(global_directory / "benchmark.parquet") if shared is None else shared.read_sidecar("benchmark")
    industries = {
        f"TW:{code}": str(
            (
                read_frame(directory / "common_values.parquet", columns=["industry_ref"])
                if shared is None
                else shared.read_stock(code, "common_values", columns=["industry_ref"])
            )["industry_ref"].iloc[0]
        )
        for code, directory in parts.items()
    }
    union_anchors = {
        f"TW:{code}": sorted({int(day) for target in PATTERNS for day in group_frame(event_parts[target][code], "pattern:union", 126).calendar_index})
        for code in parts
    }
    holding_identity = {
        "source_id": source["source_id"],
        "input_id": input_id,
        "sidecars": barrier["sidecars"],
        "anchors": union_anchors,
        "industries": industries,
        **({"shared_read_pins": shared.pins} if shared is not None else {}),
    }
    holding_directory = output / f"holding-{object_digest(holding_identity)}"
    holding_path = holding_directory / "holding-context.parquet"
    holding_receipt_path = holding_directory / "receipt.json"
    if holding_directory.exists():
        holding_receipt = read_json(holding_receipt_path)
        if (
            holding_receipt.get("identity") != holding_identity
            or holding_receipt.get("complete") is not True
            or file_digest(holding_path) != holding_receipt["sha256"]
        ):
            raise ValueError("existing holding identity differs or incomplete")
    else:
        holding = holding_values(
            close_matrix,
            industries,
            cast(pd.Series, benchmark["Close"]),
            cast(pd.Series, context["retrospective_state"]),
            jump_matrix=jump_matrix,
            benchmark_jump=cast(pd.Series, benchmark["quality_reason"]).fillna("").str.contains("unexplained.*jump", regex=True),
            anchors=union_anchors,
        )
        staging = output / f".staging-{holding_directory.name}-{uuid.uuid4().hex}"
        staging.mkdir()
        staging_path = staging / holding_path.name
        with staging_path.open("xb") as stream:
            holding.to_parquet(stream, index=False)
        verify_barrier(barrier)
        verify_source(source)
        write_json(staging / "receipt.json", {"complete": True, "identity": holding_identity, "sha256": file_digest(staging_path)})
        publish_noreplace(staging, holding_directory)
    files: dict[str, str] = {"holding_context.parquet": str(holding_path)}
    for target in PATTERNS:
        selected = {row["candidate_id"]: tuple(Atom(**atom) for atom in row["atoms"]) for row in selections[target]["candidates"]}
        groups = {target: target, **{identifier: target for identifier in top[target]}}
        target_identity = {
            "target": target,
            "source_id": source["source_id"],
            "input_id": input_id,
            "top_candidates": list(top[target]),
            "event_receipts": {code: file_digest(directory / "receipt.json") for code, directory in event_parts[target].items()},
            **({"shared_read_pins": shared.pins} if shared is not None else {}),
        }
        target_summary = output / f"summary-{object_digest(target_identity)}"
        if target_summary.exists():
            saved = read_json(target_summary / "receipt.json")
            if saved.get("identity") != target_identity or saved.get("complete") is not True:
                raise ValueError("existing followup summary differs or incomplete")
            verify_files(output, saved["artifacts"])
            files.update(saved["files"])
            continue
        target_files: dict[str, str] = {}
        accumulator = FollowupAccumulator(groups)
        failure = FailureAccumulator(groups)
        for code, directory in sorted(event_parts[target].items()):
            original = pd.concat([group_frame(directory, "pattern:union", horizon) for horizon in (126, 252)], ignore_index=True)
            stock_directory = parts[code]
            indicator = read_frame(stock_directory / "indicators.parquet") if shared is None else shared.read_stock(code, "indicators")
            pivots = read_frame(stock_directory / "pivots.parquet") if shared is None else shared.read_stock(code, "pivots")
            identity = {
                "stock": code,
                "target": target,
                "source_id": source["source_id"],
                "input_id": input_id,
                "event_receipt_sha256": file_digest(directory / "receipt.json"),
                "top_candidates": list(top[target]),
                **({"shared_read_pins": shared.pins} if shared is not None else {}),
            }
            destination = output / object_digest(identity)
            if destination.exists():
                receipt = read_json(destination / "receipt.json")
                if receipt.get("identity") != identity or receipt.get("complete") is not True:
                    raise ValueError("existing followup identity differs or incomplete")
                verify_files(destination, receipt["artifacts"])
                base = FollowupTables(*(read_frame(destination / f"{field.name}.parquet") for field in fields(FollowupTables)))
            else:
                base = followup_values(original, indicator, pivots)
                staging = output / f".staging-{destination.name}-{uuid.uuid4().hex}"
                staging.mkdir()
                artifacts = []
                for field in fields(FollowupTables):
                    path = staging / f"{field.name}.parquet"
                    with path.open("xb") as stream:
                        getattr(base, field.name).to_parquet(stream, index=False)
                    artifacts.append(describe_file(staging, path))
                verify_source(source)
                verify_files(staging, artifacts)
                write_json(
                    staging / "receipt.json", {"schema": "pattern-scan-followup-part.v1", "complete": True, "identity": identity, "artifacts": artifacts}
                )
                publish_noreplace(staging, destination)
            memberships = {target: set(original.event_id)}
            first_horizon = original.loc[original.horizon.eq(126)]
            for identifier in top[target]:
                matched = candidate_membership(first_horizon, selected[identifier]) == 1
                memberships[identifier] = set(first_horizon.loc[matched, "event_id"])
            market_by_id = original.drop_duplicates("event_id").set_index("event_id")["mkt"]
            chunks: dict[str, list[pd.DataFrame]] = {field.name: [] for field in fields(FollowupTables)}
            for group, ids in memberships.items():
                for field in fields(FollowupTables):
                    frame = getattr(base, field.name)
                    frame = frame.loc[frame.event_id.isin(ids)].copy()
                    frame["group_id"], frame["target_pattern_id"] = group, target
                    frame["mkt"] = frame.event_id.map(market_by_id)
                    chunks[field.name].append(frame)
            bound = FollowupTables(*(pd.concat(chunks[field.name], ignore_index=True) for field in fields(FollowupTables)))
            accumulator.add_stock(bound)
            holding_stock = read_frame(holding_path, filters=[("security_id", "==", f"TW:{code}")])
            failure.add_stock(bound, holding_stock)
            for field in fields(FollowupTables):
                target_files[f"observations/{target}/{object_digest(code)}/{field.name}.parquet"] = str(destination / f"{field.name}.parquet")
        results = accumulator.finalize()
        failures = failure.finalize()
        summary_tables = {field.name: getattr(result, field.name) for result in (results, failures) for field in fields(result)}
        target_staging = output / f".staging-{target_summary.name}-{uuid.uuid4().hex}"
        target_staging.mkdir()
        for name, table in summary_tables.items():
            path = target_staging / f"{name}.parquet"
            with path.open("xb") as stream:
                table.to_parquet(stream, index=False)
            target_files[f"{target}/{name}.parquet"] = str(target_summary / path.name)
        descriptors = [describe_file(output, Path(path)) for path in target_files.values() if Path(path).parent != target_summary]
        for name in summary_tables:
            record = describe_file(target_staging, target_staging / f"{name}.parquet")
            descriptors.append({**record, "path": f"{target_summary.name}/{record['path']}"})
        verify_source(source)
        verify_barrier(barrier)
        for code, directory in event_parts[target].items():
            if file_digest(directory / "receipt.json") != target_identity["event_receipts"][code]:
                raise ValueError("followup event ancestor changed during computation")
            verify_files(directory, read_json(directory / "receipt.json")["artifacts"])
        write_json(target_staging / "receipt.json", {"complete": True, "identity": target_identity, "artifacts": descriptors, "files": target_files})
        publish_noreplace(target_staging, target_summary)
        verify_files(output, descriptors)
        files.update(target_files)
        LOGGER.info("Completed bounded Q5/Q6 target=%s groups=%d memory=%d", target, len(groups), accumulator.memory_nbytes)
    verify_source(source)
    verify_barrier(barrier)
    receipt = {
        "schema": "pattern-scan-q4-q5-q6.v1",
        "complete": True,
        "source_id": source["source_id"],
        "input_id": input_id,
        "top_candidates": top,
        "episodes": episodes,
        "files": files,
        "measurement": phase_receipt("q4_q5_q6_followup", before, resource_sample()),
        **({"shared_read_pins": shared.pins} if shared is not None else {}),
    }
    receipt_path = output / "receipt.json"
    if receipt_path.exists():
        saved = read_json(receipt_path, max_bytes=64_000_000)
        if any(
            object_digest(saved.get(key)) != object_digest(receipt.get(key))
            for key in ("source_id", "input_id", "top_candidates", "episodes", "files", "shared_read_pins")
        ):
            raise ValueError("existing completed followup differs")
        return saved
    write_json(receipt_path, receipt)
    return receipt
