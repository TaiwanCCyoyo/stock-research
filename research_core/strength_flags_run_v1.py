"""Gated research execution; all market reads require both owner-merged PRs.

No execution happens on import. This module never changes producer data,
PR17 holds/processes, or the momentum study's forward log/schedule.
"""

from __future__ import annotations

import json
import logging
import pickle
import shutil
import subprocess
import time
import zlib
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from numpy.typing import NDArray
from pandas.testing import assert_frame_equal

from research_core import momentum_only_v1 as momentum
from research_core.artifact_store import publish_new_directory, write_json
from research_core.live_producer import assert_producer_idle
from research_core.maintained_adjusted_daily import (
    current_generation,
    held_generations,
    hold_generation,
    read_adjusted_daily,
    read_technical,
    release_generation,
)
from research_core.pattern_scan_conditions_v1 import classify_column
from research_core.pattern_scan_daily_values_v1 import calculate_common_values
from research_core.pattern_scan_flags_v1 import FLAG_IDS, event_flag_observations
from research_core.pattern_scan_indicators_v1 import prepare_detector_frame
from research_core.research_measurement_v1 import host_resources, phase_receipt, resource_sample
from research_core.run_receipt import InputSpec, changed_results, code_identity, fingerprint_inputs, write_run_receipt
from research_core.scratch_runs import ScratchRun, create_run, open_run
from research_core.strength_flag_counts_v1 import CELL_KEYS, GROUPS, METRICS, cell_cube, count_stock, intervals, memberships, parity_counts, summarize_cell
from research_core.strength_flags_v1 import APPLICABLE_FLAGS, FLAG_STATES, LANDMARKS, BatchFlagIndex

LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "20261024-strength-weakening-flags"
TASK = REPO_ROOT / "tasks" / TASK_ID
HOLDER = "strength-weakening-flags"
DEFINITION_ID = "strength-weakening-flags.v1"
REPOSITORY = "TaiwanCCyoyo/stock-research"
REFERENCE = momentum.TASK / "results/set_summary-all-full.parquet"
REFERENCE_GROUPS = {"C-base-daily": "C-base-daily", "C-52w-daily": "C-52w-daily", "CORE": "A1&A2:daily", "LEAD_B1": "LEAD_B1:daily"}


class AlignmentError(RuntimeError):
    """A required exact comparison failed; rules may not be changed to proceed."""


