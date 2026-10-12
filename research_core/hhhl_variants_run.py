"""One fixed, additive HHHL variants pipeline over verified frozen inputs."""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import uuid
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow

from research_core.artifact_store import describe_file, file_digest, object_digest, publish_noreplace, safe_path, write_json
from research_core.hhhl_variants_audit import write_audit_samples
from research_core.hhhl_variants_daily import bin_columns, calculate_daily_features
from research_core.hhhl_variants_features import FEATURES, feature_inventory, selection_atoms
from research_core.hhhl_variants_flag_summary import FlagSummaries
from research_core.hhhl_variants_inputs import FrozenInputs, StockInput
from research_core.hhhl_variants_paths import event_flag_records, outcomes_for_closes
from research_core.hhhl_variants_pattern import pattern_feature_values
from research_core.hhhl_variants_query import summary_transport
from research_core.hhhl_variants_rates import RateAccumulator
from research_core.hhhl_variants_references import attach_references
from research_core.hhhl_variants_selection import SelectionEvent, select_candidates, split_for_code
from research_core.hhhl_variants_summary import StudySummaries

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
TASK = "tasks/20261012-hhhl-v4-variants"
HORIZONS = (126, 252)
LANDMARKS = (5, 10, 20, 40)
COHORTS = ("P-clean", "P-over", "P-all", "C-nh", "C-52w", "C-base")
SPLITS = ("development", "cross-check")
FLAGS = ("X1", "X2", "X3", "X4", "X5_MA20", "X5_MA60", "X6_10", "X6_15")
APPROVED_MISSION_MERGE = "fcda359370cd81594451839d4e79e2216cbce255"
UNKNOWN_INDUSTRIES = frozenset(("", "unknown", "unclassified", "(missing)", "未分類", "未分类", "None", "nan"))


def compact(frame: pd.DataFrame) -> pd.DataFrame:
    """Categorical text compresses local daily tables; numeric precision stays 64 bit."""
    result = frame.copy()
    for name in result.columns:
        if result[name].dtype == object and not name.endswith(("levels", "sequence")):
            if name.endswith(("_bin", "_status", "_reason")) or name in {
                "code",
                "cohort_id",
                "split_id",
                "label",
                "industry_ref",
                "regime",
                "flag_id",
                "flag_state",
                "raw_flag_state",
            }:
                result[name] = result[name].astype("category")
    return result


