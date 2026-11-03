"""Pure presentation contract for a fixed, previously verified L1 event cohort.

Outcomes come exclusively from the supplied projection, classifications from the
saved-condition adapter, and every count/rate from ``summarize_events``. This
module performs no market I/O, feature calculation, outcome reconstruction or
certification of the caller's provenance assertions.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from copy import deepcopy
from itertools import product
from typing import Any, cast

import pandas as pd

from research_core.pattern_scan_conditions_v1 import FEATURES
from research_core.pattern_scan_rates_v1 import summarize_events

SCHEMA_VERSION = "l1-volume-comparison.v1"
HORIZONS = (126, 252)
SOURCE_IDENTITY_COLUMNS = ("definition_id", "input_id", "base_label_version_id", "base_label_manifest_sha256")
STATUSES = ("known", "feature_unknown", "not_applicable")
CELL_GROUPS = tuple(product(("vol_le_0_7", "vol_gt_0_7"), ("g_ge_1_5", "g_lt_1_5")))
LOGGER = logging.getLogger(__name__)
RATE_DENOMINATORS = {
    "hit_rate": "known_n",
    "loss_rate": "known_n",
    "censored_hit_lower_bound": "censored_potential_n",
    "censored_hit_upper_bound": "censored_potential_n",
    "full_calendar_hit_lower_bound": "full_main_potential_n",
    "full_calendar_hit_upper_bound": "full_main_potential_n",
}
SEMANTICS = {
    "outcome_source": "research_core.pattern_scan_projection_v1.project_outcomes",
    "summary_source": "research_core.pattern_scan_rates_v1.summarize_events",
    "classification_source": "saved common_values via pattern_scan_conditions_v1.classify_column",
    "partition": "Fix L1 union event IDs before conditions; same classification at both horizons.",
    "boundaries": "VOL_a <= 0.7 / > 0.7; G >= 1.5 / < 1.5.",
    "count_overlap": "unknown_n and censored_n overlap; eligibility exclusions can overlap both. None is loss.",
    "stock_counts": "distinct_stock_n counts event-bearing stocks within this summary; do not add across cells or years.",
    "zero_denominator": "Rates and bounds are null when their denominator is zero.",
    "rate_denominators": RATE_DENOMINATORS,
    "references": "At most three deterministic input event references per cell; not a representative sample or a file/URL locator.",
    "provenance": "Caller assertions only. input_structure_verified means in-memory contract checks, not authentic-market-input certification.",
    "research_scope": "Synthetic and pilot cells are not evaluated research conclusions; historical exposure never becomes unseen validation.",
}


def _provenance(supplied: Mapping[str, Any], events: pd.DataFrame) -> dict[str, Any]:
    required = {
        "scope",
        "data_id",
        "input_id",
        "base_label_version_id",
        "base_label_manifest_sha256",
        "definition_id",
        "code_commit",
        "source_id",
        "generation",
        "actual_selected_stocks",
        "historical_exposed",
        "validation_scope",
    }
    if set(supplied) != required:
        raise ValueError("provenance requires the exact versioned fields")
    result = deepcopy(dict(supplied))
    if result["scope"] not in ("synthetic", "pilot", "full") or result["historical_exposed"] is not True:
        raise ValueError("scope must be synthetic/pilot/full and historical_exposed must be true")
    for key in ("data_id", "input_id", "base_label_version_id", "definition_id", "code_commit", "source_id", "generation"):
        if not isinstance(result[key], str) or not result[key].strip():
            raise ValueError(f"provenance {key} must be nonblank")
    manifest = result["base_label_manifest_sha256"]
    if not isinstance(manifest, str) or re.fullmatch(r"[0-9a-f]{64}", manifest) is None:
        raise ValueError("provenance base_label_manifest_sha256 must be a lowercase SHA256")
    if result["source_id"] != result["definition_id"]:
        raise ValueError("original numerical source_id must equal projected definition_id")
    for column in SOURCE_IDENTITY_COLUMNS:
        values = cast(pd.Series, events[column])
        if not values.map(lambda value: isinstance(value, str) and bool(value.strip())).all():
            raise ValueError(f"event {column} requires nonblank source identities")
        if values.nunique(dropna=False) > 1 or not values.eq(result[column]).all():
            raise ValueError(f"cohort {column} must match declared provenance")
    stocks = result["actual_selected_stocks"]
    if (
        not isinstance(stocks, (list, tuple))
        or not stocks
        or any(not isinstance(stock, str) or not stock.strip() for stock in stocks)
        or len(set(stocks)) != len(stocks)
    ):
        raise ValueError("actual_selected_stocks requires unique nonblank identities")
    if not set(events.security_id).issubset(stocks):
        raise ValueError("event stock is absent from actual_selected_stocks")
    if result["scope"] == "pilot" and len(stocks) > 5:
        raise ValueError("pilot permits at most five actual selected stocks")
    if result["scope"] == "synthetic" and any(not stock.startswith("SYNTH-") for stock in stocks):
        raise ValueError("synthetic stock identities must start with SYNTH-")
    result["actual_selected_stocks"] = sorted(stocks)
    validation = result["validation_scope"]
    fields = {"input_structure_verified", "full_q1_parity", "marginal_parity", "unseen_validation"}
    if not isinstance(validation, dict) or set(validation) != fields or any(type(value) is not bool for value in validation.values()):
        raise ValueError("validation_scope requires the exact explicit boolean fields")
    if not validation["input_structure_verified"] or validation["unseen_validation"]:
        raise ValueError("input structure must be verified and unseen validation must be false")
    complete = validation["full_q1_parity"] and validation["marginal_parity"]
    if result["scope"] == "full" and not complete:
        raise ValueError("full scope requires both caller-asserted full Q1 and marginal parity")
    if result["scope"] != "full" and (validation["full_q1_parity"] or validation["marginal_parity"]):
        raise ValueError("synthetic/pilot scope cannot claim full Q1 or marginal parity")
    return result


def _conditions(events: pd.DataFrame, conditions: pd.DataFrame) -> pd.DataFrame:
    required = {"event_id", *(f"{feature}_{field}" for feature in ("G", "VOL_a") for field in ("bin", "status", "reason"))}
    if not conditions.columns.is_unique or not required.issubset(conditions):
        raise ValueError("conditions require event_id and G/VOL_a bin/status/reason")
    rows = conditions.loc[:, sorted(required)].copy(deep=True)
    if rows.event_id.isna().any() or rows.event_id.duplicated().any() or set(rows.event_id) != set(events.event_id):
        raise ValueError("conditions require one-to-one complete event IDs")
    for feature in ("G", "VOL_a"):
        known = rows[f"{feature}_status"].eq("known")
        if not rows[f"{feature}_status"].isin(STATUSES).all():
            raise ValueError(f"invalid {feature} status")
        if not rows.loc[known, f"{feature}_bin"].isin(FEATURES[feature].bin_ids).all() or rows.loc[~known, f"{feature}_bin"].notna().any():
            raise ValueError(f"invalid {feature} classification bin")
        if (
            rows.loc[known, f"{feature}_reason"].notna().any()
            or not rows.loc[~known, f"{feature}_reason"].map(lambda value: isinstance(value, str) and bool(value.strip())).all()
        ):
            raise ValueError(f"invalid {feature} classification reason")
    rows["g_group"] = rows.G_bin.map({bin_id: "g_lt_1_5" if bin_id == "lt150" else "g_ge_1_5" for bin_id in FEATURES["G"].bin_ids})
    rows["vol_a_group"] = rows.VOL_a_bin.map({bin_id: "vol_le_0_7" if bin_id == "le070" else "vol_gt_0_7" for bin_id in FEATURES["VOL_a"].bin_ids})
    return rows


def _references(rows: pd.DataFrame) -> list[dict[str, Any]]:
    columns = ["event_id", "security_id", "t0", "horizon"]
    ordered = rows.sort_values(["security_id", "t0", "event_id", "horizon"], kind="stable")
    return ordered.loc[:, columns].head(3).to_dict(orient="records")


def _evaluation(scope: str) -> dict[str, str]:
    if scope == "synthetic":
        return {"status": "not_evaluated", "reason": "synthetic_only"}
    if scope == "pilot":
        return {"status": "not_evaluated", "reason": "pilot_only_no_full_research_validation"}
    return {"status": "evaluated", "reason": "historical_descriptive_only"}


def build_l1_comparison(events: pd.DataFrame, conditions: pd.DataFrame, *, provenance: Mapping[str, Any]) -> dict[str, Any]:
    """Partition already verified preserved L1 union events, without new rules.

    ``conditions`` has one row/event with G_bin/G_status/G_reason and the same
    VOL_a fields. It must come from the saved-condition adapter; raw values are
    ignored. ``actual_selected_stocks`` may include selected zero-event stocks.
    Projected definition/input/base-label identities must be present, uniform
    across the cohort and equal the declared provenance. The original numerical
    source_id is the projection's definition_id, as in the recovery adapter.
    This checks supplied metadata consistency, not external source authenticity.
    Full-scope provenance assertions require separate caller-side acceptance.
    """
    required = {"pattern_id", "cohort_id", "event_eligibility_excluded", *SOURCE_IDENTITY_COLUMNS}
    if not events.columns.is_unique or not required.issubset(events):
        raise ValueError("events require explicit L1 union, eligibility and source identity fields")
    summarize_events(events)
    if not events.pattern_id.eq("L1").all() or not events.cohort_id.eq("union").all():
        raise ValueError("comparison accepts only preserved L1 union events")
    if not events.horizon.isin(HORIZONS).all() or not events.groupby("event_id").horizon.nunique().eq(2).all():
        raise ValueError("each fixed event requires H126 and H252")
    for column in ("security_id", "t0", "pattern_id", "cohort_id", "subtype_id", "definition_id", "input_id", "calendar_index", "window_start"):
        if column in events and not bool(events.groupby("event_id")[column].nunique(dropna=False).eq(1).all()):
            raise ValueError(f"event {column} differs across horizons")
    source = _provenance(provenance, events)
    classified = _conditions(events, conditions)
    joined = events.merge(classified, on="event_id", how="left", validate="many_to_one", suffixes=("", "_condition"))
    if any(column in events for column in ("G_bin", "G_status", "G_reason", "VOL_a_bin", "VOL_a_status", "VOL_a_reason", "g_group", "vol_a_group")):
        raise ValueError("projected event columns collide with supplied conditions")
    horizons: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        rows = joined.loc[joined.horizon.eq(horizon)]
        cells = []
        for vol, g in CELL_GROUPS:
            selected = rows.loc[rows.vol_a_group.eq(vol) & rows.g_group.eq(g)]
            cells.append({
                "cell_id": f"{vol}__{g}",
                "vol_a_group": vol,
                "g_group": g,
                "summary": summarize_events(selected),
                "evaluation_status": _evaluation(source["scope"]),
                "references": _references(selected),
            })
        unavailable = []
        for g_status, vol_status in product(STATUSES, repeat=2):
            if (g_status, vol_status) == ("known", "known"):
                continue
            selected = rows.loc[rows.G_status.eq(g_status) & rows.VOL_a_status.eq(vol_status)]
            reason_counts = {
                feature: [
                    {"reason": reason, "event_n": int(count)} for reason, count in selected[f"{feature}_reason"].dropna().value_counts().sort_index().items()
                ]
                for feature in ("G", "VOL_a")
            }
            unavailable.append({
                "G_status": g_status,
                "VOL_a_status": vol_status,
                "summary": summarize_events(selected),
                "reason_counts": reason_counts,
                "evaluation_status": _evaluation(source["scope"]),
                "references": _references(selected),
            })
        horizons.append({"horizon": horizon, "cohort": summarize_events(rows), "cells": cells, "unavailable": unavailable})
    result = {
        "schema_version": SCHEMA_VERSION,
        "synthetic": source["scope"] == "synthetic",
        "provenance": source,
        "cohort": {"pattern_id": "L1", "cohort_id": "union", "horizons": list(HORIZONS), "event_n": int(events.event_id.nunique())},
        "semantics": deepcopy(SEMANTICS),
        "horizons": horizons,
    }
    LOGGER.info(
        "Built L1 comparison scope=%s events=%d selected_stocks=%d", source["scope"], result["cohort"]["event_n"], len(source["actual_selected_stocks"])
    )
    return result


def comparison_json_schema() -> dict[str, Any]:
    """Return the portable structural JSON Schema; provenance remains assertions."""

    def obj(properties: dict[str, Any]) -> dict[str, Any]:
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    text = {"type": "string", "minLength": 1}
    count = {"type": "integer", "minimum": 0}
    nullable = {"type": ["number", "null"], "minimum": 0}
    empty = pd.DataFrame(
        columns=pd.Index(("security_id", "event_id", "t0", "horizon", "effective_label", "calendar_full", "event_main_eligible", "event_eligibility_excluded"))
    )
    summary = obj({
        key: {**nullable, "maximum": 1} if key in RATE_DENOMINATORS else nullable if key == "per_stock_event_count_median" else count
        for key in summarize_events(empty)
    })
    evaluation = obj({"status": {"enum": ["evaluated", "not_evaluated"]}, "reason": text})
    references = {
        "type": "array",
        "maxItems": 3,
        "items": obj({"event_id": text, "security_id": text, "t0": {"type": "string", "format": "date"}, "horizon": {"enum": list(HORIZONS)}}),
    }
    common = {"summary": summary, "evaluation_status": evaluation, "references": references}
    reasons = {"type": "array", "items": obj({"reason": text, "event_n": count})}
    validation = obj({
        "input_structure_verified": {"const": True},
        "full_q1_parity": {"type": "boolean"},
        "marginal_parity": {"type": "boolean"},
        "unseen_validation": {"const": False},
    })
    provenance = obj({
        "scope": {"enum": ["synthetic", "pilot", "full"]},
        **{key: text for key in ("data_id", "input_id", "base_label_version_id", "definition_id", "code_commit", "source_id", "generation")},
        "base_label_manifest_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "actual_selected_stocks": {"type": "array", "minItems": 1, "uniqueItems": True, "items": text},
        "historical_exposed": {"const": True},
        "validation_scope": validation,
    })
    provenance["allOf"] = [
        {
            "if": {"properties": {"scope": {"const": scope}}},
            "then": {
                "properties": {
                    "validation_scope": {"properties": {key: {"const": scope == "full"} for key in ("full_q1_parity", "marginal_parity")}},
                    "actual_selected_stocks": {"maxItems": 5} if scope == "pilot" else {"items": {"pattern": "^SYNTH-"}} if scope == "synthetic" else {},
                }
            },
        }
        for scope in ("synthetic", "pilot", "full")
    ]
    cell = obj({
        "cell_id": {"enum": [f"{vol}__{g}" for vol, g in CELL_GROUPS]},
        "vol_a_group": {"enum": ["vol_le_0_7", "vol_gt_0_7"]},
        "g_group": {"enum": ["g_ge_1_5", "g_lt_1_5"]},
        **common,
    })
    unavailable = obj({
        "G_status": {"enum": list(STATUSES)},
        "VOL_a_status": {"enum": list(STATUSES)},
        **common,
        "reason_counts": obj({"G": reasons, "VOL_a": reasons}),
    })
    horizon = obj({
        "horizon": {"enum": list(HORIZONS)},
        "cohort": summary,
        "cells": {"type": "array", "minItems": 4, "maxItems": 4, "items": cell},
        "unavailable": {"type": "array", "minItems": 8, "maxItems": 8, "items": unavailable},
    })
    horizon["properties"]["cells"]["prefixItems"] = [
        {**cell, "properties": {**cell["properties"], "cell_id": {"const": f"{vol}__{g}"}, "vol_a_group": {"const": vol}, "g_group": {"const": g}}}
        for vol, g in CELL_GROUPS
    ]
    horizon["properties"]["unavailable"]["prefixItems"] = [
        {**unavailable, "properties": {**unavailable["properties"], "G_status": {"const": g}, "VOL_a_status": {"const": vol}}}
        for g, vol in product(STATUSES, repeat=2)
        if (g, vol) != ("known", "known")
    ]
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **obj({
            "schema_version": {"const": SCHEMA_VERSION},
            "synthetic": {"type": "boolean"},
            "provenance": provenance,
            "cohort": obj({"pattern_id": {"const": "L1"}, "cohort_id": {"const": "union"}, "horizons": {"const": list(HORIZONS)}, "event_n": count}),
            "semantics": {"const": SEMANTICS},
            "horizons": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "prefixItems": [{**horizon, "properties": {**horizon["properties"], "horizon": {"const": value}}} for value in HORIZONS],
                "items": False,
            },
        }),
    }
    schema["allOf"] = [
        {
            "if": {"properties": {"provenance": {"properties": {"scope": {"const": scope}}}}},
            "then": {"properties": {"synthetic": {"const": scope == "synthetic"}}},
        }
        for scope in ("synthetic", "pilot", "full")
    ]
    return deepcopy(schema)
