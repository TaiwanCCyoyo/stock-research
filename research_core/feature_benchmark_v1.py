"""Fixed invented-input benchmark; no market execution or speed acceptance gate."""

from __future__ import annotations

import io
import logging
import sys
import tracemalloc
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research_core.artifact_store import file_digest, safe_path, write_json
from research_core.derived_features import compute_features
from research_core.derived_features_selective_v1 import compute_selected
from research_core.feature_block_store_v1 import FeatureBlockStore
from research_core.research_measurement_v1 import host_resources, phase_receipt, resource_sample
from research_core.stock_feature_pool_v1 import ROOT, SOURCE_FILES, ExecutionBudget, make_stock_request, run_stock_requests

LOGGER = logging.getLogger(__name__)
FEATURES = ("SMA20", "ATR14", "pivots_1p5")
STOCK_N, ROW_N = 16, 1849


def _measured(name: str, action: Callable[[], Any]) -> tuple[Any, dict[str, Any]]:
    before = resource_sample()
    owned_trace = not tracemalloc.is_tracing()
    if owned_trace:
        tracemalloc.start()
    try:
        result = action()
        measurement = phase_receipt(name, before, resource_sample())
        current, peak = tracemalloc.get_traced_memory()
        measurement["python_allocations"] = {
            "current_bytes": current,
            "peak_bytes": peak,
            "scope": "Parent Python allocations during this phase" if owned_trace else "Existing tracer lifetime; not isolated phase peak",
        }
        return result, measurement
    finally:
        if owned_trace:
            tracemalloc.stop()


def _prepared(output: Path) -> dict[str, Path]:
    directory = output / "prepared"
    directory.mkdir()
    dates = pd.bdate_range("2020-01-01", periods=ROW_N, name="Date")
    paths = {}
    for ordinal in range(STOCK_N):
        code = f"{ordinal + 1:04d}"
        close = 100 + ordinal + 20 * np.sin(np.arange(ROW_N) / 17)
        frame = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Quality": True}, index=dates)
        frame.iloc[283::283, frame.columns.get_loc("Quality")] = False
        path = directory / f"{code}.parquet"
        frame.to_parquet(path)
        paths[code] = path
    return paths


def _phase_sum(phases: list[dict[str, Any]]) -> dict[str, Any]:
    native = [row["native"] for row in phases if row["native"] is not None]
    return {
        "wall_seconds": sum(row["wall_seconds"] for row in phases),
        "cpu_seconds": sum(row["cpu_seconds"] for row in phases),
        "io_delta_sum": {key: sum(row["io_delta"].get(key, 0) for row in native) for key in sorted({key for row in native for key in row["io_delta"]})},
        "scope": "Sum of sequential direct stock phases; logical transfers including cached I/O, not physical disk throughput",
    }


def _direct(paths: dict[str, Path], output: Path, *, selected: bool) -> tuple[dict[tuple[str, str], Path], dict[str, Any]]:
    output.mkdir()
    payloads = {}
    phases: dict[str, list[dict[str, Any]]] = {"read": [], "calculate": [], "serialize": []}
    for code, path in paths.items():
        before = resource_sample()
        prepared = pd.read_parquet(path)
        phases["read"].append(phase_receipt("read", before, resource_sample()))
        before = resource_sample()
        daily, pivots = compute_selected(prepared, FEATURES) if selected else compute_features(prepared)
        phases["calculate"].append(phase_receipt("calculate", before, resource_sample()))
        before = resource_sample()
        for feature in FEATURES:
            frame = daily[[feature]] if feature in daily else pivots.loc[pivots.k.eq(1.5)].reset_index(drop=True)
            target = output / f"{code}-{feature}.parquet"
            frame.to_parquet(target, index=feature in daily)
            payloads[code, feature] = target
        phases["serialize"].append(phase_receipt("serialize", before, resource_sample()))
    return payloads, {name: _phase_sum(rows) for name, rows in phases.items()}


def _assert_payload(left: bytes, right: bytes) -> None:
    pd.testing.assert_frame_equal(pd.read_parquet(io.BytesIO(left)), pd.read_parquet(io.BytesIO(right)), check_exact=True)
    if left != right:
        raise ValueError("Invented-input numerical parity passed but parquet bytes differ")


