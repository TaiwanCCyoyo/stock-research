"""Bounded event, selection and full-cell analysis for the approved scan."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core.artifact_store import describe_file, file_digest, object_digest, publish_noreplace, read_json, verify_files, write_json
from research_core.hhhl_variants_selection import Atom, SelectionEvent
from research_core.pattern_scan_barrier_v1 import metadata
from research_core.pattern_scan_candidate_coverage_v1 import CandidateCoverage
from research_core.pattern_scan_classification_cache_v1 import ConditionClassificationCache
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_count_matrix_v1 import aggregate_memberships
from research_core.pattern_scan_dense_counts_v1 import DenseCounts
from research_core.pattern_scan_event_conditions_v1 import atoms_for_pattern
from research_core.pattern_scan_event_tables_v1 import build_event_tables
from research_core.pattern_scan_execution_v1 import ROOT, verify_source
from research_core.pattern_scan_groups_v1 import PRIMARY
from research_core.pattern_scan_inputs_v1 import read_preparation_pins
from research_core.pattern_scan_membership_v1 import membership_inventory, stock_memberships
from research_core.pattern_scan_parquet_v1 import read_frame, write_frame
from research_core.pattern_scan_selection_v1 import select_pattern_candidates
from research_core.pattern_scan_shared_v1 import SharedInputs, load_shared
from research_core.pattern_scan_summary_store_v1 import YEARS
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_file_bundle_v1 import publish_file_bundle
from research_core.research_data_paths import DataRoots, _checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample

LOGGER = logging.getLogger(__name__)
STOCK_TABLES = ("prices", "indicators", "pivots", "common_values", "universe", "pattern_states", "cohort_events", "controls", "base_labels")


def _write_frame(path: Path, table: pd.DataFrame) -> None:
    with _checked_path(path).open("xb") as stream:
        write_frame(table, stream, index=False)


def prepare_event_parts(
    parts: dict[str, Path],
    barrier: dict[str, Any],
    entries: dict[str, dict[str, Any]],
    output: Path,
    *,
    source: dict[str, Any],
    input_id: str,
    shared: SharedInputs | None = None,
) -> dict[str, dict[str, Path]]:
    """One complete per-stock/target receipt; interrupted staging is retained."""
    verify_source(source)
    if shared is not None:
        shared.validate_scope(tuple(parts), source, input_id)
        if shared.entries != entries:
            raise ValueError("event shared catalog entries differ from supplied pins")
    output = _checked_path(output)
    output.mkdir(parents=True, exist_ok=True)
    collected: dict[str, dict[str, Path]] = {target: {} for target in PATTERNS}
    pins = {kind: {"version_id": entry["version_id"], "manifest_sha256": entry["manifest"]["sha256"]} for kind, entry in entries.items()}
    for code, directory in sorted(parts.items()):
        part_receipt = read_json(directory / "receipt.json")
        if part_receipt["source_id"] != source["source_id"] or part_receipt["input_id"] != input_id:
            raise ValueError("event stock part source/input differs")
        verify_files(directory, part_receipt["artifacts"])
        global_record = barrier["global_files"][code]
        global_path = _checked_path(Path(global_record["path"]))
        if file_digest(global_path) != global_record["sha256"]:
            raise ValueError("event global feature part changed")
        tables = {name: read_frame(directory / f"{name}.parquet") if shared is None else shared.read_stock(code, name) for name in STOCK_TABLES}
        global_values = read_frame(global_path) if shared is None else shared.read_global(code)
        classification_cache = ConditionClassificationCache()
        for target in PATTERNS:
            identity = {
                "code": code,
                "target": target,
                "source_id": source["source_id"],
                "input_id": input_id,
                "shared_pins": pins,
                "global_sha256": global_record["sha256"],
                "stock_request_id": part_receipt["request_id"],
                **({"shared_read_pins": shared.pins} if shared is not None else {}),
            }
            destination = _checked_path(output / object_digest(identity))
            if destination.exists():
                receipt = read_json(destination / "receipt.json")
                if receipt.get("identity") != identity or receipt.get("complete") is not True:
                    raise ValueError("existing event part identity differs or incomplete")
                verify_files(destination, receipt["artifacts"])
                collected[target][code] = destination
                continue
            before = resource_sample()
            bound = build_event_tables(
                target,
                tables,
                global_values,
                security_id=f"TW:{code}",
                definition_id=source["source_id"],
                input_id=input_id,
                base_label_version_id=entries["labels"]["version_id"],
                base_label_manifest_sha256=entries["labels"]["manifest"]["sha256"],
                classification_cache=classification_cache,
            )
            staging = output / f".staging-{destination.name}-{uuid.uuid4().hex}"
            staging.mkdir()
            frames = {
                "events": bound.events,
                "conditions": bound.conditions,
                "group_memberships": bound.group_memberships,
                "daily_groups": pd.DataFrame(bound.daily_groups),
                "formula_groups": pd.DataFrame(bound.formula_groups),
            }
            for name, frame in frames.items():
                if name in {"daily_groups", "formula_groups"}:
                    frame = frame.reset_index()
                _write_frame(staging / f"{name}.parquet", frame)
            artifacts = [describe_file(staging, staging / f"{name}.parquet") for name in frames]
            verify_source(source)
            verify_files(staging, artifacts)
            write_json(
                staging / "receipt.json",
                {
                    "schema": "pattern-scan-event-part.v1",
                    "complete": True,
                    "identity": identity,
                    "artifacts": artifacts,
                    "measurement": phase_receipt("event_projection_conditions", before, resource_sample()),
                },
            )
            publish_noreplace(staging, destination)
            collected[target][code] = destination
        LOGGER.info("Bound all event tables stock=%s", code)
    return collected


def group_frame(directory: Path, group: str, horizon: int) -> pd.DataFrame:
    """One stock, exact retained group, own event projection and condition rows."""
    events = read_frame(directory / "events.parquet", filters=[("horizon", "==", horizon)])
    memberships = read_frame(directory / "group_memberships.parquet", filters=[("group_id", "==", group)])
    conditions = read_frame(directory / "conditions.parquet")
    joined = memberships.merge(events, on="event_id", how="left", validate="one_to_one").merge(conditions, on="event_id", how="left", validate="one_to_one")
    joined["mkt"] = joined["MKT"].fillna("unknown")
    return joined


def select_all(event_parts: dict[str, dict[str, Path]]) -> dict[str, Any]:
    """Select once from original eligible development H126 union events."""
    selected: dict[str, Any] = {}
    for target in PATTERNS:
        atoms = atoms_for_pattern(target)
        by_key = {(atom.feature_id, atom.bin_id): atom for atom in atoms}
        rows: list[SelectionEvent] = []
        for code, directory in sorted(event_parts[target].items()):
            frame = group_frame(directory, "pattern:union", 126)
            for row in frame.loc[frame.event_main_eligible.astype(bool)].to_dict("records"):
                observed = frozenset(
                    by_key[(feature, row[f"{feature}_bin"])]
                    for feature in {atom.feature_id for atom in atoms}
                    if row[f"{feature}_status"] == "known" and (feature, row[f"{feature}_bin"]) in by_key
                )
                rows.append(SelectionEvent(row["event_id"], code, "union", 126, bool(row["calendar_full"]), row["effective_label"], observed))
        result = select_pattern_candidates(target, rows, atoms, target_cohorts=("union",))
        selected[target] = asdict(result)
    return selected


def _group_metadata(target: str, group: str, horizon: int) -> dict[str, Any]:
    if group.startswith("pattern:"):
        return {"pattern_id": target, "control_id": "pattern", "cohort_id": group.partition(":")[2], "horizon": horizon}
    return {"pattern_id": target, "control_id": group, "cohort_id": "union", "horizon": horizon, "primary_control_id": PRIMARY[target]}


def summarize_all(event_parts: dict[str, dict[str, Path]], selections: dict[str, Any], output: Path) -> dict[str, Any]:
    """One bounded group/horizon at a time; all zero and annual cells retained."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    output = _checked_path(output)
    output.mkdir(parents=True, exist_ok=True)
    before = resource_sample()
    files: dict[str, Path] = {}
    top_rows: list[dict[str, Any]] = []
    full_n = annual_n = candidate_main_n = primary_single_n = secondary_single_n = missing_diagnostic_n = pattern_group_n = 0
    if len(PATTERNS) > 12 or sum(len(row["candidates"]) for row in selections.values()) > 1_104:
        raise ValueError("registered selection family/candidate cap exceeded")
    for target in PATTERNS:
        candidates = {row["candidate_id"]: tuple(Atom(**atom) for atom in row["atoms"]) for row in selections[target]["candidates"]}
        ancestor_pins = {code: file_digest(directory / "receipt.json") for code, directory in event_parts[target].items()}
        first_directory = next(iter(event_parts[target].values()))
        groups = list(read_frame(first_directory / "daily_groups.parquet").columns)
        groups.remove("t0")
        pattern_group_n += sum(group.startswith("pattern:") for group in groups)
        if pattern_group_n > 30:
            raise ValueError("registered subtype/union row cap exceeded")
        for group in groups:
            for horizon in (126, 252):
                # Combinations are defined on the original union and its three
                # main controls. Secondary controls remain unconditional/single.
                active_candidates = candidates if group in {"pattern:union", "C-base-no-pattern", "C-base-all", PRIMARY[target]} else {}
                inventory = membership_inventory(_group_metadata(target, group, horizon), active_candidates)
                identifiers = tuple(object_digest(row) for row in inventory)
                identity = {"target": target, "group": group, "horizon": horizon, "ancestors": ancestor_pins, "inventory": object_digest(inventory)}
                name = object_digest(identity)
                destination = _checked_path(output / name)
                if destination.exists():
                    saved = read_json(destination / "receipt.json")
                    if saved.get("identity") != identity or saved.get("complete") is not True:
                        raise ValueError("existing summary group identity differs or incomplete")
                    verify_files(destination, saved["artifacts"])
                    full_n += saved["full_cell_n"]
                    annual_n += saved["annual_row_n"]
                    candidate_main_n += saved["candidate_primary_row_n"]
                    primary_single_n += saved["primary_single_row_n"]
                    secondary_single_n += saved["secondary_single_row_n"]
                    missing_diagnostic_n += saved["missing_diagnostic_row_n"]
                    top_rows.extend(saved["confirmation_top_input"])
                    files[f"summary/{name}.parquet"] = destination / "summary.parquet"
                    files[f"annual/{name}.parquet"] = destination / "annual.parquet"
                    files[f"candidate-coverage/{name}.parquet"] = destination / "candidate-coverage.parquet"
                    continue
                staging = _checked_path(output / f".staging-{name}-{uuid.uuid4().hex}")
                staging.mkdir()
                summary_path, annual_path = staging / "summary.parquet", staging / "annual.parquet"
                group_full_n = group_annual_n = group_candidate_n = group_primary_n = group_secondary_n = group_missing_n = 0
                group_top: list[dict[str, Any]] = []
                accumulator = DenseCounts(identifiers, horizon)
                coverage = CandidateCoverage(_group_metadata(target, group, horizon), active_candidates)
                for directory in event_parts[target].values():
                    frame = group_frame(directory, group, horizon)
                    memberships = stock_memberships(frame, inventory, max_membership_rows=2_000_000)
                    accumulator.add_stock(aggregate_memberships(frame, memberships))
                    if active_candidates and not frame.empty:
                        coverage.add_stock(frame)
                _write_frame(staging / "candidate-coverage.parquet", coverage.finalize())
                writers: dict[str, Any] = {}
                buffers: dict[str, list[dict[str, Any]]] = {"summary": [], "annual": []}

                def flush(kind: str) -> None:
                    if not buffers[kind]:
                        return
                    # Explicit dataframe conversion keeps scalar union types
                    # stable even for an all-zero/null first chunk.
                    frame = pd.DataFrame(buffers[kind])
                    frame["candidate_id"] = (
                        cast(pd.Series, frame["candidate_id"] if "candidate_id" in frame else pd.Series("", index=frame.index)).fillna("").astype("string")
                    )
                    frame["candidate_atoms_json"] = (
                        cast(pd.Series, frame["candidate_atoms"] if "candidate_atoms" in frame else pd.Series(None, index=frame.index, dtype=object))
                        .map(lambda value: json.dumps(value, sort_keys=True) if isinstance(value, list) else "[]")
                        .astype("string")
                    )
                    if "candidate_atoms" in frame:
                        frame = frame.drop(columns="candidate_atoms")
                    if "removed_year" in frame:
                        frame["removed_year"] = frame["removed_year"].astype("Int64")
                    for column in frame:
                        if column.endswith("_rate") or column.endswith("_bound") or column.endswith("_median"):
                            frame[column] = cast(pd.Series, pd.to_numeric(frame[column], errors="raise")).astype(float)
                    table = pa.Table.from_pandas(frame, preserve_index=False)
                    if kind not in writers:
                        writers[kind] = pq.ParquetWriter(summary_path if kind == "summary" else annual_path, table.schema, compression="zstd")
                    writers[kind].write_table(table)
                    buffers[kind].clear()

                try:
                    for meta, cell in zip(inventory, identifiers, strict=True):
                        if meta["feature_id"] == "candidate" and meta["split"] != "cross-check":
                            continue
                        total = accumulator.summarize(cell)
                        removed, dropped = accumulator.drop_best_year(cell)
                        # A nonexistent control condition never acquires a
                        # numeric comparison by inheriting its known outcomes.
                        if meta["condition_status"] == "not_applicable":
                            for summary in (total, dropped):
                                for key in summary:
                                    if key.endswith("_rate") or key.endswith("_bound"):
                                        summary[key] = None
                        for kind, summary in (("full", total), ("drop_best_year", dropped)):
                            buffers["summary"].append({**meta, **summary, "row_kind": kind, "removed_year": removed if kind == "drop_best_year" else None})
                        group_full_n += 1
                        if meta["condition_status"] != "known":
                            group_missing_n += 1
                        elif meta["feature_id"] not in {"candidate", "unconditional"}:
                            if group.startswith("pattern:") or group in {"C-base-no-pattern", "C-base-all", PRIMARY[target]}:
                                group_primary_n += 1
                            else:
                                group_secondary_n += 1
                        if meta["feature_id"] == "candidate" and meta["condition_status"] == "known":
                            group_candidate_n += 1
                            if horizon == 252 and group == "pattern:union" and meta["era"] == "all" and meta["mkt"] == "all":
                                group_top.append({**meta, **total})
                        for year, summary in zip(YEARS, accumulator.annual_summary(cell), strict=True):
                            if meta["condition_status"] == "not_applicable":
                                for key in summary:
                                    if key.endswith("_rate") or key.endswith("_bound"):
                                        summary[key] = None
                            buffers["annual"].append({**meta, **summary, "year": year})
                            group_annual_n += 1
                        if len(buffers["summary"]) >= 2048:
                            flush("summary")
                        if len(buffers["annual"]) >= 8192:
                            flush("annual")
                    flush("summary")
                    flush("annual")
                finally:
                    for writer in writers.values():
                        writer.close()
                descriptors = [describe_file(staging, path) for path in (summary_path, annual_path, staging / "candidate-coverage.parquet")]
                verify_files(staging, descriptors)
                for code, directory in event_parts[target].items():
                    if file_digest(directory / "receipt.json") != ancestor_pins[code]:
                        raise ValueError("event ancestor changed during summary calculation")
                    verify_files(directory, read_json(directory / "receipt.json")["artifacts"])
                write_json(
                    staging / "receipt.json",
                    {
                        "schema": "pattern-scan-summary-group.v1",
                        "complete": True,
                        "identity": identity,
                        "artifacts": descriptors,
                        "full_cell_n": group_full_n,
                        "annual_row_n": group_annual_n,
                        "candidate_primary_row_n": group_candidate_n,
                        "primary_single_row_n": group_primary_n,
                        "secondary_single_row_n": group_secondary_n,
                        "missing_diagnostic_row_n": group_missing_n,
                        "confirmation_top_input": group_top,
                    },
                )
                publish_noreplace(staging, destination)
                full_n += group_full_n
                annual_n += group_annual_n
                candidate_main_n += group_candidate_n
                primary_single_n += group_primary_n
                secondary_single_n += group_secondary_n
                missing_diagnostic_n += group_missing_n
                top_rows.extend(group_top)
                files[f"summary/{name}.parquet"], files[f"annual/{name}.parquet"] = destination / "summary.parquet", destination / "annual.parquet"
                files[f"candidate-coverage/{name}.parquet"] = destination / "candidate-coverage.parquet"
                LOGGER.info("Summarized scan target=%s group=%s H=%d cells=%d memory=%d", target, group, horizon, len(inventory), accumulator.memory_nbytes)
    if candidate_main_n > 211_968:
        raise ValueError("confirmation candidate primary row cap exceeded")
    if primary_single_n > 5_529_600:
        raise ValueError("primary single condition row cap exceeded")
    return {
        "files": {name: str(path) for name, path in files.items()},
        "full_cell_n": full_n,
        "annual_row_n": annual_n,
        "candidate_primary_row_n": candidate_main_n,
        "primary_single_row_n": primary_single_n,
        "secondary_single_row_n": secondary_single_n,
        "missing_diagnostic_row_n": missing_diagnostic_n,
        "full_plus_drop_and_annual_rows_per_cell": 19,
        "confirmation_top_input": top_rows,
        "measurement": phase_receipt("all_q1_q2_q3_cells", before, resource_sample()),
    }


