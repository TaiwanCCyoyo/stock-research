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
from research_core.pattern_scan_dense_counts_v1 import DenseCounts
from research_core.pattern_scan_event_conditions_v1 import atoms_for_pattern
from research_core.pattern_scan_event_tables_v1 import build_event_tables
from research_core.pattern_scan_execution_v1 import ROOT, verify_source
from research_core.pattern_scan_groups_v1 import PRIMARY
from research_core.pattern_scan_inputs_v1 import read_preparation_pins
from research_core.pattern_scan_membership_v1 import StockCountPlan, membership_inventory
from research_core.pattern_scan_parquet_v1 import read_frame, write_frame
from research_core.pattern_scan_price_references_v4 import read_stock_prices, verify_stock_artifacts
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
        verify_stock_artifacts(directory, part_receipt)
        global_record = barrier["global_files"][code]
        global_path = _checked_path(Path(global_record["path"]))
        if file_digest(global_path) != global_record["sha256"]:
            raise ValueError("event global feature part changed")
        tables = {
            name: (read_stock_prices(directory) if name == "prices" else read_frame(directory / f"{name}.parquet"))
            if shared is None
            else shared.read_stock(code, name)
            for name in STOCK_TABLES
        }
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
                count_plan = StockCountPlan(inventory, max_membership_rows=2_000_000)
                for directory in event_parts[target].values():
                    frame = group_frame(directory, group, horizon)
                    accumulator.add_stock(count_plan.matrix(frame))
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


