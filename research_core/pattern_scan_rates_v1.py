"""Integer event summaries over one explicitly caller-filtered cohort.

Unknown and censored counts overlap. Neither enters the main known denominator;
Both calendar strata exclude explicit eligibility blocks from uncertainty bounds.
Without event_eligibility_excluded, only full-calendar known ineligible rows are
inferred excluded; unspecified eligibility of unknown/censored rows assumes none.
The formal runner must supply the explicit boolean exclusion column.
"""

from __future__ import annotations

import logging
from datetime import date
from numbers import Integral
from typing import TypeAlias

import numpy as np
import pandas as pd

Summary: TypeAlias = dict[str, int | float | None]
LOGGER = logging.getLogger(__name__)
REQUIRED_COLUMNS = ("security_id", "event_id", "t0", "horizon", "effective_label", "calendar_full", "event_main_eligible")


def _validated(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(REQUIRED_COLUMNS) - set(frame.columns)
    if missing or not frame.columns.is_unique:
        raise ValueError(f"invalid event columns; missing={sorted(missing)}")
    for name in ("security_id", "event_id"):
        if not bool(frame[name].map(lambda value: isinstance(value, str) and bool(value.strip())).all()):
            raise ValueError(f"{name} requires nonblank strings")
    for value in frame["t0"]:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError("t0 requires canonical ISO dates")
    for value in frame["horizon"]:
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < 1:
            raise ValueError("horizon requires positive integers")
    for name in ("calendar_full", "event_main_eligible"):
        if not bool(frame[name].map(lambda value: isinstance(value, (bool, np.bool_))).all()):
            raise ValueError(f"{name} requires boolean values")
    if "event_eligibility_excluded" in frame:
        if not bool(frame["event_eligibility_excluded"].map(lambda value: isinstance(value, (bool, np.bool_))).all()):
            raise ValueError("event_eligibility_excluded requires boolean values")
        if (frame["event_main_eligible"].astype(bool) & frame["event_eligibility_excluded"].astype(bool)).any():
            raise ValueError("eligible events cannot have an eligibility exclusion")
    if not bool(frame["effective_label"].isin(("hit", "loss", "flat-win", "unknown")).all()):
        raise ValueError("invalid effective_label")
    if frame.duplicated(["event_id", "horizon"]).any():
        raise ValueError("duplicate event_id/horizon")
    if (frame["event_main_eligible"].astype(bool) & (~frame["calendar_full"].astype(bool) | frame["effective_label"].eq("unknown"))).any():
        raise ValueError("eligible events require full-calendar known labels")
    return frame


def summarize_events(frame: pd.DataFrame) -> Summary:
    """Summarize one cohort without regrouping, filtering or changing outcomes."""
    rows = _validated(frame)
    labels = rows["effective_label"]
    full = rows["calendar_full"].astype(bool)
    eligible = rows["event_main_eligible"].astype(bool)
    unknown = labels.eq("unknown")
    counts = rows.groupby("security_id", sort=False).size()
    known_n = int(eligible.sum())
    hit_n = int((eligible & labels.eq("hit")).sum())
    loss_n = int((eligible & labels.eq("loss")).sum())
    full_unknown_n = int((full & unknown).sum())
    excluded = rows["event_eligibility_excluded"].astype(bool) if "event_eligibility_excluded" in rows else full & ~unknown & ~eligible
    full_potential = full & ~excluded & (eligible | unknown)
    potential = int(full_potential.sum())
    potential_unknown_n = int((full_potential & unknown).sum())
    censored_potential = ~full & ~excluded
    censored_potential_n = int(censored_potential.sum())
    censored_hit_n = int((censored_potential & labels.eq("hit")).sum())
    censored_potential_unknown_n = int((censored_potential & unknown).sum())
    result: Summary = {
        "event_n": len(rows),
        "distinct_stock_n": len(counts),
        "per_stock_event_count_median": float(counts.median()) if len(counts) else None,
        "per_stock_event_count_max": int(counts.max()) if len(counts) else 0,
        "known_n": known_n,
        "unknown_n": int(unknown.sum()),
        "censored_n": int((~full).sum()),
        "excluded_known_n": int((full & ~unknown & ~eligible).sum()),
        "hit_n": hit_n,
        "loss_n": loss_n,
        "flat_win_n": int((eligible & labels.eq("flat-win")).sum()),
        "hit_rate": hit_n / known_n if known_n else None,
        "loss_rate": loss_n / known_n if known_n else None,
        "observed_hit_n": int(labels.eq("hit").sum()),
        "full_calendar_n": int(full.sum()),
        "full_calendar_unknown_n": full_unknown_n,
        "full_calendar_observed_hit_n": int((full & labels.eq("hit")).sum()),
        "censored_unknown_n": int((~full & unknown).sum()),
        "censored_observed_hit_n": int((~full & labels.eq("hit")).sum()),
        "full_main_potential_n": potential,
        "full_eligibility_excluded_n": int((full & excluded).sum()),
        "censored_eligibility_excluded_n": int((~full & excluded).sum()),
        "censored_potential_n": censored_potential_n,
        "censored_hit_lower_bound": censored_hit_n / censored_potential_n if censored_potential_n else None,
        "censored_hit_upper_bound": (censored_hit_n + censored_potential_unknown_n) / censored_potential_n if censored_potential_n else None,
        "full_calendar_hit_lower_bound": hit_n / potential if potential else None,
        "full_calendar_hit_upper_bound": (hit_n + potential_unknown_n) / potential if potential else None,
    }
    LOGGER.debug("Event summary: events=%d eligible=%d full_unknown=%d censored=%d", len(rows), known_n, full_unknown_n, result["censored_n"])
    return result


def drop_best_hit_year(frame: pd.DataFrame, *, years: tuple[int, ...] = tuple(range(2010, 2027))) -> tuple[int | None, Summary]:
    """Remove the approved year with most eligible hits; earlier ties win."""
    rows = _validated(frame)
    if not years or len(set(years)) != len(years) or any(isinstance(year, bool) or not isinstance(year, int) or year < 1 or year > 9999 for year in years):
        raise ValueError("years require unique valid integer years")
    if rows.empty:
        return None, summarize_events(rows)
    event_years = rows["t0"].map(lambda value: date.fromisoformat(value).year)
    eligible_hits = rows["event_main_eligible"].astype(bool) & rows["effective_label"].eq("hit")
    removed = min(years, key=lambda year: (-int((eligible_hits & event_years.eq(year)).sum()), year))
    LOGGER.debug("Dropping best eligible-hit year %d from %d events", removed, len(rows))
    return removed, summarize_events(rows.loc[~event_years.eq(removed)])
