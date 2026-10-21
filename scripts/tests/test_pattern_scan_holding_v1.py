from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_variants_run import UNKNOWN_INDUSTRIES
from research_core.pattern_scan_holding_v1 import STATES, holding_values


def _inputs() -> tuple[pd.DataFrame, dict[str, str], pd.Series, pd.Series, pd.DataFrame, pd.Series]:
    dates = pd.bdate_range("2020-01-01", periods=5)
    prices = pd.DataFrame(
        {"0001": [10.0, 15.0, 20.0, 25.0, 30.0], "0002": [20.0, 40.0, 60.0, 80.0, 100.0], "0003": [30.0, 80.0, 120.0, 140.0, 160.0]}, index=dates
    )
    industries = {code: "tech" for code in prices.columns}
    benchmark = pd.Series([100.0, 105.0, 110.0, 115.0, 120.0], index=dates)
    states = pd.Series(["up", None, "down", "mixed", "consolidation"], index=dates)
    jumps = pd.DataFrame(False, index=dates, columns=prices.columns)
    benchmark_jump = pd.Series(False, index=dates)
    return prices, industries, benchmark, states, jumps, benchmark_jump


def _run(*, horizon: int = 2) -> pd.DataFrame:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    return holding_values(prices, industries, benchmark, states, horizons=(horizon,), jump_matrix=jumps, benchmark_jump=benchmark_jump)


def _row(result: pd.DataFrame, code: str = "0001", anchor: int = 0, horizon: int = 2) -> Any:
    mask = (
        cast(pd.Series, result["security_id"]).eq(code) & cast(pd.Series, result["calendar_index"]).eq(anchor) & cast(pd.Series, result["horizon"]).eq(horizon)
    )
    return cast(Any, result.loc[mask].iloc[0])


def test_fixed_peers_exclude_self_with_integer_counts_and_original_codes() -> None:
    result = _run()
    first = _row(result)
    second = _row(result, "0002")
    assert first["security_id"] == "0001"
    assert first["own_return"] == 1
    assert first["peer_return"] == 2.5
    assert second["peer_return"] == 2
    assert first["potential_peer_n"] == first["known_peer_n"] == 2
    assert first["unknown_peer_n"] == 0
    assert first["benchmark_return"] == pytest.approx(0.1)
    assert not bool(result.duplicated(["security_id", "t0", "calendar_index", "horizon"]).any())


@pytest.mark.parametrize("industry", sorted(UNKNOWN_INDUSTRIES))
def test_unknown_industry_does_not_invent_peers_or_block_benchmark(industry: str) -> None:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    industries["0001"] = industry
    result = holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump)
    row = _row(result)
    assert pd.isna(row["peer_return"])
    assert row["peer_return_reason"] == "unknown_industry"
    assert row["potential_peer_n"] == row["known_peer_n"] == row["unknown_peer_n"] == 0
    assert row["own_return"] == 1
    assert row["benchmark_return"] == pytest.approx(0.1)


def test_single_classified_stock_has_no_peers_and_different_industry_not_included() -> None:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    industries["0001"] = "different"
    result = holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump)
    assert _row(result)["peer_return_reason"] == "no_peers"
    assert _row(result)["potential_peer_n"] == 0
    assert _row(result, "0002")["peer_return"] == 3


def test_missing_peer_endpoint_keeps_potential_and_unknown_counts_without_zero_fill() -> None:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    prices.loc[prices.index[2], "0002"] = np.nan
    result = holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump)
    row = _row(result)
    assert row["peer_return"] == 3
    assert row["known_peer_n"] == row["unknown_peer_n"] == 1
    assert row["potential_peer_n"] == 2
    assert _row(result, "0002")["own_return_reason"] == "invalid_endpoint"


def test_middle_missing_price_is_endpoint_diagnostic_not_label_reclassification() -> None:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    prices.loc[prices.index[1], "0002"] = np.nan
    result = holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump)
    assert _row(result, "0002")["own_return"] == 2
    assert _row(result)["peer_return"] == 2.5
    assert _row(result)["known_peer_n"] == 2


