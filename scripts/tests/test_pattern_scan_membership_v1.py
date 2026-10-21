"""Fixed zero registry, eight-facet assignments and candidate coverage cases."""

from typing import Any, cast

import pandas as pd
import pytest

from research_core.artifact_store import object_digest
from research_core.hhhl_variants_selection import Atom, split_for_code
from research_core.pattern_scan_conditions_v1 import FEATURES
from research_core.pattern_scan_membership_v1 import StockCountPlan, candidate_coverage, membership_inventory, stock_memberships
from research_core.pattern_scan_reporting_v1 import candidate_membership, facet_masks

BASE = {"pattern_id": "B1", "control_id": "pattern", "cohort_id": "union", "horizon": 126}
ATOMS = (Atom("MA", "MA_a", "lt0"), Atom("IND", "MACD", "true"))


def frame() -> pd.DataFrame:
    result = pd.DataFrame({
        "event_id": ["a", "b", "c", "d"],
        "security_id": "TW:0050",
        "t0": ["2010-01-04", "2013-01-04", "2019-01-04", "2026-01-04"],
        "horizon": 126,
        "mkt": ["up", "unknown", "mixed", "consolidation"],
    })
    for feature, definition in FEATURES.items():
        result[f"{feature}_bin"] = definition.bin_ids[0]
        result[f"{feature}_status"] = "known"
    result["PAT_other_B1_status"] = "not_applicable"
    result["PAT_other_B1_bin"] = None
    result.loc[1, ["MA_a_bin", "MA_a_status"]] = [None, "feature_unknown"]
    result.loc[2, ["MA_a_bin", "MA_a_status"]] = [None, "not_applicable"]
    result.loc[3, "MA_a_bin"] = "ge15"
    return result


def test_inventory_has_zero_bins_missing_strata_and_diagnostics() -> None:
    inventory = membership_inventory(BASE)
    triples = {(row["feature_id"], row["bin_id"], row["condition_status"]) for row in inventory}
    assert ("unconditional", "all", "known") in triples
    for feature, definition in FEATURES.items():
        for bin_id in definition.bin_ids:
            assert (feature, bin_id, "known") in triples
        assert (feature, "feature_unknown", "feature_unknown") in triples
        assert (feature, "not_applicable", "not_applicable") in triples
    assert any(row["feature_id"] == "K" for row in inventory)
    assert len(inventory) == len(triples) * 72
    assert len({object_digest(row) for row in inventory}) == len(inventory)


def test_each_condition_matches_eight_public_facets_and_correct_raw_code_split() -> None:
    source = frame()
    original = source.copy(deep=True)
    inventory = membership_inventory(BASE)
    members = stock_memberships(source, inventory)
    registry = {object_digest(row): row for row in inventory}
    assert len(members) == len(source) * 8 * (len(FEATURES) + 1)
    unconditional = members.loc[members.cell_id.map(lambda cell: registry[cell]["feature_id"] == "unconditional")]
    expected: set[tuple[str, str, str, str]] = set()
    for facets, mask in facet_masks(source):
        for event in source.event_id.loc[mask]:
            expected.add((event, facets["split"], facets["era"], facets["mkt"]))
    observed = {
        (row.event_id, registry[row.cell_id]["split"], registry[row.cell_id]["era"], registry[row.cell_id]["mkt"])
        for row in unconditional.itertuples(index=False)
    }
    assert observed == expected
    for row in unconditional.itertuples(index=False):
        assert registry[row.cell_id]["split"] in {"all", split_for_code("0050")}
    own_pat = members.loc[members.cell_id.map(lambda cell: registry[cell]["feature_id"] == "PAT_other_B1")]
    assert all(registry[cell]["condition_status"] == "not_applicable" for cell in own_pat.cell_id)
    pd.testing.assert_frame_equal(source, original)


def test_unknown_not_zero_and_unused_cells_remain_registered() -> None:
    source = frame()
    inventory = membership_inventory(BASE)
    members = stock_memberships(source, inventory)
    cells = {object_digest(row): row for row in inventory}
    unknown = members.loc[members.event_id.eq("b")]
    ma = [cells[cell] for cell in unknown.cell_id if cells[cell]["feature_id"] == "MA_a"]
    assert len(ma) == 8 and all(row["condition_status"] == "feature_unknown" for row in ma)
    unused = [object_digest(row) for row in inventory if row["feature_id"] == "MA_a" and row["bin_id"] == "05to15"]
    assert unused and not members.cell_id.isin(unused).any()


def test_candidate_true_only_and_separate_false_unknown_na_coverage() -> None:
    source = frame()
    source["MACD_bin"] = "true"
    source.loc[3, ["MACD_bin", "MACD_status"]] = [None, "feature_unknown"]
    inventory = membership_inventory(BASE, {"candidate-1": ATOMS})
    coverage = candidate_coverage(source, inventory)
    assert coverage.membership_state.tolist() == [1, -1, -2, 0]  # False absorbs unknown; N/A dominates.
    assert coverage.membership_state.tolist() == candidate_membership(source, ATOMS).tolist()
    members = stock_memberships(source, inventory)
    registry = {object_digest(row): row for row in inventory}
    candidate_rows = members.loc[members.cell_id.map(lambda cell: registry[cell]["feature_id"] == "candidate")]
    assert candidate_rows.groupby("event_id").size().to_dict() == {"a": 8, "b": 8, "c": 8}
    assert {registry[cell]["condition_status"] for cell in candidate_rows.loc[candidate_rows.event_id.eq("a"), "cell_id"]} == {"known"}
    assert {registry[cell]["condition_status"] for cell in candidate_rows.loc[candidate_rows.event_id.eq("b"), "cell_id"]} == {"feature_unknown"}


