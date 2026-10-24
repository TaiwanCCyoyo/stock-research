"""Bounded stock projections and independent group reductions for PR17 v5.

Only the coordinator publishes completed directories and writes progress. Workers
read the fixed original inputs and the run's completed projections in place.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import pickle
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Executor, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import pyarrow as pa

from research_core.artifact_store import publish_noreplace
from research_core.hhhl_variants_selection import Atom
from research_core.research_data_paths import checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample

if TYPE_CHECKING:
    from research_core.pattern_scan_local_inputs_v5 import LocalInputs

LOGGER = logging.getLogger(__name__)
MAX_WORKERS = 10
_INPUTS: LocalInputs | None = None
_TARGET = ""
_INITIALIZATION: dict[str, Any] = {}
_FIRST_TASK = True
T = TypeVar("T")
R = TypeVar("R")


def validate_workers(workers: int) -> int:
    if type(workers) is not int or not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be an integer from 1 to {MAX_WORKERS}")
    return workers


@dataclass(frozen=True)
class InputSpec:
    stock_result: Path
    temporary: Path
    target: str
    cache: Path
    codes: tuple[str, ...]
    require_complete: bool
    read_only: bool = False


@dataclass(frozen=True)
class GroupJob:
    group: str
    horizon: int
    candidates: dict[str, tuple[Atom, ...]]
    staging: Path
    codes: tuple[str, ...] | None = None


def initialize_worker(spec: InputSpec) -> None:
    global _INPUTS, _TARGET, _INITIALIZATION, _FIRST_TASK
    from research_core.pattern_scan_local_inputs_v5 import LocalInputs

    before = resource_sample()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    inputs = LocalInputs(spec.stock_result, spec.temporary)
    if not spec.codes or not set(spec.codes).issubset(inputs.codes) or len(set(spec.codes)) != len(spec.codes):
        raise ValueError("parallel input specification needs unique original stocks")
    inputs.attach_target(spec.target, spec.cache, require_complete=spec.require_complete)
    inputs.projection_build_allowed = not spec.read_only
    _INPUTS = inputs
    _TARGET = spec.target
    _INITIALIZATION = phase_receipt("worker-initialization", before, resource_sample())
    _FIRST_TASK = True


def _measurement(before: dict[str, Any]) -> dict[str, Any]:
    global _FIRST_TASK
    result = phase_receipt("parallel-task", before, resource_sample())
    result["worker_pid"] = os.getpid()
    if _FIRST_TASK:
        result["initialization"] = _INITIALIZATION
        _FIRST_TASK = False
    return result


def project_stock(job: tuple[str, str, Path]) -> dict[str, Any]:
    if _INPUTS is None:
        raise RuntimeError("projection worker was not initialized")
    target, code, staging = job
    before = resource_sample()
    _INPUTS.write_projection(target, code, staging)
    return {"code": code, "staging": str(staging), "measurement": _measurement(before)}


def summarize_group(job: GroupJob) -> dict[str, Any]:
    from research_core.pattern_scan_local_conditions_v5 import _summarize_group

    if _INPUTS is None:
        raise RuntimeError("group worker was not initialized")
    inputs = _INPUTS
    target = _TARGET
    before = resource_sample()
    phases: dict[str, float] = {}

    def frames() -> Iterator[tuple[str, Any]]:
        for code in job.codes or inputs.codes:
            started = time.perf_counter()
            frame = inputs.group_frame(inputs.bound(target, code), job.group, job.horizon)
            phases["frame_read_seconds"] = phases.get("frame_read_seconds", 0.0) + time.perf_counter() - started
            yield code, frame

    job.staging.mkdir()
    paths, top_rows = _summarize_group(frames, target, job.group, job.horizon, job.candidates, job.staging, timings=phases)
    return {"paths": [str(path) for path in paths], "top_rows": top_rows, "measurement": {**_measurement(before), "phases": phases}}


def bounded_results(pool: Executor, function: Callable[[T], R], jobs: Iterable[T], *, workers: int, metrics: dict[str, Any]) -> Iterator[tuple[T, R]]:
    """Admit at most `workers` jobs; never pickle a whole market DataFrame."""
    validate_workers(workers)
    pending: dict[Future[R], T] = {}
    iterator = iter(jobs)
    started = time.perf_counter()
    metrics.update(workers=workers, max_in_flight=0, job_pickle_bytes=0, job_pickle_seconds=0.0, first_result_seconds=None)

    def refill() -> None:
        while len(pending) < workers:
            try:
                job = next(iterator)
            except StopIteration:
                return
            pickle_started = time.perf_counter()
            metrics["job_pickle_bytes"] += len(pickle.dumps(job))
            metrics["job_pickle_seconds"] += time.perf_counter() - pickle_started
            pending[pool.submit(function, job)] = job
            metrics["max_in_flight"] = max(metrics["max_in_flight"], len(pending))

    refill()
    failure: Exception | None = None
    try:
        while pending:
            ready, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in ready:
                job = pending.pop(future)
                if future.cancelled():
                    continue
                try:
                    result = future.result()
                except Exception as error:
                    if failure is None:
                        failure = error
                    for remaining in pending:
                        remaining.cancel()
                    continue
                if metrics["first_result_seconds"] is None:
                    metrics["first_result_seconds"] = time.perf_counter() - started
                yield job, result
            if failure is None:
                refill()
        if failure is not None:
            raise failure
    finally:
        for future in pending:
            future.cancel()


def process_pool(spec: InputSpec, workers: int) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(
        max_workers=validate_workers(workers), mp_context=multiprocessing.get_context("spawn"), initializer=initialize_worker, initargs=(spec,)
    )


def project_in_parallel(inputs: LocalInputs, target: str, output: Path, codes: list[str], *, workers: int, on_completed: Callable[[str], None]) -> None:
    from research_core.artifact_store import relocate_noreplace
    from research_core.pattern_scan_local_inputs_v5 import write_progress

    if not codes:
        return
    spec = InputSpec(inputs.stock_result, inputs.temporary, target, output, inputs.codes, False)
    jobs = [(target, code, output / f".staging-{code}-{uuid.uuid4().hex}") for code in codes]
    metrics: dict[str, Any] = {}
    measurements = []
    before = resource_sample()
    with process_pool(spec, workers) as pool:
        for job, result in bounded_results(pool, project_stock, jobs, workers=workers, metrics=metrics):
            code, staging = result["code"], checked_path(Path(result["staging"]))
            if code != job[1] or staging != checked_path(job[2]):
                raise ValueError("parallel projection result differs from its admitted stock")
            destination = checked_path(output / code)
            if destination.exists():
                relocate_noreplace(destination, output / f".interrupted-{code}-{uuid.uuid4().hex}")
            publish_noreplace(staging, destination)
            on_completed(code)
            measurements.append(result["measurement"])
            LOGGER.info("Parallel target projection target=%s stock=%s workers=%d done=%d/%d", target, code, workers, len(measurements), len(codes))
    write_progress(
        output / "parallel-execution.json", {**metrics, "measurement": phase_receipt("parallel-projections", before, resource_sample()), "tasks": measurements}
    )
