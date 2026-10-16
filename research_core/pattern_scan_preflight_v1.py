"""Bounded resource observations on explicitly representative completed parts."""

from __future__ import annotations

import logging
from dataclasses import fields
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.artifact_store import describe_file, object_digest, read_json, safe_path, verify_files, write_json
from research_core.pattern_scan_analysis_v1 import group_frame, prepare_event_parts
from research_core.pattern_scan_barrier_v1 import build_barrier
from research_core.pattern_scan_count_matrix_v1 import aggregate_memberships
from research_core.pattern_scan_dense_counts_v1 import DenseCounts
from research_core.pattern_scan_execution_v1 import verify_source
from research_core.pattern_scan_followup_summary_v1 import FollowupAccumulator
from research_core.pattern_scan_followup_v1 import followup_values
from research_core.pattern_scan_holding_v1 import holding_values
from research_core.pattern_scan_membership_v1 import membership_inventory, stock_memberships
from research_core.pattern_scan_parquet_v1 import read_frame
from research_core.research_measurement_v1 import phase_receipt, resource_sample

LOGGER = logging.getLogger(__name__)
MAX_STOCKS = 4
EVENTS_PER_STOCK = 4
TARGET = "H1"
HORIZON = 126
LANDMARKS = (5,)


def split_audit(prepared: pd.DataFrame) -> dict[str, Any]:
    """Observe the fixed 0050 split-date transition; never infer factor validity."""
    split_date = pd.Timestamp("2025-06-18")
    if not isinstance(prepared.index, pd.DatetimeIndex) or not prepared.index.is_unique or not prepared.index.is_monotonic_increasing:
        raise ValueError("split audit requires the supplied ordered research-price calendar")
    required = {"Close", "RawClose", "Quality", "quality_reason"}
    if not required.issubset(prepared):
        return {"status": "unknown", "reason": "missing_prepared_price_columns", "split_date": "2025-06-18"}
    calendar = cast(pd.DatetimeIndex, prepared.index)
    if split_date not in calendar:
        return {"status": "unknown", "reason": "split_date_not_in_supplied_calendar", "split_date": "2025-06-18"}
    location = int(cast(int, calendar.get_loc(split_date)))
    raw_before = cast(pd.Series, pd.to_numeric(cast(pd.Series, prepared.iloc[:location]["RawClose"]), errors="coerce")).to_numpy(dtype=float)
    observed_before = np.flatnonzero(np.isfinite(raw_before) & (raw_before > 0))
    if not len(observed_before):
        return {"status": "unknown", "reason": "previous_common_session_unavailable", "split_date": "2025-06-18"}
    previous = int(observed_before[-1])
    pair = cast(pd.DataFrame, prepared.iloc[[previous, location]])
    record: dict[str, Any] = {
        "status": "observed",
        "reason": None,
        "split_date": "2025-06-18",
        "previous_date": cast(pd.Timestamp, calendar[previous]).strftime("%Y-%m-%d"),
        "quality": pair["Quality"].tolist(),
        "quality_reason": pair["quality_reason"].where(pair["quality_reason"].notna(), None).tolist(),
        "suspended_or_missing_calendar_slots": location - previous - 1,
        "factor_validity": "not_certified_by_transition_observation",
    }
    if "restatement_factor" in pair:
        factors = pair["restatement_factor"].to_numpy(dtype=float, na_value=np.nan)
        ratio = float(factors[0] / factors[1]) if bool(np.isfinite(factors).all() and (factors > 0).all()) else None
        record["restatement_factor_ratio"] = ratio
        record["declared_split_factor"] = 0.25
        record["split_factor_consistent"] = None if ratio is None else bool(np.isclose(ratio, 0.25, rtol=1e-12, atol=0))
    for column, key in (("Close", "adjusted_close"), ("RawClose", "raw_close")):
        values = pair[column].to_numpy(dtype=float, na_value=np.nan)
        known = bool(np.isfinite(values).all() and (values > 0).all())
        record[f"{key}_values"] = [float(value) if np.isfinite(value) else None for value in values]
        record[f"{key}_ratio"] = float(values[1] / values[0]) if known else None
        if not known:
            record["status"], record["reason"] = "unknown", "transition_prices_unusable"
    return record


def _save(output: Path, name: str, table: pd.DataFrame, artifacts: list[dict[str, Any]]) -> None:
    path = safe_path(output / name)
    with path.open("xb") as stream:
        table.to_parquet(stream, index=False, compression="zstd")
    artifacts.append(describe_file(output, path))


