"""Bounded membership expansion retains complete integer stock populations."""

from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core import pattern_scan_membership_v1 as membership
from research_core.artifact_store import object_digest
from research_core.hhhl_variants_selection import Atom
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
    original = membership._stock_memberships

    def bounded(frame: pd.DataFrame, registry: pd.DataFrame, compiled_candidates: Any, **kwargs: Any) -> pd.DataFrame:
        observed_batches.append(len(frame))
        assert len(frame) <= 3
        return original(frame, registry, compiled_candidates, **kwargs)

    for code, size in (("TW:0001", 23), ("TW:0020", 11)):
        source = _frame(code, size, mixed=True)
        untouched = source.copy(deep=True)
        unbatched = aggregate_memberships(source, membership.stock_memberships(source, inventory))
        with monkeypatch.context() as patch:
            patch.setattr(membership, "_stock_memberships", bounded)
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

    monkeypatch.setattr(membership, "_stock_memberships", forbidden)
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
    original_memberships = membership._stock_memberships
    registry_calls, candidate_calls, batch_registries = [], [], []

    def registry(rows: Any) -> pd.DataFrame:
        compiled = original_registry(rows)
        registry_calls.append(compiled)
        return compiled

    def candidates(compiled: pd.DataFrame) -> Any:
        candidate_calls.append(compiled)
        return original_candidates(compiled)

    def members(frame: pd.DataFrame, compiled: pd.DataFrame, definitions: Any, **kwargs: Any) -> pd.DataFrame:
        assert len(frame) <= 2
        batch_registries.append(compiled)
        return original_memberships(frame, compiled, definitions, **kwargs)

    monkeypatch.setattr(membership, "_registry", registry)
    monkeypatch.setattr(membership, "_candidates", candidates)
    monkeypatch.setattr(membership, "_stock_memberships", members)
    cap = 2 * 8 * (1 + len(FEATURES) + 2)
    plan = membership.StockCountPlan(inventory, max_membership_rows=cap)
    assert len(registry_calls) == len(candidate_calls) == 1
    for source, matrix in zip(sources, expected, strict=True):
        pd.testing.assert_frame_equal(plan.matrix(source), matrix, check_exact=True)
    pd.testing.assert_frame_equal(plan.matrix(sources[0]), expected[0], check_exact=True)
    assert len(registry_calls) == len(candidate_calls) == 1
    assert len(batch_registries) > len(sources)
    assert all(compiled is registry_calls[0] for compiled in batch_registries)
    other_plan = membership.StockCountPlan(other_inventory, max_membership_rows=2 * 8 * (1 + len(FEATURES) + 1))
    assert len(registry_calls) == len(candidate_calls) == 2
    pd.testing.assert_frame_equal(other_plan.matrix(sources[0]), other_expected, check_exact=True)
    assert batch_registries[-1] is registry_calls[1]
    # Processing a different candidate registry cannot mutate the first plan.
    pd.testing.assert_frame_equal(plan.matrix(sources[1]), expected[1], check_exact=True)
    assert batch_registries[-1] is registry_calls[0]
    assert len(registry_calls) == len(candidate_calls) == 2


def test_4110_events_with_92_candidates_keep_allocation_bounded_and_one_complete_stock_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _frame("TW:0001", 4110, mixed=False)
    candidates = _candidates(92)
    inventory = membership.membership_inventory(BASE, candidates)
    identifiers = tuple(object_digest(row) for row in inventory)
    limit = 2_000_000
    with pytest.raises(ValueError, match="allocation bound"):
        membership.stock_memberships(source, inventory, max_membership_rows=limit)
    original = membership._stock_memberships
    observed = []

    def bounded(frame: pd.DataFrame, registry: pd.DataFrame, compiled_candidates: Any, **kwargs: Any) -> pd.DataFrame:
        bound = len(frame) * 8 * (1 + len(FEATURES) + len(candidates))
        assert kwargs["max_membership_rows"] == limit and bound <= limit
        members = original(frame, registry, compiled_candidates, **kwargs)
        assert len(members) <= limit
        observed.append((len(frame), len(members)))
        return members

    monkeypatch.setattr(membership, "_stock_memberships", bounded)
    matrix = membership.stock_count_matrix(source, inventory, max_membership_rows=limit)
    assert len(observed) > 1 and sum(size for size, _ in observed) == 4110
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