@pytest.mark.parametrize("jump_day", [0, 1, 2])
def test_window_jump_including_anchor_and_endpoint_makes_return_unknown(jump_day: int) -> None:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    jumps.loc[jumps.index[jump_day], "0002"] = True
    result = holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump)
    assert _row(result, "0002")["own_return_reason"] == "unexplained_jump"
    assert _row(result)["peer_return"] == 3
    assert _row(result)["unknown_peer_n"] == 1


def test_unknown_quality_is_not_false_and_absent_layers_are_explicit() -> None:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    nullable = jumps.astype("boolean")
    nullable.loc[nullable.index[1], "0002"] = pd.NA
    result = holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=nullable, benchmark_jump=benchmark_jump)
    assert _row(result, "0002")["own_return_reason"] == "quality_unknown"
    absent = holding_values(prices, industries, benchmark, states, horizons=(2,))
    row = _row(absent)
    assert row["own_return_reason"] == row["benchmark_return_reason"] == "quality_layer_not_supplied"
    assert pd.isna(row["own_return"]) and pd.isna(row["benchmark_return"])
    assert row["known_peer_n"] == 0 and row["unknown_peer_n"] == 2


def test_censored_rows_keep_peer_counts_and_observed_context_denominator() -> None:
    row = _row(_run(horizon=3), anchor=3, horizon=3)
    assert not row["calendar_full"] and row["censored"] and row["endpoint_out_of_range"]
    assert row["observed_sessions"] == 1
    assert row["potential_peer_n"] == row["unknown_peer_n"] == 2
    assert row["known_peer_n"] == 0
    assert row["peer_return_reason"] == row["own_return_reason"] == row["benchmark_return_reason"] == "window_end"
    assert row["holding_consolidation_fraction"] == 1
    last = _row(_run(), anchor=4)
    assert last["observed_sessions"] == 0 and last["holding_context_reason"] == "no_observed_future"
    assert all(pd.isna(last[f"holding_{state}_fraction"]) for state in STATES)


def test_future_context_includes_unknown_and_excludes_anchor() -> None:
    row = _row(_run(horizon=3), horizon=3)
    assert row["observed_sessions"] == 3
    assert row["holding_up_n"] == row["holding_consolidation_n"] == 0
    assert row["holding_unknown_n"] == row["holding_down_n"] == row["holding_mixed_n"] == 1
    assert sum(row[f"holding_{state}_n"] for state in STATES) == 3
    assert sum(row[f"holding_{state}_fraction"] for state in STATES) == pytest.approx(1)
    assert row["information_scope"] == "retrospective_holding_diagnostic"


def test_benchmark_quality_and_endpoint_are_independent_of_peers() -> None:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    benchmark_jump.iloc[1] = True
    result = holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump)
    row = _row(result)
    assert row["benchmark_return_reason"] == "unexplained_jump"
    assert row["peer_return"] == 2.5
    benchmark_jump.iloc[1] = False
    benchmark.iloc[2] = np.nan
    result = holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump)
    assert _row(result)["benchmark_return_reason"] == "invalid_endpoint"


def test_all_missing_stock_remains_in_the_fixed_grid_and_peer_inventory() -> None:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    prices["0003"] = np.nan
    result = holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump)
    assert len(result) == len(prices) * 3
    assert _row(result)["potential_peer_n"] == 2 and _row(result)["known_peer_n"] == 1
    assert _row(result, "0003")["own_return_reason"] == "invalid_anchor"
    assert _row(result, "0003")["peer_return"] == 1.5


