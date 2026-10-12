"""Invented prepared stocks exercise bounded execution and exact block reuse."""

import io
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core import stock_feature_pool_v1 as pool
from research_core.derived_features_selective_v1 import compute_selected
from research_core.feature_block_store_v1 import FeatureBlockStore

WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="Owned workers require Windows Job Objects")
FEATURES = ["ATR14", "SMA20", "pivots_1p5"]


@pytest.fixture
def prepared(tmp_path: Path) -> dict[str, Path]:
    paths = {}
    dates = pd.date_range("2020-01-01", periods=120, name="Date")
    for ordinal, code in enumerate(("0001", "0020", "3010")):
        close = 50 + ordinal * 10 + np.sin(np.arange(120) / 4) * 8
        frame = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Quality": True}, index=dates)
        frame.loc[dates[50], "Quality"] = False
        path = tmp_path / f"prepared-{code}.parquet"
        frame.to_parquet(path)
        paths[code] = path
    return paths


def requests_for(paths: dict[str, Path], extra: bool = False) -> list[dict[str, Any]]:
    return [
        pool.make_stock_request(path, code, FEATURES + (["EMA20"] if extra and code == "0001" else []), price_basis="synthetic") for code, path in paths.items()
    ]


def expected_bytes(request: dict[str, Any], feature: str) -> bytes:
    daily, pivots = compute_selected(pd.read_parquet(request["prepared_path"]), [identity["feature_id"] for identity in request["identities"]])
    result = daily[[feature]] if feature in daily else pivots.loc[pivots.k.eq(1.5)].reset_index(drop=True)
    stream = io.BytesIO()
    result.to_parquet(stream, index=feature in daily)
    return stream.getvalue()