def run_analysis(
    roots: DataRoots,
    parts: dict[str, Path],
    barrier: dict[str, Any],
    entries: dict[str, dict[str, Any]],
    output: Path,
    *,
    source: dict[str, Any],
    input_id: str,
) -> dict[str, Any]:
    """Publish uniquely pinned event projections then complete approved tables."""
    verify_source(source)
    output = _checked_path(output)
    output.mkdir(parents=True, exist_ok=True)
    shared = load_shared(roots, entries, tuple(parts), source, input_id)
    event_parts = prepare_event_parts(parts, barrier, entries, output / "event-parts", source=source, input_id=input_id, shared=shared)
    selections = select_all(event_parts)
    selection_path = output / "selection.json"
    if selection_path.exists():
        if read_json(selection_path) != json.loads(json.dumps(selections)):
            raise ValueError("existing fixed selection differs")
    else:
        write_json(selection_path, selections)
    audits = _audits(roots, parts, barrier, event_parts, selections, output / "audits", source=source, input_id=input_id, shared=shared)
    summaries = summarize_all(event_parts, selections, output / "summaries")
    calendar = pd.DatetimeIndex(pd.to_datetime(barrier["calendar"]))
    event_files = {
        f"{target}/{object_digest(code)}/{name}.parquet": directory / f"{name}.parquet"
        for target, stocks in event_parts.items()
        for code, directory in stocks.items()
        for name in ("events", "conditions", "group_memberships", "daily_groups", "formula_groups")
    }
    event_metadata = metadata("patterns", source, input_id, calendar)
    event_metadata["data_id"] = "pattern-scan-event-outcomes-full-2010-v1"
    event_metadata["inputs"]["base_label_version"] = entries["labels"]["version_id"]
    event_metadata["inputs"]["base_label_manifest_sha256"] = entries["labels"]["manifest"]["sha256"]
    overlay = publish_file_bundle(DataCatalog(roots), event_metadata, event_files)
    from research_core.pattern_scan_completion_v1 import complete_followup

    followup = complete_followup(parts, barrier, event_parts, selections, summaries, output / "followup", source=source, input_id=input_id, shared=shared)
    verify_source(source)
    episode_metadata = metadata("episodes", source, input_id, calendar)
    episode_metadata["data_id"] = "pattern-scan-episodes-full-2010-v1"
    episode_metadata["inputs"]["base_labels"] = {"version_id": entries["labels"]["version_id"], "manifest_sha256": entries["labels"]["manifest"]["sha256"]}
    episode_files = {name: Path(path) for name, path in followup["episodes"]["files"].items()}
    episode_entry = publish_file_bundle(DataCatalog(roots), episode_metadata, episode_files)
    result_metadata = metadata("patterns", source, input_id, calendar)
    result_metadata["data_id"] = "pattern-scan-report-tables-full-2010-v1"
    result_metadata["inputs"]["shared_versions"] = {
        kind: {"data_id": entry["data_id"], "version_id": entry["version_id"], "manifest_sha256": entry["manifest"]["sha256"]}
        for kind, entry in {**entries, "event_outcomes": overlay, "episodes": episode_entry}.items()
    }
    result_metadata["coverage"].update(**{
        key: summaries[key]
        for key in (
            "full_cell_n",
            "annual_row_n",
            "candidate_primary_row_n",
            "primary_single_row_n",
            "secondary_single_row_n",
            "missing_diagnostic_row_n",
            "full_plus_drop_and_annual_rows_per_cell",
        )
    })
    result_files = {
        **{f"q1-q3/{name}": Path(path) for name, path in summaries["files"].items()},
        **{f"q5-q6/{name}": Path(path) for name, path in followup["files"].items()},
        "selection.json": output / "selection.json",
        "executed-sources.zip": output.parent / "seal" / "executed-sources.zip",
        "source.json": output.parent / "seal" / "source.json",
        **{f"audits/{name}": Path(path) for name, path in audits["files"].items()},
    }
    result_metadata["parameters"]["artifact_owner"] = "tasks/20261013-pattern-scan"
    result_metadata["backup"]["primary_copy"] = "one physical task report bundle"
    result_entry = publish_file_bundle(DataCatalog(roots), result_metadata, result_files, task_id="20261013-pattern-scan")
    verify_source(source)
    return {
        "shared_event_outcomes": overlay,
        "shared_episodes": episode_entry,
        "shared_report_tables": result_entry,
        "selection": selections,
        "summary_receipt": summaries,
        "followup": followup,
        "audits": audits,
        "shared_consumption_measurements": shared.consumption_measurements,
    }