def _continuation_execution_provenance(
    output: Path,
    source: dict[str, Any],
    input_id: str,
    continuation_request: Path,
) -> tuple[dict[str, Path], dict[str, Any]]:
    """Validate one active executor against immutable stock/price ancestry."""
    from research_core.pattern_scan_continuation_v4 import verify_phase_result
    from research_core.pattern_scan_git_source_v2 import assert_current_code, verify_git_source
    from research_core.pattern_scan_price_references_v4 import EQUALITY, HANDOFF, RETIRED, retired_preparation_reference
    from research_core.pattern_scan_result_lifecycle_v3 import _run

    run = _run(_checked_path(output.parent))
    if output != run / "analysis":
        raise ValueError("continuation analysis must use the original run analysis directory")
    pins: dict[Path, dict[str, Any]] = {}
    records: dict[Path, dict[str, Any]] = {}

    def pin(path: Path) -> dict[str, Any]:
        if not path.is_absolute() or path.suffix != ".json":
            raise ValueError("explicit absolute execution JSON metadata required")
        path = _checked_path(path)
        if not path.is_file() or not path.is_relative_to(run.parent):
            raise ValueError("execution metadata must belong to this run or its control sibling")
        if path not in pins:
            pins[path] = {**describe_file(path.parent, path), "path": str(path)}
        return pins[path]

    def load(path: Path) -> dict[str, Any]:
        pin(path)
        if path not in records:
            records[path] = read_json(path, max_bytes=128_000_000)
        return records[path]

    def matches_pin(path: Path, expected: dict[str, Any]) -> None:
        if not isinstance(expected, dict) or set(expected) != {"path", "bytes", "sha256"} or object_digest(pin(path)) != object_digest(expected):
            raise ValueError("continuation execution metadata descriptor differs")

    request = load(continuation_request)
    control = continuation_request.parent
    if (
        request.get("schema") != "pattern-scan-continuation.v4"
        or request.get("phase") != "analysis"
        or request.get("calculation_authorized") is not True
        or request.get("run_root") != str(run)
        or continuation_request.name != "request-analysis.json"
        or control == run
        or control.parent != run.parent
        or request.get("control_root") != str(control)
        or request.get("primary") != str(run.parent.parent.parent)
        or request.get("data") != str(run.parent.parent.parent / "research_data")
        or request.get("source") != source
        or request.get("input_id") != input_id
    ):
        raise ValueError("continuation analysis request ownership/source/input differs")
    executor = request["executor"]
    assert_current_code(executor, ROOT)
    prepared = load(run / "derived-preparation.json")
    if (
        prepared.get("schema") != "pattern-scan-derived-preparation.v2"
        or prepared.get("scope") != "full_ordinary_reference"
        or prepared.get("source") != source
        or prepared.get("input_id") != input_id
        or type(prepared.get("calendar_n")) is not int
        or prepared["calendar_n"] != 4110
        or type(prepared.get("ordinary_reference_n")) is not int
        or prepared["ordinary_reference_n"] != 1942
    ):
        raise ValueError("continuation preparation numerical ancestry differs")
    reference = retired_preparation_reference(run)
    if reference.get("source") != source or reference.get("input_id") != input_id or reference.get("reference") != request["reference"]:
        raise ValueError("continuation shared price reference differs from verified handoff")
    matches_pin(run / HANDOFF, request["price_handoff"])
    names = (
        "derived-preparation.json",
        "producer-read-receipt.json",
        "phase-stock-result.json",
        "request-stock.json",
        "response-stock.json",
        "response-stock.job-memory.json",
        "run-stock-receipt.json",
    )
    for name in names:
        matches_pin(run / name, reference["ancestors"][name])
    matches_pin(run / "phase-stock-result.json", request["stock_reference"])
    stock = load(run / "phase-stock-result.json")
    rows = stock.get("pool", {}).get("results", [])
    expected_codes = [row["code"] for row in prepared["requests"]]
    codes = [row.get("code") for row in rows]
    if (
        stock.get("phase") != "full_stock_checkpoints"
        or stock.get("global_analysis_admitted") is not False
        or any(not isinstance(code, str) or not code.strip() for code in codes)
        or any(not isinstance(code, str) or not code.strip() for code in expected_codes)
        or len(rows) != 1942
        or len(set(codes)) != 1942
        or len(expected_codes) != 1942
        or set(codes) != set(expected_codes)
        or any(row.get("complete") is not True or row.get("source_id") != source["source_id"] or row.get("input_id") != input_id for row in rows)
    ):
        raise ValueError("continuation requires the complete original 1942-stock pool")
    capacity_path = Path(request["capacity_path"])
    capacity = load(capacity_path)
    if (
        pin(capacity_path)["sha256"] != request["capacity_sha256"]
        or capacity.get("schema") != "pattern-scan-continuation-capacity.v4"
        or capacity.get("phase") != "analysis"
        or capacity.get("executor_source_id") != executor["source_id"]
        or capacity.get("ancestral_source_id") != source["source_id"]
        or capacity.get("input_id") != input_id
    ):
        raise ValueError("continuation capacity metadata identity differs")
    equality = load(run / EQUALITY)
    matches_pin(run / EQUALITY, reference["audit"])
    retirement = load(run / RETIRED)
    if (
        equality.get("schema") != "pattern-scan-price-reader-equivalence.v3"
        or equality.get("complete") is not True
        or equality.get("reference_source_id") != source["source_id"]
        or equality.get("reference_input_id") != input_id
        or equality.get("reference") != request["reference"]
        or equality.get("generation") != request["reference"]["generation"]
        or equality.get("calendar_n") != 4110
        or equality.get("security_n") != 1943
        or equality.get("cutoff") != "2026-10-12"
        or any(equality.get(name) is not True for name in ("all_columns_equal", "calendar_equal", "quality_equal"))
        or type(equality.get("mismatch_n")) is not int
        or equality["mismatch_n"] != 0
        or retirement.get("schema") != "pattern-scan-own-price-retirement.v4"
        or retirement.get("complete") is not True
        or retirement.get("run_root") != str(run)
        or retirement.get("original_source_id") != source["source_id"]
        or retirement.get("original_input_id") != input_id
        or retirement.get("generation") != request["reference"]["generation"]
        or retirement.get("handoff") != {"path": str(run / HANDOFF), "sha256": request["price_handoff"]["sha256"]}
        or retirement.get("other_stock_artifacts_retained") is not True
    ):
        raise ValueError("continuation equality or own-price retirement identity differs")
    # The phase and response duplicate the whole stock pool. Their pins remain
    # in provenance/run receipts; expanded per-stock metadata is not permanent.
    files = {f"execution/{name}": run / name for name in names if name not in {"phase-stock-result.json", "response-stock.json"}}
    files.update({
        "execution/continuation-request.json": continuation_request,
        "execution/continuation-capacity.json": capacity_path,
        "execution/shared-price-equivalence.json": run / EQUALITY,
        "execution/own-price-retirement.json": run / RETIRED,
    })
    provenance: dict[str, Any] = {
        "stock_reference": pin(run / "phase-stock-result.json"),
        "executor": executor,
        "ancestral_stock_source": source,
        "shared_price_reference": request["reference"],
        "price_handoff": pin(run / HANDOFF),
    }
    phase_execution: dict[str, Any] = {}
    unavailable: list[str] = []
    expected_outputs = {
        "prices": {"price_handoff": run / HANDOFF, "equivalence": run / EQUALITY},
        "retire-prices": {"price_retirement": run / RETIRED},
        "barrier": {"barrier": run / "global/receipt.json"},
        "events": {"event_checkpoint": run / "event-checkpoint.json"},
    }
    for phase, outputs in expected_outputs.items():
        paths = {
            "request": control / f"request-{phase}.json",
            "response": control / f"response-{phase}.json",
            "job-memory": control / f"response-{phase}.job-memory.json",
        }
        present = [_checked_path(path).exists() for path in paths.values()]
        if not any(present):
            unavailable.append(phase)
            continue
        if not all(present):
            raise ValueError(f"incomplete prior continuation phase evidence: {phase}")
        previous = load(paths["request"])
        if (
            previous.get("schema") != "pattern-scan-continuation.v4"
            or previous.get("phase") != phase
            or previous.get("calculation_authorized") is not True
            or any(previous.get(key) != request[key] for key in ("run_root", "control_root", "primary", "data", "source", "input_id"))
            or object_digest(previous.get("stock_reference")) != object_digest(request["stock_reference"])
            or object_digest(previous.get("reference")) != object_digest(request["reference"])
            or (phase == "retire-prices" and previous.get("retirement_authorized") is not True)
            or (phase == "prices" and previous.get("price_handoff") is not None)
            or (phase != "prices" and object_digest(previous.get("price_handoff")) != object_digest(request["price_handoff"]))
        ):
            raise ValueError(f"prior continuation request lineage differs: {phase}")
        # A completed prior phase may have a different actual executing commit.
        # Historical validation must never compare it with today's checkout.
        verify_git_source(previous["executor"])
        saved = load(paths["response"])
        result_pins = saved.get("results")
        if not isinstance(result_pins, dict) or set(result_pins) != set(outputs):
            raise ValueError(f"prior continuation result keys differ: {phase}")
        for name, expected_path in outputs.items():
            descriptor = result_pins[name]
            if (
                not isinstance(descriptor, dict)
                or set(descriptor) != {"path", "bytes", "sha256"}
                or descriptor.get("path") != str(expected_path)
                or type(descriptor.get("bytes")) is not int
                or descriptor["bytes"] < 0
                or not isinstance(descriptor.get("sha256"), str)
            ):
                raise ValueError(f"prior continuation result locator differs: {phase}")
            # Reject aliases/foreign locators before the reusable verifier reads bytes.
            _checked_path(expected_path)
        verified_phase = verify_phase_result(paths["response"], previous)
        paths["capacity"] = Path(previous["capacity_path"])
        prior_capacity = load(paths["capacity"])
        observation = verified_phase["coordinator_job_memory"]
        if (
            pin(paths["capacity"])["sha256"] != previous["capacity_sha256"]
            or prior_capacity.get("schema") != "pattern-scan-continuation-capacity.v4"
            or prior_capacity.get("phase") != ("prices" if phase == "retire-prices" else phase)
            or prior_capacity.get("executor_source_id") != previous["executor"]["source_id"]
            or prior_capacity.get("ancestral_source_id") != source["source_id"]
            or prior_capacity.get("input_id") != input_id
            or type(prior_capacity.get("memory", {}).get("job_limit_bytes")) is not int
            or prior_capacity["memory"]["job_limit_bytes"] != observation["limit_bytes"]
        ):
            raise ValueError(f"prior continuation capacity or observed Job limit differs: {phase}")
        retained_metadata = {}
        for kind, path in paths.items():
            logical = f"execution/phases/{phase}/{kind}.json"
            files[logical] = path
            retained_metadata[kind] = {"retained_path": logical, **pin(path)}
        phase_execution[phase] = {"executor": previous["executor"], "job_memory": observation, "metadata": retained_metadata}
    provenance["phase_execution"] = phase_execution
    provenance["phase_execution_unavailable"] = unavailable
    provenance["analysis_native_job_memory"] = {"status": "pending", "observation": None}
    return files, provenance


