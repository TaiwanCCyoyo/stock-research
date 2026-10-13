"""Registered Q5/Q6 descriptive cells over caller-supplied event projections."""

from __future__ import annotations

import json
import logging
from array import array
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from itertools import product
from numbers import Integral, Real
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.hhhl_variants_flag_summary import RISE_BINS
from research_core.hhhl_variants_rates import descriptive_flag_rates, trigger_return_summary
from research_core.hhhl_variants_selection import split_for_code
from research_core.pattern_scan_flags_v1 import FLAG_IDS
from research_core.pattern_scan_followup_v1 import FollowupTables

LOGGER = logging.getLogger(__name__)
SPLITS = ("development", "cross-check")
ERAS = ("all", "2010-2012", "2013-2018", "2019-2026")
MARKETS = ("all", "up", "down", "consolidation", "mixed", "unknown")
FLAG_STATES = ("triggered", "all_false", "unknown")
PATHS = ("direct_failure", "rise_then_fall", "sideways", "slow_decline", "unknown")
META = ("group_id", "target_pattern_id", "horizon", "split_id", "era", "mkt")
AUDIT = ("event_n", "known_n", "unknown_label_n", "censored_n", "excluded_n", "known_ineligible_n", "distinct_stock_n")
LABEL_COUNTS = ("hit_n", "loss_n", "flat_win_n", "unknown_n", "hit_rate", "loss_rate", "hit_lower", "hit_upper")
PATH_COLUMNS = META + ("path_category", *AUDIT, "path_n", "max_gain_known_n", "max_gain_unknown_n", "max_gain_q25", "max_gain_median", "max_gain_q75")
FIRST_COLUMNS = META + (
    "flag_id",
    "first_state",
    *AUDIT,
    "first_n",
    "same_day_tie_n",
    "offset_known_n",
    "offset_unknown_n",
    "offset_q25",
    "offset_median",
    "offset_q75",
)
RATE_FIELDS = tuple(
    f"{population}_{name}"
    for population in ("nonhit", "hit_cost")
    for name in ("triggered_n", "all_false_n", "unknown_n", "known_n", "known_rate", "all_n", "lower", "upper")
)
RETURN_FIELDS = ("trigger_return_n", "trigger_return_unknown_n", "trigger_return_p10", "trigger_return_median", "trigger_return_p90")
FLAG_COLUMNS = META + ("flag_id", *AUDIT, *RATE_FIELDS, *RETURN_FIELDS)
LANDMARK_COLUMNS = META + ("flag_id", "landmark", "flag_state", "return_bin", *AUDIT, *LABEL_COUNTS, "unknown_return_n", *RETURN_FIELDS)
TRADEOFF_COLUMNS = META + (
    "flag_id",
    "nonhit_trigger_rate",
    "hit_before_target_cost",
    "nonhit_lower",
    "nonhit_upper",
    "cost_lower",
    "cost_upper",
    "nonhit_population_n",
    "hit_population_n",
)
EXCLUSION_COLUMNS = META + ("source_table", "reason_scope", "reason", "event_n")


@dataclass(frozen=True)
class FollowupSummaryTables:
    path_summary: pd.DataFrame
    first_flag_summary: pd.DataFrame
    flag_summary: pd.DataFrame
    landmark_summary: pd.DataFrame
    tradeoff_points: pd.DataFrame
    exclusions: pd.DataFrame


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    return cast(pd.Series, frame[name])


