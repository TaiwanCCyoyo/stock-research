"""Feature and eligibility values, taken from the canonical implementation rather than re-derived.

The 2026-09-12 prototype re-implemented the six features from their prose descriptions and got
three of them wrong: `ext_20` included the current bar in its own prior high (so a breakout could
never read positive), `vol_ratio` compared a 20-bar mean to a 60-bar mean instead of today's
volume to its prior-20 mean, and `contraction` used a 20-bar close range instead of
ATR(14)/close against its own 60-bar mean. It also used a min-max percentile instead of pandas'
`rank(pct=True, method="average")`, and it read the as-of bar inside a strictly-prior eligibility
window.

Rather than fix six formulas and hope, this module **imports `tasks/20260823-rotation-universe`
directly**. `compute()` is the definition; anything written here that merely agreed with it would
be free to drift. The differential tests in `tests/test_canonical_features.py` exist to prove the
import is actually what is being used.

Nothing here reads a real file. `compute(px, meta)` takes both the price frame and the industry
metadata as arguments, so an injected synthetic frame and explicit metadata produce the reference
values with no cache access at all -- which is what keeps this batch inside its "zero real market
data" boundary while still using the real code.

Two things this module adds on top of the canonical table, neither of which changes a value:

- an **as-of view** that refuses to hand back a row dated after the decision date, so the runner
  cannot accidentally read forward even though the table is computed over the whole frame;
- the **six-feature restriction**. The canonical table carries eight features; the two cohort
  columns depend on a current-snapshot industry join with no as-of history, which the candidate
  packet records as a defect, so they are dropped here and never scored.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[5]
CANONICAL_TASK = REPO_ROOT / "tasks" / "20260823-rotation-universe"
if str(CANONICAL_TASK) not in sys.path:
    sys.path.insert(0, str(CANONICAL_TASK))

from eligibility import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    LIQ_FLOOR,
    LIQ_WINDOW,
    MIN_HISTORY,
    add_eligibility_columns,
)
from features import RANK_PREFIX, compute  # noqa: E402  # pyright: ignore[reportMissingImports]

# The candidate is the six non-cohort features. `cohort_ret_20` and `cohort_breadth` are computed
# by the canonical table but deliberately not read: their industry join has no as-of history.
SIX_FEATURES = ("ret_20", "ret_60", "ext_20", "above_ma60", "vol_ratio", "contraction")
CANDIDATE_WEIGHTS: Mapping[str, float] = {
    "r_ret_20": 1.0,
    "r_ret_60": 1.0,
    "r_ext_20": 1.0,
    "r_above_ma60": 1.0,
    "r_vol_ratio": 1.0,
    "r_contraction": -1.0,
}
# development-measurement: equal-weight percentile ranks of trailing 20- and 60-session returns.
CONTROL_WEIGHTS: Mapping[str, float] = {"r_ret_20": 1.0, "r_ret_60": 1.0}
SIX_RANK_COLUMNS = tuple(RANK_PREFIX + name for name in SIX_FEATURES)


class FeatureError(ValueError):
    """The injected frame cannot produce canonical feature values."""


@dataclass(frozen=True)
class FeatureRow:
    """One (code, date) feature observation, with explicit unavailability.

    A NaN feature is `None` here, never 0.0. The canonical table leaves a column NaN until its
    window is genuinely complete, and zero-filling would make an incomplete window look like a
    neutral reading.
    """

    code: str
    day: date
    eligible: bool
    ranks: Mapping[str, float | None]
    raw: Mapping[str, float | None]

    @property
    def scorable(self) -> bool:
        return self.eligible and all(value is not None for value in self.ranks.values())


def _as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, pd.Timestamp):
        return value
    return pd.Timestamp(value).date()


def build_price_frame(bars: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Assemble the canonical input frame from explicit rows.

    Required columns are exactly those `features.load_prices` produces. `Volume` is in LOTS,
    which is the unit the canonical eligibility floor is expressed in; supplying shares here
    would understate turnover by 1000x and silently change the eligible set.
    """
    frame = pd.DataFrame(list(bars))
    missing = {"Code", "Date", "Open", "High", "Low", "Close", "Volume"} - set(frame.columns)
    if missing:
        raise FeatureError(f"price frame is missing required columns: {sorted(missing)}")
    frame["Code"] = frame["Code"].astype(str)
    frame["Date"] = pd.to_datetime(frame["Date"])
    return frame.sort_values(["Code", "Date"]).reset_index(drop=True)


def canonical_table(prices: pd.DataFrame, categories: pd.DataFrame | None = None) -> pd.DataFrame:
    """The canonical feature/eligibility table for an injected frame.

    `categories` is supplied explicitly so no `symbol_meta` snapshot is read. The cohort columns
    it feeds are not used by this candidate; it exists because `compute` requires the join.
    """
    if categories is None:
        codes = sorted(prices["Code"].unique())
        # A single placeholder category. The cohort columns are dropped downstream, and a
        # constant category cannot leak information into the six features, which are all
        # computed per-symbol before any grouping.
        categories = pd.DataFrame({"Code": codes, "industry_category": ["UNSPECIFIED"] * len(codes)})
    return compute(prices, categories)