def github_pr(number: int) -> dict[str, Any]:
    result = subprocess.run(
        ["gh", "pr", "view", str(number), "--repo", REPOSITORY, "--json", "number,url,state,mergedAt,mergeCommit,baseRefName,files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def verify_owner_merges(mission_pr: int, code_pr: int, *, lookup: Callable[[int], dict[str, Any]] = github_pr) -> list[dict[str, Any]]:
    """Verify exact task identities and merged destination, never accept an override flag."""
    if mission_pr == code_pr or min(mission_pr, code_pr) < 1:
        raise ValueError("two distinct positive PR numbers are required")
    records: list[dict[str, Any]] = []
    for number, required in ((mission_pr, f"tasks/{TASK_ID}/mission.md"), (code_pr, "scripts/run_strength_flags.py")):
        record = lookup(number)
        files = {row["path"] for row in record.get("files", [])}
        if record.get("state") != "MERGED" or not record.get("mergedAt") or record.get("baseRefName") != "main" or required not in files:
            raise RuntimeError(f"PR #{number} must be owner-merged into {REPOSITORY} main and contain {required}")
        if record.get("url") != f"https://github.com/{REPOSITORY}/pull/{number}":
            raise RuntimeError("PR destination identity differs from the approved repository")
        merge_record = record.get("mergeCommit")
        merge = merge_record.get("oid") if isinstance(merge_record, dict) else None
        if not isinstance(merge, str) or len(merge) != 40:
            raise RuntimeError("merged PR is missing its merge commit")
        records.append(record)
    return records


def verify_execution_checkout(merges: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Fetch before execution; require clean code based on the latest remote main."""
    subprocess.run(["git", "fetch", "origin"], cwd=REPO_ROOT, check=True, timeout=120)
    expected = code_identity(REPO_ROOT)
    if expected.get("dirty"):
        raise RuntimeError("start market execution with clean committed code")
    for ref in ("origin/main", *[str(record["mergeCommit"]["oid"]) for record in merges]):
        subprocess.run(["git", "merge-base", "--is-ancestor", ref, "HEAD"], cwd=REPO_ROOT, check=True, timeout=30)
    return expected


def compare_reference(actual: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    """Eight group/horizon rows, every known/hit/loss integer must match exactly."""
    rows = []
    for group in GROUPS:
        for horizon in (126, 252):
            ours = actual.loc[actual.group_id.eq(group) & actual.horizon.eq(horizon) & actual.target_multiple.eq(2)]
            expected = reference.loc[reference.group_id.eq(REFERENCE_GROUPS[group]) & reference.horizon.eq(horizon) & reference.target_multiple.eq(2)]
            if "era" in expected:
                expected = expected.loc[expected.era.eq("all")]
            if "split" in expected:
                expected = expected.loc[expected.split.eq("all")]
            if "row_kind" in expected:
                expected = expected.loc[expected.row_kind.eq("full")]
            if len(ours) != 1 or len(expected) != 1:
                raise AlignmentError(f"alignment row missing/duplicated: {group}, H{horizon}")
            row = {"group_id": group, "horizon": horizon, "target_multiple": 2.0}
            for metric in ("known_n", "hit_n", "loss_n"):
                observed, previous = int(ours.iloc[0][metric]), int(expected.iloc[0][metric])
                row.update({metric: observed, f"reference_{metric}": previous, f"delta_{metric}": observed - previous})
            rows.append(row)
    return pd.DataFrame(rows)


def require_exact_alignment(comparison: pd.DataFrame) -> None:
    if comparison[[f"delta_{metric}" for metric in ("known_n", "hit_n", "loss_n")]].to_numpy().any():
        raise AlignmentError("C-2 PR61 totals differ; preserve differences and stop for owner, without changing a rule")


def assert_observation_parity(frame: pd.DataFrame, pivots: pd.DataFrame, t0s: Sequence[int], *, reference_frame: pd.DataFrame | None = None) -> int:
    """Seven applicable flags, all public clock/state/offset/riskset/rise fields."""
    index = BatchFlagIndex(frame, pivots, max_horizon=252)
    for t0 in t0s:
        old = event_flag_observations(frame if reference_frame is None else reference_frame, pivots, int(t0))
        new = index.observations([int(t0)], targets=(2.0,), horizons=(126, 252))
        old = old.loc[old.flag_id.isin(APPLICABLE_FLAGS)].reset_index(drop=True)
        new = new.loc[new.flag_id.isin(APPLICABLE_FLAGS), old.columns].reset_index(drop=True)
        try:
            assert_frame_equal(new, old, check_dtype=False, check_exact=True)
            for row in old.itertuples(index=False):
                cutoff = min(row.landmark, int(row.first_hit_offset) - 1) if pd.notna(row.first_hit_offset) else row.landmark
                state, offset = index.histories(row.flag_id, np.array([int(t0)], dtype=np.int64), np.array([cutoff], dtype=np.int64))
                if FLAG_STATES[state[0]] != row.flag_state or (None if offset[0] < 0 else int(offset[0])) != (
                    None if pd.isna(row.first_trigger_offset) else int(row.first_trigger_offset)
                ):
                    raise AssertionError(f"production history differs: {row.flag_id}, L{row.landmark}")
        except AssertionError as error:
            raise AlignmentError(f"C-2 flag parity differs at t0={t0}: {error}") from error
    return len(t0s)


def _prepared(code: str, generation: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    assert_producer_idle()
    rows, record = read_adjusted_daily(
        "reference_factor_adjusted", codes=[code], generation=generation, as_of=momentum.CUTOFF, calendar=momentum.pr17_calendar()
    )
    return rows.drop(columns="Code").set_index("Date"), record


def _save_stock(path: Path, stock: momentum.StockDaily) -> None:
    arrays: dict[str, NDArray[Any]] = {
        "eligible": stock.eligible,
        "jump": stock.jump,
        "c52w": stock.c52w,
        "ret120": stock.ret120,
    }
    arrays.update({f"atom_{name}": value for name, value in stock.atoms.items()})
    arrays.update({f"label_{h}_{t:g}": value for (h, t), value in stock.labels.items()})
    arrays.update({f"main_{h}_{t:g}": value for (h, t), value in stock.main_eligible.items()})
    arrays.update({f"full_{h}": value for h, value in stock.calendar_full.items()})
    temporary = path.with_suffix(".partial.npz")
    np.savez_compressed(temporary, allow_pickle=False, **arrays)
    temporary.replace(path)


def _load_stock(path: Path, code: str) -> momentum.StockDaily:
    with np.load(path, allow_pickle=False) as data:
        return momentum.StockDaily(
            code,
            momentum.split_for_code(code),
            data["eligible"],
            data["jump"],
            data["c52w"],
            {name: data[f"atom_{name}"] for name in momentum.LOCAL_ATOMS},
            data["ret120"],
            {(h, t): data[f"label_{h}_{t:g}"] for h, t in momentum.LABELS},
            {(h, t): data[f"main_{h}_{t:g}"] for h, t in momentum.LABELS},
            {h: data[f"full_{h}"] for h in momentum.HORIZONS},
        )


def representative_codes(codes: Sequence[str]) -> list[str]:
    fixed = [code for code in ("1104", "1416", "1589", "2330", "6236", "6986") if code in codes]
    remaining = sorted(set(codes) - set(fixed), key=lambda code: (zlib.crc32(code.encode()), code))
    return [*fixed, *remaining[: 20 - len(fixed)]]


def indicator_probe(codes: Sequence[str], generation: str) -> dict[str, Any]:
    """Twenty-stock equality inventory; current-asof tables never silently replace cutoff indicators."""
    status = current_generation(generation=generation)
    report: dict[str, Any] = {"codes": list(codes), "selected": [], "comparisons": [], "shared_reads": []}
    if str(status["asof"]) != momentum.CUTOFF:
        report["reason"] = "stored technical tables are computed at another asof; cutoff recomputation through PR17 adapter is required"
        return report
    tables: dict[str, pd.DataFrame] = {}
    for table in ("daily", "conditions"):
        if status.get("technical", {}).get("tables", {}).get(table) is not None:
            tables[table], record = read_technical(table, codes=list(codes), generation=generation)
            report["shared_reads"].append(record)
    definitions = [
        ("daily", "SMA20", "SMA20"),
        ("daily", "SMA60", "SMA60"),
        ("daily", "BBLower", "BB20_Lower"),
        ("conditions", "C3", "close_to_sma240"),
        ("conditions", "D2", "close_to_prior250_low"),
        ("conditions", "G2_limit", "raw_return1"),
    ]
    for code in codes:
        prepared, _ = _prepared(code, generation)
        adapter, pivots = prepare_detector_frame(prepared)
        common = calculate_common_values(adapter, pivots)
        for table, ours, theirs in definitions:
            equal = False
            if table in tables:
                shared = tables[table]
                other = shared.loc[shared.Code.astype(str).eq(code)].set_index("Date").reindex(adapter.index)
                expected = adapter[ours] if table == "daily" else common[ours]
                observed = _condition_values(ours, other[theirs]) if theirs in other else None
                equal = observed is not None and np.array_equal(
                    expected.to_numpy(dtype=float, na_value=np.nan), observed.to_numpy(dtype=float, na_value=np.nan), equal_nan=True
                )
            report["comparisons"].append({"code": code, "column": f"{table}:{ours}:{theirs}", "equal": bool(equal)})
    report["selected"] = [
        f"{table}:{ours}:{theirs}"
        for table, ours, theirs in definitions
        if all(row["equal"] for row in report["comparisons"] if row["column"] == f"{table}:{ours}:{theirs}")
    ]
    report["reason"] = "only columns identical for all 20 stocks are read from shared tables; pivots always come from the PR17 adapter"
    return report


def _condition_values(name: str, values: pd.Series) -> pd.Series:
    if name != "G2_limit":
        return values
    return pd.Series([None if pd.isna(value) else bool(value >= 0.095) for value in values], index=values.index, dtype=object)


def _study_stock(code: str, prepared: pd.DataFrame, generation: str, selected: Sequence[str]) -> tuple[momentum.StockDaily, pd.DataFrame, pd.DataFrame]:
    stock = momentum.stock_daily(code, prepared)
    frame, pivots = prepare_detector_frame(prepared)
    for table in ("daily", "conditions"):
        columns = [value.split(":")[1:] for value in selected if value.split(":")[0] == table]
        if not columns:
            continue
        shared, _ = read_technical(table, codes=[code], generation=generation, columns=[names[1] for names in columns])
        shared = shared.set_index("Date").reindex(frame.index)
        for name, source in columns:
            values = _condition_values(name, cast(pd.Series, shared[source]))
            if table == "daily":
                frame[name] = values.to_numpy()
            else:
                atom = {"C3": "A1", "D2": "A2", "G2_limit": "A3"}[name]
                feature, bin_id, _ = momentum.ATOMS[atom]
                classified = classify_column(feature, values)
                stock.atoms[atom] = np.where(classified.status.eq("known"), classified.bin_id.eq(bin_id).astype(np.int8), np.int8(-1)).astype(np.int8)
    return stock, frame, pivots


def _count_job(job: tuple[str, str, str, tuple[str, ...]]) -> dict[str, Any]:
    code, generation, directory, selected = job
    started = resource_sample()
    prepared, shared = _prepared(code, generation)
    read_done = resource_sample()
    stock, indicators, pivots = _study_stock(code, prepared, generation, selected)
    flags = BatchFlagIndex(indicators, pivots)
    prepared_done = resource_sample()
    counts = count_stock(stock, flags, momentum.calendar_years(momentum.pr17_calendar()))
    computed_done = resource_sample()
    path = Path(directory) / f"{code}.parquet"
    temporary = path.with_suffix(".partial.parquet")
    counts.to_parquet(temporary, compression="zstd", index=False)
    temporary.replace(path)
    ended = resource_sample()
    return {
        "code": code,
        "rows": len(counts),
        "bytes": path.stat().st_size,
        "dataframe_memory_bytes": int(counts.memory_usage(index=True, deep=True).sum()),
        "shared": shared,
        "phases": [
            phase_receipt("read", started, read_done),
            phase_receipt("indicators_flags", read_done, prepared_done),
            phase_receipt("counts", prepared_done, computed_done),
            phase_receipt("write", computed_done, ended),
        ],
        "measurement": phase_receipt("stock_total", started, ended),
    }


def _bounded_jobs(jobs: Sequence[tuple[str, str, str, tuple[str, ...]]], workers: int) -> list[dict[str, Any]]:
    if workers == 1:
        return [_count_job(job) for job in jobs]
    records: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        # At most workers futures exist; fixed input order controls aggregation.
        for start in range(0, len(jobs), workers):
            records.extend(pool.map(_count_job, jobs[start : start + workers]))
    return records


def probe_cost(directory: Path, codes: Sequence[str], generation: str, *, memory_limit_bytes: int, selected: tuple[str, ...]) -> dict[str, Any]:
    """Serial/2/4 worker equality and phase/counter receipts on identical stocks."""
    records: list[dict[str, Any]] = []
    serialization_started = time.perf_counter()
    pickle.loads(pickle.dumps((list(codes), generation, str(directory))))
    serialization = time.perf_counter() - serialization_started
    for workers in (1, 2, 4):
        if workers > 1:
            serial_peak = records[0]["estimated_worker_peak_bytes"]
            if serial_peak is None or workers * serial_peak > memory_limit_bytes:
                records.append({"workers": workers, "not_run": "serial peak gives insufficient worker memory admission", "within_memory_limit": False})
                continue
        target = directory / f"workers-{workers}"
        target.mkdir(parents=True, exist_ok=True)
        before = resource_sample()
        child = _bounded_jobs([(code, generation, str(target), selected) for code in codes], workers)
        after = resource_sample()
        if workers > 1:
            for code in codes:
                assert_frame_equal(pd.read_parquet(directory / "workers-1" / f"{code}.parquet"), pd.read_parquet(target / f"{code}.parquet"), check_exact=True)
        peaks = [row["measurement"]["native"]["peak_working_set_process_lifetime_bytes"] for row in child if row["measurement"]["native"] is not None]
        estimated_peak = workers * max(peaks) if peaks else None
        records.append({
            "workers": workers,
            "max_in_flight": workers,
            "measurement": phase_receipt("probe_total", before, after),
            "stocks": child,
            "estimated_worker_peak_bytes": estimated_peak,
            "within_memory_limit": estimated_peak is not None and estimated_peak <= memory_limit_bytes,
        })
    usable = [row for row in records if row["within_memory_limit"]]
    if not usable:
        raise RuntimeError("worker memory measurements unavailable or exceed the explicit limit; stop for owner")
    chosen = min(usable, key=lambda row: row["measurement"]["wall_seconds"])
    nstocks = len(momentum.pr17_codes())
    bytes_estimate = sum(row["bytes"] for row in chosen["stocks"]) * nstocks / len(codes)
    free_bytes = shutil.disk_usage(directory).free
    years = sorted(set(momentum.calendar_years(momentum.pr17_calendar()).tolist()))
    probe_dataset = ds.dataset([directory / "workers-1" / f"{code}.parquet" for code in codes], format="parquet")
    filter_ = (
        (ds.field("group_id") == "C-base-daily")
        & (ds.field("horizon") == 126)
        & (ds.field("target_multiple") == 2)
        & (ds.field("landmark") == 20)
        & (ds.field("flag_id") == "X6_10")
    )
    summary_started = resource_sample()
    probe_counts = cell_cube(probe_dataset.to_table(filter=filter_).to_pandas(), codes, years)
    intervals(probe_counts)
    summary_done = resource_sample()
    summary_measurement = phase_receipt("cell_load_and_bootstrap", summary_started, summary_done)
    cell_count = len(GROUPS) * len(momentum.LABELS) * len(LANDMARKS) * len(FLAG_IDS)
    bootstrap_estimate = summary_measurement["wall_seconds"] * cell_count * nstocks / len(codes)
    cube_memory_estimate = nstocks * len(years) * 4 * 5 * len(METRICS) * 8
    if bytes_estimate * 1.25 > free_bytes or cube_memory_estimate * 4 > memory_limit_bytes:
        raise RuntimeError("estimated scratch disk or summary memory exceeds admission; stop without shrinking the study")
    return {
        "codes": list(codes),
        "host": host_resources(),
        "records": records,
        "selected_workers": chosen["workers"],
        "max_in_flight": chosen["workers"],
        "memory_limit_bytes": memory_limit_bytes,
        "job_serialization_roundtrip_seconds": serialization,
        "startup_scope": "parent wall includes pool startup and dispatch; isolated startup observation unavailable",
        "estimated_count_seconds": chosen["measurement"]["wall_seconds"] * nstocks / len(codes),
        "summary_probe": summary_measurement,
        "estimated_summary_seconds": bootstrap_estimate,
        "estimate_limitations": "linear stock-count extrapolation; cell density, compression and bootstrap work may differ across cells",
        "estimated_total_seconds": chosen["measurement"]["wall_seconds"] * nstocks / len(codes) + bootstrap_estimate,
        "estimated_intermediate_bytes": bytes_estimate,
        "scratch_free_bytes": free_bytes,
        "summary_cube_estimated_bytes": cube_memory_estimate,
    }


def _prepare_alignment(run: ScratchRun, codes: Sequence[str], generation: str, selected: Sequence[str]) -> tuple[pd.DataFrame, list[tuple[str, int]]]:
    directory = run.path / "stocks"
    directory.mkdir(exist_ok=True)
    totals: list[pd.DataFrame] = []
    core: list[tuple[str, int]] = []
    years = momentum.calendar_years(momentum.pr17_calendar())
    for position, code in enumerate(codes, 1):
        path = directory / f"{code}.npz"
        if path.exists():
            stock = _load_stock(path, code)
        else:
            prepared, _ = _prepared(code, generation)
            stock, _, _ = _study_stock(code, prepared, generation, selected)
            _save_stock(path, stock)
        total = parity_counts(stock, years)
        total.insert(0, "code", code)
        totals.append(total)
        core.extend((code, int(t0)) for t0 in np.flatnonzero(memberships(stock)["CORE"] & stock.eligible))
        run.heartbeat(progress={"step": position, "total": len(codes), "label": "對齊既有研究"})
    per_stock = pd.concat(totals)
    per_stock.to_parquet(run.path / "alignment-stock-totals.parquet", index=False)
    actual = cast(
        pd.DataFrame,
        per_stock.groupby(["group_id", "horizon", "target_multiple"], as_index=False)[["known_n", "hit_n", "loss_n"]].sum(),
    )
    return actual, core


def _alignment_gate(run: ScratchRun, codes: Sequence[str], generation: str, selected: Sequence[str]) -> dict[str, Any]:
    actual, core = _prepare_alignment(run, codes, generation, selected)
    comparison = compare_reference(actual, pd.read_parquet(REFERENCE))
    comparison.to_parquet(run.path / "alignment-totals.parquet", index=False)
    require_exact_alignment(comparison)
    if len(core) < 200:
        raise AlignmentError("fewer than the required 200 CORE events; stop rather than reduce the sample")
    drawn_indices = np.random.default_rng(20261024).choice(len(core), 200, replace=False)
    sample = sorted(core[int(index)] for index in drawn_indices)
    pd.DataFrame(sample, columns=pd.Index(["code", "t0_index"])).to_parquet(run.path / "alignment-sample.parquet", index=False)
    checked = 0
    for code in sorted({row[0] for row in sample}):
        prepared, _ = _prepared(code, generation)
        reference_frame, _ = prepare_detector_frame(prepared)
        _, frame, pivots = _study_stock(code, prepared, generation, selected)
        checked += assert_observation_parity(frame, pivots, [row[1] for row in sample if row[0] == code], reference_frame=reference_frame)
    return {"exact_totals": True, "sampled_core_events": checked, "seed": 20261024, "generation": generation}


def _write_tables(run: ScratchRun, codes: Sequence[str]) -> list[Path]:
    dataset = ds.dataset(run.path / "counts", format="parquet")
    years = sorted(set(momentum.calendar_years(momentum.pr17_calendar()).tolist()))
    final = run.path / "final"
    final.mkdir(exist_ok=True)
    outputs = []
    for group in GROUPS:
        for horizon in momentum.HORIZONS:
            summaries, bounds, strata = [], [], []
            for target in momentum.TARGETS:
                for flag in FLAG_IDS:
                    common = (
                        (ds.field("group_id") == group)
                        & (ds.field("horizon") == horizon)
                        & (ds.field("target_multiple") == target)
                        & (ds.field("flag_id") == flag)
                    )
                    full = dataset.to_table(filter=common & (ds.field("landmark") == horizon)).to_pandas()
                    for landmark in LANDMARKS:
                        if landmark >= horizon:
                            continue
                        key = {"group_id": group, "horizon": horizon, "target_multiple": target, "landmark": landmark, "flag_id": flag}
                        rows = dataset.to_table(filter=common & (ds.field("landmark") == landmark)).to_pandas()
                        summary, interval = summarize_cell(rows, full, codes, years, key=key)
                        summaries.extend(summary)
                        bounds.extend(interval)
                        strata.extend(rows.groupby([*CELL_KEYS, "basis", "flag_state", "rise_bin"], as_index=False)[list(METRICS)].sum().to_dict("records"))
            for name, records in (("summary", summaries), ("intervals", bounds), ("rise-strata", strata)):
                path = final / f"{name}-{group}-H{horizon}.parquet"
                pd.DataFrame(records).to_parquet(path, compression="zstd", index=False)
                outputs.append(path)
    return outputs


def final_payload(path: Path) -> bytes:
    """Final JSON has one trailing LF before any final-result digest is made."""
    payload = path.read_bytes()
    return payload.rstrip(b"\r\n") + b"\n" if path.suffix.lower() == ".json" else payload


def save_timings(path: Path, timings: dict[str, Any], *, resume: bool) -> None:
    """A finalize retry reuses the first completed timings, preserving published bytes."""
    if path.exists():
        if not resume:
            raise RuntimeError("timings already exist; resume only this run rather than replacing them")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or "phases" not in value or "cost" not in value:
            raise RuntimeError("saved timings are incomplete; preserve them and stop")
        return
    write_json(path, timings)


def publish_final_outputs(run_path: Path, outputs: Sequence[Path], destination: Path, *, run_id: str, code_commit: str, resume: bool) -> None:
    """No-replace publication, or exact same-run recovery after publication succeeded."""
    marker = run_path / "publication.json"
    expected = {"destination": str(destination), "run": run_id, "code_commit": code_commit}
    if marker.exists():
        if json.loads(marker.read_text(encoding="utf-8")) != expected:
            raise RuntimeError("publication marker belongs to a different run/code/destination")
    else:
        if destination.exists():
            raise RuntimeError("existing results have no publication marker for this run; preserve them")
        write_json(marker, expected)
    payloads = {path.name: final_payload(path) for path in outputs}
    if destination.exists():
        existing = {path.name for path in destination.iterdir()}
        if (
            not resume
            or existing - {*payloads, "run-receipt.json"}
            or any(not (destination / name).is_file() or (destination / name).read_bytes() != value for name, value in payloads.items())
        ):
            raise RuntimeError("existing final results differ or belong to another run; preserve them and stop")
    else:
        publish_new_directory(destination, payloads)


def reusable_receipt(path: Path, *, run_id: str, code_commit: str, resume: bool, expected_results: Sequence[str], repo_root: Path = REPO_ROOT) -> bool:
    """Only an intact receipt from this same finalization can be reused."""
    if not path.exists():
        return False
    if not resume:
        raise RuntimeError("receipt already exists; use same-run resume")
    record = json.loads(path.read_text(encoding="utf-8"))
    if (
        record.get("run_id") != run_id
        or record.get("code", {}).get("commit") != code_commit
        or set(record.get("results", {})) != set(expected_results)
        or changed_results(path, repo_root)
    ):
        raise RuntimeError("existing receipt/results differ from this run; preserve them and stop")
    return True


def finish_resource_probe(run: ScratchRun, *, generation: str, reason: str) -> None:
    """End only this completed probe's hold; failed probes keep their resumable hold."""
    own = [row for rows in held_generations().values() for row in rows if row.get("holder") == HOLDER]
    if len(own) != 1 or own[0].get("generation") != generation or own[0].get("reason") != reason:
        raise RuntimeError("probe holder no longer matches this run; do not release another reader's hold")
    path = run.path / "probe-only.json"
    if not path.exists():
        write_json(path, {"alignment": "pending", "research_complete": False, "formal_results": False})
    if run.record["state"] != "complete":
        run.mark("complete")
    release_generation(HOLDER)


def run_study(
    *, mission_pr: int, code_pr: int, run_id: str, owner: str, probe: bool = False, resume: bool = False, memory_limit_bytes: int = 4 * 1024**3
) -> Path:
    """C entrypoint; alignment failures leave labelled scratch evidence and stop."""
    merges = verify_owner_merges(mission_pr, code_pr)
    expected_code = verify_execution_checkout(merges)
    assert_producer_idle()
    calendar, codes = momentum.pr17_calendar(), momentum.pr17_codes()
    representative = representative_codes(codes)
    generation = str(current_generation()["generation"])
    purpose = "20-stock resource probe only; alignment pending, no study conclusion" if probe else "Weakening flags; descriptive exposed history only"
    context = open_run(TASK_ID, run_id, repo_root=REPO_ROOT) if resume else create_run(TASK_ID, run_id, purpose=purpose, owner=owner, repo_root=REPO_ROOT)
    with context as run:
        identity_path = run.path / "execution.json"
        if resume:
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
            if identity["code"]["commit"] != expected_code["commit"] or identity["probe"] != probe:
                raise RuntimeError("resume requires the same committed code and execution kind")
            generation = identity["generation"]
        else:
            write_json(identity_path, {"generation": generation, "code": expected_code, "probe": probe, "owner_merges": merges})
        held = held_generations()
        own_holds = [record for records in held.values() for record in records if record.get("holder") == HOLDER]
        reason = f"{TASK_ID}/{run_id}: preserve until report delivery"
        if own_holds and any(record.get("generation") != generation or record.get("reason") != reason for record in own_holds):
            raise RuntimeError("the study holder protects another run; preserve it and stop")
        hold_generation(generation, holder=HOLDER, reason=reason)
        started = resource_sample()
        inputs = fingerprint_inputs([
            InputSpec("pr17_calendar", momentum.PR17_PINS, live_producer=False),
            InputSpec("pr17_universe", momentum.PR17_UNIVERSE, live_producer=False),
            InputSpec("pr61_reference", REFERENCE, live_producer=False),
            InputSpec("pr61_receipt", REFERENCE.parent / "run-receipt.json", live_producer=False, optional=True),
        ])
        _, shared_record = read_adjusted_daily(
            "reference_factor_adjusted", codes=[representative[0]], generation=generation, as_of=momentum.CUTOFF, calendar=calendar
        )
        try:
            if not (run.path / "indicator-probe.json").exists():
                write_json(run.path / "indicator-probe.json", indicator_probe(representative, generation))
            selected_columns = tuple(json.loads((run.path / "indicator-probe.json").read_text(encoding="utf-8"))["selected"])
            if not probe and not (run.path / "alignment.json").exists():
                alignment = _alignment_gate(run, codes, generation, selected_columns)
                write_json(run.path / "alignment.json", alignment)
            if not (run.path / "cost.json").exists():
                cost = probe_cost(run.path / "probe", representative, generation, memory_limit_bytes=memory_limit_bytes, selected=selected_columns)
                write_json(run.path / "cost.json", cost)
            else:
                cost = json.loads((run.path / "cost.json").read_text(encoding="utf-8"))
            if cost["memory_limit_bytes"] > memory_limit_bytes:
                raise RuntimeError("recorded worker admission exceeds the requested memory limit; use a new resource probe")
            if probe:
                finish_resource_probe(run, generation=generation, reason=reason)
                return run.path
            directory = run.path / "counts"
            directory.mkdir(exist_ok=True)
            jobs = [(code, generation, str(directory), selected_columns) for code in codes if not (directory / f"{code}.parquet").exists()]
            for start in range(0, len(jobs), int(cost["selected_workers"])):
                _bounded_jobs(jobs[start : start + int(cost["selected_workers"])], int(cost["selected_workers"]))
                run.heartbeat(progress={"step": min(start + int(cost["selected_workers"]), len(jobs)), "total": len(jobs), "label": "計算轉弱訊號"})
            computed = resource_sample()
            outputs = _write_tables(run, codes)
            summarized = resource_sample()
            timings = {
                "phases": [phase_receipt("prepare_and_counts", started, computed), phase_receipt("summary_and_bootstrap", computed, summarized)],
                "cost": cost,
            }
            save_timings(run.path / "final" / "timings.json", timings, resume=resume)
            outputs.append(run.path / "final" / "timings.json")
            for name in ("alignment.json", "alignment-totals.parquet", "alignment-sample.parquet", "indicator-probe.json"):
                outputs.append(run.path / name)
            destination = TASK / "results"
            publish_final_outputs(run.path, outputs, destination, run_id=run_id, code_commit=expected_code["commit"], resume=resume)
            receipt_path = destination / "run-receipt.json"
            if not reusable_receipt(
                receipt_path, run_id=run_id, code_commit=expected_code["commit"], resume=resume, expected_results=[path.stem for path in outputs]
            ):
                write_run_receipt(
                    receipt_path,
                    run_id=run_id,
                    definition=DEFINITION_ID,
                    parameters={
                        "targets": momentum.TARGETS,
                        "horizons": momentum.HORIZONS,
                        "landmarks": LANDMARKS,
                        "bootstrap_reps": 2000,
                        "stock_seed": 20261024,
                        "two_way_seed": 20261025,
                    },
                    inputs=inputs,
                    results={path.stem: destination / path.name for path in outputs},
                    preregistration=TASK / "mission.md",
                    repo_root=REPO_ROOT,
                    shared_data=[shared_record],
                    expected_code=expected_code,
                    sources=[
                        REPO_ROOT / "research_core" / name
                        for name in ("strength_flags_run_v1.py", "strength_flags_v1.py", "strength_flag_counts_v1.py", "multiple_observations_v1.py")
                    ],
                )
                with receipt_path.open("ab") as receipt:
                    receipt.write(b"\n")
            if run.record["state"] != "complete":
                run.mark("complete")
            return destination
        except AlignmentError as error:
            LOGGER.error("C-2 STOP: %s; evidence retained at %s", error, run.path)
            if not (run.path / "alignment-stop.json").exists():
                reference_receipt = REFERENCE.parent / "run-receipt.json"
                previous = json.loads(reference_receipt.read_text(encoding="utf-8")) if reference_receipt.is_file() else None
                write_json(
                    run.path / "alignment-stop.json",
                    {
                        "error": str(error),
                        "generation": generation,
                        "reference": str(REFERENCE),
                        "reference_shared_data": previous.get("shared_data") if previous else None,
                        "stock_differences": (
                            "current per-stock totals retained; PR61 public aggregate does not identify affected stocks, so the cause remains unverified"
                        ),
                        "action": "stop_for_owner_no_rule_adjustment",
                    },
                )
            raise
