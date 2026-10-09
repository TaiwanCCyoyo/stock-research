"""Hand-calculable attribution fixtures; no prices or research outputs are read."""

import math
from copy import deepcopy
from datetime import date, timedelta
from typing import Any

import pytest

from research_core.attribution import AttributionError, mark_attempt_pnl, non_hit_attribution
from research_core.ledger import LedgerError, mark_equity, replay_ledger


def attempt(identity: str, entry: int, exit_index: int | None, hit: bool | None, *, captured: float | None = None) -> dict[str, Any]:
    return {"id": identity, "entry_index": entry, "exit_index": exit_index, "hit": hit, "captured_pnl_twd": captured}


def points(curves: dict[str, list[float | None]], initial: float = 2_000_000) -> list[dict[str, Any]]:
    count = len(next(iter(curves.values())))
    assert all(len(curve) == count for curve in curves.values())
    result = []
    for index in range(count):
        observed = [curve[index] for curve in curves.values() if curve[index] is not None]
        # A missing attribution is not silently treated as a zero account mark.
        equity = initial + math.fsum(value for value in observed if value is not None) if len(observed) == len(curves) else None
        result.append({
            "date": (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
            "equity": equity,
            "attempt_pnl": {identity: curve[index] for identity, curve in curves.items()},
        })
    return result


def test_twenty_non_hits_keep_small_wins_but_exclude_a_large_hit() -> None:
    # One concurrent winner, and twenty sequential non-hit attempts. At most two
    # positions overlap; losses occur first, then the small profitable non-hits.
    attempts = [attempt("winner", 1, 42, True, captured=500_000)]
    curves: dict[str, list[float | None]] = {"winner": [0.0] * 43}
    for index in range(20):
        identity = f"miss-{index}"
        entry = 2 + 2 * index
        exit_index = entry + 1
        pnl = -20_000.0 if index < 10 else 5_000.0
        attempts.append(attempt(identity, entry, exit_index, False))
        curves[identity] = [0.0 if checkpoint < exit_index else pnl for checkpoint in range(43)]
    curves["winner"] = [0.0 if index < 20 else 500_000.0 for index in range(43)]
    result = non_hit_attribution(attempts, points(curves), initial_equity=2_000_000)
    whole = result["whole_study"]
    assert whole["status"] == "ok"
    assert whole["net_pnl_twd"] == -150_000
    assert whole["worst_cumulative_loss_twd"] == 200_000
    assert whole["peak_to_trough_erosion_twd"] == 200_000
    assert whole["net_fraction_initial"] == pytest.approx(-0.075)
    assert result["window_summary"]["status"] == "ok"
    assert len(result["windows"]) == 1
    assert result["windows"][0]["start_index"] == 1
    assert result["windows"][0]["end_index"] == 41
    assert result["windows"][0]["peak_to_trough_fraction_start"] == pytest.approx(0.1)
    assert points(curves)[-1]["equity"] == 2_350_000
    assert "winner" not in whole["attempt_ids"]


def test_hit_breaks_windows_but_does_not_reset_whole_study_non_hit_losses() -> None:
    attempts = [attempt("a", 1, 2, False), attempt("hit", 3, 4, True, captured=100), attempt("b", 5, 6, False)]
    checkpoints = points({"a": [0, 0, -20, -20, -20, -20, -20], "hit": [0, 0, 0, 0, 100, 100, 100], "b": [0, 0, 0, 0, 0, 0, -10]}, 1_000)
    result = non_hit_attribution(attempts, checkpoints, initial_equity=1_000, span=2)
    assert result["windows"] == []
    assert result["window_summary"]["status"] == "no_eligible_windows"
    assert result["window_summary"]["worst_peak_to_trough_fraction_start"] is None
    assert [run["attempt_ids"] for run in result["runs"]] == [["a"], ["b"]]
    assert result["whole_study"]["net_pnl_twd"] == -30


def test_overlapping_holding_periods_use_latest_exit_and_fixed_start_equity() -> None:
    attempts = [attempt("a", 1, 5, False), attempt("b", 2, 3, False)]
    checkpoints = points({"a": [0, -1, -2, 10, -30, -5], "b": [0, 0, -1, 10, 10, 10]}, 100)
    result = non_hit_attribution(attempts, checkpoints, initial_equity=100, span=2)
    window = result["windows"][0]
    assert window["end_index"] == 5
    assert window["net_pnl_twd"] == 5
    assert window["worst_cumulative_loss_twd"] == 20
    assert window["peak_to_trough_erosion_twd"] == 40
    assert window["peak_to_trough_fraction_start"] == pytest.approx(0.4)


def test_every_overlapping_window_is_retained() -> None:
    attempts = [attempt("a", 1, 2, False), attempt("b", 3, 4, False), attempt("c", 5, 6, False)]
    checkpoints = points({"a": [0, 0, -10, -10, -10, -10, -10], "b": [0, 0, 0, 0, -20, -20, -20], "c": [0, 0, 0, 0, 0, 0, 5]}, 100)
    result = non_hit_attribution(attempts, checkpoints, initial_equity=100, span=2)
    assert [window["attempt_ids"] for window in result["windows"]] == [["a", "b"], ["b", "c"]]
    assert result["windows"][1]["start_equity"] == 90
    assert result["windows"][1]["peak_to_trough_fraction_start"] == pytest.approx(20 / 90)
    assert result["windows"][1]["peak_to_trough_fraction_initial"] == pytest.approx(0.2)


@pytest.mark.parametrize("exit_index", [None, 4])
def test_unknown_or_open_attempt_is_not_dropped_to_form_a_window(exit_index: int | None) -> None:
    attempts = [attempt("a", 1, 2, False), attempt("unknown", 3, exit_index, None), attempt("b", 5, 6, False)]
    checkpoints = points({"a": [0, 0, -10, -10, -10, -10, -10], "unknown": [0, 0, 0, -1, -100, -100, -100], "b": [0, 0, 0, 0, 0, 0, 5]}, 1_000)
    result = non_hit_attribution(attempts, checkpoints, initial_equity=1_000, span=2)
    assert result["unknown_attempt_ids"] == ["unknown"]
    assert result["whole_study"]["status"] == "partial"
    assert result["whole_study"]["net_pnl_twd"] == -5
    assert result["unclassified_attribution"]["status"] == "partial"
    assert result["unclassified_attribution"]["net_pnl_twd"] == -100
    assert result["windows"] == []
    assert result["window_summary"]["status"] == "unavailable"


def test_missing_in_life_mark_makes_the_metric_unavailable_not_zero() -> None:
    attempts = [attempt("a", 1, 3, False)]
    checkpoints = points({"a": [0, -1, None, -10]}, 100)
    result = non_hit_attribution(attempts, checkpoints, initial_equity=100, span=1)
    assert result["whole_study"]["status"] == "unavailable"
    assert result["whole_study"]["net_pnl_twd"] is None
    assert result["windows"][0]["status"] == "unavailable"
    assert result["window_summary"]["status"] == "unavailable"
    assert result["window_summary"]["worst_peak_to_trough_fraction_start"] is None


@pytest.mark.parametrize("equity", [None, 0])
def test_missing_or_zero_denominator_does_not_publish_a_fraction(equity: float | None) -> None:
    if equity is None:
        checkpoints = points({"a": [0, -1, -10]}, 100)
        checkpoints[0]["equity"] = None
        result = non_hit_attribution([attempt("a", 1, 2, False)], checkpoints, initial_equity=100, span=1)
        assert result["windows"][0]["net_pnl_twd"] == -10
    else:
        checkpoints = points({"a": [0, -1, -100, -100, -100], "b": [0, 0, 0, 0, 0]}, 100)
        result = non_hit_attribution([attempt("a", 1, 2, False), attempt("b", 3, 4, False)], checkpoints, initial_equity=100, span=1)
        assert result["windows"][-1]["net_pnl_twd"] == 0
    assert result["windows"][-1]["peak_to_trough_fraction_start"] is None
    assert result["window_summary"]["status"] == "unavailable"


def test_partial_sale_split_and_delayed_dividend_use_economic_not_cash_pnl() -> None:
    events = [
        {"action": "BUY", "code": "A", "date": "2026-01-01", "qty": 2, "total": -102},
        {"action": "DIVIDEND_ENTITLEMENT", "code": "A", "date": "2026-01-02", "total": 0, "entitlement_id": "x", "amount": 10},
        {"action": "SPLIT", "code": "A", "date": "2026-01-03", "total": 0, "qty": 2, "old_qty": 2, "new_qty": 4},
        {"action": "SELL", "code": "A", "date": "2026-01-04", "qty": 2, "total": 44},
        {"action": "SELL", "code": "A", "date": "2026-01-05", "qty": 2, "total": 44},
        {"action": "BUY", "code": "A", "date": "2026-01-06", "qty": 1, "total": -40},
        {"action": "DIVIDEND", "code": "A", "date": "2026-01-07", "total": 10, "entitlement_id": "x"},
    ]
    raw_marks = [50, 45, 22.5, 22.5, None, 40, 40]
    expected_pnl = [-2, -2, -2, -3, -4, -4, -4]
    for prefix, (price, expected) in enumerate(zip(raw_marks, expected_pnl, strict=True), 1):
        ledger = replay_ledger(1_000, events[:prefix])
        marks = {} if price is None else {"A": price}
        attributed = mark_attempt_pnl(ledger, marks)
        assert attributed["0"] == pytest.approx(expected)
        assert sum(attributed.values()) == pytest.approx(mark_equity(ledger, marks) - 1_000)
        if prefix >= 6:
            assert attributed["5"] == 0
    with pytest.raises(LedgerError, match="missing mark"):
        mark_attempt_pnl(replay_ledger(1_000, events[:1]), {})


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "entry_zero",
        "exit_before_entry",
        "open_hit",
        "not_ordered",
        "not_zero_before_entry",
        "changed_after_exit",
        "unknown_pnl_id",
        "reversed_dates",
        "boolean_pnl",
    ],
)
def test_invalid_input_is_rejected(mutation: str) -> None:
    attempts = [attempt("a", 1, 2, False), attempt("b", 3, 4, False)]
    checkpoints = points({"a": [0, -1, -10, -10, -10], "b": [0, 0, 0, -1, 2]}, 100)
    if mutation == "duplicate":
        attempts[1]["id"] = "a"
    elif mutation == "entry_zero":
        attempts[0]["entry_index"] = 0
    elif mutation == "exit_before_entry":
        attempts[0]["exit_index"] = 0
    elif mutation == "open_hit":
        attempts[0].update(exit_index=None, hit=True)
    elif mutation == "not_ordered":
        attempts.reverse()
    elif mutation == "not_zero_before_entry":
        checkpoints[0]["attempt_pnl"]["a"] = 1
    elif mutation == "changed_after_exit":
        checkpoints[4]["attempt_pnl"]["a"] = -5
    elif mutation == "unknown_pnl_id":
        checkpoints[0]["attempt_pnl"]["unexpected"] = 0
    elif mutation == "reversed_dates":
        checkpoints.reverse()
    elif mutation == "boolean_pnl":
        checkpoints[1]["attempt_pnl"]["a"] = True
    with pytest.raises(AttributionError):
        non_hit_attribution(attempts, checkpoints, initial_equity=100, span=2)