class AsOfFeatures:
    """As-of lookup over a canonical table, with a hard decision-date boundary."""

    def __init__(self, table: pd.DataFrame) -> None:
        self._rows: dict[tuple[str, date], FeatureRow] = {}
        self._by_date: dict[date, list[str]] = {}
        for record in table.to_dict("records"):
            code, day = str(record["Code"]), _as_date(record["Date"])
            ranks = {column: _none_if_nan(record.get(column)) for column in SIX_RANK_COLUMNS}
            raw = {name: _none_if_nan(record.get(name)) for name in SIX_FEATURES}
            row = FeatureRow(code=code, day=day, eligible=bool(record["eligible"]), ranks=ranks, raw=raw)
            self._rows[(code, day)] = row
            self._by_date.setdefault(day, []).append(code)
        for day in self._by_date:
            self._by_date[day].sort()

    def row(self, code: str, day: date) -> FeatureRow | None:
        return self._rows.get((code, day))

    def pool(self, as_of: date) -> tuple[FeatureRow, ...]:
        """Every scorable row on the decision date.

        The date filter is exact rather than `<=`: a decision on `t` reads the features dated
        `t`, which the canonical table already guarantees were computed from bars up to and
        including `t` and nothing after.
        """
        codes = self._by_date.get(as_of, ())
        return tuple(row for code in codes if (row := self._rows[(code, as_of)]).scorable)

    def dates(self) -> tuple[date, ...]:
        return tuple(sorted(self._by_date))


def _none_if_nan(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return None if number != number else number


def rank_within_universe(table: pd.DataFrame, universe: Mapping[date, frozenset[str]], *, membership_basis: str) -> pd.DataFrame:
    """Re-rank the canonical table's cross-section inside a dated membership population.

    This does not re-derive a feature. Canonical `compute()` already computes each raw feature on
    the full frame and then ranks **only the rows eligible on that date**:

        ranked = out[out["eligible"]]
        rank = ranked.groupby("Date", sort=False)[column].rank(pct=True, method="average")

    The single line below is that expression with a narrower mask -- eligibility AND dated
    identity -- so the population question is answered where canonical already asks it. The raw
    feature columns are untouched, which is what preserves every stock's legitimate warm-up
    history: a code's `ret_60` does not depend on who else was listed.

    This is only sound because the six scored features are **population-independent**: `ret_20`,
    `ret_60`, `ext_20`, `above_ma60`, `vol_ratio` and `contraction` are per-code rolling windows.
    The canonical table's other two columns, `cohort_ret_20` and `cohort_breadth`, are computed
    from a date's eligible peers and would therefore need recomputation, not re-ranking. They are
    dropped by this candidate. Adding a cohort feature later invalidates this function; it would
    have to re-enter `compute()` with the narrower mask instead.
    """
    out = table.copy()
    out["canonical_eligible"] = out["eligible"].to_numpy()
    days = out["Date"].map(_as_date)
    in_universe = [code in universe.get(day, frozenset()) for code, day in zip(out["Code"], days, strict=True)]
    out["in_universe"] = in_universe
    out["membership_basis"] = membership_basis
    out["eligible"] = out["canonical_eligible"] & out["in_universe"]

    ranked = out[out["eligible"]]
    for name in SIX_FEATURES:
        out[RANK_PREFIX + name] = ranked.groupby("Date", sort=False)[name].rank(pct=True, method="average")
    for name in ("cohort_ret_20", "cohort_breadth"):
        # Not re-rankable under a narrower mask, and not scored. Blanked rather than left stale so
        # nothing downstream can read a percentile that belongs to the wider population.
        if RANK_PREFIX + name in out.columns:
            out[RANK_PREFIX + name] = float("nan")
    return out


def strictly_prior_eligibility(prices: pd.DataFrame) -> pd.DataFrame:
    """Canonical eligibility columns, exposed for the differential tests.

    `add_eligibility_columns` is where the strictly-prior rule lives: `cumcount()` counts bars
    before the row's own date, and `shift(1)` removes the row from its own liquidity window.
    """
    return add_eligibility_columns(prices)


__all__ = [
    "CANDIDATE_WEIGHTS",
    "CONTROL_WEIGHTS",
    "LIQ_FLOOR",
    "LIQ_WINDOW",
    "MIN_HISTORY",
    "SIX_FEATURES",
    "SIX_RANK_COLUMNS",
    "AsOfFeatures",
    "FeatureError",
    "FeatureRow",
    "build_price_frame",
    "canonical_table",
    "rank_within_universe",
    "strictly_prior_eligibility",
]
