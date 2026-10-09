"""Hand-checkable synthetic benchmark context; no market data or strategy test."""

from collections.abc import Sequence
from datetime import date, timedelta
from fractions import Fraction
from typing import Any

import pytest

from research_core.market_context import compute_context_rows, definition


def dates(count: int) -> list[str]:
    return [(date(2026, 1, 1) + timedelta(days=index)).isoformat() for index in range(count)]


def rows(closes: Sequence[float | None], layer: str = "past_only") -> list[dict[str, Any]]:
    return compute_context_rows(dates(len(closes)), list(closes), layer=layer)


@pytest.mark.parametrize(
    ("last", "state"),
    [(103.0, "up"), (102.999999, "consolidation"), (97.0, "down"), (97.000001, "consolidation"), (100.0, "consolidation")],
)
def test_return_boundaries(last: float, state: str) -> None:
    result = rows([100.0] * 20 + [last])[-1]
    assert result["state"] == state
    assert result["window_return"] == float(Fraction(str(last)) / 100 - 1)
    assert result["event"] is None  # First known up after warmup is not launch.


@pytest.mark.parametrize(("peak", "state"), [(108.0, "consolidation"), (108.000001, "mixed")])
def test_range_boundary_and_mixed(peak: float, state: str) -> None:
    result = rows([100.0] * 10 + [peak] + [100.0] * 10)[-1]
    assert result["state"] == state
    assert result["window_return"] == 0.0
    assert result["window_range"] == pytest.approx((peak - 100) / 100)


def test_trend_precedes_range_and_twenty_intervals_use_twenty_one_prices() -> None:
    result = rows([100.0] * 10 + [150.0] + [100.0] * 9 + [103.0])
    assert all(row["state"] == "unknown" for row in result[:20])
    assert result[19]["missing_reason"] == "warmup"
    assert result[20]["state"] == "up"
    assert result[20]["window_range"] == 0.5
    assert result[20]["window_start"] == dates(21)[0]
    assert result[20]["window_end"] == dates(21)[20]
    assert result[19]["information_cutoff"] == dates(21)[19]


@pytest.mark.parametrize("bad", [None, 0.0, -1.0, float("nan"), float("inf"), float("-inf")])
def test_unusable_windows_do_not_fill_and_recover(bad: float | None) -> None:
    result = rows([100.0] * 21 + [bad] + [100.0] * 21)
    assert result[20]["state"] == "consolidation"
    for row in result[21:42]:
        assert row["state"] == "unknown"
        assert row["missing_reason"] == "unusable_observations"
        assert row["window_return"] is None
        assert row["window_range"] is None
        assert row["event"] is None
    assert result[42]["state"] == "consolidation"


def test_launch_resumption_continuation_and_down_reset() -> None:
    # Each 21-price plateau washes the preceding level out of the window.
    result = rows([100.0] * 21 + [104.0] * 21 + [108.16] * 21 + [100.0] * 21 + [104.0] * 21)
    assert (result[20]["state"], result[20]["event"]) == ("consolidation", None)
    assert (result[21]["state"], result[21]["event"]) == ("up", "launch")
    assert (result[22]["state"], result[22]["event"]) == ("up", None)
    assert result[41]["state"] == "consolidation"
    assert (result[42]["state"], result[42]["event"]) == ("up", "resumption")
    assert result[63]["state"] == "down"
    assert (result[84]["state"], result[84]["event"]) == ("up", "launch")


def test_unknown_resets_event_history_and_first_known_up_establishes_history() -> None:
    result = rows([100.0] * 21 + [104.0] * 21 + [None] + [100.0] * 20 + [104.0] * 21 + [108.16])
    assert result[42]["state"] == "unknown"
    assert (result[63]["state"], result[63]["event"]) == ("up", None)
    assert result[83]["state"] == "consolidation"
    assert (result[84]["state"], result[84]["event"]) == ("up", "resumption")


def test_mixed_does_not_establish_resumption_history() -> None:
    # The low 90 remains in both windows while endpoints change from 100 to 104.
    result = rows([100.0] * 10 + [90.0] + [100.0] * 9 + [104.0, 100.0, 104.0])
    assert (result[20]["state"], result[20]["event"]) == ("up", None)
    assert result[21]["state"] == "mixed"
    assert (result[22]["state"], result[22]["event"]) == ("up", "launch")


def test_past_only_prefix_and_scale_invariance() -> None:
    prices = [100.0] * 21 + [104.0] * 21 + [108.0] * 21 + [95.0] * 21
    expected = rows(prices)
    for length in (1, 20, 21, 25, 42, 65):
        assert rows(prices[:length]) == expected[:length]
    assert rows([close * 10 for close in prices]) == expected
    assert rows(prices[:42] + [200.0] * 42)[:42] == expected[:42]


def test_retrospective_cutoff_tail_and_future_dependence() -> None:
    prices = [100.0] * 21 + [104.0] * 20
    result = rows(prices, "retrospective")
    assert all(row["missing_reason"] == "warmup" for row in result[:10])
    assert result[10]["information_cutoff"] == dates(41)[20]
    assert result[11]["state"] == "up"
    assert result[11]["event"] == "launch"
    for row in result[-10:]:
        assert row["state"] == "unknown"
        assert row["missing_reason"] == "future_unavailable"
        assert row["information_cutoff"] is None
        assert row["window_end"] is None
    assert rows([100.0] * 41, "retrospective")[11]["state"] == "consolidation"
    assert rows(prices[:21], "retrospective")[11]["state"] == "unknown"


def test_short_centered_series_declares_unavailable_future() -> None:
    result = rows([100.0] * 5, "retrospective")
    assert all(row["missing_reason"] == "future_unavailable" for row in result)
    assert all(row["information_cutoff"] is None for row in result)


@pytest.mark.parametrize(
    ("calendar", "closes", "layer", "message"),
    [
        (["2026-01-01"], [], "past_only", "equal lengths"),
        (["2026-01-01"], [100.0], "future", "layer"),
        (["20260101"], [100.0], "past_only", "ISO"),
        (["2026-1-01"], [100.0], "past_only", "ISO"),
        (["2026-02-30"], [100.0], "past_only", "ISO"),
        (["2026-01-01", "2026-01-01"], [100.0] * 2, "past_only", "ordered and unique"),
        (["2026-01-02", "2026-01-01"], [100.0] * 2, "past_only", "ordered and unique"),
        (["2026-01-01"], [True], "past_only", "numeric"),
        (["2026-01-01"], ["100"], "past_only", "numeric"),
        ([None], [100.0], "past_only", "ISO"),
    ],
)
def test_invalid_inputs(calendar: Any, closes: Any, layer: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        compute_context_rows(calendar, closes, layer=layer)


def test_empty_input_and_independent_definition_objects() -> None:
    assert rows([]) == []
    assert rows([], "retrospective") == []
    rule = definition()
    assert rule["intervals"] + 1 == rule["observations"]
    rule["thresholds"]["up_return_min"] = 99
    assert definition()["thresholds"]["up_return_min"] == 0.03