def test_exact_common_grid_and_metadata_required() -> None:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    with pytest.raises(ValueError, match="exactly cover"):
        holding_values(prices.drop(columns="0003"), industries, benchmark, states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump)
    with pytest.raises(ValueError, match="price grid"):
        holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps.iloc[:-1], benchmark_jump=benchmark_jump)
    with pytest.raises(ValueError, match="common calendar"):
        holding_values(prices, industries, benchmark.iloc[:-1], states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump)


def test_malformed_states_and_numeric_jump_flags_are_rejected() -> None:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    states.iloc[0] = "not_a_regime"
    with pytest.raises(ValueError, match="retrospective"):
        holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump)
    states.iloc[0] = "up"
    with pytest.raises(ValueError, match="booleans"):
        holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps.astype(int), benchmark_jump=benchmark_jump)


def test_both_fixed_horizons_use_the_same_calendar_and_prepared_benchmark_basis() -> None:
    calendar = pd.bdate_range("2020-01-01", periods=253)
    prices = pd.DataFrame({"0001": 100.0, "0002": 200.0}, index=calendar)
    benchmark = pd.Series(100.0, index=calendar)
    benchmark.iloc[126] = 110
    benchmark.iloc[252] = 120
    jumps = pd.DataFrame(False, index=calendar, columns=prices.columns)
    result = holding_values(
        prices,
        {"0001": "tech", "0002": "tech"},
        benchmark,
        pd.Series("unknown", index=calendar),
        jump_matrix=jumps,
        benchmark_jump=pd.Series(False, index=calendar),
    )
    assert _row(result, horizon=126)["benchmark_return"] == pytest.approx(0.1)
    assert _row(result, horizon=252)["benchmark_return"] == pytest.approx(0.2)
    assert _row(result, horizon=252)["holding_unknown_n"] == 252


def test_changes_after_endpoint_do_not_change_completed_holding_diagnostic() -> None:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    original = holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump)
    prices.loc[prices.index[3:], :] = np.nan
    benchmark.iloc[3:] = np.nan
    states.iloc[3:] = "unknown"
    changed = holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump)
    pd.testing.assert_series_equal(_row(original), _row(changed))


def test_requested_anchor_rows_match_full_output_without_filtering_peers() -> None:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    full = holding_values(prices, industries, benchmark, states, horizons=(1, 2), jump_matrix=jumps, benchmark_jump=benchmark_jump)
    selected = holding_values(
        prices, industries, benchmark, states, horizons=(1, 2), jump_matrix=jumps, benchmark_jump=benchmark_jump, anchors={"0001": [2, 0], "0003": [1]}
    )
    mask = (cast(pd.Series, full["security_id"]).eq("0001") & cast(pd.Series, full["calendar_index"]).isin([0, 2])) | (
        cast(pd.Series, full["security_id"]).eq("0003") & cast(pd.Series, full["calendar_index"]).eq(1)
    )
    expected = full.loc[mask].reset_index(drop=True)
    pd.testing.assert_frame_equal(selected, expected)
    assert _row(selected)["potential_peer_n"] == _row(selected)["known_peer_n"] == 2
    assert "0002" not in set(selected["security_id"])


@pytest.mark.parametrize("anchors", [{}, {"0001": []}])
def test_empty_requested_anchors_keep_stable_schema(anchors: dict[str, list[int]]) -> None:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    full = _run()
    empty = holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump, anchors=anchors)
    pd.testing.assert_frame_equal(empty, full.iloc[:0].reset_index(drop=True))


@pytest.mark.parametrize("anchors", [{"missing": [0]}, {"0001": [0, 0]}, {"0001": [-1]}, {"0001": [5]}, {"0001": [True]}, {"0001": [1.5]}])
def test_invalid_requested_anchor_identity_or_positions_are_rejected(anchors: Any) -> None:
    prices, industries, benchmark, states, jumps, benchmark_jump = _inputs()
    with pytest.raises(ValueError, match="anchor"):
        holding_values(prices, industries, benchmark, states, horizons=(2,), jump_matrix=jumps, benchmark_jump=benchmark_jump, anchors=anchors)
