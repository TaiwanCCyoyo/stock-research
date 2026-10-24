"""Bounded, semantics-preserving CPU and I/O probe for PR17 local pools."""

from __future__ import annotations

import logging
import pickle
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
from pandas.testing import assert_frame_equal

from research_core.artifact_store import read_json, write_json
from research_core.hhhl_variants_selection import split_for_code
from research_core.pattern_scan_groups_v1 import PRIMARY
from research_core.pattern_scan_local_conditions_v5 import _selection_record
from research_core.pattern_scan_local_inputs_v5 import EVENT_FILES, LocalInputs, write_progress
from research_core.pattern_scan_local_parallel_v5 import (
    GroupJob,
    InputSpec,
    bounded_results,
    process_pool,
    summarize_group,
    validate_workers,
)
from research_core.research_data_paths import checked_path
from research_core.research_measurement_v1 import host_resources, phase_receipt, resource_sample

LOGGER = logging.getLogger(__name__)

TARGET = "B2"
CASES = (("pattern:union", 252), ("C-base-all", 126))
GROUPS = tuple(group for group, _ in CASES)
HORIZONS = (126, 252)
DEFAULT_WORKERS = (1, 2, 4, 8, 10)


def _selection_path(continuation: Path) -> Path:
    candidates = (
        continuation / TARGET / "conditions" / f"{TARGET}-selection.json",
        continuation / TARGET / ".staging-conditions" / f"{TARGET}-selection.json",
    )
    found = [path for path in candidates if path.is_file()]
    if len(found) != 1:
        raise ValueError(f"expected one existing B2 selection record, found {len(found)}")
    return found[0]


def _sample_codes(inputs: LocalInputs) -> tuple[str, ...]:
    cached = inputs._cached_codes.get(TARGET, set())
    splits = {split: sorted(code for code in inputs.codes if code in cached and split_for_code(code) == split)[:4] for split in ("development", "cross-check")}
    if any(len(codes) != 4 for codes in splits.values()):
        raise ValueError("paused B2 event cache needs at least four stocks from each CRC split")
    return tuple((*splits["development"], *splits["cross-check"]))


def _native_totals(measurements: list[dict[str, Any]]) -> dict[str, Any]:
    cpu = 0.0
    peak_memory: int | None = None
    io_totals: dict[str, int] = {}
    for measurement in measurements:
        cpu += float(measurement.get("cpu_seconds", 0.0))
        native = measurement.get("native")
        if isinstance(native, dict):
            peak = native.get("peak_working_set_process_lifetime_bytes")
            if isinstance(peak, int):
                peak_memory = peak if peak_memory is None else max(peak_memory, peak)
            io = native.get("io_delta")
            if isinstance(io, dict):
                for key, value in io.items():
                    if isinstance(value, int):
                        io_totals[key] = io_totals.get(key, 0) + value
        initialization = measurement.get("initialization")
        if isinstance(initialization, dict):
            cpu += float(initialization.get("cpu_seconds", 0.0))
            native = initialization.get("native")
            if isinstance(native, dict):
                peak = native.get("peak_working_set_process_lifetime_bytes")
                if isinstance(peak, int):
                    peak_memory = peak if peak_memory is None else max(peak_memory, peak)
                io = native.get("io_delta")
                if isinstance(io, dict):
                    for key, value in io.items():
                        if isinstance(value, int):
                            io_totals[key] = io_totals.get(key, 0) + value
    return {"aggregate_worker_cpu_seconds": cpu, "aggregate_worker_io_delta": io_totals or None, "max_worker_peak_working_set_bytes": peak_memory}


def _compare_group_outputs(
    baseline: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
) -> int:
    compared = 0
    if baseline is current:
        return 0
    if {key.rsplit("|r", 1)[0] for key in baseline} != {key.rsplit("|r", 1)[0] for key in current}:
        raise AssertionError("parallel group job inventory differs from serial baseline")
    for key, right in current.items():
        left = baseline[key.rsplit("|r", 1)[0] + "|r0"]
        if len(left["paths"]) != 3 or len(right["paths"]) != 3:
            raise AssertionError(f"group job {key} did not produce three final tables")
        if "comparison_frames" not in left:
            left["comparison_frames"] = [pd.read_parquet(path) for path in left["paths"]]
        for left_frame, right_path in zip(left["comparison_frames"], right["paths"], strict=True):
            assert_frame_equal(left_frame, pd.read_parquet(right_path), check_exact=True)
            compared += 1
        assert_frame_equal(
            pd.DataFrame.from_records(left["top_rows"] or []),
            pd.DataFrame.from_records(right["top_rows"] or []),
            check_exact=True,
        )
    return compared


