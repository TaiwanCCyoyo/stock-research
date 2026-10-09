"""Descriptive current-reference industry roles and bounded H03 comparisons.

Classification is current metadata, not point-in-time industry membership.
``laggard_turning`` means a positive short return below the long peer mean;
unequal lookbacks do not establish acceleration. No future outcome enters roles.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.feature_atlas_outcomes import binary_comparison

LOGGER = logging.getLogger(__name__)
CLASSIFICATION_BASIS = "current_metadata_reference_not_PIT"
ROLES = ("leader", "laggard_turning", "laggard_weak")
ARMS = ("all", "relative_strength", "peer_strong", "peer_strong_rs", "leader_strong", "turning_strong", "weak_strong")
CONTROLS = ("peer_strong", "peer_strong_rs", "relative_strength")
CANDIDATES = ("leader_strong", "turning_strong", "weak_strong")
STATES = ("up", "down", "consolidation", "mixed", "unknown")
PATH_METRICS = ("forward_return", "min_return", "max_drawdown")
MISSING_REASONS = ("ineligible", "missing_industry", "missing_returns", "insufficient_peers")


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    return cast(pd.Series, frame[name])


def _numeric(frame: pd.DataFrame, name: str) -> pd.Series:
    values = _column(frame, name)
    if not values.dropna().empty and (not pd.api.types.is_numeric_dtype(values) or pd.api.types.is_bool_dtype(values)):
        raise ValueError(f"{name} requires numeric finite values or missing")
    numeric = cast(pd.Series, pd.to_numeric(values, errors="raise"))
    if not np.isfinite(numeric.dropna().to_numpy(dtype=float)).all():
        raise ValueError(f"{name} requires finite values or missing")
    return numeric.astype(float)


def _boolean(frame: pd.DataFrame, name: str) -> None:
    values = _column(frame, name)
    if not pd.api.types.is_bool_dtype(values) or values.isna().any():
        raise ValueError(f"{name} requires nonmissing booleans")


def _validate_keys(frame: pd.DataFrame) -> pd.Series:
    keys = cast(pd.DataFrame, frame[["security_id", "asof_date"]])
    if keys.isna().to_numpy().any() or keys.duplicated().any():
        raise ValueError("missing or duplicate stock/date keys")
    if _column(frame, "security_id").astype(str).str.strip().eq("").any():
        raise ValueError("missing stock/date keys")
    values = _column(frame, "asof_date")
    dates = cast(pd.Series, pd.to_datetime(values, errors="raise"))
    if dates.isna().any() or dates.dt.tz is not None or not dates.eq(dates.dt.normalize()).all():
        raise ValueError("asof_date requires nonmissing timezone-naive calendar dates")
    if pd.api.types.is_object_dtype(values) or pd.api.types.is_string_dtype(values):
        if not values.astype(str).eq(dates.dt.strftime("%Y-%m-%d")).all():
            raise ValueError("asof_date requires ISO YYYY-MM-DD dates")
    indices = _numeric(frame, "calendar_index")
    if indices.isna().any() or not indices.ge(0).all() or not indices.mod(1).eq(0).all():
        raise ValueError("calendar_index requires nonnegative integers")
    calendar = pd.DataFrame({"date": dates, "index": indices}).drop_duplicates()
    if _column(calendar, "date").duplicated().any() or _column(calendar, "index").duplicated().any():
        raise ValueError("inconsistent date/calendar_index mapping")
    if not _column(calendar.sort_values("date"), "index").is_monotonic_increasing:
        raise ValueError("inconsistent date/calendar_index order")
    if not _column(frame, "year").eq(dates.dt.year).all() or not dates.dt.year.between(2019, 2026).all():
        raise ValueError("year must match date within 2019-2026")
    return dates


def _industry(frame: pd.DataFrame) -> pd.Series:
    values = _column(frame, "industry_ref")
    if pd.api.types.infer_dtype(values.dropna()) not in ("string", "unicode", "empty"):
        raise ValueError("industry_ref requires strings or missing")
    cleaned = values.astype("string").str.strip()
    return cleaned.mask(cleaned.eq("") | cleaned.str.upper().eq("UNKNOWN"))


def build_roles(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compute leave-one-out peer statistics by same-date industry, vectorized.

    A row contributes only when base eligible with both returns known. Exclude
    that contribution only for actual members; require five *other* members.
    Saved ranks affect common analysis support, never pool membership or roles.
    """
    dates = _validate_keys(frame)
    _boolean(frame, "base_eligible")
    if not _column(frame, "classification_basis").eq(CLASSIFICATION_BASIS).fillna(False).all():
        raise ValueError(f"classification_basis must be {CLASSIFICATION_BASIS}")
    industry = _industry(frame)
    ret20, ret60 = _numeric(frame, "ret20"), _numeric(frame, "ret60")
    rank = _numeric(frame, "rs60_percentile")
    if not rank.dropna().between(0, 1).all():
        raise ValueError("rs60_percentile requires ranks within [0, 1]")
    eligible = _column(frame, "base_eligible")
    returns_known = ret20.notna() & ret60.notna()
    member = eligible & industry.notna() & returns_known
    # Reset only the temporary calculation index, preserving arbitrary caller
    # indices (including repeated index labels) on the returned rows.
    pool = pd.DataFrame({
        "date": dates.to_numpy(),
        "industry": industry.to_numpy(),
        "count": member.to_numpy(dtype=int),
        "ret20": ret20.where(member, 0.0).to_numpy(),
        "ret60": ret60.where(member, 0.0).to_numpy(),
        "positive60": (member & ret60.gt(0)).to_numpy(dtype=int),
    })
    # Missing-industry rows contribute zero, never a member. Keeping that empty
    # group avoids pandas' all-missing-key transform failure; its denominator is
    # still zero and its peer statistics stay undefined.
    totals = cast(
        pd.DataFrame,
        pool.groupby(["date", "industry"], sort=False, observed=True, dropna=False)[["count", "ret20", "ret60", "positive60"]].transform("sum"),
    )
    count = _column(totals, "count").fillna(0).to_numpy(dtype=int) - member.to_numpy(dtype=int)
    denominator = np.where(count > 0, count, np.nan)
    mean20 = (_column(totals, "ret20").to_numpy() - ret20.where(member, 0.0).to_numpy()) / denominator
    mean60 = (_column(totals, "ret60").to_numpy() - ret60.where(member, 0.0).to_numpy()) / denominator
    breadth = (_column(totals, "positive60").to_numpy() - (member & ret60.gt(0)).to_numpy(dtype=int)) / denominator
    sufficient = pd.Series(count >= 5, index=frame.index)
    known = member & sufficient
    role = pd.Series("unknown", index=frame.index, dtype=object)
    leader = known & (ret60.ge(mean60) | np.isclose(ret60.to_numpy(), mean60, rtol=0, atol=1e-12))
    role.loc[leader] = "leader"
    role.loc[known & ~leader & ret20.gt(0)] = "laggard_turning"
    role.loc[known & ~leader & ret20.le(0)] = "laggard_weak"
    reason = pd.Series(None, index=frame.index, dtype=object)
    reason.loc[~sufficient] = "insufficient_peers"
    reason.loc[~returns_known] = "missing_returns"
    reason.loc[industry.isna()] = "missing_industry"
    reason.loc[~eligible] = "ineligible"
    reason.loc[known] = None
    strength = np.where(count >= 5, np.where((mean60 > 0) & (breadth >= 0.60), "strong", "other"), "unknown")
    result = frame.copy()
    result["peer_count"] = count
    result["peer_mean_ret20"] = mean20
    result["peer_mean_ret60"] = mean60
    result["peer_positive60_fraction"] = breadth
    result["role"] = role
    result["role_missing_reason"] = reason
    result["peer_strength"] = strength
    support = known & rank.notna()
    audit: dict[str, Any] = {
        "classification_basis": CLASSIFICATION_BASIS,
        "descriptive_not_PIT": True,
        "turning_definition": "short_positive_proxy_not_proven_acceleration",
        "n_input": len(frame),
        "n_eligible": int(eligible.sum()),
        "n_ineligible": int((~eligible).sum()),
        "n_peer_pool": int(member.sum()),
        "n_role_known": int(known.sum()),
        "n_role_unknown": int((~known).sum()),
        "n_support": int(support.sum()),
        "n_support_missing": int((~support).sum()),
        "n_eligible_support": int((eligible & support).sum()),
        "n_eligible_support_missing": int((eligible & ~support).sum()),
        "n_missing_rs60_percentile": int(rank.isna().sum()),
        "role_counts": {value: int(role.eq(value).sum()) for value in (*ROLES, "unknown")},
        "missing_reason_counts": {value: int(reason.eq(value).sum()) for value in MISSING_REASONS},
        "peer_strength_counts": {value: int((strength == value).sum()) for value in ("strong", "other", "unknown")},
    }
    LOGGER.info("Built industry roles input=%d pool=%d known=%d support=%d", len(frame), audit["n_peer_pool"], audit["n_role_known"], audit["n_support"])
    return result, audit


