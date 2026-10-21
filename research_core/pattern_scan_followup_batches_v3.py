"""Exact followup summaries with one group/horizon's raw samples alive at once."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import fields
from typing import Any

import pandas as pd

from research_core.pattern_scan_failure_summary_v1 import FailureAccumulator, FailureSummaryTables
from research_core.pattern_scan_followup_summary_v1 import FollowupAccumulator, FollowupSummaryTables
from research_core.pattern_scan_followup_v1 import FollowupTables
from research_core.research_measurement_v1 import phase_receipt, resource_sample

LOGGER = logging.getLogger(__name__)
HORIZONS = (126, 252)
BatchFeeds = Callable[[str, int], Iterable[tuple[FollowupTables, pd.DataFrame]]]


def _summarize_batch(
    group: str,
    target: str,
    horizon: int,
    feeds: BatchFeeds,
) -> tuple[FollowupSummaryTables, FailureSummaryTables, dict[str, Any]]:
    before = resource_sample()
    LOGGER.info("Followup batch start group=%s target=%s horizon=%d", group, target, horizon)
    followup = FollowupAccumulator({group: target}, horizons=(horizon,))
    failure = FailureAccumulator({group: target}, horizons=(horizon,))
    feed_n = 0
    for tables, holding in feeds(group, horizon):
        followup.add_stock(tables)
        failure.add_stock(tables, holding)
        feed_n += 1
        del tables, holding
    followup_bytes, failure_bytes = followup.memory_nbytes, failure.memory_nbytes
    summaries = followup.finalize()
    failures = failure.finalize()
    # Neither returned table dataclass references an accumulator or its cells.
    # Release both exact raw sample stores before the next batch is constructed.
    del followup, failure
    measurement = {
        "group_id": group,
        "target_pattern_id": target,
        "horizon": horizon,
        "stock_feed_n": feed_n,
        "followup_raw_sample_bytes": followup_bytes,
        "failure_raw_sample_bytes": failure_bytes,
        "total_raw_sample_bytes": followup_bytes + failure_bytes,
        "raw_sample_scope": "retained numeric array payload before finalize; excludes Python bookkeeping, quantile temporaries and result frames",
        "phase": phase_receipt("followup_summary_batch", before, resource_sample()),
    }
    LOGGER.info("Followup batch complete group=%s horizon=%d feeds=%d raw_sample_bytes=%d", group, horizon, feed_n, measurement["total_raw_sample_bytes"])
    return summaries, failures, measurement


def _combine(frames: list[pd.DataFrame]) -> pd.DataFrame:
    # A batch with only null quantiles infers object; another may infer float.
    # Reapply pandas' ordinary column inference after concatenating, as in the
    # original finalizer's single DataFrame construction. All-None stays object.
    return pd.concat(frames, ignore_index=True).infer_objects(copy=False)


def summarize_followup_batches(
    groups: dict[str, str],
    feeds: BatchFeeds,
) -> tuple[FollowupSummaryTables, FailureSummaryTables, list[dict[str, Any]]]:
    """Consume precomputed stock projections without recomputing observations.

    ``feeds(group, horizon)`` must supply complete, already bound stock tables
    for precisely that group/horizon, in the same stock and event order as the
    original reduction. Existing accumulators validate the projections. Empty
    candidates may yield no stocks; their registered zero cells are retained.
    Only finalized result frames survive across batches. Native resource data
    follows ``phase_receipt`` semantics, including process-lifetime peak RSS.
    """
    if not groups:
        return FollowupAccumulator({}).finalize(), FailureAccumulator({}).finalize(), []
    if any(not isinstance(group, str) or not group.strip() or not isinstance(target, str) or not target.strip() for group, target in groups.items()):
        raise ValueError("registered group/pattern identities must be nonblank strings")
    summary_frames: dict[str, list[pd.DataFrame]] = {field.name: [] for field in fields(FollowupSummaryTables)}
    failure_frames: dict[str, list[pd.DataFrame]] = {field.name: [] for field in fields(FailureSummaryTables)}
    measurements = []
    for group in sorted(groups):
        for horizon in HORIZONS:
            summaries, failures, measurement = _summarize_batch(group, groups[group], horizon, feeds)
            for name, chunks in summary_frames.items():
                chunks.append(getattr(summaries, name))
            for name, chunks in failure_frames.items():
                chunks.append(getattr(failures, name))
            measurements.append(measurement)
            del summaries, failures
    # Each finalizer enumerates sorted group then horizon. Its exclusions are
    # sorted by group/horizon first, so this concatenation also preserves that
    # family's global ordering, including dynamically observed reason rows.
    return (
        FollowupSummaryTables(*(_combine(chunks) for chunks in summary_frames.values())),
        FailureSummaryTables(*(_combine(chunks) for chunks in failure_frames.values())),
        measurements,
    )
