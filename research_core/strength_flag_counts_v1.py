"""Integer stock/year counts and paired weakening estimates (W1--W10).

The tall sparse count table is resumable scratch data. A cell is reconstructed
as a small stock x year cube only when summarizing/bootstraping that cell; no
stock/event rate is averaged. Cooldown always precedes landmark flag splitting.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from research_core import count_cube_v1 as cube
from research_core import momentum_only_v1 as momentum
from research_core.multiple_outcomes_v1 import outcomes_for_targets
from research_core.pattern_scan_flags_v1 import FLAG_IDS
from research_core.strength_flags_v1 import FLAG_STATES, LANDMARKS, RISE_BINS, BatchFlagIndex

LOGGER = logging.getLogger(__name__)
DEFINITION_ID = "strength-flag-counts.v1"
GROUPS = ("C-base-daily", "C-52w-daily", "CORE", "LEAD_B1")
METRICS = ("event_n", "known_n", "hit_n", "loss_n", "flat_win_n", "unknown_n", "censored_n", "full_hit_n")
CELL_KEYS = ("group_id", "horizon", "target_multiple", "landmark", "flag_id")
COUNT_KEYS = (*CELL_KEYS, "basis", "year", "flag_state", "rise_bin")
BOOTSTRAPS = (("stock", 20261024), ("two_way", 20261025))
N_REPS = 2000


def memberships(stock: momentum.StockDaily) -> dict[str, NDArray[np.bool_]]:
    """Only PR61 membership APIs; no cross-sectional atom is needed here."""
    return {
        "C-base-daily": np.ones(len(stock.eligible), dtype=bool),
        "C-52w-daily": stock.c52w,
        "CORE": momentum.set_members(stock.atoms, ("A1", "A2")),
        "LEAD_B1": momentum.set_members(stock.atoms, ("A1", "A2", "A3")),
    }


def parity_counts(stock: momentum.StockDaily, years: NDArray[np.int64]) -> pd.DataFrame:
    """Unconditional PR61 totals, before any landmark/riskset filtering."""
    rows = []
    for group, members in memberships(stock).items():
        lookback = momentum.BASELINE_LOOKBACK.get(group, 0)
        counts = momentum.group_counts(stock, members, lookback=lookback, year_index=years - int(years.min()), n_years=int(years.max() - years.min()) + 1)
        for horizon in (126, 252):
            values = counts[momentum.LABELS.index((horizon, 2.0))].sum(axis=0)
            rows.append({
                "group_id": group,
                "horizon": horizon,
                "target_multiple": 2.0,
                **{name: int(values[momentum.METRICS.index(name)]) for name in ("known_n", "hit_n", "loss_n")},
            })
    return pd.DataFrame(rows)


def count_stock(
    stock: momentum.StockDaily,
    flags: BatchFlagIndex,
    years: NDArray[np.int64],
    *,
    horizons: Sequence[int] = momentum.HORIZONS,
    targets: Sequence[float] = momentum.TARGETS,
    landmarks: Sequence[int] = LANDMARKS,
) -> pd.DataFrame:
    """Sparse per-stock/year integer counts; all landmark outcomes use PR61 overlay.

    Full-scope rows (L=H) include all member events, not the no-hit riskset;
    they alone measure false abandonment among calendar-full effective hits.
    Landmark rows contain only the entire-valid-prefix/no-hit riskset.
    """
    if len(years) != len(stock.eligible) or len(years) != flags.n:
        raise ValueError("stock, flag index and year calendar must align")
    groups = memberships(stock)
    event_days = np.flatnonzero(stock.eligible).astype(np.int64)
    if not len(event_days):
        return pd.DataFrame(columns=pd.Index(["code", "split", *COUNT_KEYS, *METRICS]))
    first_year, n_years = int(years.min()), int(years.max() - years.min()) + 1
    all_positions = np.arange(flags.n)
    invalid_prefix = np.concatenate(([0], np.cumsum(~flags.valid)))
    records: list[dict[str, Any]] = []
    for horizon in horizons:
        outcomes = outcomes_for_targets(flags.close, horizon, list(targets))
        for target in targets:
            outcome = outcomes[target]
            first_hit = outcome["first_hit_offset"].to_numpy(dtype=float, na_value=np.nan)
            for landmark in (*[value for value in landmarks if value < horizon], horizon):
                full = landmark == horizon
                available = np.minimum(all_positions + landmark, flags.n - 1)
                prefix_valid = (all_positions + landmark < flags.n) & ((invalid_prefix[available + 1] - invalid_prefix[all_positions]) == 0)
                riskset = prefix_valid & (~np.isfinite(first_hit) | (first_hit > landmark))
                ratios = np.full(flags.n, np.nan)
                ratio_known = flags.valid & (all_positions + landmark < flags.n) & flags.valid[available]
                ratios[ratio_known] = flags.close[available[ratio_known]] / flags.close[ratio_known]
                # Unknown rise is retained explicitly; pooled estimates include it only for full scope.
                rise = np.where(~np.isfinite(ratios), 4, np.where(ratios < 1, 0, np.where(ratios < 1.1, 1, np.where(ratios < 1.25, 2, 3)))).astype(np.int64)
                cutoffs = np.full(flags.n, landmark, dtype=np.int64)
                if full:
                    cutoffs = np.where(np.isfinite(first_hit), np.minimum(cutoffs, np.nan_to_num(first_hit, nan=landmark + 1).astype(np.int64) - 1), cutoffs)
                histories = {flag: flags.histories(flag, all_positions.astype(np.int64), cutoffs) for flag in FLAG_IDS}
                for group, members in groups.items():
                    quality = momentum.quality_unknown(stock.jump, momentum.BASELINE_LOOKBACK.get(group, 0), horizon)
                    label = np.where(quality, 0, stock.labels[horizon, target])
                    known = stock.main_eligible[horizon, target] & ~quality
                    for basis in ("daily", "cooled"):
                        selected = members & stock.eligible if basis == "daily" else momentum.cooled(members, stock.eligible)
                        if not full:
                            selected &= riskset
                        days = np.flatnonzero(selected)
                        if not len(days):
                            continue
                        for flag in FLAG_IDS:
                            states = histories[flag][0]
                            encoded = ((years[days] - first_year) * 4 + states[days]) * 5 + rise[days]
                            masks = (
                                np.ones(len(days), dtype=bool),
                                known[days],
                                known[days] & (label[days] == 1),
                                known[days] & (label[days] == 2),
                                known[days] & (label[days] == 3),
                                label[days] == 0,
                                ~stock.calendar_full[horizon][days],
                                stock.calendar_full[horizon][days] & (label[days] == 1),
                            )
                            columns = [np.bincount(encoded[mask], minlength=n_years * 4 * 5) for mask in masks]
                            for index in np.flatnonzero(columns[0]):
                                year_state, r = divmod(int(index), 5)
                                y, s = divmod(year_state, 4)
                                records.append({
                                    "code": stock.code,
                                    "split": stock.split,
                                    "group_id": group,
                                    "horizon": horizon,
                                    "target_multiple": target,
                                    "landmark": landmark,
                                    "flag_id": flag,
                                    "basis": basis,
                                    "year": first_year + y,
                                    "flag_state": FLAG_STATES[s],
                                    "rise_bin": (*RISE_BINS, "unknown")[r],
                                    **{metric: int(column[index]) for metric, column in zip(METRICS, columns, strict=True)},
                                })
    return pd.DataFrame(records, columns=pd.Index(["code", "split", *COUNT_KEYS, *METRICS]))


def estimate(counts: NDArray[np.floating[Any]]) -> dict[str, float | None]:
    """From `[state, rise, metric]` counts; triggered rise distribution is fixed by each draw.

    No triggered stratum may be dropped or silently reweighted when the
    untriggered comparison lacks known support. Such standardization is null.
    """
    known, hit = METRICS.index("known_n"), METRICS.index("hit_n")
    triggered, untriggered = counts[0], counts[1]
    tn, un = float(triggered[:, known].sum()), float(untriggered[:, known].sum())
    tr = float(triggered[:, hit].sum()) / tn if tn else None
    ur = float(untriggered[:, hit].sum()) / un if un else None
    pooled = None if tr is None or ur is None else tr - ur
    ratio = tr / ur if tr is not None and ur else None
    standard: float | None = None
    if tn:
        weights = triggered[:4, known] / tn
        support = weights > 0
        if triggered[4, known] == 0 and np.all(untriggered[:4, known][support] > 0):
            standard = float(
                np.sum(
                    weights[support]
                    * (triggered[:4, hit][support] / triggered[:4, known][support] - untriggered[:4, hit][support] / untriggered[:4, known][support])
                )
            )
    return {"triggered_hit_rate": tr, "untriggered_hit_rate": ur, "pooled_difference": pooled, "hit_rate_ratio": ratio, "standardized_difference": standard}


def cell_cube(rows: pd.DataFrame, codes: Sequence[str], years: Sequence[int], *, basis: str = "daily") -> NDArray[np.int64]:
    """Dense one-cell cube `[stock,year,state,rise,metric]` from sparse counts."""
    out = np.zeros((len(codes), len(years), 4, 5, len(METRICS)), dtype=np.int64)
    if rows.empty:
        return out
    selected = rows.loc[rows.basis.eq(basis)]
    stock_index, year_index = {value: i for i, value in enumerate(codes)}, {value: i for i, value in enumerate(years)}
    state_index, rise_index = {value: i for i, value in enumerate(FLAG_STATES)}, {value: i for i, value in enumerate((*RISE_BINS, "unknown"))}
    for row in selected.itertuples(index=False):
        out[stock_index[str(row.code)], year_index[int(row.year)], state_index[str(row.flag_state)], rise_index[str(row.rise_bin)]] += np.array(
            [getattr(row, name) for name in METRICS], dtype=np.int64
        )
    return out


def intervals(counts: NDArray[np.int64], *, reps: int = N_REPS) -> list[dict[str, Any]]:
    """Paired stock and stock x year draws; undefined draws stay in the uncertainty accounting."""
    nstocks, nyears = counts.shape[:2]
    # Only the two comparison states' known/hit counts affect these estimates.
    # Excluding the other metrics lowers bootstrap work by eightfold.
    reduced = counts[:, :, :2, :, :][..., [METRICS.index("known_n"), METRICS.index("hit_n")]]
    flattened = reduced.reshape(nstocks, nyears, -1)
    rows = []
    for method, seed in BOOTSTRAPS:
        stock_weights = cube.bootstrap_weights(nstocks, reps, seed)
        year_weights = cube.bootstrap_weights(nyears, reps, seed + 1) if method == "two_way" else None
        samples = cube.resampled_totals(flattened, stock_weights, year_weights).reshape(reps, 2, 5, 2)
        known, hit = samples[..., 0], samples[..., 1]
        totals = known.sum(axis=2)
        rates = np.divide(hit.sum(axis=2), totals, out=np.full((reps, 2), np.nan), where=totals > 0)
        pooled = rates[:, 0] - rates[:, 1]
        ratio = np.divide(rates[:, 0], rates[:, 1], out=np.full(reps, np.nan), where=rates[:, 1] > 0)
        weights = np.divide(known[:, 0, :4], totals[:, 0, None], out=np.zeros((reps, 4)), where=totals[:, 0, None] > 0)
        strata_rates = np.divide(hit[:, :, :4], known[:, :, :4], out=np.zeros((reps, 2, 4)), where=known[:, :, :4] > 0)
        standard = (weights * (strata_rates[:, 0] - strata_rates[:, 1])).sum(axis=1)
        support = (totals[:, 0] > 0) & (known[:, 0, 4] == 0) & np.all((weights == 0) | (known[:, 1, :4] > 0), axis=1)
        standard[~support] = np.nan
        estimates = {"pooled_difference": pooled, "hit_rate_ratio": ratio, "standardized_difference": standard}
        for metric in ("pooled_difference", "hit_rate_ratio", "standardized_difference"):
            values = estimates[metric]
            valid = int(np.isfinite(values).sum())
            low, high = cube.percentile_interval(values)
            # Missing common support is not a narrower CI on surviving strata/draws.
            if valid != reps:
                low, high = None, None
            rows.append({"method": method, "metric": metric, "seed": seed, "replicates": reps, "defined_replicates": valid, "lower": low, "upper": high})
    return rows


def verdict(flag: str, cooled_counts: NDArray[np.int64], bounds: Sequence[dict[str, Any]]) -> str:
    if flag in {"Y1", "Y2"}:
        return "not_applicable"
    known = METRICS.index("known_n")
    for state in (0, 1):
        by_stock = cooled_counts[:, :, state, :, known].sum(axis=(1, 2))
        if int(by_stock.sum()) < 100 or int((by_stock > 0).sum()) < 30:
            return "inseparable"

    def both(metric: str, end: str, direction: int) -> bool:
        rows = [row for row in bounds if row["metric"] == metric]
        return len(rows) == 2 and all(row[end] is not None and direction * row[end] > 0 for row in rows)

    if both("pooled_difference", "upper", -1):
        return "weakens_beyond_drop" if both("standardized_difference", "upper", -1) else "weakens_with_drop"
    if both("pooled_difference", "lower", 1):
        return "opposite"
    return "unresolved"


def false_abandonment(full_counts: NDArray[np.int64]) -> dict[str, Any]:
    """Before-first-hit cost among calendar-full hits, with PR17 unknown bounds."""
    hits = full_counts[..., METRICS.index("full_hit_n")].sum(axis=(0, 1, 3))
    triggered, not_triggered, unknown = (int(value) for value in hits[:3])
    known, total = triggered + not_triggered, triggered + not_triggered + unknown
    return {
        "hit_triggered_n": triggered,
        "hit_not_triggered_n": not_triggered,
        "hit_flag_unknown_n": unknown,
        "false_abandonment_rate": triggered / known if known else None,
        "false_abandonment_lower": triggered / total if total else None,
        "false_abandonment_upper": (triggered + unknown) / total if total else None,
    }


def summarize_cell(
    rows: pd.DataFrame, full_rows: pd.DataFrame, codes: Sequence[str], years: Sequence[int], *, key: dict[str, Any], reps: int = N_REPS
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """All era/CRC/drop-best slices, plus the fixed all-data verdict and paired CIs."""
    daily, cooled = cell_cube(rows, codes, years), cell_cube(rows, codes, years, basis="cooled")
    full = cell_cube(full_rows, codes, years)
    bounds = intervals(daily, reps=reps)
    decision = verdict(str(key["flag_id"]), cooled, bounds)
    primary = (
        key["group_id"] in {"CORE", "LEAD_B1"}
        and key["horizon"] in {126, 252}
        and key["target_multiple"] == 2
        and key["landmark"] == 20
        and key["flag_id"] not in {"Y1", "Y2"}
    )
    stock_splits = np.array([momentum.split_for_code(code) for code in codes])
    year_values = np.array(years)
    slices: list[tuple[str, str, str, NDArray[np.bool_], NDArray[np.bool_], str | None]] = [
        ("all", "all", "full", np.ones(len(codes), bool), np.ones(len(years), bool), None)
    ]
    for split in ("development", "cross-check"):
        slices.append((split, "all", "full", stock_splits == split, np.ones(len(years), bool), None))
    for era, mask in (("2010-2012", year_values <= 2012), ("2013-2018", (year_values >= 2013) & (year_values <= 2018)), ("2019+", year_values >= 2019)):
        slices.append(("all", era, "full", np.ones(len(codes), bool), mask, None))
    hits = daily[..., METRICS.index("hit_n")].sum(axis=(2, 3))
    if daily[..., METRICS.index("event_n")].sum():
        best_year = int(np.argmax(hits.sum(axis=0)))
        best_stock = min(np.flatnonzero(hits.sum(axis=1) == hits.sum(axis=1).max()), key=lambda i: codes[int(i)])
        slices.append(("all", "all", "drop_best_year", np.ones(len(codes), bool), np.arange(len(years)) != best_year, str(years[best_year])))
        slices.append(("all", "all", "drop_best_stock", np.arange(len(codes)) != best_stock, np.ones(len(years), bool), str(codes[int(best_stock)])))
    summaries = []
    for split, era, kind, sm, ym, dropped in slices:
        part = daily[sm][:, ym]
        cool = cooled[sm][:, ym]
        aggregate = part.sum(axis=(0, 1)).astype(float)
        row: dict[str, Any] = {
            **key,
            "split": split,
            "era": era,
            "row_kind": kind,
            "dropped": dropped,
            "primary": bool(primary),
            **estimate(aggregate),
            **false_abandonment(full[sm][:, ym]),
        }
        for s, state in enumerate(FLAG_STATES):
            for m, metric in enumerate(METRICS):
                row[f"{state}_{metric}"] = int(aggregate[s, :, m].sum())
            known_by_stock = cool[:, :, s, :, METRICS.index("known_n")].sum(axis=(1, 2))
            row[f"{state}_cooled_known_n"] = int(known_by_stock.sum())
            row[f"{state}_cooled_stock_n"] = int((known_by_stock > 0).sum())
            daily_known = part[:, :, s, :, METRICS.index("known_n")].sum(axis=(1, 2))
            row[f"{state}_distinct_stock_n"] = int((daily_known > 0).sum())
        row["verdict"] = decision if split == era == "all" and kind == "full" else None
        summaries.append(row)
    return summaries, [{**key, **row} for row in bounds]