def _compare_projection_outputs(baseline: Path, current: Path, codes: tuple[str, ...], cache: dict[tuple[str, str], pd.DataFrame]) -> int:
    compared = 0
    if baseline == current:
        return 0
    for code in codes:
        for name in EVENT_FILES:
            key = (code, name)
            if key not in cache:
                cache[key] = pd.read_parquet(baseline / code / f"{name}.parquet")
            left = cache[key]
            right = pd.read_parquet(current / code / f"{name}.parquet")
            assert_frame_equal(left, right, check_exact=True)
            compared += 1
    return compared


def run_probe(
    stock_result: Path,
    continuation: Path,
    output: Path,
    *,
    workers: tuple[int, ...] = DEFAULT_WORKERS,
) -> dict[str, Any]:
    """Benchmark fixed B2 group and projection samples into a registered run."""
    stock_result, continuation, output = (checked_path(path) for path in (stock_result, continuation, output))
    worker_counts = tuple(validate_workers(value) for value in workers)
    if not worker_counts or len(set(worker_counts)) != len(worker_counts) or 1 not in worker_counts:
        raise ValueError("worker counts must be unique and include the serial baseline 1")
    probe_root = output / "pattern-scan-parallel-probe-v5"
    probe_root.mkdir()

    source = LocalInputs(stock_result, continuation / "_temporary")
    cache = continuation / "_temporary" / "events" / TARGET
    source.attach_target(TARGET, cache, require_complete=False)
    source.projection_build_allowed = False
    cached_codes = tuple(sorted(source._cached_codes[TARGET]))
    group_codes = _sample_codes(source)
    projection_codes = tuple(code for code in source.codes if code not in source._cached_codes[TARGET] and (TARGET, code) not in source.existing)[:16]
    if len(projection_codes) != 16:
        raise ValueError("paused B2 event cache leaves fewer than sixteen original stocks for projection probe")

    _, candidates = _selection_record(_selection_path(continuation), TARGET)
    reference = source.bound(TARGET, group_codes[0])
    missing_groups = set(GROUPS) - set(reference.daily_groups)
    if missing_groups:
        raise ValueError(f"B2 event schema lacks required benchmark groups: {sorted(missing_groups)}")
    del reference

    # Equalize selected input-file cache warmth before the first timed arm.
    warm_started = resource_sample()
    warm_paths = [cache / code / f"{name}.parquet" for code in group_codes for name in EVENT_FILES]
    warm_paths += [
        source.parts[code] / f"{name}.parquet"
        for code in projection_codes
        for name in ("indicators", "pivots", "common_values", "universe", "pattern_states", "raw_events", "cohort_events", "controls", "base_labels")
    ]
    warm_paths += [Path(source.barrier["global_files"][code]["path"]) for code in projection_codes]
    warm_bytes = 0
    for path in warm_paths:
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                warm_bytes += len(block)
    warmup = {**phase_receipt("selected-input-cache-warmup", warm_started, resource_sample()), "bytes_read": warm_bytes}

    main_groups = {"pattern:union", "C-base-no-pattern", "C-base-all", PRIMARY[TARGET]}
    group_runs: dict[int, dict[str, dict[str, Any]]] = {}
    group_measures: dict[str, Any] = {}
    spec = InputSpec(stock_result, continuation / "_temporary", TARGET, cache, source.codes, False, True)
    pickle_started = time.perf_counter()
    initializer_pickle_bytes = len(pickle.dumps(spec))
    initializer_pickle_seconds = time.perf_counter() - pickle_started
    for worker_count in worker_counts:
        repeats = max(1, (worker_count + 1) // 2)
        job_count = len(CASES) * repeats
        LOGGER.info("Start conditions probe workers=%d jobs=%d stocks=%d", worker_count, job_count, len(group_codes))
        write_progress(output / "probe-progress.json", {"step": 0, "total": job_count, "label": f"Conditions probe: {worker_count} workers"})
        run_dir = probe_root / f"groups-w{worker_count}"
        run_dir.mkdir()
        jobs = [
            GroupJob(
                group,
                horizon,
                candidates if group in main_groups else {},
                run_dir / f"{quote(group, safe='')}-h{horizon}-r{repeat}",
                group_codes,
            )
            for repeat in range(repeats)
            for group, horizon in CASES
        ]
        metrics: dict[str, Any] = {}
        measured: list[dict[str, Any]] = []
        results: dict[str, dict[str, Any]] = {}
        before = resource_sample()
        with process_pool(spec, worker_count) as pool:
            for job, result in bounded_results(pool, summarize_group, jobs, workers=worker_count, metrics=metrics):
                repeat = job.staging.name.rsplit("-r", 1)[1]
                key = f"{job.group}|h{job.horizon}|r{repeat}"
                results[key] = result
                measured.append(result["measurement"])
                write_progress(output / "probe-progress.json", {"step": len(results), "total": job_count, "label": f"Conditions probe: {worker_count} workers"})
        whole_pool = phase_receipt("group-pool", before, resource_sample())
        if len(results) != job_count:
            raise ValueError("probe result inventory differs from its admitted job count")
        group_runs[worker_count] = results
        group_measures[str(worker_count)] = {
            "pool": whole_pool,
            **metrics,
            **_native_totals(measured),
            "worker_tasks": measured,
            "jobs": len(results),
            "output_tables": sum(len(row["paths"]) for row in results.values()),
            "pickle_bytes_per_second": metrics["job_pickle_bytes"] / metrics["job_pickle_seconds"] if metrics["job_pickle_seconds"] else None,
        }
        write_progress(probe_root / "group-measurements.json", group_measures)
        LOGGER.info("Complete conditions probe workers=%d wall_seconds=%.3f", worker_count, whole_pool["wall_seconds"])

    baseline_groups = group_runs[1]
    group_comparisons: dict[str, Any] = {}
    for worker_count in worker_counts:
        LOGGER.info("Verify conditions probe workers=%d", worker_count)
        before_compare = time.perf_counter()
        count = _compare_group_outputs(baseline_groups, group_runs[worker_count])
        group_comparisons[str(worker_count)] = {"exact_tables": count, "comparison_seconds": time.perf_counter() - before_compare}
    for row in baseline_groups.values():
        row.pop("comparison_frames", None)

    projection_runs: dict[int, Path] = {}
    projection_measures: dict[str, Any] = {}
    for worker_count in worker_counts:
        LOGGER.info("Start projection probe workers=%d stocks=%d", worker_count, len(projection_codes))
        write_progress(output / "probe-progress.json", {"step": 0, "total": len(projection_codes), "label": f"Projection probe: {worker_count} workers"})
        trial = probe_root / f"projections-w{worker_count}"
        temporary = trial / "_temporary"
        destination = temporary / "events" / TARGET
        trial.mkdir()
        temporary.mkdir()
        inputs = LocalInputs(stock_result, temporary)
        inputs.codes = projection_codes
        inputs.workers = worker_count
        before = resource_sample()
        inputs.cache_target(TARGET, destination)
        wall = phase_receipt("projection-cache", before, resource_sample())
        projection_runs[worker_count] = destination
        execution_path = destination / "parallel-execution.json"
        pool_measurement = read_json(execution_path) if execution_path.is_file() else {}
        tasks = pool_measurement.get("tasks", []) if isinstance(pool_measurement, dict) else []
        projection_measures[str(worker_count)] = {
            "pool": wall,
            "worker_tasks": tasks,
            "first_result_seconds": pool_measurement.get("first_result_seconds") if isinstance(pool_measurement, dict) else None,
            "max_in_flight": pool_measurement.get("max_in_flight", 1) if isinstance(pool_measurement, dict) else 1,
            "job_pickle_bytes": pool_measurement.get("job_pickle_bytes", 0) if isinstance(pool_measurement, dict) else 0,
            "job_pickle_seconds": pool_measurement.get("job_pickle_seconds", 0.0) if isinstance(pool_measurement, dict) else 0.0,
            "pickle_bytes_per_second": (
                pool_measurement["job_pickle_bytes"] / pool_measurement["job_pickle_seconds"]
                if isinstance(pool_measurement, dict) and pool_measurement.get("job_pickle_seconds")
                else None
            ),
            **_native_totals(tasks),
        }
        write_progress(probe_root / "projection-measurements.json", projection_measures)
        LOGGER.info("Complete projection probe workers=%d wall_seconds=%.3f", worker_count, wall["wall_seconds"])

    projection_comparisons: dict[str, Any] = {}
    reference_frames: dict[tuple[str, str], pd.DataFrame] = {}
    for worker_count in worker_counts:
        before_compare = time.perf_counter()
        count = _compare_projection_outputs(projection_runs[1], projection_runs[worker_count], projection_codes, reference_frames)
        projection_comparisons[str(worker_count)] = {"exact_parquet_tables": count, "comparison_seconds": time.perf_counter() - before_compare}

    group_base_rate = group_measures["1"]["jobs"] / group_measures["1"]["pool"]["wall_seconds"]
    projection_base_wall = projection_measures["1"]["pool"]["wall_seconds"]
    summary = {
        "group": {
            str(count): {
                "workers": count,
                "wall_seconds": group_measures[str(count)]["pool"]["wall_seconds"],
                "cpu_seconds": group_measures[str(count)]["pool"]["cpu_seconds"],
                "aggregate_worker_cpu_seconds": group_measures[str(count)]["aggregate_worker_cpu_seconds"],
                "jobs": group_measures[str(count)]["jobs"],
                "jobs_per_second": group_measures[str(count)]["jobs"] / group_measures[str(count)]["pool"]["wall_seconds"],
                "speedup_vs_1": (group_measures[str(count)]["jobs"] / group_measures[str(count)]["pool"]["wall_seconds"]) / group_base_rate,
                "exact_tables": group_comparisons[str(count)]["exact_tables"],
                "comparison_seconds": group_comparisons[str(count)]["comparison_seconds"],
                "max_in_flight": group_measures[str(count)]["max_in_flight"],
                "pickle_bytes_per_second": group_measures[str(count)]["pickle_bytes_per_second"],
            }
            for count in worker_counts
        },
        "projection": {
            str(count): {
                "workers": count,
                "wall_seconds": projection_measures[str(count)]["pool"]["wall_seconds"],
                "cpu_seconds": projection_measures[str(count)]["pool"]["cpu_seconds"],
                "aggregate_worker_cpu_seconds": projection_measures[str(count)]["aggregate_worker_cpu_seconds"],
                "speedup_vs_1": projection_base_wall / projection_measures[str(count)]["pool"]["wall_seconds"],
                "exact_parquet_tables": projection_comparisons[str(count)]["exact_parquet_tables"],
                "comparison_seconds": projection_comparisons[str(count)]["comparison_seconds"],
                "max_in_flight": projection_measures[str(count)]["max_in_flight"],
                "pickle_bytes_per_second": projection_measures[str(count)]["pickle_bytes_per_second"],
            }
            for count in worker_counts
        },
    }
    details = {
        "target": TARGET,
        "groups": list(GROUPS),
        "cases": [list(case) for case in CASES],
        "horizons": list(HORIZONS),
        "worker_counts": list(worker_counts),
        "cached_code_count": len(cached_codes),
        "group_sample_codes": list(group_codes),
        "projection_sample_codes": list(projection_codes),
        "source_code_count": len(source.codes),
        "host": host_resources(),
        "input_cache_warmup": warmup,
        "initializer_descriptor_pickle_bytes": initializer_pickle_bytes,
        "initializer_descriptor_pickle_seconds": initializer_pickle_seconds,
        "unavailable_observations": [
            "isolated interpreter spawn/import wall time; included in first-result latency",
            "physical disk throughput; native I/O includes cached transfers",
        ],
        "group_measurements": group_measures,
        "projection_measurements": projection_measures,
        "comparisons": {"group": group_comparisons, "projection": projection_comparisons},
    }
    write_json(probe_root / "summary.json", summary)
    write_json(probe_root / "measurements.json", details)
    return {"summary": summary, "details": details, "path": str(probe_root)}
