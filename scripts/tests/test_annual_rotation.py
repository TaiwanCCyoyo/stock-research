from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core.annual_rotation import annual_candidates, economic_path, first_observed_trade, paired_benchmark_path, select_leaders


def fixture() -> tuple[Any, pd.DataFrame, pd.DataFrame]:
    dates = pd.DatetimeIndex(["2020-12-31", "2021-01-04", "2021-12-30", "2022-01-03"])
    raw = pd.DataFrame({
        "Code": "1234",
        "Date": dates,
        "Open": [100.0, 100.0, 90.0, 100.0],
        "High": [100.0, 100.0, 90.0, 100.0],
        "Low": [100.0, 100.0, 90.0, 100.0],
        "Close": [100.0, 100.0, 90.0, 100.0],
        "Volume": 1.0,
    })
    events = pd.DataFrame({
        "code": ["1234"],
        "ex_date": [pd.Timestamp("2021-12-30")],
        "event_type": ["CASH_DIVIDEND"],
        "price_factor": [0.9],
        "cash_dividend_estimate": [10.0],
    })
    return dates, raw, events


def test_cash_reinvests_at_raw_close_and_costs_are_once():
    dates, raw, events = fixture()
    result = economic_path(raw, events, dates, start=dates[1], end=dates[-1], commission=0.01, sell_tax=0.03, slippage=0.01)
    assert result["gross_multiplier"] == pytest.approx(100 / 90)
    assert result["net_multiplier"] == pytest.approx((1 + 10 / (90 * 1.01)) / (1.01 * 1.01) * 0.99 * 0.96)
    assert result["raw_entry"] == 100


def test_entry_ex_date_has_no_entitlement_and_exit_ex_date_stays_cash():
    dates, raw, events = fixture()
    entry = economic_path(raw, events, dates, start=dates[2], end=dates[-1])
    assert entry["gross_multiplier"] == pytest.approx(100 / 90)
    exit_result = economic_path(raw, events, dates, start=dates[1], end=dates[2], sell_tax=0.03)
    assert exit_result["gross_multiplier"] == 1
    assert exit_result["net_multiplier"] == pytest.approx(0.9 * 0.97 + 0.1)


def test_unknown_rights_do_not_become_zero_or_a_factor_profit():
    dates, raw, events = fixture()
    events["event_type"] = "EX_RIGHT"
    result = economic_path(raw, events, dates, start=dates[1], end=dates[-1])
    assert result["gross_multiplier"] is None
    assert "unsupported_economic_action" in result["reasons"][0]


def test_split_requires_exact_share_ratio_not_rounded_price_factor():
    dates, raw, events = fixture()
    raw.loc[2:, ["Open", "High", "Low", "Close"]] = 25.0
    events["event_type"], events["price_factor"] = "ETF_SPLIT", 0.25001
    result = economic_path(raw, events, dates, start=dates[1], end=dates[-1])
    assert result["gross_multiplier"] is None
    known = economic_path(raw, events, dates, start=dates[1], end=dates[-1], split_ratios={"2021-12-30": 4.0})
    assert known["gross_multiplier"] == 1.0


def test_past_year_rank_ignores_future_actions_and_quotes():
    dates, raw, events = fixture()
    before = annual_candidates(raw, events, dates, year=2021)
    future = events.copy()
    future.loc[0, "ex_date"] = dates[-1]
    future["event_type"] = "UNKNOWN"
    altered = raw.copy()
    altered.loc[3, ["Open", "High", "Low", "Close"]] = 10000.0
    after = annual_candidates(altered, pd.concat([events, future]), dates, year=2021)
    assert before == after


def test_missing_quote_is_unknown_and_leader_is_not_replaced_by_future_data():
    dates, raw, events = fixture()
    raw.loc[2, "Open"] = np.nan
    result = annual_candidates(raw, events, dates, year=2021)
    assert result["ranking_gross_return"] is None
    rows = [{"code": "1235", "ranking_gross_return": 0.3}, {"code": "1234", "ranking_gross_return": 0.3}, result]
    assert select_leaders(rows)[0]["code"] == "1234"


def test_positive_volume_next_observation_and_one_price_sensitivity():
    dates, raw, _ = fixture()
    raw.loc[1, "Volume"] = 0.0
    raw.loc[3, "High"] = 101.0
    assert first_observed_trade(raw, dates, on_or_after=dates[1]) == dates[2]
    assert first_observed_trade(raw, dates, on_or_after=dates[1], avoid_one_price=True) == dates[3]


def test_duplicate_action_is_unknown():
    dates, raw, events = fixture()
    result = economic_path(raw, pd.concat([events, events]), dates, start=dates[1], end=dates[-1])
    assert result["gross_multiplier"] is None
    assert "ambiguous_same_day_actions" in result["reasons"][0]


def test_foreign_code_event_cannot_change_this_holding():
    dates, raw, events = fixture()
    foreign = events.copy()
    foreign["code"], foreign["event_type"] = "9999", "EX_RIGHT"
    expected = economic_path(raw, events, dates, start=dates[1], end=dates[-1])
    assert economic_path(raw, pd.concat([events, foreign]), dates, start=dates[1], end=dates[-1]) == expected


def test_continuous_benchmark_does_not_charge_annual_entry_and_exit():
    dates, raw, events = fixture()
    result = economic_path(raw, events, dates, start=dates[1], end=dates[-1], commission=0.01, entry_cost=False, exit_cost=False)
    assert result["net_multiplier"] == pytest.approx(1 + 10 / (90 * 1.01))


def test_dividend_on_known_halt_is_unknown_without_a_reinvestment_quote():
    dates, raw, events = fixture()
    raw = raw.drop(index=2)
    result = economic_path(raw, events, dates, start=dates[1], end=dates[-1], known_halts={"2021-12-30"})
    assert result["status"] == "unknown"
    assert result["gross_multiplier"] is None
    assert "missing_dividend_reinvestment_close" in result["reasons"][0]


def test_paired_benchmark_never_delays_to_its_own_first_quote():
    dates, raw, events = fixture()
    raw = raw.drop(index=1)
    result = paired_benchmark_path(raw, events, dates, {"entry_date": "2021-01-04", "exit_date": "2022-01-03", "is_ytd": False})
    assert result["gross_multiplier"] is None
    assert result["status"] == "unknown"


def test_new_listing_is_retained_as_ineligible_not_an_unknown_candidate():
    dates, raw, events = fixture()
    result = annual_candidates(raw.loc[raw.Date >= dates[1]], events, dates, year=2021)
    assert result["ranking_status"] == "ineligible"
    assert result["ranking_gross_return"] is None
    assert select_leaders([result]) == []


def test_known_halt_cannot_excuse_an_observed_corrupt_quote():
    dates, raw, events = fixture()
    raw.loc[2, "Low"] = 1000.0
    result = economic_path(raw, events, dates, start=dates[1], end=dates[-1], known_halts={"2021-12-30"})
    assert result["gross_multiplier"] is None
    assert "invalid_ohlc" in result["reasons"][0]
