"""Live-read preparation followed by bounded computation over derived prices.

The producer-read phase finishes and fingerprints its results before numerical
work starts. Later phases consume those derived checkpoints, never reread the
producer or demand that today's live files reproduce historical results.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from research_core.artifact_store import describe_file, file_digest, object_digest, publish_noreplace, read_json, relative_name, verify_files
from research_core.live_producer import assert_producer_idle
from research_core.pattern_scan_barrier_v1 import build_barrier, checkpoint_label_entry, publish_stock_versions, verified_parts
from research_core.pattern_scan_capacity_v2 import require_capacity
from research_core.pattern_scan_execution_v1 import GIT_BOOTSTRAP, ROOT, _MemoryBoundJob, run_requests
from research_core.pattern_scan_git_source_v2 import assert_current_code, git_source_identity
from research_core.pattern_scan_live_inputs_v2 import load_live_inputs
from research_core.pattern_scan_parquet_v1 import read_frame, write_frame
from research_core.pattern_scan_pipeline_v1 import prepare_requests, profile_requests, representative_codes
from research_core.pattern_scan_preflight_v1 import profile_global
from research_core.pattern_scan_profile_v1 import validate_profile
from research_core.pattern_scan_receipt_io_v2 import publish_scan_receipt, read_scan_receipt
from research_core.pattern_scan_run_v1 import _attach_memory, _publish_json
from research_core.producer_data import producer_data_root
from research_core.research_data_paths import DataRoots, _artifact_name, _checked_path
from research_core.research_measurement_v1 import host_resources, phase_receipt, resource_sample
from research_core.run_receipt import InputSpec, changed_results, fingerprint_inputs, write_run_receipt

LOGGER = logging.getLogger(__name__)
TASK = "20261013-pattern-scan"
PUBLICATION_POLICY = "results-only-deferred.v3"


def _retain_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        if object_digest(read_scan_receipt(path)) != object_digest(value):
            raise ValueError(f"retained phase identity differs: {path}")
    else:
        publish_scan_receipt(path, value)


def _capacity(request: dict[str, Any], roots: DataRoots, *, input_id: str | None = None) -> None:
    """Admit only the named phase; later global work retains its own gate."""
    mode = request["mode"]
    if mode not in {"prepare", "stock", "all"}:
        return
    path = None if request.get("capacity_path") is None else Path(request["capacity_path"])
    if request.get("publication_policy") == PUBLICATION_POLICY and mode in {"prepare", "stock"}:
        from research_core.pattern_scan_capacity_v3 import require_phase_capacity

        if path is None or request.get("profile_path") is None:
            raise ValueError("explicit phase capacity and resource observation required")
        expected_input = read_json(path)["input_id"] if input_id is None else input_id
        require_phase_capacity(
            path, roots.primary, phase=mode, source_id=request["source"]["source_id"], input_id=expected_input, profile_path=Path(request["profile_path"])
        )
    else:
        require_capacity(path, roots.primary)


def _execution_profile(request: dict[str, Any], prepared: dict[str, Any]) -> dict[str, Any]:
    path = Path(request["profile_path"])
    if request.get("publication_policy") == PUBLICATION_POLICY:
        from research_core.pattern_scan_profile_observation_v3 import load_execution_profile

        return load_execution_profile(
            path,
            source=request["source"],
            input_id=prepared["input_id"],
            calendar_n=prepared["calendar_n"],
            ordinary_reference_n=prepared["ordinary_reference_n"],
        )
    profile = read_json(path)
    validate_profile(profile, source=request["source"], input_id=prepared["input_id"])
    return profile


def _receipt(path: Path, **kwargs: Any) -> None:
    if path.exists():
        saved = read_json(path)
        if (
            saved.get("run_id") != kwargs["run_id"]
            or saved.get("definition") != kwargs["definition"]
            or saved.get("parameters") != kwargs["parameters"]
            or changed_results(path, ROOT)
        ):
            raise ValueError("existing phase receipt differs")
        return
    staging = path.with_name(f".staging-{path.name}-{uuid.uuid4().hex}")
    write_run_receipt(staging, **kwargs)
    publish_noreplace(staging, path)


def verify_completion(response: Path, request: dict[str, Any], roots: DataRoots) -> dict[str, Any]:
    """Inspect historical result hashes without opening current producer inputs."""
    saved = read_scan_receipt(response)
    receipt = _checked_path(Path(saved["run_receipt_path"]))
    record = read_json(receipt)
    if (
        saved.get("schema") != "pattern-scan-coordinator-receipt.v2"
        or saved.get("complete") is not True
        or saved.get("request_id") != object_digest(request)
        or saved.get("source_id") != request["source"]["source_id"]
        or receipt.parent != response.parent
        or file_digest(receipt) != saved.get("run_receipt_sha256")
        or record.get("run_id") != request["run_id"]
        or record.get("parameters", {}).get("source_id") != request["source"]["source_id"]
        or record.get("parameters", {}).get("input_id") != saved.get("input_id")
        or record.get("code") != request["source"]["code"]
        or changed_results(receipt, ROOT)
    ):
        raise ValueError("historical scan result identity differs or is incomplete")
    result = saved["result"]
    phase_path = Path(record["results"]["phase_result"]["path"])
    phase_path = _checked_path(phase_path if phase_path.is_absolute() else ROOT / phase_path)
    if phase_path.parent != response.parent or read_scan_receipt(phase_path) != result:
        raise ValueError("historical phase result identity differs from response")
    if result["phase"] in {"full_stock_shared_versions", "complete_pattern_scan"}:
        from research_core.research_data_catalog import verify_entry

        for entry in result["shared_versions"].values():
            verify_entry(entry, roots)
        if result["phase"] == "complete_pattern_scan":
            for key in ("shared_event_outcomes", "shared_episodes", "shared_report_tables"):
                verify_entry(result["analysis"][key], roots)
    elif result["phase"] == "computed_pattern_scan_unpublished":
        from research_core.pattern_scan_result_lifecycle_v3 import verify_computed_results

        verify_computed_results(result["analysis"]["retained_result"])
    return _attach_memory(saved, response, request)


def launch(
    roots: DataRoots,
    *,
    mode: str,
    run_id: str,
    calculation_authorized: bool = False,
    prepared_path: Path | None = None,
    profile_path: Path | None = None,
    capacity_path: Path | None = None,
    memory_bytes: int = 6 * 1024**3,
    job_memory_bytes: int = 8 * 1024**3,
    timeout_seconds: float = 8 * 3600,
) -> dict[str, Any]:
    if calculation_authorized is not True:
        raise PermissionError("explicit approved pattern-scan calculation authorization required")
    if mode not in {"prepare", "profile", "storage-profile", "stock", "all"} or not run_id or relative_name(run_id) != run_id or "/" in run_id:
        raise ValueError("explicit supported phase and one task run identifier required")
    if type(memory_bytes) is not int or type(job_memory_bytes) is not int or not 0 < memory_bytes < job_memory_bytes <= 8 * 1024**3:
        raise ValueError("finite coordinator and child memory caps required")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds < 86400:
        raise ValueError("bounded coordinator timeout required")
    _artifact_name(run_id)
    roots.validate_worktree(ROOT)
    run = _checked_path(roots.primary / ".tmp" / "pattern-scan-execution" / run_id)
    run.mkdir(parents=True, exist_ok=True)
    if (run / "cleanup-receipt.json").exists():
        from research_core.research_data_catalog import verify_entry

        retired = read_scan_receipt(run / "cleanup-receipt.json")
        if retired.get("schema") != "pattern-scan-cleanup.v3" or retired.get("complete") is not True or retired.get("run_root") != str(run):
            raise ValueError("invalid retained-result cleanup receipt")
        verify_entry(retired["entry"], roots)
        return {
            "complete": True,
            "source_id": retired["entry"]["inputs"]["source_id"],
            "result": {"phase": "retained_result_published", "entry": retired["entry"]},
        }
    path, response = run / f"request-{mode}.json", run / f"response-{mode}.json"
    if path.exists():
        request = read_json(path)
        expected = {
            "mode": mode,
            "run_id": run_id,
            "primary": str(roots.primary),
            "data": str(roots.data),
            "prepared_path": None if prepared_path is None else str(prepared_path.resolve()),
            "profile_path": None if profile_path is None else str(profile_path.resolve()),
            "capacity_path": None if capacity_path is None else str(capacity_path.resolve()),
            "memory_bytes": memory_bytes,
            "job_memory_bytes": job_memory_bytes,
            "timeout_seconds": timeout_seconds,
        }
        if any(request.get(key) != value for key, value in expected.items()):
            raise ValueError("existing run parameters differ; preserve it and choose a new run identifier")
        if response.exists():
            return verify_completion(response, request, roots)
        assert_current_code(request["source"], ROOT)
    else:
        request = {
            "schema": "pattern-scan-coordinator-request.v2",
            "calculation_authorized": True,
            "mode": mode,
            "run_id": run_id,
            "primary": str(roots.primary),
            "data": str(roots.data),
            "run_root": str(run),
            "source": git_source_identity(ROOT),
            "publication_policy": PUBLICATION_POLICY,
            "memory_bytes": memory_bytes,
            "job_memory_bytes": job_memory_bytes,
            "timeout_seconds": timeout_seconds,
            "producer_root": str(producer_data_root()) if mode in {"prepare", "profile"} else None,
            "prepared_path": None if prepared_path is None else str(prepared_path.resolve()),
            "profile_path": None if profile_path is None else str(profile_path.resolve()),
            "capacity_path": None if capacity_path is None else str(capacity_path.resolve()),
        }
        _publish_json(path, request)
    _capacity(request, roots)
    available = host_resources()["physical_available_bytes"]
    if available is None or available - job_memory_bytes < 4 * 1024**3:
        raise ValueError("cannot establish coordinator cap and four GiB host reserve")
    active = run / ".scan-active.json"
    token = {"request_id": object_digest(request), "owner": uuid.uuid4().hex}
    _publish_json(active, token)
    job = None
    started = time.monotonic()
    try:
        job = _MemoryBoundJob(job_memory_bytes)
        process = job.start([sys.executable, "-c", GIT_BOOTSTRAP, str(ROOT), str(path)], ROOT)
        while process.poll() is None:
            if time.monotonic() - started > timeout_seconds:
                raise TimeoutError("owned coordinator timeout; completed checkpoints remain available for resume")
            time.sleep(0.2)
        if process.returncode != 0:
            raise ValueError(f"owned live scan coordinator failed exit={process.returncode}; retained scratch={run}")
        memory_path = response.with_suffix(".job-memory.json")
        if not memory_path.exists():
            _publish_json(
                memory_path,
                {
                    "schema": "pattern-scan-coordinator-memory.v1",
                    "complete": True,
                    "request_id": object_digest(request),
                    "response_sha256": file_digest(response),
                    "job_memory": job.memory_receipt(),
                },
            )
        return verify_completion(response, request, roots)
    finally:
        if job is not None:
            job.terminate_and_confirm()
            job.close()
        if active.exists() and read_json(active) == token:
            active.unlink()


def _prepare(roots: DataRoots, request: dict[str, Any], run: Path) -> tuple[dict[str, Any], Path]:
    """End the short live-read run with derived-result hashes before computation."""
    index = run / "derived-preparation.json"
    receipt_path = run / "producer-read-receipt.json"
    if index.exists():
        record = read_json(index)
        if record.get("schema") != "pattern-scan-derived-preparation.v2" or record.get("source") != request["source"]:
            raise ValueError("retained preparation source or protocol differs")
        expected_scope = "full_ordinary_reference" if request["mode"] == "prepare" else "representative_resource_probe"
        if record.get("scope") != expected_scope:
            raise ValueError("retained preparation scope differs from requested phase")
        verify_files(run, record["artifacts"])
        if not receipt_path.exists():
            assert_producer_idle()
            _receipt(
                receipt_path,
                run_id=request["run_id"] + ":producer-read",
                definition="pattern-scan-price-preparation.v2",
                parameters={"cutoff": "2026-10-12", "start": "2010-01-04", "scope": record["scope"]},
                inputs=record["producer_fingerprint"],
                results={"derived_preparation": index},
                preregistration=ROOT / "tasks" / TASK / "mission.md",
                repo_root=ROOT,
            )
        if changed_results(receipt_path, ROOT):
            raise ValueError("derived preparation lacks its complete producer-read receipt")
        return record, index
    pins = ROOT / "tasks" / TASK / "params" / "input-pins-v1.json.gz"
    if str(producer_data_root()) != request["producer_root"]:
        raise ValueError("effective live producer root differs from request")
    snapshot = load_live_inputs(roots, pins_path=pins)
    codes, strata = representative_codes(snapshot)
    ordinary_n = int(snapshot.inventory["included"].sum())
    if request["mode"] == "prepare":
        if request["profile_path"] is None:
            raise ValueError("full-market price preparation requires a measured same-input profile")
        _execution_profile(request, {"input_id": snapshot.input_id, "calendar_n": len(snapshot.calendar), "ordinary_reference_n": ordinary_n})
        _capacity(request, roots, input_id=snapshot.input_id)
        codes = tuple(sorted(snapshot.inventory.loc[snapshot.inventory["included"], "code"].astype(str)))
    packets, measurement = prepare_requests(snapshot, codes, request["source"], run, calculation_authorized=True)
    benchmark = run / "prepared" / "benchmark.parquet"
    if not benchmark.exists():
        with benchmark.open("xb") as stream:
            write_frame(snapshot.stock("0050"), stream, index=True)
    snapshot.verify_after()
    artifacts = [describe_file(run, Path(packet["prepared_path"])) for packet in packets]
    artifacts.append(describe_file(run, benchmark))
    record = {
        "schema": "pattern-scan-derived-preparation.v2",
        "source": request["source"],
        "input_id": snapshot.input_id,
        "producer_fingerprint": snapshot.fingerprint,
        "calendar_n": len(snapshot.calendar),
        "ordinary_reference_n": ordinary_n,
        "scope": "full_ordinary_reference" if request["mode"] == "prepare" else "representative_resource_probe",
        "strata": strata,
        "requests": packets,
        "benchmark_path": str(benchmark),
        "artifacts": artifacts,
        "measurements": [*snapshot.consumption_measurements, measurement],
    }
    _retain_json(index, record)
    _receipt(
        receipt_path,
        run_id=request["run_id"] + ":producer-read",
        definition="pattern-scan-price-preparation.v2",
        parameters={"cutoff": "2026-10-12", "start": "2010-01-04", "scope": record["scope"]},
        inputs=snapshot.fingerprint,
        results={"derived_preparation": index},
        preregistration=ROOT / "tasks" / TASK / "mission.md",
        repo_root=ROOT,
    )
    LOGGER.info("Finished producer-read phase; subsequent computation consumes derived prices only run=%s", run)
    return record, index


def _derived_inputs(index: Path, request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if index.name != "derived-preparation.json" or index.parent.parent != Path(request["primary"]) / ".tmp" / "pattern-scan-execution":
        raise ValueError("derived preparation must be in primary task-owned scratch")
    record = read_json(_checked_path(index), max_bytes=128_000_000)
    if record.get("schema") != "pattern-scan-derived-preparation.v2" or record.get("source") != request["source"]:
        raise ValueError("derived preparation protocol or source identity differs")
    verify_files(index.parent, record["artifacts"])
    producer_receipt = index.parent / "producer-read-receipt.json"
    if changed_results(producer_receipt, ROOT):
        raise ValueError("producer-read result identity differs")
    specs = [
        InputSpec("derived_preparation", index, live_producer=False),
        InputSpec("producer_read_receipt", producer_receipt, live_producer=False),
        InputSpec("derived_prices", index.parent / "prepared", pattern="**/*.parquet", live_producer=False),
    ]
    for name, key in (("resource_profile", "profile_path"), ("capacity_plan", "capacity_path")):
        if request.get(key) is not None:
            specs.append(InputSpec(name, _checked_path(Path(request[key])), live_producer=False))
    phase_request = Path(request["run_root"]) / f"request-{request['mode']}.json"
    if phase_request.is_file():
        specs.append(InputSpec("phase_request", phase_request, live_producer=False))
    fingerprint = fingerprint_inputs(specs)
    return record, fingerprint


def coordinator_main(request_path: Path) -> None:
    request = read_json(_checked_path(request_path))
    if request.get("schema") != "pattern-scan-coordinator-request.v2" or request.get("calculation_authorized") is not True:
        raise PermissionError("approved live scan protocol required")
    source = request["source"]
    assert_current_code(source, ROOT)
    roots = DataRoots(Path(request["primary"]), Path(request["data"]))
    run = _checked_path(Path(request["run_root"]))
    if run.parent != roots.primary / ".tmp" / "pattern-scan-execution" or request_path.parent != run:
        raise ValueError("coordinator outside primary task scratch")
    mode = request["mode"]
    _capacity(request, roots)
    before = resource_sample()
    if mode in {"prepare", "profile"}:
        prepared, index = _prepare(roots, request, run)
    else:
        if request["prepared_path"] is None:
            raise ValueError("computation requires an explicit completed derived preparation")
        index = _checked_path(Path(request["prepared_path"]))
        prepared = read_json(index, max_bytes=128_000_000)
        expected_scope = "representative_resource_probe" if mode == "storage-profile" else "full_ordinary_reference"
        if prepared.get("scope") != expected_scope:
            raise ValueError("representative preparation cannot certify full-market computation or change resource scope")
    prepared, fingerprint = _derived_inputs(index, request)
    input_id = prepared["input_id"]
    benchmark = read_frame(Path(prepared["benchmark_path"]))
    packets = [{**packet, "run_root": str(run)} for packet in prepared["requests"]]
    # Existing workers require owned derived frames inside this run, without copying them.
    # Full phases therefore continue the preparation's run rather than moving checkpoints.
    if mode in {"stock", "all"} and index.parent != run:
        raise ValueError("full computation must resume the same derived-preparation run")
    result: dict[str, Any]
    results: dict[str, Path] = {"derived_preparation": index}
    if mode == "prepare":
        result = {"phase": "derived_price_preparation", "prepared_path": str(index), "scope": prepared["scope"]}
    elif mode == "profile":
        profile_path = run / "resource-profile.json"
        if profile_path.exists():
            profile = read_json(profile_path, max_bytes=128_000_000)
        else:
            profile = profile_requests(packets, memory_bytes=request["memory_bytes"], estimated_worker_bytes=512 * 1024**2)
            profile["strata"] = prepared["strata"]
            parts = verified_parts(profile["profiles"][0]["results"], source=source, input_id=input_id)
            sample = {code: parts[code] for code in sorted(parts)[:4]}
            preflight = run / f"preflight-{uuid.uuid4().hex}"
            profile["global_preflight"] = profile_global(sample, benchmark, preflight, source=source, input_id=input_id)
            profile["global_preflight_path"] = str(preflight)
            profile["estimate"] = {"ordinary_reference_n": prepared["ordinary_reference_n"], "calendar_n": prepared["calendar_n"]}
            profile["live_read_policy"] = "producer-read receipt completed before numerical work; derived checkpoints only"
            _publish_json(profile_path, profile)
        validate_profile(profile, source=source, input_id=input_id)
        result = {"phase": "resource_profile", "profile_path": str(profile_path), "profile": profile}
        results["resource_profile"] = profile_path
    elif mode == "storage-profile":
        from research_core.pattern_scan_analysis_v1 import prepare_event_parts
        from research_core.pattern_scan_storage_profile_v2 import profile_storage

        if request["profile_path"] is None:
            raise ValueError("storage profile requires a completed representative resource profile")
        profile = read_json(_checked_path(Path(request["profile_path"])), max_bytes=128_000_000)
        validate_profile(profile, source=source, input_id=input_id)
        reference = verified_parts(profile["profiles"][0]["results"], source=source, input_id=input_id)
        parts = {code: reference[code] for code in profile["global_preflight"]["security_codes"]}
        preflight = _checked_path(Path(profile["global_preflight_path"]))
        if read_json(preflight / "receipt.json") != profile["global_preflight"]:
            raise ValueError("representative preflight receipt differs from measured profile")
        barrier = read_json(preflight / "barrier" / "receipt.json")
        labels = {
            code: next(record for record in read_json(directory / "receipt.json")["artifacts"] if record["path"] == "base_labels.parquet")
            for code, directory in parts.items()
        }
        entries = {
            "labels": {
                "version_id": f"preflight-only:{object_digest({'source': source['source_id'], 'input': input_id, 'labels': labels})}",
                "manifest": {"sha256": object_digest(labels)},
            }
        }
        event_parts = prepare_event_parts(parts, barrier, entries, preflight / "events", source=source, input_id=input_id)
        observation = profile_storage(parts, barrier, event_parts, run / "storage-profile", source=source, input_id=input_id)
        result = {"phase": "representative_full_storage_profile", "observation": observation}
        results["storage_observation"] = run / "storage-profile" / "receipt.json"
    else:
        if request["profile_path"] is None:
            raise ValueError("formal computation requires a measured same-source/input profile")
        profile = _execution_profile(request, prepared)
        _capacity(request, roots, input_id=input_id)
        limits = profile["selected"]
        pool = run_requests(
            packets,
            workers=limits["workers"],
            memory_bytes=limits["memory_cap_bytes"],
            estimated_worker_bytes=limits["estimated_worker_bytes"],
            stocks_per_process=limits["stocks_per_process"],
            timeout_seconds=limits["timeout_seconds"],
        )
        parts = verified_parts(pool["results"], source=source, input_id=input_id)
        deferred = request.get("publication_policy") == PUBLICATION_POLICY
        bound_barrier: dict[str, Any] | None = None
        bound_entries: dict[str, dict[str, Any]] | None = None
        if deferred and mode == "stock":
            result = {
                "phase": "full_stock_checkpoints",
                "pool": pool,
                "global_analysis_admitted": False,
                "resource_observation": profile.get("observation_provenance"),
            }
        else:
            bound_barrier = build_barrier(parts, benchmark, run / "global")
            bound_entries = (
                {"labels": checkpoint_label_entry(parts, source=source, input_id=input_id)}
                if deferred
                else publish_stock_versions(roots, parts, bound_barrier, source=source, input_id=input_id)
            )
            result = {
                "phase": "full_stock_checkpoints" if deferred else "full_stock_shared_versions",
                "pool": pool,
                "barrier": bound_barrier,
                "shared_versions": bound_entries,
            }
        if mode == "all":
            from research_core.pattern_scan_analysis_v1 import run_analysis

            assert bound_barrier is not None and bound_entries is not None
            result["analysis"] = run_analysis(
                roots,
                parts,
                bound_barrier,
                bound_entries,
                run / "analysis",
                source=source,
                input_id=input_id,
                **({"defer_publication": True} if deferred else {}),
            )
            result["phase"] = "computed_pattern_scan_unpublished" if deferred else "complete_pattern_scan"
    result_path = run / f"phase-{mode}-result.json"
    _retain_json(result_path, result)
    results["phase_result"] = result_path
    receipt_path = run / f"run-{mode}-receipt.json"
    _receipt(
        receipt_path,
        run_id=request["run_id"],
        definition="pattern-scan.v1/live-input-execution.v2",
        parameters={
            "start": "2010-01-04",
            "cutoff": "2026-10-12",
            "mode": mode,
            "source_id": source["source_id"],
            "input_id": input_id,
            "memory_bytes": request["memory_bytes"],
            "job_memory_bytes": request["job_memory_bytes"],
            "timeout_seconds": request["timeout_seconds"],
        },
        inputs=fingerprint,
        results=results,
        preregistration=ROOT / "tasks" / TASK / "mission.md",
        repo_root=ROOT,
    )
    publish_scan_receipt(
        request_path.with_name(f"response-{mode}.json"),
        {
            "schema": "pattern-scan-coordinator-receipt.v2",
            "complete": True,
            "request_id": object_digest(request),
            "source_id": source["source_id"],
            "input_id": input_id,
            "run_receipt_path": str(receipt_path),
            "run_receipt_sha256": file_digest(receipt_path),
            "result": result,
            "measurements": [phase_receipt("coordinator_total", before, resource_sample())],
        },
    )