def _barrier_summary(receipt: dict[str, Any]) -> dict[str, Any]:
    workers = receipt["worker_receipts"]
    native = [row["measurement"]["native"] for row in workers if row["measurement"]["native"] is not None]
    return {
        **{
            key: receipt[key]
            for key in (
                "stock_n",
                "feature_n",
                "computed_n",
                "reused_n",
                "effective_workers",
                "peak_inflight_processes",
                "stocks_per_process",
                "memory_budget_scope",
            )
        },
        "parent_measurement": receipt["measurement"],
        "child_phase_cpu_seconds_sum": sum(row["measurement"]["cpu_seconds"] for row in workers),
        "child_phase_wall_seconds_sum": sum(row["measurement"]["wall_seconds"] for row in workers),
        "child_phase_scope": (
            "Per-stock calculation and serialization; summed wall times overlap under parallel execution; "
            "parent wall includes startup, barriers, verification and publication"
        ),
        "worker_process_lifetime_peak_bytes_max": max((row["peak_working_set_process_lifetime_bytes"] for row in native), default=None),
        "child_io_delta_sum": {key: sum(row["io_delta"].get(key, 0) for row in native) for key in sorted({key for row in native for key in row["io_delta"]})},
        "io_scope": "Logical Windows process transfers including cached I/O; not physical disk throughput",
    }


