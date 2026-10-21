"""Independent candidate audit over explicit computed, unpublished scan results."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from research_core.artifact_store import canonical, describe_file, file_digest, object_digest, publish_noreplace, read_json, verify_files, write_json
from research_core.pattern_scan_analysis_v1 import group_frame
from research_core.pattern_scan_barrier_v1 import verify_barrier
from research_core.pattern_scan_candidate_audit_v2 import compare_candidate, reconstruct_candidate, select_audit_candidates
from research_core.pattern_scan_groups_v1 import PRIMARY
from research_core.pattern_scan_inputs_v1 import read_preparation_pins
from research_core.pattern_scan_parquet_v1 import read_frame
from research_core.pattern_scan_rates_v1 import REQUIRED_COLUMNS
from research_core.pattern_scan_receipt_io_v2 import publish_scan_receipt, read_scan_receipt
from research_core.pattern_scan_result_lifecycle_v3 import verify_computed_results
from research_core.research_data_paths import DataRoots, _artifact_name, _checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample
from research_core.run_receipt import changed_results, code_identity, write_run_receipt

LOGGER = logging.getLogger(__name__)
CODE_ROOT = Path(__file__).resolve().parents[1]
TASK = "20261013-pattern-scan"
DEFINITION = "pattern-scan-candidate-reconstruction.v2"
PARAMETERS: dict[str, Any] = {
    "selection": "first five sorted target/candidate_id",
    "horizons": [126, 252],
    "states": [1, -1, -2],
    "split": "cross-check",
    "eras": ["all", "2010-2012", "2013-2018", "2019+"],
    "markets": ["all", "up", "down", "consolidation", "mixed", "unknown"],
    "relative_tolerance": 1e-12,
    "absolute_tolerance": 1e-12,
    "rows_per_case": 1368,
    "full_scope_checks": 54720,
}


def _pin(path: Path, parents: dict[str, Any], *, digest: str | None = None) -> None:
    path = _checked_path(path)
    name = str(path)
    if name in parents:
        if digest is not None and parents[name]["sha256"] != digest:
            raise ValueError("conflicting audit parent hash")
        return
    info = path.stat()
    parents[name] = {
        "path": name,
        "bytes": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "sha256": file_digest(path) if digest is None else digest,
        "live_producer": False,
    }


def _owned(path: Path, root: Path) -> Path:
    path = _checked_path(path)
    if not path.is_relative_to(root) or path == root:
        raise ValueError("audit parent escaped completed run root")
    return path


def _rebase_results(receipt_path: Path, staging: Path, destination: Path) -> dict[str, Any]:
    """Rebase only this newly generated, unpublished run receipt's locators."""
    receipt = read_scan_receipt(receipt_path)
    for record in receipt["results"].values():
        locator = Path(record["path"])
        original = _checked_path(locator if locator.is_absolute() else CODE_ROOT / locator)
        if not original.is_relative_to(staging) or original == staging:
            raise ValueError("new audit result locator escaped staging")
        record["path"] = str(_checked_path(destination / original.relative_to(staging)))
    receipt_path.write_bytes(canonical(receipt))
    return receipt


def _preregistration_matches(record: dict[str, Any], mission: Path, mission_sha256: str) -> bool:
    """Read legacy SHA pins or the committed-path/code receipt form.

    The new form is tied to this audit's original execution code and retained
    mission parent pin, not whichever mission is currently checked out.
    """
    preregistration = record.get("preregistration")
    if not isinstance(preregistration, dict):
        return False
    if "sha256" in preregistration:  # Named legacy form; preserve its original contract.
        return preregistration["sha256"] == mission_sha256
    parent = record.get("input_fingerprint", {}).get("inputs", {}).get(str(mission), {})
    code = record.get("code")
    return (
        preregistration == {"path": f"tasks/{TASK}/mission.md"}
        and isinstance(code, dict)
        and isinstance(code.get("commit"), str)
        and bool(code["commit"])
        and isinstance(parent, dict)
        and parent.get("path") == str(mission)
        and parent.get("sha256") == mission_sha256
    )


