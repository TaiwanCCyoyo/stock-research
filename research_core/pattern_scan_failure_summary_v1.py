"""Outcome-separated Q5 diagnostics with sparse exact streaming samples."""

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

from research_core.hhhl_variants_selection import split_for_code
from research_core.pattern_scan_flags_v1 import FLAG_IDS
from research_core.pattern_scan_followup_summary_v1 import ERAS, FLAG_STATES, MARKETS, PATHS, SPLITS
from research_core.pattern_scan_followup_v1 import FollowupTables
from research_core.pattern_scan_holding_v1 import STATES

LOGGER = logging.getLogger(__name__)
POPULATIONS = ("hit", "nonhit", "unknown")
META = ("group_id", "target_pattern_id", "horizon", "split_id", "era", "mkt", "population")
AUDIT = ("event_n", "main_eligible_n", "unknown_label_n", "excluded_n", "censored_n", "distinct_stock_n", "sample_n", "sample_distinct_stock_n")
METRICS = ("own_return", "benchmark_return", "peer_return", *(f"holding_{state}_fraction" for state in STATES))
QUANTILES = ("known_n", "unknown_n", "q25", "median", "q75")
SCOPE = "full-calendar non-excluded metric-known diagnostics; unknown outcome remains unknown"
PATH_COLUMNS = (
    META
    + ("path_category", *AUDIT, "path_n", "numeric_sample_scope")
    + tuple(f"{metric}_{field}" for metric in ("max_return", "peak_offset") for field in QUANTILES)
)
FIRST_COLUMNS = (
    META + ("flag_id", "first_state", *AUDIT, "first_n", "same_day_tie_n", "numeric_sample_scope") + tuple(f"first_day_{field}" for field in QUANTILES)
)
HOLDING_COLUMNS = META + (*AUDIT, "numeric_sample_scope") + tuple(f"{metric}_{field}" for metric in METRICS for field in QUANTILES)


@dataclass(frozen=True)
class FailureSummaryTables:
    path_by_outcome: pd.DataFrame
    first_flag_by_outcome: pd.DataFrame
    holding_by_outcome: pd.DataFrame


@dataclass
class _Cell:
    counts: dict[str, int] = field(default_factory=dict)
    samples: dict[str, array] = field(default_factory=dict)
    stocks: set[str] = field(default_factory=set)
    sample_stocks: set[str] = field(default_factory=set)

    def count(self, name: str, amount: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + amount

    def audit(self, row: dict[str, Any], included: bool) -> None:
        self.count("event_n")
        self.count("main_eligible_n", int(row["event_main_eligible"]))
        self.count("unknown_label_n", int(row["effective_label"] == "unknown"))
        self.count("excluded_n", int(row["event_eligibility_excluded"]))
        self.count("censored_n", int(not row["calendar_full"]))
        self.stocks.add(row["security_id"])
        if included:
            self.count("sample_n")
            self.sample_stocks.add(row["security_id"])

    def sample(self, metric: str, value: Any) -> None:
        if isinstance(value, Real) and not isinstance(value, (bool, np.bool_)) and np.isfinite(float(value)):
            self.samples.setdefault(metric, array("d")).append(float(value))
        else:
            self.count(f"{metric}_unknown_n")

    def merge(self, other: _Cell) -> None:
        for name, value in other.counts.items():
            self.count(name, value)
        for metric, values in other.samples.items():
            self.samples.setdefault(metric, array("d")).extend(values)
        self.stocks.update(other.stocks)
        self.sample_stocks.update(other.sample_stocks)

    def values(self) -> dict[str, int]:
        return {
            name: len(self.stocks) if name == "distinct_stock_n" else len(self.sample_stocks) if name == "sample_distinct_stock_n" else self.counts.get(name, 0)
            for name in AUDIT
        }

    def quantiles(self, metric: str) -> dict[str, int | float | None]:
        values = np.asarray(self.samples.get(metric, array("d")), dtype=float)
        return {
            f"{metric}_known_n": len(values),
            f"{metric}_unknown_n": self.counts.get(f"{metric}_unknown_n", 0),
            **{
                f"{metric}_{name}": float(np.quantile(values, probability)) if len(values) else None
                for name, probability in (("q25", 0.25), ("median", 0.5), ("q75", 0.75))
            },
        }


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _observed_offset(value: Any, name: str) -> int:
    # Nullable offsets emitted by a pandas table may be integer-valued floats.
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)) or not np.isfinite(float(value)) or float(value) != int(float(value)):
        raise ValueError(f"{name} must be a positive integer-valued observed offset")
    return _integer(int(float(value)), name, minimum=1)


