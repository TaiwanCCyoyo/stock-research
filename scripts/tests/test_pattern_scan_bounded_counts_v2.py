"""Bounded membership expansion retains complete integer stock populations."""

from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core import pattern_scan_membership_v1 as membership
from research_core.artifact_store import object_digest
from research_core.hhhl_variants_selection import Atom, split_for_code
from research_core.pattern_scan_conditions_v1 import FEATURES
from research_core.pattern_scan_count_matrix_v1 import GROUP_COLUMNS, aggregate_memberships
from research_core.pattern_scan_dense_counts_v1 import DenseCounts
from research_core.pattern_scan_summary_store_v1 import COUNT_FIELDS

BASE = {"pattern_id": "B1", "control_id": "pattern", "cohort_id": "union", "horizon": 126}


def _frame(code: str, size: int, *, mixed: bool) -> pd.DataFrame:
    frame = pd.DataFrame({
        "event_id": [f"{code}:{index}" for index in range(size)],
        "security_id": code,
        "t0": [f"{2010 + index % 17}-01-04" for index in range(size)],
        "horizon": 126,
        "mkt": ["up" if index % 2 else "unknown" for index in range(size)],
        "effective_label": ["hit", "loss", "unknown", "flat-win", "hit", "unknown", "loss"] * (size // 7) + ["hit"] * (size % 7),
        "calendar_full": True,
        "event_main_eligible": True,
        "event_eligibility_excluded": False,
    })
    if mixed:
        frame.loc[frame.effective_label.eq("unknown"), "event_main_eligible"] = False
        frame.loc[np.arange(size) % 5 == 0, ["calendar_full", "event_main_eligible"]] = False
        frame.loc[np.arange(size) % 7 == 1, ["event_eligibility_excluded", "event_main_eligible"]] = [True, False]
    else:
        frame["effective_label"] = "hit"
    feature_columns = {
        column: value
        for feature, definition in FEATURES.items()
        for column, value in ((f"{feature}_bin", definition.bin_ids[0]), (f"{feature}_status", "known"))
    }
    frame = pd.concat([frame, pd.DataFrame(feature_columns, index=frame.index)], axis=1)
    if mixed:
        frame.loc[np.arange(size) % 3 == 1, ["MA_a_bin", "MA_a_status"]] = [None, "feature_unknown"]
        frame.loc[np.arange(size) % 3 == 2, ["MA_a_bin", "MA_a_status"]] = [None, "not_applicable"]
    return frame


def _candidates(size: int) -> dict[str, tuple[Atom, ...]]:
    by_family: dict[str, Atom] = {}
    for feature, definition in FEATURES.items():
        if not definition.diagnostic_only:
            by_family.setdefault(definition.family, Atom(definition.family, feature, definition.bin_ids[0]))
    atoms = tuple(by_family.values())[:8]
    conjunctions = [group for arity in (1, 2, 3) for group in combinations(atoms, arity)]
    assert len(conjunctions) >= size
    return {f"synthetic-{index:03}": group for index, group in enumerate(conjunctions[:size])}


def test_batched_integer_matrix_and_all_dense_summaries_match_unbatched_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = {"synthetic": (Atom(FEATURES["MA_a"].family, "MA_a", FEATURES["MA_a"].bin_ids[0]),)}
    inventory = membership.membership_inventory(BASE, candidates)
    identifiers = tuple(object_digest(row) for row in inventory)
    expected, actual = DenseCounts(identifiers, 126), DenseCounts(identifiers, 126)
    rows_per_event = 8 * (1 + len(FEATURES) + len(candidates))
    observed_batches = []
    original = np.bincount
    original_counts = membership._bounded_condition_counts

    def bounded(values: Any, **kwargs: Any) -> Any:
        observed_batches.append(len(values))
        assert len(values) <= 3 and "weights" not in kwargs
        return original(values, **kwargs)

    def count_with_guard(*args: Any, **kwargs: Any) -> Any:
        with monkeypatch.context() as patch:
            patch.setattr(np, "bincount", bounded)
            return original_counts(*args, **kwargs)

    monkeypatch.setattr(membership, "_bounded_condition_counts", count_with_guard)

    for code, size in (("TW:0001", 23), ("TW:0020", 11)):
        source = _frame(code, size, mixed=True)
        untouched = source.copy(deep=True)
        unbatched = aggregate_memberships(source, membership.stock_memberships(source, inventory))
        matrix = membership.stock_count_matrix(source, inventory, max_membership_rows=3 * rows_per_event)
        pd.testing.assert_frame_equal(matrix, unbatched, check_exact=True, check_dtype=True)
        pd.testing.assert_frame_equal(source, untouched)
        expected.add_stock(unbatched)
        actual.add_stock(matrix)
    assert len(observed_batches) > 2
    assert tuple(matrix.columns) == (*GROUP_COLUMNS, *COUNT_FIELDS)
    assert all(matrix[column].dtype == np.dtype("int64") for column in (*COUNT_FIELDS, "year", "horizon"))
    # Observed cells include unknown/N/A candidate states; include one zero cell too.
    check_cells = set(matrix.cell_id) | {identifiers[-1]}
    for cell in check_cells:
        assert actual.summarize(cell) == expected.summarize(cell)
        assert actual.annual_summary(cell) == expected.annual_summary(cell)
        assert actual.drop_best_year(cell) == expected.drop_best_year(cell)
    unconditional = next(
        object_digest(row) for row in inventory if row["feature_id"] == "unconditional" and (row["split"], row["era"], row["mkt"]) == ("all", "all", "all")
    )
    summary = actual.summarize(unconditional)
    assert summary["distinct_stock_n"] == 2
    assert summary["per_stock_event_count_median"] == 17.0
    assert summary["per_stock_event_count_max"] == 23
    unknown_n, censored_n = summary["unknown_n"], summary["censored_n"]
    assert unknown_n is not None and censored_n is not None
    assert unknown_n > 0 and censored_n > 0


@pytest.mark.parametrize("invalid", ["duplicate", "stock", "horizon", "inventory_horizon", "date", "market", "limit"])
def test_whole_stock_validation_precedes_any_batch(invalid: str, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _frame("TW:0001", 8, mixed=True)
    inventory = membership.membership_inventory(BASE)
    limit = 8 * (1 + len(FEATURES))
    if invalid == "duplicate":
        source.loc[7, "event_id"] = source.loc[0, "event_id"]
    elif invalid == "stock":
        source.loc[7, "security_id"] = "TW:0020"
    elif invalid == "horizon":
        source.loc[7, "horizon"] = 252
    elif invalid == "inventory_horizon":
        source["horizon"] = 252
    elif invalid == "date":
        source.loc[7, "t0"] = "2009-01-04"
    elif invalid == "market":
        source.loc[7, "mkt"] = "unsupported"
    else:
        limit = 0

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("invalid complete stock must fail before any batch")

    monkeypatch.setattr(membership, "_bounded_condition_counts", forbidden)
    with pytest.raises(ValueError):
        membership.stock_count_matrix(source, inventory, max_membership_rows=limit)


def test_empty_matrix_schema_and_too_small_allocation_guard() -> None:
    source = _frame("TW:0001", 1, mixed=False)
    inventory = membership.membership_inventory(BASE)
    empty = source.iloc[:0]
    pd.testing.assert_frame_equal(
        membership.stock_count_matrix(empty, inventory, max_membership_rows=1),
        aggregate_memberships(empty, membership.stock_memberships(empty, inventory)),
    )
    with pytest.raises(ValueError, match="one event"):
        membership.stock_count_matrix(source, inventory, max_membership_rows=1)


def test_reused_plan_compiles_once_for_multiple_stocks_and_batches_without_state_leaks(monkeypatch: pytest.MonkeyPatch) -> None:
    inventory = membership.membership_inventory(BASE, _candidates(2))
    other_inventory = membership.membership_inventory(BASE, _candidates(1))
    sources = [_frame("TW:0001", 7, mixed=True), _frame("TW:0020", 5, mixed=True)]
    expected = [aggregate_memberships(source, membership.stock_memberships(source, inventory)) for source in sources]
    other_expected = aggregate_memberships(sources[0], membership.stock_memberships(sources[0], other_inventory))
    original_registry, original_candidates = membership._registry, membership._candidates
    registry_calls, candidate_calls = [], []

    def registry(rows: Any) -> pd.DataFrame:
        compiled = original_registry(rows)
        registry_calls.append(compiled)
        return compiled

    def candidates(compiled: pd.DataFrame) -> Any:
        candidate_calls.append(compiled)
        return original_candidates(compiled)

    monkeypatch.setattr(membership, "_registry", registry)
    monkeypatch.setattr(membership, "_candidates", candidates)
    cap = 2 * 8 * (1 + len(FEATURES) + 2)
    plan = membership.StockCountPlan(inventory, max_membership_rows=cap)
    assert len(registry_calls) == len(candidate_calls) == 1
    for source, matrix in zip(sources, expected, strict=True):
        pd.testing.assert_frame_equal(plan.matrix(source), matrix, check_exact=True)
    pd.testing.assert_frame_equal(plan.matrix(sources[0]), expected[0], check_exact=True)
    assert len(registry_calls) == len(candidate_calls) == 1
    other_plan = membership.StockCountPlan(other_inventory, max_membership_rows=2 * 8 * (1 + len(FEATURES) + 1))
    assert len(registry_calls) == len(candidate_calls) == 2
    pd.testing.assert_frame_equal(other_plan.matrix(sources[0]), other_expected, check_exact=True)
    # Processing a different candidate registry cannot mutate the first plan.
    pd.testing.assert_frame_equal(plan.matrix(sources[1]), expected[1], check_exact=True)
    assert len(registry_calls) == len(candidate_calls) == 2


def test_4110_events_with_92_candidates_keep_allocation_bounded_and_one_complete_stock_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _frame("TW:0001", 4110, mixed=False)
    candidates = _candidates(92)
    inventory = membership.membership_inventory(BASE, candidates)
    identifiers = tuple(object_digest(row) for row in inventory)
    limit = 2_000_000
    with pytest.raises(ValueError, match="allocation bound"):
        membership.stock_memberships(source, inventory, max_membership_rows=limit)
    original = np.bincount
    original_counts = membership._bounded_condition_counts
    observed = []
    batch_size = limit // (8 * (1 + len(FEATURES) + len(candidates)))

    def bounded(values: Any, **kwargs: Any) -> Any:
        assert len(values) <= batch_size and "weights" not in kwargs
        observed.append(len(values))
        return original(values, **kwargs)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("matrix must not allocate legacy event/cell expansions")

    def count_with_guard(*args: Any, **kwargs: Any) -> Any:
        with monkeypatch.context() as patch:
            patch.setattr(np, "bincount", bounded)
            return original_counts(*args, **kwargs)

    monkeypatch.setattr(membership, "_bounded_condition_counts", count_with_guard)
    monkeypatch.setattr(membership, "_stock_memberships", forbidden)
    matrix = membership.stock_count_matrix(source, inventory, max_membership_rows=limit)
    assert observed and max(observed) == batch_size
    assert not matrix.duplicated(list(GROUP_COLUMNS)).any()
    dense = DenseCounts(identifiers, 126)
    dense.add_stock(matrix)
    for row in inventory:
        if row["feature_id"] == "candidate" and row["condition_status"] == "known" and (row["split"], row["era"], row["mkt"]) == ("all", "all", "all"):
            summary = dense.summarize(object_digest(row))
            assert summary["event_n"] == summary["hit_n"] == 4110
            assert summary["distinct_stock_n"] == 1
            assert summary["per_stock_event_count_median"] == 4110.0
    with pytest.raises(ValueError, match="duplicate complete stock feed"):
        dense.add_stock(matrix)


@pytest.mark.parametrize("code", ["0050", "TW0050", "TW:0050"])
@pytest.mark.parametrize("selection", ["all", "feature", "restricted_candidate"])
def test_integer_lookup_matches_legacy_oracle_for_prefixes_and_subset_registries(code: str, selection: str) -> None:
    source = _frame(code, 35, mixed=True)
    source["mkt"] = ["up", "down", "consolidation", "mixed", "unknown"] * 7
    source["MACD_bin"] = "true"
    # N/A dominates false; false dominates unknown. Missing feature bins are ignored.
    source.loc[0, ["MA_a_bin", "MA_a_status", "MACD_bin"]] = ["ignored", "not_applicable", "false"]
    source.loc[1, ["MA_a_bin", "MA_a_status", "MACD_bin", "MACD_status"]] = ["ge15", "known", None, "feature_unknown"]
    source.loc[2, ["MA_a_bin", "MA_a_status", "MACD_bin", "MACD_status"]] = [None, "feature_unknown", "true", "known"]
    candidates = {"joint": (Atom("MA", "MA_a", "lt0"), Atom("IND", "MACD", "true"))}
    inventory = membership.membership_inventory(BASE, candidates)
    if selection == "feature":
        inventory = tuple(row for row in inventory if row["feature_id"] == "MA_a")
    elif selection == "restricted_candidate":
        inventory = tuple(row for row in inventory if row["feature_id"] == "candidate" and row["split"] == "cross-check" and row["era"] == "all")
    original = source.copy(deep=True)
    expected = aggregate_memberships(source, membership.stock_memberships(source, inventory))
    plan = membership.StockCountPlan(inventory, max_membership_rows=8 * (1 + len(FEATURES) + len(candidates)))
    pd.testing.assert_frame_equal(plan.matrix(source), expected, check_exact=True)
    # Absent exclusion columns must retain the oracle's inference, not become false.
    inferred = source.drop(columns="event_eligibility_excluded")
    inferred_expected = aggregate_memberships(inferred, membership.stock_memberships(inferred, inventory))
    pd.testing.assert_frame_equal(plan.matrix(inferred), inferred_expected, check_exact=True)
    pd.testing.assert_frame_equal(source, original)


@pytest.mark.parametrize("split", ["development", "cross-check"])
def test_cross_check_candidate_registry_preserves_empty_matrix_schema(split: str) -> None:
    code = next(f"{number:04}" for number in range(100) if split_for_code(f"{number:04}") == split)
    source = _frame(code, 7, mixed=True)
    inventory = tuple(
        row
        for row in membership.membership_inventory(BASE, {"one": (Atom("MA", "MA_a", "lt0"),)})
        if row["feature_id"] == "candidate" and row["split"] == "cross-check"
    )
    expected = aggregate_memberships(source, membership.stock_memberships(source, inventory))
    actual = membership.StockCountPlan(inventory, max_membership_rows=8).matrix(source)
    assert actual.empty == (split == "development")
    pd.testing.assert_frame_equal(actual, expected, check_exact=True, check_dtype=True)


@pytest.mark.parametrize("invalid", ["bin", "status", "schema", "label", "eligible", "excluded", "event_id", "missing_facet", "candidate_schema"])
def test_integer_matrix_preserves_legacy_input_rejections(invalid: str) -> None:
    source = _frame("TW:0001", 7, mixed=True)
    inventory = membership.membership_inventory(BASE, {"one": (Atom("MA", "MA_a", "lt0"),)})
    if invalid == "bin":
        source.loc[0, "MA_a_bin"] = "invalid"
    elif invalid == "status":
        source.loc[0, "MA_a_status"] = "invalid"
    elif invalid == "schema":
        source = source.drop(columns="MA_a_bin")
    elif invalid == "label":
        source.loc[0, "effective_label"] = "invalid"
    elif invalid == "eligible":
        source.loc[0, "event_main_eligible"] = True  # This event is censored.
    elif invalid == "excluded":
        source["event_eligibility_excluded"] = 1
    elif invalid == "event_id":
        source.loc[0, "event_id"] = " "
    elif invalid == "missing_facet":
        inventory = tuple(row for row in inventory if row["split"] != "all")
    else:
        inventory = tuple(row for row in inventory if row["feature_id"] == "candidate")
        source = source.drop(columns="MA_a_status")
    with pytest.raises(ValueError):
        aggregate_memberships(source, membership.stock_memberships(source, inventory))
    with pytest.raises(ValueError):
        membership.StockCountPlan(inventory).matrix(source)
