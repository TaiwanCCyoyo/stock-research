"""Isolated, bounded L1 checkpoint pilot; no full-market execution or selection."""

from __future__ import annotations

import io
import logging
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

from research_core import scratch_runs
from research_core.artifact_store import canonical, object_digest, publish_noreplace, read_json, write_json
from research_core.pattern_scan_dense_counts_v1 import DenseCounts
from research_core.pattern_scan_execution_v1 import _MemoryBoundJob
from research_core.pattern_scan_membership_v1 import StockCountPlan, membership_inventory
from research_core.pattern_scan_parquet_v1 import write_frame
from research_core.pattern_scan_q1_counts_v1 import Q1Counts
from research_core.pattern_scan_recovery_v1 import load_recovery_inventory, recover_stock
from research_core.pattern_scan_summary_store_v1 import YEARS
from research_core.research_data_paths import checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample
from research_core.run_receipt import InputSpec, assert_inputs_unchanged, code_identity, fingerprint_inputs, write_run_receipt

LOGGER = logging.getLogger(__name__)
INPUT_ID = "5c48eb999a81e42149c858331a601aff700a63af3c7f2fb8d642bf20b1370c05"
SOURCE_ID = "a3cfc677ef01547132ce5f3e5cd2a514201fecc02d65f4fa87aeb6fc69cc7ea4"
LABEL_VERSION = "checkpoint-only:27791891061e5d71cd791d3389beaae6923da7f2d6800462985937c2cba6e48f"
MEMORY_LIMIT = 2 * 1024**3
OUTPUT_LIMIT = 128 * 1024**2
TIMEOUT = 600
TASK = "20261013-pattern-scan"
PILOT_BOOTSTRAP = """
import logging,os,sys
from pathlib import Path
sys.dont_write_bytecode=True
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','BLIS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
sys.path.insert(0,sys.argv[1])
from research_core.pattern_scan_recovery_pilot_v1 import worker_main
worker_main(Path(sys.argv[2]))
"""


def _codes(codes: tuple[str, ...]) -> None:
    if (
        not isinstance(codes, tuple)
        or not 1 <= len(codes) <= 5
        or len(set(codes)) != len(codes)
        or any(not isinstance(code, str) or re.fullmatch(r"[A-Za-z0-9]+", code) is None for code in codes)
    ):
        raise ValueError("pilot requires one to five unique stock codes")


def _overlaps(left: Path, right: Path) -> bool:
    left, right = left.resolve(), right.resolve()
    return left.is_relative_to(right) or right.is_relative_to(left)


def _marginal_cells() -> dict[int, tuple[tuple[dict[str, Any], ...], tuple[str, ...], StockCountPlan, DenseCounts]]:
    result = {}
    for horizon in (126, 252):
        meta = {"pattern_id": "L1", "control_id": "pattern", "cohort_id": "union", "horizon": horizon}
        inventory = tuple(row for row in membership_inventory(meta) if row["feature_id"] in ("G", "VOL_a"))
        ids = tuple(object_digest(row) for row in inventory)
        result[horizon] = inventory, ids, StockCountPlan(inventory), DenseCounts(ids, horizon)
    return result


def _marginal_add(cells: dict[int, Any], events: pd.DataFrame, conditions: pd.DataFrame, markets: pd.Series) -> None:
    joined = events.merge(conditions, on="event_id", how="left", validate="many_to_one")
    joined["mkt"] = joined.t0.map(markets)
    for horizon, (_, _, plan, counts) in cells.items():
        counts.add_stock(plan.matrix(joined.loc[joined.horizon.eq(horizon)]))


