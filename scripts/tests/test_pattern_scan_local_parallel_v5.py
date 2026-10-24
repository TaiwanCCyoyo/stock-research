"""Synthetic coverage for bounded PR17 condition-group workers."""

from __future__ import annotations

import multiprocessing
import os
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pandas as pd
import pyarrow as pa
import pytest

from research_core import pattern_scan_local_conditions_v5 as conditions
from research_core import pattern_scan_local_parallel_probe_v5 as probe
from research_core import pattern_scan_local_parallel_v5 as parallel
from research_core.hhhl_variants_selection import Atom, split_for_code
from research_core.pattern_scan_conditions_v1 import FEATURES
from research_core.pattern_scan_local_inputs_v5 import LocalInputs
from research_core.pattern_scan_local_parallel_v5 import GroupJob


def _membership_subset(base_metadata: Mapping[str, Any], candidates: Mapping[str, Sequence[Atom]] | None = None) -> tuple[dict[str, Any], ...]:
    rows = _ORIGINAL_MEMBERSHIP_INVENTORY(base_metadata, candidates)
    return tuple(row for row in rows if row["feature_id"] in {"MA_b", "candidate"})


_ORIGINAL_MEMBERSHIP_INVENTORY = conditions.membership_inventory


def test_probe_repetitions_compare_each_case_against_its_reference(tmp_path: Path) -> None:
    def result(name: str, value: int = 1) -> dict[str, Any]:
        directory = tmp_path / name
        directory.mkdir()
        paths = []
        for number in range(3):
            path = directory / f"table-{number}.parquet"
            pd.DataFrame({"known_n": [value], "unknown_n": [0]}).to_parquet(path, index=False)
            paths.append(str(path))
        return {"paths": paths, "top_rows": [{"known_n": value}]}

    baseline = {"union|h252|r0": result("baseline-union"), "all|h126|r0": result("baseline-all")}
    current = {f"{case}|r{repeat}": result(f"{case.split('|')[0]}-{repeat}") for repeat in range(2) for case in ("union|h252", "all|h126")}
    assert probe._compare_group_outputs(baseline, current) == 12
    assert probe._compare_group_outputs(baseline, baseline) == 0
    current["union|h252|r1"]["top_rows"] = [{"known_n": 2}]
    with pytest.raises(AssertionError):
        probe._compare_group_outputs(baseline, current)


class _SyntheticInputs:
    def __init__(self, cache: Path, codes: tuple[str, ...]) -> None:
        self.cache = cache
        self.codes = codes

    def bound(self, target: str, code: str) -> str:
        assert target == "R1"
        return code

    def group_frame(self, bound: str, group: str, horizon: int) -> pd.DataFrame:
        assert group in {"pattern:union", "C-secondary"}
        return pd.read_parquet(self.cache / f"{bound}-h{horizon}.parquet")


def _initialize_synthetic_group_worker(cache: str, codes: tuple[str, ...]) -> None:
    conditions.membership_inventory = _membership_subset
    parallel._INPUTS = cast(LocalInputs, _SyntheticInputs(Path(cache), codes))
    parallel._TARGET = "R1"
    parallel._INITIALIZATION = {"synthetic": True}
    parallel._FIRST_TASK = True


def _synthetic_stock(code: str, horizon: int) -> pd.DataFrame:
    return pd.DataFrame({
        "security_id": [f"TW:{code}"] * 5,
        "event_id": [f"{code}-{index}" for index in range(5)],
        "t0": ["2010-01-04", "2011-01-04", "2012-01-04", "2026-01-04", "2026-02-04"],
        "horizon": [horizon] * 5,
        "effective_label": ["hit", "loss", "unknown", "hit", "unknown"],
        "calendar_full": [True, True, True, False, False],
        "event_main_eligible": [True, True, False, False, False],
        "event_eligibility_excluded": [False, False, False, True, False],
        "mkt": ["up", "down", "unknown", "mixed", "consolidation"],
        "MA_b_bin": ["true", "false", None, None, "true"],
        "MA_b_status": ["known", "known", "feature_unknown", "not_applicable", "known"],
    })


def _delay_result(job: tuple[str, float]) -> str:
    value, delay = job
    time.sleep(delay)
    return value


@pytest.mark.parametrize("workers", (True, 0, 11))
def test_validate_workers_rejects_bool_zero_and_above_limit(workers: int) -> None:
    with pytest.raises(ValueError, match="workers"):
        parallel.validate_workers(workers)


def test_bounded_results_limits_admission_and_yields_out_of_order_jobs() -> None:
    jobs = [("slow", 0.12), ("fast", 0.01), ("later", 0.01)]
    metrics: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        yielded = list(parallel.bounded_results(pool, _delay_result, jobs, workers=2, metrics=metrics))
    assert yielded[0] == (jobs[1], "fast")
    assert {job for job, _ in yielded} == set(jobs)
    assert all(result == job[0] for job, result in yielded)
    assert metrics["max_in_flight"] == 2
    assert metrics["max_in_flight"] <= metrics["workers"]


