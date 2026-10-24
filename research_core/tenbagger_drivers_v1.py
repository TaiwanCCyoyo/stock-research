"""Fixed retrospective and forward-denominator descriptions of large runners.

Only synthetic-data-safe computations live here. The runner owns live reads,
owner-merge gates, exact PR61 alignment, scratch lifetime and result receipts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from research_core import count_cube_v1 as cube
from research_core import momentum_only_v1 as momentum
from research_core.institutional_flow_v1 import NET_COLUMNS

DEFINITION_ID = "tenbagger-drivers.v1"
TASK_ID = "20261024-tenbagger-drivers"
HORIZONS = (252, 504)
TARGETS = (2.0, 3.0, 5.0, 10.0)
LABELS = tuple((h, t) for h in HORIZONS for t in TARGETS)
REPS = 2000
SEEDS = {"stock": 20261026, "two_way": 20261027}
ERAS = {"all": (2010, 2026), "2010-2012": (2010, 2012), "2013-2018": (2013, 2018), "2019+": (2019, 2026)}
CONDITIONS = {
    "HOT": ("HOT",),
    "SMALL": ("SMALL",),
    "HOT&SMALL": ("HOT", "SMALL"),
    "INST": ("INST",),
    "HOT&SMALL&INST": ("HOT", "SMALL", "INST"),
    "CORE&HOT&SMALL": ("CORE", "HOT", "SMALL"),
    "CORE&INST": ("CORE", "INST"),
    "CORE&HOT&SMALL&INST": ("CORE", "HOT", "SMALL", "INST"),
}
BASES = ("C-base-daily", "CORE", "C-base-daily|INST-known", "CORE|INST-known")
GROUPS = (*BASES, *CONDITIONS)
RETRO_GROUPS = ("ge10", "ge5_lt10", "ge2_lt5")
POINTS = ("anchor", "first_2x", "first_3x")
RETRO_VARIABLES = ("BREADTH", "SIZE_PERCENTILE", "HOT", "SMALL", "HOT&SMALL", "INST") + tuple(
    f"{column}_{suffix}" for column in NET_COLUMNS for suffix in ("buy_fraction", "volume_ratio")
)


class AlignmentError(RuntimeError):
    """Exact predeclared alignment failed; definitions must not be adjusted."""


@dataclass(frozen=True)
class DriverStock:
    daily: momentum.StockDaily
    close: NDArray[np.float64]
    industry: str
    features: pd.DataFrame


def conjunction(states: Sequence[NDArray[np.int8]]) -> NDArray[np.int8]:
    stacked = np.stack(states)
    return np.where((stacked == 0).any(axis=0), np.int8(0), np.where((stacked == 1).all(axis=0), np.int8(1), np.int8(-1))).astype(np.int8)


def formal_members(stock: DriverStock) -> dict[str, NDArray[np.bool_]]:
    """All eight F1 groups and F2's strictly identical institutional masks."""
    n = len(stock.daily.eligible)
    states = {name: stock.features[name].to_numpy(dtype=np.int8) for name in ("HOT", "SMALL", "INST")}
    states["CORE"] = conjunction([stock.daily.atoms["A1"], stock.daily.atoms["A2"]])
    known = states["INST"] != -1
    members = {
        "C-base-daily": np.ones(n, dtype=bool),
        "CORE": states["CORE"] == 1,
        "C-base-daily|INST-known": known,
        "CORE|INST-known": (states["CORE"] == 1) & known,
    }
    members.update({name: conjunction([states[item] for item in atoms]) == 1 for name, atoms in CONDITIONS.items()})
    return members


def comparison_bases(group: str) -> tuple[str, ...]:
    institutional = "INST" in CONDITIONS[group]
    suffix = "|INST-known" if institutional else ""
    return (f"C-base-daily{suffix}", f"CORE{suffix}") if "CORE" in CONDITIONS[group] else (f"C-base-daily{suffix}",)