def test_inputs_are_not_mutated() -> None:
    attempts = [attempt("a", 1, 2, False)]
    checkpoints = points({"a": [0, -1, -10]}, 100)
    original = deepcopy((attempts, checkpoints))
    non_hit_attribution(attempts, checkpoints, initial_equity=100, span=1)
    assert (attempts, checkpoints) == original


def test_same_timestamp_keeps_execution_checkpoint_order() -> None:
    attempts = [attempt("a", 1, 2, False), attempt("b", 3, 4, False)]
    checkpoints = points({"a": [0, -1, -5, -5, -5], "b": [0, 0, 0, -1, 2]}, 100)
    for point in checkpoints:
        point["date"] = "2026-01-01T09:00:00"
    result = non_hit_attribution(attempts, checkpoints, initial_equity=100, span=2)
    assert result["windows"][0]["net_pnl_twd"] == -3
    assert result["windows"][0]["peak_to_trough_erosion_twd"] == 6


def test_zero_equity_inside_the_path_is_a_measured_total_loss() -> None:
    result = non_hit_attribution([attempt("a", 1, 3, False)], points({"a": [0, -1, -100, -100]}, 100), initial_equity=100, span=1)
    assert result["whole_study"]["status"] == "ok"
    assert result["windows"][0]["peak_to_trough_fraction_start"] == 1


