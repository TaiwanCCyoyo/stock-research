"""Gated live-data execution for the fixed tenbagger-drivers description.

No live input is read before both owner-merged PRs are verified. Probes measure
stock-local work only: a 20-stock ranking is never called full-market A4 parity.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research_core import momentum_only_v1 as momentum
from research_core import tenbagger_drivers_v1 as study
from research_core.artifact_store import copy_verified, file_digest, publish_noreplace, release_os_lock, safe_path, try_os_lock, write_json
from research_core.industry_breadth_v1 import industry_daily, prior_turnover
from research_core.institutional_flow_v1 import InstitutionalRead, assert_institutional_idle, institutional_daily, read_institutional
from research_core.live_producer import ProducerChangedError, readonly_sqlite, stat_identity
from research_core.maintained_adjusted_daily import current_generation, held_generations, hold_generation, read_adjusted_daily, release_generation
from research_core.producer_data import producer_data_root
from research_core.research_measurement_v1 import host_resources, phase_receipt, resource_sample
from research_core.run_receipt import InputSpec, changed_results, code_identity, fingerprint_inputs, write_run_receipt
from research_core.scratch_runs import create_run, scratch_root

LOGGER = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parents[1]
PR61_TASK = Path("tasks/20261021-momentum-only-doubling")
TASK = Path("tasks") / study.TASK_ID
OWNER = "TaiwanCCyoyo"
REPOSITORY = f"{OWNER}/stock-research"
SOURCES = (
    Path("research_core/industry_breadth_v1.py"),
    Path("research_core/institutional_flow_v1.py"),
    Path("research_core/tenbagger_drivers_v1.py"),
    Path("research_core/tenbagger_drivers_run_v1.py"),
    Path("scripts/run_tenbagger_drivers.py"),
)


def _git(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", "-C", str(repo_root), *arguments], capture_output=True, text=True, check=False)
    if completed.returncode:
        raise ValueError(f"Git prerequisite failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def check_merged_pr(number: int, repo_root: Path) -> dict[str, Any]:
    """Observe actual PR merge state, approved owner, destination and fetched main."""
    observed = subprocess.run(
        ["gh", "pr", "view", str(number), "--repo", REPOSITORY, "--json", "state,mergedAt,mergedBy,mergeCommit,baseRefName,url,headRefOid"],
        capture_output=True,
        text=True,
        check=False,
    )
    if observed.returncode:
        raise ValueError(f"cannot verify owner merge of PR {number}: {observed.stderr.strip()}")
    record: dict[str, Any] = json.loads(observed.stdout)
    if (
        record.get("state") != "MERGED"
        or not record.get("mergedAt")
        or record.get("baseRefName") != "main"
        or (record.get("mergedBy") or {}).get("login") != OWNER
    ):
        raise ValueError(f"PR {number} must be merged by the owner into {REPOSITORY} main before market reads")
    merge = (record.get("mergeCommit") or {}).get("oid")
    if not merge:
        raise ValueError(f"PR {number} has no verifiable merge commit")
    _git(repo_root, "merge-base", "--is-ancestor", str(merge), "origin/main")
    return record


def execution_gate(repo_root: Path, *, mission_pr: int, code_pr: int, step: str, formal_decision: Path | None) -> dict[str, Any]:
    """No allow flags: require owner-merged A/B and a recorded decision for D."""
    if step not in ("retro", "formal") or mission_pr == code_pr:
        raise ValueError("distinct mission/code PRs and a fixed retro|formal step required")
    records = {"mission_pr": check_merged_pr(mission_pr, repo_root), "code_pr": check_merged_pr(code_pr, repo_root)}
    for source in (TASK / "mission.md", *SOURCES):
        canonical = _git(repo_root, "show", f"origin/main:{source.as_posix()}")
        actual = (repo_root / source).read_text(encoding="utf-8").strip()
        if canonical != actual:
            raise ValueError(f"execution source differs from owner-merged origin/main: {source}")
    if step == "formal":
        if formal_decision is None:
            raise ValueError("formal execution requires the owner's recorded decision after the retrospective report")
        relative = formal_decision.resolve().relative_to(repo_root.resolve())
        if not relative.is_relative_to(TASK):
            raise ValueError("the formal owner decision belongs in this study's task directory")
        decision = json.loads(formal_decision.read_text(encoding="utf-8"))
        if decision.get("step") != "formal" or decision.get("decision") != "continue" or decision.get("decided_by") != OWNER:
            raise ValueError("formal owner decision must explicitly approve continuation")
        retro_receipt = repo_root / str(decision.get("retro_receipt", ""))
        if not retro_receipt.is_file() or not retro_receipt.resolve().is_relative_to((repo_root / TASK).resolve()):
            raise ValueError("formal decision must identify this study's completed retrospective receipt")
        receipt = json.loads(retro_receipt.read_text(encoding="utf-8"))
        if receipt.get("definition") != study.DEFINITION_ID or receipt.get("parameters", {}).get("step") != "retro":
            raise ValueError("formal decision names a different or incomplete retrospective run")
        evidence_path = retro_receipt.parent / "r6-recommendation.json"
        if not evidence_path.is_file() or "r6-recommendation.json" not in receipt.get("results", {}) or changed_results(retro_receipt, repo_root):
            raise ValueError("formal decision requires the preserved retrospective results and R6 evidence")
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        if evidence.get("rule") != "R6" or not evidence.get("owner_decision_required"):
            raise ValueError("retrospective R6 evidence is missing or belongs to a different rule")
        records["formal_decision"] = decision
    return records


def _equivalent(left: study.DriverStock, right: study.DriverStock) -> bool:
    if left.daily.code != right.daily.code or left.industry != right.industry or not left.features.equals(right.features):
        return False
    if not np.array_equal(left.close, right.close, equal_nan=True):
        return False
    for name in ("eligible", "jump", "c52w", "ret120"):
        if not np.array_equal(getattr(left.daily, name), getattr(right.daily, name), equal_nan=True):
            return False
    for name in ("atoms", "labels", "main_eligible", "calendar_full"):
        a, b = getattr(left.daily, name), getattr(right.daily, name)
        if a.keys() != b.keys() or any(not np.array_equal(a[key], b[key], equal_nan=True) for key in a):
            return False
    return True


def probe_stocks(codes: Sequence[str], prepare: Callable[[str], study.DriverStock], *, generation: str, code_commit: str) -> dict[str, Any]:
    """Measure identical local inputs serially and with 2/4 bounded threads.

    `executor.map` materializes only this fixed small probe, not the universe.
    No A4/breadth or market comparison is made here. Unsupported RSS/I/O are
    explicit unavailable fields from resource_sample, never fabricated values.
    """
    if not codes or len(set(codes)) != len(codes) or len(codes) > 20:
        raise ValueError("probe requires 1..20 unique fixed codes")
    baseline: list[study.DriverStock] = []
    measurements: list[dict[str, Any]] = []
    for workers in (1, 2, 4):
        before = resource_sample()
        started = time.monotonic()
        if workers == 1:
            found = [prepare(code) for code in codes]
            baseline = found
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                found = []
                for offset in range(0, len(codes), workers):
                    found.extend(executor.map(prepare, codes[offset : offset + workers]))
        finished = time.monotonic()
        after = resource_sample()
        if len(found) != len(baseline) or not all(_equivalent(a, b) for a, b in zip(baseline, found, strict=True)):
            raise study.AlignmentError(f"stock-local parallel probe differs with {workers} workers")
        measurements.append({
            "workers": workers,
            "in_flight_limit": workers,
            "wall_seconds": finished - started,
            "resources": phase_receipt(f"stock_local_threads_{workers}", before, after),
            "identical": True,
            "startup_and_scheduling_included": True,
            "serialization": "none: thread workers share read-only inputs",
        })
    fastest = min(measurements, key=lambda record: record["wall_seconds"])
    serialization_start = time.monotonic()
    encoded_bytes = 0
    retained_bytes: list[int] = []
    for stock in baseline:
        buffer = io.BytesIO()
        stock.features.to_parquet(buffer, index=True)
        encoded_bytes += buffer.tell()
        retained = int(stock.features.memory_usage(index=True, deep=True).sum()) + stock.close.nbytes
        retained += sum(getattr(stock.daily, name).nbytes for name in ("eligible", "jump", "c52w", "ret120"))
        retained += sum(array.nbytes for name in ("atoms", "labels", "main_eligible", "calendar_full") for array in getattr(stock.daily, name).values())
        retained_bytes.append(retained)
    # The fixed complete 1,942 x 4,110 ranking/breadth grids are mandatory.
    # Probe memory is an estimate, labelled as such, with available headroom
    # observed after live inputs were loaded. Keep 25% of it outside this budget.
    resources = host_resources()
    available = resources.get("physical_available_bytes")
    limit = None if available is None else int(available * 0.75)
    estimate = int(max(retained_bytes) * 1942 * 1.25 + 8 * 1942 * 4110 * 8)
    return {
        "schema": "tenbagger-local-probe.v1",
        "generation": generation,
        "code_commit": code_commit,
        "codes": list(codes),
        "measurements": measurements,
        "selected_workers": fastest["workers"],
        "scope": "stock-local only; no global A4 rank or alignment verdict",
        "global_parity": "not_evaluated",
        "thread_workers": True,
        "checkpoint_serialization": {
            "wall_seconds": time.monotonic() - serialization_start,
            "encoded_bytes": encoded_bytes,
            "format": "parquet features to memory; disk transfer measured separately during the full run",
        },
        "memory": {
            "estimated_retained_and_grid_bytes": estimate,
            "additional_memory_budget_bytes": limit,
            "available_after_inputs_bytes": available,
            "feasible": None if limit is None else estimate <= limit,
            "scope": "retained stock arrays/features + full-grid allowance; live input memory is already allocated",
        },
    }


def _sqlite_read(path: Path, query: str, cutoff: str) -> pd.DataFrame:
    wal = path.with_name(path.name + "-wal")
    before = (stat_identity(path), stat_identity(wal) if wal.exists() else None)
    with closing(readonly_sqlite(path)) as connection:
        frame = pd.read_sql_query(query, connection, params=[cutoff])
    if before != (stat_identity(path), stat_identity(wal) if wal.exists() else None):
        raise ProducerChangedError(f"producer database/WAL changed during read: {path}")
    return frame


def read_auxiliary(calendar: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Actual exchange amount/shares and current official classifications."""
    root = producer_data_root()
    quotes = _sqlite_read(root / "official_daily.sqlite", "SELECT code,date,value,volume FROM official_daily_price WHERE date <= ?", momentum.CUTOFF)
    metadata = _sqlite_read(root / "symbol_meta.sqlite", "SELECT code,industry_category FROM symbol_meta WHERE ? IS NOT NULL", momentum.CUTOFF)
    if quotes.duplicated(["code", "date"]).any() or metadata.code.duplicated().any():
        raise ValueError("ambiguous duplicate source amount, share volume or symbol metadata")
    quotes["date"] = pd.to_datetime(quotes.date)
    return quotes.set_index("code", drop=False).sort_index(), metadata.set_index("code", drop=False).sort_index()


