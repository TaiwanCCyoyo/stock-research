"""Versioned continuation of pinned HHHL run_study using sealed daily caches.

The v1 orchestration is intentionally retained here to pin this execution path.
Only cache loading and the parity-tested sparse summary adapter differ. No
original globals are patched and no market calculations or definitions change.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research_core.artifact_store import copy_verified, safe_path, verify_files, write_json
from research_core.hhhl_variants_audit import write_audit_samples
from research_core.hhhl_variants_features import FEATURES, feature_inventory, selection_atoms
from research_core.hhhl_variants_flag_summary import FlagSummaries
from research_core.hhhl_variants_inputs import StockInput
from research_core.hhhl_variants_rates import RateAccumulator
from research_core.hhhl_variants_references import attach_references
from research_core.hhhl_variants_run import (
    COHORTS,
    HORIZONS,
    SPLITS,
    compact,
    cross_section,
    initialize_legacy,
    join_cohort_features,
    legacy_crossings,
    near_high_counts,
    near_high_rows,
    observations,
    stock_features,
    stock_flags,
)
from research_core.hhhl_variants_selection import SelectionEvent, select_candidates
from research_core.hhhl_variants_summary_fast_v1 import FastStudySummaries

LOG = logging.getLogger(__name__)


def cache_inventory(inputs: Any, cache_root: Path, descriptors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Require exactly the complete ordinal inventory before staging any copies."""
    cache_root = safe_path(cache_root)
    expected = {f"daily/{ordinal:04}.parquet" for ordinal in range(1, len(inputs.tables) + 1)}
    if not expected or len(descriptors) != len(expected) or {entry["path"] for entry in descriptors} != expected:
        raise ValueError("daily cache inventory must match every stock ordinal exactly")
    verify_files(cache_root, descriptors)
    inventory = {entry["path"]: entry for entry in descriptors}
    for ordinal, entry in enumerate(inputs.tables, start=1):
        descriptor = inventory[f"daily/{ordinal:04}.parquet"]
        code = entry["security_id"].split(":", 1)[1]
        if descriptor.get("code") != code:
            raise ValueError("daily cache code does not match input inventory")
        rows = descriptor.get("rows")
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
            raise ValueError("daily cache row descriptor must be a nonnegative integer")
    return inventory