def formal_counts(stocks: Sequence[DriverStock], calendar: pd.DatetimeIndex) -> tuple[NDArray[np.int32], NDArray[np.int32]]:
    """Daily and independently cooled stock x t0-year integer cubes, no rates."""
    years = momentum.calendar_years(calendar)
    year_index = np.asarray(years - momentum.FIRST_YEAR, dtype=np.intp)
    n_years = int(year_index.max()) + 1
    shape = (len(GROUPS), len(LABELS), len(stocks), n_years, len(momentum.METRICS))
    daily, cooled = np.zeros(shape, dtype=np.int32), np.zeros(shape, dtype=np.int32)
    selected_labels = [momentum.LABELS.index(label) for label in LABELS]
    for position, stock in enumerate(stocks):
        for group, mask in formal_members(stock).items():
            index = GROUPS.index(group)
            for destination, members in ((daily, mask), (cooled, momentum.cooled(mask, stock.daily.eligible))):
                counted = momentum.group_counts(stock.daily, members, lookback=0, year_index=year_index, n_years=n_years)
                destination[index, :, position] = counted[selected_labels]
    return daily, cooled


def _samples(counts: NDArray[np.integer], stocks: NDArray[np.integer], years: NDArray[np.integer] | None, numerator: str) -> NDArray[np.float64]:
    totals = cube.resampled_totals(counts, stocks, years)
    denominator = totals[:, momentum.METRICS.index("known_n")]
    result = np.full(len(totals), np.nan)
    np.divide(totals[:, momentum.METRICS.index(numerator)], denominator, out=result, where=denominator > 0)
    return result


def _bootstrap(n_stocks: int, n_years: int, reps: int) -> dict[str, tuple[NDArray[np.int32], NDArray[np.int32] | None]]:
    return {
        "stock": (cube.bootstrap_weights(n_stocks, reps, SEEDS["stock"]), None),
        "two_way": (cube.bootstrap_weights(n_stocks, reps, SEEDS["two_way"]), cube.bootstrap_weights(n_years, reps, SEEDS["two_way"] + 1)),
    }


