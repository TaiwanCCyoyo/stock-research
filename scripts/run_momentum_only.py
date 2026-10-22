"""Momentum-only study runner (tasks/20261021-momentum-only-doubling/mission.md).

    uv run python -m scripts.run_momentum_only stocks --work <dir> --generation <id>
    uv run python -m scripts.run_momentum_only parity --work <dir>

`stocks` computes each PR17 stock's eligibility, C-52w, local atoms, ret120 and the
12 labels at the PR17 cutoff and calendar, one `.npz` per code under `<work>/stocks/`
(intermediate, resumable, not hashed). `parity` is the mission's gate: it recounts
C-base-daily and C-52w-daily at 2x H126/H252 (split=all, era=all, full) and compares
known/hit/loss with PR17's stored Q1 rows.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from research_core import count_cube_v1 as cube
from research_core import momentum_only_v1 as study
from research_core.artifact_store import publish_new_directory
from research_core.maintained_adjusted_daily import current_generation, read_adjusted_daily
from research_core.run_receipt import InputSpec, code_identity, fingerprint_inputs, write_run_receipt

LOGGER = logging.getLogger(__name__)
CUTOFF = study.CUTOFF
PINS = study.PR17_PINS
PR17_Q1 = Path("tasks/20261013-pattern-scan/web-report/data/tables/B1-summary.parquet")
PR17_PREPARATION = study.PR17_UNIVERSE
pr17_calendar = study.pr17_calendar
pr17_codes = study.pr17_codes
_years = study.calendar_years


def _save(path: Path, stock: study.StockDaily) -> None:
    arrays: dict[str, Any] = {"eligible": stock.eligible, "jump": stock.jump, "c52w": stock.c52w, "ret120": stock.ret120}
    arrays.update({f"atom_{name}": values for name, values in stock.atoms.items()})
    arrays.update({f"label_{h}_{t:g}": values for (h, t), values in stock.labels.items()})
    arrays.update({f"main_{h}_{t:g}": values for (h, t), values in stock.main_eligible.items()})
    arrays.update({f"full_{h}": values for h, values in stock.calendar_full.items()})
    staging = path.with_name(path.stem + ".partial.npz")
    np.savez(staging, **arrays)
    staging.replace(path)


def load(path: Path, code: str) -> study.StockDaily:
    with np.load(path) as data:
        return study.StockDaily(
            code=code,
            split=study.split_for_code(code),
            eligible=data["eligible"],
            jump=data["jump"],
            c52w=data["c52w"],
            atoms={name: data[f"atom_{name}"] for name in study.LOCAL_ATOMS},
            ret120=data["ret120"],
            labels={(h, t): data[f"label_{h}_{t:g}"] for h in study.HORIZONS for t in study.TARGETS},
            main_eligible={(h, t): data[f"main_{h}_{t:g}"] for h in study.HORIZONS for t in study.TARGETS},
            calendar_full={h: data[f"full_{h}"] for h in study.HORIZONS},
        )


def run_stocks(work: Path, generation: str) -> None:
    calendar, codes = pr17_calendar(), pr17_codes()
    directory = work / "stocks"
    directory.mkdir(parents=True, exist_ok=True)
    identity = {"generation": generation, "definition": study.DEFINITION_ID, "code": code_identity(REPO_ROOT)}
    started_path = work / "stocks-started.json"
    if started_path.exists():
        previous = json.loads(started_path.read_text(encoding="utf-8"))
        if previous != identity:
            raise SystemExit(f"{work} was started with {previous}; resume only with the same generation, definition and clean code, or use a new --work")
    else:
        if any(directory.iterdir()):
            raise SystemExit(f"{directory} holds stock files without a start record; use a new --work")
        started_path.write_text(json.dumps(identity, indent=2), encoding="utf-8")
    started = time.monotonic()
    done = 0
    for position, code in enumerate(codes, 1):
        target = directory / f"{code}.npz"
        if target.exists():
            continue
        prices, _ = read_adjusted_daily("reference_factor_adjusted", codes=[code], as_of=CUTOFF, calendar=calendar, generation=generation)
        prepared = prices.drop(columns="Code").set_index("Date")
        _save(target, study.stock_daily(code, prepared))
        done += 1
        if position % 100 == 0:
            LOGGER.info("Stocks %d/%d (%d new) %.0fs", position, len(codes), done, time.monotonic() - started)
    (work / "stocks.json").write_text(
        json.dumps(
            {"generation": generation, "cutoff": CUTOFF, "codes": len(codes), "new": done, "wall_seconds": round(time.monotonic() - started, 1)}, indent=2
        ),
        encoding="utf-8",
    )
    LOGGER.info("Stock phase complete codes=%d new=%d", len(codes), done)


def _pr17_rows() -> pd.DataFrame:
    rows = pq.read_table(PR17_Q1).to_pandas()
    keep = (
        rows.control_id.isin(["C-base-daily", "C-52w-daily"])
        & rows.cohort_id.eq("union")
        & rows.split.eq("all")
        & rows.era.eq("all")
        & rows.mkt.eq("all")
        & rows.row_kind.eq("full")
    )
    return rows.loc[keep, ["control_id", "horizon", "known_n", "hit_n", "loss_n", "hit_rate", "loss_rate"]].reset_index(drop=True)


def run_parity(work: Path) -> dict[str, Any]:
    calendar, codes = pr17_calendar(), pr17_codes()
    year_index = np.asarray(_years(calendar) - study.FIRST_YEAR, dtype=np.intp)
    n_years = int(year_index.max()) + 1
    columns = [study.METRICS.index(name) for name in ("known_n", "hit_n", "loss_n")]
    totals = {(group, horizon): np.zeros(3, dtype=np.int64) for group in study.BASELINE_LOOKBACK for horizon in (126, 252)}
    for code in codes:
        stock = load(work / "stocks" / f"{code}.npz", code)
        for group, members in (("C-base-daily", np.ones(len(calendar), dtype=bool)), ("C-52w-daily", stock.c52w)):
            counts = study.group_counts(stock, members, lookback=study.BASELINE_LOOKBACK[group], year_index=year_index, n_years=n_years)
            for horizon in (126, 252):
                totals[group, horizon] += counts[study.LABELS.index((horizon, 2.0))].sum(axis=0)[columns]
    ours = pd.DataFrame([{"group": g, "horizon": h, "known_n": int(v[0]), "hit_n": int(v[1]), "loss_n": int(v[2])} for (g, h), v in totals.items()])
    reference = _pr17_rows().rename(columns={"control_id": "group", "hit_rate": "hit_rate_pr17", "loss_rate": "loss_rate_pr17"})
    merged = ours.merge(reference, on=["group", "horizon"], suffixes=("", "_pr17"), validate="one_to_one")
    merged["hit_rate"] = merged.hit_n / merged.known_n
    merged["loss_rate"] = merged.loss_n / merged.known_n
    merged["known_rel_diff"] = (merged.known_n - merged.known_n_pr17).abs() / merged.known_n_pr17
    merged["hit_pp_diff"] = (merged.hit_rate - merged.hit_rate_pr17).abs() * 100
    merged["loss_pp_diff"] = (merged.loss_rate - merged.loss_rate_pr17).abs() * 100
    exact = bool((merged[["known_n", "hit_n", "loss_n"]].to_numpy() == merged[["known_n_pr17", "hit_n_pr17", "loss_n_pr17"]].to_numpy()).all())
    within = bool(((merged.known_rel_diff <= 0.01) & (merged.hit_pp_diff <= 0.2) & (merged.loss_pp_diff <= 0.2)).all())
    verdict = "exact" if exact else "within_tolerance" if within else "stop"
    report = {"verdict": verdict, "cells": merged.to_dict(orient="records")}
    (work / "parity_check.json").write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    merged.to_parquet(work / "parity_check.parquet", index=False)
    LOGGER.info("Parity verdict=%s", verdict)
    return report


ERAS = {"all": (2010, 2026), "2010-2012": (2010, 2012), "2013-2018": (2013, 2018), "2019+": (2019, 2026)}
SPLITS = ("all", "development", "cross-check")
REPS = 2000
SEEDS = {"stock": 20261021, "two_way": 20261022}
FOCUS = ("A1&A2:daily", "LEAD_B1:daily")


def _comparison(row: dict[str, Any], base: dict[str, Any] | None, prefix: str) -> dict[str, Any]:
    empty = {f"hit_ratio_vs_{prefix}": None, f"hit_diff_vs_{prefix}": None, f"loss_diff_vs_{prefix}": None}
    if base is None or row["hit_rate"] is None or base["hit_rate"] is None:
        return empty
    return {
        f"hit_ratio_vs_{prefix}": row["hit_rate"] / base["hit_rate"] if base["hit_rate"] else None,
        f"hit_diff_vs_{prefix}": row["hit_rate"] - base["hit_rate"],
        f"loss_diff_vs_{prefix}": row["loss_rate"] - base["loss_rate"],
    }


def _slice_rows(key: dict[str, Any], sliced: np.ndarray, years: np.ndarray, split_codes: list[str]) -> list[dict[str, Any]]:
    rows = [{**key, "row_kind": "full", "removed": None, **cube.summarize(sliced, study.METRICS)}]
    year = cube.best_year(sliced, study.METRICS)
    keep_years = np.ones(sliced.shape[1], dtype=bool)
    if year is not None:
        keep_years[year] = False
    removed_year = None if year is None else str(years[year])
    rows.append({**key, "row_kind": "drop_best_year", "removed": removed_year, **cube.summarize(sliced, study.METRICS, years=keep_years)})
    best = cube.best_stock(sliced, study.METRICS, split_codes)
    keep_stocks = np.ones(sliced.shape[0], dtype=bool)
    if best is not None:
        keep_stocks[best] = False
    removed_stock = None if best is None else split_codes[best]
    rows.append({**key, "row_kind": "drop_best_stock", "removed": removed_stock, **cube.summarize(sliced, study.METRICS, stocks=keep_stocks)})
    return rows


def run_study(work: Path) -> None:
    calendar, codes = pr17_calendar(), pr17_codes()
    started = time.monotonic()
    stocks = [load(work / "stocks" / f"{code}.npz", code) for code in codes]
    loaded = time.monotonic()
    a4 = study.h_states(stocks)
    ranked = time.monotonic()
    year_index = np.asarray(_years(calendar) - study.FIRST_YEAR, dtype=np.intp)
    n_years = int(year_index.max()) + 1
    counts = np.stack([study.stock_group_counts(stock, h, year_index=year_index, n_years=n_years) for stock, h in zip(stocks, a4, strict=True)])
    np.save(work / "counts.npy", counts)
    counted = time.monotonic()
    names = list(study.groups())
    splits = np.array([stock.split for stock in stocks])
    stock_masks = {"all": np.ones(len(codes), dtype=bool), **{name: splits == name for name in SPLITS[1:]}}
    year_values = np.arange(study.FIRST_YEAR, study.FIRST_YEAR + n_years)
    rows: list[dict[str, Any]] = []
    annual: list[dict[str, Any]] = []
    for g, group in enumerate(names):
        for label, (horizon, target) in enumerate(study.LABELS):
            full = counts[:, g, label]
            for split, smask in stock_masks.items():
                split_codes = [code for code, keep in zip(codes, smask, strict=True) if keep]
                for era, (first, last) in ERAS.items():
                    ymask = (year_values >= first) & (year_values <= last)
                    key = {"group_id": group, "horizon": horizon, "target_multiple": target, "split": split, "era": era}
                    rows.extend(_slice_rows(key, full[smask][:, ymask], year_values[ymask], split_codes))
            for y, year in enumerate(year_values):
                annual.append({
                    "group_id": group,
                    "horizon": horizon,
                    "target_multiple": target,
                    "year": int(year),
                    **cube.summarize(full[:, [y]], study.METRICS),
                })

    def row_key(group: object, row: dict[str, Any]) -> tuple[object, ...]:
        return (group, row["horizon"], row["target_multiple"], row["split"], row["era"], row["row_kind"])

    index: dict[tuple[object, ...], dict[str, Any]] = {row_key(r["group_id"], r): r for r in rows}
    extra = []
    for r in rows:
        is_cooled = r["group_id"].endswith(":cooled") or r["group_id"] in ("C-base", "C-52w")
        base_id, c52_id = ("C-base", "C-52w") if is_cooled else ("C-base-daily", "C-52w-daily")
        extra.append({**_comparison(r, index.get(row_key(base_id, r)), "base"), **_comparison(r, index.get(row_key(c52_id, r)), "c52w")})
    summary = pd.concat([pd.DataFrame(rows), pd.DataFrame(extra)], axis=1)
    summary.to_parquet(work / "set_summary.parquet", index=False)
    pd.DataFrame(annual).to_parquet(work / "set_annual.parquet", index=False)
    summarized = time.monotonic()
    weights = {
        "stock": (cube.bootstrap_weights(len(codes), REPS, SEEDS["stock"]), None),
        "two_way": (cube.bootstrap_weights(len(codes), REPS, SEEDS["two_way"]), cube.bootstrap_weights(n_years, REPS, SEEDS["two_way"] + 1)),
    }
    known, hit, loss = (study.METRICS.index(name) for name in ("known_n", "hit_n", "loss_n"))
    intervals = []
    for focus in FOCUS:
        for label, (horizon, target) in enumerate(study.LABELS):
            for mode, (stock_weights, year_weights) in weights.items():
                totals = {
                    g: cube.resampled_totals(counts[:, names.index(g), label], stock_weights, year_weights) for g in (focus, "C-base-daily", "C-52w-daily")
                }
                with np.errstate(divide="ignore", invalid="ignore"):
                    rate = {g: (t[:, hit] / t[:, known], t[:, loss] / t[:, known]) for g, t in totals.items()}
                stats = {
                    "hit_diff_vs_base": rate[focus][0] - rate["C-base-daily"][0],
                    "hit_ratio_vs_base": rate[focus][0] / rate["C-base-daily"][0],
                    "loss_diff_vs_base": rate[focus][1] - rate["C-base-daily"][1],
                    "hit_diff_vs_c52w": rate[focus][0] - rate["C-52w-daily"][0],
                    "loss_diff_vs_c52w": rate[focus][1] - rate["C-52w-daily"][1],
                }
                for statistic, samples in stats.items():
                    low, high = cube.percentile_interval(samples)
                    intervals.append({
                        "group_id": focus,
                        "horizon": horizon,
                        "target_multiple": target,
                        "bootstrap": mode,
                        "seed": SEEDS[mode],
                        "reps": REPS,
                        "statistic": statistic,
                        "lower": low,
                        "upper": high,
                    })
    pd.DataFrame(intervals).to_parquet(work / "bootstrap_intervals.parquet", index=False)
    finished = time.monotonic()
    timings = {
        "load": round(loaded - started, 1),
        "h_barrier": round(ranked - loaded, 1),
        "count": round(counted - ranked, 1),
        "summarize": round(summarized - counted, 1),
        "bootstrap": round(finished - summarized, 1),
    }
    record = {"codes": len(codes), "groups": names, "labels": [list(label) for label in study.LABELS], "timings_seconds": timings}
    (work / "study.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    LOGGER.info("Study tables written rows=%d annual=%d intervals=%d timings=%s", len(summary), len(annual), len(intervals), timings)


def _coverage_summary(rows: pd.DataFrame) -> dict[str, Any]:
    status = rows["coverage_status"]
    matched, unmatched, unknown = (int(status.eq(value).sum()) for value in ("matched", "unmatched", "unknown"))
    total = len(rows)
    timed = rows.loc[status.eq("matched") & rows["first_timing_certain"].eq(True)]
    entries = rows.loc[status.eq("matched"), "entry_return"].astype(float)
    remaining = rows.loc[status.eq("matched"), "remaining_return"].astype(float)

    def quantiles(values: pd.Series) -> dict[str, float | None]:
        if values.empty:
            return {"q25": None, "median": None, "q75": None}
        return {"q25": float(values.quantile(0.25)), "median": float(values.median()), "q75": float(values.quantile(0.75))}

    return {
        "episode_n": total,
        "distinct_stock_n": int(rows["code"].nunique()),
        "matched_n": matched,
        "unmatched_n": unmatched,
        "unknown_n": unknown,
        "coverage_rate": matched / (matched + unmatched) if matched + unmatched else None,
        "coverage_lower_bound": matched / total if total else None,
        "coverage_upper_bound": (matched + unknown) / total if total else None,
        "timing_known_n": len(timed),
        **{f"offset_{k}": v for k, v in quantiles(timed["observed_offset"].astype(float)).items()},
        **{f"entry_return_{k}": v for k, v in quantiles(entries).items()},
        **{f"remaining_return_{k}": v for k, v in quantiles(remaining).items()},
    }


def run_coverage(work: Path) -> None:
    """Big-runner coverage for H504 5x/10x episodes, with a daily random control per set."""
    calendar, codes = pr17_calendar(), pr17_codes()
    generation = json.loads((work / "stocks.json").read_text(encoding="utf-8"))["generation"]
    stocks = [load(work / "stocks" / f"{code}.npz", code) for code in codes]
    a4 = study.h_states(stocks)
    years = _years(calendar)
    iso = [str(day) for day in pd.Series(calendar).dt.strftime("%Y-%m-%d")]
    sets = study.condition_sets()
    observations: list[dict[str, Any]] = []
    quotas: list[dict[str, Any]] = []
    episodes_out: list[dict[str, Any]] = []
    for stock, h in zip(stocks, a4, strict=True):
        prices, _ = read_adjusted_daily("reference_factor_adjusted", codes=[stock.code], as_of=CUTOFF, calendar=calendar, generation=generation)
        closes = study.masked_close(prices.drop(columns="Code").set_index("Date"))
        episodes = {label: study.merge_episodes(study.episode_starts(stock, *label), closes, label[0]) for label in study.EPISODE_LABELS}
        if not any(episodes.values()):
            continue
        for (horizon, target), found in episodes.items():
            for episode in found:
                episodes_out.append({
                    "code": stock.code,
                    "horizon": horizon,
                    "target_multiple": target,
                    "anchor_index": episode.anchor_index,
                    "peak_index": episode.peak_index,
                    "anchor_date": None if episode.anchor_index is None else iso[episode.anchor_index],
                    "peak_date": None if episode.peak_index is None else iso[episode.peak_index],
                    "status": episode.status,
                    "reason": episode.reason,
                    "start_n": len(episode.start_indices),
                    "peak_return": None if episode.peak_index is None else float(closes[episode.peak_index] / closes[episode.anchor_index] - 1),
                })
        atoms = {**stock.atoms, "A4": h}
        for name, members in sets.items():
            states = study.set_states(atoms, members, stock.eligible)
            drawn, quota = study.random_daily_draws(stock.eligible, states == 1, years, group_id=name, code=stock.code)
            quotas.extend(quota)
            short_years = [int(str(q["year"])) for q in quota if q["shortfall_n"]]
            random_states = np.where(np.isin(years, np.array(short_years, dtype=np.int64)), np.int8(-1), drawn.astype(np.int8)).astype(np.int8)
            for (horizon, target), found in episodes.items():
                for episode in found:
                    for group, values in ((name, states), (f"{name}:random", random_states)):
                        observed = study.observe_to_peak(episode, closes, values)
                        observations.append({"group_id": group, "code": stock.code, "horizon": horizon, "target_multiple": target, **observed})
    frame = pd.DataFrame(observations)
    frame.to_parquet(work / "coverage_observations.parquet", index=False)
    pd.DataFrame(quotas).to_parquet(work / "coverage_quotas.parquet", index=False)
    pd.DataFrame(episodes_out).to_parquet(work / "episodes.parquet", index=False)
    summary = [
        {"group_id": group, "horizon": horizon, "target_multiple": target, **_coverage_summary(rows)}
        for (group, horizon, target), rows in cast(Any, frame.groupby(["group_id", "horizon", "target_multiple"], sort=True))
    ]
    pd.DataFrame(summary).to_parquet(work / "big_runner_coverage.parquet", index=False)
    LOGGER.info("Coverage written episodes=%d observations=%d groups=%d", len(episodes_out), len(frame), len(summary))


AUDIT_SAMPLE_5X = 20
DAILY_LIMIT = 0.105  # above the 10% daily price limit (7% before 2015-06-01)


def _audit_row(episode: pd.Series, prepared: pd.DataFrame, closes: np.ndarray, actions: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict[str, Any]:
    """Price evidence for one episode window, anchor..peak. Screening only; decisions are manual."""
    anchor, peak = int(episode["anchor_index"]), int(episode["peak_index"])
    window = prepared.iloc[anchor : peak + 1]
    raw = window["RawClose"].to_numpy(dtype=float)
    adjusted = closes[anchor : peak + 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        adjusted_returns = adjusted[1:] / adjusted[:-1] - 1
        raw_returns = raw[1:] / raw[:-1] - 1
    first, last = calendar[anchor], calendar[peak]
    events = actions.loc[(pd.to_datetime(actions["ex_date"]) > first) & (pd.to_datetime(actions["ex_date"]) <= last)]
    big_days = [
        {
            "date": str(pd.Series(calendar[anchor + 1 + i : anchor + 2 + i]).dt.strftime("%Y-%m-%d").iloc[0]),
            "adjusted_return": float(adjusted_returns[i]),
            "raw_return": float(raw_returns[i]),
        }
        for i in np.flatnonzero(np.abs(adjusted_returns) > DAILY_LIMIT)
    ]
    reasons = window["quality_reason"].dropna()
    flags = []
    if big_days:
        flags.append("adjusted_move_beyond_daily_limit")
    if (window["quality_reason"].astype(str).str.contains("ambiguous_or_missing_action_factor")).any():
        flags.append("ambiguous_or_missing_action_factor")
    if not np.isfinite(raw).all():
        flags.append("missing_raw_close")
    return {
        "code": episode["code"],
        "target_multiple": float(episode["target_multiple"]),
        "anchor_date": episode["anchor_date"],
        "peak_date": episode["peak_date"],
        "sessions": peak - anchor,
        "adjusted_ratio": float(adjusted[-1] / adjusted[0]),
        "raw_ratio": float(raw[-1] / raw[0]) if np.isfinite(raw[[0, -1]]).all() else None,
        "action_events": json.dumps(events[["ex_date", "event_type", "price_factor"]].to_dict(orient="records"), default=str),
        "action_event_n": len(events),
        "max_adjusted_daily_return": float(np.nanmax(adjusted_returns)) if len(adjusted_returns) else None,
        "min_adjusted_daily_return": float(np.nanmin(adjusted_returns)) if len(adjusted_returns) else None,
        "beyond_limit_days": json.dumps(big_days),
        "quality_reasons": json.dumps(sorted({str(value) for value in reasons})),
        "screen_flags": json.dumps(flags),
    }


def run_audit(work: Path) -> None:
    """Screen every H504 10x episode and 20 seeded 5x episodes with price evidence."""
    calendar = pr17_calendar()
    generation = json.loads((work / "stocks.json").read_text(encoding="utf-8"))["generation"]
    episodes = pd.read_parquet(work / "episodes.parquet")
    known = episodes.loc[episodes["status"].eq("known")]
    tens = known.loc[known["target_multiple"].eq(10.0)]
    fives = known.loc[known["target_multiple"].eq(5.0)].sort_values(["code", "anchor_index"]).reset_index(drop=True)
    picked = np.sort(np.random.default_rng(SEEDS["stock"]).choice(len(fives), size=min(AUDIT_SAMPLE_5X, len(fives)), replace=False))
    selected = pd.concat([tens, fives.iloc[picked]], ignore_index=True)
    actions = pd.read_parquet(Path(current_generation(generation=generation)["path"]) / "actions.parquet")
    rows: list[dict[str, Any]] = []
    for code, group in selected.groupby("code", sort=True):
        prices, _ = read_adjusted_daily("reference_factor_adjusted", codes=[str(code)], as_of=CUTOFF, calendar=calendar, generation=generation)
        prepared = prices.drop(columns="Code").set_index("Date")
        closes = study.masked_close(prepared)
        stock_actions = actions.loc[actions["code"].eq(code)]
        rows.extend(_audit_row(episode, prepared, closes, stock_actions, calendar) for _, episode in group.iterrows())
    audit = pd.DataFrame(rows)
    audit.to_parquet(work / "audit_screen.parquet", index=False)
    flagged = int(audit["screen_flags"].ne("[]").sum())
    LOGGER.info("Audit screen rows=%d (10x=%d, 5x sample=%d) flagged=%d", len(audit), len(tens), len(picked), flagged)


TASK = Path("tasks/20261021-momentum-only-doubling")
REPO_ROOT = Path(__file__).resolve().parents[1]
PHASES = ("stocks", "parity", "study", "coverage", "audit")
FINAL_TABLES = ("set_annual", "bootstrap_intervals", "big_runner_coverage", "coverage_quotas", "parity_check")
DECOMPOSITION_REASON = "PR17 daily raw union pattern states are not published with a data contract (mission start condition 3)"


def _verdicts(summary: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    """Core-question cells (decomposition not_evaluated): no share; both bootstraps must agree."""
    keep = summary.split.eq("all") & summary.era.eq("all") & summary.row_kind.eq("full")
    full = summary.loc[keep].set_index(["group_id", "horizon", "target_multiple"])
    rows = []
    for focus in FOCUS:
        cooled_id = focus.replace(":daily", ":cooled")
        for horizon, target in study.LABELS:
            cell = full.loc[(focus, horizon, target)]
            sample = full.loc[(cooled_id, horizon, target)]
            sufficient = bool(sample["known_n"] >= 100 and sample["distinct_stock_n"] >= 30)
            bounds = intervals.loc[intervals.group_id.eq(focus) & intervals.horizon.eq(horizon) & intervals.target_multiple.eq(target)]
            record: dict[str, Any] = {
                "group_id": focus,
                "horizon": horizon,
                "target_multiple": target,
                "primary": target == 2.0 and horizon in (126, 252),
                "hit_rate": cell["hit_rate"],
                "loss_rate": cell["loss_rate"],
                "hit_ratio_vs_base": cell["hit_ratio_vs_base"],
                "hit_diff_vs_base": cell["hit_diff_vs_base"],
                "loss_diff_vs_base": cell["loss_diff_vs_base"],
                "hit_diff_vs_c52w": cell["hit_diff_vs_c52w"],
                "cooled_known_n": int(sample["known_n"]),
                "cooled_distinct_stock_n": int(sample["distinct_stock_n"]),
                "sample_sufficient": sufficient,
            }
            for statistic in ("hit_diff_vs_base", "loss_diff_vs_base", "hit_diff_vs_c52w"):
                chosen = bounds.loc[bounds.statistic.eq(statistic)]
                above = bool((chosen["lower"].astype(float) > 0).all())
                below = bool((chosen["upper"].astype(float) < 0).all())
                direction = "above_zero" if above else "below_zero" if below else "unresolved"
                record[f"{statistic}_direction"] = direction if sufficient else "insufficient_sample"
            rows.append(record)
    return pd.DataFrame(rows)


def _decomposition() -> pd.DataFrame:
    rows: list[dict[str, Any]] = [
        {"family": family, "horizon": horizon, "target_multiple": target, "status": "not_evaluated", "reason": DECOMPOSITION_REASON}
        for family in ("B1", "H1")
        for horizon, target in study.LABELS
    ]
    rows += [
        {"family": name, "horizon": None, "target_multiple": None, "status": "not_evaluated", "reason": DECOMPOSITION_REASON}
        for name in ("A7", "LEAD_H1", "share")
    ]
    return pd.DataFrame(rows)


def _audit_episodes(work: Path) -> pd.DataFrame:
    screen = pd.read_parquet(work / "audit_screen.parquet")
    decisions = json.loads((TASK / "audit-decisions.json").read_text(encoding="utf-8"))["decisions"]
    by_key = {(str(d["code"]), float(d["target_multiple"]), str(d["anchor_date"])): d for d in decisions}
    keys = [(str(c), float(t), str(a)) for c, t, a in zip(screen["code"], screen["target_multiple"], screen["anchor_date"], strict=True)]
    undecided = [key for key in keys if key not in by_key]
    if undecided:
        raise ValueError(f"every screened episode needs a recorded manual decision (mission: all 10x and the 20 sampled 5x): {undecided}")
    screen["review"] = "manual"
    screen["audit_price_error"] = [bool(by_key.get(key, {}).get("audit_price_error", False)) for key in keys]
    screen["review_note"] = [by_key.get(key, {}).get("note") for key in keys]
    episodes = pd.read_parquet(work / "episodes.parquet")
    unknown = episodes.loc[episodes.target_multiple.eq(10.0) & episodes.status.ne("known")]
    unknown_rows = pd.DataFrame({
        "code": unknown.code,
        "target_multiple": 10.0,
        "anchor_date": unknown.anchor_date,
        "review": "not_screenable_unknown_episode",
        "audit_price_error": False,
        "review_note": unknown.reason,
    })
    return pd.concat([screen, unknown_rows], ignore_index=True)


def run_finalize(work: Path, output: Path) -> None:
    """Publish final tables and a results-only receipt after checking all phases ran from one clean commit."""
    phases = json.loads((work / "phases.json").read_text(encoding="utf-8"))
    missing = [phase for phase in PHASES if phase not in phases]
    identities = {json.dumps(phases[phase]["code"], sort_keys=True) for phase in PHASES if phase in phases}
    if missing or len(identities) != 1 or any(phases[phase]["code"]["dirty"] for phase in PHASES):
        raise SystemExit(f"every phase must run from one clean commit; missing={missing} identities={identities}")
    identity = phases["stocks"]["code"]
    stocks = json.loads((work / "stocks.json").read_text(encoding="utf-8"))
    verdicts = _verdicts(pd.read_parquet(work / "set_summary.parquet"), pd.read_parquet(work / "bootstrap_intervals.parquet"))
    audit = _audit_episodes(work)
    if bool(audit["audit_price_error"].astype(bool).any()):
        raise SystemExit("audit_price_error episodes require the second (removed) count version before publication")
    tables = {name: pd.read_parquet(work / f"{name}.parquet") for name in FINAL_TABLES}
    tables.update({"verdicts": verdicts, "decomposition_summary": _decomposition(), "audit_episodes": audit})
    # One set_summary file per split x row_kind keeps every file under the 500 KiB commit limit.
    summary = pd.read_parquet(work / "set_summary.parquet")
    for (split, kind), part in cast(Any, summary.groupby(["split", "row_kind"], sort=True)):
        tables[f"set_summary-{split}-{kind}"] = part.reset_index(drop=True)
    files: dict[str, bytes] = {}
    for name, frame in tables.items():
        buffer = io.BytesIO()
        frame.to_parquet(buffer, index=False, compression="zstd")
        files[f"{name}.parquet"] = buffer.getvalue()
    result = {
        "definition": study.DEFINITION_ID,
        "generation": stocks["generation"],
        "cutoff": CUTOFF,
        "parity": json.loads((work / "parity_check.json").read_text(encoding="utf-8"))["verdict"],
        "primary_cells": json.loads(verdicts.loc[verdicts.primary].to_json(orient="records")),
        "decomposition": "not_evaluated",
        "audit": {"rows": len(audit), "audit_price_error": int(audit["audit_price_error"].sum())},
    }
    files["research_result.json"] = (json.dumps(result, indent=2, ensure_ascii=False) + chr(10)).encode("utf-8")
    publish_new_directory(output, files)
    _, record = read_adjusted_daily("reference_factor_adjusted", codes=["2330"], as_of=CUTOFF, calendar=pr17_calendar(), generation=stocks["generation"])
    write_run_receipt(
        output / "run-receipt.json",
        run_id=f"momentum-only-{stocks['generation']}",
        definition=study.DEFINITION_ID,
        parameters={
            "cutoff": CUTOFF,
            "targets": list(study.TARGETS),
            "horizons": list(study.HORIZONS),
            "bootstrap_reps": REPS,
            "seeds": SEEDS,
            "phases": phases,
        },
        inputs=fingerprint_inputs([
            InputSpec("pr17_calendar_pins", PINS, live_producer=False),
            InputSpec("pr17_universe", PR17_PREPARATION, live_producer=False),
            InputSpec("pr17_parity_reference", PR17_Q1, live_producer=False),
        ]),
        results={name: output / name for name in files},
        preregistration=TASK / "mission.md",
        repo_root=REPO_ROOT,
        shared_data=[record],
        expected_code=identity,
    )
    LOGGER.info("Published %d final files to %s", len(files), output)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    stocks = sub.add_parser("stocks")
    stocks.add_argument("--work", type=Path, required=True)
    stocks.add_argument("--generation", required=True)
    for name in ("parity", "study", "coverage", "audit"):
        sub.add_parser(name).add_argument("--work", type=Path, required=True)
    final = sub.add_parser("finalize")
    final.add_argument("--work", type=Path, required=True)
    final.add_argument("--output", type=Path, default=TASK / "results")
    args = parser.parse_args()
    identity = code_identity(REPO_ROOT)
    started = time.monotonic()
    if args.command == "stocks":
        run_stocks(args.work, args.generation)
    elif args.command == "parity":
        sys.stdout.write(json.dumps(run_parity(args.work), indent=2, default=float) + chr(10))
    elif args.command == "finalize":
        run_finalize(args.work, args.output)
        return
    else:
        if json.loads((args.work / "parity_check.json").read_text(encoding="utf-8"))["verdict"] == "stop":
            raise SystemExit("parity gate failed; the mission forbids computing condition sets")
        {"study": run_study, "coverage": run_coverage, "audit": run_audit}[args.command](args.work)
    phases_path = args.work / "phases.json"
    phases = json.loads(phases_path.read_text(encoding="utf-8")) if phases_path.exists() else {}
    phases[args.command] = {"code": identity, "wall_seconds": round(time.monotonic() - started, 1)}
    phases_path.write_text(json.dumps(phases, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
