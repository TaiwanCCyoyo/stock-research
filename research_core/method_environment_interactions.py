"""Bounded descriptive comparisons of saved methods, F37 and past-only context."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.feature_atlas_outcomes import binary_comparison

LOGGER = logging.getLogger(__name__)
FAMILIES = ("F10", "F32", "F33")
ARMS = ("all", "method", "relative_strength", "conjunction")
STATES = ("up", "down", "consolidation", "mixed", "unknown")
PATH_METRICS = ("forward_return", "min_return", "max_drawdown")


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    """Select a contract column with an explicit pandas Series type."""
    return cast(pd.Series, frame[name])


def _dates(values: pd.Series, name: str) -> pd.Series:
    parsed = cast(pd.Series, pd.to_datetime(values, errors="raise"))
    if parsed.isna().any() or parsed.dt.tz is not None or not parsed.eq(parsed.dt.normalize()).all():
        raise ValueError(f"{name} requires nonmissing timezone-naive calendar dates")
    # Strings must be unambiguous ISO dates; pandas otherwise accepts ambiguous forms.
    if pd.api.types.is_object_dtype(values) or pd.api.types.is_string_dtype(values):
        if not values.astype(str).eq(parsed.dt.strftime("%Y-%m-%d")).all():
            raise ValueError(f"{name} requires ISO YYYY-MM-DD dates")
    return parsed


def _validate_keys(frame: pd.DataFrame) -> pd.Series:
    if cast(pd.DataFrame, frame[["security_id", "asof_date"]]).isna().to_numpy().any() or frame.duplicated(["security_id", "asof_date"]).any():
        raise ValueError("missing or duplicate stock/date keys")
    dates = _dates(_column(frame, "asof_date"), "asof_date")
    indices = _column(frame, "calendar_index")
    if not pd.api.types.is_numeric_dtype(indices) or pd.api.types.is_bool_dtype(indices):
        raise ValueError("calendar_index requires nonnegative integers")
    if indices.isna().any() or not np.isfinite(indices).all() or not indices.ge(0).all() or not indices.mod(1).eq(0).all():
        raise ValueError("calendar_index requires nonnegative integers")
    calendar = pd.DataFrame({"date": dates, "index": indices}).drop_duplicates()
    if _column(calendar, "date").duplicated().any() or _column(calendar, "index").duplicated().any():
        raise ValueError("inconsistent date/calendar_index mapping")
    if not _column(calendar.sort_values("date"), "index").is_monotonic_increasing:
        raise ValueError("inconsistent date/calendar_index order")
    return dates


def attach_context(frame: pd.DataFrame, context_rows: list[dict[str, Any]] | pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Validate and left-join exact same-date benchmark states, without filling."""
    dates = _validate_keys(frame)
    context = pd.DataFrame(context_rows).copy()
    required = ["asof_date", "security_id", "layer", "state", "information_cutoff", "missing_reason"]
    if context.empty and not len(context.columns):
        context = pd.DataFrame(columns=pd.Index(required))
    if not set(required).issubset(context.columns):
        raise ValueError("missing context contract columns")
    context["asof_date"] = _dates(_column(context, "asof_date"), "context asof_date")
    if _column(context, "asof_date").duplicated().any():
        raise ValueError("duplicate context dates")
    if not _column(context, "security_id").eq("TW:0050").all() or not _column(context, "layer").eq("past_only").all():
        raise ValueError("context requires TW:0050 past_only layer")
    if not _column(context, "state").isin(STATES).all():
        raise ValueError("invalid context state")
    cutoff = _dates(_column(context, "information_cutoff"), "information_cutoff")
    if cutoff.gt(_column(context, "asof_date")).any():
        raise ValueError("future information_cutoff")
    unknown = _column(context, "state").eq("unknown")
    if cast(pd.Series, context.loc[unknown, "missing_reason"]).isna().any() or cast(pd.Series, context.loc[~unknown, "missing_reason"]).notna().any():
        raise ValueError("context state/missing_reason mismatch")
    if {"market_state", "context_missing_reason"} & set(frame.columns):
        raise ValueError("context already attached")
    lookup = context.set_index("asof_date")
    joined = frame.copy()
    joined["asof_date"] = dates
    joined["market_state"] = dates.map(_column(lookup, "state")).fillna("unknown")
    joined["context_missing_reason"] = dates.map(_column(lookup, "missing_reason")).astype(object)
    missing = ~dates.isin(_column(context, "asof_date"))
    joined.loc[missing, "context_missing_reason"] = "missing_context_date"
    audit = {
        "atlas_rows": len(frame),
        "joined_rows": len(joined),
        "context_rows": len(context),
        "missing_context_rows": int(missing.sum()),
        "missing_context_dates": int(cast(pd.Series, dates[missing]).nunique()),
        "unknown_context_rows": int(_column(joined, "market_state").eq("unknown").sum()),
    }
    LOGGER.info("Attached context rows=%d missing=%d unknown=%d", len(joined), audit["missing_context_rows"], audit["unknown_context_rows"])
    return joined, audit