def test_missing_pnl_key_is_not_an_implicit_zero() -> None:
    checkpoints = points({"a": [0, -1, -10]}, 100)
    del checkpoints[1]["attempt_pnl"]["a"]
    result = non_hit_attribution([attempt("a", 1, 2, False)], checkpoints, initial_equity=100, span=1)
    assert result["whole_study"]["status"] == "unavailable"
    assert result["whole_study"]["net_pnl_twd"] is None


@pytest.mark.parametrize(
    "field,value", [("entry_index", True), ("entry_index", -1), ("entry_index", 1.0), ("entry_index", 3), ("exit_index", 3), ("exit_index", True)]
)
def test_invalid_or_out_of_bounds_indices_are_rejected(field: str, value: Any) -> None:
    item = attempt("a", 1, 2, False)
    item[field] = value
    with pytest.raises(AttributionError):
        non_hit_attribution([item], points({"a": [0, -1, -5]}, 100), initial_equity=100)


@pytest.mark.parametrize("value", [True, 0, -1, math.nan, math.inf])
def test_invalid_initial_equity_is_rejected(value: Any) -> None:
    with pytest.raises(AttributionError):
        non_hit_attribution([attempt("a", 1, 2, False)], points({"a": [0, -1, -5]}, 100), initial_equity=value)