def prepare_stock(
    code: str, calendar: pd.DatetimeIndex, generation: str, quotes: pd.DataFrame, metadata: pd.DataFrame, institutions: InstitutionalRead
) -> study.DriverStock:
    prices, _ = read_adjusted_daily("reference_factor_adjusted", codes=[code], as_of=momentum.CUTOFF, calendar=calendar, generation=generation)
    prepared = prices.drop(columns="Code").set_index("Date")
    daily = momentum.stock_daily(code, prepared)
    official = (quotes.loc[[code]] if code in quotes.index else quotes.iloc[:0]).set_index("date").reindex(calendar)
    category = metadata.loc[[code], "industry_category"] if code in metadata.index else pd.Series(dtype=object)
    industry = "unknown" if category.empty or pd.isna(category.iloc[0]) else str(category.iloc[0])
    rows = institutions.rows.loc[[code]] if code in institutions.rows.index else institutions.rows.iloc[:0]
    parts = [institutional_daily(rows, calendar, code, market, official.volume, institutions.coverage) for market in institutions.coverage]
    features = parts[0].copy()
    for part in parts[1:]:
        for column in features:
            valid = part[column].ne(-1) if column == "INST" or column.endswith("_state") else part[column].notna()
            features.loc[valid, column] = part.loc[valid, column]
    features["TURNOVER20"] = prior_turnover(official.value)
    features["BREADTH"] = np.nan
    features["SIZE_PERCENTILE"] = np.nan
    features["HOT"] = np.int8(-1)
    features["SMALL"] = np.int8(-1)
    return study.DriverStock(daily, momentum.masked_close(prepared), industry, features)


