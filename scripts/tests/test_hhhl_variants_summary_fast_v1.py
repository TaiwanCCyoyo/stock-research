"""Complete synthetic frame parity against the byte-preserved summary v1."""

from typing import Any, cast

import pandas as pd
import pytest

from research_core.hhhl_variants_features import FEATURES
from research_core.hhhl_variants_selection import Atom, Candidate, DevelopmentCounts, candidate_id
from research_core.hhhl_variants_summary import StudySummaries
from research_core.hhhl_variants_summary_fast_v1 import FastStudySummaries

COHORTS = ("P-clean", "P-over", "P-all", "C-nh", "C-52w", "C-base")
SPLITS = ("development", "cross-check")
HORIZONS = (126, 252)
YEARS = tuple(range(2019, 2027))


def candidates() -> tuple[Candidate, ...]:
    atoms = (
        (Atom("D", "D", "ge100"),),
        (Atom("A", "A", "lt10"), Atom("D", "D", "ge100")),
        (Atom("B", "B", "ge20"), Atom("G", "G", "ge500")),
    )
    return tuple(Candidate(candidate_id(items), items, DevelopmentCounts(0, 0, 0, 0)) for items in atoms)


def synthetic_frame(*, compact: bool, endpoint_aliases: bool, include_optional: bool) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for cohort in COHORTS:
        for split in SPLITS:
            for horizon in HORIZONS:
                for year in YEARS:
                    for position in range(6):
                        full = position < 4
                        label = ("hit", "loss", "flat-win", "unknown", "hit", "unknown")[position]
                        overhead = cohort == "P-over" or cohort == "P-all" and position % 2 == 0
                        row: dict[str, Any] = dict(
                            event_id=f"{cohort}-{split}-{horizon}-{year}-{position}",
                            code="0050" if position % 2 == 0 else "1234",
                            cohort_id=cohort,
                            split_id=split,
                            horizon=horizon,
                            year=year,
                            calendar_full=full,
                            label=label,
                        )
                        for feature_id, definition in FEATURES.items():
                            outside = definition.pattern_only and not cohort.startswith("P-") or definition.overhead_only and not overhead
                            state = "not_applicable" if outside else "feature_unknown" if position == 3 else "known"
                            bin_id = sorted(set(definition.bin_ids))[0] if state == "known" else None
                            if feature_id == "D" and state == "known" and position % 2 == 0:
                                bin_id = "ge100"
                            if feature_id == "A" and state == "known":
                                bin_id = "lt10"
                            row[f"{feature_id}_bin"] = bin_id
                            row[f"{feature_id}_status"] = state
                            row[f"{feature_id}_reason"] = "outside_feature_cohort" if outside else "warmup_insufficient" if state == "feature_unknown" else None
                        if include_optional:
                            row["unknown_reason"] = "missing_before_hit" if position == 3 else "censored_window" if position == 5 else None
                            for diagnostic in ("drawdown10_full_state", "drawdown20_full_state", "before_hit10_state", "before_hit20_state"):
                                offset = 1 if diagnostic.startswith("before_hit") else 0
                                row[diagnostic] = ("triggered", "all_false", "unknown")[(position + offset) % 3]
                            for indicator in ("hit_then_below_anchor", "hit_endpoint_unknown"):
                                row[f"{indicator}_n" if endpoint_aliases else indicator] = position == (0 if indicator == "hit_then_below_anchor" else 4)
                        rows.append(row)
    frame = pd.DataFrame(rows)
    if compact:
        for name in frame.columns:
            if frame[name].dtype == object or name in {"year", "horizon", "calendar_full"}:
                frame[name] = frame[name].astype("category")
    return frame


@pytest.mark.parametrize("initialize", [False, True])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("endpoint_aliases,include_optional", [(False, True), (True, True), (False, False)])
def test_complete_frame_exact_parity(initialize: bool, compact: bool, endpoint_aliases: bool, include_optional: bool) -> None:
    fixed = candidates()
    regular, fast = StudySummaries(), FastStudySummaries()
    if initialize:
        for cohort in COHORTS:
            for split in SPLITS:
                for horizon in HORIZONS:
                    regular.initialize_group(cohort, split, horizon, fixed)
                    fast.initialize_group(cohort, split, horizon, fixed)
    frame = synthetic_frame(compact=compact, endpoint_aliases=endpoint_aliases, include_optional=include_optional)
    # Multiple batches retain cross-year shared-code unions and reason counters.
    split_position = len(frame) // 2
    for batch in (frame.iloc[:split_position], frame.iloc[split_position:]):
        regular.add_observations(batch, fixed)
        fast.add_observations(batch, fixed)
    expected, actual = regular.finalize(), fast.finalize()
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert {"baseline", "single", "candidate", "Kdistribution", "year", "drop_best_year"}.issubset(set(actual["row_kind"]))
    assert cast(pd.Series, actual["known_n"]).eq(0).to_numpy(dtype=bool).any()
    assert cast(pd.Series, actual["known_security_n"]).eq(2).to_numpy(dtype=bool).any()
    assert cast(pd.Series, actual["outcome_reason_counts"]).eq("{}").to_numpy(dtype=bool).any()


def test_empty_initialized_group_exact_parity() -> None:
    regular, fast = StudySummaries(), FastStudySummaries()
    for instance in (regular, fast):
        instance.initialize_group("P-all", "development", 126, candidates())
    pd.testing.assert_frame_equal(fast.finalize(), regular.finalize(), check_exact=True)


def test_candidates_only_full_filtered_frame_exact_parity() -> None:
    fixed = candidates()
    regular, fast = StudySummaries(), FastStudySummaries(candidates_only=True)
    for cohort in COHORTS:
        for split in SPLITS:
            for horizon in HORIZONS:
                for instance in (regular, fast):
                    instance.initialize_group(cohort, split, horizon, fixed)
    frame = synthetic_frame(compact=True, endpoint_aliases=True, include_optional=True)
    regular.add_observations(frame, fixed)
    fast.add_observations(frame, fixed)
    expected, actual = regular.finalize(), fast.finalize()
    kinds = ["candidate", "Kdistribution"]
    expected = cast(pd.DataFrame, expected[expected["base_row_kind"].isin(kinds)]).reset_index(drop=True)
    actual = cast(pd.DataFrame, actual[actual["base_row_kind"].isin(kinds)]).reset_index(drop=True)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
