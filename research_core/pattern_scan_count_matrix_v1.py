"""Batch integer event vectors and cell/stock/year membership accumulation."""

from __future__ import annotations

import logging
from typing import cast

import numpy as np
import pandas as pd

from research_core.pattern_scan_rates_v1 import summarize_events
from research_core.pattern_scan_summary_store_v1 import COUNT_FIELDS, YEARS

LOGGER = logging.getLogger(__name__)
GROUP_COLUMNS = ("cell_id", "security_id", "year", "horizon")


def event_count_vectors(frame: pd.DataFrame) -> pd.DataFrame:
    """Return exactly COUNT_FIELDS as int64 0/1, indexed by unique event_id.

    Effective labels have the same meaning as the public summary oracle; a
    preserved base_label is never substituted for an event quality projection.
    Explicit eligibility exclusions affect uncertainty bounds independently
    from observed/unknown/censored counts. The oracle's legacy exclusion
    inference is retained when the optional exclusion field is absent.
    """
    summarize_events(frame)  # Validate once per batch with the public contract.
    if frame["event_id"].duplicated().any():
        raise ValueError("event count vectors require unique event_id")
    labels = cast(pd.Series, frame["effective_label"])
    full = cast(pd.Series, frame["calendar_full"]).astype(bool)
    eligible = cast(pd.Series, frame["event_main_eligible"]).astype(bool)
    unknown = labels.eq("unknown")
    hit, loss, flat = labels.eq("hit"), labels.eq("loss"), labels.eq("flat-win")
    excluded = cast(pd.Series, frame["event_eligibility_excluded"]).astype(bool) if "event_eligibility_excluded" in frame else full & ~unknown & ~eligible
    full_potential = full & ~excluded & (eligible | unknown)
    censored_potential = ~full & ~excluded
    masks = {
        "event_n": pd.Series(True, index=frame.index),
        "known_n": eligible,
        "unknown_n": unknown,
        "censored_n": ~full,
        "excluded_known_n": full & ~unknown & ~eligible,
        "hit_n": eligible & hit,
        "loss_n": eligible & loss,
        "flat_win_n": eligible & flat,
        "observed_hit_n": hit,
        "full_calendar_n": full,
        "full_calendar_unknown_n": full & unknown,
        "full_calendar_observed_hit_n": full & hit,
        "censored_unknown_n": ~full & unknown,
        "censored_observed_hit_n": ~full & hit,
        "full_main_potential_n": full_potential,
        "full_eligibility_excluded_n": full & excluded,
        "censored_eligibility_excluded_n": ~full & excluded,
        "censored_potential_n": censored_potential,
        "full_potential_unknown_n": full & ~excluded & unknown,
        "censored_potential_hit_n": censored_potential & hit,
        "censored_potential_unknown_n": censored_potential & unknown,
    }
    result = pd.DataFrame(
        {field: cast(pd.Series, masks[field]).to_numpy(dtype=np.int64) for field in COUNT_FIELDS}, index=pd.Index(frame["event_id"].to_numpy(), name="event_id")
    )
    LOGGER.debug("Built event count vectors events=%d fields=%d", len(result), len(COUNT_FIELDS))
    return result


def _empty() -> pd.DataFrame:
    return pd.DataFrame({
        column: pd.Series(dtype="int64" if column in {"year", "horizon", *COUNT_FIELDS} else object) for column in (*GROUP_COLUMNS, *COUNT_FIELDS)
    })


def aggregate_memberships(frame: pd.DataFrame, membership_rows: pd.DataFrame) -> pd.DataFrame:
    """Sum integer counts for one stock/horizon across caller-owned cells.

    Memberships supply event_id/cell_id and may assign an event to several
    independent bins/facets. Duplicate event/cell memberships fail rather than
    multiply events. Cell metadata and cross-batch feed uniqueness remain with
    the caller; this pure operation opens no store and computes no rate average.
    """
    vectors = event_count_vectors(frame)
    if not membership_rows.columns.is_unique or not {"event_id", "cell_id"}.issubset(membership_rows):
        raise ValueError("memberships require unique event_id/cell_id columns")
    members = cast(pd.DataFrame, membership_rows[["event_id", "cell_id"]]).copy(deep=True)
    for column in ("event_id", "cell_id"):
        if not cast(pd.Series, members[column]).map(lambda value: isinstance(value, str) and bool(value.strip())).all():
            raise ValueError("membership identities require nonblank strings")
    if members.duplicated(["event_id", "cell_id"]).any():
        raise ValueError("duplicate event/cell membership")
    if not cast(pd.Series, members["event_id"]).isin(vectors.index).all():
        raise ValueError("membership references an unknown event")
    if frame.empty:
        return _empty()
    if cast(pd.Series, frame["security_id"]).nunique() != 1 or cast(pd.Series, frame["horizon"]).nunique() != 1:
        raise ValueError("membership accumulation requires one stock and one horizon")
    years = cast(pd.Series, frame["t0"]).str.slice(0, 4).astype("int64")
    if not years.isin(YEARS).all():
        raise ValueError("event years must be 2010..2026")
    if members.empty:
        return _empty()
    indexed = vectors.copy(deep=True)
    indexed["security_id"] = frame["security_id"].to_numpy()
    indexed["year"] = years.to_numpy()
    indexed["horizon"] = frame["horizon"].to_numpy(dtype=np.int64)
    joined = members.merge(indexed.reset_index(), on="event_id", how="left", validate="many_to_one", sort=False)
    result = cast(pd.DataFrame, joined.groupby(list(GROUP_COLUMNS), sort=True, observed=True)[list(COUNT_FIELDS)].sum()).reset_index()
    result = result.loc[:, [*GROUP_COLUMNS, *COUNT_FIELDS]]
    for field in (*COUNT_FIELDS, "year", "horizon"):
        result[field] = result[field].astype("int64")
    LOGGER.debug("Aggregated membership counts events=%d memberships=%d cell_stock_years=%d", len(frame), len(members), len(result))
    return result