def attach_industries(stocks: Sequence[study.DriverStock], calendar: pd.DatetimeIndex, a4: Sequence[np.ndarray]) -> None:
    codes = [stock.daily.code for stock in stocks]
    eligible = pd.DataFrame({stock.daily.code: stock.daily.eligible for stock in stocks}, index=calendar)
    ranked = pd.DataFrame(dict(zip(codes, a4, strict=True)), index=calendar)
    amounts = pd.DataFrame({stock.daily.code: stock.features.TURNOVER20.to_numpy() for stock in stocks}, index=calendar)
    values = industry_daily(eligible, ranked, amounts, {stock.daily.code: stock.industry for stock in stocks})
    for stock in stocks:
        code = stock.daily.code
        for name, matrix in (("BREADTH", values.breadth), ("SIZE_PERCENTILE", values.size_percentile), ("HOT", values.hot), ("SMALL", values.small)):
            stock.features[name] = matrix[code].to_numpy()


def _episode_counts(stocks: Sequence[study.DriverStock]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "code": stock.daily.code,
            "target_multiple": target,
            "episode_n": len(momentum.merge_episodes(momentum.episode_starts(stock.daily, 504, target), stock.close, 504)),
        }
        for stock in stocks
        for target in (5.0, 10.0)
    ])