def formal_tables(
    counts: NDArray[np.integer], cooled: NDArray[np.integer], codes: Sequence[str], *, reps: int = REPS
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """F3--F6 summaries, paired two-mode intervals and hit/loss verdicts."""
    if counts.shape != cooled.shape or counts.shape[:3] != (len(GROUPS), len(LABELS), len(codes)):
        raise ValueError("aligned daily/cooled cubes and original code order required")
    years = np.arange(counts.shape[3]) + momentum.FIRST_YEAR
    rows: list[dict[str, Any]] = []
    intervals: list[dict[str, Any]] = []
    verdicts: list[dict[str, Any]] = []
    weights = _bootstrap(len(codes), len(years), reps)
    for g, group in enumerate(GROUPS):
        for label_index, (horizon, target) in enumerate(LABELS):
            values = counts[g, label_index]
            for era, (first, last) in ERAS.items():
                sliced = values[:, (years >= first) & (years <= last)]
                row_key = {"group_id": group, "horizon": horizon, "target_multiple": target, "era": era}
                rows.append({**row_key, "row_kind": "full", **cube.summarize(sliced, momentum.METRICS)})
                best_year_index = cube.best_year(sliced, momentum.METRICS)
                security = cube.best_stock(sliced, momentum.METRICS, codes)
                if best_year_index is not None:
                    remaining = np.ones(sliced.shape[1], dtype=bool)
                    remaining[best_year_index] = False
                    rows.append({
                        **row_key,
                        "row_kind": "drop_best_year",
                        "dropped_year": int(years[(years >= first) & (years <= last)][best_year_index]),
                        **cube.summarize(sliced, momentum.METRICS, years=remaining),
                    })
                if security is not None:
                    remaining = np.ones(len(codes), dtype=bool)
                    remaining[security] = False
                    rows.append({
                        **row_key,
                        "row_kind": "drop_best_stock",
                        "dropped_stock": codes[security],
                        **cube.summarize(sliced, momentum.METRICS, stocks=remaining),
                    })
            for year_index, annual_year in enumerate(years):
                rows.append({
                    "group_id": group,
                    "horizon": horizon,
                    "target_multiple": target,
                    "era": "annual",
                    "row_kind": "full",
                    "year": int(annual_year),
                    **cube.summarize(values[:, year_index : year_index + 1], momentum.METRICS),
                })
            if group not in CONDITIONS:
                continue
            cold = cube.summarize(cooled[g, label_index], momentum.METRICS)
            insufficient = cold["known_n"] < 100 or cold["distinct_stock_n"] < 30
            for baseline in comparison_bases(group):
                reference = counts[GROUPS.index(baseline), label_index]
                for numerator, outcome in (("hit_n", "hit"), ("loss_n", "loss")):
                    bounds: list[tuple[float | None, float | None]] = []
                    for mode, (stock_weights, year_weights) in weights.items():
                        difference = _samples(values, stock_weights, year_weights, numerator) - _samples(reference, stock_weights, year_weights, numerator)
                        low, high = cube.percentile_interval(difference)
                        bounds.append((low, high))
                        intervals.append({
                            "group_id": group,
                            "baseline": baseline,
                            "horizon": horizon,
                            "target_multiple": target,
                            "outcome": outcome,
                            "bootstrap": mode,
                            "difference_low": low,
                            "difference_high": high,
                            "finite_replicates": int(np.isfinite(difference).sum()),
                            "replicates": reps,
                        })
                    verdict = (
                        "inseparable"
                        if insufficient
                        else "above_base"
                        if all(low is not None and low > 0 for low, _ in bounds)
                        else "below_base"
                        if all(high is not None and high < 0 for _, high in bounds)
                        else "unresolved"
                    )
                    verdicts.append({
                        "group_id": group,
                        "baseline": baseline,
                        "horizon": horizon,
                        "target_multiple": target,
                        "outcome": outcome,
                        "verdict": verdict,
                        "cooled_known_n": cold["known_n"],
                        "cooled_distinct_stock_n": cold["distinct_stock_n"],
                    })
    return pd.DataFrame(rows), pd.DataFrame(intervals), pd.DataFrame(verdicts)


def retro_observations(stocks: Sequence[DriverStock], calendar: pd.DatetimeIndex, exclusions: set[tuple[str, str]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """R1--R3's same 2x/H504 episodes and three fixed observation times."""
    rows: list[dict[str, Any]] = []
    alignment: list[dict[str, Any]] = []
    for stock in stocks:
        code, close = stock.daily.code, stock.close
        for target in (5.0, 10.0):
            episodes = momentum.merge_episodes(momentum.episode_starts(stock.daily, 504, target), close, 504)
            alignment.append({"code": code, "target_multiple": target, "episode_n": len(episodes)})
        episodes = momentum.merge_episodes(momentum.episode_starts(stock.daily, 504, 2.0), close, 504)
        for serial, episode in enumerate(episodes):
            anchor, peak = episode.anchor_index, episode.peak_index
            if episode.status != "known" or anchor is None or peak is None:
                continue
            anchor_date = cast(pd.Timestamp, calendar[anchor]).date().isoformat()
            if (code, anchor_date) in exclusions:
                continue
            multiple = float(close[peak] / close[anchor])
            category = "ge10" if multiple >= 10 else "ge5_lt10" if multiple >= 5 else "ge2_lt5"
            points: dict[str, int | None] = {"anchor": anchor}
            for target in (2, 3):
                crossed = np.flatnonzero(close[anchor + 1 : anchor + 505] >= target * close[anchor])
                points[f"first_{target}x"] = None if not len(crossed) else anchor + 1 + int(crossed[0])
            for point, position in points.items():
                if position is None:
                    continue
                features = stock.features.iloc[position]
                record: dict[str, Any] = {
                    "episode_id": f"{code}:{anchor_date}:{serial}",
                    "code": code,
                    "industry": stock.industry,
                    "anchor_date": anchor_date,
                    "peak_date": cast(pd.Timestamp, calendar[peak]).date().isoformat(),
                    "peak_multiple": multiple,
                    "group_id": category,
                    "point": point,
                    "calendar_index": position,
                    "t0": cast(pd.Timestamp, calendar[position]).date().isoformat(),
                    "year": int(cast(pd.Timestamp, calendar[position]).year),
                }
                record.update({variable: features[variable] for variable in RETRO_VARIABLES if variable in features})
                record["HOT&SMALL"] = int(conjunction([np.array([features["HOT"]], dtype=np.int8), np.array([features["SMALL"]], dtype=np.int8)])[0])
                rows.append(record)
    columns = [
        "episode_id",
        "code",
        "industry",
        "anchor_date",
        "peak_date",
        "peak_multiple",
        "group_id",
        "point",
        "calendar_index",
        "t0",
        "year",
        *RETRO_VARIABLES,
    ]
    return pd.DataFrame(rows, columns=pd.Index(columns)), pd.DataFrame(alignment)


def random_observations(observations: pd.DataFrame, stocks: Sequence[DriverStock], calendar: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    """R4 cohort x point x stock x t0-year matching; no quota reassignment."""
    rows: list[dict[str, Any]] = []
    quotas: list[dict[str, Any]] = []
    years = momentum.calendar_years(calendar)
    targets = pd.concat(
        [
            observations,
            observations.loc[observations.group_id.isin(("ge10", "ge5_lt10"))].assign(group_id="ge5"),
        ],
        ignore_index=True,
    )
    for stock in stocks:
        for key, requested in targets.loc[targets.code.eq(stock.daily.code)].groupby(["group_id", "point", "year"], sort=True):
            cohort, point, year = cast(tuple[str, str, int], key)
            pool = np.flatnonzero(stock.daily.eligible & (years == year))
            quota = len(requested)
            take = min(quota, len(pool))
            seed = int.from_bytes(f"20261024|{cohort}|{point}|{stock.daily.code}|{year}".encode(), "big") % (2**63)
            indices = np.sort(np.random.default_rng(seed).choice(pool, size=take, replace=False))
            quotas.append({
                "code": stock.daily.code,
                "matched_group": cohort,
                "point": point,
                "year": int(year),
                "quota_n": quota,
                "available_n": len(pool),
                "drawn_n": take,
                "shortfall_n": quota - take,
                "seed": str(seed),
            })
            for position in indices:
                values = stock.features.iloc[int(position)]
                record: dict[str, Any] = {
                    "code": stock.daily.code,
                    "industry": stock.industry,
                    "point": point,
                    "year": int(year),
                    "t0": cast(pd.Timestamp, calendar[int(position)]).date().isoformat(),
                    "group_id": "random",
                    "matched_group": cohort,
                    "calendar_index": int(position),
                }
                record.update({variable: values[variable] for variable in RETRO_VARIABLES if variable in values})
                record["HOT&SMALL"] = int(conjunction([np.array([values["HOT"]], dtype=np.int8), np.array([values["SMALL"]], dtype=np.int8)])[0])
                rows.append(record)
    return pd.DataFrame(
        rows, columns=pd.Index(["code", "industry", "point", "year", "t0", "group_id", "matched_group", "calendar_index", *RETRO_VARIABLES])
    ), pd.DataFrame(quotas)


def _bins(variable: str) -> tuple[tuple[str, float, float], ...]:
    if variable == "BREADTH":
        return (("lt10pct", 0, 0.1), ("10to25pct", 0.1, 0.25), ("ge25pct", 0.25, np.inf))
    if variable == "SIZE_PERCENTILE":
        return (("lt50", 0, 50), ("ge50", 50, np.inf))
    if variable in ("HOT", "SMALL", "HOT&SMALL", "INST"):
        return (("false", 0, 1), ("true", 1, 2))
    threshold = 0.6 if variable.endswith("buy_fraction") else 0.05
    return (("below", -np.inf, threshold), ("at_or_above", threshold, np.inf))


def _median_samples(
    found: pd.DataFrame,
    variable: str,
    known: pd.Series,
    stock_positions: Mapping[str, int],
    weights: Mapping[str, tuple[NDArray[np.int32], NDArray[np.int32] | None]],
    reps: int,
) -> dict[str, NDArray[np.float64]]:
    """Exact value-histogram integer counts by stock x year, then reweight.

    The sparse histogram keeps one integer multiplicity for each observed
    (stock, t0 year, value), avoiding a stock x year x unique-value dense cube.
    A bootstrap replicate's median is formed from its integer histogram, never
    from an average of stock medians or an independent redraw of episode rows.
    """
    hist = found.loc[known, ["code", "year", variable]].groupby(["code", "year", variable], sort=True).size().rename("count").reset_index()
    output = {mode: np.full(reps, np.nan) for mode in weights}
    if hist.empty:
        return output
    values = np.sort(hist[variable].unique().astype(float))
    positions = np.searchsorted(values, hist[variable].to_numpy(dtype=float))
    stocks = hist.code.map(stock_positions).to_numpy(dtype=np.intp)
    years = hist.year.to_numpy(dtype=np.intp) - momentum.FIRST_YEAR
    counts = hist["count"].to_numpy(dtype=np.int64)
    for mode, (sw, yw) in weights.items():
        for rep in range(reps):
            multiplicities = counts * sw[rep, stocks]
            if yw is not None:
                multiplicities = multiplicities * yw[rep, years]
            histogram = np.bincount(positions, weights=multiplicities, minlength=len(values)).astype(np.int64)
            total = int(histogram.sum())
            if total:
                cumulative = histogram.cumsum()
                low = int(np.searchsorted(cumulative, (total - 1) // 2 + 1))
                high = int(np.searchsorted(cumulative, total // 2 + 1))
                output[mode][rep] = (values[low] + values[high]) / 2
    return output


def retro_tables(
    observations: pd.DataFrame, random: pd.DataFrame, codes: Sequence[str], *, reps: int = REPS
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """R5 distributions/medians and paired stock-year bin-proportion intervals.

    Institutional variables are compared on the primary INST-known mask for
    every group. Medians for secondary flows additionally require finite values.
    Bootstrap counts are integer stock x observation-year denominators and bin
    counts; every rate is formed only after resampling those counts.
    """
    if "matched_group" not in random:
        raise ValueError("random controls must identify their matched retrospective cohort")
    random = random.copy()
    random["group_id"] = "random:" + random["matched_group"].astype(str)
    all_rows = pd.concat([observations, random], ignore_index=True)
    all_rows = pd.concat([all_rows, observations.loc[observations.group_id.isin(("ge10", "ge5_lt10"))].assign(group_id="ge5")], ignore_index=True)
    groups = (*RETRO_GROUPS, "ge5", *(f"random:{cohort}" for cohort in (*RETRO_GROUPS, "ge5")))
    first_year, n_years = 2010, 17
    weights = _bootstrap(len(codes), n_years, reps)
    stock_positions = {code: index for index, code in enumerate(codes)}
    summaries: list[dict[str, Any]] = []
    intervals: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for point in POINTS:
        for variable in RETRO_VARIABLES:
            by_group: dict[str, tuple[NDArray[np.int64], list[dict[str, Any]], dict[str, NDArray[np.float64]]]] = {}
            for group in groups:
                found = all_rows.loc[all_rows.point.eq(point) & all_rows.group_id.eq(group)]
                values = cast(pd.Series, pd.to_numeric(cast(pd.Series, found[variable]), errors="coerce"))
                known = values.notna() & np.isfinite(values)
                if variable in ("HOT", "SMALL", "HOT&SMALL", "INST"):
                    known &= values.ne(-1)
                institutional = variable == "INST" or any(variable.startswith(column) for column in NET_COLUMNS)
                if institutional:
                    known &= found.INST.ne(-1) & found.INST.notna()
                bins = _bins(variable)
                counts = np.zeros((len(codes), n_years, len(bins) + 1), dtype=np.int64)
                positions = found.loc[known, "code"].map(stock_positions).to_numpy(dtype=np.intp)
                year_indices = found.loc[known, "year"].to_numpy(dtype=np.intp) - first_year
                np.add.at(counts[:, :, 0], (positions, year_indices), 1)
                group_rows: list[dict[str, Any]] = []
                for bin_index, (label, lower, upper) in enumerate(bins):
                    matched = known & values.ge(lower) & values.lt(upper)
                    positions = found.loc[matched, "code"].map(stock_positions).to_numpy(dtype=np.intp)
                    year_indices = found.loc[matched, "year"].to_numpy(dtype=np.intp) - first_year
                    np.add.at(counts[:, :, bin_index + 1], (positions, year_indices), 1)
                    record = {
                        "point": point,
                        "variable": variable,
                        "group_id": group,
                        "matched_group": group.removeprefix("random:") if group.startswith("random:") else None,
                        "bin": label,
                        "event_n": len(found),
                        "known_n": int(known.sum()),
                        "unknown_n": int((~known).sum()),
                        "unknown_fraction": None if found.empty else float((~known).mean()),
                        "bin_n": int(matched.sum()),
                        "proportion": None if not known.any() else float(matched.sum() / known.sum()),
                        "median": None if not known.any() else float(values.loc[known].median()),
                    }
                    summaries.append(record)
                    group_rows.append(record)
                by_group[group] = (counts, group_rows, _median_samples(found, variable, known, stock_positions, weights, reps))
            for group in ("ge10", "ge5_lt10", "ge5"):
                for baseline in ("ge2_lt5", f"random:{group}"):
                    group_counts, group_rows, group_medians = by_group[group]
                    base_counts, base_rows, base_medians = by_group[baseline]
                    median_diff = (
                        None if group_rows[0]["median"] is None or base_rows[0]["median"] is None else group_rows[0]["median"] - base_rows[0]["median"]
                    )
                    for mode in weights:
                        difference = group_medians[mode] - base_medians[mode]
                        low, high = cube.percentile_interval(difference)
                        intervals.append({
                            "point": point,
                            "variable": variable,
                            "group_id": group,
                            "baseline": baseline,
                            "bin": "median",
                            "difference": median_diff,
                            "bootstrap": mode,
                            "difference_low": low,
                            "difference_high": high,
                            "finite_replicates": int(np.isfinite(difference).sum()),
                            "replicates": reps,
                        })
                    for bin_index, (label, _, _) in enumerate(_bins(variable)):
                        point_diff = (
                            None
                            if group_rows[bin_index]["proportion"] is None or base_rows[bin_index]["proportion"] is None
                            else group_rows[bin_index]["proportion"] - base_rows[bin_index]["proportion"]
                        )
                        bounds: list[tuple[float | None, float | None]] = []
                        for mode, (sw, yw) in weights.items():
                            left = cube.resampled_totals(group_counts, sw, yw)
                            right = cube.resampled_totals(base_counts, sw, yw)
                            left_rate, right_rate = np.full(reps, np.nan), np.full(reps, np.nan)
                            np.divide(left[:, bin_index + 1], left[:, 0], out=left_rate, where=left[:, 0] > 0)
                            np.divide(right[:, bin_index + 1], right[:, 0], out=right_rate, where=right[:, 0] > 0)
                            low, high = cube.percentile_interval(left_rate - right_rate)
                            bounds.append((low, high))
                            intervals.append({
                                "point": point,
                                "variable": variable,
                                "group_id": group,
                                "baseline": baseline,
                                "bin": label,
                                "difference": point_diff,
                                "bootstrap": mode,
                                "difference_low": low,
                                "difference_high": high,
                                "finite_replicates": int(np.isfinite(left_rate - right_rate).sum()),
                                "replicates": reps,
                            })
                        if point == "first_2x" and group == "ge5" and baseline == "ge2_lt5" and variable in ("HOT&SMALL", "INST") and label == "true":
                            supports = point_diff is not None and point_diff > 0 and all(low is not None and low > 0 for low, _ in bounds)
                            evidence.append({
                                "variable": variable,
                                "difference": point_diff,
                                "stock_low": bounds[0][0],
                                "stock_high": bounds[0][1],
                                "two_way_low": bounds[1][0],
                                "two_way_high": bounds[1][1],
                                "supports_continuation": supports,
                            })
    recommendation = {
        "rule": "R6",
        "recommend_continue": any(row["supports_continuation"] for row in evidence),
        "evidence": evidence,
        "owner_decision_required": True,
        "formal_definitions_unchanged": True,
    }
    return pd.DataFrame(summaries), pd.DataFrame(intervals), recommendation


def exact_a4(actual: Sequence[NDArray[np.int8]], reference: Sequence[NDArray[np.int8]], codes: Sequence[str]) -> list[dict[str, object]]:
    if len(actual) != len(reference) or len(actual) != len(codes):
        raise AlignmentError("A4 reference does not cover the complete fixed universe")
    differences = []
    for code, left, right in zip(codes, actual, reference, strict=True):
        if left.shape != right.shape:
            raise AlignmentError(f"A4 calendar shape differs for {code}")
        changed = np.flatnonzero(left != right)
        if len(changed):
            differences.append({"code": code, "different_cells": len(changed), "first_index": int(changed[0])})
    return differences


def exact_episode_counts(actual: pd.DataFrame, reference: pd.DataFrame) -> list[dict[str, object]]:
    differences: list[dict[str, object]] = []
    for target, fixed in ((10.0, 139), (5.0, 900)):
        counted = int(actual.loc[actual.target_multiple.eq(target), "episode_n"].sum())
        stored = reference.loc[reference.target_multiple.eq(target) & reference.horizon.eq(504), "episode_n"].unique()
        if len(stored) != 1 or int(stored[0]) != fixed or counted != fixed:
            differences.append({"target_multiple": target, "actual": counted, "reference": stored.tolist(), "fixed": fixed})
    return differences


def exact_formal_counts(counts: NDArray[np.integer], reference: pd.DataFrame) -> list[dict[str, object]]:
    differences: list[dict[str, object]] = []
    reference = reference.copy()
    for column, value in (("era", "all"), ("split", "all"), ("row_kind", "full")):
        if column in reference:
            reference = reference.loc[reference[column].eq(value)]
    for group, reference_group in (("C-base-daily", "C-base-daily"), ("CORE", "A1&A2:daily")):
        for index, (horizon, target) in enumerate(LABELS):
            if target == 2:
                continue
            found = reference.loc[reference.group_id.eq(reference_group) & reference.horizon.eq(horizon) & reference.target_multiple.eq(target)]
            if len(found) != 1:
                differences.append({"group_id": group, "horizon": horizon, "target_multiple": target, "reason": "missing_or_duplicate_reference"})
                continue
            totals = counts[GROUPS.index(group), index].sum(axis=(0, 1))
            for metric in momentum.METRICS:
                expected = int(found.iloc[0][metric])
                measured = int(totals[momentum.METRICS.index(metric)])
                if expected != measured:
                    differences.append({
                        "group_id": group,
                        "horizon": horizon,
                        "target_multiple": target,
                        "metric": metric,
                        "actual": measured,
                        "reference": expected,
                    })
    return differences