def run_cached_study(inputs: Any, staging: Path, cache_root: Path, cache_descriptors: list[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Continue the pinned pipeline from a complete hash-verified daily cache."""
    cached = cache_inventory(inputs, cache_root, cache_descriptors)
    for folder in ("daily", "features", "observations", "flags", "pivots"):
        (staging / folder).mkdir()
    cross_parts = []
    stocks: list[StockInput] = []
    for ordinal in range(1, len(inputs.tables) + 1):
        stock = inputs.stock(ordinal)
        descriptor = cached[f"daily/{ordinal:04}.parquet"]
        if descriptor["code"] != stock.code:
            raise ValueError("daily cache code does not match stock routing")
        copy_verified(cache_root / descriptor["path"], staging / descriptor["path"], descriptor["sha256"])
        daily = pd.read_parquet(staging / descriptor["path"])
        if len(daily) != descriptor["rows"] or len(daily) != len(stock.raw):
            raise ValueError("daily cache rows do not match descriptor/common calendar")
        context = stock.context.copy()
        context["Date"], context["code"], context["calendar_index"] = stock.raw["Date"], stock.code, np.arange(len(daily))
        context["ret120"], context["turnover20"], context["legacy_liquid"] = daily["ret120"], daily["turnover20"], stock.legacy_liquid
        context["is_cnh"] = False
        context.loc[stock.control_indices, "is_cnh"] = True
        cross_parts.append(compact(context))
        stocks.append(stock)
        if ordinal % 100 == 0:
            LOG.info("Variants daily %d/%d", ordinal, len(inputs.tables))
    cross, boundaries = cross_section(pd.concat(cross_parts, ignore_index=True))
    del cross_parts
    boundaries.to_parquet(staging / "daily-boundaries.parquet", index=False)
    cross_groups = cross.groupby("code", sort=False).indices
    summaries, flag_summaries, legacy = FastStudySummaries(), FlagSummaries(), RateAccumulator()
    initialize_legacy(legacy)
    for cohort in COHORTS:
        for split in SPLITS:
            for horizon in HORIZONS:
                summaries.initialize_group(cohort, split, horizon)
    near: Counter[tuple[str, str, str]] = Counter()
    inventory = {(atom.feature_id, atom.bin_id): atom for atom in selection_atoms()}
    selection_events = []
    for stock in stocks:
        daily = pd.read_parquet(staging / f"daily/{stock.ordinal:04}.parquet")
        features = stock_features(stock, daily, cross.iloc[cross_groups[stock.code]].reset_index(drop=True))
        features.to_parquet(staging / f"features/{stock.ordinal:04}.parquet", index=False)
        obs = observations(stock, daily)
        obs.to_parquet(staging / f"observations/{stock.ordinal:04}.parquet", index=False)
        joined = join_cohort_features(obs, features)
        summaries.add_observations(joined)
        for row in joined.loc[joined["cohort_id"].isin(["P-clean", "P-over"]) & joined["horizon"].eq(126)].to_dict(orient="records"):
            atoms = frozenset(inventory[(feature, row[f"{feature}_bin"])] for feature in FEATURES if row[f"{feature}_status"] == "known")
            selection_events.append(SelectionEvent(row["event_id"], stock.code, row["cohort_id"], 126, bool(row["calendar_full"]), row["label"], atoms))
        flags = stock_flags(stock, daily)
        if len(flags):
            compact(flags).to_parquet(staging / f"flags/{stock.ordinal:04}.parquet", index=False)
            all_flags = flags.copy()
            all_flags["cohort_id"] = "P-all"
            flag_summaries.add_flags(pd.concat([flags, all_flags], ignore_index=True))
            legacy_crossings(stock, flags, legacy)
        near_high_counts(stock, daily, near)
        write_json(
            staging / f"pivots/{stock.ordinal:04}.json",
            {"code": stock.code, "low_pivots": stock.low_pivots, "semantics": "frozen-v4-1.5ATR valid rows; indices mapped to common calendar"},
        )
        if stock.ordinal % 100 == 0:
            LOG.info("Variants observations %d/%d", stock.ordinal, len(stocks))
    selected = select_candidates(selection_events, inventory.values())
    selection = {
        "schema_version": "hhhl-variants-selection.v1",
        "selected_atoms": [asdict(atom) for atom in selected.selected_atoms],
        "candidates": [asdict(candidate) for candidate in selected.candidates],
        "development_counts": asdict(selected.development_counts),
        "cross_check_candidate_ids": [candidate.candidate_id for candidate in selected.candidates],
    }
    write_json(staging / "selection.json", selection)
    candidate_summaries = FastStudySummaries(candidates_only=True)
    for cohort in COHORTS:
        for split in SPLITS:
            for horizon in HORIZONS:
                candidate_summaries.initialize_group(cohort, split, horizon, selected.candidates)
    if selected.candidates:
        for stock in stocks:
            obs = pd.read_parquet(staging / f"observations/{stock.ordinal:04}.parquet")
            features = pd.read_parquet(staging / f"features/{stock.ordinal:04}.parquet")
            candidate_summaries.add_observations(join_cohort_features(obs, features), selected.candidates)
            if stock.ordinal % 100 == 0:
                LOG.info("Variants cached candidates %d/%d", stock.ordinal, len(stocks))
    candidate_rows = candidate_summaries.finalize()
    candidate_rows = candidate_rows.loc[candidate_rows["base_row_kind"].isin(["candidate", "Kdistribution"])]
    parts = [summaries.finalize(), candidate_rows, flag_summaries.finalize(), pd.DataFrame(legacy.finalize()), pd.DataFrame(near_high_rows(near))]
    summary = pd.concat([part for part in parts if len(part)], ignore_index=True)
    summary = attach_references(summary, selected.candidates)
    required = {
        "candidate_id": None,
        "landmark": None,
        "riskset_id": None,
        "not_applicable_reason": None,
        "flag_unknown_n": 0,
        "calendar_full_n": 0,
        "hit_n": 0,
        "loss_n": 0,
        "flat_win_n": 0,
        "unknown_n": 0,
        "censored_n": 0,
        "known_security_n": 0,
        "horizon": None,
    }
    for name, default in required.items():
        if name not in summary:
            summary[name] = default
        elif default == 0:
            summary[name] = summary[name].fillna(0)
    for name in summary:
        if name.endswith("_n") and name != "riskset_n":
            summary[name] = summary[name].fillna(0)
    summary["definition_id"] = "hhhl-variants-features.v1"
    write_json(staging / "definitions.json", feature_inventory())
    audit = write_audit_samples(stocks, staging)
    write_json(staging / "audit-digest.json", audit)
    counts_by_stock = pd.concat(
        [
            stock.events.assign(
                code=stock.code, cohort_id=np.where(stock.events["has_old"].eq(True) | stock.events["has_recent_far"].eq(True), "P-over", "P-clean")
            )[["code", "cohort_id", "event_id"]]
            for stock in stocks
        ],
        ignore_index=True,
    )
    counts_by_stock.groupby(["code", "cohort_id"], observed=True).agg(event_n=("event_id", "size")).reset_index().to_parquet(
        staging / "event-counts-by-stock.parquet", index=False
    )
    return summary, selection