def _ancestors(
    run: Path,
    result: dict[str, Any],
    source_id: str,
    input_id: str,
    selected: tuple[dict[str, Any], ...],
    parents: dict[str, Any],
    retained: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Path]], dict[tuple[str, str, int], tuple[Path, Path]]]:
    entries = result["shared_versions"]
    shared_pins = {kind: {"version_id": entry["version_id"], "manifest_sha256": entry["manifest"]["sha256"]} for kind, entry in entries.items()}
    pool = result["pool"]["results"]
    stocks = {row["code"]: row for row in pool}
    barrier = result["barrier"]
    if not stocks or len(stocks) != len(pool) or set(stocks) != set(barrier["global_files"]) or set(stocks) != set(barrier["identity"]["stock_receipts"]):
        raise ValueError("completed stock/barrier pool differs")
    event_parts: dict[str, dict[str, Path]] = {row["target"]: {} for row in selected}
    event_hashes: dict[str, dict[str, str]] = {target: {} for target in event_parts}
    for code, stock in sorted(stocks.items()):
        if stock.get("source_id") != source_id or stock.get("input_id") != input_id or stock.get("complete") is not True:
            raise ValueError("completed stock source/input identity differs")
        stock_receipt = _owned(Path(stock["output_path"]) / "receipt.json", run)
        if read_json(stock_receipt) != stock:
            raise ValueError("completed stock receipt identity differs")
        stock_sha = file_digest(stock_receipt)
        if barrier["identity"]["stock_receipts"].get(code) != stock_sha:
            raise ValueError("barrier stock receipt pin differs")
        _pin(stock_receipt, parents, digest=stock_sha)
        for target in event_parts:
            identity = {
                "code": code,
                "target": target,
                "source_id": source_id,
                "input_id": input_id,
                "shared_pins": shared_pins,
                "global_sha256": barrier["global_files"][code]["sha256"],
                "stock_request_id": stock["request_id"],
            }
            directory = _owned(run / "analysis" / "event-parts" / object_digest(identity), run)
            path = directory / "receipt.json"
            receipt = read_json(path)
            if receipt.get("schema") != "pattern-scan-event-part.v1" or receipt.get("complete") is not True or receipt.get("identity") != identity:
                raise ValueError("selected event receipt identity differs or is incomplete")
            verify_files(directory, receipt["artifacts"])
            if {item["path"] for item in receipt["artifacts"]} != {
                f"{name}.parquet" for name in ("events", "conditions", "group_memberships", "daily_groups", "formula_groups")
            }:
                raise ValueError("selected event payload inventory differs")
            for item in receipt["artifacts"]:
                _pin(directory / item["path"], parents, digest=item["sha256"])
            _pin(path, parents)
            event_parts[target][code] = directory
            event_hashes[target][code] = parents[str(path)]["sha256"]
    files = result["analysis"]["summary_receipt"]["files"]
    index = {}
    for name, value in files.items():
        if not name.startswith("summary/"):
            continue
        token = Path(name).stem
        if name != f"summary/{token}.parquet":
            raise ValueError("noncanonical summary index name")
        directory = _owned(run / "analysis" / "summaries" / token, run)
        if _owned(Path(value), run) != directory / "summary.parquet" or files.get(f"annual/{token}.parquet") != str(directory / "annual.parquet"):
            raise ValueError("summary index path identity differs")
        receipt = read_json(directory / "receipt.json")
        identity = receipt.get("identity", {})
        target, group, horizon = identity.get("target"), identity.get("group"), identity.get("horizon")
        if target not in event_parts:
            continue
        if group not in ("pattern:union", "C-base-no-pattern", "C-base-all", PRIMARY[target]) or horizon not in (126, 252):
            continue
        if (
            receipt.get("schema") != "pattern-scan-summary-group.v1"
            or receipt.get("complete") is not True
            or object_digest(identity) != token
            or identity.get("ancestors") != event_hashes[target]
        ):
            raise ValueError("summary group identity differs or is incomplete")
        key = target, group, horizon
        if key in index:
            raise ValueError("duplicate summary group identity")
        if not {"summary.parquet", "annual.parquet"}.issubset(item["path"] for item in receipt["artifacts"]):
            raise ValueError("summary receipt lacks its complete aggregate payloads")
        unchecked = []
        for item in receipt["artifacts"]:
            known = retained.get(str(directory / item["path"]))
            if known is None:
                unchecked.append(item)
            elif item["bytes"] != known["bytes"] or item["sha256"] != known["sha256"]:
                raise ValueError("summary descriptor differs from computed retained result")
        if unchecked:
            verify_files(directory, unchecked)
        for item in receipt["artifacts"]:
            _pin(directory / item["path"], parents, digest=item["sha256"])
        _pin(directory / "receipt.json", parents)
        index[key] = directory / "summary.parquet", directory / "annual.parquet"
    required = {
        (target, group, horizon)
        for target in event_parts
        for group in ("pattern:union", "C-base-no-pattern", "C-base-all", PRIMARY[target])
        for horizon in (126, 252)
    }
    if set(index) != required:
        raise ValueError("missing selected-target summary groups")
    return event_parts, index