def _prepare(frame: pd.DataFrame, groups: Mapping[str, str], extra: set[str], keys: list[str]) -> pd.DataFrame:
    required = {
        "group_id",
        "target_pattern_id",
        "security_id",
        "event_id",
        "t0",
        "horizon",
        "mkt",
        "effective_label",
        "event_main_eligible",
        "calendar_full",
        "event_eligibility_excluded",
        *extra,
    }
    if not frame.columns.is_unique or not required.issubset(frame.columns):
        raise ValueError("followup rows require unique canonical population/diagnostic fields")
    if bool(frame.duplicated(keys).any()):
        raise ValueError("duplicate followup observation identity")
    result = frame.copy()
    years: list[int] = []
    splits: list[str] = []
    for supplied in result.to_dict(orient="records"):
        row = cast(dict[str, Any], supplied)
        if row["group_id"] not in groups or row["target_pattern_id"] != groups[row["group_id"]]:
            raise ValueError("unregistered group or inconsistent target pattern")
        if not isinstance(row["security_id"], str) or not row["security_id"].strip() or not isinstance(row["event_id"], str) or not row["event_id"].strip():
            raise ValueError("original security/event identities must be nonblank strings")
        day = date.fromisoformat(row["t0"])
        if day.isoformat() != row["t0"] or not 2010 <= day.year <= 2026:
            raise ValueError("t0 must be a canonical date in the fixed research period")
        if row["mkt"] not in MARKETS[1:] or row["effective_label"] not in {"hit", "loss", "flat-win", "unknown"}:
            raise ValueError("invalid market state or effective outcome")
        if isinstance(row["horizon"], (bool, np.bool_)) or not isinstance(row["horizon"], Integral) or row["horizon"] <= 0:
            raise ValueError("event horizon must be a positive integer")
        for name in ("calendar_full", "event_main_eligible", "event_eligibility_excluded"):
            if not isinstance(row[name], (bool, np.bool_)):
                raise ValueError(f"{name} must be boolean")
        if row["event_main_eligible"] and (not row["calendar_full"] or row["event_eligibility_excluded"] or row["effective_label"] == "unknown"):
            raise ValueError("effective eligibility contradicts its population")
        code = row["security_id"]
        original_code = code[3:] if code.startswith("TW:") else code[2:] if code.startswith("TW") else code
        if not original_code.strip():
            raise ValueError("empty original code after removing the TW identity prefix")
        years.append(day.year)
        splits.append(split_for_code(original_code))
    result["_year"], result["_split"] = years, splits
    return result