def _validate_outcomes(frame: pd.DataFrame) -> None:
    if not _column(frame, "market_state").isin(STATES).all():
        raise ValueError("invalid market_state")
    for horizon in (63, 126):
        _boolean(frame, f"complete_{horizon}")
        label = _numeric(frame, f"label_{horizon}")
        if not label.dropna().isin([0, 1]).all():
            raise ValueError(f"label_{horizon} requires binary values or missing")
        known = label.notna()
        if (known & ~_column(frame, f"complete_{horizon}")).any():
            raise ValueError(f"known label_{horizon} requires complete path")
        for metric in (*PATH_METRICS, "wait_to_threshold"):
            values = _numeric(frame, f"{metric}_{horizon}")
            required = label.eq(1) if metric == "wait_to_threshold" else known
            if (required & values.isna()).any():
                raise ValueError(f"known label_{horizon} requires finite {metric}_{horizon}")


def _groups(frame: pd.DataFrame) -> Iterator[tuple[str | None, int | str | None, pd.DataFrame]]:
    yield None, None, frame
    for column in ("year", "market_state", "industry_ref"):
        for value, group in frame.groupby(column, observed=True, sort=False, dropna=False):
            normalized = None if cast(bool, pd.isna(value)) else int(cast(Any, value)) if column == "year" else str(value)
            yield column, normalized, group