def _existing_event_audit(named: dict[str, dict[str, Any]], run: Path) -> dict[str, Any]:
    """Describe already retained build_audit evidence, never rerun ten events."""
    required = {name: named.get(f"audits/events/{name}.parquet") for name in ("raw_events", "cold_events", "conditions")}
    if any(row is None for row in required.values()):
        return {"status": "unknown", "event_audit_n": None, "reason": "retained independent event-audit tables missing"}
    paths = {name: _owned(Path(row["source_path"]), run) for name, row in required.items() if row is not None}
    raw_n = pq.ParquetFile(paths["raw_events"]).metadata.num_rows
    cold_n = pq.ParquetFile(paths["cold_events"]).metadata.num_rows
    matches = read_frame(paths["conditions"], columns=["matches"])["matches"]
    mismatch_n = int((~matches.eq(True).fillna(False)).sum())
    return {
        "status": "retained_existing_event_audit",
        "executed_by_candidate_driver": False,
        "event_audit_n": cold_n,
        "raw_event_rows": raw_n,
        "condition_comparisons": len(matches),
        "condition_mismatch_n": mismatch_n,
        "ten_event_scope_present": raw_n == cold_n == 10
        and len(matches) > 0
        and pd.api.types.is_bool_dtype(matches.dtype)
        and bool(matches.notna().all())
        and mismatch_n == 0,
    }