def _report_execution_files(
    output: Path,
    source: dict[str, Any],
    input_id: str,
    continuation_request: Path | None = None,
) -> dict[str, Path]:
    """Select existing execution provenance before analysis or publication starts."""
    if continuation_request is not None:
        return _continuation_execution_provenance(output, source, input_id, continuation_request)[0]
    run = _checked_path(output.parent)
    if source.get("schema") != "pattern-scan-source.git.v2":
        return {"executed-sources.zip": run / "seal" / "executed-sources.zip", "source.json": run / "seal" / "source.json"}

    def metadata_file(path: Path) -> tuple[Path, dict[str, Any]]:
        checked = _checked_path(path)
        if not path.is_absolute() or checked.suffix != ".json" or not checked.is_file():
            raise ValueError(f"required report execution metadata missing or invalid: {path}")
        return checked, read_json(checked, max_bytes=128_000_000)

    request_path, request = metadata_file(run / "request-all.json")
    index, prepared = metadata_file(run / "derived-preparation.json")
    producer_receipt, receipt = metadata_file(run / "producer-read-receipt.json")
    if (
        request.get("schema") != "pattern-scan-coordinator-request.v2"
        or request.get("calculation_authorized") is not True
        or request.get("mode") != "all"
        or request.get("source") != source
        or request.get("run_root") != str(run)
        or request.get("prepared_path") != str(index)
        or not isinstance(request.get("run_id"), str)
        or not request["run_id"]
        or prepared.get("schema") != "pattern-scan-derived-preparation.v2"
        or prepared.get("scope") != "full_ordinary_reference"
        or prepared.get("source") != source
        or prepared.get("input_id") != input_id
    ):
        raise ValueError("report execution request or derived preparation identity differs")
    result = receipt.get("results", {}).get("derived_preparation", {})
    if (
        receipt.get("schema") != "run-receipt.v1"
        or receipt.get("run_id") != request["run_id"] + ":producer-read"
        or result.get("path") != str(index)
        or result.get("bytes") != index.stat().st_size
        or result.get("sha256") != file_digest(index)
    ):
        raise ValueError("report producer-read receipt identity differs")
    selected = {
        "execution/request.json": request_path,
        "execution/derived-preparation.json": index,
        "execution/producer-read-receipt.json": producer_receipt,
    }
    for field, name in (("profile_path", "resource-profile"), ("capacity_path", "capacity-plan")):
        value = request.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"required report execution metadata path missing: {field}")
        path, record = metadata_file(Path(value))
        if field == "profile_path":
            if record.get("schema") == "pattern-scan-profile-observation.v3":
                from research_core.pattern_scan_profile_observation_v3 import load_execution_profile

                load_execution_profile(
                    path, source=source, input_id=input_id, calendar_n=prepared["calendar_n"], ordinary_reference_n=prepared["ordinary_reference_n"]
                )
                selected["execution/historical-resource-profile.json"] = Path(record["historical_profile"]["path"])
            elif (
                record.get("schema") != "pattern-scan-resource-profile.v1"
                or record.get("source_id") != source["source_id"]
                or record.get("input_id") != input_id
            ):
                raise ValueError("report resource profile source/input identity differs")
        elif record.get("schema") != "pattern-scan-capacity.v2":
            raise ValueError("report capacity plan protocol differs")
        selected[f"execution/{name}.json"] = path
    return selected