def _distribution(values: pd.Series) -> dict[str, Any]:
    known = values.dropna()
    row: dict[str, Any] = {"count": len(known), "missing": int(values.isna().sum())}
    if known.empty:
        return {**row, "mean": None, "p10": None, "median": None, "p90": None}
    quantiles = cast(pd.Series, known.quantile([0.1, 0.5, 0.9]))
    return {**row, "mean": float(known.mean()), "p10": float(quantiles.iloc[0]), "median": float(quantiles.iloc[1]), "p90": float(quantiles.iloc[2])}


def _summaries(frame: pd.DataFrame, panel: str, comparisons: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    indexed = {(r["arm"], r["label"], r["context_column"], r["context_value"]): r for r in comparisons}
    paths, pairs = [], []
    for context, value, group in _groups(frame):
        selections = {arm: _column(group, arm).eq(1).fillna(False) for arm in ARMS}
        for horizon in (63, 126):
            label = f"label_{horizon}"
            winners = _column(group, label).eq(1).fillna(False)
            for arm in ARMS:
                row = indexed[(arm, label, context, value)]
                chosen = cast(pd.DataFrame, group.loc[selections[arm] & _column(group, label).notna()])
                row.update(
                    selected_distinct_issuers=int(_column(chosen, "security_id").nunique()), selected_distinct_dates=int(_column(chosen, "asof_date").nunique())
                )
                for outcome, subset in (
                    ("all", chosen),
                    ("winner", cast(pd.DataFrame, chosen.loc[_column(chosen, label).eq(1)])),
                    ("nonwinner", cast(pd.DataFrame, chosen.loc[_column(chosen, label).eq(0)])),
                ):
                    metrics = {metric: _distribution(_column(subset, f"{metric}_{horizon}")) for metric in PATH_METRICS}
                    if outcome == "winner":
                        metrics["wait_to_threshold"] = _distribution(_column(subset, f"wait_to_threshold_{horizon}"))
                    paths.append({
                        "panel": panel,
                        "arm": arm,
                        "label": label,
                        "context_column": context,
                        "context_value": value,
                        "outcome": outcome,
                        "selected_known": len(subset),
                        "selected_distinct_issuers": int(_column(subset, "security_id").nunique()),
                        "selected_distinct_dates": int(_column(subset, "asof_date").nunique()),
                        "metrics": metrics,
                    })
                if arm in CONTROLS:
                    continue
                for control in CONTROLS:
                    baseline = indexed[(control, label, context, value)]
                    retained = int((winners & selections[arm] & selections[control]).sum())
                    pairs.append({
                        "panel": panel,
                        "arm": arm,
                        "control": control,
                        "label": label,
                        "context_column": context,
                        "context_value": value,
                        "candidate_tp": row["tp"],
                        "control_tp": baseline["tp"],
                        "retained_winners": retained,
                        "winner_retention": retained / baseline["tp"] if baseline["tp"] else None,
                        "differences": {
                            metric: row[metric] - baseline[metric] if row[metric] is not None and baseline[metric] is not None else None
                            for metric in (
                                "precision",
                                "winner_coverage",
                                "nonwinner_among_selected",
                                "selected_known",
                                "tp",
                                "fp",
                                "fn",
                                "tn",
                                "precision_lower",
                                "precision_upper",
                            )
                        },
                    })
    return paths, pairs


def _triage(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the fixed provisional rule; diagnostic slices cannot rescue it."""
    indexed = {(r["panel"], r["arm"], r["context_column"], r["context_value"]): r for r in comparisons if r["label"] == "label_126"}
    candidates = []
    for arm in CANDIDATES:
        insufficient, failed, panels, years = [], [], {}, []
        deltas: list[float] = []
        for panel in ("daily", "grid126"):
            candidate = indexed[(panel, arm, None, None)]
            controls = {control: indexed[(panel, control, None, None)] for control in ("peer_strong", "peer_strong_rs")}
            panels[panel] = {
                "selected_known": candidate["selected_known"],
                "selected_distinct_issuers": candidate["selected_distinct_issuers"],
                "precision": candidate["precision"],
                "controls": {
                    control: {key: row[key] for key in ("selected_known", "selected_distinct_issuers", "precision")} for control, row in controls.items()
                },
            }
            candidate_supported = candidate["selected_known"] >= 30 and candidate["selected_distinct_issuers"] >= 10
            if not candidate_supported:
                insufficient.append(f"{panel}:candidate_support_below_30_rows_or_10_issuers")
            for control, baseline in controls.items():
                control_supported = baseline["selected_known"] >= 30 and baseline["selected_distinct_issuers"] >= 10
                if not control_supported:
                    insufficient.append(f"{panel}:{control}:insufficient_comparator")
                elif candidate_supported and (
                    candidate["precision"] is None or baseline["precision"] is None or candidate["precision"] <= baseline["precision"]
                ):
                    failed.append(f"{panel}:precision_not_above_{control}")
            rs_precision = controls["peer_strong_rs"]["precision"]
            if candidate["precision"] is not None and rs_precision is not None:
                deltas.append(candidate["precision"] - rs_precision)
        for year in range(2019, 2026):
            annual_candidate = indexed.get(("daily", arm, "year", year))
            annual_baseline = indexed.get(("daily", "peer_strong_rs", "year", year))
            if (
                annual_candidate is not None
                and annual_baseline is not None
                and annual_candidate["selected_known"] >= 30
                and annual_baseline["selected_known"] >= 30
            ):
                years.append({
                    "year": year,
                    "precision": annual_candidate["precision"],
                    "peer_strong_rs_precision": annual_baseline["precision"],
                    "higher_precision": annual_candidate["precision"] > annual_baseline["precision"],
                })
        wins = sum(year["higher_precision"] for year in years)
        if len(years) < 4:
            insufficient.append("fewer_than_four_evaluable_years")
        elif wins * 2 <= len(years):
            failed.append("no_strict_annual_majority")
        candidates.append({
            "arm": arm,
            "qualifies": not insufficient and not failed,
            "status": "insufficient_evidence" if insufficient else "failed_provisional_rule" if failed else "qualifies",
            "reasons": [*insufficient, *failed],
            "insufficient_evidence_reasons": insufficient,
            "failed_precision_reasons": failed,
            "panels": panels,
            "evaluable_years": years,
            "higher_precision_years": wins,
            "minimum_precision_delta_vs_peer_strong_rs": min(deltas) if len(deltas) == 2 else None,
        })
    qualifiers = [row for row in candidates if row["qualifies"]]
    qualifiers.sort(key=lambda row: (-row["minimum_precision_delta_vs_peer_strong_rs"], CANDIDATES.index(row["arm"])))
    nominee = qualifiers[0] if qualifiers else None
    nomination = (
        None
        if nominee is None
        else {
            "arm": nominee["arm"],
            "minimum_precision_delta_vs_peer_strong_rs": nominee["minimum_precision_delta_vs_peer_strong_rs"],
            "purpose": "account_design_only",
            "pooled_unknown_label_bounds": [
                {key: row[key] for key in ("panel", "selected_unknown", "precision_lower", "precision_upper")}
                for row in comparisons
                if row["arm"] == nominee["arm"] and row["label"] == "label_126" and row["context_column"] is None
            ],
        }
    )
    return {"candidates": candidates, "nomination": nomination, "provisional_not_strategy_approval": True}


def analyze(frame: pd.DataFrame) -> dict[str, Any]:
    """Compare seven arms on identical support, daily and original grid126."""
    roles, audit = build_roles(frame)
    _validate_outcomes(roles)
    eligible = cast(pd.DataFrame, roles.loc[_column(roles, "base_eligible")]).copy()
    eligible["industry_ref"] = _industry(eligible)
    # A null context is also a category, to keep the declared row bound exact.
    if _column(eligible, "industry_ref").nunique(dropna=False) > 64:
        raise ValueError("industry_ref exceeds 64 eligible context categories")
    support = _column(eligible, "role").isin(ROLES) & _column(eligible, "rs60_percentile").notna()
    strong = _column(eligible, "peer_strength").eq("strong")
    rs = _column(eligible, "rs60_percentile").ge(0.8)
    flags = {"all": pd.Series(True, index=eligible.index), "relative_strength": rs, "peer_strong": strong, "peer_strong_rs": strong & rs}
    flags.update({arm: strong & _column(eligible, "role").eq(role) for arm, role in zip(CANDIDATES, ROLES, strict=True)})
    for arm, flag in flags.items():
        eligible[arm] = flag.astype(float).where(support)
    comparisons, paths, pairs = [], [], []
    for panel in ("daily", "grid126"):
        population = eligible if panel == "daily" else cast(pd.DataFrame, eligible.loc[_column(eligible, "calendar_index").mod(126).eq(0)])
        rows = binary_comparison(population, list(ARMS), ["year", "market_state", "industry_ref"])
        for row in rows:
            row.update(panel=panel, arm=row.pop("feature"), outcome_role="primary" if row["label"] == "label_126" else "secondary")
        path_rows, paired_rows = _summaries(population, panel, rows)
        comparisons.extend(rows)
        paths.extend(path_rows)
        pairs.extend(paired_rows)
        LOGGER.info("Analyzed industry roles panel=%s eligible=%d comparisons=%d", panel, len(population), len(rows))
    if len(comparisons) > 2184:
        raise ValueError("industry comparison row bound exceeded")
    triage = _triage(comparisons)
    if triage["nomination"] is not None:
        nominee = triage["nomination"]
        nominee["nonwinner_paths"] = [
            row
            for row in paths
            if row["arm"] == nominee["arm"] and row["label"] == "label_126" and row["context_column"] is None and row["outcome"] == "nonwinner"
        ]
    return {"comparisons": comparisons, "path_summaries": paths, "paired_rows": pairs, "triage": triage, "role_audit": audit}