def audit_computed_scan(
    roots: DataRoots,
    *,
    computed_results: dict[str, Any],
    run_root: Path,
    output_id: str,
    stock_reference: Path | None = None,
) -> dict[str, Any]:
    """Audit retained computed results before publication, without stock kernels."""
    started = resource_sample()
    run = _checked_path(run_root)
    if run.parent != roots.primary / ".tmp" / "pattern-scan-execution":
        raise ValueError("audit requires a completed run under primary task scratch")
    if not output_id or _artifact_name(output_id) != output_id or "/" in output_id:
        raise ValueError("audit output ID must be one explicit component")
    if not run_root.is_absolute() or Path(computed_results["path"]) != run / "computed-results.json":
        raise ValueError("computed descriptor must belong to the exact explicit run")
    if (run / ".scan-active.json").exists():
        raise ValueError("candidate audit requires an inactive computed run")
    computed = verify_computed_results(computed_results)
    if computed.get("complete") is not True or computed.get("state") != "computed_unpublished" or computed.get("run_root") != str(run):
        raise ValueError("complete unpublished computed results required")
    source, input_id = computed["source"], computed["input_id"]
    source_id = source["source_id"]
    if not isinstance(source_id, str) or not source_id or not isinstance(input_id, str) or not input_id:
        raise ValueError("computed source/input identities required")
    reference = computed["provenance"].get("stock_reference", {})
    reference_path = run / "phase-stock-result.json" if stock_reference is None else stock_reference
    if not reference_path.is_absolute():
        raise ValueError("absolute completed stock reference required")
    reference_path = _owned(reference_path, run)
    if (
        not isinstance(reference, dict)
        or set(reference) != {"path", "bytes", "sha256"}
        or reference.get("path") != str(reference_path)
        or type(reference.get("bytes")) is not int
        or reference["bytes"] != reference_path.stat().st_size
        or reference.get("sha256") != file_digest(reference_path)
    ):
        raise ValueError("completed stock reference differs from computed continuation pin")
    stock_result = read_scan_receipt(reference_path)
    if stock_result.get("phase") != "full_stock_checkpoints" or stock_result.get("global_analysis_admitted") is not False:
        raise ValueError("explicit completed stock checkpoint reference required")
    retained = {row["source_path"]: row for row in computed["artifacts"]}
    named = {row["path"]: row for row in computed["artifacts"]}
    existing_event_audit = _existing_event_audit(named, run)
    selection_path = _owned(Path(named["selection.json"]["source_path"]), run)
    selection = read_json(selection_path)
    if object_digest(selection) != object_digest(computed["provenance"]["selection"]):
        raise ValueError("computed selection differs from retained selection")
    files = {name.removeprefix("q1-q3/"): row["source_path"] for name, row in named.items() if name.startswith("q1-q3/")}
    barrier_path = _owned(run / "global" / "receipt.json", run)
    barrier = read_json(barrier_path)
    if any(_owned(Path(row["path"]), run).parent != barrier_path.parent for row in [*barrier["global_files"].values(), *barrier["sidecars"].values()]):
        raise ValueError("barrier payload outside its explicit owned directory")
    verify_barrier(barrier)
    result = {
        "pool": stock_result["pool"],
        "barrier": barrier,
        "shared_versions": {"labels": computed["provenance"]["label_checkpoint"]},
        "analysis": {"selection": selection, "summary_receipt": {"files": files}},
    }
    if not source_id or not input_id or barrier.get("source_id") != source_id or barrier.get("input_id") != input_id or barrier.get("complete") is not True:
        raise ValueError("audit requires complete approved source/input identities")
    pins_path = roots.primary / "tasks" / TASK / "params" / "input-pins-v1.json.gz"
    calendar = read_preparation_pins(pins_path)["price_observation"]["calendar"]
    dates = pd.DatetimeIndex(pd.to_datetime(calendar["dates"]))
    if (
        barrier.get("calendar") != calendar["dates"]
        or object_digest(calendar["dates"]) != calendar["sha256"]
        or dates.empty
        or dates.hasnans
        or dates.tz is not None
        or not dates.is_unique
        or not dates.is_monotonic_increasing
        or any(day != day.normalize() for day in dates)
        or calendar["dates"][0] != "2010-01-04"
        or calendar["dates"][-1] != "2026-10-12"
    ):
        raise ValueError("audit requires the approved fixed common calendar")
    selected = select_audit_candidates(result["analysis"]["selection"])
    mission = roots.primary / "tasks" / TASK / "mission.md"
    output = _checked_path(run / "audits" / "candidate-reconstruction" / output_id)
    identity = {
        "definition": DEFINITION,
        "parameters": PARAMETERS,
        "source": source,
        "input_id": input_id,
        "computed_results": {"path": str(run / "computed-results.json"), "sha256": computed_results["sha256"]},
        "stock_reference": reference,
        "barrier": {"path": str(barrier_path), "sha256": file_digest(barrier_path)},
        "calendar_sha256": calendar["sha256"],
        "preregistration_sha256": file_digest(mission),
        "selected": list(selected),
    }
    if output.exists():
        saved = read_scan_receipt(output / "receipt.json")
        expected_checks = len(selected) * 4 * 2 * PARAMETERS["rows_per_case"]
        if (
            saved.get("schema") != "pattern-scan-candidate-audit.v4"
            or saved.get("complete") is not True
            or saved.get("identity") != identity
            or saved.get("source_id") != source_id
            or saved.get("input_id") != input_id
            or saved.get("output_path") != str(output)
            or saved.get("selected_candidate_n") != len(selected)
            or saved.get("aggregate_checks") != expected_checks
            or saved.get("audit_complete") != (len(selected) == 5 and expected_checks == PARAMETERS["full_scope_checks"])
            or saved.get("existing_event_audit") != existing_event_audit
            or saved.get("mismatch_n") != 0
        ):
            raise ValueError("retained audit identity differs or is incomplete")
        record = read_scan_receipt(output / "run-receipt.json")
        receipt_descriptors = [row for row in saved["artifacts"] if row["path"] == "run-receipt.json"]
        if len(receipt_descriptors) != 1:
            raise ValueError("retained audit requires one pinned run receipt")
        verify_files(output, receipt_descriptors)
        expected_artifacts = {row["path"]: row for row in receipt_descriptors}
        for row in record["results"].values():
            path = _owned(Path(row["path"]), output)
            name = path.relative_to(output).as_posix()
            if name in expected_artifacts:
                raise ValueError("duplicate retained audit result path")
            expected_artifacts[name] = {"path": name, "bytes": row["bytes"], "sha256": row["sha256"]}
        if (
            len(saved["artifacts"]) != len(expected_artifacts)
            or {row["path"]: row for row in saved["artifacts"]} != expected_artifacts
            or record.get("code") != saved.get("audit_execution_code")
            or record.get("definition") != DEFINITION
            or record.get("run_id") != output_id
            or record.get("parameters") != {"source_id": source_id, "input_id": input_id, **PARAMETERS}
            or not _preregistration_matches(record, mission, identity["preregistration_sha256"])
        ):
            raise ValueError("retained audit result descriptors differ")
        if changed_results(output / "run-receipt.json", CODE_ROOT):
            raise ValueError("retained audit result hashes changed")
        parquet_results = {name: row for name, row in record["results"].items() if name.endswith(".parquet")}
        if set(saved.get("result_files", {})) != set(parquet_results):
            raise ValueError("retained audit Parquet result inventory differs")
        for name, row in parquet_results.items():
            if saved["result_files"][name] != {
                "path": name,
                "bytes": row["bytes"],
                "sha256": row["sha256"],
                "rows": pq.ParquetFile(output / name).metadata.num_rows,
            }:
                raise ValueError("retained audit Parquet row metadata differs")
        for row in record["input_fingerprint"]["inputs"].values():
            path = _checked_path(Path(row["path"]))
            if not path.is_relative_to(run) and path not in (mission, pins_path):
                raise ValueError("retained audit parent escaped declared roots")
            if path.stat().st_size != row["bytes"] or file_digest(path) != row["sha256"]:
                raise ValueError("retained audit parent hashes changed")
        return saved
    code_mission = _checked_path(CODE_ROOT / "tasks" / TASK / "mission.md")
    if mission.read_bytes() != code_mission.read_bytes():
        raise ValueError("retained mission differs from the audit executor's committed mission")
    execution_code = code_identity(CODE_ROOT)
    parents: dict[str, Any] = {}
    for path, digest in (
        (Path(computed_results["path"]), computed_results["sha256"]),
        (reference_path, reference["sha256"]),
        (barrier_path, identity["barrier"]["sha256"]),
        (mission, identity["preregistration_sha256"]),
        (pins_path, None),
    ):
        _pin(path, parents, digest=digest)
    for name, row in named.items():
        if name == "selection.json" or name.startswith("audits/events/"):
            _pin(_owned(Path(row["source_path"]), run), parents, digest=row["sha256"])
    event_parts, summaries = _ancestors(run, result, source_id, input_id, selected, parents, retained)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = _checked_path(output.with_name(f".staging-{output.name}-{uuid.uuid4().hex}"))
    staging.mkdir()
    files, metrics, cases = {}, {}, []
    for candidate in selected:
        target, identifier = candidate["target"], candidate["candidate_id"]
        for group in ("pattern:union", "C-base-no-pattern", "C-base-all", PRIMARY[target]):
            for horizon in (126, 252):
                before = resource_sample()
                metadata = {"pattern_id": target, "control_id": "pattern" if group == "pattern:union" else group, "cohort_id": "union", "horizon": horizon}
                if group != "pattern:union":
                    metadata["primary_control_id"] = PRIMARY[target]
                columns = list(
                    dict.fromkeys([
                        *REQUIRED_COLUMNS,
                        "event_eligibility_excluded",
                        "mkt",
                        *(f"{atom['feature_id']}_{suffix}" for atom in candidate["atoms"] for suffix in ("bin", "status")),
                    ])
                )

                def slim_frames() -> Any:
                    for _, directory in sorted(event_parts[target].items()):
                        yield group_frame(directory, group, horizon).loc[:, columns].copy()

                rebuilt = reconstruct_candidate(slim_frames(), metadata=metadata, candidate_id=identifier, atoms=candidate["atoms"])
                stored = [
                    read_frame(path, filters=[("feature_id", "==", "candidate"), ("candidate_id", "==", identifier), ("split", "==", "cross-check")])
                    for path in summaries[target, group, horizon]
                ]
                counts = compare_candidate(rebuilt, stored_summary=stored[0], stored_annual=stored[1])
                if counts["aggregate_checks"] != PARAMETERS["rows_per_case"]:
                    raise ValueError("independent candidate aggregate case scope differs")
                case_id = object_digest({"target": target, "candidate_id": identifier, "group": group, "horizon": horizon})
                for name in ("summary", "annual", "memberships"):
                    frame = rebuilt[name]
                    if name == "memberships":
                        frame = frame.loc[:, ["security_id", "event_id", "t0", "horizon", "mkt", "membership_state", "split"]].copy()
                        for key, value in {**metadata, "candidate_id": identifier}.items():
                            frame[key] = value
                    path = staging / f"{case_id}-{name}.parquet"
                    with path.open("xb") as stream:
                        frame.to_parquet(stream, index=False, compression="zstd")
                    files[path.name] = path
                    metrics[path.name] = {"rows": pq.ParquetFile(path).metadata.num_rows, "bytes": path.stat().st_size}
                cases.append({
                    "target": target,
                    "candidate_id": identifier,
                    "group": group,
                    "horizon": horizon,
                    **counts,
                    "measurement": phase_receipt("independent_candidate_case", before, resource_sample()),
                })
                del rebuilt, stored, frame
    checks = sum(case["aggregate_checks"] for case in cases)
    audit_complete = len(selected) == 5 and checks == PARAMETERS["full_scope_checks"]
    overview = {
        "definition": DEFINITION,
        "audit_complete": audit_complete,
        "selected_candidate_n": len(selected),
        "expected_full_scope_candidates": 5,
        "aggregate_checks": checks,
        "full_scope_expected_checks": PARAMETERS["full_scope_checks"],
        "status": "complete" if audit_complete else "incomplete_candidate_scope",
        "cases": cases,
        "files": metrics,
        "mismatch_n": 0,
        "existing_event_audit": existing_event_audit,
        "measurement": phase_receipt("independent_candidate_audit_total", started, resource_sample()),
    }
    write_json(staging / "overview.json", overview)
    files["overview.json"] = staging / "overview.json"
    run_receipt = staging / "run-receipt.json"
    write_run_receipt(
        run_receipt,
        run_id=output_id,
        definition=DEFINITION,
        parameters={"source_id": source_id, "input_id": input_id, **PARAMETERS},
        inputs={"captured_at_utc": datetime.now(timezone.utc).isoformat(), "producer_as_of": None, "inputs": parents},
        results=files,
        preregistration=code_mission,
        repo_root=CODE_ROOT,
    )
    record = _rebase_results(run_receipt, staging, output)
    if record["code"] != execution_code:
        raise ValueError("audit execution code changed during reconstruction")
    artifacts = [{"path": name, "bytes": row["bytes"], "sha256": row["sha256"]} for name, row in record["results"].items()]
    artifacts.append(describe_file(staging, run_receipt))
    receipt = {
        "schema": "pattern-scan-candidate-audit.v4",
        "complete": True,
        "identity": identity,
        "source_id": source_id,
        "input_id": input_id,
        "audit_execution_code": record["code"],
        "audit_complete": audit_complete,
        "selected_candidate_n": len(selected),
        "aggregate_checks": checks,
        "mismatch_n": 0,
        "existing_event_audit": existing_event_audit,
        "result_files": {name: {"path": name, **metrics[name], "sha256": record["results"][name]["sha256"]} for name in metrics},
        "full_scope_expected_checks": PARAMETERS["full_scope_checks"],
        "artifacts": artifacts,
        "output_path": str(output),
    }
    publish_scan_receipt(staging / "receipt.json", receipt)
    publish_noreplace(staging, output)
    LOGGER.info("Retained independent candidate audit output=%s candidates=%d checks=%d complete=%s", output, len(selected), checks, audit_complete)
    return receipt