def run_analysis(
    roots: DataRoots,
    parts: dict[str, Path],
    barrier: dict[str, Any],
    entries: dict[str, dict[str, Any]],
    output: Path,
    *,
    source: dict[str, Any],
    input_id: str,
    defer_publication: bool = False,
    continuation_request: Path | None = None,
) -> dict[str, Any]:
    """Compute approved tables; new runs defer publication of retained results."""
    verify_source(source)
    output = _checked_path(output)
    execution_provenance: dict[str, Any] = {}
    if continuation_request is not None:
        if not defer_publication:
            raise ValueError("continuation analysis requires deferred result publication")
        execution_files, execution_provenance = _continuation_execution_provenance(output, source, input_id, continuation_request)
    else:
        execution_files = _report_execution_files(output, source, input_id)
    output.mkdir(parents=True, exist_ok=True)
    shared = None if defer_publication else load_shared(roots, entries, tuple(parts), source, input_id)
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
    overlay = None if defer_publication else publish_file_bundle(DataCatalog(roots), event_metadata, event_files)
    from research_core.pattern_scan_completion_v1 import complete_followup

    followup = complete_followup(
        parts,
        barrier,
        event_parts,
        selections,
        summaries,
        output / "followup",
        source=source,
        input_id=input_id,
        shared=shared,
        **({"bounded_batches": True} if defer_publication else {}),
    )
    verify_source(source)
    if defer_publication:
        from research_core.pattern_scan_result_lifecycle_v3 import record_computed_results
        from research_core.pattern_scan_retained_v3 import collect_retained_files

        retained = collect_retained_files(summaries, followup, audits, selection_path=selection_path, execution_files=execution_files)
        inventory = record_computed_results(
            output.parent,
            retained,
            source=source,
            input_id=input_id,
            provenance={"label_checkpoint": entries["labels"], "selection": selections, **execution_provenance},
            transient_files=[path for path in output.parent.rglob("*") if path.is_file() and path.name not in {".scan-active.json", "computed-results.json"}],
        )
        return {
            "status": "computed_unpublished",
            "catalog_publication": False,
            "retained_result": inventory,
            "selection": selections,
            "summary_receipt": summaries,
            "followup": followup,
            "audits": audits,
            "independent_candidate_reconstruction": "pending",
        }
    assert shared is not None and overlay is not None
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
        **execution_files,
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
    shared: SharedInputs | None,
) -> dict[str, Any]:
    from research_core.pattern_scan_audit_v1 import build_audit, legacy_overlap_audit, read_legacy_h1

    identity = {
        "source_id": source["source_id"],
        "input_id": input_id,
        "selections": object_digest(selections),
        "shared_pins": {} if shared is None else shared.pins,
    }
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
        frame = read_frame(parts[code] / "raw_events.parquet") if shared is None else shared.read_stock(code, "raw_events")
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
