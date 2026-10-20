"""One-target Q4 results over the original study inputs, without payload pins.

Narrow target-local projections permit interrupted final reduction to resume.
The caller owns temporary retirement, final-result hashes and the run receipt.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from research_core.artifact_store import object_digest, read_json
from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_candidate_daily_v1 import daily_candidate_states
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_episode_coverage_v1 import CONTROL_COLUMNS, _control_rows
from research_core.pattern_scan_episode_tables_v1 import (
    OBSERVATION_COLUMNS,
    admission_counts,
    daily_base_coverage,
    grouped_coverage,
    observe_group,
    per_stock_episodes,
    summarize_coverage,
)
from research_core.pattern_scan_events_v1 import Episode
from research_core.pattern_scan_local_inputs_v5 import write_progress
from research_core.pattern_scan_reporting_v1 import ERAS, MARKETS, candidate_membership
from research_core.pattern_scan_retained_v3 import select_q4_examples

if TYPE_CHECKING:
    from research_core.pattern_scan_local_inputs_v5 import LocalInputs

LOGGER = logging.getLogger(__name__)
QUOTA_COLUMNS = ("security_id", "year", "quota_n", "available_n", "drawn_n", "shortfall_n", "shortfall", "coverage_status", "seed")
GROUP_COLUMNS = ("group_id", "split", "era", "mkt", "pattern_id", "candidate_id", "control_id")
TIMING_COLUMNS = ("late_known_n", "late_n") + tuple(
    f"{name}_{suffix}" for name in ("timing", "entry_return", "remaining_return") for suffix in ("known_n", "unknown_n", "q25", "median", "q75")
)
RESULT_COLUMNS = {
    "coverage.parquet": GROUP_COLUMNS
    + (
        "episode_n",
        "distinct_stock_n",
        "matched_n",
        "unmatched_n",
        "unknown_n",
        "coverage_rate",
        "coverage_lower_bound",
        "coverage_upper_bound",
    )
    + TIMING_COLUMNS,
    "timing.parquet": GROUP_COLUMNS + ("episode_n",) + TIMING_COLUMNS,
    "examples.parquet": OBSERVATION_COLUMNS,
    "admission-counts.parquet": ("security_id", "measure", "count"),
    "draws.parquet": CONTROL_COLUMNS + ("group_id",),
    "quotas.parquet": QUOTA_COLUMNS + ("group_id",),
}
PROJECTION_COLUMNS = {
    "observations": OBSERVATION_COLUMNS,
    "draws": RESULT_COLUMNS["draws.parquet"],
    "quotas": RESULT_COLUMNS["quotas.parquet"],
    "admission": RESULT_COLUMNS["admission-counts.parquet"],
}


def _readable(path: Path, columns: tuple[str, ...]) -> bool:
    """Check only the Parquet footer/schema, without a payload digest or scan."""
    try:
        with pq.ParquetFile(path) as parquet:
            names = parquet.schema_arrow.names
            return len(names) == len(columns) and set(names) == set(columns)
    except PermissionError:
        raise
    except (OSError, ValueError, pa.ArrowException):
        return False


def completed_results(output: Path) -> list[Path] | None:
    """Return the six readable final tables; the caller owns phase identity."""
    paths = [output / name for name in RESULT_COLUMNS]
    return paths if all(_readable(path, RESULT_COLUMNS[path.name]) for path in paths) else None


def _store_frame(path: Path, frame: pd.DataFrame) -> None:
    """Atomically replace one owned projection or an invalid final table."""
    staged = path.with_name(f".{path.name}.incomplete")
    with staged.open("wb") as stream:
        frame.to_parquet(stream, index=False, compression="zstd")
    os.replace(staged, path)


def _cached_stock(directory: Path) -> dict[str, pd.DataFrame] | None:
    if not all(_readable(directory / f"{name}.parquet", columns) for name, columns in PROJECTION_COLUMNS.items()):
        return None
    try:
        return {name: pd.read_parquet(directory / f"{name}.parquet") for name in PROJECTION_COLUMNS}
    except PermissionError:
        raise
    except (OSError, ValueError, pa.ArrowException):
        return None


def random_matched_control(pool: pd.DataFrame, targets: pd.DataFrame, group_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Preserve legacy ordering/seeds/draws while omitting pool payload hashes."""
    if not isinstance(group_id, str) or not group_id.strip():
        raise ValueError("group_id requires a nonblank string")
    # Reuse the legacy calendar, uniqueness and cooldown validation unchanged.
    available = _control_rows(pool, cooled=True)
    requested = _control_rows(targets, cooled=False)
    keys = sorted(set(zip(available.security_id, available.year, strict=True)) | set(zip(requested.security_id, requested.year, strict=True)))
    draws: list[pd.DataFrame] = []
    quotas: list[dict[str, object]] = []
    for stock, year in keys:
        stock_pool = available.loc[available.security_id.eq(stock) & available.year.eq(year)]
        quota = int((requested.security_id.eq(stock) & requested.year.eq(year)).sum())
        drawn = min(quota, len(stock_pool))
        # This digest derives an algorithmic seed, never an input/file identity.
        seed = int(object_digest({"seed": 20261013, "group_id": group_id, "security_id": stock, "year": int(year)})[:16], 16)
        positions = np.random.default_rng(seed).choice(len(stock_pool), size=drawn, replace=False)
        draws.append(stock_pool.iloc[np.sort(positions)].loc[:, list(CONTROL_COLUMNS)])
        quotas.append({
            "security_id": stock,
            "year": int(year),
            "quota_n": quota,
            "available_n": len(stock_pool),
            "drawn_n": drawn,
            "shortfall_n": quota - drawn,
            "shortfall": drawn < quota,
            "coverage_status": "unknown" if drawn < quota else "known",
            "seed": str(seed),
        })
    drawn_frame = pd.concat(draws, ignore_index=True) if draws else available.loc[:, list(CONTROL_COLUMNS)].iloc[:0]
    drawn_frame = drawn_frame.sort_values(["security_id", "calendar_index", "t0"], kind="stable").reset_index(drop=True)
    return drawn_frame, pd.DataFrame(quotas, columns=pd.Index(QUOTA_COLUMNS))


