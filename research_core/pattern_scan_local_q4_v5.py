"""One-target Q4 results over the original study inputs, without payload pins.

Only final tables and the promised bounded examples/draw records are written.
The caller owns completed-phase reuse, final-result hashes and the run receipt.
"""

from __future__ import annotations

import logging
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pandas as pd

from research_core.artifact_store import object_digest
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
from research_core.pattern_scan_reporting_v1 import ERAS, MARKETS, candidate_membership
from research_core.pattern_scan_retained_v3 import select_q4_examples

if TYPE_CHECKING:
    from research_core.pattern_scan_local_inputs_v5 import LocalInputs

LOGGER = logging.getLogger(__name__)
QUOTA_COLUMNS = ("security_id", "year", "quota_n", "available_n", "drawn_n", "shortfall_n", "shortfall", "coverage_status", "seed")


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
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False, compression="zstd")
    return path


def run_q4(inputs: LocalInputs, target: str, candidates: dict[str, tuple[Atom, ...]], output: Path) -> list[Path]:
    """Reduce one target and its supplied top <=10 candidates; never reselect.

    All stock/event detail stays in memory, limited to this target. Exact
    quantiles use the narrow observations until final reduction. No ancestor
    verification, intermediate inventory or permanent detailed copy is added.
    """
    if target not in PATTERNS or len(candidates) > 10 or any(not isinstance(key, str) or not key.strip() or not atoms for key, atoms in candidates.items()):
        raise ValueError("Q4 requires one approved target and at most ten fixed nonempty candidates")
    if not inputs.codes or len(set(inputs.codes)) != len(inputs.codes):
        raise ValueError("Q4 requires a fixed unique stock pool")
    if output.exists():
        raise FileExistsError(f"Q4 output already exists: {output}")
    dates = tuple(inputs.calendar.strftime("%Y-%m-%d"))
    groups = _group_registry(target, candidates)
    observations: list[pd.DataFrame] = []
    all_draws: list[pd.DataFrame] = []
    all_quotas: list[pd.DataFrame] = []
    counts: list[dict[str, object]] = []
    for code in sorted(inputs.codes):
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
            counts.append({"security_id": security_id, "measure": name, "count": admitted[name]})
        counts.append({"security_id": security_id, "measure": "episode_n", "count": len(episodes)})
        for reason, count in cast(dict[str, int], admitted["exclusion_counts"]).items():
            counts.append({"security_id": security_id, "measure": f"excluded:{reason}", "count": count})
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
        observations.append(daily_base_coverage(episodes, closes, dates, daily["C-base-daily"].tolist(), anchor_mkt, security_id, group_id="C-base-daily"))
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
            observations.append(
                observe_group(episodes, closes, dates, targets.calendar_index.astype(int).tolist(), states, anchor_mkt, security_id, identifier)
            )
            observations.append(
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
            observations.append(random_rows)
            drawn["group_id"], quota["group_id"] = identifier + ":C-base-random", identifier + ":C-base-random"
            all_draws.append(drawn)
            all_quotas.append(quota)
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
    output.mkdir(parents=True)
    frames = {
        "coverage.parquet": coverage_frame,
        "timing.parquet": coverage_frame.loc[:, [*keys, "episode_n", *timing_columns]],
        "examples.parquet": select_q4_examples(all_rows),
        "admission-counts.parquet": pd.DataFrame(counts),
        "draws.parquet": pd.concat(all_draws, ignore_index=True),
        "quotas.parquet": pd.concat(all_quotas, ignore_index=True),
    }
    paths = [_write(output, name, frame) for name, frame in frames.items()]
    LOGGER.info("Completed Q4 target=%s groups=%d coverage_cells=%d retained_files=%d", target, len(groups), len(coverage_frame), len(paths))
    return paths