def _facet(frame: pd.DataFrame, group: str, horizon: int, split: str, era: str, market: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    mask = _column(frame, "group_id").eq(group) & _column(frame, "horizon").eq(horizon) & _column(frame, "_split").eq(split)
    if era != "all":
        lower, upper = map(int, era.split("-"))
        mask &= _column(frame, "_year").between(lower, upper)
    if market != "all":
        mask &= _column(frame, "mkt").eq(market)
    return cast(pd.DataFrame, frame.loc[mask])


def _eligible(rows: pd.DataFrame) -> pd.Series:
    return _column(rows, "event_main_eligible").astype(bool) & _column(rows, "calendar_full").astype(bool)


def _audit(rows: pd.DataFrame) -> dict[str, int]:
    if rows.empty:
        return dict.fromkeys(AUDIT, 0)
    eligible = _eligible(rows)
    unknown = _column(rows, "effective_label").eq("unknown")
    full = _column(rows, "calendar_full").astype(bool)
    excluded = _column(rows, "event_eligibility_excluded").astype(bool)
    return {
        "event_n": len(rows),
        "known_n": int(eligible.sum()),
        "unknown_label_n": int(unknown.sum()),
        "censored_n": int((~full).sum()),
        "excluded_n": int(excluded.sum()),
        "known_ineligible_n": int((full & ~unknown & ~excluded & ~eligible).sum()),
        "distinct_stock_n": int(_column(rows.loc[eligible], "security_id").nunique()),
    }


def _quantiles(values: pd.Series, prefix: str) -> dict[str, int | float | None]:
    numeric = cast(pd.Series, pd.to_numeric(values, errors="coerce")).to_numpy(dtype=float, na_value=np.nan)
    known = numeric[np.isfinite(numeric)]
    return {
        f"{prefix}_known_n": len(known),
        f"{prefix}_unknown_n": len(values) - len(known),
        **{
            f"{prefix}_{name}": float(np.quantile(known, probability)) if len(known) else None
            for name, probability in (("q25", 0.25), ("median", 0.5), ("q75", 0.75))
        },
    }


def _flag_rates(rows: pd.DataFrame, label: str) -> dict[str, int | float | None]:
    mask = _eligible(rows)
    labels = _column(rows, "effective_label")
    mask &= labels.eq("hit") if label == "hit" else labels.isin(("loss", "flat-win"))
    states = _column(rows.loc[mask], "flag_state")
    return descriptive_flag_rates(*(int(states.eq(state).sum()) for state in FLAG_STATES))


def _label_counts(rows: pd.DataFrame) -> dict[str, int | float | None]:
    if rows.empty:
        return {"hit_n": 0, "loss_n": 0, "flat_win_n": 0, "unknown_n": 0, "hit_rate": None, "loss_rate": None, "hit_lower": None, "hit_upper": None}
    eligible = _eligible(rows)
    labels = _column(rows, "effective_label")
    known = int(eligible.sum())
    unknown = int((_column(rows, "calendar_full").astype(bool) & ~_column(rows, "event_eligibility_excluded").astype(bool) & labels.eq("unknown")).sum())
    hit, loss, flat = (int((eligible & labels.eq(label)).sum()) for label in ("hit", "loss", "flat-win"))
    potential = known + unknown
    return {
        "hit_n": hit,
        "loss_n": loss,
        "flat_win_n": flat,
        "unknown_n": unknown,
        "hit_rate": hit / known if known else None,
        "loss_rate": loss / known if known else None,
        "hit_lower": hit / potential if potential else None,
        "hit_upper": (hit + unknown) / potential if potential else None,
    }


def _validated_tables(
    paths: pd.DataFrame,
    first_flags: pd.DataFrame,
    flags: pd.DataFrame,
    landmarks: pd.DataFrame,
    groups: Mapping[str, str],
    hs: Sequence[int],
    ls: Sequence[int],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    identity = ["group_id", "event_id", "horizon"]
    prepared_paths = _prepare(paths, groups, {"path_category", "max_return"}, identity)
    prepared_first = _prepare(first_flags, groups, {"first_flag_state", "first_flag_flag_id", "first_flag_offset", "first_flag_all_flag_ids_json"}, identity)
    prepared_flags = _prepare(flags, groups, {"flag_id", "flag_state", "trigger_return"}, [*identity, "flag_id"])
    prepared_landmarks = _prepare(
        landmarks,
        groups,
        {"flag_id", "landmark", "flag_state", "rise_bin", "riskset_id", "riskset_eligible", "trigger_return"},
        [*identity, "flag_id", "landmark"],
    )
    population_fields = [
        *identity,
        "target_pattern_id",
        "security_id",
        "t0",
        "mkt",
        "effective_label",
        "event_main_eligible",
        "calendar_full",
        "event_eligibility_excluded",
    ]
    populations = pd.concat(
        [table.loc[:, population_fields] for table in (prepared_paths, prepared_first, prepared_flags, prepared_landmarks)], ignore_index=True
    )
    if bool(populations.drop_duplicates().duplicated(identity).any()):
        raise ValueError("the same event projection cannot change population between diagnostics")
    for table in (prepared_paths, prepared_first, prepared_flags, prepared_landmarks):
        if not bool(_column(table, "horizon").isin(hs).all()):
            raise ValueError("unregistered observation horizon")
    for table in (prepared_flags, prepared_landmarks):
        if not bool(_column(table, "flag_id").isin(FLAG_IDS).all()) or not bool(_column(table, "flag_state").isin(FLAG_STATES).all()):
            raise ValueError("invalid flag identity or first-decision state")
    if not bool(_column(prepared_paths, "path_category").isin(PATHS).all()) or not bool(_column(prepared_first, "first_flag_state").isin(FLAG_STATES).all()):
        raise ValueError("invalid path or first-flag state")
    if not bool(_column(prepared_landmarks, "riskset_id").eq("new_no_hit_valid_prefix").all()):
        raise ValueError("landmarks require the NEW fixed-endpoint riskset")
    for value in _column(prepared_landmarks, "riskset_eligible"):
        if not isinstance(value, (bool, np.bool_)):
            raise ValueError("riskset eligibility must be boolean")
    if not bool(_column(prepared_landmarks, "landmark").isin(ls).all()):
        raise ValueError("unregistered landmark position")
    if bool((_column(prepared_landmarks, "landmark") >= _column(prepared_landmarks, "horizon")).any()):
        raise ValueError("landmarks must precede the fixed horizon")
    rises = _column(prepared_landmarks, "rise_bin")
    if not bool((rises.isna() | rises.isin(RISE_BINS)).all()):
        raise ValueError("landmark return bins must use the public fixed boundaries")
    return prepared_paths, prepared_first, prepared_flags, prepared_landmarks


def summarize_followup(
    paths: pd.DataFrame,
    first_flags: pd.DataFrame,
    flags: pd.DataFrame,
    landmarks: pd.DataFrame,
    *,
    groups: Mapping[str, str],
    horizons: Sequence[int] = (126, 252),
    landmarks_at: Sequence[int] = (5, 10, 20, 40),
) -> FollowupSummaryTables:
    """Register 48 facets per group/horizon, including every empty cell.

    Only development/cross-check splits are registered for the mission's Q5/Q6
    bound. Full rates use each effective main population and before-hit flag
    history; raw flags never requalify an event. Landmarks require the NEW
    valid-prefix riskset and use its existing return bin, including exact legacy
    boundaries. Unknown return counts remain visible in pooled rows. First-flag
    ties are diagnostics, not additive mutually exclusive event populations.
    """
    if any(not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip() for key, value in groups.items()):
        raise ValueError("registered group/pattern identities must be nonblank strings")
    hs, ls = tuple(horizons), tuple(landmarks_at)
    if (
        any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value <= 0 for value in (*hs, *ls))
        or len(set(hs)) != len(hs)
        or len(set(ls)) != len(ls)
    ):
        raise ValueError("registered horizons/landmarks require unique positive integers")
    prepared_paths, prepared_first, prepared_flags, prepared_landmarks = _validated_tables(paths, first_flags, flags, landmarks, groups, hs, ls)
    identity = ["group_id", "event_id", "horizon"]
    p_rows: list[dict[str, Any]] = []
    first_rows: list[dict[str, Any]] = []
    flag_rows: list[dict[str, Any]] = []
    landmark_rows: list[dict[str, Any]] = []
    tradeoffs: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for group, horizon, split, era, market in product(sorted(groups), hs, SPLITS, ERAS, MARKETS):
        meta = dict(zip(META, (group, groups[group], horizon, split, era, market), strict=True))
        pp, ff, full, lm = (_facet(table, group, horizon, split, era, market) for table in (prepared_paths, prepared_first, prepared_flags, prepared_landmarks))
        eligible_paths = cast(pd.DataFrame, pp.loc[_eligible(pp)])
        for category in PATHS:
            selected = cast(pd.DataFrame, eligible_paths.loc[_column(eligible_paths, "path_category").eq(category)])
            p_rows.append({**meta, "path_category": category, **_audit(pp), "path_n": len(selected), **_quantiles(_column(selected, "max_return"), "max_gain")})
        for flag, state in product((*FLAG_IDS, "none", "unknown"), FLAG_STATES):
            state_rows = cast(pd.DataFrame, ff.loc[_column(ff, "first_flag_state").eq(state)])
            identities = _column(state_rows, "first_flag_flag_id").fillna("none" if state == "all_false" else "unknown")
            chosen = cast(pd.DataFrame, state_rows.loc[identities.eq(flag) & _eligible(state_rows)])
            ties = _column(state_rows.loc[_eligible(state_rows)], "first_flag_all_flag_ids_json").map(lambda value: flag in json.loads(value))
            first_rows.append({
                **meta,
                "flag_id": flag,
                "first_state": state,
                **_audit(state_rows),
                "first_n": len(chosen),
                "same_day_tie_n": int(ties.sum()),
                **_quantiles(_column(chosen, "first_flag_offset"), "offset"),
            })
        for flag in FLAG_IDS:
            rows = cast(pd.DataFrame, full.loc[_column(full, "flag_id").eq(flag)])
            nonhit, cost = _flag_rates(rows, "nonhit"), _flag_rates(rows, "hit")
            returns = _column(rows.loc[_eligible(rows) & _column(rows, "flag_state").eq("triggered")], "trigger_return")
            flag_rows.append({
                **meta,
                "flag_id": flag,
                **_audit(rows),
                **{f"nonhit_{key}": value for key, value in nonhit.items()},
                **{f"hit_cost_{key}": value for key, value in cost.items()},
                **trigger_return_summary(returns.tolist()),
            })
            tradeoffs.append({
                **meta,
                "flag_id": flag,
                "nonhit_trigger_rate": nonhit["known_rate"],
                "hit_before_target_cost": cost["known_rate"],
                "nonhit_lower": nonhit["lower"],
                "nonhit_upper": nonhit["upper"],
                "cost_lower": cost["lower"],
                "cost_upper": cost["upper"],
                "nonhit_population_n": nonhit["all_n"],
                "hit_population_n": cost["all_n"],
            })
            for landmark, state, rise in product((value for value in ls if value < horizon), FLAG_STATES, ("pooled", *RISE_BINS)):
                all_landmark = cast(pd.DataFrame, lm.loc[_column(lm, "flag_id").eq(flag) & _column(lm, "landmark").eq(landmark)])
                active = cast(
                    pd.DataFrame, all_landmark.loc[_column(all_landmark, "riskset_eligible").astype(bool) & _column(all_landmark, "flag_state").eq(state)]
                )
                if rise != "pooled":
                    active = cast(pd.DataFrame, active.loc[_column(active, "rise_bin").eq(rise)])
                return_values = _column(active.loc[_eligible(active) & _column(active, "flag_state").eq("triggered")], "trigger_return")
                landmark_rows.append({
                    **meta,
                    "flag_id": flag,
                    "landmark": landmark,
                    "flag_state": state,
                    "return_bin": rise,
                    **_audit(active),
                    **_label_counts(active),
                    "unknown_return_n": int(_column(active, "rise_bin").isna().sum()),
                    **trigger_return_summary(return_values.tolist()),
                })
        for source, table in (("paths", pp), ("first_flags", ff), ("flags", full), ("landmarks", lm)):
            unique = table.drop_duplicates(identity)
            audit = _audit(unique)
            for reason, count_name in (
                ("effective_label_unknown", "unknown_label_n"),
                ("censored", "censored_n"),
                ("event_eligibility_excluded", "excluded_n"),
                ("known_ineligible", "known_ineligible_n"),
            ):
                exclusions.append({**meta, "source_table": source, "reason_scope": "population", "reason": reason, "event_n": audit[count_name]})
            for scope in ("detection_quality", "result_quality", "event_eligibility", "effective_unknown"):
                column = f"{scope}_reasons_json"
                if column not in unique.columns:
                    continue
                counts: dict[str, int] = {}
                for value in _column(unique, column):
                    tokens = json.loads(value) if isinstance(value, str) else []
                    if not isinstance(tokens, list) or any(not isinstance(token, str) or not token.strip() for token in tokens):
                        raise ValueError("exclusion reason JSON must contain nonblank strings")
                    for reason in set(tokens):
                        counts[reason] = counts.get(reason, 0) + 1
                exclusions.extend(
                    {**meta, "source_table": source, "reason_scope": scope, "reason": reason, "event_n": count} for reason, count in sorted(counts.items())
                )
    LOGGER.debug("Followup summaries groups=%d paths=%d flags=%d landmarks=%d", len(groups), len(p_rows), len(flag_rows), len(landmark_rows))
    return FollowupSummaryTables(
        *(
            pd.DataFrame(rows, columns=pd.Index(columns))
            for rows, columns in (
                (p_rows, PATH_COLUMNS),
                (first_rows, FIRST_COLUMNS),
                (flag_rows, FLAG_COLUMNS),
                (landmark_rows, LANDMARK_COLUMNS),
                (tradeoffs, TRADEOFF_COLUMNS),
                (exclusions, EXCLUSION_COLUMNS),
            )
        )
    )


@dataclass
class _Cell:
    counts: dict[str, int] = field(default_factory=dict)
    samples: dict[str, array] = field(default_factory=dict)
    stock_events: dict[str, int] = field(default_factory=dict)

    def add(self, name: str, value: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + value

    def audit(self, row: dict[str, Any]) -> None:
        eligible = bool(row["calendar_full"] and row["event_main_eligible"])
        unknown = row["effective_label"] == "unknown"
        self.add("event_n")
        self.add("known_n", int(eligible))
        self.add("unknown_label_n", int(unknown))
        self.add("censored_n", int(not row["calendar_full"]))
        self.add("excluded_n", int(row["event_eligibility_excluded"]))
        self.add("known_ineligible_n", int(row["calendar_full"] and not unknown and not row["event_eligibility_excluded"] and not eligible))
        if eligible:
            stock = row["security_id"]
            self.stock_events[stock] = self.stock_events.get(stock, 0) + 1

    def sample(self, name: str, value: Any) -> None:
        if isinstance(value, Real) and not isinstance(value, (bool, np.bool_)) and np.isfinite(float(value)):
            self.samples.setdefault(name, array("d")).append(float(value))
        else:
            self.add(f"{name}_unknown_n")

    def merged(self, other: _Cell) -> None:
        for name, value in other.counts.items():
            self.add(name, value)
        for name, values in other.samples.items():
            self.samples.setdefault(name, array("d")).extend(values)
        for stock, count in other.stock_events.items():
            self.stock_events[stock] = self.stock_events.get(stock, 0) + count

    def audit_values(self) -> dict[str, int]:
        return {name: len(self.stock_events) if name == "distinct_stock_n" else self.counts.get(name, 0) for name in AUDIT}

    def quantiles(self, name: str) -> dict[str, int | float | None]:
        values = np.asarray(self.samples.get(name, array("d")), dtype=float)
        return {
            f"{name}_known_n": len(values),
            f"{name}_unknown_n": self.counts.get(f"{name}_unknown_n", 0),
            **{
                f"{name}_{key}": float(np.quantile(values, probability)) if len(values) else None
                for key, probability in (("q25", 0.25), ("median", 0.5), ("q75", 0.75))
            },
        }

    def trigger_returns(self) -> dict[str, int | float | None]:
        result = trigger_return_summary(self.samples.get("trigger_return", array("d")))
        result["trigger_return_unknown_n"] = self.counts.get("trigger_return_unknown_n", 0)
        return result

    def rates(self, population: str) -> dict[str, int | float | None]:
        return descriptive_flag_rates(*(self.counts.get(f"{population}_{state}", 0) for state in FLAG_STATES))

    def labels(self) -> dict[str, int | float | None]:
        hit, loss, flat, unknown = (self.counts.get(name, 0) for name in ("hit_n", "loss_n", "flat_win_n", "unknown_n"))
        known, potential = hit + loss + flat, hit + loss + flat + unknown
        return {
            "hit_n": hit,
            "loss_n": loss,
            "flat_win_n": flat,
            "unknown_n": unknown,
            "hit_rate": hit / known if known else None,
            "loss_rate": loss / known if known else None,
            "hit_lower": hit / potential if potential else None,
            "hit_upper": (hit + unknown) / potential if potential else None,
        }


class FollowupAccumulator:
    """One complete feed per stock/group, retaining counts and exact samples.

    Only observed facet/cell keys are accumulated; finalize registers zero
    cells once. Feed validation and local reduction finish before state changes.
    Numeric sample bytes are reported separately from Python bookkeeping/RSS.
    """

    def __init__(self, groups: Mapping[str, str], horizons: Sequence[int] = (126, 252), landmarks_at: Sequence[int] = (5, 10, 20, 40)) -> None:
        self.groups = dict(groups)
        self.horizons = tuple(horizons)
        self.landmarks_at = tuple(landmarks_at)
        if any(not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip() for key, value in self.groups.items()):
            raise ValueError("registered group/pattern identities must be nonblank strings")
        values = (*self.horizons, *self.landmarks_at)
        if (
            any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value <= 0 for value in values)
            or not self.horizons
            or len(set(self.horizons)) != len(self.horizons)
            or len(set(self.landmarks_at)) != len(self.landmarks_at)
        ):
            raise ValueError("registered horizons/landmarks require unique positive integers")
        self._cells: dict[tuple[Any, ...], _Cell] = {}
        self._feeds: set[tuple[str, str]] = set()

    @property
    def memory_nbytes(self) -> int:
        """Read-only exact numeric sample buffer bytes; excludes bookkeeping."""
        return sum(len(values) * values.itemsize for cell in self._cells.values() for values in cell.samples.values())

    @staticmethod
    def _metas(row: dict[str, Any]) -> tuple[tuple[Any, ...], ...]:
        year = row["_year"]
        era = "2010-2012" if year <= 2012 else "2013-2018" if year <= 2018 else "2019-2026"
        return tuple((row["group_id"], row["target_pattern_id"], row["horizon"], row["_split"], e, m) for e, m in product(("all", era), ("all", row["mkt"])))

    def add_stock(self, tables: FollowupTables) -> None:
        pp, ff, full, lm = _validated_tables(tables.paths, tables.first_flags, tables.flags, tables.landmarks, self.groups, self.horizons, self.landmarks_at)
        frames = (pp, ff, full, lm)
        identity_fields = ["group_id", "event_id", "horizon"]
        path_keys = set(pp.loc[:, identity_fields].itertuples(index=False, name=None))
        first_keys = set(ff.loc[:, identity_fields].itertuples(index=False, name=None))
        flag_keys = set(full.loc[:, identity_fields].itertuples(index=False, name=None))
        if first_keys != path_keys or flag_keys != path_keys:
            raise ValueError("stock feeds require complete matching path/first/full-flag identities")
        observed_horizons: dict[tuple[str, str], set[int]] = {}
        for group, event, horizon in path_keys:
            observed_horizons.setdefault((group, event), set()).add(horizon)
        if any(values != set(self.horizons) for values in observed_horizons.values()):
            raise ValueError("stock feeds require all registered horizons for each event")
        actual_flags = set(full.loc[:, [*identity_fields, "flag_id"]].itertuples(index=False, name=None))
        expected_flags = {(*identity, flag) for identity in path_keys for flag in FLAG_IDS}
        actual_landmarks = set(lm.loc[:, [*identity_fields, "landmark", "flag_id"]].itertuples(index=False, name=None))
        expected_landmarks = {
            (*identity, landmark, flag) for identity in path_keys for landmark in self.landmarks_at if landmark < identity[2] for flag in FLAG_IDS
        }
        if actual_flags != expected_flags or actual_landmarks != expected_landmarks:
            raise ValueError("stock feeds require complete registered flag/landmark observations")
        stocks = {stock for frame in frames for stock in _column(frame, "security_id")}
        if len(stocks) > 1:
            raise ValueError("add_stock requires one original security identity")
        feeds = {(group, stock) for frame in frames for group, stock in frame.loc[:, ["group_id", "security_id"]].itertuples(index=False, name=None)}
        if feeds & self._feeds:
            raise ValueError("duplicate stock/group feed")
        local: dict[tuple[Any, ...], _Cell] = {}

        def cell(family: str, meta: tuple[Any, ...], *tail: Any) -> _Cell:
            return local.setdefault((family, *meta, *tail), _Cell())

        for supplied in pp.to_dict(orient="records"):
            row = cast(dict[str, Any], supplied)
            for meta in self._metas(row):
                cell("paths_audit", meta).audit(row)
                if row["event_main_eligible"]:
                    selected = cell("path", meta, row["path_category"])
                    selected.add("path_n")
                    selected.sample("max_gain", row["max_return"])
        for supplied in ff.to_dict(orient="records"):
            row = cast(dict[str, Any], supplied)
            state = row["first_flag_state"]
            raw_flag = row["first_flag_flag_id"]
            flag = "none" if state == "all_false" and pd.isna(raw_flag) else "unknown" if pd.isna(raw_flag) else raw_flag
            ties = json.loads(row["first_flag_all_flag_ids_json"])
            if not isinstance(ties, list) or any(value not in FLAG_IDS for value in ties):
                raise ValueError("first flag ties must contain registered flag identities")
            if flag not in (*FLAG_IDS, "none", "unknown"):
                raise ValueError("invalid first flag identity")
            for meta in self._metas(row):
                cell("first_audit", meta, state).audit(row)
                if row["event_main_eligible"]:
                    selected = cell("first", meta, flag, state)
                    selected.add("first_n")
                    selected.sample("offset", row["first_flag_offset"])
                    for tied in set(ties):
                        cell("first", meta, tied, state).add("same_day_tie_n")
        for supplied in full.to_dict(orient="records"):
            row = cast(dict[str, Any], supplied)
            for meta in self._metas(row):
                selected = cell("flag", meta, row["flag_id"])
                selected.audit(row)
                if row["event_main_eligible"]:
                    population = "hit_cost" if row["effective_label"] == "hit" else "nonhit"
                    selected.add(f"{population}_{row['flag_state']}")
                    if row["flag_state"] == "triggered":
                        selected.sample("trigger_return", row["trigger_return"])
        for supplied in lm.to_dict(orient="records"):
            row = cast(dict[str, Any], supplied)
            if not row["riskset_eligible"]:
                continue
            rises = ("pooled", row["rise_bin"]) if not pd.isna(row["rise_bin"]) else ("pooled",)
            for meta in self._metas(row):
                for rise in rises:
                    selected = cell("landmark", meta, row["flag_id"], row["landmark"], row["flag_state"], rise)
                    selected.audit(row)
                    if pd.isna(row["rise_bin"]):
                        selected.add("unknown_return_n")
                    if row["event_main_eligible"]:
                        selected.add({"hit": "hit_n", "loss": "loss_n", "flat-win": "flat_win_n"}[row["effective_label"]])
                        if row["flag_state"] == "triggered":
                            selected.sample("trigger_return", row["trigger_return"])
                    elif row["calendar_full"] and not row["event_eligibility_excluded"] and row["effective_label"] == "unknown":
                        selected.add("unknown_n")
        identity = ["group_id", "event_id", "horizon"]
        for source, frame in zip(("paths", "first_flags", "flags", "landmarks"), frames, strict=True):
            for supplied in frame.drop_duplicates(identity).to_dict(orient="records"):
                row = cast(dict[str, Any], supplied)
                reasons = [
                    ("population", "effective_label_unknown", row["effective_label"] == "unknown"),
                    ("population", "censored", not row["calendar_full"]),
                    ("population", "event_eligibility_excluded", row["event_eligibility_excluded"]),
                    (
                        "population",
                        "known_ineligible",
                        row["calendar_full"]
                        and row["effective_label"] != "unknown"
                        and not row["event_eligibility_excluded"]
                        and not row["event_main_eligible"],
                    ),
                ]
                for scope in ("detection_quality", "result_quality", "event_eligibility", "effective_unknown"):
                    value = row.get(f"{scope}_reasons_json")
                    tokens = json.loads(value) if isinstance(value, str) else []
                    if not isinstance(tokens, list) or any(not isinstance(token, str) or not token.strip() for token in tokens):
                        raise ValueError("exclusion reason JSON must contain nonblank strings")
                    reasons.extend((scope, reason, True) for reason in set(tokens))
                for meta in self._metas(row):
                    for scope, reason, active in reasons:
                        if active:
                            cell("exclusion", meta, source, scope, reason).add("event_n")
        for key, addition in local.items():
            self._cells.setdefault(key, _Cell()).merged(addition)
        self._feeds.update(feeds)
        LOGGER.debug("Followup streaming feeds=%d cells=%d numeric_bytes=%d", len(self._feeds), len(self._cells), self.memory_nbytes)

    def finalize(self) -> FollowupSummaryTables:
        columns = {
            "group_id",
            "target_pattern_id",
            "security_id",
            "event_id",
            "t0",
            "horizon",
            "mkt",
            "effective_label",
            "event_main_eligible",
            "calendar_full",
            "event_eligibility_excluded",
            "path_category",
            "max_return",
            "first_flag_state",
            "first_flag_flag_id",
            "first_flag_offset",
            "first_flag_all_flag_ids_json",
            "flag_id",
            "flag_state",
            "trigger_return",
            "landmark",
            "rise_bin",
            "riskset_id",
            "riskset_eligible",
        }
        empty = pd.DataFrame(columns=pd.Index(sorted(columns)))
        template = summarize_followup(empty, empty, empty, empty, groups=self.groups, horizons=self.horizons, landmarks_at=self.landmarks_at)
        blank = _Cell()

        def get(family: str, meta: tuple[Any, ...], *tail: Any) -> _Cell:
            return self._cells.get((family, *meta, *tail), blank)

        output: list[pd.DataFrame] = []
        for family, table in zip(
            ("path", "first", "flag", "landmark", "tradeoff", "exclusion"),
            (
                template.path_summary,
                template.first_flag_summary,
                template.flag_summary,
                template.landmark_summary,
                template.tradeoff_points,
                template.exclusions,
            ),
            strict=True,
        ):
            rows: list[dict[str, Any]] = []
            for supplied in table.to_dict(orient="records"):
                row = cast(dict[str, Any], supplied)
                meta = tuple(row[name] for name in META)
                if family == "path":
                    selected = get("path", meta, row["path_category"])
                    row.update(get("paths_audit", meta).audit_values())
                    row.update(path_n=selected.counts.get("path_n", 0))
                    row.update(selected.quantiles("max_gain"))
                elif family == "first":
                    selected = get("first", meta, row["flag_id"], row["first_state"])
                    row.update(get("first_audit", meta, row["first_state"]).audit_values())
                    row.update(first_n=selected.counts.get("first_n", 0), same_day_tie_n=selected.counts.get("same_day_tie_n", 0))
                    row.update(selected.quantiles("offset"))
                elif family in {"flag", "tradeoff"}:
                    selected = get("flag", meta, row["flag_id"])
                    nonhit, cost = selected.rates("nonhit"), selected.rates("hit_cost")
                    if family == "flag":
                        row.update(selected.audit_values())
                        row.update({f"nonhit_{key}": value for key, value in nonhit.items()})
                        row.update({f"hit_cost_{key}": value for key, value in cost.items()})
                        row.update(selected.trigger_returns())
                    else:
                        row.update(
                            nonhit_trigger_rate=nonhit["known_rate"],
                            hit_before_target_cost=cost["known_rate"],
                            nonhit_lower=nonhit["lower"],
                            nonhit_upper=nonhit["upper"],
                            cost_lower=cost["lower"],
                            cost_upper=cost["upper"],
                            nonhit_population_n=nonhit["all_n"],
                            hit_population_n=cost["all_n"],
                        )
                elif family == "landmark":
                    selected = get("landmark", meta, row["flag_id"], row["landmark"], row["flag_state"], row["return_bin"])
                    row.update(selected.audit_values())
                    row.update(selected.labels())
                    row.update(unknown_return_n=selected.counts.get("unknown_return_n", 0))
                    row.update(selected.trigger_returns())
                else:
                    row["event_n"] = get("exclusion", meta, row["source_table"], row["reason_scope"], row["reason"]).counts.get("event_n", 0)
                rows.append(row)
            if family == "exclusion":
                for key, selected in sorted(self._cells.items()):
                    if key[0] == "exclusion" and key[-2] != "population":
                        rows.append({
                            **dict(zip(META, key[1:7], strict=True)),
                            "source_table": key[-3],
                            "reason_scope": key[-2],
                            "reason": key[-1],
                            "event_n": selected.counts["event_n"],
                        })
                order = ["group_id", "horizon", "split_id", "era", "mkt", "source_table", "reason_scope", "reason"]
                output.append(pd.DataFrame(rows, columns=table.columns).sort_values(order, kind="stable").reset_index(drop=True))
            else:
                output.append(pd.DataFrame(rows, columns=table.columns))
        return FollowupSummaryTables(*output)