def test_bounded_results_drains_running_success_then_raises_first_error_without_refill() -> None:
    started = threading.Event()
    admitted: list[str] = []
    yielded: list[tuple[str, str]] = []

    def jobs():
        for name in ("fail", "success", "must-not-start"):
            admitted.append(name)
            yield name

    def execute(name: str) -> str:
        if name == "fail":
            assert started.wait(timeout=2)
            raise RuntimeError("first submitted job failed")
        if name == "success":
            started.set()
            time.sleep(0.1)
        return name

    metrics: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        with pytest.raises(RuntimeError, match="first submitted job failed"):
            for item in parallel.bounded_results(pool, execute, jobs(), workers=2, metrics=metrics):
                yielded.append(item)

    assert admitted == ["fail", "success"]
    assert yielded == [("success", "success")]
    assert metrics["max_in_flight"] == 2


def test_initialize_worker_attaches_read_only_complete_inputs_and_caps_threads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from research_core import pattern_scan_local_inputs_v5 as inputs_module

    attached: list[tuple[str, Path, bool]] = []

    class FakeInputs:
        codes = ("1101", "1102")
        projection_build_allowed = True

        def __init__(self, stock_result: Path, temporary: Path) -> None:
            self.stock_result, self.temporary = stock_result, temporary

        def attach_target(self, target: str, cache: Path, *, require_complete: bool) -> None:
            attached.append((target, cache, require_complete))

    thread_caps: list[tuple[str, int]] = []
    monkeypatch.setattr(parallel, "_INPUTS", None)
    monkeypatch.setattr(parallel, "_TARGET", "")
    monkeypatch.setattr(parallel, "_INITIALIZATION", {})
    monkeypatch.setattr(parallel, "_FIRST_TASK", True)
    monkeypatch.setattr(inputs_module, "LocalInputs", FakeInputs)
    monkeypatch.setattr(pa, "set_cpu_count", lambda value: thread_caps.append(("cpu", value)))
    monkeypatch.setattr(pa, "set_io_thread_count", lambda value: thread_caps.append(("io", value)))
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        monkeypatch.setenv(name, "test")
    spec = parallel.InputSpec(tmp_path / "stock.json", tmp_path / ".tmp", "R1", tmp_path / "cache", ("1101",), True, True)

    parallel.initialize_worker(spec)

    assert attached == [("R1", spec.cache, True)]
    assert parallel._INPUTS is not None
    assert parallel._INPUTS.projection_build_allowed is False
    assert parallel._TARGET == "R1"
    assert thread_caps == [("cpu", 1), ("io", 1)]
    assert all(os.environ[name] == "1" for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS"))


def test_spawned_group_summaries_match_serial_tables_and_top_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conditions, "membership_inventory", _membership_subset)
    cache = tmp_path / "cache"
    cache.mkdir()
    split_codes = {split: next(f"{number:05}" for number in range(1000) if split_for_code(f"{number:05}") == split) for split in ("development", "cross-check")}
    codes = tuple(split_codes.values())
    for code in codes:
        for horizon in (126, 252):
            _synthetic_stock(code, horizon).to_parquet(cache / f"{code}-h{horizon}.parquet", index=False)

    atom = Atom(FEATURES["MA_b"].family, "MA_b", "true")
    candidate_id = "pattern-scan.v1:R1:MA_b=true"
    candidates: dict[str, tuple[Atom, ...]] = {candidate_id: (atom,)}
    jobs = [
        GroupJob(group, horizon, candidates if group == "pattern:union" else {}, tmp_path / f"unused-{index}", codes)
        for index, (group, horizon) in enumerate((("pattern:union", 126), ("pattern:union", 252), ("C-secondary", 126), ("C-secondary", 252)))
    ]

    def frames(job: GroupJob):
        return lambda: ((code, _synthetic_stock(code, job.horizon)) for code in codes)

    serial: dict[tuple[str, int], tuple[list[pd.DataFrame], list[dict[str, Any]]]] = {}
    for index, job in enumerate(jobs):
        staging = tmp_path / f"serial-{index}"
        staging.mkdir()
        timings: dict[str, float] = {}
        paths, top_rows = conditions._summarize_group(frames(job), "R1", job.group, job.horizon, job.candidates, staging, timings=timings)
        assert {"matrix_seconds", "add_stock_seconds", "coverage_seconds", "summary_write_seconds"} <= set(timings)
        serial[(job.group, job.horizon)] = ([pd.read_parquet(path) for path in paths], top_rows)

    for workers in (1, 2, 4):
        submitted = [GroupJob(job.group, job.horizon, job.candidates, tmp_path / f"spawn-{workers}-{index}", codes) for index, job in enumerate(jobs)]
        metrics: dict[str, Any] = {}
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_initialize_synthetic_group_worker,
            initargs=(str(cache), codes),
        ) as pool:
            results = list(parallel.bounded_results(pool, parallel.summarize_group, submitted, workers=workers, metrics=metrics))
        assert metrics["max_in_flight"] <= workers
        assert len(results) == len(submitted)
        for job, result in results:
            produced = [pd.read_parquet(path) for path in result["paths"]]
            expected_tables, expected_top = serial[(job.group, job.horizon)]
            for actual, expected in zip(produced, expected_tables, strict=True):
                pd.testing.assert_frame_equal(actual, expected, check_dtype=True, check_exact=True)
            pd.testing.assert_frame_equal(pd.DataFrame(result["top_rows"]), pd.DataFrame(expected_top), check_dtype=True, check_exact=True)
            assert {"frame_read_seconds", "matrix_seconds", "add_stock_seconds", "coverage_seconds", "summary_write_seconds"} <= set(
                result["measurement"]["phases"]
            )