def cross_section(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fixed H/K3 and eleven-calendar-day other-code C-nh membership."""
    result = frame.copy()
    eligible = result["base_eligible"].eq(True)
    rank_mask = eligible & np.isfinite(result["ret120"])
    result["H"] = np.nan
    result.loc[rank_mask, "H"] = result.loc[rank_mask].groupby("calendar_index")["ret120"].rank(method="average", pct=True) * 100
    result["H_applicable"] = eligible
    result["H_unknown_reason"] = pd.Series(None, index=result.index, dtype=object)
    result.loc[eligible & ~rank_mask, "H_unknown_reason"] = np.where(
        result.loc[eligible & ~rank_mask, "calendar_index"] < 120, "warmup_insufficient", "warmup_insufficient_after_gap"
    )
    amount_mask = eligible & result["legacy_liquid"].eq(True) & np.isfinite(result["turnover20"])
    grouped = result.loc[amount_mask].groupby("calendar_index")["turnover20"]
    cutpoints = grouped.quantile([1 / 3, 2 / 3], interpolation="linear").unstack()
    q1 = result["calendar_index"].map(cutpoints.get(1 / 3, pd.Series(dtype=float)))
    q2 = result["calendar_index"].map(cutpoints.get(2 / 3, pd.Series(dtype=float)))
    result["K3"] = pd.Series(None, index=result.index, dtype=object)
    result.loc[amount_mask, "K3"] = np.where(
        result.loc[amount_mask, "turnover20"] <= q1[amount_mask], "low", np.where(result.loc[amount_mask, "turnover20"] <= q2[amount_mask], "middle", "high")
    )
    result["K3_applicable"] = eligible & result["legacy_liquid"].eq(True)
    result["K3_unknown_reason"] = pd.Series(None, index=result.index, dtype=object)
    result.loc[result["K3_applicable"] & ~amount_mask, "K3_unknown_reason"] = "warmup_insufficient_after_gap"
    codes = {code: index for index, code in enumerate(sorted(result["code"].unique()))}
    result["J"] = np.nan
    n = int(result["calendar_index"].max()) + 1 if len(result) else 0
    valid_industry = result["industry_ref"].notna() & ~result["industry_ref"].astype(str).isin(list(UNKNOWN_INDUSTRIES))
    result["J_unknown_reason"] = pd.Series(None, index=result.index, dtype=object)
    result.loc[~valid_industry, "J_unknown_reason"] = "industry_unclassified"
    result.loc[valid_industry & result["calendar_index"].lt(10), "J_unknown_reason"] = "warmup_insufficient"
    for _, members in result.loc[valid_industry].groupby("industry_ref", observed=True, sort=False):
        daily_bits = [0] * n
        signals = members.loc[members["is_cnh"].eq(True)]
        for row in signals[["calendar_index", "code"]].itertuples(index=False):
            daily_bits[int(row.calendar_index)] |= 1 << codes[row.code]
        windows = [0] * n
        for t in range(10, n):
            for bits in daily_bits[t - 10 : t + 1]:
                windows[t] |= bits
        values = [
            np.nan if t < 10 else windows[t].bit_count() - bool(windows[t] & (1 << codes[code]))
            for t, code in members[["calendar_index", "code"]].itertuples(index=False, name=None)
        ]
        result.loc[members.index, "J"] = values
    dates = result.groupby("calendar_index")["Date"].first()
    boundaries = pd.DataFrame({
        "Date": dates,
        "q1": cutpoints.get(1 / 3),
        "q2": cutpoints.get(2 / 3),
        "k3_security_n": grouped.size(),
        "h_security_n": result.loc[rank_mask].groupby("calendar_index").size(),
    }).reset_index()
    return result, boundaries


def stock_features(stock: StockInput, daily: pd.DataFrame, cross: pd.DataFrame) -> pd.DataFrame:
    values = daily.copy()
    for feature in ("H", "J", "K3"):
        values[feature] = cross[feature].to_numpy()
        for suffix in ("_applicable", "_unknown_reason"):
            if feature + suffix in cross:
                values[feature + suffix] = cross[feature + suffix].to_numpy()
    values["I"] = stock.context["regime"].to_numpy()
    for feature, definition in FEATURES.items():
        if definition.pattern_only:
            values[feature] = np.nan if not definition.categories else pd.Series(None, index=values.index, dtype=object)
            values[f"{feature}_applicable"] = False
    if len(stock.events):
        pattern = pattern_feature_values(
            stock.events, pd.DatetimeIndex(stock.raw["Date"]), stock.adjusted["Low"].to_numpy(float), stock.adjusted["Close"].to_numpy(float)
        )
        positions = stock.events["calendar_index"].to_numpy(int)
        for name in pattern:
            if name not in values:
                values[name] = pd.Series(None, index=values.index, dtype=object)
            values.loc[positions, name] = pattern[name].to_numpy()
        for feature, definition in FEATURES.items():
            if definition.pattern_only and feature != "A":
                values.loc[positions, f"{feature}_applicable"] = True
    bins = bin_columns(values)
    bins.loc[~values["H_applicable"], "H_reason"] = "outside_eligible_universe"
    bins.loc[~values["K3_applicable"], "K3_reason"] = "outside_daily_liquid_universe"
    result = pd.concat([values.loc[:, list(FEATURES)], bins], axis=1)
    result.insert(0, "Date", stock.raw["Date"].to_numpy())
    result.insert(0, "calendar_index", np.arange(len(result)))
    result.insert(0, "code", stock.code)
    result["event_id"] = [f"day:{stock.security_id}:{date:%Y-%m-%d}" for date in pd.to_datetime(result["Date"])]
    if len(stock.events):
        result.loc[stock.events["calendar_index"].to_numpy(int), "event_id"] = stock.events["event_id"].to_numpy()
    return compact(result)


def join_cohort_features(obs: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """Pattern values remain scoped to P even when controls share its date."""
    joined = obs.merge(features.drop(columns=["code", "Date", "event_id"]), on="calendar_index", how="left", validate="many_to_one")
    controls = joined["cohort_id"].astype(str).str.startswith("C-")
    for feature, definition in FEATURES.items():
        if definition.pattern_only:
            for suffix in ("bin", "status", "reason"):
                name = f"{feature}_{suffix}"
                joined[name] = joined[name].astype(object)
            joined.loc[controls, feature] = None
            joined.loc[controls, f"{feature}_bin"] = None
            joined.loc[controls, f"{feature}_status"] = "not_applicable"
            joined.loc[controls, f"{feature}_reason"] = "outside_feature_cohort"
    return joined


def observations(stock: StockInput, daily: pd.DataFrame) -> pd.DataFrame:
    n = len(stock.raw)
    dates = pd.to_datetime(stock.raw["Date"])
    eligible = stock.context["base_eligible"].eq(True).to_numpy()
    c52 = (
        eligible
        & daily["D"].ge(1).to_numpy()
        & daily["prior_volume20"].gt(0).to_numpy()
        & (stock.raw["VolumeLots"].to_numpy(float) >= 1.5 * daily["prior_volume20"].to_numpy(float))
    )
    events = stock.events
    clean = events.loc[~(events["has_old"].eq(True) | events["has_recent_far"].eq(True))]
    over = events.loc[events["has_old"].eq(True) | events["has_recent_far"].eq(True)]
    groups = {
        "C-base": np.flatnonzero(eligible),
        "C-52w": np.flatnonzero(c52),
        "C-nh": stock.control_indices,
        "P-clean": clean["calendar_index"].to_numpy(int),
        "P-over": over["calendar_index"].to_numpy(int),
        "P-all": events["calendar_index"].to_numpy(int),
    }
    id_by_position = dict(zip(events["calendar_index"], events["event_id"], strict=True))
    pieces = []
    for horizon in HORIZONS:
        outcomes = outcomes_for_closes(stock.adjusted["Close"].to_numpy(float), horizon)
        for cohort, positions in groups.items():
            selected = outcomes.iloc[positions].copy()
            selected["calendar_index"] = positions
            selected["Date"] = dates.iloc[positions].to_numpy()
            selected["year"] = dates.iloc[positions].dt.year.to_numpy()
            selected["code"], selected["cohort_id"], selected["split_id"], selected["horizon"] = stock.code, cohort, split_for_code(stock.code), horizon
            selected["event_id"] = [
                id_by_position[t] if cohort.startswith("P-") else f"{cohort}:{stock.security_id}:{dates.iloc[t]:%Y-%m-%d}" for t in positions
            ]
            pieces.append(selected)
    result = pd.concat(pieces, ignore_index=True)
    if result.duplicated(["cohort_id", "event_id", "horizon"]).any():
        raise ValueError("duplicate observation identities")
    if len(stock.raw) != n:
        raise ValueError("input mutated while constructing observations")
    return compact(result)


def stock_flags(stock: StockInput, daily: pd.DataFrame) -> pd.DataFrame:
    records = []
    dates = pd.DatetimeIndex(stock.raw["Date"])
    close = stock.adjusted["Close"].to_numpy(float)
    for event in stock.events.to_dict(orient="records"):
        t0 = int(event["calendar_index"])
        restart = dates.get_indexer([pd.Timestamp(event["restart_date"])])[0]
        if restart < 0:
            raise ValueError("original restart outside common calendar")
        cohort = "P-over" if event["has_old"] or event["has_recent_far"] else "P-clean"
        paths = event_flag_records(
            close,
            daily["ma20"].to_numpy(float),
            daily["ma60"].to_numpy(float),
            t0,
            float(event["Z2"]),
            float(event["hz_top"]),
            float(stock.adjusted["Low"].iloc[restart]),
            stock.low_pivots,
        )
        for record in paths:
            records.append({
                **record,
                "event_id": event["event_id"],
                "code": stock.code,
                "cohort_id": cohort,
                "split_id": split_for_code(stock.code),
                "year": cast(pd.Timestamp, dates[t0]).year,
                "calendar_index": t0,
                "Date": dates[t0],
            })
    return pd.DataFrame(records)


def legacy_crossings(stock: StockInput, flags: pd.DataFrame, accumulator: RateAccumulator) -> None:
    close = stock.adjusted["Close"].to_numpy(float)
    events = {event["event_id"]: event for event in stock.events.to_dict(orient="records")}
    for row in flags.loc[flags["flag_id"].eq("X1") & flags["scope"].eq("landmark")].to_dict(orient="records"):
        event = events[row["event_id"]]
        for age in ("old", "recent_far"):
            levels = [float(line["level"]) for line in json.loads(event["bonus_levels"]) if line["age"] == age]
            prefix = close[row["calendar_index"] + 1 : row["calendar_index"] + row["landmark"] + 1]
            state = "triggered" if levels and any((prefix > level).any() for level in levels) else "all_false" if levels else "unknown"
            key = (row["cohort_id"], row["split_id"], row["horizon"], row["landmark"], age, state)
            metadata = {
                "row_kind": "legacy_cross",
                "cohort_id": row["cohort_id"],
                "split_id": row["split_id"],
                "horizon": row["horizon"],
                "landmark": row["landmark"],
                "flag_id": f"legacy_{age}",
                "flag_state": state,
                "riskset_id": "legacy_active",
                "feature_price_basis": "frozen_v4_factor",
                "not_applicable_reason": "no_bonus_lines" if row["cohort_id"] == "P-clean" else None,
            }
            counts = {"excluded_riskset_n": int(row["legacy_state"] != "active"), "not_applicable_n": int(row["legacy_state"] == "active" and not levels)}
            known_codes = []
            if row["legacy_state"] == "active" and levels:
                full = bool(row["calendar_full"])
                label = row["label"]
                counts.update(
                    calendar_full_n=int(full),
                    hit_n=int(full and label == "hit"),
                    loss_n=int(full and label == "loss"),
                    flat_win_n=int(full and label == "flat-win"),
                    unknown_n=int(full and label == "unknown"),
                    censored_n=int(not full),
                    censored_hit_n=int(not full and label == "hit"),
                    censored_unknown_n=int(not full and label != "hit"),
                )
                known_codes = [stock.code] if full and label != "unknown" else []
            accumulator.add(key, metadata, row["year"], counts, known_codes)


def initialize_legacy(accumulator: RateAccumulator) -> None:
    for cohort in ("P-clean", "P-over"):
        for split in SPLITS:
            for horizon in HORIZONS:
                for landmark in LANDMARKS:
                    for age in ("old", "recent_far"):
                        for state in ("triggered", "all_false", "unknown"):
                            key = (cohort, split, horizon, landmark, age, state)
                            metadata = {
                                "row_kind": "legacy_cross",
                                "cohort_id": cohort,
                                "split_id": split,
                                "horizon": horizon,
                                "landmark": landmark,
                                "flag_id": f"legacy_{age}",
                                "flag_state": state,
                                "riskset_id": "legacy_active",
                                "feature_price_basis": "frozen_v4_factor",
                                "not_applicable_reason": "no_bonus_lines" if cohort == "P-clean" else None,
                            }
                            accumulator.add(key, metadata, 2019, {})


def near_high_counts(stock: StockInput, daily: pd.DataFrame, accumulator: Counter[tuple[str, str, str]]) -> None:
    clean = stock.events.loc[~(stock.events["has_old"].eq(True) | stock.events["has_recent_far"].eq(True)), "calendar_index"].to_numpy(int)
    ratios = daily["D"].to_numpy(float)[clean]
    split = split_for_code(stock.code)
    for split_id in (split, "pooled"):
        for bin_id, threshold in (("ge100", 1.0), ("ge095", 0.95)):
            accumulator[("P-clean", split_id, f"{bin_id}:all")] += len(clean)
            accumulator[("P-clean", split_id, f"{bin_id}:known")] += int(np.isfinite(ratios).sum())
            accumulator[("P-clean", split_id, f"{bin_id}:matched")] += int((np.isfinite(ratios) & (ratios >= threshold)).sum())
        c52 = np.flatnonzero(
            stock.context["base_eligible"].eq(True).to_numpy()
            & daily["D"].ge(1).to_numpy()
            & daily["prior_volume20"].gt(0).to_numpy()
            & (stock.raw["VolumeLots"].to_numpy(float) >= 1.5 * daily["prior_volume20"].to_numpy(float))
        )
        accumulator[("C-52w", split_id, "clean_overlap:all")] += len(c52)
        accumulator[("C-52w", split_id, "clean_overlap:known")] += len(c52)
        accumulator[("C-52w", split_id, "clean_overlap:matched")] += len(set(c52) & set(clean))


def near_high_rows(counts: Counter[tuple[str, str, str]]) -> list[dict[str, Any]]:
    rows = []
    for cohort, bins in (("P-clean", ("ge100", "ge095")), ("C-52w", ("clean_overlap",))):
        for split in (*SPLITS, "pooled"):
            for bin_id in bins:
                total, known, matched = (counts[(cohort, split, f"{bin_id}:{name}")] for name in ("all", "known", "matched"))
                rows.append({
                    "row_kind": "near_high",
                    "base_row_kind": "near_high",
                    "cohort_id": cohort,
                    "split_id": split,
                    "feature_id": "D",
                    "bin_id": bin_id,
                    "feature_price_basis": "frozen_v4_factor",
                    "near_high_all_n": total,
                    "near_high_known_n": known,
                    "near_high_unknown_n": total - known,
                    "near_high_matched_n": matched,
                    "near_high_rate": matched / known if known else None,
                    "near_high_lower": matched / total if total else None,
                    "near_high_upper": (matched + total - known) / total if total else None,
                })
    return rows


def implementation_receipt(approved_merge: str) -> dict[str, Any]:
    if approved_merge != APPROVED_MISSION_MERGE:
        raise ValueError("this version requires the verified PR7 mission merge")
    if subprocess.run(["git", "merge-base", "--is-ancestor", approved_merge, "HEAD"], cwd=ROOT, capture_output=True).returncode:
        raise ValueError("approved mission merge is not in this task branch")
    if subprocess.check_output(["git", "status", "--porcelain", "--ignore-submodules=all"], cwd=ROOT, text=True).strip():
        raise ValueError("commit the fixed implementation before market calculation")
    paths = [
        *ROOT.glob("research_core/hhhl_variants_*.py"),
        ROOT / "research_core/artifact_store.py",
        ROOT / "research_core/hhhl_v4_source.py",
        ROOT / "research_core/derived_features.py",
        ROOT / "research_core/feature_atlas_dataset.py",
        ROOT / "research_core/feature_atlas_io.py",
        ROOT / "research_core/jobs.py",
        ROOT / "research_core/patterns/hhhl/source.py",
        ROOT / "scripts/run_hhhl_variants.py",
    ]
    return {
        "approved_mission_merge": approved_merge,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "code_sha256": {path.relative_to(ROOT).as_posix(): file_digest(path) for path in paths},
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "pyarrow": pyarrow.__version__,
        "source_boundary": "new interpreter; isolated nonexistent pycache prefix; bytecode writes disabled",
    }


def run_study(inputs: Any, staging: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Same pipeline accepts an invented bundle in integration tests."""
    for folder in ("daily", "features", "observations", "flags", "pivots"):
        (staging / folder).mkdir()
    cross_parts = []
    stocks: list[StockInput] = []
    for ordinal in range(1, len(inputs.tables) + 1):
        stock = inputs.stock(ordinal)
        daily = calculate_daily_features(stock.raw, stock.adjusted, stock.legacy_vx, stock.legacy_liquid)
        compact(daily).to_parquet(staging / f"daily/{ordinal:04}.parquet", index=False)
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
    summaries, flag_summaries, legacy = StudySummaries(), FlagSummaries(), RateAccumulator()
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
    candidate_summaries = StudySummaries()
    for cohort in COHORTS:
        for split in SPLITS:
            for horizon in HORIZONS:
                candidate_summaries.initialize_group(cohort, split, horizon, selected.candidates)
    if selected.candidates:
        for stock in stocks:
            obs = pd.read_parquet(staging / f"observations/{stock.ordinal:04}.parquet")
            features = pd.read_parquet(staging / f"features/{stock.ordinal:04}.parquet")
            candidate_summaries.add_observations(join_cohort_features(obs, features), selected.candidates)
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


def execute(primary: Path, pins_path: Path, publication: Path, approved_merge: str) -> dict[str, Any]:
    execution = implementation_receipt(approved_merge)
    final = safe_path(primary / TASK / "datasets/hhhl-v4-variants-01")
    if final.exists() or publication.exists():
        raise FileExistsError("fixed dataset/publication already exists; do not run or replace it")
    final.parent.mkdir(parents=True, exist_ok=True)
    lock = safe_path(final.parent / f".{final.name}.lock")
    write_json(lock, {"pid": os.getpid(), "execution": execution, "owner": "01a12bfc-b535-7352-bef7-68fe3a56901e"})
    staging = safe_path(final.parent / f".staging-{final.name}-{uuid.uuid4().hex}")
    staging.mkdir()
    write_json(staging / "execution-start.json", execution)
    inputs = FrozenInputs(primary, pins_path)
    summary, selection = run_study(inputs, staging)
    summary["input_dataset_id"] = "hhhl-v4-descriptive-01"
    summary["input_manifest_sha256"] = inputs.pins["v4_bulk"]["manifest_sha256"]
    inputs.verify_after()
    if any(file_digest(ROOT / relative) != digest for relative, digest in execution["code_sha256"].items()):
        raise ValueError("implementation changed during fixed calculation")
    summary.to_parquet(staging / "summary.parquet", index=False, compression="zstd", compression_level=19)
    artifacts = []
    for path in sorted(staging.rglob("*")):
        if path.is_file():
            descriptor = describe_file(staging, path)
            if path.suffix == ".parquet":
                import pyarrow.parquet as pq

                descriptor["rows"] = pq.ParquetFile(path).metadata.num_rows
            if path.parent.name in {"features", "observations", "flags", "daily", "pivots"}:
                ordinal = int(path.stem)
                descriptor["code"] = inputs.tables[ordinal - 1]["security_id"].split(":", 1)[1]
            artifacts.append(descriptor)
    identity = {
        "input_pins_sha256": file_digest(pins_path),
        "execution": execution,
        "mission_sha256": file_digest(ROOT / TASK / "mission.md"),
        "definition_id": "hhhl-variants-features.v1",
    }
    dataset_id = "hhhl-variants-" + object_digest(identity)
    manifest = {
        "schema_version": "hhhl-variants-dataset.v1",
        "dataset_id": dataset_id,
        "identity": identity,
        "artifacts": artifacts,
        "summary_rows": len(summary),
        "candidate_n": len(selection["candidates"]),
    }
    write_json(staging / "manifest.json", manifest)
    publish_noreplace(staging, final)
    publication = safe_path(publication)
    publication.parent.mkdir(parents=True, exist_ok=True)
    pub_stage = publication.parent / f".staging-{publication.name}-{uuid.uuid4().hex}"
    pub_stage.mkdir()
    contents, descriptor = summary_transport((final / "summary.parquet").read_bytes(), len(summary))
    for name, data in contents.items():
        with safe_path(pub_stage / name).open("xb") as stream:
            stream.write(data)
    receipt = {
        "schema_version": "hhhl-variants-publication.v1",
        "dataset_id": dataset_id,
        "summary": descriptor,
        "local_dataset": {"path": str(final), "manifest_sha256": file_digest(final / "manifest.json")},
        "execution": execution,
        "summary_row_kind_counts": {str(kind): int(count) for kind, count in summary.groupby("row_kind").size().items()},
        "summary_base_row_kind_counts": {str(kind): int(count) for kind, count in summary.groupby("base_row_kind").size().items()},
    }
    write_json(pub_stage / "receipt.json", receipt)
    publish_noreplace(pub_stage, publication)
    lock.unlink()
    LOG.info("Fixed variants published dataset=%s summary_rows=%d", dataset_id, len(summary))
    return receipt