def alignment_gate(stocks: Sequence[study.DriverStock], a4: Sequence[np.ndarray], repo_root: Path, directory: Path, *, generation: str, formal: bool) -> None:
    """Compare the consumed A4 grid with PR61 recomputed on this fixed input.

    Both paths deliberately reuse PR61's unchanged implementation. This is a
    full-grid alignment check, not independent statistical replication and not
    a comparison against retired historical intermediates.
    """
    codes = [stock.daily.code for stock in stocks]
    published = json.loads((repo_root / PR61_TASK / "results" / "research_result.json").read_text(encoding="utf-8"))
    original_a4 = momentum.h_states([stock.daily for stock in stocks])
    differences: dict[str, Any] = {"A4": "not_evaluated", "episodes": "not_evaluated", "counts": "not_evaluated"}
    reference_identity = {
        "reference_generation": generation,
        "published_generation": published.get("generation"),
        "reference_method": "momentum_only_v1.h_states",
        "shared_implementation": True,
    }

    def stop(reason: str) -> None:
        write_json(directory / "alignment.json", {"verdict": "stop", **reference_identity, "differences": differences})
        raise study.AlignmentError(f"{reason}; see {directory / 'alignment.json'}; do not adjust definitions")

    differences["A4"] = study.exact_a4(a4, original_a4, codes)
    if differences["A4"]:
        stop("exact PR61 A4 alignment failed")
    reference = repo_root / PR61_TASK / "results"
    differences["episodes"] = study.exact_episode_counts(_episode_counts(stocks), pd.read_parquet(reference / "big_runner_coverage.parquet"))
    if differences["episodes"]:
        stop("exact PR61 episode alignment failed")
    if formal:
        # Gate only C-base-daily and unmasked CORE before calculating any of
        # this study's eight new condition-group outcome summaries.
        calendar = momentum.pr17_calendar()
        year_index = np.asarray(momentum.calendar_years(calendar) - momentum.FIRST_YEAR, dtype=np.intp)
        n_years = int(year_index.max()) + 1
        baseline_counts = np.zeros((len(study.GROUPS), len(study.LABELS), len(stocks), n_years, len(momentum.METRICS)), dtype=np.int32)
        labels = [momentum.LABELS.index(label) for label in study.LABELS]
        for stock_index, stock in enumerate(stocks):
            members = {"C-base-daily": np.ones(len(calendar), dtype=bool), "CORE": (stock.daily.atoms["A1"] == 1) & (stock.daily.atoms["A2"] == 1)}
            for group, mask in members.items():
                baseline_counts[study.GROUPS.index(group), :, stock_index] = momentum.group_counts(
                    stock.daily, mask, lookback=0, year_index=year_index, n_years=n_years
                )[labels]
        differences["counts"] = study.exact_formal_counts(baseline_counts, pd.read_parquet(reference / "set_summary-all-full.parquet"))
        if differences["counts"]:
            stop("exact PR61 formal baseline-count alignment failed")
    write_json(directory / "alignment.json", {"verdict": "exact", **reference_identity, "differences": differences})
    return None