def test_parallel_groups_adopts_existing_publishes_missing_and_reports_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core.artifact_store import read_json

    cache = tmp_path / "cache"
    cache.mkdir()
    output = tmp_path / "final"
    output.mkdir()
    temporary = tmp_path / ".tmp"
    temporary.mkdir()
    existing_name = "pattern%3Aunion-h126"
    existing = output / existing_name
    existing.mkdir()
    for table in ("summary", "annual", "candidate-coverage"):
        (existing / f"existing-{table}.parquet").write_bytes(table.encode())

    inputs = SimpleNamespace(stock_result=tmp_path / "stock.json", temporary=temporary, codes=("1101", "1102"), workers=4)
    groups = ("pattern:union", "C-secondary")
    atom = Atom(FEATURES["MA_b"].family, "MA_b", "true")
    candidates: dict[str, tuple[Atom, ...]] = {"pattern-scan.v1:R1:MA_b=true": (atom,)}
    progress: dict[str, Any] = {"completed": {}}
    progress_path = output / "progress.json"
    progress_events: list[tuple[int, int]] = []
    captured_specs: list[parallel.InputSpec] = []
    submitted: list[GroupJob] = []

    class Pool:
        def __enter__(self) -> Pool:
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            return None

    def make_pool(spec: parallel.InputSpec, workers: int) -> Pool:
        captured_specs.append(spec)
        assert workers == 3
        return Pool()

    def run_jobs(pool: Pool, function: Any, jobs: Any, *, workers: int, metrics: dict[str, Any]):
        assert function is parallel.summarize_group and workers == 3
        metrics.update(workers=workers, max_in_flight=workers, job_pickle_bytes=0, job_pickle_seconds=0.0, first_result_seconds=0.0)
        for job in jobs:
            submitted.append(job)
            job.staging.mkdir()
            (job.staging / "published-marker").write_text(job.group, encoding="utf-8")
            yield job, {"measurement": {"worker_pid": 1, "phases": {"frame_read_seconds": 0.0}}}

    monkeypatch.setattr(conditions, "_group_paths", lambda directory, *args: list(directory.iterdir()))
    monkeypatch.setattr(parallel, "process_pool", make_pool)
    monkeypatch.setattr(parallel, "bounded_results", run_jobs)
    conditions._parallel_groups(
        cast(LocalInputs, inputs),
        "R1",
        output,
        groups,
        candidates,
        progress,
        progress_path,
        lambda done, total: progress_events.append((done, total)),
    )

    assert progress_events == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert progress["completed"][existing_name] == existing_name
    assert len(submitted) == 3
    assert [(job.group, job.horizon) for job in submitted] == [
        ("pattern:union", 252),
        ("C-secondary", 126),
        ("C-secondary", 252),
    ]
    assert submitted[0].candidates == candidates
    assert all(job.candidates == {} for job in submitted[1:])
    assert len({job.staging for job in submitted}) == len(submitted)
    assert all((output / f"{job.group.replace(':', '%3A')}-h{job.horizon}" / "published-marker").is_file() for job in submitted)
    assert all(not job.staging.exists() for job in submitted)
    assert captured_specs[0].require_complete is True and captured_specs[0].read_only is True
    assert captured_specs[0].cache == temporary / "events" / "R1"
    assert read_json(progress_path)["completed"] == progress["completed"]
    assert read_json(temporary / "parallel-conditions-R1.json")["tasks"] == [{"worker_pid": 1, "phases": {"frame_read_seconds": 0.0}}] * 3
