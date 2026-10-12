"""Synthetic resolved-feature frames only, never published market artifacts."""

import json
from typing import Any, cast

import pandas as pd
import pytest

from research_core.hhhl_variants_features import FEATURES
from research_core.hhhl_variants_selection import Atom, Candidate, DevelopmentCounts, candidate_id
from research_core.hhhl_variants_summary import StudySummaries


def event(identifier: str, cohort: str = "P-clean", code: str = "0050", year: int = 2020, label: str = "hit", full: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = dict(
        event_id=identifier, code=code, year=year, label=label, calendar_full=full, cohort_id=cohort, split_id="development", horizon=126
    )
    for feature_id, definition in FEATURES.items():
        outside = definition.pattern_only and not cohort.startswith("P-") or definition.overhead_only and cohort != "P-over"
        result.update({
            f"{feature_id}_bin": None if outside else sorted(set(definition.bin_ids))[0],
            f"{feature_id}_status": "not_applicable" if outside else "known",
            f"{feature_id}_reason": "outside_feature_cohort" if outside else None,
        })
    return result


def fixed_candidate(*atoms: Atom) -> Candidate:
    return Candidate(candidate_id(atoms), tuple(atoms), DevelopmentCounts(0, 0, 0, 0))


def pooled(frame: pd.DataFrame, kind: str, cohort: str = "P-clean", feature: str | None = None, bin_id: str | None = None) -> pd.DataFrame:
    selected = cast(pd.DataFrame, frame[(frame["row_kind"] == kind) & (frame["cohort_id"] == cohort)])
    if feature is not None:
        selected = cast(pd.DataFrame, selected[selected["feature_id"] == feature])
    if bin_id is not None:
        selected = cast(pd.DataFrame, selected[selected["bin_id"] == bin_id])
    return selected


def test_two_cohorts_unknown_censored_and_all_empty_feature_cells() -> None:
    rows = [event("a"), event("b", label="unknown"), event("c", label="hit", full=False), event("d", "C-nh", label="loss")]
    rows[1].update(D_bin=None, D_status="feature_unknown", D_reason="warmup_insufficient")
    summaries = StudySummaries()
    summaries.add_observations(pd.DataFrame(rows))
    result = summaries.finalize()
    baseline = pooled(result, "baseline").iloc[0]
    assert baseline.known_n == baseline.hit_n == 1
    assert baseline.unknown_n == baseline.censored_hit_n == 1
    assert baseline.hit_rate == 1
    assert baseline.hit_lower == 0.5 and baseline.hit_upper == 1
    assert pooled(result, "baseline", "C-nh").iloc[0].loss_rate == 1
    missing_bin = pooled(result, "single", feature="D", bin_id="lt090").iloc[0]
    assert missing_bin.known_n == 0 and pd.isna(missing_bin.hit_rate)
    feature_unknown = pooled(result, "single", feature="D", bin_id="feature_unknown").iloc[0]
    assert json.loads(feature_unknown.reason_counts) == {"warmup_insufficient": 1}
    expected_cells = 1 + sum(len(set(feature.bin_ids)) + 2 for feature in FEATURES.values())
    assert len(result) == 2 * expected_cells * 10
    years = result[(result.base_row_kind == "baseline") & (result.row_kind == "year") & (result.cohort_id == "P-clean")]
    assert cast(pd.Series, years["year"]).tolist() == list(range(2019, 2027))


def test_fixed_intersection_pattern_control_not_applicable_and_k_distributions() -> None:
    pattern = fixed_candidate(Atom("B", "B", "lt05"), Atom("D", "D", "ge100"))
    rows = [event("a"), event("b", label="loss"), event("control", "C-nh")]
    rows[0].update(B_bin="lt05", D_bin="ge100", K_bin="lt03")
    rows[1].update(B_bin="ge20", D_bin="ge100", K_bin="ge05")
    summaries = StudySummaries()
    summaries.add_observations(pd.DataFrame(rows), (pattern,))
    result = summaries.finalize()
    candidate = pooled(result, "candidate").iloc[0]
    assert candidate.candidate_id == pattern.candidate_id
    assert candidate.hit_n == candidate.known_n == 1
    control = pooled(result, "candidate", "C-nh").iloc[0]
    assert control.known_n == control.calendar_full_n == 0
    assert control.not_applicable_n == 1
    assert pd.isna(control.hit_rate) and control.not_applicable_reason == "outside_feature_cohort"
    selected_k = pooled(result, "Kdistribution", feature="K", bin_id="lt03").iloc[0]
    assert selected_k.known_n == 1
    empty_k = pooled(result, "Kdistribution", feature="K", bin_id="ge05").iloc[0]
    assert empty_k.known_n == 0
    notapp_b = pooled(result, "single", "C-nh", "B", "not_applicable").iloc[0]
    assert notapp_b.known_n == 1 and pd.isna(notapp_b.hit_rate)


def test_incremental_stock_union_diagnostics_and_no_source_mutation() -> None:
    first = event("a", year=2020)
    second = event("b", year=2021, label="loss")
    third = event("c", code="1234", year=2021, label="hit")
    first.update(hit_then_below_anchor=True, hit_endpoint_unknown=False, drawdown10_full_state="triggered")
    second.update(hit_then_below_anchor=False, hit_endpoint_unknown=False, drawdown10_full_state="all_false")
    third.update(hit_then_below_anchor=False, hit_endpoint_unknown=True, drawdown10_full_state="unknown")
    frame = pd.DataFrame([first, second, third])
    original = frame.copy(deep=True)
    summaries = StudySummaries()
    summaries.add_observations(frame.iloc[:1])
    summaries.add_observations(frame.iloc[1:])
    result = summaries.finalize()
    baseline = pooled(result, "baseline").iloc[0]
    assert baseline.known_security_n == 2 and baseline.known_n == 3
    assert baseline.hit_then_below_anchor_n == baseline.hit_endpoint_unknown_n == 1
    assert baseline.drawdown10_full_triggered_n == baseline.drawdown10_full_all_false_n == baseline.drawdown10_full_unknown_n == 1
    dropped = result[(result.base_row_kind == "baseline") & (result.row_kind == "drop_best_year")].iloc[0]
    assert dropped.removed_year == 2020  # One hit in each year: earliest tie.
    assert dropped.known_security_n == 2
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize(
    "name,value",
    [
        ("cohort_id", "other"),
        ("split_id", "other"),
        ("horizon", 63),
        ("label", "other"),
        ("year", 2018),
        ("calendar_full", 1),
        ("D_status", "unknown"),
        ("D_bin", "wrong"),
    ],
)
def test_invalid_keys_status_and_bins_raise(name: str, value: object) -> None:
    row = event("a")
    row[name] = value
    with pytest.raises(ValueError):
        StudySummaries().add_observations(pd.DataFrame([row]))


def test_missing_column_duplicate_and_censored_known_loss_rejected() -> None:
    with pytest.raises(ValueError, match="missing"):
        StudySummaries().add_observations(pd.DataFrame([event("a")]).drop(columns="D_reason"))
    with pytest.raises(ValueError, match="duplicate"):
        StudySummaries().add_observations(pd.DataFrame([event("a"), event("a")]))
    with pytest.raises(ValueError, match="censored"):
        StudySummaries().add_observations(pd.DataFrame([event("a", label="loss", full=False)]))


def test_k_atoms_forbidden_and_candidates_must_remain_fixed() -> None:
    row = pd.DataFrame([event("a")])
    with pytest.raises(ValueError, match="diagnostic"):
        StudySummaries().add_observations(row, (fixed_candidate(Atom("K", "K", "lt03", False)),))
    summaries = StudySummaries()
    summaries.add_observations(row, (fixed_candidate(Atom("D", "D", "ge100")),))
    with pytest.raises(ValueError, match="inventory changed"):
        summaries.add_observations(row, (fixed_candidate(Atom("D", "D", "lt090")),))


def test_explicit_empty_group_registers_all_fixed_cells() -> None:
    candidate = fixed_candidate(Atom("D", "D", "ge100"))
    summaries = StudySummaries()
    summaries.initialize_group("C-52w", "cross-check", 252, (candidate,))
    result = summaries.finalize()
    assert (result.known_n == 0).all()
    assert result.hit_rate.isna().all()
    assert len(result[result.row_kind == "candidate"]) == 1
    assert len(result[result.row_kind == "Kdistribution"]) == 16
    # A later nonempty batch updates the pre-existing cells rather than copying them.
    row = event("a", "C-52w")
    row.update(split_id="cross-check", horizon=252, D_bin="ge100")
    summaries.add_observations(pd.DataFrame([row]), (candidate,))
    updated = summaries.finalize()
    assert len(result) == len(updated)
    assert pooled(updated, "baseline", "C-52w").iloc[0].known_n == 1


def test_compact_categorical_fields_match_plain_frame_and_missing_code_rejected() -> None:
    plain = pd.DataFrame([event("a"), event("b", "C-nh", label="unknown", full=False)])
    compact = plain.copy()
    categorical_columns = ["code", "cohort_id", "split_id", "event_id", "label", "calendar_full", "horizon", "year"]
    categorical_columns.extend(f"{feature_id}_{suffix}" for feature_id in FEATURES for suffix in ("bin", "status"))
    for name in categorical_columns:
        compact[name] = compact[name].astype("category")
    regular_summaries = StudySummaries()
    regular_summaries.add_observations(plain)
    categorical_summaries = StudySummaries()
    categorical_summaries.add_observations(compact)
    pd.testing.assert_frame_equal(categorical_summaries.finalize(), regular_summaries.finalize())
    compact.loc[0, "code"] = None
    with pytest.raises(ValueError, match="invalid original string code"):
        StudySummaries().add_observations(compact)


def test_pall_overhead_a_keeps_over_subset_in_bins_and_candidate_denominators() -> None:
    candidate = fixed_candidate(Atom("A", "A", "lt10"), Atom("D", "D", "ge100"))
    clean = event("clean", "P-clean", label="loss")
    over_hit = event("over-hit", "P-over", code="1234")
    over_loss = event("over-loss", "P-over", code="5678", label="loss")
    over_hit.update(A_bin="lt10", D_bin="ge100")
    over_loss.update(A_bin="ge40", D_bin="ge100")
    original_rows = [clean, over_hit, over_loss]
    # P-all relabels the original union; it preserves each event's A status.
    union_rows = [dict(row, cohort_id="P-all") for row in original_rows]
    summaries = StudySummaries()
    summaries.initialize_group("P-all", "development", 126, (candidate,))
    summaries.add_observations(pd.DataFrame(original_rows + union_rows), (candidate,))
    result = summaries.finalize()
    assert pooled(result, "baseline", "P-all").iloc[0].known_n == 3
    bin_row = pooled(result, "single", "P-all", "A", "lt10").iloc[0]
    assert bin_row.known_n == bin_row.hit_n == 1
    assert bin_row.hit_rate == 1
    assert bin_row.not_applicable_reason is None
    absent_row = pooled(result, "single", "P-all", "A", "not_applicable").iloc[0]
    assert absent_row.not_applicable_n == absent_row.known_n == 1
    assert pd.isna(absent_row.hit_rate)
    union_candidate = pooled(result, "candidate", "P-all").iloc[0]
    over_candidate = pooled(result, "candidate", "P-over").iloc[0]
    assert union_candidate.known_n == over_candidate.known_n == 1
    assert union_candidate.hit_rate == over_candidate.hit_rate == 1
    assert union_candidate.not_applicable_reason is None
    clean_candidate = pooled(result, "candidate", "P-clean").iloc[0]
    assert clean_candidate.known_n == 0 and clean_candidate.not_applicable_n == 1
    assert pd.isna(clean_candidate.hit_rate)


def test_full_and_before_hit_diagnostics_have_independent_known_denominators() -> None:
    after_hit_drop = event("after-drop", year=2020)
    hit_then_missing = event("after-missing", year=2021)
    loss_before_drop = event("loss-drop", year=2021, label="loss")
    censored_drop = event("censored", year=2021, full=False)
    after_hit_drop.update(drawdown10_full_state="triggered", drawdown20_full_state="all_false", before_hit10_state="all_false", before_hit20_state="all_false")
    hit_then_missing.update(drawdown10_full_state="unknown", drawdown20_full_state="unknown", before_hit10_state="all_false", before_hit20_state="all_false")
    loss_before_drop.update(
        drawdown10_full_state="triggered", drawdown20_full_state="all_false", before_hit10_state="triggered", before_hit20_state="all_false"
    )
    censored_drop.update(drawdown10_full_state="triggered", drawdown20_full_state="triggered", before_hit10_state="triggered", before_hit20_state="triggered")
    summaries = StudySummaries()
    summaries.add_observations(pd.DataFrame([after_hit_drop, hit_then_missing, loss_before_drop, censored_drop]))
    result = summaries.finalize()
    baseline = pooled(result, "baseline").iloc[0]
    assert baseline["calendar_full_n"] == 3 and baseline["censored_n"] == 1
    assert baseline["drawdown10_full_triggered_n"] == 2
    assert baseline["drawdown10_full_unknown_n"] == 1
    assert baseline["drawdown10_full_known_n"] == 2
    assert baseline["drawdown10_full_rate"] == 1
    assert baseline["drawdown10_full_lower"] == pytest.approx(2 / 3)
    assert baseline["drawdown10_full_upper"] == 1
    assert baseline["before_hit10_triggered_n"] == 1
    assert baseline["before_hit10_known_n"] == 3
    assert baseline["before_hit10_rate"] == pytest.approx(1 / 3)
    assert baseline["before_hit10_lower"] == baseline["before_hit10_upper"] == pytest.approx(1 / 3)
    assert baseline["drawdown20_full_known_n"] == 2 and baseline["drawdown20_full_rate"] == 0
    assert baseline["drawdown20_full_upper"] == pytest.approx(1 / 3)
    assert baseline["before_hit20_known_n"] == 3 and baseline["before_hit20_rate"] == 0
    empty = result[(result["base_row_kind"] == "baseline") & (result["row_kind"] == "year") & (result["year"] == 2019)].iloc[0]
    assert pd.isna(empty["before_hit10_rate"]) and pd.isna(empty["drawdown20_full_lower"])
    dropped = result[(result["base_row_kind"] == "baseline") & (result["row_kind"] == "drop_best_year")].iloc[0]
    assert dropped["removed_year"] == 2020
    assert dropped["before_hit10_rate"] == 0.5
    assert dropped["drawdown10_full_rate"] == 1


def test_omitted_optional_path_diagnostic_is_unknown_not_false() -> None:
    summaries = StudySummaries()
    summaries.add_observations(pd.DataFrame([event("a")]))
    baseline = pooled(summaries.finalize(), "baseline").iloc[0]
    assert baseline["before_hit10_unknown_n"] == 1
    assert baseline["before_hit10_known_n"] == baseline["before_hit10_all_false_n"] == 0
    assert pd.isna(baseline["before_hit10_rate"])
    assert baseline["before_hit10_lower"] == 0 and baseline["before_hit10_upper"] == 1


def test_outcome_unknown_reasons_separate_from_feature_reasons_and_slice_by_year() -> None:
    candidate = fixed_candidate(Atom("D", "D", "090to100"))
    rows = [
        event("hit", year=2020),
        event("invalid", year=2020, label="unknown"),
        event("missing", year=2021, label="unknown"),
        event("censored", year=2021, label="unknown", full=False),
    ]
    for row, reason in zip(rows, (None, "invalid_anchor", "missing_before_hit", "censored_window"), strict=True):
        row["unknown_reason"] = reason
    summaries = StudySummaries()
    summaries.add_observations(pd.DataFrame(rows), (candidate,))
    result = summaries.finalize()
    for kind in ("baseline", "candidate"):
        base = pooled(result, kind).iloc[0]
        assert json.loads(base["outcome_reason_counts"]) == {"invalid_anchor": 1, "missing_before_hit": 1, "censored_window": 1}
        assert json.loads(base["reason_counts"]) == {}
        assert base["known_n"] == 1 and base["unknown_n"] == 2 and base["censored_unknown_n"] == 1
        dropped = result[(result["base_row_kind"] == kind) & (result["row_kind"] == "drop_best_year")].iloc[0]
        assert dropped["removed_year"] == 2020
        assert json.loads(dropped["outcome_reason_counts"]) == {"missing_before_hit": 1, "censored_window": 1}