@pytest.mark.parametrize("value", [True, 0, -1, 1.5])
def test_invalid_window_span_is_rejected(value: Any) -> None:
    with pytest.raises(AttributionError):
        non_hit_attribution([attempt("a", 1, 2, False)], points({"a": [0, -1, -5]}, 100), initial_equity=100, span=value)


def test_insufficient_attempts_and_all_hits_do_not_pass_by_default() -> None:
    checkpoints = points({"a": [0, -1, 10]}, 100)
    result = non_hit_attribution([attempt("a", 1, 2, False)], checkpoints, initial_equity=100, span=20)
    assert result["window_summary"]["status"] == "insufficient_windows"
    assert result["window_summary"]["worst_peak_to_trough_fraction_start"] is None
    result = non_hit_attribution([attempt("a", 1, 2, True, captured=10)], checkpoints, initial_equity=100, span=1)
    assert result["whole_study"]["status"] == "unavailable"
    assert result["whole_study"]["net_pnl_twd"] is None
    assert result["window_summary"]["status"] == "no_eligible_windows"


@pytest.mark.parametrize("hit", [0, 1, 0.0, 1.0, "false", [], {}])
def test_hit_labels_must_be_boolean_or_explicit_unknown(hit: Any) -> None:
    item = attempt("a", 1, 2, False)
    item["hit"] = hit
    with pytest.raises(AttributionError):
        non_hit_attribution([item], points({"a": [0, -1, -10]}, 100), initial_equity=100)


def test_whole_study_uses_the_complete_supplied_path_not_only_the_first_miss_start() -> None:
    attempts = [attempt("winner", 1, 2, True, captured=100), attempt("a", 3, 4, False)]
    checkpoints = points({"winner": [0, 0, 100, 100, 100, 100], "a": [0, 0, 0, -1, -10, -10]}, 100)
    result = non_hit_attribution(attempts, checkpoints, initial_equity=100, span=1)
    assert result["whole_study"]["start_index"] == 0
    assert result["whole_study"]["end_index"] == 5
    assert result["whole_study"]["peak_to_trough_fraction_start"] == pytest.approx(0.1)
    assert result["windows"][0]["peak_to_trough_fraction_start"] == pytest.approx(0.05)
    del checkpoints[-1]["attempt_pnl"]["a"]
    result = non_hit_attribution(attempts, checkpoints, initial_equity=100, span=1)
    assert result["whole_study"]["status"] == "unavailable"
    assert result["windows"][0]["status"] == "ok"


def test_incomparable_timezone_checkpoints_are_rejected_cleanly() -> None:
    checkpoints = points({"a": [0, -1, -10]}, 100)
    checkpoints[1]["date"] = "2026-01-02T00:00:00+08:00"
    with pytest.raises(AttributionError, match="comparable"):
        non_hit_attribution([attempt("a", 1, 2, False)], checkpoints, initial_equity=100)


def test_fraction_overflow_is_not_emitted_as_infinite_evidence() -> None:
    checkpoints = points({"a": [0, 0, 100]}, 1e-320)
    with pytest.raises(AttributionError, match="finite"):
        non_hit_attribution([attempt("a", 1, 2, False)], checkpoints, initial_equity=1e-320, span=1)