def _exclusions(repo_root: Path) -> set[tuple[str, str]]:
    decisions = json.loads((repo_root / PR61_TASK / "audit-decisions.json").read_text(encoding="utf-8"))["decisions"]
    return {(str(row["code"]), str(row["anchor_date"])) for row in decisions if row.get("audit_price_error") is True}


@contextmanager
def execution_lock(path: Path) -> Iterator[None]:
    """Serialize the study across run ids and checkouts before touching its hold.

    The persistent lock file is not a liveness claim; the OS owns the lock and
    releases it on process exit. Never unlink it while another run may open it.
    """
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if not try_os_lock(handle):
            raise ValueError("another tenbagger study execution is running; preserve its hold")
        try:
            yield
        finally:
            release_os_lock(handle)


def publish_results(source: Path, destination: Path) -> None:
    """Verify copies of final small tables, then publish on the destination FS.

    Scratch may be on another volume. Only the destination's sibling staging
    directory is renamed; failure retains scratch and any staging for recovery.
    """
    source, destination = safe_path(source), safe_path(destination)
    if destination.exists():
        raise FileExistsError(f"result destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = safe_path(destination.parent / f".staging-{destination.name}-{uuid.uuid4().hex}")
    staging.mkdir()
    for path in sorted(source.iterdir()):
        if not path.is_file():
            raise ValueError(f"only final result files may be published: {path}")
        copy_verified(path, staging / path.name, file_digest(path))
    publish_noreplace(staging, destination)


def run(arguments: argparse.Namespace) -> None:
    """Execute one owner-gated probe or fixed step; never proceed to step two."""
    gates = execution_gate(REPO, mission_pr=arguments.mission_pr, code_pr=arguments.code_pr, step=arguments.step, formal_decision=arguments.formal_decision)
    with execution_lock(scratch_root() / study.TASK_ID / ".execution.lock"):
        _run_exclusive(arguments, gates)


def _run_exclusive(arguments: argparse.Namespace, gates: dict[str, Any]) -> None:
    """Keep the study lock through hold acquisition, all reads and hold release."""
    assert_institutional_idle()
    calendar, codes = momentum.pr17_calendar(), momentum.pr17_codes()
    if len(codes) != 1942:
        raise study.AlignmentError("the approved universe must contain 1,942 stocks")
    identity = code_identity(REPO, sources=[REPO / source for source in SOURCES])
    if identity["dirty"]:
        raise ValueError("commit the executed sources before a research run")
    status = current_generation(generation=arguments.generation)
    generation = str(status["generation"])
    if any(record.get("holder") == "tenbagger-drivers" for records in held_generations().values() for record in records):
        raise ValueError("tenbagger-drivers already has a generation hold; preserve it and inspect the existing run")
    hold_generation(generation, holder="tenbagger-drivers", reason=f"{study.TASK_ID} {arguments.step} {arguments.run_id}")
    try:
        root = producer_data_root()
        before = resource_sample()
        specs = [
            InputSpec("source_amount_and_shares", root / "official_daily.sqlite", tables={"official_daily_price": "date"}),
            InputSpec("official_classification", root / "symbol_meta.sqlite", tables={"symbol_meta": None}),
            InputSpec("institutional", root / "institutional.sqlite", tables={"institutional_daily": "date", "institutional_fetch_log": "date"}),
        ]
        if not arguments.probe:
            specs.extend([
                InputSpec("pr61_published_tables", REPO / PR61_TASK / "results", pattern="*.parquet", live_producer=False),
                InputSpec("pr61_published_identity", REPO / PR61_TASK / "results" / "research_result.json", live_producer=False),
                InputSpec("pr61_price_audit_decisions", REPO / PR61_TASK / "audit-decisions.json", live_producer=False),
            ])
        inputs = fingerprint_inputs(specs)
        observed_institutions = read_institutional(calendar)
        institutions = InstitutionalRead(
            observed_institutions.rows.set_index("code", drop=False).sort_index(), observed_institutions.coverage, observed_institutions.path
        )
        del observed_institutions
        quotes, metadata = read_auxiliary(calendar)
        after = resource_sample()
        with create_run(
            study.TASK_ID,
            arguments.run_id,
            purpose=f"{arguments.step} {'stock-local probe' if arguments.probe else 'fixed descriptive study'}",
            owner=arguments.owner,
            repo_root=REPO,
        ) as scratch:
            write_json(
                scratch.path / "inputs.json",
                {
                    "input_fingerprint": inputs,
                    "coverage": institutions.coverage,
                    "generation": generation,
                    "gates": gates,
                    "read_phase": phase_receipt("live_inputs", before, after),
                },
            )

            def prepare(code: str) -> study.DriverStock:
                return prepare_stock(code, calendar, generation, quotes, metadata, institutions)

            if arguments.probe:
                strata = ["1104", "1416", "1589", "2330", "6236", "6986"]
                import zlib

                remainder = sorted((code for code in codes if code not in strata), key=lambda code: (zlib.crc32(code.encode()), code))
                selected = [code for code in strata if code in codes] + remainder[:14]
                record = probe_stocks(selected, prepare, generation=generation, code_commit=identity["commit"])
                record["estimated_full_local_seconds"] = 1942 * min(row["wall_seconds"] for row in record["measurements"]) / len(selected)
                write_json(scratch.path / "probe.json", record)
                scratch.mark("complete")
                LOGGER.info("Probe complete %s; global parity not evaluated", scratch.path / "probe.json")
                return
            if arguments.probe_record is None:
                raise ValueError("full execution requires a completed --probe-record before choosing workers")
            probe = json.loads(arguments.probe_record.read_text(encoding="utf-8"))
            if probe.get("schema") != "tenbagger-local-probe.v1" or probe.get("generation") != generation or probe.get("code_commit") != identity["commit"]:
                raise ValueError("probe record must describe this exact generation and committed executor")
            workers = int(probe["selected_workers"])
            if workers not in (1, 2, 4) or float(probe["estimated_full_local_seconds"]) > 8 * 3600:
                raise ValueError("probe did not establish a bounded executable stock-local budget")
            if probe.get("memory", {}).get("feasible") is not True:
                raise ValueError("probe did not establish sufficient observed memory headroom; report the missing or exceeded bound")
            stocks: list[study.DriverStock] = []
            # At most workers in flight; each completed fixed-order batch is
            # stored before admitting the next, and no producer inputs are copied.
            stock_dir = scratch.path / "stocks"
            stock_dir.mkdir()
            with ThreadPoolExecutor(max_workers=workers) as executor:
                for offset in range(0, len(codes), workers):
                    batch = list(executor.map(prepare, codes[offset : offset + workers]))
                    stocks.extend(batch)
                    for stock in batch:
                        stock.features.to_parquet(stock_dir / f"{stock.daily.code}-features.parquet", index=True)
                    scratch.heartbeat(progress={"step": len(stocks), "total": len(codes), "label": "整理股票條件"})
            a4 = momentum.h_states([stock.daily for stock in stocks])
            attach_industries(stocks, calendar, a4)
            alignment_gate(stocks, a4, REPO, scratch.path, generation=generation, formal=arguments.step == "formal")
            started = resource_sample()
            tables: dict[str, pd.DataFrame] = {}
            recommendation: dict[str, Any] = {}
            if arguments.step == "retro":
                observations, _ = study.retro_observations(stocks, calendar, _exclusions(REPO))
                random, quotas = study.random_observations(observations, stocks, calendar)
                distributions, intervals, recommendation = study.retro_tables(observations, random, codes)
                tables.update(
                    retro_distributions=distributions,
                    retro_intervals=intervals,
                    tenbagger_episodes=observations.loc[observations.group_id.eq("ge10")],
                    retro_quotas=quotas,
                )
                write_json(scratch.path / "r6-recommendation.json", recommendation)
            else:
                counted = study.formal_counts(stocks, calendar)
                summary, intervals, verdicts = study.formal_tables(*counted, codes)
                tables.update(formal_summary=summary, formal_intervals=intervals, formal_verdicts=verdicts)
            finished = resource_sample()
            final = scratch.path / "final"
            final.mkdir()
            for name, table in tables.items():
                table.to_parquet(final / f"{name}.parquet", index=False)
            write_json(
                final / "execution.json",
                {
                    "step": arguments.step,
                    "coverage": institutions.coverage,
                    "generation": generation,
                    "workers": workers,
                    "in_flight_limit": workers,
                    "summary_phase": phase_receipt("summaries_bootstrap", started, finished),
                    "global_alignment": "exact",
                    "owner_decision_required": arguments.step == "retro",
                },
            )
            if arguments.step == "retro":
                write_json(final / "r6-recommendation.json", recommendation)
            destination = REPO / TASK / "results" / arguments.step / arguments.run_id
            destination.parent.mkdir(parents=True, exist_ok=True)
            publish_results(final, destination)
            results = {path.name: path for path in destination.iterdir() if path.is_file()}
            _, shared_read = read_adjusted_daily(
                "reference_factor_adjusted", codes=[codes[0]], columns=["Code", "Date"], as_of=momentum.CUTOFF, calendar=calendar, generation=generation
            )
            write_run_receipt(
                destination / "run-receipt.json",
                run_id=arguments.run_id,
                definition=study.DEFINITION_ID,
                parameters={
                    "step": arguments.step,
                    "cutoff": momentum.CUTOFF,
                    "targets": study.TARGETS,
                    "horizons": study.HORIZONS,
                    "bootstrap_reps": study.REPS,
                    "bootstrap_seeds": study.SEEDS,
                    "coverage": institutions.coverage,
                },
                inputs=inputs,
                results=results,
                preregistration=REPO / TASK / "mission.md",
                repo_root=REPO,
                shared_data=[shared_read],
                sources=[REPO / source for source in SOURCES],
                expected_code=identity,
            )
            scratch.mark("complete")
            LOGGER.info("%s finished at %s; final report/owner delivery still required", arguments.step, destination)
    finally:
        release_generation("tenbagger-drivers")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Fixed tenbagger description; A/B must be owner-merged before any probe or market read. No implicit formal continuation."
    )
    result.add_argument("--step", choices=("retro", "formal"), required=True)
    result.add_argument("--probe", action="store_true", help="Measure stock-local work on 20 fixed stocks only; does not perform global A4 alignment")
    result.add_argument("--mission-pr", type=int, required=True, help="Owner-merged A mission PR number")
    result.add_argument("--code-pr", type=int, required=True, help="Owner-merged B implementation PR number")
    result.add_argument(
        "--formal-decision",
        type=Path,
        help="Main session's record of the owner's direct continuation instruction after C, naming its verified retro receipt/R6 evidence",
    )
    result.add_argument("--probe-record", type=Path, help="Completed probe.json for this generation and code commit; required for the full run")
    result.add_argument("--generation", help="Explicit held generation; default current is resolved once")
    result.add_argument("--run-id", required=True, help="New labelled scratch run id; never overwrites another run")
    result.add_argument("--owner", required=True, help="Session identity recorded as the scratch owner")
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run(parser().parse_args())