def _marginal_finalize(cells: dict[int, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary: list[dict[str, Any]] = []
    annual: list[dict[str, Any]] = []
    for inventory, ids, _, counts in cells.values():
        for meta, cell in zip(inventory, ids, strict=True):
            removed, dropped = counts.drop_best_year(cell)
            summary.extend((
                {**meta, **counts.summarize(cell), "row_kind": "full", "removed_year": None},
                {**meta, **dropped, "row_kind": "drop_best_year", "removed_year": removed},
            ))
            annual.extend({**meta, **row, "year": year} for year, row in zip(YEARS, counts.annual_summary(cell), strict=True))
    return pd.DataFrame(summary), pd.DataFrame(annual)


def _parquet(frame: pd.DataFrame) -> bytes:
    stream = io.BytesIO()
    write_frame(frame, stream, index=False)
    return stream.getvalue()


def run_pilot_worker(
    stock_root: Path,
    output: Path,
    *,
    requested_codes: tuple[str, ...],
    expected_input_id: str,
    expected_source_id: str,
    expected_label_version_id: str,
    expected_calendar_n: int,
    expected_stock_n: int,
    expected_retained_n: int,
    repo_root: Path,
    run_id: str,
    expected_code: dict[str, Any],
) -> dict[str, Any]:
    """Read a bounded selection and publish final worker artifacts to a fresh directory."""
    _codes(requested_codes)
    stock_root, output, repo_root = map(checked_path, (stock_root, output, repo_root))
    if _overlaps(stock_root, output) or _overlaps(repo_root, output) or output.exists():
        raise ValueError("pilot output must be fresh and separate from inputs and checkout")
    before = resource_sample()
    inputs = fingerprint_inputs([
        InputSpec("stock_index", stock_root / "phase-stock-result.json", live_producer=False),
        InputSpec("preparation", stock_root / "derived-preparation.json", live_producer=False),
        InputSpec("global", stock_root / "global" / "receipt.json", live_producer=False),
    ])
    inventory = load_recovery_inventory(
        stock_root,
        requested_codes=requested_codes,
        expected_input_id=expected_input_id,
        expected_source_id=expected_source_id,
        expected_label_version_id=expected_label_version_id,
        expected_calendar_n=expected_calendar_n,
        expected_stock_n=expected_stock_n,
        expected_retained_n=expected_retained_n,
    )
    selected_inputs = []
    for code in requested_codes:
        stock_dir = Path(inventory.rows[code]["output_path"])
        selected_inputs.append(InputSpec(f"{code}:stock_receipt", stock_dir / "receipt.json", live_producer=False))
        for name in ("cohort_events", "base_labels", "indicators", "common_values"):
            selected_inputs.append(InputSpec(f"{code}:{name}", stock_dir / f"{name}.parquet", live_producer=False))
        global_path = checked_path(Path(inventory.barrier["global_files"][code]["path"]))
        if not global_path.is_relative_to(stock_root / "global"):
            raise ValueError("global input outside retained root")
        selected_inputs.append(InputSpec(f"{code}:global", global_path, live_producer=False))
        if code in inventory.retained:
            retained_dir = inventory.retained[code][0]
            for name in ("receipt.json", "events.parquet", "conditions.parquet", "group_memberships.parquet"):
                selected_inputs.append(InputSpec(f"{code}:retained:{name}", retained_dir / name, live_producer=False))
    selected_fingerprint = fingerprint_inputs(selected_inputs)
    inputs["inputs"].update(selected_fingerprint["inputs"])
    q1 = Q1Counts("L1", ("pattern:union",))
    marginal = _marginal_cells()
    audits, frames = [], {}
    reductions = []
    for code in requested_codes:
        recovered = recover_stock(inventory, code)
        reduction_before = resource_sample()
        q1.add_stock(code, recovered.events, recovered.memberships, markets=recovered.markets)
        _marginal_add(marginal, recovered.events, recovered.conditions, recovered.markets)
        reductions.append(phase_receipt(f"aggregate_{code}", reduction_before, resource_sample()))
        audits.append(recovered.audit)
        frames[f"{code}-events.parquet"] = recovered.events
        frames[f"{code}-conditions.parquet"] = recovered.conditions
    reduction_before = resource_sample()
    frames["q1-summary.parquet"], frames["q1-annual.parquet"] = q1.finalize()
    frames["marginal-summary.parquet"], frames["marginal-annual.parquet"] = _marginal_finalize(marginal)
    reductions.append(phase_receipt("aggregate_finalize", reduction_before, resource_sample()))
    serial_before = resource_sample()
    payloads = {name: _parquet(frame) for name, frame in frames.items()}
    serialization = phase_receipt("serialization", serial_before, resource_sample())
    # Leave bounded room for the audit, supervisor records and result receipt.
    if sum(map(len, payloads.values())) > OUTPUT_LIMIT - 2 * 1024**2:
        raise ValueError("pilot serialized outputs exceed the bounded output budget")
    assert_inputs_unchanged(inputs)
    inventory._reads.unchanged()
    output.mkdir()
    write_before = resource_sample()
    for name, body in payloads.items():
        staging = output / (".staging-" + name)
        with staging.open("xb") as stream:
            stream.write(body)
        publish_noreplace(staging, output / name)
    output_write = phase_receipt("artifact_write", write_before, resource_sample())
    assert_inputs_unchanged(inputs)
    inventory._reads.unchanged()
    audit = {
        "schema": "l1-recovery-pilot.v1",
        "run_id": run_id,
        "selected_codes": list(requested_codes),
        "scope": "bounded pilot; no four-cell or full-market results",
        "integrity_scope": "internal saved-receipt consistency; not independent archival authenticity",
        "full_q1_parity": "not_run",
        "full_marginal_parity": "not_run",
        "inventory_measurement": inventory.measurement,
        "runtime_provenance": inventory.runtime_audit,
        "retained_l1_payloads_verified": len(inventory.retained),
        "stocks": audits,
        "aggregation": reductions,
        "serialization": serialization,
        "artifact_write": output_write,
        "overall": phase_receipt("worker", before, resource_sample()),
        "input_fingerprint": inputs,
        "expected_code": expected_code,
    }
    audit_bytes = canonical(audit)
    if sum(map(len, payloads.values())) + len(audit_bytes) > OUTPUT_LIMIT - 1024**2:
        raise ValueError("pilot audit exceeds the bounded output budget")
    with (output / ".staging-audit.json").open("xb") as stream:
        stream.write(audit_bytes)
    publish_noreplace(output / ".staging-audit.json", output / "audit.json")
    return audit


def worker_main(request_path: Path) -> None:
    request = read_json(request_path)
    run_pilot_worker(
        Path(request["stock_root"]),
        Path(request["output"]),
        requested_codes=tuple(request["codes"]),
        expected_input_id=INPUT_ID,
        expected_source_id=SOURCE_ID,
        expected_label_version_id=LABEL_VERSION,
        expected_calendar_n=4110,
        expected_stock_n=1942,
        expected_retained_n=114,
        repo_root=Path(request["repo_root"]),
        run_id=request["run_id"],
        expected_code=request["expected_code"],
    )


def launch_pilot(stock_root: Path, *, codes: tuple[str, ...], run_id: str, owner: str, repo_root: Path) -> Path:
    """Create and supervise one fresh Windows scratch run; never resume or clean."""
    _codes(codes)
    if sys.platform != "win32":
        raise RuntimeError("pilot requires a Windows job object")
    stock_root, repo_root = checked_path(stock_root), checked_path(repo_root)
    if not stock_root.is_dir():
        raise ValueError("stock root does not exist")
    executor = code_identity(repo_root)
    if executor["dirty"]:
        raise ValueError("pilot requires a clean committed executor")
    scratch = scratch_runs.scratch_root(repo_root=repo_root)
    target = scratch / TASK / run_id
    if _overlaps(target, stock_root) or _overlaps(target, repo_root):
        raise ValueError("scratch output overlaps input or checkout")
    with scratch_runs.create_run(
        TASK,
        run_id,
        purpose="bounded L1 retained checkpoint recovery pilot",
        owner=owner,
        depends_on=(str(stock_root.resolve()),),
        root=scratch,
        repo_root=repo_root,
    ) as run:
        request_path = run.path / "request.json"
        output = run.path / "payload"
        write_json(
            request_path,
            {
                "stock_root": str(stock_root),
                "output": str(output),
                "codes": list(codes),
                "run_id": run_id,
                "repo_root": str(repo_root),
                "expected_code": executor,
            },
        )
        job = _MemoryBoundJob(MEMORY_LIMIT)
        started, last_heartbeat = time.monotonic(), 0.0
        exit_code = None
        timed_out = False
        terminated = False
        completed = False
        try:
            process = job.start([sys.executable, "-c", PILOT_BOOTSTRAP, str(repo_root), str(request_path)], repo_root)
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed - last_heartbeat >= 10 or last_heartbeat == 0:
                    run.heartbeat(progress={"step": 0, "total": len(codes), "label": "pilot worker running"})
                    last_heartbeat = elapsed
                if elapsed >= TIMEOUT:
                    timed_out = True
                    raise TimeoutError("pilot exceeded 600 second owned job limit")
                time.sleep(0.5)
            exit_code = process.returncode
            if time.monotonic() - started >= TIMEOUT:
                timed_out = True
                raise TimeoutError("pilot exceeded 600 second owned job limit")
            if exit_code:
                raise subprocess.CalledProcessError(exit_code, process.args)
            audit = read_json(output / "audit.json")
            if audit.get("selected_codes") != list(codes) or audit.get("expected_code") != executor or code_identity(repo_root) != executor:
                raise ValueError("pilot worker identity differs")
            job_observation = {**job.memory_receipt(), "wall_seconds": time.monotonic() - started, "exit_code": exit_code, "timed_out": False}
            terminated = True
            job.terminate_and_confirm()
            write_json(run.path / "job-memory.json", job_observation)
            files = {path.name: path for path in output.iterdir() if path.is_file()}
            files["job-memory.json"] = run.path / "job-memory.json"
            if sum(path.stat().st_size for path in run.path.rglob("*") if path.is_file()) > OUTPUT_LIMIT - 1024**2:
                raise ValueError("pilot artifacts exceed bounded output budget")
            write_run_receipt(
                run.path / "receipt.json",
                run_id=run_id,
                definition="l1-recovery-pilot.v1",
                parameters={
                    "codes": list(codes),
                    "input_id": INPUT_ID,
                    "source_id": SOURCE_ID,
                    "label_version_id": LABEL_VERSION,
                    "full_q1_parity": "not_run",
                    "full_marginal_parity": "not_run",
                },
                inputs=audit["input_fingerprint"],
                results=files,
                repo_root=repo_root,
                expected_code=executor,
            )
            run.heartbeat(progress={"step": len(codes), "total": len(codes), "label": "pilot complete; retained for review"})
            run.mark("complete")
            completed = True
            return run.path
        finally:
            try:
                if not completed:
                    write_json(
                        run.path / "job-failure.json",
                        {**job.memory_receipt(), "wall_seconds": time.monotonic() - started, "exit_code": exit_code, "timed_out": timed_out},
                    )
            finally:
                try:
                    if not terminated:
                        job.terminate_and_confirm()
                finally:
                    job.close()