def random_control_coverage(
    pool: pd.DataFrame,
    targets: pd.DataFrame,
    *,
    group_id: str,
    episodes: tuple[Episode, ...],
    closes: list[float | None],
    dates: tuple[str, ...],
    anchor_regime: list[str],
    security_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Apply the original observed/unknown semantics without a pool pin."""
    drawn, quota = random_matched_control(pool, targets, group_id)
    own_drawn = drawn.loc[drawn.security_id.eq(security_id)]
    retained = tuple(int(value) for value in own_drawn.calendar_index)
    states = np.zeros(len(closes), dtype=np.int8)
    for index, t0 in own_drawn.loc[:, ["calendar_index", "t0"]].itertuples(index=False, name=None):
        if not 0 <= int(index) < len(closes) or dates[int(index)] != t0:
            raise ValueError("random draw does not match stock calendar")
        states[int(index)] = 1
    rows = observe_group(episodes, closes, dates, retained, states.tolist(), anchor_regime, security_id, group_id)
    shortfall_years = {int(row.year) for row in quota.loc[quota.security_id.eq(security_id) & quota.shortfall.astype(bool)].itertuples(index=False)}
    for index, row in rows.iterrows():
        t0 = row["anchor_t0"]
        if isinstance(t0, str) and int(t0[:4]) in shortfall_years:
            rows.loc[index, "coverage_status"] = "unknown"
            rows.loc[index, "quota_shortfall"] = True
    return rows, drawn, quota


def _group_registry(target: str, candidates: dict[str, tuple[Atom, ...]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {"C-base-daily": {"control_id": "C-base-daily", "candidate_id": None, "pattern_id": None}}
    for candidate in (None, *candidates):
        identifier = f"{target}:original" if candidate is None else f"{target}:candidate:{candidate}"
        for suffix, control in (("", "pattern"), (":C-52w", "C-52w"), (":C-base-random", "C-base-random")):
            groups[identifier + suffix] = {"pattern_id": target, "candidate_id": candidate, "control_id": control}
    return groups


def _write(output: Path, name: str, frame: pd.DataFrame) -> Path:
    path = output / name
    if not _readable(path, RESULT_COLUMNS[name]):
        _store_frame(path, frame)
    return path


def run_q4(inputs: LocalInputs, target: str, candidates: dict[str, tuple[Atom, ...]], output: Path) -> list[Path]:
    """Reduce one target and its supplied top <=10 candidates; never reselect.

    Target-local narrow projections preserve exact quantiles and random draws
    across a restart, without per-file inventories or hashes. Completed final
    tables are never replaced; the caller retires ``output/_temporary`` only
    after all six final tables have been handed off.
    """
    if target not in PATTERNS or len(candidates) > 10 or any(not isinstance(key, str) or not key.strip() or not atoms for key, atoms in candidates.items()):
        raise ValueError("Q4 requires one approved target and at most ten fixed nonempty candidates")
    complete = completed_results(output)
    if complete is not None:
        return complete
    if not inputs.codes or len(set(inputs.codes)) != len(inputs.codes):
        raise ValueError("Q4 requires a fixed unique stock pool")
    dates = tuple(inputs.calendar.strftime("%Y-%m-%d"))
    codes = tuple(sorted(inputs.codes))
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / "_temporary"
    temporary.mkdir(exist_ok=True)
    progress_path = temporary / "progress.json"
    scope = {
        "schema": "pattern-scan-local-q4-projections.v1",
        "target": target,
        "source_id": inputs.source_id,
        "input_id": inputs.input_id,
        "candidates": [{"candidate_id": key, "atoms": [asdict(atom) for atom in atoms]} for key, atoms in candidates.items()],
        "codes": list(codes),
        "calendar": list(dates),
    }
    progress = read_json(progress_path) if progress_path.exists() else {**scope, "completed": []}
    if any(progress.get(key) != value for key, value in scope.items()):
        raise ValueError("Q4 temporary projection scope differs")
    completed = set(progress["completed"])
    if not completed.issubset(codes):
        raise ValueError("Q4 temporary stock coverage differs")
    groups = _group_registry(target, candidates)
    observations: list[pd.DataFrame] = []
    all_draws: list[pd.DataFrame] = []
    all_quotas: list[pd.DataFrame] = []
    counts: list[pd.DataFrame] = []
    for position, code in enumerate(codes):
        directory = temporary / f"stock-{position:05d}"
        cached = _cached_stock(directory) if code in completed else None
        if cached is not None:
            observations.append(cached["observations"])
            all_draws.append(cached["draws"])
            all_quotas.append(cached["quotas"])
            counts.append(cached["admission"])
            LOGGER.info("Reused Q4 target=%s stock=%s", target, code)
            continue
        stock_observations: list[pd.DataFrame] = []
        stock_draws: list[pd.DataFrame] = []
        stock_quotas: list[pd.DataFrame] = []
        stock_counts: list[dict[str, object]] = []
        security_id = f"TW:{code}"
        tables = inputs.stock(code)
        prices = tables["prices"]
        global_values = inputs.global_values(code)
        if not prices.index.equals(inputs.calendar) or not global_values.index.equals(inputs.calendar):
            raise ValueError("Q4 prices/global values differ from the original calendar")
        closes = [None if pd.isna(value) else float(value) for value in prices.Close]
        reasons = [None if pd.isna(value) else str(value) for value in prices.quality_reason]
        episodes, admission = per_stock_episodes(closes, tables["base_labels"], reasons, security_id, dates=dates)
        admitted = admission_counts(admission)
        for name in ("start_n", "admitted_n", "excluded_n"):
            stock_counts.append({"security_id": security_id, "measure": name, "count": admitted[name]})
        stock_counts.append({"security_id": security_id, "measure": "episode_n", "count": len(episodes)})
        for reason, count in cast(dict[str, int], admitted["exclusion_counts"]).items():
            stock_counts.append({"security_id": security_id, "measure": f"excluded:{reason}", "count": count})
        anchor_mkt = global_values.MKT.fillna("unknown").tolist()
        bound = inputs.bound(target, code)
        daily = pd.DataFrame(bound.daily_groups)
        if "t0" in daily:
            aligned = daily.t0.tolist() == list(dates)
        else:
            aligned = daily.index.equals(inputs.calendar)
        if not aligned:
            raise ValueError("Q4 daily groups differ from the original calendar")
        retained = inputs.group_frame(bound, "pattern:union", 126)
        pool = inputs.group_frame(bound, "C-base-all", 126)
        pool = cast(pd.DataFrame, pool.loc[pool.base_eligible.eq(True)]).copy()
        c52 = inputs.group_frame(bound, "C-52w", 126)
        stock_observations.append(
            daily_base_coverage(episodes, closes, dates, daily["C-base-daily"].tolist(), anchor_mkt, security_id, group_id="C-base-daily")
        )
        candidate_states: dict[str, np.ndarray] = {}
        if candidates:
            common = tables["common_values"].copy()
            for column in global_values:
                common[column] = global_values[column].to_numpy()
            candidate_states = dict(
                daily_candidate_states(
                    target,
                    tables["raw_events"],
                    tables["indicators"],
                    common,
                    tables["pattern_states"][target].to_numpy(dtype=np.int8),
                    security_id=security_id,
                    definition_id=inputs.source_id,
                    input_id=inputs.input_id,
                    candidates=candidates,
                )
            )
        for candidate in (None, *candidates):
            identifier = f"{target}:original" if candidate is None else f"{target}:candidate:{candidate}"
            targets = retained if candidate is None else cast(pd.DataFrame, retained.loc[candidate_membership(retained, candidates[candidate]) == 1])
            states = daily["pattern:union"].tolist() if candidate is None else candidate_states[candidate].tolist()
            stock_observations.append(
                observe_group(episodes, closes, dates, targets.calendar_index.astype(int).tolist(), states, anchor_mkt, security_id, identifier)
            )
            stock_observations.append(
                observe_group(
                    episodes, closes, dates, c52.calendar_index.astype(int).tolist(), daily["C-52w"].tolist(), anchor_mkt, security_id, identifier + ":C-52w"
                )
            )
            random_rows, drawn, quota = random_control_coverage(
                pool,
                targets,
                group_id=identifier + ":C-base-random",
                episodes=episodes,
                closes=closes,
                dates=dates,
                anchor_regime=anchor_mkt,
                security_id=security_id,
            )
            stock_observations.append(random_rows)
            drawn["group_id"], quota["group_id"] = identifier + ":C-base-random", identifier + ":C-base-random"
            stock_draws.append(drawn)
            stock_quotas.append(quota)
        projections = {
            "observations": pd.concat(stock_observations, ignore_index=True),
            "draws": pd.concat(stock_draws, ignore_index=True),
            "quotas": pd.concat(stock_quotas, ignore_index=True),
            "admission": pd.DataFrame(stock_counts),
        }
        directory.mkdir(exist_ok=True)
        for name, frame in projections.items():
            _store_frame(directory / f"{name}.parquet", frame)
        completed.add(code)
        write_progress(progress_path, {**scope, "completed": sorted(completed)})
        observations.append(projections["observations"])
        all_draws.append(projections["draws"])
        all_quotas.append(projections["quotas"])
        counts.append(projections["admission"])
        LOGGER.info("Q4 target=%s stock=%s episodes=%d candidates=%d", target, code, len(episodes), len(candidates))
    all_rows = pd.concat(observations, ignore_index=True) if observations else pd.DataFrame(columns=pd.Index(OBSERVATION_COLUMNS))
    coverage = [row for row in grouped_coverage(all_rows) if row["split"] != "all"]
    empty = pd.DataFrame(columns=pd.Index(OBSERVATION_COLUMNS))
    for group in sorted(set(groups) - set(all_rows.group_id)):
        coverage.extend(
            {"group_id": group, "split": split, "era": era, "mkt": market, **summarize_coverage(empty)}
            for split, era, market in product(("development", "cross-check"), ERAS, MARKETS)
        )
    coverage_frame = pd.DataFrame([{**row, **groups[cast(str, row["group_id"])]} for row in coverage])
    keys = ["group_id", "split", "era", "mkt", "pattern_id", "candidate_id", "control_id"]
    timing_columns = [name for name in coverage_frame if name.startswith(("timing_", "entry_return_", "remaining_return_", "late_"))]
    frames = {
        "coverage.parquet": coverage_frame,
        "timing.parquet": coverage_frame.loc[:, [*keys, "episode_n", *timing_columns]],
        "examples.parquet": select_q4_examples(all_rows),
        "admission-counts.parquet": pd.concat(counts, ignore_index=True),
        "draws.parquet": pd.concat(all_draws, ignore_index=True),
        "quotas.parquet": pd.concat(all_quotas, ignore_index=True),
    }
    paths = [_write(output, name, frame) for name, frame in frames.items()]
    LOGGER.info("Completed Q4 target=%s groups=%d coverage_cells=%d retained_files=%d", target, len(groups), len(coverage_frame), len(paths))
    return paths
