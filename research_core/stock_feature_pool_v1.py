"""Bounded Windows stock batches; complete barriers precede global calculations."""

from __future__ import annotations

import hashlib
import os
import platform
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow

from research_core.artifact_store import file_digest, object_digest, read_json, safe_path, verify_files, write_json
from research_core.derived_features_selective_v1 import ALL_FEATURES
from research_core.feature_block_store_v1 import FeatureBlockStore
from research_core.feature_identity_v1 import identity_digest, validate_identity
from research_core.prepared_stock_input_v1 import prepared_calendar, read_prepared
from research_core.research_measurement_v1 import host_resources, phase_receipt, resource_sample
from research_core.stock_feature_contract_v1 import make_feature_identity
from research_core.windows_process_job import WindowsProcessJob

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = tuple(
    f"research_core/{name}.py"
    for name in (
        "__init__",
        "artifact_store",
        "feature_identity_v1",
        "feature_block_store_v1",
        "research_measurement_v1",
        "derived_features_selective_v1",
        "stock_feature_contract_v1",
        "prepared_stock_input_v1",
        "bounded_parquet",
        "stock_feature_worker_v1",
        "stock_feature_pool_v1",
        "windows_process_job",
    )
)


@dataclass(frozen=True)
class ExecutionBudget:
    workers: int = 2
    memory_bytes: int = 1_073_741_824
    estimated_worker_bytes: int = 536_870_912
    stocks_per_process: int = 4
    timeout_seconds: float = 120.0

    def effective_workers(self) -> int:
        for value in (self.workers, self.memory_bytes, self.estimated_worker_bytes, self.stocks_per_process):
            if type(value) is not int or value < 1:
                raise ValueError("positive integer execution limits required")
        if self.stocks_per_process > 8 or type(self.timeout_seconds) not in (int, float) or not np.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("invalid batch size or timeout")
        available = host_resources()["physical_available_bytes"]
        bound = min(self.memory_bytes, available // 2) if available is not None else self.memory_bytes
        workers = min(self.workers, os.cpu_count() or 1, bound // self.estimated_worker_bytes)
        if workers < 1:
            raise ValueError("insufficient declared/available memory budget for one worker")
        return workers


def runtime_identity() -> dict[str, str]:
    return {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "pyarrow": pyarrow.__version__}


def implementation_identity() -> dict[str, str]:
    return {name: file_digest(ROOT / name) for name in SOURCE_FILES}


def make_stock_request(prepared_path: Path, code: str, features: list[str], *, price_basis: str) -> dict[str, Any]:
    """Bind an existing prepared snapshot; this function computes no feature."""
    source = safe_path(prepared_path)
    if not prepared_path.is_absolute() or not isinstance(code, str) or not code.strip() or not isinstance(price_basis, str) or not price_basis.strip():
        raise ValueError("explicit absolute input, original string code and price basis required")
    if not features or len(set(features)) != len(features) or set(features) - set(ALL_FEATURES):
        raise ValueError("unique known feature requests required")
    prepared, digest = read_prepared(source)
    calendar = prepared_calendar(prepared)
    if file_digest(source) != digest:
        raise ValueError("prepared snapshot changed during planning")
    implementation, runtime = implementation_identity(), runtime_identity()
    identities = [
        make_feature_identity(feature, code, digest, calendar, implementation, runtime, price_basis) for feature in ALL_FEATURES if feature in features
    ]
    return {
        "stock_code": code,
        "prepared_path": str(source),
        "prepared_sha256": digest,
        "price_basis": price_basis,
        "implementation": implementation,
        "runtime": runtime,
        "identities": identities,
    }


def _verify_request(request: dict[str, Any]) -> None:
    if request["implementation"] != implementation_identity() or request["runtime"] != runtime_identity():
        raise ValueError("planned implementation/runtime differs")
    if file_digest(Path(request["prepared_path"])) != request["prepared_sha256"]:
        raise ValueError("planned input differs")
    if not request["identities"]:
        raise ValueError("nonempty stock identities required")
    prepared, _ = read_prepared(Path(request["prepared_path"]), request["prepared_sha256"])
    calendar = prepared_calendar(prepared)
    for identity in request["identities"]:
        identity = validate_identity(identity)
        if identity["scope"] != "stock" or identity["stock_code"] != request["stock_code"]:
            raise ValueError("stock scheduler rejects cross-sectional or mixed-stock blocks")
        if identity["calendar"] != calendar:
            raise ValueError("planned calendar differs from the prepared snapshot")
        if identity != make_feature_identity(
            identity["feature_id"],
            request["stock_code"],
            request["prepared_sha256"],
            identity["calendar"],
            request["implementation"],
            request["runtime"],
            request["price_basis"],
        ):
            raise ValueError("planned stock feature contract differs")


def run_stock_requests(
    requests: list[dict[str, Any]], store: FeatureBlockStore, staging: Path, *, budget: ExecutionBudget = ExecutionBudget()
) -> dict[str, Any]:
    """Reuse matches; compute missing/invalid features behind a bounded barrier.

    This is a calculation API, not authorization. A future study supplies its
    approved mission and immutable prepared-input contract. No global selection,
    cross-sectional rank or publication of a complete study occurs here.
    """
    if sys.platform != "win32":
        raise RuntimeError("owned stock process execution v1 requires Windows Job Objects")
    if len({request["stock_code"] for request in requests}) != len(requests):
        raise ValueError("one request per original stock code required")
    requests = sorted(requests, key=lambda request: request["stock_code"])
    for request in requests:
        _verify_request(request)
    workers = budget.effective_workers()
    staging = safe_path(staging)
    staging.mkdir(parents=True, exist_ok=False)
    before = resource_sample()
    identities = [identity for request in requests for identity in request["identities"]]
    batch_id = object_digest(sorted(identity_digest(identity) for identity in identities))
    store.root.mkdir(parents=True, exist_ok=True)
    lock = safe_path(store.root / f".batch-{batch_id}.lock")
    token = {"pid": os.getpid(), "token": uuid.uuid4().hex, "batch_id": batch_id}
    write_json(lock, token)
    succeeded = False
    active: list[dict[str, Any]] = []
    try:
        jobs: list[tuple[Path, dict[str, Any]]] = []
        reused = 0
        for ordinal, request in enumerate(requests):
            plan = store.plan(request["identities"])
            if any(row["status"] == "conflict" for row in plan):
                raise ValueError("conflicting valid cache generations")
            missing = [identity for identity, row in zip(request["identities"], plan) if row["status"] != "reusable"]
            reused += len(plan) - len(missing)
            if missing:
                directory = staging / f"stock-{ordinal:06}"
                directory.mkdir()
                path = directory / "request.json"
                packet = {**request, "identities": missing}
                write_json(path, packet)
                jobs.append((path, packet))
        batches = [jobs[offset : offset + budget.stocks_per_process] for offset in range(0, len(jobs), budget.stocks_per_process)]
        next_batch, completed = 0, []
        peak_inflight = 0
        while next_batch < len(batches) or active:
            while next_batch < len(batches) and len(active) < workers:
                batch = batches[next_batch]
                owner = WindowsProcessJob()
                try:
                    prefix = staging / f"unused-pycache-{uuid.uuid4().hex}"
                    process = owner.start(
                        [
                            sys.executable,
                            "-B",
                            "-X",
                            f"pycache_prefix={prefix}",
                            "-m",
                            "research_core.stock_feature_worker_v1",
                            *[str(path) for path, _ in batch],
                        ],
                        ROOT,
                    )
                except BaseException:
                    owner.close()
                    raise
                active.append({"owner": owner, "process": process, "batch": batch, "started": time.monotonic()})
                next_batch += 1
                peak_inflight = max(peak_inflight, len(active))
            for item in list(active):
                process = item["process"]
                if time.monotonic() - item["started"] > budget.timeout_seconds:
                    raise TimeoutError("owned stock batch exceeded deadline")
                if process.poll() is None:
                    continue
                if process.returncode != 0:
                    raise RuntimeError(f"owned stock batch failed with exit {process.returncode}")
                # Also confirm descendants are gone before trusting a receipt.
                item["owner"].terminate_and_confirm()
                active.remove(item)
                item["owner"].close()
                completed.extend(item["batch"])
            if active:
                time.sleep(0.01)
        worker_receipts = []
        computed = 0
        # Complete all workers before cache publication/global consumers.
        for path, packet in sorted(completed, key=lambda pair: pair[1]["stock_code"]):
            receipt = read_json(path.parent / "complete.json")
            if (
                receipt.get("schema") != "stock-feature-worker.v1"
                or receipt["stock_code"] != packet["stock_code"]
                or receipt["request_sha256"] != file_digest(path)
            ):
                raise ValueError("worker receipt identity mismatch")
            verify_files(path.parent, receipt["artifacts"])
            expected = {identity_digest(identity): identity for identity in packet["identities"]}
            if len(receipt["artifacts"]) != len(expected) or {entry["identity_id"] for entry in receipt["artifacts"]} != set(expected):
                raise ValueError("worker output feature inventory differs")
            peak = receipt["measurement"]["native"]["peak_working_set_process_lifetime_bytes"]
            if peak > budget.estimated_worker_bytes:
                raise ValueError("observed worker peak exceeded its declared admission estimate")
            for entry in receipt["artifacts"]:
                data = safe_path(path.parent / entry["path"]).read_bytes()
                if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise ValueError("worker output bytes changed")
                store.publish(expected[entry["identity_id"]], {"values.parquet": data})
                computed += 1
            worker_receipts.append(receipt)
        for request in requests:
            _verify_request(request)
        results = [store.inspect(identity) for identity in identities]
        if any(result["status"] != "reusable" for result in results):
            raise ValueError("feature barrier incomplete")
        result = {
            "schema": "stock-feature-barrier.v1",
            "batch_id": batch_id,
            "stock_n": len(requests),
            "feature_n": len(identities),
            "reused_n": reused,
            "computed_n": computed,
            "effective_workers": workers,
            "peak_inflight_processes": peak_inflight,
            "stocks_per_process": budget.stocks_per_process,
            "memory_budget_scope": "Admission estimate plus post-run observed worker peaks, not an OS memory sandbox",
            "worker_receipts": worker_receipts,
            "references": [row["reference"] for row in results],
            "measurement": phase_receipt("bounded_stock_barrier", before, resource_sample()),
        }
        write_json(staging / "complete.json", result)
        succeeded = True
        return result
    finally:
        teardown_errors = []
        for item in active:
            try:
                item["owner"].terminate_and_confirm()
                item["process"].wait(timeout=5)
            except BaseException as error:
                teardown_errors.append(error)
            finally:
                try:
                    item["owner"].close()
                except BaseException as error:
                    teardown_errors.append(error)
        if succeeded and read_json(lock) == token:
            lock.unlink()
        if teardown_errors:
            raise RuntimeError("owned process teardown was not confirmed for every batch") from teardown_errors[0]