def _timing_comparison(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    left, right = baseline["wall_seconds"], candidate["wall_seconds"]
    return {
        "baseline_wall_seconds": left,
        "candidate_wall_seconds": right,
        "wall_seconds_saved": left - right,
        "speedup_ratio": left / right if right > 0 else None,
        "scope": "Single fixed run; startup and serialization included; negative savings retained; no timing acceptance gate",
    }


def run_synthetic_benchmark(output: Path) -> dict[str, Any]:
    """Write one compact immutable receipt to an explicit fresh scratch directory."""
    if not output.is_absolute():
        raise ValueError("Absolute fresh scratch output required")
    output = safe_path(output)
    if output.exists():
        raise FileExistsError("Benchmark output must be a fresh scratch directory")
    if sys.platform != "win32":
        raise RuntimeError("Synthetic stock process benchmark requires Windows Job Objects")
    output.mkdir(parents=True, exist_ok=False)
    source_files = (*SOURCE_FILES, "research_core/derived_features.py", "research_core/feature_benchmark_v1.py", "scripts/feature_blocks.py")
    observed_sources = {name: file_digest(ROOT / name) for name in source_files}
    LOGGER.info("Starting fixed synthetic benchmark output=%s stocks=%d rows=%d", output, STOCK_N, ROW_N)
    paths, preparation = _measured("synthetic_prepare_and_serialize", lambda: _prepared(output))
    (full, full_details), full_measurement = _measured("direct_full_read_calculate_serialize", lambda: _direct(paths, output / "direct-full", selected=False))
    (selected, selected_details), selected_measurement = _measured(
        "direct_selected_read_calculate_serialize", lambda: _direct(paths, output / "direct-selected", selected=True)
    )
    for key in full:
        _assert_payload(full[key].read_bytes(), selected[key].read_bytes())
    requests = [make_stock_request(path, code, list(FEATURES), price_basis="synthetic") for code, path in paths.items()]
    stores, barriers, measurements = {}, {}, {}
    for workers in (1, 2):
        name = f"workers-{workers}"
        store = FeatureBlockStore(output / name / "cache")
        budget = ExecutionBudget(workers=workers, stocks_per_process=4, estimated_worker_bytes=512 * 1024**2, memory_bytes=1024**3)
        barrier, measurement = _measured(name, partial(run_stock_requests, requests, store, output / name / "staging", budget=budget))
        if (barrier["computed_n"], barrier["reused_n"]) != (48, 0):
            raise ValueError("Fresh synthetic barrier must compute all 48 blocks")
        stores[workers], barriers[name], measurements[name] = store, _barrier_summary(barrier), measurement
        for request in requests:
            for identity in request["identities"]:
                key = request["stock_code"], identity["feature_id"]
                _assert_payload(selected[key].read_bytes(), store.read(identity, "values.parquet"))
    increased = [
        make_stock_request(path, code, list(FEATURES) + (["EMA20"] if code == "0001" else []), price_basis="synthetic") for code, path in paths.items()
    ]
    budget = ExecutionBudget(workers=2, stocks_per_process=4, estimated_worker_bytes=512 * 1024**2, memory_bytes=1024**3)
    increment, increment_measurement = _measured("increment_one_EMA20", lambda: run_stock_requests(increased, stores[1], output / "increment", budget=budget))
    if (increment["computed_n"], increment["reused_n"]) != (1, 48):
        raise ValueError("Synthetic EMA20 addition must compute exactly one block")
    first = increased[0]
    ema_identity = next(row for row in first["identities"] if row["feature_id"] == "EMA20")
    ema_daily, _ = compute_selected(pd.read_parquet(first["prepared_path"]), ["EMA20"])
    stream = io.BytesIO()
    ema_daily.to_parquet(stream, index=True)
    _assert_payload(stream.getvalue(), stores[1].read(ema_identity, "values.parquet"))
    reuse, reuse_measurement = _measured("all_reuse", lambda: run_stock_requests(increased, stores[1], output / "all-reuse", budget=budget))
    if (reuse["computed_n"], reuse["reused_n"], reuse["peak_inflight_processes"]) != (0, 49, 0):
        raise ValueError("Entirely reusable synthetic barrier must launch zero processes")
    payloads = [
        {"stock_code": code, "feature": feature, "bytes": path.stat().st_size, "sha256": file_digest(path)} for (code, feature), path in selected.items()
    ]
    receipt = {
        "schema": "research-feature-synthetic-benchmark.v1",
        "complete": True,
        "contract": {
            "stocks": STOCK_N,
            "weekday_rows": ROW_N,
            "close": "100+ordinal+20*sin(index/17)",
            "OHLC": "Open=Close, High=Close+1, Low=Close-1",
            "invalid_quality": "283::283",
            "features": list(FEATURES),
            "price_basis": "synthetic",
            "market_data": False,
        },
        "host": host_resources(),
        "scratch_path": str(output),
        "implementation": requests[0]["implementation"],
        "runtime": requests[0]["runtime"],
        "benchmark_implementation": observed_sources,
        "prepared_sources": [
            {"stock_code": request["stock_code"], "path": request["prepared_path"], "sha256": request["prepared_sha256"]} for request in requests
        ],
        "measurement_scope": (
            "Tracemalloc is enabled around each measured parent phase and may affect timing; "
            "a single synthetic run does not estimate market workload throughput"
        ),
        "retention": (
            "Prepared inputs, direct parquet payloads and cache publications remain scratch; this receipt carries summaries and digests, no price frames"
        ),
        "prepared_bytes": sum(path.stat().st_size for path in paths.values()),
        "selected_payload_bytes": sum(row["bytes"] for row in payloads),
        "payloads": payloads,
        "phases": {
            "prepare": preparation,
            "direct_full": full_measurement,
            "direct_selected": selected_measurement,
            **measurements,
            "increment": increment_measurement,
            "all_reuse": reuse_measurement,
        },
        "direct_phase_details": {"full": full_details, "selected": selected_details},
        "startup_scope": (
            "Fresh process startup is included in parent barrier wall time; isolated startup and worker serialization "
            "durations are unavailable in worker v1 receipts and are not inferred from overlapping child times"
        ),
        "barriers": {**barriers, "increment": _barrier_summary(increment), "all_reuse": _barrier_summary(reuse)},
        "parity": {
            "full_selected_numerical_and_bytes": True,
            "serial_parallel_numerical_and_bytes": True,
            "EMA20_numerical_and_bytes": True,
            "original_leading_zero_codes": True,
        },
        "comparisons": {
            "full_to_selected": _timing_comparison(full_measurement, selected_measurement),
            "one_to_two_workers": _timing_comparison(measurements["workers-1"], measurements["workers-2"]),
        },
    }
    if observed_sources != {name: file_digest(ROOT / name) for name in source_files}:
        raise ValueError("Benchmark implementation changed during measurement")
    write_json(output / "receipt.json", receipt)
    LOGGER.info("Completed synthetic benchmark payload_bytes=%d receipt=%s", receipt["selected_payload_bytes"], output / "receipt.json")
    return receipt
