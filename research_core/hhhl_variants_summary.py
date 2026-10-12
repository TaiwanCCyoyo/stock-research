"""Incremental summaries of supplied HHHL observations, without market IO."""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from collections.abc import Sequence
from numbers import Integral
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.hhhl_variants_features import FEATURES
from research_core.hhhl_variants_rates import YEARS, RateAccumulator, descriptive_flag_rates
from research_core.hhhl_variants_selection import Atom, Candidate, candidate_id

LOGGER = logging.getLogger(__name__)
_COHORTS = {"P-clean", "P-over", "P-all", "C-nh", "C-52w", "C-base"}
_SPLITS = {"development", "cross-check"}
_LABELS = {"hit", "loss", "flat-win", "unknown"}
_STATES = {"known", "feature_unknown", "not_applicable"}
_RATE_FIELDS = ("hit_rate", "loss_rate", "hit_lower", "hit_upper", "loss_lower", "loss_upper", "censored_hit_lower", "censored_hit_upper")
_GROUP_COLUMNS = ["cohort_id", "split_id", "horizon"]
_IDENTITY_COLUMNS = ["row_kind", "candidate_id", "feature_id", "bin_id", *_GROUP_COLUMNS]
_PATH_DIAGNOSTICS = ("drawdown10_full_state", "drawdown20_full_state", "before_hit10_state", "before_hit20_state")


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    return cast(pd.Series, frame[name])


def _basis(feature_id: str | None) -> str:
    if feature_id in {"K2", "K3", "G2_limit"}:
        return "raw_price"
    if feature_id == "G":
        return "frozen_v4_vx"
    if feature_id == "I":
        return "atlas_causal_regime"
    if feature_id == "J":
        return "atlas_current_reference_industry"
    return "fixed_v4_factor"


def _applicable(feature_id: str, cohort_id: str) -> bool:
    definition = FEATURES[feature_id]
    # P-all contains both pattern cohorts. A's supplied row statuses retain
    # the P-over subset while leaving its P-clean rows not applicable.
    return not (definition.pattern_only and not cohort_id.startswith("P-")) and not (definition.overhead_only and cohort_id not in {"P-over", "P-all"})