def _validate_analysis(frame: pd.DataFrame) -> None:
    dates = _validate_keys(frame)
    if not _column(frame, "year").eq(dates.dt.year).all() or not dates.dt.year.between(2019, 2026).all():
        raise ValueError("year must match date within 2019-2026")
    if not _column(frame, "market_state").isin(STATES).all():
        raise ValueError("invalid market_state")
    for flag in ("base_eligible", "complete_63", "complete_126"):
        # dtype checking avoids a Python callback on millions of boolean rows.
        values = _column(frame, flag)
        if not pd.api.types.is_bool_dtype(values) or values.isna().any():
            raise ValueError(f"{flag} requires nonmissing booleans")
    for flag in (*FAMILIES, "F37", "label_63", "label_126"):
        if not _column(frame, flag).dropna().isin([0, 1]).all():
            raise ValueError(f"{flag} requires binary values or missing")
    for horizon in (63, 126):
        if (_column(frame, f"label_{horizon}").notna() & ~_column(frame, f"complete_{horizon}")).any():
            raise ValueError(f"known label_{horizon} requires complete path")
        for metric in (*PATH_METRICS, "wait_to_threshold"):
            values = _column(frame, f"{metric}_{horizon}")
            if not pd.api.types.is_numeric_dtype(values):
                raise ValueError(f"{metric}_{horizon} requires numeric values")
            if not np.isfinite(values.dropna()).all():
                raise ValueError(f"{metric}_{horizon} requires finite values or missing")


def _distribution(values: pd.Series) -> dict[str, Any]:
    known = values.dropna()
    result: dict[str, Any] = {"count": int(len(known)), "missing": int(values.isna().sum())}
    if known.empty:
        return {**result, "mean": None, "p10": None, "median": None, "p90": None}
    quantiles = cast(pd.Series, known.quantile([0.1, 0.5, 0.9]))
    return {**result, "mean": float(known.mean()), "p10": float(quantiles.iloc[0]), "median": float(quantiles.iloc[1]), "p90": float(quantiles.iloc[2])}


def _groups(frame: pd.DataFrame) -> Iterator[tuple[str | None, int | str | None, pd.DataFrame]]:
    yield None, None, frame
    for column in ("market_state", "year"):
        for value, group in frame.groupby(column, observed=True, sort=False, dropna=False):
            yield column, int(cast(Any, value)) if column == "year" else str(value), group


def _paths(frame: pd.DataFrame, panel: str, family: str) -> tuple[list[dict[str, Any]], dict[tuple[Any, ...], tuple[int, int]]]:
    rows: list[dict[str, Any]] = []
    distinct: dict[tuple[Any, ...], tuple[int, int]] = {}
    for context, value, group in _groups(frame):
        for arm in ARMS:
            selected = _column(group, arm).eq(1).fillna(False)
            for horizon in (63, 126):
                label = f"label_{horizon}"
                known = selected & _column(group, label).notna()
                chosen = cast(pd.DataFrame, group.loc[known])
                distinct[(arm, label, context, value)] = (int(_column(chosen, "security_id").nunique()), int(_column(chosen, "asof_date").nunique()))
                for outcome, subset in (
                    ("all", chosen),
                    ("winner", cast(pd.DataFrame, chosen.loc[_column(chosen, label).eq(1)])),
                    ("nonwinner", cast(pd.DataFrame, chosen.loc[_column(chosen, label).eq(0)])),
                ):
                    row: dict[str, Any] = {
                        "panel": panel,
                        "family": family,
                        "arm": arm,
                        "label": label,
                        "context_column": context,
                        "context_value": value,
                        "outcome": outcome,
                        "selected_known": len(subset),
                        "selected_distinct_issuers": int(_column(subset, "security_id").nunique()),
                        "selected_distinct_dates": int(_column(subset, "asof_date").nunique()),
                        "metrics": {metric: _distribution(_column(subset, f"{metric}_{horizon}")) for metric in PATH_METRICS},
                    }
                    if outcome == "winner":
                        row["metrics"]["wait_to_threshold"] = _distribution(_column(subset, f"wait_to_threshold_{horizon}"))
                    rows.append(row)
    return rows, distinct