def test_empty_batches_keep_fixed_registry_and_empty_membership_schema() -> None:
    source = frame().iloc[:0]
    inventory = membership_inventory(BASE, {"candidate-1": ATOMS})
    members = stock_memberships(source, inventory)
    assert members.empty and members.columns.tolist() == ["event_id", "cell_id"]
    coverage = candidate_coverage(source, inventory)
    assert coverage.empty and coverage.columns.tolist() == ["event_id", "candidate_id", "membership_state"]
    assert len(inventory) > 72


@pytest.mark.parametrize("invalid", ["duplicate_event", "bin", "status", "horizon", "capacity", "pool", "schema"])
def test_invalid_membership_inputs_fail(invalid: str) -> None:
    source = frame()
    inventory = membership_inventory(BASE)
    limit = 500_000
    if invalid == "duplicate_event":
        source.loc[1, "event_id"] = "a"
    elif invalid == "bin":
        source.loc[0, "MA_a_bin"] = "unsupported"
    elif invalid == "status":
        source.loc[0, "MA_a_status"] = "missing"
    elif invalid == "horizon":
        source["horizon"] = 252
    elif invalid == "capacity":
        limit = 1
    elif invalid == "pool":
        source.loc[1, "security_id"] = "TW:002"
    else:
        source = source.drop(columns="MA_a_bin")
    with pytest.raises(ValueError):
        stock_memberships(source, inventory, max_membership_rows=limit)


def test_inventory_metadata_and_candidate_definition_reject_invalid_overrides() -> None:
    with pytest.raises(ValueError):
        membership_inventory({**BASE, "split": "development"})
    with pytest.raises(ValueError):
        membership_inventory(BASE, {"bad": (Atom("MA", "MA_a", "unsupported"),)})
    inventory = membership_inventory(BASE)
    duplicated = (*inventory, cast(dict[str, Any], inventory[0]))
    with pytest.raises(ValueError):
        stock_memberships(frame(), duplicated)


def test_unconditional_matrix_matches_full_inventory_without_condition_columns() -> None:
    source = frame().assign(
        effective_label=["hit", "unknown", "loss", "flat-win"],
        calendar_full=[True, True, True, False],
        event_main_eligible=[True, False, True, False],
        event_eligibility_excluded=False,
    )
    inventory = membership_inventory(BASE)
    unconditional = tuple(row for row in inventory if row["feature_id"] == "unconditional")
    ids = {object_digest(row) for row in unconditional}
    full = StockCountPlan(inventory).matrix(source)
    expected = full.loc[full.cell_id.isin(ids)].reset_index(drop=True)
    stripped = source.drop(columns=[f"{feature}_{suffix}" for feature in FEATURES for suffix in ("bin", "status")])
    actual = StockCountPlan(unconditional, max_membership_rows=8).matrix(stripped)
    pd.testing.assert_frame_equal(actual, expected)
    members = stock_memberships(stripped, unconditional, max_membership_rows=8 * len(source))
    assert len(members) == 8 * len(source)
    with pytest.raises(ValueError, match="allocation bound"):
        stock_memberships(stripped, unconditional, max_membership_rows=8 * len(source) - 1)
    with pytest.raises(ValueError, match="allocation bound"):
        StockCountPlan(unconditional, max_membership_rows=7).matrix(stripped)


def test_selected_feature_only_and_candidate_dependencies_are_preserved() -> None:
    source = frame()
    inventory = membership_inventory(BASE, {"candidate-1": ATOMS})
    selected = tuple(row for row in inventory if row["feature_id"] == "MA_a")
    narrow = source.loc[:, ["event_id", "security_id", "t0", "horizon", "mkt", "MA_a_bin", "MA_a_status"]]
    full = stock_memberships(source, inventory)
    ids = {object_digest(row) for row in selected}
    expected = full.loc[full.cell_id.isin(ids)].reset_index(drop=True)
    pd.testing.assert_frame_equal(stock_memberships(narrow, selected, max_membership_rows=8 * len(source)), expected)
    candidates = tuple(row for row in inventory if row["feature_id"] == "candidate")
    candidate_ids = {object_digest(row) for row in candidates}
    candidate_expected = full.loc[full.cell_id.isin(candidate_ids)].reset_index(drop=True)
    candidate_source = source.loc[:, [*narrow.columns, "MACD_bin", "MACD_status"]]
    pd.testing.assert_frame_equal(stock_memberships(candidate_source, candidates, max_membership_rows=8 * len(source)), candidate_expected)
    with pytest.raises(ValueError, match="missing condition schema for MACD"):
        stock_memberships(narrow, candidates, max_membership_rows=8 * len(source))


@pytest.mark.parametrize("invalid", ["unknown", "duplicate"])
def test_requested_inventory_rejects_unknown_or_duplicate_cells(invalid: str) -> None:
    inventory = tuple(row for row in membership_inventory(BASE) if row["feature_id"] == "unconditional")
    malformed = ({**inventory[0], "feature_id": "unregistered"},) if invalid == "unknown" else (*inventory, inventory[0])
    message = "outside the approved" if invalid == "unknown" else "duplicate inventory"
    with pytest.raises(ValueError, match=message):
        StockCountPlan(malformed)
    with pytest.raises(ValueError, match=message):
        stock_memberships(frame(), malformed)