class StudySummaries:
    """Accumulate all fixed cells; caller supplies already resolved features."""

    def __init__(self) -> None:
        self._rates = RateAccumulator()
        self._reasons: dict[tuple[Any, ...], dict[int, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
        self._outcome_reasons: dict[tuple[Any, ...], dict[int, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
        self._candidate_signature: tuple[tuple[str, tuple[Atom, ...]], ...] | None = None

    @staticmethod
    def _metadata(
        cohort: str, split: str, horizon: int, row_kind: str, identifier: str | None, feature_id: str | None, bin_id: str | None, outside: bool = False
    ) -> dict[str, Any]:
        return dict(
            row_kind=row_kind,
            candidate_id=identifier,
            feature_id=feature_id,
            bin_id=bin_id,
            cohort_id=cohort,
            split_id=split,
            horizon=int(horizon),
            landmark=None,
            riskset_id=None,
            feature_price_basis=_basis(feature_id),
            not_applicable_reason="outside_feature_cohort" if outside else None,
        )

    def initialize_group(self, cohort: str, split: str, horizon: int, candidates: Sequence[Candidate] = ()) -> None:
        """Register zero cells when a cohort/split/horizon has no source events."""
        if cohort not in _COHORTS or split not in _SPLITS or isinstance(horizon, bool) or not isinstance(horizon, Integral) or horizon not in (126, 252):
            raise ValueError("invalid empty cohort/split/horizon group")
        columns = ["calendar_full", "label", "year", "code", "event_id", *_GROUP_COLUMNS]
        columns.extend(f"{feature_id}_{suffix}" for feature_id in FEATURES for suffix in ("bin", "status", "reason"))
        self._validate(pd.DataFrame(columns=pd.Index(columns)), candidates)
        signature = tuple((candidate.candidate_id, candidate.atoms) for candidate in candidates)
        if self._candidate_signature is not None and self._candidate_signature != signature:
            raise ValueError("fixed candidate inventory changed between batches")
        self._candidate_signature = signature

        def register(kind: str, identifier: str | None, feature: str | None, bin_id: str | None, outside: bool = False) -> None:
            metadata = self._metadata(cohort, split, horizon, kind, identifier, feature, bin_id, outside)
            key = tuple(metadata[name] for name in _IDENTITY_COLUMNS)
            zero_counts = {"not_applicable_n": 0}
            zero_counts.update({f"{name.removesuffix('_state')}_{state}_n": 0 for name in _PATH_DIAGNOSTICS for state in ("triggered", "all_false", "unknown")})
            self._rates.add(key, metadata, 2019, zero_counts)

        register("baseline", None, None, None)
        for feature, definition in FEATURES.items():
            for bin_id in sorted(set(definition.bin_ids)):
                atom = Atom(definition.family, feature, bin_id, not definition.diagnostic_only)
                register("single", candidate_id((atom,)), feature, bin_id, not _applicable(feature, cohort))
            for status in ("feature_unknown", "not_applicable"):
                register("single", f"hhhl-v4-variants.v1:{feature}={status}", feature, status)
        for candidate in candidates:
            outside = any(not _applicable(atom.feature_id, cohort) for atom in candidate.atoms)
            register("candidate", candidate.candidate_id, None, None, outside)
            for feature in ("K", "K2", "K3"):
                for bin_id in (*sorted(set(FEATURES[feature].bin_ids)), "feature_unknown", "not_applicable"):
                    register("Kdistribution", candidate.candidate_id, feature, bin_id, outside)

    @staticmethod
    def _validate(frame: pd.DataFrame, candidates: Sequence[Candidate]) -> list[str]:
        required = {"calendar_full", "label", "year", "code", "event_id", *_GROUP_COLUMNS}
        for feature_id in FEATURES:
            required.update((f"{feature_id}_bin", f"{feature_id}_status", f"{feature_id}_reason"))
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"missing observation columns: {sorted(missing)}")
        for name, allowed in (("cohort_id", _COHORTS), ("split_id", _SPLITS), ("label", _LABELS), ("horizon", {126, 252}), ("year", set(YEARS))):
            column = _column(frame, name)
            if column.isna().any() or not column.isin(list(allowed)).all():
                raise ValueError(f"invalid {name}")
        for name in ("horizon", "year"):
            if (
                not _column(frame, name)
                .astype(object)
                .map(lambda value: isinstance(value, Integral) and not isinstance(value, bool))
                .to_numpy(dtype=bool)
                .all()
            ):
                raise ValueError(f"invalid integer {name}")
        if not _column(frame, "calendar_full").astype(object).map(lambda value: isinstance(value, (bool, np.bool_))).to_numpy(dtype=bool).all():
            raise ValueError("calendar_full must be boolean")
        if not cast(pd.Series, frame.loc[~_column(frame, "calendar_full").to_numpy(dtype=bool), "label"]).isin(["hit", "unknown"]).all():
            raise ValueError("censored labels must be hit or unknown")
        for name in ("code", "event_id"):
            if not _column(frame, name).astype(object).map(lambda value: isinstance(value, str) and bool(value.strip())).to_numpy(dtype=bool).all():
                raise ValueError(f"invalid original string {name}")
        if frame.duplicated(["cohort_id", "split_id", "horizon", "event_id"]).any():
            raise ValueError("duplicate event within cohort/horizon")
        for feature_id, definition in FEATURES.items():
            statuses = _column(frame, f"{feature_id}_status")
            bins = _column(frame, f"{feature_id}_bin")
            known_bins = cast(pd.Series, bins[statuses == "known"])
            unresolved_bins = cast(pd.Series, bins[statuses != "known"])
            if not statuses.isin(list(_STATES)).all() or not known_bins.isin(list(set(definition.bin_ids))).all():
                raise ValueError(f"invalid feature status/bin: {feature_id}")
            if unresolved_bins.notna().any():
                raise ValueError(f"unresolved feature must have null bin: {feature_id}")
        ids: set[str] = set()
        for candidate in candidates:
            if candidate.candidate_id in ids or not candidate.atoms:
                raise ValueError("candidate IDs must be unique and atoms nonempty")
            ids.add(candidate.candidate_id)
            if candidate.candidate_id != candidate_id(candidate.atoms):
                raise ValueError("candidate identity does not match fixed atoms")
            for atom in candidate.atoms:
                atom_definition = FEATURES.get(atom.feature_id)
                if (
                    atom_definition is None
                    or atom_definition.diagnostic_only
                    or atom.family != atom_definition.family
                    or atom.bin_id not in atom_definition.bin_ids
                ):
                    raise ValueError("invalid or diagnostic candidate atom")
        diagnostics = [name for name in _PATH_DIAGNOSTICS if name in frame.columns]
        for name in diagnostics:
            if not _column(frame, name).isin(["triggered", "all_false", "unknown"]).all():
                raise ValueError(f"invalid diagnostic state: {name}")
        for name in ("hit_then_below_anchor", "hit_endpoint_unknown", "hit_then_below_anchor_n", "hit_endpoint_unknown_n"):
            if name in frame and not _column(frame, name).dropna().isin([True, False, 0, 1]).all():
                raise ValueError(f"invalid event indicator: {name}")
        return diagnostics

    def add_observations(self, frame: pd.DataFrame, candidates: Sequence[Candidate] = ()) -> None:
        """Aggregate masks and yearly counts, without retaining individual rows."""
        diagnostics = self._validate(frame, candidates)
        signature = tuple((candidate.candidate_id, candidate.atoms) for candidate in candidates)
        if self._candidate_signature is not None and self._candidate_signature != signature:
            raise ValueError("fixed candidate inventory changed between batches")
        self._candidate_signature = signature
        if frame.empty:
            return
        support = [*sorted({"calendar_full", "label", "year", "code", *_GROUP_COLUMNS}), *diagnostics]
        if "unknown_reason" in frame:
            support.append("unknown_reason")
        for name in ("hit_then_below_anchor", "hit_endpoint_unknown", "hit_then_below_anchor_n", "hit_endpoint_unknown_n"):
            if name in frame:
                support.append(name)
        for feature_id in FEATURES:
            support.extend((f"{feature_id}_bin", f"{feature_id}_status", f"{feature_id}_reason"))
        for group, group_frame in cast(pd.DataFrame, frame[support]).groupby(_GROUP_COLUMNS, sort=True, observed=True):
            cohort, split, horizon = cast(tuple[str, str, int], group)
            arrays = {name: _column(group_frame, name).to_numpy() for name in support if name not in _GROUP_COLUMNS}
            for feature_id in FEATURES:
                name = f"{feature_id}_bin"
                nullable_bins = arrays[name].astype(object, copy=True)
                nullable_bins[pd.isna(nullable_bins)] = None
                arrays[name] = nullable_bins
            all_mask = np.ones(len(group_frame), dtype=bool)

            def record(
                row_kind: str,
                identifier: str | None,
                feature_id: str | None,
                bin_id: str | None,
                mask: np.ndarray,
                *,
                inapplicable: bool = False,
                reasons: np.ndarray | None = None,
            ) -> None:
                metadata = self._metadata(cohort, split, horizon, row_kind, identifier, feature_id, bin_id, inapplicable)
                key = tuple(metadata[name] for name in _IDENTITY_COLUMNS)
                self._record(key, metadata, arrays, mask, diagnostics, inapplicable, reasons)

            record("baseline", None, None, None, all_mask)
            for feature_id, definition in FEATURES.items():
                statuses = arrays[f"{feature_id}_status"]
                bins = arrays[f"{feature_id}_bin"]
                outside = not _applicable(feature_id, cohort)
                for bin_id in sorted(set(definition.bin_ids)):
                    atom = Atom(definition.family, feature_id, bin_id, not definition.diagnostic_only)
                    record("single", candidate_id((atom,)), feature_id, bin_id, (statuses == "known") & (bins == bin_id), inapplicable=outside)
                for status in ("feature_unknown", "not_applicable"):
                    record(
                        "single", f"hhhl-v4-variants.v1:{feature_id}={status}", feature_id, status, statuses == status, reasons=arrays[f"{feature_id}_reason"]
                    )
            for candidate in candidates:
                candidate_mask = all_mask.copy()
                outside = any(not _applicable(atom.feature_id, cohort) for atom in candidate.atoms)
                for atom in candidate.atoms:
                    candidate_mask &= (arrays[f"{atom.feature_id}_status"] == "known") & (arrays[f"{atom.feature_id}_bin"] == atom.bin_id)
                record("candidate", candidate.candidate_id, None, None, candidate_mask, inapplicable=outside)
                for feature_id in ("K", "K2", "K3"):
                    statuses = arrays[f"{feature_id}_status"]
                    bins = arrays[f"{feature_id}_bin"]
                    for bin_id in (*sorted(set(FEATURES[feature_id].bin_ids)), "feature_unknown", "not_applicable"):
                        feature_mask = (statuses == "known") & (bins == bin_id) if bin_id not in {"feature_unknown", "not_applicable"} else statuses == bin_id
                        record("Kdistribution", candidate.candidate_id, feature_id, bin_id, candidate_mask & feature_mask, inapplicable=outside)
        LOGGER.debug("Aggregated %d supplied observations", len(frame))

    def _record(
        self,
        key: tuple[Any, ...],
        metadata: dict[str, Any],
        arrays: dict[str, np.ndarray],
        mask: np.ndarray,
        diagnostics: list[str],
        inapplicable: bool,
        reasons: np.ndarray | None,
    ) -> None:
        full = arrays["calendar_full"].astype(bool)
        labels = arrays["label"]
        for year in np.unique(arrays["year"]):
            year_mask = arrays["year"] == year
            selected = mask & year_mask
            if inapplicable:
                selected = np.zeros(len(mask), dtype=bool)
            complete = selected & full
            censored = selected & ~full
            counts = {
                "calendar_full_n": int(np.count_nonzero(complete)),
                "hit_n": int(np.count_nonzero(complete & (labels == "hit"))),
                "loss_n": int(np.count_nonzero(complete & (labels == "loss"))),
                "flat_win_n": int(np.count_nonzero(complete & (labels == "flat-win"))),
                "unknown_n": int(np.count_nonzero(complete & (labels == "unknown"))),
                "censored_n": int(np.count_nonzero(censored)),
                "censored_hit_n": int(np.count_nonzero(censored & (labels == "hit"))),
                "censored_unknown_n": int(np.count_nonzero(censored & (labels == "unknown"))),
                "not_applicable_n": int(np.count_nonzero(year_mask))
                if inapplicable
                else int(np.count_nonzero(selected))
                if metadata["bin_id"] == "not_applicable"
                else 0,
            }
            for name in ("hit_then_below_anchor", "hit_endpoint_unknown"):
                source = name if name in arrays else f"{name}_n"
                if source in arrays:
                    counts[f"{name}_n"] = int(np.count_nonzero(complete & (labels == "hit") & (arrays[source] == 1)))
            for diagnostic in _PATH_DIAGNOSTICS:
                states = arrays.get(diagnostic)
                for state in ("triggered", "all_false", "unknown"):
                    # An omitted optional diagnostic supplies no path evidence;
                    # its full-window observations remain unknown, never false.
                    counts[f"{diagnostic.removesuffix('_state')}_{state}_n"] = (
                        int(np.count_nonzero(complete & (states == state)))
                        if states is not None
                        else int(np.count_nonzero(complete))
                        if state == "unknown"
                        else 0
                    )
            known_mask = complete & (labels != "unknown")
            codes = np.unique(arrays["code"][known_mask]).tolist()
            self._rates.add(key, metadata, int(year), counts, codes)
            if reasons is not None:
                self._reasons[key][int(year)].update(str(value) for value in reasons[selected] if value is not None and not pd.isna(value))
            if "unknown_reason" in arrays:
                outcome_unknown = selected & (labels == "unknown")
                self._outcome_reasons[key][int(year)].update(
                    str(value) for value in arrays["unknown_reason"][outcome_unknown] if value is not None and not pd.isna(value)
                )

    def finalize(self) -> pd.DataFrame:
        """Return all registered cells and fixed annual/sensitivity slices."""
        rows = self._rates.finalize()
        for row in rows:
            for diagnostic in _PATH_DIAGNOSTICS:
                prefix = diagnostic.removesuffix("_state")
                rates = descriptive_flag_rates(row[f"{prefix}_triggered_n"], row[f"{prefix}_all_false_n"], row[f"{prefix}_unknown_n"])
                row[f"{prefix}_known_n"] = rates["known_n"]
                row[f"{prefix}_all_n"] = rates["all_n"]
                row[f"{prefix}_rate"] = rates["known_rate"]
                row[f"{prefix}_lower"] = rates["lower"]
                row[f"{prefix}_upper"] = rates["upper"]
            if row["not_applicable_reason"] is not None or row["bin_id"] == "not_applicable":
                for name in _RATE_FIELDS:
                    row[name] = None
                for diagnostic in _PATH_DIAGNOSTICS:
                    prefix = diagnostic.removesuffix("_state")
                    for suffix in ("rate", "lower", "upper"):
                        row[f"{prefix}_{suffix}"] = None
            key_values = dict(row, row_kind=row["base_row_kind"])
            key = tuple(key_values[name] for name in _IDENTITY_COLUMNS)
            reasons: Counter[str] = Counter()
            selected_years = (row["year"],) if row["row_kind"] == "year" else tuple(year for year in YEARS if year != row["removed_year"])
            for year in selected_years:
                reasons.update(self._reasons.get(key, {}).get(year, {}))
            row["reason_counts"] = json.dumps(dict(sorted(reasons.items())), ensure_ascii=False, separators=(",", ":"))
            outcome_reasons: Counter[str] = Counter()
            for year in selected_years:
                outcome_reasons.update(self._outcome_reasons.get(key, {}).get(year, {}))
            row["outcome_reason_counts"] = json.dumps(dict(sorted(outcome_reasons.items())), ensure_ascii=False, separators=(",", ":"))
        return pd.DataFrame(rows)
