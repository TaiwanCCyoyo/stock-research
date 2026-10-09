"""Fixed descriptive summaries of event anchors and existing atlas outcomes."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

OUTCOME_COLUMNS = [
    f"{name}_{horizon}"
    for horizon in (63, 126)
    for name in ("label", "complete", "unknown_reason", "max_return", "min_return", "max_drawdown", "forward_return", "wait_to_threshold")
]


def fraction(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def quantile(values: pd.Series, q: float) -> dict[str, Any]:
    known = values.dropna()
    value = float(known.quantile(q)) if len(known) else None
    return {"value": value if value is not None and math.isfinite(value) else None, "known": len(known), "unknown": len(values) - len(known)}


def describe(frame: pd.DataFrame, horizon: int) -> dict[str, Any]:
    """Eligibility first; null outcomes stay outside the point-rate denominator."""
    eligible = frame.loc[frame["base_eligible"].eq(True).fillna(False)]
    labels = eligible[f"label_{horizon}"]
    if not labels.dropna().isin([0, 1]).all():
        raise ValueError("atlas labels must be binary or null")
    known = int(labels.notna().sum())
    hits = int(labels.eq(1).sum())
    unknown = len(eligible) - known
    misses = eligible.loc[labels.eq(0).fillna(False)]
    winners = eligible.loc[labels.eq(1).fillna(False)]
    return {
        "rows": len(frame),
        "eligible": len(eligible),
        "ineligible": len(frame) - len(eligible),
        "securities": int(eligible["security_id"].nunique()),
        "known_securities": int(eligible.loc[labels.notna(), "security_id"].nunique()),
        "known": known,
        "hits": hits,
        "nonhits": known - hits,
        "unknown": unknown,
        "rate": fraction(hits, known),
        "unknown_lower": fraction(hits, len(eligible)),
        "unknown_upper": fraction(hits + unknown, len(eligible)),
        "nonhit_min_return_median": quantile(misses[f"min_return_{horizon}"], 0.5),
        "nonhit_min_return_p10": quantile(misses[f"min_return_{horizon}"], 0.1),
        "nonhit_max_drawdown_median": quantile(misses[f"max_drawdown_{horizon}"], 0.5),
        "hit_wait_median": quantile(winners[f"wait_to_threshold_{horizon}"], 0.5),
    }


def first_per_security(frame: pd.DataFrame) -> pd.DataFrame:
    """First eligible anchor BEFORE checking outcome; unknown firsts are not replaced."""
    eligible = frame.loc[frame["base_eligible"].eq(True).fillna(False)]
    return eligible.sort_values(["anchor_date", "breakout_date"], kind="stable").drop_duplicates("security_id", keep="first")


def event_groups(events: pd.DataFrame, prefix: str = "") -> list[tuple[str, str, str, pd.DataFrame]]:
    """Same fixed cuts at each actual anchor; never relabel breakthrough outcomes."""
    groups: list[tuple[str, str, str, pd.DataFrame]] = [
        (f"{prefix}pattern", "pooled", "all", events.loc[events["pattern"].eq(True)]),
        (f"{prefix}inside_big_range", "pooled", "all", events.loc[events["pattern"].eq(False)]),
        (f"{prefix}pattern_no_structure_cash_dividend", "pooled", "all", events.loc[events["pattern"].eq(True) & ~events["structure_cash_dividend"].eq(True)]),
    ]
    patterns = events.loc[events["pattern"].eq(True)]
    for cat in ("hhhl", "bottom", "range"):
        groups.append((f"{prefix}pattern", "cat", cat, patterns.loc[patterns["cat"].eq(cat)]))
    for context in ("clears", "after_decline", "inside_big_range"):
        groups.append((f"{prefix}detector_event", "context", context, events.loc[events["context"].eq(context)]))
    for year in range(2019, 2027):
        for family, selection in (("pattern", patterns), ("inside_big_range", events.loc[events["pattern"].eq(False)])):
            groups.append((f"{prefix}{family}", "year", str(year), selection.loc[selection["year"].eq(year)]))
    return groups


def summarize(
    events: pd.DataFrame, baseline: pd.DataFrame, controls: pd.DataFrame, noise: pd.DataFrame, transitions: pd.DataFrame | None = None
) -> list[dict[str, Any]]:
    """Only preregistered slices; no Cartesian combinations or parameter search."""
    groups = event_groups(events)
    groups.append(("noise", "pooled", "all", noise))
    if transitions is not None:
        for zone in ("z1", "z2"):
            for status in ("stood", "failed"):
                selected = transitions.loc[transitions["zone_name"].eq(zone) & transitions["status"].eq(status)]
                groups.extend(event_groups(selected, f"{zone}_{status}_"))
    output = []
    for horizon in (63, 126):
        bases: dict[str, dict[str, Any]] = {}
        control_rates: dict[str, float | None] = {}
        # Main no-any-event and secondary no-true-pattern are fixed same-day controls.
        for scope, b in [("pooled", baseline), *[(str(y), baseline.loc[baseline["year"].eq(y)]) for y in range(2019, 2027)]]:
            for family, selected in (
                ("all_stock_days", b),
                ("high_volume_no_event", controls.loc[controls["control_no_event"].eq(True)]),
                ("high_volume_no_pattern", controls.loc[controls["control_no_pattern"].eq(True)]),
            ):
                if family != "all_stock_days" and scope != "pooled":
                    selected = selected.loc[selected["year"].eq(int(scope))]
                description = describe(selected, horizon)
                if family == "all_stock_days":
                    bases[scope] = description
                elif family == "high_volume_no_event":
                    control_rates[scope] = description["rate"]
                output.append({
                    "family": family,
                    "slice": "year" if scope != "pooled" else "pooled",
                    "value": scope if scope != "pooled" else "all",
                    "sampling": "all_observations",
                    "horizon": horizon,
                    **description,
                })
        for family, slice_name, value, group in groups:
            scope = value if slice_name == "year" else "pooled"
            br, cr = bases[scope]["rate"], control_rates[scope]
            for sampling, selected in (("all_events", group), ("first_per_security", first_per_security(group))):
                d = describe(selected, horizon)
                rate = d["rate"]
                output.append({
                    "family": family,
                    "slice": slice_name,
                    "value": value,
                    "sampling": sampling,
                    "horizon": horizon,
                    **d,
                    "all_day_base_rate": br,
                    "no_event_control_rate": cr,
                    "lift_all_days": rate / br if rate is not None and br else None,
                    "lift_no_event_control": rate / cr if rate is not None and cr else None,
                })
    return output