@WINDOWS
def test_actual_serial_parallel_values_bytes_and_incremental_reuse(prepared: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    requests = requests_for(prepared)
    serial, parallel = FeatureBlockStore(tmp_path / "serial"), FeatureBlockStore(tmp_path / "parallel")
    receipts = []
    for workers, store in ((1, serial), (2, parallel)):
        receipt = pool.run_stock_requests(requests, store, tmp_path / f"run-{workers}", budget=pool.ExecutionBudget(workers=workers, stocks_per_process=2))
        receipts.append(receipt)
        assert (receipt["computed_n"], receipt["reused_n"], receipt["feature_n"], receipt["stock_n"]) == (9, 0, 9, 3)
        assert receipt["peak_inflight_processes"] <= workers
        assert {row["stock_code"] for row in receipt["worker_receipts"]} == set(prepared)
    for request in requests:
        assert request["stock_code"] in prepared
        for identity in request["identities"]:
            feature = identity["feature_id"]
            left, right = serial.read(identity, "values.parquet"), parallel.read(identity, "values.parquet")
            assert left == right == expected_bytes(request, feature)
            pd.testing.assert_frame_equal(pd.read_parquet(io.BytesIO(left)), pd.read_parquet(io.BytesIO(right)))
    assert requests[0]["stock_code"] == requests[0]["identities"][0]["stock_code"] == "0001"
    increased = requests_for(prepared, extra=True)
    receipt = pool.run_stock_requests(increased, serial, tmp_path / "increment", budget=pool.ExecutionBudget(workers=2, stocks_per_process=2))
    assert (receipt["computed_n"], receipt["reused_n"]) == (1, 9)
    assert [row["stock_code"] for row in receipt["worker_receipts"]] == ["0001"]
    assert len(receipt["worker_receipts"][0]["artifacts"]) == 1
    ema = next(identity for identity in increased[0]["identities"] if identity["feature_id"] == "EMA20")
    assert serial.read(ema, "values.parquet") == expected_bytes(increased[0], "EMA20")

    def unexpected_process() -> None:
        pytest.fail("An entirely reusable request must start zero processes")

    monkeypatch.setattr(pool, "WindowsProcessJob", unexpected_process)
    receipt = pool.run_stock_requests(increased, serial, tmp_path / "all-reuse")
    assert (receipt["computed_n"], receipt["reused_n"], receipt["peak_inflight_processes"]) == (0, 10, 0)
    assert receipt["worker_receipts"] == []


@WINDOWS
@pytest.mark.parametrize(
    "mutation,match",
    [
        ("duplicate", "one request"),
        ("cross_section", "cross-sectional"),
        ("input", "input differs"),
        ("calendar", "calendar differs"),
        ("semantics", "contract differs"),
        ("runtime", "implementation/runtime differs"),
        ("implementation", "implementation/runtime differs"),
    ],
)
def test_invalid_requests_rejected_before_receipt(
    prepared: dict[str, Path], tmp_path: Path, mutation: str, match: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = deepcopy(requests_for(prepared))
    if mutation == "duplicate":
        requests.append(deepcopy(requests[0]))
    elif mutation == "cross_section":
        requests[0]["identities"][0].update(scope="cross_section", context={"universe": "invented"})
    elif mutation == "input":
        path = prepared["0001"]
        frame = pd.read_parquet(path)
        frame.iloc[0, 0] += 0.25
        frame.to_parquet(path)
    elif mutation == "semantics":
        requests[0]["identities"][0]["semantics"]["gap"] = "forged fill policy"
    elif mutation == "calendar":
        requests[0]["identities"][0]["calendar"]["rows"] += 1
    else:
        key = next(iter(requests[0][mutation]))
        requests[0][mutation][key] = "forged" if mutation == "runtime" else "0" * 64
    monkeypatch.setattr(pool, "WindowsProcessJob", lambda: pytest.fail("Rejected request started a process"))
    staging, store = tmp_path / "rejected", FeatureBlockStore(tmp_path / "store")
    with pytest.raises(ValueError, match=match):
        pool.run_stock_requests(requests, store, staging)
    assert not staging.exists()
    assert not store.root.exists()


@WINDOWS
@pytest.mark.parametrize("failure", ["timeout", "missing-quality"])
def test_actual_worker_failure_retains_diagnosis_without_publications(
    prepared: dict[str, Path], tmp_path: Path, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if failure == "missing-quality":
        path = prepared["0001"]
        pd.read_parquet(path).drop(columns="Quality").to_parquet(path)
    requests = requests_for(prepared)
    processes = []
    start = pool.WindowsProcessJob.start

    def record_start(self: Any, command: list[str], cwd: Path) -> Any:
        process = start(self, command, cwd)
        processes.append(process)
        return process

    monkeypatch.setattr(pool.WindowsProcessJob, "start", record_start)
    store, staging = FeatureBlockStore(tmp_path / "store"), tmp_path / "failed"
    budget = pool.ExecutionBudget(workers=2, stocks_per_process=2, timeout_seconds=0.000001 if failure == "timeout" else 120)
    with pytest.raises(TimeoutError if failure == "timeout" else RuntimeError, match="deadline" if failure == "timeout" else "failed with exit"):
        pool.run_stock_requests(requests, store, staging, budget=budget)
    assert processes and all(process.poll() is not None for process in processes)
    assert not (staging / "complete.json").exists()
    assert list(staging.glob("stock-*/request.json"))
    assert list(store.root.glob(".batch-*.lock"))
    assert not list(store.root.rglob("manifest.json"))
    assert all(store.inspect(identity)["status"] == "missing" for request in requests for identity in request["identities"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("workers", True),
        ("workers", 0),
        ("memory_bytes", True),
        ("memory_bytes", 0),
        ("estimated_worker_bytes", True),
        ("estimated_worker_bytes", 0),
        ("stocks_per_process", True),
        ("stocks_per_process", 0),
        ("stocks_per_process", 9),
        ("timeout_seconds", True),
        ("timeout_seconds", 0),
        ("timeout_seconds", float("nan")),
        ("timeout_seconds", float("inf")),
    ],
)
def test_invalid_budget(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        pool.ExecutionBudget(**{field: value}).effective_workers()


@pytest.mark.parametrize("available,declared,expected", [(1200, 1000, 3), (None, 1000, 5), (10000, 400, 2)])
def test_budget_is_bounded_by_declared_available_memory_and_cpu(monkeypatch: pytest.MonkeyPatch, available: int | None, declared: int, expected: int) -> None:
    monkeypatch.setattr(pool, "host_resources", lambda: {"physical_available_bytes": available})
    monkeypatch.setattr(pool.os, "cpu_count", lambda: 8)
    assert pool.ExecutionBudget(workers=7, memory_bytes=declared, estimated_worker_bytes=200).effective_workers() == expected
    monkeypatch.setattr(pool.os, "cpu_count", lambda: 1)
    assert pool.ExecutionBudget(workers=7, memory_bytes=declared, estimated_worker_bytes=200).effective_workers() == 1


def test_budget_rejects_insufficient_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pool, "host_resources", lambda: {"physical_available_bytes": 100})
    with pytest.raises(ValueError, match="insufficient"):
        pool.ExecutionBudget(memory_bytes=1000, estimated_worker_bytes=51).effective_workers()
