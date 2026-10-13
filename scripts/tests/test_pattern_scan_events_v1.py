from __future__ import annotations

from typing import cast

import pytest

from research_core.pattern_scan_events_v1 import describe_price_path, merge_hit_episodes, per_group_cooldown


def test_cooldown_union_dedup_and_twenty_session_boundary() -> None:
    assert per_group_cooldown([42, 20, 0, 21, 21, 40, 41]) == (0, 21, 42)
    assert per_group_cooldown([]) == ()
    # A suppressed day 20 does not extend the accepted day 0's cooldown.
    assert per_group_cooldown([0, 20, 21]) == (0, 21)


def test_caller_groups_stocks_patterns_and_controls_independently() -> None:
    groups = {("A", "union"): [0, 0, 20, 21], ("B", "union"): [20], ("A", "control"): [20]}
    assert {key: per_group_cooldown(value) for key, value in groups.items()} == {("A", "union"): (0, 21), ("B", "union"): (20,), ("A", "control"): (20,)}


def test_episode_chain_twenty_boundary_and_twenty_one_separation() -> None:
    result = merge_hit_episodes([61, 40, 20, 0, 20], [100.0] * 188)
    assert [episode.start_indices for episode in result] == [(0, 20, 40), (61,)]
    assert [(episode.anchor_index, episode.peak_index) for episode in result] == [(0, 1), (61, 62)]


def test_episode_anchor_only_among_starts_and_peak_earliest_ties() -> None:
    closes = [100.0] * 148
    closes[1], closes[20], closes[21] = 1.0, 90.0, 90.0
    closes[22], closes[23], closes[146], closes[147] = 200.0, 200.0, 190.0, 999.0
    episode = merge_hit_episodes([0, 20, 21], closes)[0]
    assert (episode.anchor_index, episode.peak_index, episode.status) == (20, 22, "known")


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), 0.0, -1.0])
def test_episode_missing_anchor_never_selects_another_start(value: float | None) -> None:
    closes: list[float | None] = [100.0] * 147
    closes[20] = value
    episode = merge_hit_episodes([0, 20], closes)[0]
    assert (episode.status, episode.reason, episode.anchor_index, episode.peak_index) == ("unknown", "missing_or_invalid_anchor", None, None)


def test_episode_missing_window_and_truncation_have_no_peak() -> None:
    closes: list[float | None] = [100.0] * 127
    closes[30] = None
    missing = merge_hit_episodes([0], closes)[0]
    truncated = merge_hit_episodes([0], [100.0] * 126)[0]
    assert (missing.status, missing.reason, missing.peak_index) == ("unknown", "missing_or_invalid_price", None)
    assert (truncated.status, truncated.reason, truncated.peak_index) == ("unknown", "incomplete_window", None)


@pytest.mark.parametrize(
    ("future", "category", "minus", "plus"),
    [
        ([90, 120], "direct_failure", 1, 2),
        ([90, 100], "direct_failure", 1, None),
        ([110, 90, 120], "rise_then_fall", 2, 1),
        ([110, 85], "slow_decline", 2, 1),
        ([110, 85.01], "sideways", 2, 1),
        ([119.99, 100], "sideways", None, 1),
        ([120, 100], "rise_then_fall", None, 1),
        ([200, 100], "rise_then_fall", None, 1),
        ([110, 89.99], "sideways", 2, 1),
        ([100, 100], "sideways", None, None),
    ],
)
def test_path_thresholds_and_order(future: list[float], category: str, minus: int | None, plus: int | None) -> None:
    result = describe_price_path([100.0, *future], 0, horizon=len(future))
    assert (result.category, result.first_minus_10_offset, result.first_plus_10_offset) == (category, minus, plus)
    assert result.reason is None


def test_path_metrics_use_future_only_and_earliest_peak() -> None:
    result = describe_price_path([999, 100, 120, 120, 110], 1, horizon=3)
    assert result.max_return == pytest.approx(0.2)
    assert result.min_return == pytest.approx(0.1)
    assert result.peak_offset == 1


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), 0, -10])
def test_path_missing_does_not_cross_gaps_or_return_false(value: float | None) -> None:
    result = describe_price_path([100, 90, value, 200], 0, horizon=3)
    assert result.category == "unknown"
    assert result.reason == "missing_or_invalid_price"
    assert result.max_return is None and result.first_minus_10_offset is None


def test_path_truncation_unknown_even_after_decisive_threshold() -> None:
    result = describe_price_path([100, 90, 200], 0, horizon=126)
    assert (result.category, result.reason) == ("unknown", "incomplete_window")
    assert describe_price_path([100] * 127, 0, horizon=126).category == "sideways"


@pytest.mark.parametrize("indices", [[True], [-1], [1.0]])
def test_invalid_indices_fail_closed(indices: list[int]) -> None:
    with pytest.raises(ValueError, match="indices"):
        per_group_cooldown(indices)
    with pytest.raises(ValueError, match="indices"):
        merge_hit_episodes(indices, [100] * 127)


def test_invalid_horizon_and_calendar_and_price_types_fail_closed() -> None:
    for horizon in (0, -1, True):
        with pytest.raises(ValueError, match="horizon"):
            describe_price_path([100, 100], 0, horizon=horizon)
    with pytest.raises(ValueError, match="outside"):
        merge_hit_episodes([127], [100] * 127)
    with pytest.raises(ValueError, match="outside"):
        describe_price_path([100], 1, horizon=1)
    with pytest.raises(ValueError, match="real"):
        describe_price_path([100, cast(float, "bad")], 0, horizon=1)
