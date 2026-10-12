"""Synthetic summary counts for matched descriptive comparisons."""

from typing import cast

import pandas as pd
import pytest

from research_core.hhhl_variants_rates import RateAccumulator
from research_core.hhhl_variants_references import attach_references
from research_core.hhhl_variants_selection import Atom, Candidate, DevelopmentCounts, candidate_id


def packet(
    accumulator: RateAccumulator,
    cohort: str,
    year: int,
    hit: int,
    loss: int,
    flat: int,
    *,
    kind: str = "baseline",
    feature: str | None = None,
    bin_id: str | None = None,
    candidate: str | None = None,
    outside: bool = False,
) -> None:
    metadata = dict(
        row_kind=kind,
        cohort_id=cohort,
        split_id="development",
        horizon=126,
        candidate_id=candidate,
        feature_id=feature,
        bin_id=bin_id,
        not_applicable_reason="outside_feature_cohort" if outside else None,
    )
    counts = dict(calendar_full_n=hit + loss + flat, hit_n=hit, loss_n=loss, flat_win_n=flat)
    accumulator.add((cohort, kind, feature, bin_id, candidate), metadata, year, counts)


def target(frame: pd.DataFrame, kind: str = "baseline", span: str = "baseline") -> pd.Series:
    return frame[(frame.cohort_id == "P-clean") & (frame.base_row_kind == kind) & (frame.row_kind == span)].iloc[0]


def test_drop_control_excludes_target_best_year_not_control_best_year() -> None:
    accumulator = RateAccumulator()
    packet(accumulator, "P-clean", 2020, 8, 2, 0)
    packet(accumulator, "P-clean", 2021, 2, 3, 5)
    packet(accumulator, "C-nh", 2020, 1, 9, 0)
    packet(accumulator, "C-nh", 2021, 9, 1, 0)
    result = attach_references(pd.DataFrame(accumulator.finalize()), ())
    pooled = target(result)
    assert pooled.reference_cnh_hit_rate == 0.5
    dropped = target(result, span="drop_best_year")
    assert dropped.removed_year == dropped.reference_removed_year == 2020
    assert dropped.reference_cnh_hit_rate == 0.9
    assert dropped.reference_cnh_loss_rate == 0.1
    assert dropped.reference_cnh_known_n == 10
    year = result[(result.cohort_id == "P-clean") & (result.row_kind == "year") & (result.year == 2020)].iloc[0]
    assert year.reference_cnh_hit_rate == 0.1


def test_common_feature_matched_not_unfiltered_and_exact_ten_pp_annotation() -> None:
    accumulator = RateAccumulator()
    for cohort, loss in (("P-clean", 3), ("C-nh", 2), ("C-52w", 1)):
        packet(accumulator, cohort, 2020, 10 - loss, loss, 0, kind="single", feature="D", bin_id="ge100", candidate="D=ge100")
        packet(accumulator, cohort, 2020, 0, 10, 0)
    result = attach_references(pd.DataFrame(accumulator.finalize()), ())
    row = target(result, "single", "single")
    assert row.reference_kind == "matched_condition"
    assert row.reference_cnh_loss_rate == 0.2
    assert row.reference_cnh_loss_delta == pytest.approx(0.1)
    assert row.reference_c52w_hit_delta == pytest.approx(-0.2)
    assert row.high_loss
    assert row.reference_pall_reason == "reference_not_required"


def test_pattern_single_and_mixed_candidate_use_three_unfiltered_references() -> None:
    accumulator = RateAccumulator()
    atoms = (Atom("B", "B", "lt05"), Atom("D", "D", "ge100"))
    candidate = Candidate(candidate_id(atoms), atoms, DevelopmentCounts(0, 0, 0, 0))
    packet(accumulator, "P-clean", 2020, 8, 2, 0, kind="single", feature="B", bin_id="lt05", candidate="B=lt05")
    packet(accumulator, "P-clean", 2020, 9, 1, 0, kind="candidate", candidate=candidate.candidate_id)
    for cohort, hit in (("C-nh", 3), ("C-52w", 4), ("P-all", 5)):
        packet(accumulator, cohort, 2020, hit, 10 - hit, 0)
    result = attach_references(pd.DataFrame(accumulator.finalize()), (candidate,))
    for kind in ("single", "candidate"):
        row = target(result, kind, kind)
        assert row.reference_kind == "pattern_only_unfiltered"
        assert row.reference_cnh_hit_rate == 0.3
        assert row.reference_c52w_hit_rate == 0.4
        assert row.reference_pall_hit_rate == 0.5


def test_zero_known_missing_year_and_not_applicable_preserve_null() -> None:
    accumulator = RateAccumulator()
    packet(accumulator, "P-clean", 2020, 1, 0, 0)
    packet(accumulator, "C-nh", 2020, 0, 0, 0)
    packet(accumulator, "C-52w", 2020, 1, 0, 0)
    packet(accumulator, "P-clean", 2020, 0, 0, 0, kind="single", feature="A", bin_id="lt10", outside=True)
    frame = pd.DataFrame(accumulator.finalize())
    frame.loc[frame.not_applicable_reason.notna(), ["hit_rate", "loss_rate"]] = None
    frame = cast(pd.DataFrame, frame[~((frame["cohort_id"] == "C-52w") & (frame["row_kind"] == "year") & (frame["year"] == 2022))])
    result = attach_references(frame, ())
    row = target(result)
    assert pd.isna(row.reference_cnh_hit_rate)
    assert row.reference_cnh_known_n == 0
    assert row.reference_cnh_reason == "zero_known_reference"
    dropped = target(result, span="drop_best_year")
    assert pd.isna(dropped.reference_c52w_hit_rate)
    assert dropped.reference_c52w_reason == "missing_reference_year"
    outside = target(result, "single", "single")
    assert pd.isna(outside.hit_rate) and pd.isna(outside.reference_cnh_hit_rate)
    assert outside.reference_cnh_reason == "target_not_applicable"
    assert not outside.high_loss


def test_duplicate_keys_raise_and_input_preserved() -> None:
    accumulator = RateAccumulator()
    packet(accumulator, "P-clean", 2020, 1, 0, 0)
    frame = pd.DataFrame(accumulator.finalize())
    original = frame.copy(deep=True)
    attach_references(frame, ())
    pd.testing.assert_frame_equal(frame, original)
    with pytest.raises(ValueError, match="duplicate summary"):
        attach_references(pd.concat([frame, frame]), ())