def _audits(
    roots: DataRoots,
    parts: dict[str, Path],
    barrier: dict[str, Any],
    event_parts: dict[str, dict[str, Path]],
    selections: dict[str, Any],
    output: Path,
    *,
    source: dict[str, Any],
    input_id: str,
    shared: SharedInputs,
) -> dict[str, Any]:
    from research_core.pattern_scan_audit_v1 import build_audit, legacy_overlap_audit, read_legacy_h1

    identity = {"source_id": source["source_id"], "input_id": input_id, "selections": object_digest(selections), "shared_pins": shared.pins}
    if output.exists():
        receipt = read_json(output / "receipt.json")
        if receipt.get("identity") != identity or receipt.get("complete") is not True:
            raise ValueError("existing retained audit differs or incomplete")
        verify_files(output, receipt["artifacts"])
        return receipt
    before = resource_sample()
    audited = build_audit(parts, event_parts, selections, source=source, input_id=input_id, barrier=barrier)
    pins = read_preparation_pins(ROOT / "tasks/20261013-pattern-scan/params/input-pins-v1.json.gz")
    legacy, descriptor = read_legacy_h1(roots, pins["shared_catalog"]["contents"]["snapshot"])
    rows = []
    for code in sorted(parts):
        frame = shared.read_stock(code, "raw_events")
        rows.append(frame.loc[frame.pattern_id.eq("H1"), ["security_id", "t0", "subtype_id", "pivot", "support", "lower"]])
    current = pd.concat(rows, ignore_index=True)
    overlap = legacy_overlap_audit(current, legacy)
    staging = output.parent / f".staging-audits-{uuid.uuid4().hex}"
    staging.mkdir()
    names = []
    for field in fields(audited):
        name = f"{field.name}.parquet"
        _write_frame(staging / name, getattr(audited, field.name))
        names.append(name)
    _write_frame(staging / "legacy-overlap.parquet", overlap)
    names.extend(("legacy-overlap.parquet", "legacy-reference.json"))
    write_json(staging / "legacy-reference.json", descriptor)
    artifacts = [describe_file(staging, staging / name) for name in names]
    verify_source(source)
    verify_files(staging, artifacts)
    receipt = {
        "complete": True,
        "identity": identity,
        "artifacts": artifacts,
        "files": {name: str(output / name) for name in names},
        "measurement": phase_receipt("independent_event_candidate_and_legacy_audits", before, resource_sample()),
    }
    write_json(staging / "receipt.json", receipt)
    publish_noreplace(staging, output)
    return receipt
