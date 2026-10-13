"""Synthetic fixed facets, condition applicability and exact confirmation ranks."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_variants_selection import Atom, split_for_code
from research_core.pattern_scan_rates_v1 import REQUIRED_COLUMNS, summarize_events
from research_core.pattern_scan_reporting_v1 import (
    candidate_membership,
    collect_annual_facets,
    collect_facets,
    facet_masks,
    feed_facets,
    flat_facets,
    top_confirmation_candidates,
)
from research_core.pattern_scan_summary_store_v1 import SummaryStore


def events() -> pd.DataFrame:
    result = pd.DataFrame(
        [
            ("TW0050", "a", "2010-01-04", 252, "hit", True, True),
            ("TW0050", "b", "2014-01-04", 252, "unknown", True, False),
            ("TW0050", "c", "2020-01-04", 252, "loss", True, True),
        ],
        columns=pd.Index(REQUIRED_COLUMNS),
    )
    result["mkt"] = ["up", "unknown", "down"]
    return result


def test_facets_fixed_inventory_unknown_separate_and_crc_leading_zero() -> None:
    masks = list(facet_masks(events()))
    assert len(masks) == 72
    for metadata, mask in masks:
        assert mask.dtype == np.bool_
        if metadata == {"split": split_for_code("0050"), "era": "all", "mkt": "all"}:
            assert mask.tolist() == [True] * 3
        if metadata == {"split": "all", "era": "all", "mkt": "unknown"}:
            assert mask.tolist() == [False, True, False]
        if metadata == {"split": "all", "era": "2013-2018", "mkt": "all"}:
            assert mask.tolist() == [False, True, False]
    raw = events()
    raw["security_id"] = "0050"
    assert [mask.tolist() for _, mask in masks] == [mask.tolist() for _, mask in facet_masks(raw)]
    raw["security_id"] = "TW:0050"
    assert [mask.tolist() for _, mask in masks] == [mask.tolist() for _, mask in facet_masks(raw)]


def test_feed_preserves_events_counts_zero_cells_and_drop_year(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    scratch = tmp_path / ".tmp"
    scratch.mkdir()
    data = events()
    before = data.copy(deep=True)
    with SummaryStore(scratch / "summary.sqlite") as store:
        ids = feed_facets(store, data, metadata={"pattern_id": "L1", "control_id": "pattern", "cohort_id": "union"})
        assert len(set(ids)) == 72
        rows = list(collect_facets(store, ids))
        assert rows[0]["summary"] == summarize_events(data)
        assert rows[0]["removed_year"] == 2010
        assert rows[0]["drop_best_year_summary"] == summarize_events(data.iloc[1:])
        assert (rows[0]["split"], rows[0]["era"], rows[0]["mkt"]) == ("all", "all", "all")
        flat = list(flat_facets(store, ids))
        assert len(flat) == 144
        assert flat[0]["row_kind"] == "full" and flat[0]["event_n"] == 3
        assert flat[1]["row_kind"] == "drop_best_year" and flat[1]["event_n"] == 2
        assert any(cast(Mapping[str, Any], row["summary"])["event_n"] == 0 for row in rows)
        annual = list(collect_annual_facets(store, ids))
        assert len(annual) == 72 * 17
        assert cast(Mapping[str, Any], annual[0]["summary"])["event_n"] == 1
    pd.testing.assert_frame_equal(data, before)


def test_empty_facets_register_all_cells_with_explicit_horizon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".tmp").mkdir()
    with SummaryStore(tmp_path / ".tmp" / "summary.sqlite") as store:
        with pytest.raises(ValueError, match="horizon"):
            feed_facets(store, events().iloc[:0], metadata={})
        ids = feed_facets(store, events().iloc[:0], metadata={"horizon": 252})
        assert len(ids) == 72
        assert all(cast(Mapping[str, Any], row["summary"])["event_n"] == 0 for row in collect_facets(store, ids))


@pytest.mark.parametrize("column,value", [("security_id", 50), ("security_id", "TW"), ("mkt", "all"), ("t0", "20100104"), ("horizon", True)])
def test_invalid_facets_rejected(column: str, value: object) -> None:
    data = events().astype(object)
    data.loc[0, column] = value
    with pytest.raises(ValueError):
        list(facet_masks(data))


def test_candidate_truth_unknown_false_and_not_applicable_priority() -> None:
    bins = pd.DataFrame({
        "x_bin": ["yes", "no", None, "yes", "no", None],
        "x_status": ["known", "known", "feature_unknown", "known", "known", "feature_unknown"],
        "y_bin": ["high", None, "high", "low", None, None],
        "y_status": ["known", "feature_unknown", "known", "known", "not_applicable", "feature_unknown"],
    })
    result = candidate_membership(bins, (Atom("A", "x", "yes"), Atom("B", "y", "high")))
    assert result.dtype == np.int8
    assert result.tolist() == [1, 0, -1, 0, -2, -1]
    assert candidate_membership(bins.iloc[:0], (Atom("A", "x", "yes"),)).tolist() == []


def test_candidate_empty_and_missing_schema_are_errors() -> None:
    with pytest.raises(ValueError, match="nonempty"):
        candidate_membership(pd.DataFrame(), ())
    with pytest.raises(ValueError, match="schema"):
        candidate_membership(pd.DataFrame({"x_bin": ["yes"]}), (Atom("A", "x", "yes"),))
    with pytest.raises(ValueError, match="status"):
        candidate_membership(pd.DataFrame({"x_bin": ["yes"], "x_status": ["unknown"]}), (Atom("A", "x", "yes"),))


def summaries() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "pattern_id": "L1",
            "candidate_id": f"c{i:02}",
            "horizon": 252,
            "split": "cross-check",
            "era": "all",
            "mkt": "all",
            "control_id": "pattern",
            "cohort_id": "union",
            "known_n": 2,
            "hit_n": 1,
        }
        for i in range(12)
    ])


def test_top_ten_exact_fraction_ties_and_small_denominator_are_retained() -> None:
    data = summaries()
    data.loc[11, ["known_n", "hit_n"]] = [1, 1]
    assert top_confirmation_candidates(data) == {"L1": ("c11", *tuple(f"c{i:02}" for i in range(9)))}
    data.loc[10, ["known_n", "hit_n"]] = [100000000000000001, 50000000000000001]
    result = top_confirmation_candidates(data)
    assert result["L1"][:2] == ("c11", "c10")
    assert top_confirmation_candidates(data.iloc[::-1]) == result


def test_top_filters_control_split_era_mkt_horizon_cohort_and_zero_known() -> None:
    base = summaries().iloc[:1]
    extras = []
    for column, value in (("control_id", "condition"), ("split", "development"), ("era", "2019+"), ("mkt", "up"), ("horizon", 126), ("cohort_id", "subtype")):
        row = base.copy()
        row[column] = value
        row["candidate_id"] = column
        extras.append(row)
    zero = base.copy()
    zero["pattern_id"] = "P1"
    zero[["known_n", "hit_n"]] = 0
    assert top_confirmation_candidates(pd.concat([base, zero, *extras], ignore_index=True)) == {"L1": ("c00",), "P1": ()}


def test_bad_confirmation_counts_and_duplicate_are_rejected() -> None:
    data = summaries().iloc[:1]
    with pytest.raises(ValueError, match="duplicate"):
        top_confirmation_candidates(pd.concat([data, data], ignore_index=True))
    data = data.copy()
    data.loc[0, "hit_n"] = 3
    with pytest.raises(ValueError, match="counts"):
        top_confirmation_candidates(data)