def _paired(comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = {(r["panel"], r["family"], r["label"], r["context_column"], r["context_value"], r["arm"]): r for r in comparisons}
    rows = []
    for row in comparisons:
        for control in ("method", "relative_strength"):
            if row["arm"] == control:
                continue
            key = (row["panel"], row["family"], row["label"], row["context_column"], row["context_value"], control)
            baseline = indexed[key]
            conjunction_key = (*key[:-1], "conjunction")
            retained = baseline["tp"] if row["arm"] == "all" else indexed[conjunction_key]["tp"]
            result = {k: row[k] for k in ("panel", "family", "arm", "label", "context_column", "context_value")}
            result.update(
                control=control,
                candidate_tp=row["tp"],
                control_tp=baseline["tp"],
                retained_winners=retained,
                winner_retention=retained / baseline["tp"] if baseline["tp"] else None,
            )
            result["differences"] = {
                metric: row[metric] - baseline[metric] if row[metric] is not None and baseline[metric] is not None else None
                for metric in (
                    "precision",
                    "nonwinner_among_selected",
                    "winner_coverage",
                    "selected_known",
                    "tp",
                    "fp",
                    "fn",
                    "tn",
                    "precision_lower",
                    "precision_upper",
                )
            }
            rows.append(result)
    return rows


def _triage(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    index = {(r["panel"], r["family"], r["arm"], r["context_column"], r["context_value"]): r for r in comparisons if r["label"] == "label_126"}
    candidates = []
    for family in FAMILIES:
        for arm in ("method", "conjunction"):
            reasons = []
            panels = {}
            for panel in ("daily", "grid126"):
                candidate = index[(panel, family, arm, None, None)]
                control = index[(panel, family, "relative_strength", None, None)]
                retained = index[(panel, family, "conjunction", None, None)]["tp"]
                retention = retained / control["tp"] if control["tp"] else None
                panels[panel] = {
                    "selected_known": candidate["selected_known"],
                    "selected_distinct_issuers": candidate["selected_distinct_issuers"],
                    "precision": candidate["precision"],
                    "rs_precision": control["precision"],
                    "candidate_tp": candidate["tp"],
                    "rs_tp": control["tp"],
                    "retained_winners": retained,
                    "winner_retention": retention,
                }
                if candidate["selected_known"] < 30:
                    reasons.append(f"{panel}:selected_known_below_30")
                if candidate["selected_distinct_issuers"] < 10:
                    reasons.append(f"{panel}:selected_issuers_below_10")
                if candidate["precision"] is None or control["precision"] is None or candidate["precision"] <= control["precision"]:
                    reasons.append(f"{panel}:precision_not_above_rs")
                if retention is None or retention < 0.25:
                    reasons.append(f"{panel}:winner_retention_below_25pct_or_undefined")
            years = []
            for year in range(2019, 2026):
                annual_candidate = index.get(("daily", family, arm, "year", year))
                annual_control = index.get(("daily", family, "relative_strength", "year", year))
                if (
                    annual_candidate is not None
                    and annual_control is not None
                    and annual_candidate["selected_known"] >= 30
                    and annual_control["selected_known"] >= 30
                ):
                    years.append({
                        "year": year,
                        "precision": annual_candidate["precision"],
                        "rs_precision": annual_control["precision"],
                        "higher_precision": annual_candidate["precision"] > annual_control["precision"],
                    })
            wins = sum(year["higher_precision"] for year in years)
            if len(years) < 4:
                reasons.append("fewer_than_four_evaluable_years")
            if wins * 2 <= len(years):
                reasons.append("no_strict_annual_majority")
            retentions = [p["winner_retention"] for p in panels.values()]
            minimum = min(retentions) if all(value is not None for value in retentions) else None
            candidates.append({
                "family": family,
                "arm": arm,
                "qualifies": not reasons,
                "reasons": reasons,
                "panels": panels,
                "evaluable_years": years,
                "higher_precision_years": wins,
                "minimum_winner_retention": minimum,
            })
    qualifying = [row for row in candidates if row["qualifies"]]
    qualifying.sort(key=lambda row: (-row["minimum_winner_retention"], FAMILIES.index(row["family"]), ("method", "conjunction").index(row["arm"])))
    nominee = qualifying[0] if qualifying else None
    nomination = None
    if nominee is not None:
        nomination = {
            "family": nominee["family"],
            "arm": nominee["arm"],
            "minimum_winner_retention": nominee["minimum_winner_retention"],
            "pooled_unknown_label_bounds": [
                {k: r[k] for k in ("panel", "selected_unknown", "precision_lower", "precision_upper")}
                for r in comparisons
                if r["family"] == nominee["family"] and r["arm"] == nominee["arm"] and r["label"] == "label_126" and r["context_column"] is None
            ],
        }
    return {"candidates": candidates, "nomination": nomination, "provisional_not_strategy_approval": True}


def analyze(frame: pd.DataFrame) -> dict[str, Any]:
    """Analyze fixed daily/original-grid families; never read or recompute data."""
    _validate_analysis(frame)
    eligible = cast(pd.DataFrame, frame.loc[_column(frame, "base_eligible")])
    comparisons: list[dict[str, Any]] = []
    paths: list[dict[str, Any]] = []
    keys = ["security_id", "asof_date", "base_eligible", "year", "market_state", "label_63", "label_126"]
    metrics = [f"{metric}_{horizon}" for horizon in (63, 126) for metric in (*PATH_METRICS, "wait_to_threshold")]
    for panel in ("daily", "grid126"):
        population = eligible if panel == "daily" else cast(pd.DataFrame, eligible.loc[_column(eligible, "calendar_index").mod(126).eq(0)])
        for family in FAMILIES:
            working = cast(pd.DataFrame, population[[*keys, *metrics]]).copy()
            support = _column(population, family).notna() & _column(population, "F37").notna()
            working["all"] = np.where(support, 1.0, np.nan)
            working["method"] = _column(population, family).where(support)
            working["relative_strength"] = _column(population, "F37").where(support)
            working["conjunction"] = (_column(population, family).eq(1) & _column(population, "F37").eq(1)).astype(float).where(support)
            rows = binary_comparison(cast(pd.DataFrame, working[keys + list(ARMS)]), list(ARMS), ["market_state", "year"])
            path_rows, distinct = _paths(working, panel, family)
            for row in rows:
                row.update(panel=panel, family=family, arm=row.pop("feature"), outcome_role="primary" if row["label"] == "label_126" else "secondary")
                issuers, dates = distinct[(row["arm"], row["label"], row["context_column"], row["context_value"])]
                row.update(selected_distinct_issuers=issuers, selected_distinct_dates=dates)
            comparisons.extend(rows)
            paths.extend(path_rows)
            LOGGER.info("Analyzed panel=%s family=%s eligible=%d support=%d comparisons=%d", panel, family, len(working), int(support.sum()), len(rows))
    triage = _triage(comparisons)
    if triage["nomination"] is not None:
        nominee = triage["nomination"]
        nominee["nonwinner_paths"] = [
            r
            for r in paths
            if r["family"] == nominee["family"]
            and r["arm"] == nominee["arm"]
            and r["label"] == "label_126"
            and r["context_column"] is None
            and r["outcome"] == "nonwinner"
        ]
    result = {"comparisons": comparisons, "path_summaries": paths, "paired_rows": _paired(comparisons), "triage": triage}
    LOGGER.info("Completed interactions comparisons=%d paths=%d nomination=%s", len(comparisons), len(paths), triage["nomination"] is not None)
    return result
