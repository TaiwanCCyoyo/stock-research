"""Episode missingness and full-period deterministic matched controls."""

import numpy as np
import pandas as pd
import pytest

from research_core.pattern_scan_episode_coverage_v1 import CONTROL_COLUMNS, observe_episode, random_matched_control
from research_core.pattern_scan_events_v1 import Episode


def test_all_matches_first_observation_and_late_are_preserved() -> None:
    closes = [100.0] * 200
    closes[45], closes[60], closes[80] = 90, 110, 200
    states = [0] * 200
    states[45] = states[60] = 1
    result = observe_episode(Episode((50,), 50, 80, "known"), closes, [60, 45], states)
    assert result["coverage_status"] == "matched"
    assert result["matching_indices"] == (45, 60)
    assert result["first_matching_index"] == 45 and result["observed_offset"] == -5
    assert result["first_timing_certain"] is True and result["late"] is False
    assert result["entry_return"] == pytest.approx(-0.1)
    assert result["remaining_return"] == pytest.approx(200 / 90 - 1)
    result = observe_episode(Episode((50,), 50, 40, "known"), closes, [45, 60], states)
    assert result["late"] is True


def test_unknown_before_first_affects_timing_not_observed_match_or_peak_return() -> None:
    states = [0] * 200
    states[31], states[60], states[70] = -1, 1, -1
    result = observe_episode(Episode((50,), 50, None, "unknown", "missing_peak"), [100.0] * 200, [60], states)
    assert result["coverage_status"] == "matched"
    assert result["first_timing_certain"] is False
    assert result["remaining_return_known"] is False and result["remaining_return"] is None
    assert result["entry_return_known"] is True
    assert result["late"] is None
    states[31] = 0
    assert observe_episode(Episode((50,), 50, None, "unknown"), [100.0] * 200, [60], states)["first_timing_certain"] is True


def test_unmatched_requires_full_window_known_and_edges_are_unknown() -> None:
    states = [0] * 200
    assert observe_episode(Episode((50,), 50, 80, "known"), [100.0] * 200, [], states)["coverage_status"] == "unmatched"
    states[90] = -1
    assert observe_episode(Episode((50,), 50, 80, "known"), [100.0] * 200, [], states)["coverage_status"] == "unknown"
    for anchor in (0, 10, 170, None):
        result = observe_episode(Episode((0,), anchor, None, "unknown"), [100.0] * 200, [], [0] * 200)
        assert result["coverage_status"] == "unknown"


def test_edge_match_absorbs_incomplete_calendar_and_candidate_false_absorbs_raw_unknown() -> None:
    states, candidate = [0] * 100, [0] * 100
    states[1] = candidate[1] = 1
    result = observe_episode(Episode((0,), 0, None, "unknown"), [100.0] * 100, [1], states, candidate_daily_states=candidate)
    assert result["coverage_status"] == "matched" and result["first_timing_certain"] is False
    states[30] = -1
    result = observe_episode(Episode((50,), 50, None, "unknown"), [100.0] * 100, [], states, candidate_daily_states=candidate)
    assert result["coverage_status"] == "unmatched"


@pytest.mark.parametrize("states,events", [([0] * 100, [40]), ([-2] * 100, []), ([0] * 99, []), ([0] * 100, [100])])
def test_invalid_episode_inputs_fail(states: list[int], events: list[int]) -> None:
    with pytest.raises(ValueError):
        observe_episode(Episode((50,), 50, 80, "known"), [100.0] * 100, events, states)


def controls(values: list[tuple[str, int, str]]) -> pd.DataFrame:
    return pd.DataFrame(values, columns=pd.Index(CONTROL_COLUMNS))


def pool() -> pd.DataFrame:
    return controls([
        ("0050", 0, "2010-01-04"),
        ("0050", 30, "2010-03-04"),
        ("0050", 60, "2010-06-04"),
        ("0050", 90, "2011-01-04"),
        ("2330", 0, "2010-01-04"),
        ("2330", 30, "2010-03-04"),
    ])


def test_random_controls_use_full_year_pool_without_episode_window_or_outcomes() -> None:
    targets = controls([("0050", 10, "2010-01-20"), ("0050", 11, "2010-01-21"), ("0050", 12, "2010-01-22")])
    data = pool()
    data["outcome"] = ["hit"] * len(data)
    drawn, quotas = random_matched_control(data, targets, "P1")
    assert drawn.calendar_index.tolist() == [0, 30, 60]
    assert "outcome" not in drawn
    assert quotas.query("security_id == '0050' and year == 2010").quota_n.tolist() == [3]
    assert not quotas.shortfall.any()
    assert len(drawn.drop_duplicates()) == len(drawn)


def test_random_order_stability_and_independent_strata() -> None:
    targets = controls([("0050", 10, "2010-01-20"), ("2330", 10, "2010-01-20")])
    drawn, quota = random_matched_control(pool(), targets, "L1")
    other_drawn, other_quota = random_matched_control(pool().iloc[::-1], targets.iloc[::-1], "L1")
    pd.testing.assert_frame_equal(drawn, other_drawn)
    pd.testing.assert_frame_equal(quota, other_quota)
    subdraw, _ = random_matched_control(pool().query("security_id == '0050'"), targets.query("security_id == '0050'"), "L1")
    pd.testing.assert_frame_equal(drawn.query("security_id == '0050'").reset_index(drop=True), subdraw)


def test_shortfall_stays_same_stock_year_and_full_quota_table() -> None:
    targets = controls([("0050", 100, "2011-01-20"), ("0050", 101, "2011-01-21"), ("9999", 100, "2011-01-20")])
    drawn, quota = random_matched_control(pool(), targets, "B1")
    assert drawn.security_id.tolist() == ["0050"] and drawn.calendar_index.tolist() == [90]
    stock = quota.query("security_id == '0050' and year == 2011").iloc[0]
    assert (stock.quota_n, stock.drawn_n, stock.shortfall_n, stock.coverage_status) == (2, 1, 1, "unknown")
    missing = quota.query("security_id == '9999'").iloc[0]
    assert missing.available_n == 0 and missing.shortfall
    assert len(quota) == 4


def test_empty_pool_and_targets_remain_explicit() -> None:
    empty = pool().iloc[:0]
    drawn, quota = random_matched_control(empty, empty, "P1")
    assert drawn.empty and quota.empty
    drawn, quota = random_matched_control(empty, controls([("0050", 0, "2010-01-04")]), "P1")
    assert drawn.empty and quota.iloc[0].shortfall_n == 1


@pytest.mark.parametrize("kind", ["cooldown", "duplicate", "date", "numeric_stock", "negative_index"])
def test_bad_control_pool_rejected(kind: str) -> None:
    data = pool().copy().astype(object)
    if kind == "cooldown":
        data.loc[1, "calendar_index"] = 20
    elif kind == "duplicate":
        data.loc[1, ["calendar_index", "t0"]] = [0, "2010-01-04"]
    elif kind == "date":
        data.loc[0, "t0"] = "20100104"
    elif kind == "numeric_stock":
        data.loc[0, "security_id"] = 50
    else:
        data.loc[0, "calendar_index"] = -1
    with pytest.raises(ValueError):
        random_matched_control(data, data.iloc[:0], "P1")


def test_input_preservation_and_no_second_cooldown() -> None:
    data = pool()
    before = data.copy(deep=True)
    targets = controls([("0050", 10, "2010-01-20"), ("0050", 11, "2010-01-21")])
    drawn, _ = random_matched_control(data, targets, "P1")
    assert np.diff(drawn.calendar_index).min() > 20
    pd.testing.assert_frame_equal(data, before)
