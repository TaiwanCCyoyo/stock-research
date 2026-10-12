"""Attach descriptive matched controls to already aggregated HHHL summaries."""

from __future__ import annotations

import math
from collections.abc import Sequence
from fractions import Fraction
from typing import Any

import pandas as pd

from research_core.hhhl_variants_features import FEATURES
from research_core.hhhl_variants_rates import YEARS
from research_core.hhhl_variants_selection import Candidate

_KINDS = {"baseline", "single", "candidate"}
_COLUMNS = (
    "row_kind",
    "base_row_kind",
    "cohort_id",
    "split_id",
    "horizon",
    "candidate_id",
    "feature_id",
    "bin_id",
    "year",
    "removed_year",
    "hit_n",
    "loss_n",
    "flat_win_n",
    "hit_rate",
    "loss_rate",
    "not_applicable_reason",
)


def _null(value: Any) -> Any:
    return None if value is None or pd.isna(value) else value


def _finite(value: Any) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(value)


def _condition(row: dict[str, Any]) -> tuple[Any, ...]:
    return row["base_row_kind"], row["candidate_id"], row["feature_id"], row["bin_id"]


def _span(row: dict[str, Any]) -> tuple[str, Any]:
    if row["row_kind"] == "year":
        return "year", row["year"]
    if row["row_kind"] == "drop_best_year":
        return "drop", row["removed_year"]
    return "pooled", None


def _unsupported(row: dict[str, Any]) -> bool:
    return row["not_applicable_reason"] is not None or row["bin_id"] == "not_applicable"


def attach_references(summary: pd.DataFrame, candidates: Sequence[Candidate]) -> pd.DataFrame:
    """Match point rates by fixed condition and the target's own calendar slice.

    A sensitivity reference sums control YEAR counts after removing the target
    year. It never substitutes the control's independently chosen best year.
    """
    if summary.empty:
        result = summary.copy()
        result["reference_kind"] = pd.Series(dtype="object")
        result["high_loss"] = pd.Series(dtype="bool")
        return result
    missing = set(_COLUMNS).difference(summary.columns)
    if missing:
        raise ValueError(f"missing summary reference columns: {sorted(missing)}")
    candidate_map: dict[str, Candidate] = {}
    for candidate in candidates:
        if candidate.candidate_id in candidate_map:
            raise ValueError("duplicate candidate identity")
        candidate_map[candidate.candidate_id] = candidate
    # Values contain only three counts and an applicability flag, never records.
    lookup: dict[tuple[Any, ...], tuple[int, int, int] | None] = {}
    projected = summary[list(_COLUMNS)]
    for values in projected.itertuples(index=False, name=None):
        row = {name: _null(value) for name, value in zip(_COLUMNS, values, strict=True)}
        if row["base_row_kind"] not in _KINDS or row["row_kind"] == "drop_best_year":
            continue
        key = (row["cohort_id"], row["split_id"], row["horizon"], *_condition(row), *_span(row))
        if key in lookup:
            raise ValueError("duplicate summary reference key")
        lookup[key] = None if _unsupported(row) else (int(row["hit_n"]), int(row["loss_n"]), int(row["flat_win_n"]))

    memo: dict[tuple[Any, ...], tuple[tuple[int, int, int] | None, str | None]] = {}

    def reference(cohort: str, row: dict[str, Any], condition: tuple[Any, ...]) -> tuple[tuple[int, int, int] | None, str | None]:
        span, value = _span(row)
        prefix = (cohort, row["split_id"], row["horizon"], *condition)
        memo_key = (*prefix, span, value)
        if memo_key not in memo:
            if span != "drop":
                key = (*prefix, span, value)
                if key not in lookup:
                    memo[memo_key] = None, "missing_reference_slice"
                elif lookup[key] is None:
                    memo[memo_key] = None, "reference_not_applicable"
                else:
                    memo[memo_key] = lookup[key], None
            else:
                counts = [0, 0, 0]
                reason = None
                for year in YEARS:
                    if year == value:
                        continue
                    key = (*prefix, "year", year)
                    batch = lookup.get(key)
                    if key not in lookup or batch is None:
                        reason = "missing_reference_year" if key not in lookup else "reference_not_applicable"
                        break
                    for index, count in enumerate(batch):
                        counts[index] += count
                memo[memo_key] = ((counts[0], counts[1], counts[2]), None) if reason is None else (None, reason)
        return memo[memo_key]

    fields = ("hit_n", "loss_n", "known_n", "hit_rate", "loss_rate", "hit_delta", "loss_delta", "reason")
    additions: dict[str, list[Any]] = {"reference_kind": [], "reference_removed_year": [], "high_loss": []}
    additions.update({f"reference_{name}_{field}": [] for name in ("cnh", "c52w", "pall") for field in fields})
    for values in projected.itertuples(index=False, name=None):
        row = {name: _null(value) for name, value in zip(_COLUMNS, values, strict=True)}
        usable = row["base_row_kind"] in _KINDS and not _unsupported(row)
        pattern_only = False
        unsupported_reason = "row_not_supported"
        if usable and row["base_row_kind"] == "single":
            feature = FEATURES.get(row["feature_id"])
            if feature is None:
                usable, unsupported_reason = False, "unknown_feature"
            else:
                pattern_only = feature.pattern_only
        elif usable and row["base_row_kind"] == "candidate":
            selected_candidate = candidate_map.get(row["candidate_id"])
            if selected_candidate is None:
                usable, unsupported_reason = False, "unknown_candidate"
            else:
                pattern_only = any(FEATURES[atom.feature_id].pattern_only for atom in selected_candidate.atoms)
        additions["reference_kind"].append("pattern_only_unfiltered" if usable and pattern_only else "matched_condition" if usable else None)
        additions["reference_removed_year"].append(row["removed_year"] if row["row_kind"] == "drop_best_year" else None)
        condition = ("baseline", None, None, None) if pattern_only else _condition(row)
        high_loss = False
        for name, cohort in (("cnh", "C-nh"), ("c52w", "C-52w"), ("pall", "P-all")):
            values_out: dict[str, Any] = dict.fromkeys(fields)
            if not usable:
                values_out["reason"] = "target_not_applicable" if _unsupported(row) else unsupported_reason
            elif name == "pall" and not pattern_only:
                values_out["reason"] = "reference_not_required"
            else:
                batch, reason = reference(cohort, row, condition)
                values_out["reason"] = reason
                if batch is not None:
                    hit, loss, flat = batch
                    known = hit + loss + flat
                    values_out.update(hit_n=hit, loss_n=loss, known_n=known)
                    if known:
                        values_out.update(hit_rate=hit / known, loss_rate=loss / known)
                        for outcome in ("hit", "loss"):
                            own_rate = row[f"{outcome}_rate"]
                            if _finite(own_rate):
                                values_out[f"{outcome}_delta"] = own_rate - values_out[f"{outcome}_rate"]
                        if name == "cnh" and _finite(row["loss_rate"]):
                            own_known = row["hit_n"] + row["loss_n"] + row["flat_win_n"]
                            if own_known:
                                high_loss = Fraction(int(row["loss_n"]), int(own_known)) - Fraction(loss, known) >= Fraction(1, 10)
                    else:
                        values_out["reason"] = "zero_known_reference"
            for field in fields:
                additions[f"reference_{name}_{field}"].append(values_out[field])
        additions["high_loss"].append(high_loss)
    result = summary.copy()
    for name, values in additions.items():
        result[name] = values
    return result