def profile_global(parts: dict[str, Path], benchmark: pd.DataFrame, output: Path, *, source: dict[str, Any], input_id: str) -> dict[str, Any]:
    """Measure representative global/binding/summary/followup work without publish.

    The supplied stock grid is complete only for the declared representative
    subset. H/J/K3/peers measured here are not formal all-market research values.
    Probe caps and first-by-date samples are resource controls, not acceptance
    rules. Absolute source/input identities are verified before and after work.
    """
    if not 1 <= len(parts) <= MAX_STOCKS:
        raise ValueError("preflight requires one to four explicit representative stock parts")
    verify_source(source)
    label_pins: dict[str, Any] = {}
    for code, directory in sorted(parts.items()):
        receipt = read_json(safe_path(directory / "receipt.json"))
        if receipt.get("complete") is not True or receipt.get("source_id") != source["source_id"] or receipt.get("input_id") != input_id:
            raise ValueError("representative part is incomplete or has different source/input")
        verify_files(directory, receipt["artifacts"])
        labels = [record for record in receipt["artifacts"] if record["path"] == "base_labels.parquet"]
        if len(labels) != 1:
            raise ValueError("representative label payload pin is required")
        label_pins[code] = labels[0]
    output = safe_path(output)
    if output.exists():
        raise ValueError("preflight output must be new exclusive scratch")
    output.mkdir(parents=True)
    phases: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    before = resource_sample()
    barrier = build_barrier(parts, benchmark, output / "barrier")
    phases.append(phase_receipt("representative_global_barrier", before, resource_sample()))
    # These label references explicitly belong to this representative probe;
    # they are not published formal shared label versions.
    entries = {
        "labels": {
            "version_id": f"preflight-only:{object_digest({'source': source['source_id'], 'input': input_id, 'labels': label_pins})}",
            "manifest": {"sha256": object_digest(label_pins)},
        }
    }
    before = resource_sample()
    event_parts = prepare_event_parts(parts, barrier, entries, output / "events", source=source, input_id=input_id)
    phases.append(phase_receipt("representative_event_binding", before, resource_sample()))
    base_metadata = {"pattern_id": TARGET, "control_id": "pattern", "cohort_id": "union", "horizon": HORIZON}
    before = resource_sample()
    inventory = membership_inventory(base_metadata)
    identifiers = tuple(object_digest(row) for row in inventory)
    counts = DenseCounts(identifiers, HORIZON)
    event_n = membership_n = matrix_n = 0
    samples: dict[str, pd.DataFrame] = {}
    for code, directory in sorted(event_parts[TARGET].items()):
        events = group_frame(directory, "pattern:union", HORIZON)
        memberships = stock_memberships(events, inventory, max_membership_rows=2_000_000)
        matrix = aggregate_memberships(events, memberships)
        counts.add_stock(matrix)
        event_n += len(events)
        membership_n += len(memberships)
        matrix_n += len(matrix)
        samples[code] = events.sort_values(["calendar_index", "event_id"], kind="stable").iloc[:EVENTS_PER_STOCK].copy()
    phases.append(phase_receipt("representative_one_group_integer_feed", before, resource_sample()))
    before = resource_sample()
    rows = [{**metadata, "cell_id": identifier, **counts.summarize(identifier)} for metadata, identifier in zip(inventory, identifiers, strict=True)]
    _save(output, "representative-summary.parquet", pd.DataFrame(rows), artifacts)
    phases.append(phase_receipt("representative_one_group_summary_serialization", before, resource_sample()))
    before = resource_sample()
    accumulator = FollowupAccumulator({"preflight:H1:original": TARGET}, horizons=(HORIZON,), landmarks_at=LANDMARKS)
    sample_n = flag_n = landmark_n = 0
    selected_anchors: dict[str, list[int]] = {}
    sample_ids: dict[str, list[str]] = {}
    industries: dict[str, str] = {}
    for code, directory in sorted(parts.items()):
        indicators = read_frame(directory / "indicators.parquet")
        pivots = read_frame(directory / "pivots.parquet")
        common = read_frame(directory / "common_values.parquet", columns=["industry_ref"])
        classifications = common.industry_ref.dropna().unique()
        if len(classifications) != 1:
            raise ValueError("representative holding industry must be a fixed reference value")
        industries[f"TW:{code}"] = str(classifications[0])
        events = samples[code]
        sample_ids[code] = events.event_id.tolist()
        selected_anchors[f"TW:{code}"] = events.calendar_index.astype(int).tolist()
        followup = followup_values(events, indicators, pivots, horizons=(HORIZON,), landmarks=LANDMARKS)
        markets = events.set_index("event_id")["mkt"]
        for field in fields(followup):
            table = getattr(followup, field.name)
            table["group_id"] = "preflight:H1:original"
            table["target_pattern_id"] = TARGET
            table["mkt"] = table.event_id.map(markets)
            _save(output, f"{object_digest(code)}-{field.name}.parquet", table, artifacts)
        accumulator.add_stock(followup)
        sample_n += len(events)
        flag_n += len(followup.flags)
        landmark_n += len(followup.landmarks)
    phases.append(phase_receipt("representative_first_by_date_followup", before, resource_sample()))
    before = resource_sample()
    close_matrix = read_frame(output / "barrier" / "close_matrix.parquet")
    jumps = read_frame(output / "barrier" / "jump_matrix.parquet")
    context = read_frame(output / "barrier" / "context.parquet")
    retrospective = pd.Series(context.retrospective_state.to_numpy(), index=benchmark.index)
    benchmark_jump = (
        cast(pd.Series, benchmark["quality_reason"])
        .fillna("")
        .map(lambda value: bool(set(str(value).split("|")) & {"unexplained_jump", "unexplained_adjusted_jump"}))
        if "quality_reason" in benchmark
        else None
    )
    holding = holding_values(
        close_matrix,
        industries,
        cast(pd.Series, benchmark["Close"]),
        retrospective,
        horizons=(HORIZON,),
        jump_matrix=jumps,
        benchmark_jump=benchmark_jump,
        anchors=selected_anchors,
    )
    _save(output, "representative-holding.parquet", holding, artifacts)
    phases.append(phase_receipt("representative_first_by_date_holding", before, resource_sample()))
    before = resource_sample()
    followup_summary = accumulator.finalize()
    summary_rows = 0
    for field in fields(followup_summary):
        table = getattr(followup_summary, field.name)
        summary_rows += len(table)
        _save(output, f"representative-{field.name}.parquet", table, artifacts)
    phases.append(phase_receipt("representative_followup_summary_serialization", before, resource_sample()))
    verify_source(source)
    for directory in parts.values():
        receipt = read_json(directory / "receipt.json")
        verify_files(directory, receipt["artifacts"])
    verify_files(output, artifacts)
    work = {
        "representative_security_n": len(parts),
        "calendar_n": len(benchmark),
        "stock_calendar_rows": len(parts) * len(benchmark),
        "bound_targets_n": 12,
        "summary_groups_n": 1,
        "summary_horizons": [HORIZON],
        "summary_cell_n": len(inventory),
        "summary_event_n": event_n,
        "membership_rows": membership_n,
        "stock_cell_year_rows": matrix_n,
        "dense_numeric_bytes": counts.memory_nbytes,
        "sample_event_n": sample_n,
        "event_cap_per_stock": EVENTS_PER_STOCK,
        "followup_flag_rows": flag_n,
        "landmark_rows": landmark_n,
        "holding_rows": len(holding),
        "followup_summary_rows": summary_rows,
        "serialized_bytes": sum(record["bytes"] for record in artifacts),
    }
    receipt = {
        "schema": "pattern-scan-preflight.v1",
        "complete": True,
        "source_id": source["source_id"],
        "input_id": input_id,
        "scope": "representative fixed stock subset only; not a complete market universe",
        "security_codes": sorted(parts),
        "sample_rule": "H1 original union H126; first calendar_index/event_id order, at most four per stock; no outcome filtering",
        "sample_event_ids": sample_ids,
        "phases": phases,
        "work_sizes": work,
        "artifacts": artifacts,
        "split_audit": split_audit(benchmark),
        "extrapolation": {
            "status": "unknown",
            "reason": "complete target work sizes and cross-sectional scaling not measured",
            "observed_global_wall_seconds_per_stock_calendar_row": phases[0]["wall_seconds"] / work["stock_calendar_rows"],
            "observed_followup_wall_seconds_per_event": phases[4]["wall_seconds"] / sample_n if sample_n else None,
            "caveat": "Observed ratios only; quantiles, global barriers and zero-cell serialization need not scale linearly.",
        },
        "limitations": [
            "Representative ranks/peers are resource probes and cannot be consumed as formal market outcomes.",
            "Process lifetime peak is not isolated phase peak; unavailable native I/O/memory stays null.",
            "0050 split transition is an observation, not source/factor certification.",
        ],
    }
    write_json(output / "receipt.json", receipt)
    LOGGER.info("Representative preflight complete stocks=%d sampled_events=%d", len(parts), sample_n)
    return receipt