def test_marking_requires_one_open_attempt_for_each_held_code() -> None:
    ledger = replay_ledger(100, [{"action": "BUY", "code": "A", "date": "2026-01-01", "qty": 1, "total": -10}])
    ledger["open_attempts"] = []
    with pytest.raises(LedgerError, match="every current holding"):
        mark_attempt_pnl(ledger, {"A": 10})


def test_ledger_amounts_cannot_be_boolean_or_numeric_strings() -> None:
    ledger = replay_ledger(100, [{"action": "BUY", "code": "A", "date": "2026-01-01", "qty": 1, "total": -10}])
    ledger["open_attempts"][0]["buy_total"] = "-10"
    with pytest.raises(LedgerError):
        mark_attempt_pnl(ledger, {"A": 10})


@pytest.mark.parametrize("captured,economic", [(1, -10), (1, 0), (0, 100), (-10, 100), (101, 100)])
def test_hit_cannot_hide_nonpositive_captured_or_contradictory_economic_pnl(captured: float, economic: float) -> None:
    with pytest.raises(AttributionError):
        non_hit_attribution([attempt("a", 1, 2, True, captured=captured)], points({"a": [0, -1, economic]}, 1_000), initial_equity=1_000, span=1)


@pytest.mark.parametrize("missing", ["captured", "closed_pnl"])
def test_declared_hit_with_missing_evidence_remains_unresolved(missing: str) -> None:
    attempts = [attempt("a", 1, 2, False), attempt("claimed_hit", 3, 4, True, captured=100), attempt("b", 5, 6, False)]
    checkpoints = points({"a": [0, -1, -10, -10, -10, -10, -10], "claimed_hit": [0, 0, 0, -1, 100, 100, 100], "b": [0, 0, 0, 0, 0, -1, -10]}, 1_000)
    if missing == "captured":
        del attempts[1]["captured_pnl_twd"]
    else:
        checkpoints[4]["attempt_pnl"]["claimed_hit"] = None
    result = non_hit_attribution(attempts, checkpoints, initial_equity=1_000, span=2)
    assert result["classification_complete"] is False
    assert result["unknown_attempt_ids"] == ["claimed_hit"]
    assert result["window_summary"]["status"] == "unavailable"
    assert result["classification_reasons"]["claimed_hit"]
    assert attempts[1]["hit"] is True  # Diagnostic resolution does not mutate supplied labels.


def test_missing_interior_account_equity_is_partial_not_complete() -> None:
    checkpoints = points({"a": [0, -1, -10, -10]}, 100)
    checkpoints[2]["equity"] = None
    result = non_hit_attribution([attempt("a", 1, 3, False)], checkpoints, initial_equity=100, span=1)
    assert result["whole_study"]["status"] == "partial"
    assert result["whole_study"]["net_pnl_twd"] == -10
    assert result["windows"][0]["status"] == "partial"
    assert result["window_summary"]["status"] == "unavailable"


def test_missing_unselected_hit_pnl_blocks_complete_account_evidence() -> None:
    attempts = [attempt("hit", 1, 4, True, captured=100), attempt("a", 2, 3, False)]
    checkpoints = points({"hit": [0, -1, 10, 50, 100], "a": [0, 0, -1, -10, -10]}, 1_000)
    del checkpoints[2]["attempt_pnl"]["hit"]
    result = non_hit_attribution(attempts, checkpoints, initial_equity=1_000, span=1)
    assert result["whole_study"]["status"] == "unavailable"
    assert result["windows"][0]["status"] == "unavailable"
    assert result["window_summary"]["status"] == "unavailable"


def test_inconsistent_account_equity_is_rejected() -> None:
    checkpoints = points({"a": [0, -1, -10]}, 100)
    checkpoints[1]["equity"] = 100
    with pytest.raises(AttributionError, match="reconcile"):
        non_hit_attribution([attempt("a", 1, 2, False)], checkpoints, initial_equity=100, span=1)


def test_documented_raw_marks_keyword_is_supported() -> None:
    ledger = replay_ledger(100, [{"action": "BUY", "code": "A", "date": "2026-01-01", "qty": 1, "total": -10}])
    assert mark_attempt_pnl(ledger=ledger, raw_marks={"A": 9}) == {"0": -1}