def _population(label: str) -> str:
    return "hit" if label == "hit" else "unknown" if label == "unknown" else "nonhit"


def _included(row: dict[str, Any]) -> bool:
    return bool(row["calendar_full"] and not row["event_eligibility_excluded"]) if row["effective_label"] == "unknown" else bool(row["event_main_eligible"])


def _scope(population: str) -> str:
    return SCOPE if population == "unknown" else "effective main-eligible population; numeric diagnostics do not relabel outcomes"


class FailureAccumulator:
    """Reduce one complete stock/group feed without retaining event frames.

    Known hit/nonhit distributions require effective main eligibility. Unknown
    outcomes retain independent full-calendar non-excluded numeric diagnostics;
    they never become qualified hit/nonhit events. All inputs remain unchanged.
    """

    def __init__(self, groups: Mapping[str, str], horizons: Sequence[int] = (126, 252)) -> None:
        self.groups = dict(groups)
        self.horizons = tuple(_integer(value, "horizon", minimum=1) for value in horizons)
        if not self.horizons or len(set(self.horizons)) != len(self.horizons):
            raise ValueError("horizons must be nonempty unique")
        if any(not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip() for key, value in self.groups.items()):
            raise ValueError("registered group/pattern identities must be nonblank strings")
        self._cells: dict[tuple[Any, ...], _Cell] = {}
        self._feeds: set[tuple[str, str]] = set()

    @property
    def memory_nbytes(self) -> int:
        """Read-only live numeric payload bytes, excluding Python bookkeeping."""
        return sum(len(values) * values.itemsize for cell in self._cells.values() for values in cell.samples.values())

    def _validated(self, tables: FollowupTables) -> tuple[list[dict[str, Any]], dict[tuple[str, str, int], dict[str, Any]]]:
        identity = ("group_id", "event_id", "horizon")
        fields = (
            *identity,
            "target_pattern_id",
            "security_id",
            "t0",
            "calendar_index",
            "base_label",
            "effective_label",
            "calendar_full",
            "event_main_eligible",
            "event_eligibility_excluded",
            "mkt",
        )
        reference: dict[tuple[str, str, int], dict[str, Any]] = {}
        dates: dict[tuple[str, int], str] = {}
        stocks: set[str] = set()
        for name, frame in (("paths", tables.paths), ("first_flags", tables.first_flags), ("flags", tables.flags), ("landmarks", tables.landmarks)):
            if not frame.columns.is_unique or not set(fields).issubset(frame.columns):
                raise ValueError("followup tables require canonical event projection metadata")
            if name in {"paths", "first_flags"} and bool(frame.duplicated(list(identity)).any()):
                raise ValueError("duplicate path or first-flag identity")
            for supplied in frame.to_dict(orient="records"):
                row = cast(dict[str, Any], supplied)
                if row["group_id"] not in self.groups or row["target_pattern_id"] != self.groups[row["group_id"]]:
                    raise ValueError("unregistered group or target pattern")
                for key in ("security_id", "event_id"):
                    if not isinstance(row[key], str) or not row[key].strip():
                        raise ValueError("original security/event identities must be nonblank")
                position = _integer(row["calendar_index"], "calendar_index")
                horizon = _integer(row["horizon"], "horizon", minimum=1)
                if horizon not in self.horizons:
                    raise ValueError("unregistered observation horizon")
                day = date.fromisoformat(row["t0"])
                if day.isoformat() != row["t0"] or not 2010 <= day.year <= 2026 or row["mkt"] not in MARKETS[1:]:
                    raise ValueError("invalid fixed-period t0 or market state")
                for key in ("calendar_full", "event_main_eligible", "event_eligibility_excluded"):
                    if not isinstance(row[key], (bool, np.bool_)):
                        raise ValueError("projection eligibility/calendar fields must be booleans")
                if row["base_label"] not in {"hit", "loss", "flat-win", "unknown"} or row["effective_label"] not in {row["base_label"], "unknown"}:
                    raise ValueError("effective overlay cannot invent a base outcome")
                if row["event_main_eligible"] and (not row["calendar_full"] or row["event_eligibility_excluded"] or row["effective_label"] == "unknown"):
                    raise ValueError("effective main eligibility contradicts the projection")
                projection_key = (row["group_id"], row["event_id"], horizon)
                existing = reference.get(projection_key)
                if existing is not None and any(row[field] != existing[field] for field in fields):
                    raise ValueError("diagnostics disagree on the same event projection")
                reference[projection_key] = row
                clock = (row["security_id"], position)
                if clock in dates and dates[clock] != row["t0"]:
                    raise ValueError("calendar position has inconsistent t0 dates")
                dates[clock] = row["t0"]
                stocks.add(row["security_id"])
        if len(stocks) > 1:
            raise ValueError("add_stock requires one original stock identity")
        required_paths = {"path_category", "max_return", "peak_offset"}
        required_first = {"first_flag_state", "first_flag_flag_id", "first_flag_offset", "first_flag_all_flag_ids_json"}
        if not required_paths.issubset(tables.paths.columns) or not required_first.issubset(tables.first_flags.columns):
            raise ValueError("missing path or first-flag diagnostics")
        path_keys = set(tables.paths.loc[:, list(identity)].itertuples(index=False, name=None))
        first_keys = set(tables.first_flags.loc[:, list(identity)].itertuples(index=False, name=None))
        if path_keys != first_keys or set(reference) != path_keys:
            raise ValueError("path and first-flag populations must cover the same complete event projections")
        by_event: dict[tuple[str, str], set[int]] = {}
        for group, event, horizon in path_keys:
            by_event.setdefault((group, event), set()).add(horizon)
        if any(values != set(self.horizons) for values in by_event.values()):
            raise ValueError("stock feeds require all registered horizons")
        paths = [cast(dict[str, Any], row) for row in tables.paths.to_dict(orient="records")]
        first = {
            cast(tuple[str, str, int], tuple(row[key] for key in identity)): cast(dict[str, Any], row) for row in tables.first_flags.to_dict(orient="records")
        }
        return paths, first

    def add_stock(self, tables: FollowupTables, holding: pd.DataFrame) -> None:
        paths, first_rows = self._validated(tables)
        required_holding = {"security_id", "calendar_index", "horizon", "t0", "calendar_full", "observed_sessions", *METRICS}
        if not holding.columns.is_unique or not required_holding.issubset(holding.columns):
            raise ValueError("holding rows require unique fixed-clock return/context fields")
        holding_keys = ["security_id", "calendar_index", "horizon"]
        if bool(holding.duplicated(holding_keys).any()):
            raise ValueError("holding keys must be unique")
        stocks = {row["security_id"] for row in paths}
        selected_holding = holding.loc[cast(pd.Series, holding["security_id"]).isin(stocks)]
        holding_rows = {tuple(row[key] for key in holding_keys): cast(dict[str, Any], row) for row in selected_holding.to_dict(orient="records")}
        feeds = {(row["group_id"], row["security_id"]) for row in paths}
        if feeds & self._feeds:
            raise ValueError("duplicate stock/group feed")
        local: dict[tuple[Any, ...], _Cell] = {}

        def cell(family: str, meta: tuple[Any, ...], *tail: Any) -> _Cell:
            return local.setdefault((family, *meta, *tail), _Cell())

        for row in paths:
            holding_key = (row["security_id"], row["calendar_index"], row["horizon"])
            observation = holding_rows.get(holding_key)
            if observation is None or observation["t0"] != row["t0"] or observation["calendar_full"] != row["calendar_full"]:
                raise ValueError("event has no matching fixed-clock holding observation")
            observed = _integer(observation["observed_sessions"], "observed_sessions")
            if observed > row["horizon"] or bool(row["calendar_full"]) != (observed == row["horizon"]):
                raise ValueError("holding observed window contradicts its fixed horizon")
            if "base_first_hit_offset" in row and not pd.isna(row["base_first_hit_offset"]):
                hit = _observed_offset(row["base_first_hit_offset"], "base_first_hit_offset")
                if row["base_label"] != "hit" or hit > observed:
                    raise ValueError("base first-hit clock contradicts the observed window")
            if row["path_category"] not in PATHS:
                raise ValueError("invalid path category")
            first = first_rows[(row["group_id"], row["event_id"], row["horizon"])]
            state = first["first_flag_state"]
            if state not in FLAG_STATES:
                raise ValueError("invalid first-flag state")
            raw_flag = first["first_flag_flag_id"]
            flag = "none" if state == "all_false" and pd.isna(raw_flag) else "unknown" if pd.isna(raw_flag) else raw_flag
            if flag not in (*FLAG_IDS, "none", "unknown"):
                raise ValueError("invalid first-flag identity")
            ties = json.loads(first["first_flag_all_flag_ids_json"])
            if not isinstance(ties, list) or len(set(ties)) != len(ties) or any(value not in FLAG_IDS for value in ties):
                raise ValueError("first-flag ties must be unique registered flags")
            offset = first["first_flag_offset"]
            if state == "triggered":
                trigger = _observed_offset(offset, "first_flag_offset")
                if trigger > observed:
                    raise ValueError("first flag cannot occur outside the observed future")
            elif not pd.isna(offset):
                raise ValueError("unknown/all-false first histories cannot invent a certain trigger")
            for state_name in STATES:
                fraction = observation[f"holding_{state_name}_fraction"]
                if not pd.isna(fraction) and (not isinstance(fraction, Real) or isinstance(fraction, (bool, np.bool_)) or not 0 <= float(fraction) <= 1):
                    raise ValueError("holding fractions must retain their supplied state proportions")
            code = row["security_id"]
            original = code[3:] if code.startswith("TW:") else code[2:] if code.startswith("TW") else code
            if not original.strip():
                raise ValueError("empty original code after removing TW identity prefix")
            split = split_for_code(original)
            year = date.fromisoformat(row["t0"]).year
            era = "2010-2012" if year <= 2012 else "2013-2018" if year <= 2018 else "2019-2026"
            population, included = _population(row["effective_label"]), _included(row)
            for era_value, market in product(("all", era), ("all", row["mkt"])):
                meta = (row["group_id"], row["target_pattern_id"], row["horizon"], split, era_value, market, population)
                path_cell = cell("path", meta, row["path_category"])
                path_cell.audit(row, included)
                first_cell = cell("first", meta, flag, state)
                first_cell.audit(row, included)
                holding_cell = cell("holding", meta)
                holding_cell.audit(row, included)
                if included:
                    path_cell.count("path_n")
                    path_cell.sample("max_return", row["max_return"])
                    path_cell.sample("peak_offset", row["peak_offset"])
                    first_cell.count("first_n")
                    first_cell.sample("first_day", offset)
                    for tied in ties:
                        cell("first", meta, tied, state).count("same_day_tie_n")
                    for metric in METRICS:
                        holding_cell.sample(metric, observation[metric])
        for key, addition in local.items():
            self._cells.setdefault(key, _Cell()).merge(addition)
        self._feeds.update(feeds)
        LOGGER.debug("Failure summary feeds=%d sparse_cells=%d numeric_bytes=%d", len(self._feeds), len(self._cells), self.memory_nbytes)

    def finalize(self) -> FailureSummaryTables:
        paths: list[dict[str, Any]] = []
        first: list[dict[str, Any]] = []
        holding: list[dict[str, Any]] = []
        blank = _Cell()
        for group, horizon, split, era, market, population in product(sorted(self.groups), self.horizons, SPLITS, ERAS, MARKETS, POPULATIONS):
            meta = (group, self.groups[group], horizon, split, era, market, population)
            base = {**dict(zip(META, meta, strict=True)), "numeric_sample_scope": _scope(population)}
            for category in PATHS:
                selected = self._cells.get(("path", *meta, category), blank)
                paths.append({
                    **base,
                    "path_category": category,
                    **selected.values(),
                    "path_n": selected.counts.get("path_n", 0),
                    **selected.quantiles("max_return"),
                    **selected.quantiles("peak_offset"),
                })
            for flag, state in product((*FLAG_IDS, "none", "unknown"), FLAG_STATES):
                selected = self._cells.get(("first", *meta, flag, state), blank)
                first.append({
                    **base,
                    "flag_id": flag,
                    "first_state": state,
                    **selected.values(),
                    "first_n": selected.counts.get("first_n", 0),
                    "same_day_tie_n": selected.counts.get("same_day_tie_n", 0),
                    **selected.quantiles("first_day"),
                })
            selected = self._cells.get(("holding", *meta), blank)
            values: dict[str, Any] = {**base, **selected.values()}
            for metric in METRICS:
                values.update(selected.quantiles(metric))
            holding.append(values)
        return FailureSummaryTables(
            pd.DataFrame(paths, columns=pd.Index(PATH_COLUMNS)),
            pd.DataFrame(first, columns=pd.Index(FIRST_COLUMNS)),
            pd.DataFrame(holding, columns=pd.Index(HOLDING_COLUMNS)),
        )
