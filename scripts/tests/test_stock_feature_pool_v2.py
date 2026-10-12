"""Invented stocks verify deferred admission without changing frozen v1 evidence."""

import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core import stock_feature_pool_v1 as v1
from research_core import stock_feature_pool_v2 as pool
from research_core.artifact_store import file_digest, read_json
from research_core.feature_block_store_v1 import FeatureBlockStore

WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="Owned workers require Windows Job Objects")


@pytest.fixture
def requests(tmp_path: Path) -> list[dict[str, Any]]:
    dates = pd.date_range("2020-01-01", periods=120, name="Date")
    result = []
    for ordinal, code in enumerate(("0001", "0020")):
        close = 50 + ordinal * 10 + np.sin(np.arange(120) / 4) * 8
        frame = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Quality": True}, index=dates)
        frame.loc[dates[50], "Quality"] = False
        path = tmp_path / f"prepared-{code}.parquet"
        frame.to_parquet(path)
        result.append(pool.make_stock_request(path, code, ["ATR14", "SMA20"], price_basis="synthetic"))
    return result


def no_process() -> None:
    pytest.fail("A request requiring no admitted worker must never start a process")


def low_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v1, "host_resources", lambda: {"physical_available_bytes": 64 * 1024**2})


def test_v2_identity_binds_v1_sources_plus_versioned_coordinator(requests: list[dict[str, Any]]) -> None:
    assert pool.ExecutionBudget is v1.ExecutionBudget
    assert pool.runtime_identity is v1.runtime_identity
    assert pool.SOURCE_FILES == (*v1.SOURCE_FILES, "research_core/stock_feature_pool_v2.py")
    request = requests[0]
    assert request["stock_code"] == "0001"
    assert request["implementation"] == {name: file_digest(pool.ROOT / name) for name in pool.SOURCE_FILES}
    assert all(identity["implementation"] == request["implementation"] for identity in request["identities"])
    old = v1.make_stock_request(Path(request["prepared_path"]), "0001", ["ATR14", "SMA20"], price_basis="synthetic")
    assert old["implementation"] != request["implementation"]


@WINDOWS
def test_actual_compute_then_low_memory_all_reuse_skips_admission(requests: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FeatureBlockStore(tmp_path / "store")
    first = pool.run_stock_requests(requests, store, tmp_path / "first", budget=pool.ExecutionBudget(workers=1, stocks_per_process=2))
    assert first["schema"] == "stock-feature-barrier.v2"
    assert (first["computed_n"], first["reused_n"], first["effective_workers"]) == (4, 0, 1)
    before = {
        identity["stock_code"] + identity["feature_id"]: store.read(identity, "values.parquet") for request in requests for identity in request["identities"]
    }
    low_memory(monkeypatch)
    with pytest.raises(ValueError, match="insufficient"):
        pool.ExecutionBudget().effective_workers()
    monkeypatch.setattr(pool, "WindowsProcessJob", no_process)
    reused = pool.run_stock_requests(requests, store, tmp_path / "reused")
    assert (reused["computed_n"], reused["reused_n"], reused["effective_workers"], reused["peak_inflight_processes"]) == (0, 4, 0, 0)
    assert reused["worker_receipts"] == []
    assert (tmp_path / "reused" / "complete.json").is_file()
    assert before == {
        identity["stock_code"] + identity["feature_id"]: store.read(identity, "values.parquet") for request in requests for identity in request["identities"]
    }
    assert not list(store.root.glob(".batch-*.lock"))


@WINDOWS
def test_low_memory_missing_blocks_rejected_before_any_launch(requests: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    low_memory(monkeypatch)
    monkeypatch.setattr(pool, "WindowsProcessJob", no_process)
    store, staging = FeatureBlockStore(tmp_path / "store"), tmp_path / "missing"
    with pytest.raises(ValueError, match="insufficient"):
        pool.run_stock_requests(requests, store, staging)
    assert not (staging / "complete.json").exists()
    assert list(staging.glob("stock-*/request.json"))
    assert not list(store.root.rglob("manifest.json"))
    assert list(store.root.glob(".batch-*.lock"))


@WINDOWS
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
def test_malformed_budget_rejected_even_when_every_block_is_reusable(
    requests: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    store = FeatureBlockStore(tmp_path / "store")
    for request in requests:
        for identity in request["identities"]:
            store.publish(identity, {"values.parquet": b"invented cache bytes"})
    low_memory(monkeypatch)
    monkeypatch.setattr(pool, "WindowsProcessJob", no_process)
    staging = tmp_path / "invalid-budget"
    with pytest.raises(ValueError, match="positive integer|invalid batch size or timeout"):
        pool.run_stock_requests(requests, store, staging, budget=pool.ExecutionBudget(**{field: value}))
    assert not staging.exists()
    assert all(store.inspect(identity)["status"] == "reusable" for request in requests for identity in request["identities"])


@WINDOWS
def test_invalid_cache_is_missing_for_admission_then_recovers_additively(
    requests: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FeatureBlockStore(tmp_path / "store")
    pool.run_stock_requests(requests, store, tmp_path / "first", budget=pool.ExecutionBudget(workers=1, stocks_per_process=2))
    identity = requests[0]["identities"][0]
    reference = store.inspect(identity)["reference"]
    artifact = Path(reference["path"]) / "values.parquet"
    artifact.write_bytes(b"corrupt retained bytes")
    assert store.inspect(identity)["status"] == "invalid"
    with monkeypatch.context() as bounded:
        low_memory(bounded)
        bounded.setattr(pool, "WindowsProcessJob", no_process)
        with pytest.raises(ValueError, match="insufficient"):
            pool.run_stock_requests(requests, store, tmp_path / "low-ram-invalid")
    # Audit and release only this fixture's diagnosed, completed no-worker lock.
    # Production failures deliberately retain their locks for an ownership audit.
    locks = list(store.root.glob(".batch-*.lock"))
    assert len(locks) == 1
    assert read_json(locks[0])["pid"] == os.getpid()
    assert not (tmp_path / "low-ram-invalid" / "complete.json").exists()
    locks[0].unlink()
    recovered = pool.run_stock_requests(requests, store, tmp_path / "recovery", budget=pool.ExecutionBudget(workers=1, stocks_per_process=2))
    assert (recovered["computed_n"], recovered["reused_n"]) == (1, 3)
    assert store.inspect(identity)["status"] == "reusable"
    assert store.inspect(identity)["reference"]["path"] != reference["path"]
    assert artifact.read_bytes() == b"corrupt retained bytes"


@WINDOWS
def test_conflicting_cache_generations_rejected_before_admission(requests: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, other = FeatureBlockStore(tmp_path / "store"), FeatureBlockStore(tmp_path / "other")
    identity = requests[0]["identities"][0]
    first = store.publish(identity, {"values.parquet": b"first invented generation"})
    second = other.publish(deepcopy(identity), {"values.parquet": b"different invented generation"})
    source = Path(second["path"])
    source.rename(Path(first["path"]).parent / source.name)
    low_memory(monkeypatch)
    monkeypatch.setattr(pool, "WindowsProcessJob", no_process)
    with pytest.raises(ValueError, match="conflicting valid"):
        pool.run_stock_requests(requests, store, tmp_path / "conflict")
    assert store.inspect(identity)["status"] == "conflict"
    assert not (tmp_path / "conflict" / "complete.json").exists()
