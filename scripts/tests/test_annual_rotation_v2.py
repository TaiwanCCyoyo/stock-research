from dataclasses import FrozenInstanceError, replace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core.annual_rotation import economic_path
from research_core.annual_rotation_v2 import Entitlement, economic_path_v2


def day_at(days: pd.DatetimeIndex, position: int) -> pd.Timestamp:
    value = days[position]
    assert isinstance(value, pd.Timestamp)
    return value


def fixture(prices: list[float] | None = None) -> tuple[pd.DatetimeIndex, pd.DataFrame, pd.DataFrame]:
    days = pd.date_range("2020-01-06", periods=4, freq="B")
    values = prices or [100.0, 90.0, 95.0, 100.0]
    raw = pd.DataFrame({"Code": "1234", "Date": days, "Open": values, "High": values, "Low": values, "Close": values, "Volume": 1.0})
    actions = pd.DataFrame({
        "code": ["1234"],
        "ex_date": [day_at(days, 1)],
        "event_type": ["CASH_DIVIDEND"],
        "price_factor": [0.9],
        "cash_dividend_estimate": [10.0],
    })
    return days, raw, actions


def entitlement(day: object, **terms: Any) -> Entitlement:
    assert isinstance(day, pd.Timestamp)
    fields = {"evidence_ids": ("official-record-1",), "source_event_type": "EX_RIGHT", **terms}
    return Entitlement("1234", str(day.date()), str(day.date()), **fields)


@pytest.mark.parametrize("end_position,end_field", [(3, "Open"), (1, "Open"), (3, "Close")])
def test_cash_and_costs_match_v1_including_exit_cash(end_position: int, end_field: str):
    days, raw, actions = fixture()
    policy = {"start": day_at(days, 0), "end": day_at(days, end_position), "end_field": end_field, "commission": 0.01, "sell_tax": 0.03, "slippage": 0.01}
    previous = economic_path(raw, actions, days, **policy)
    actual = economic_path_v2(raw, actions, days, **policy)
    assert actual["gross_multiplier"] == pytest.approx(previous["gross_multiplier"])
    assert actual["net_multiplier"] == pytest.approx(previous["net_multiplier"])
    assert actual["complete_equity"] is True
    assert actual["events"][0]["source_actions"][0]["event_type"] == "CASH_DIVIDEND"


@pytest.mark.parametrize("event_position", [1, 3])
def test_exact_etf_split_matches_v1_including_open_exit(event_position: int):
    days, raw, actions = fixture([100.0] * 4)
    raw.loc[event_position:, ["Open", "High", "Low", "Close"]] = 25.0
    actions.loc[0, ["ex_date", "event_type", "price_factor"]] = [day_at(days, event_position), "ETF_SPLIT", 0.25]
    policy = {"start": day_at(days, 0), "end": day_at(days, -1), "split_ratios": {str(day_at(days, event_position).date()): 4.0}}
    assert economic_path_v2(raw, actions, days, **policy)["gross_multiplier"] == economic_path(raw, actions, days, **policy)["gross_multiplier"] == 1.0


def test_bonus_and_cash_use_pre_event_units_in_both_scenarios():
    days, raw, actions = fixture([100.0, 50.0, 52.0, 55.0])
    actions.loc[0, ["event_type", "price_factor"]] = ["EX_RIGHT_AND_DIVIDEND", 0.5]
    item = entitlement(day_at(days, 1), share_multiplier=2.0, cash_per_old_share=10.0, kind="BONUS_AND_CASH", source_event_type="EX_RIGHT_AND_DIVIDEND")
    original = actions.copy(deep=True)
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[item], commission=0.01, exit_cost=False)
    assert result["gross_multiplier"] == pytest.approx((2 / 100 + 10 / (100 * 50)) * 55)
    assert result["net_multiplier"] == pytest.approx((2 / 101 + 10 / (101 * 50 * 1.01)) * 55)
    assert result["events"][0]["source_actions"][0]["event_type"] == "EX_RIGHT_AND_DIVIDEND"
    assert result["events"][0]["quality_diagnostics"][0]["source"] == "source_price_factor"
    pd.testing.assert_frame_equal(actions, original)


@pytest.mark.parametrize("multiplier,price", [(0.5, 200.0), (10.0, 10.0)])
def test_share_only_reduction_and_par_change_have_explicit_quality_diagnostic(multiplier: float, price: float):
    days, raw, actions = fixture([100.0, price, price, price])
    actions = actions.iloc[:0]
    result = economic_path_v2(
        raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[entitlement(day_at(days, 1), share_multiplier=multiplier)]
    )
    assert result["gross_multiplier"] == pytest.approx(1.0)
    diagnostic = result["events"][0]["quality_diagnostics"][0]
    assert diagnostic["source"] == "reciprocal_exact_share_multiplier"
    assert diagnostic["diagnostic_only"] is True
    assert diagnostic["explains_jump"] is True
    assert result["events"][0]["source_actions"] == []


def test_terms_that_contradict_a_small_observed_move_keep_the_path_unknown():
    days, raw, actions = fixture([100.0, 110.0, 110.0, 110.0])
    actions = actions.iloc[:0]
    item = entitlement(day_at(days, 1), share_multiplier=0.5)
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[item])
    assert result["status"] == "unknown" and result["gross_multiplier"] is None
    assert f"{day_at(days, 1).date()}:entitlement_terms_contradict_observed_quote" in result["reasons"]


def test_terms_are_checked_on_a_close_exit_day():
    days, raw, actions = fixture([100.0, 100.0, 100.0, 110.0])
    actions = actions.iloc[:0]
    item = entitlement(day_at(days, -1), share_multiplier=0.5)
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), end_field="Close", entitlements=[item])
    assert result["status"] == "unknown"
    assert f"{day_at(days, -1).date()}:entitlement_terms_contradict_observed_quote" in result["reasons"]


def test_terms_after_a_carried_halt_are_checked_against_the_last_observed_close():
    days, raw, actions = fixture([100.0, 100.0, 110.0, 110.0])
    actions = actions.iloc[:0]
    item = entitlement(day_at(days, 2), share_multiplier=0.5)
    result = economic_path_v2(
        raw.drop(index=1), actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[item], known_halts={str(day_at(days, 1).date())}
    )
    assert result["status"] == "unknown"
    assert f"{day_at(days, 2).date()}:entitlement_terms_contradict_observed_quote" in result["reasons"]


def test_a_native_cash_dividend_contradicting_the_quote_keeps_the_path_unknown():
    days, raw, actions = fixture([100.0, 110.0, 110.0, 110.0])
    actions.loc[0, "cash_dividend_estimate"] = 90.0
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1))
    assert result["status"] == "unknown"
    assert f"{day_at(days, 1).date()}:native_action_contradicts_observed_quote" in result["reasons"]


def test_a_native_cash_dividend_on_an_open_exit_day_is_checked_against_the_open():
    days, raw, actions = fixture([100.0, 100.0, 100.0, 110.0])
    actions.loc[0, "ex_date"] = day_at(days, -1)
    actions.loc[0, "cash_dividend_estimate"] = 90.0
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), end_field="Open")
    assert result["status"] == "unknown"
    assert f"{day_at(days, -1).date()}:native_action_contradicts_observed_quote" in result["reasons"]


def test_small_terms_survive_ordinary_noise_in_either_direction():
    days, raw, actions = fixture([100.0, 103.0, 103.0, 103.0])
    actions = actions.iloc[:0]
    item = entitlement(day_at(days, 1), share_multiplier=1.02)
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[item])
    assert result["status"] == "modeled" and result["gross_multiplier"] == pytest.approx(1.03 * 1.02)


def test_lapse_and_realize_are_separate_rights_scenarios():
    days, raw, actions = fixture([100.0, 80.0, 80.0, 80.0])
    actions.loc[0, "event_type"] = "EX_RIGHT"
    item = entitlement(day_at(days, 1), share_multiplier=1.1, cash_per_old_share=2.0, rights_per_old_share=0.2, subscription_price=30.0)
    policy = {"start": day_at(days, 0), "end": day_at(days, -1), "entitlements": [item]}
    lapse = economic_path_v2(raw, actions, days, rights_scenario="lapse", **policy)
    realize = economic_path_v2(raw, actions, days, rights_scenario="realize", **policy)
    assert lapse["gross_multiplier"] == pytest.approx(0.9)
    assert realize["gross_multiplier"] == pytest.approx(1.0)
    assert lapse["events"][0]["rights_value_per_old_share"] == 0
    assert realize["events"][0]["rights_value_per_old_share"] == 10


@pytest.mark.parametrize("availability", ["H", "N"])
@pytest.mark.parametrize("missing_row", [True, False])
def test_official_no_ohlc_marks_carry_but_complete_equity_is_false(availability: str, missing_row: bool):
    days, raw, actions = fixture([100.0] * 4)
    if missing_row:
        raw = raw.drop(index=1)
    else:
        raw.loc[1, ["Open", "High", "Low", "Close"]] = np.nan
    result = economic_path_v2(
        raw, actions.iloc[:0], days, start=day_at(days, 0), end=day_at(days, -1), unavailable_days={str(day_at(days, 1).date()): availability}
    )
    assert result["status"] == "modeled"
    assert result["gross_multiplier"] == 1.0
    assert result["carried_days"] == 1
    assert result["complete_equity"] is False
    assert result["marks"][1]["mark_observed"] is False
    assert result["marks"][1]["gross"] == 1.0


def test_valid_observed_quote_wins_over_halt_metadata():
    days, raw, actions = fixture([100.0, 110.0, 110.0, 110.0])
    result = economic_path_v2(raw, actions.iloc[:0], days, start=day_at(days, 0), end=day_at(days, -1), known_halts={str(day_at(days, 1).date())})
    assert result["gross_multiplier"] == 1.1
    assert result["complete_equity"] is True
    assert result["marks"][1]["mark_observed"] is True


def test_unresolved_status_and_corrupt_quotes_cannot_be_excused():
    days, raw, actions = fixture()
    absent = economic_path_v2(
        raw.drop(index=1), actions.iloc[:0], days, start=day_at(days, 0), end=day_at(days, -1), unavailable_days={str(day_at(days, 1).date()): "U"}
    )
    raw.loc[1, "Low"] = 1000.0
    corrupt = economic_path_v2(raw, actions.iloc[:0], days, start=day_at(days, 0), end=day_at(days, -1), unavailable_days={str(day_at(days, 1).date()): "H"})
    assert absent["gross_multiplier"] is None
    assert "missing_official_quote" in absent["reasons"][0]
    assert corrupt["gross_multiplier"] is None
    assert "invalid_ohlc" in corrupt["reasons"][0]


@pytest.mark.parametrize("terms,scenario", [({"cash_per_old_share": 2.0}, "lapse"), ({"rights_per_old_share": 0.1, "subscription_price": 100.0}, "realize")])
def test_reinvestment_never_uses_carried_or_delayed_price(terms: dict[str, float], scenario: str):
    days, raw, actions = fixture([100.0] * 4)
    actions.loc[0, "event_type"] = "EX_RIGHT"
    result = economic_path_v2(
        raw.drop(index=1),
        actions,
        days,
        start=day_at(days, 0),
        end=day_at(days, -1),
        entitlements=[entitlement(day_at(days, 1), **terms)],
        rights_scenario=scenario,
        known_halts={str(day_at(days, 1).date())},
    )
    assert result["gross_multiplier"] is None
    assert "missing_entitlement_reinvestment_close" in result["reasons"][0]


def test_cash_dividend_on_halt_keeps_v1_unknown_rule():
    days, raw, actions = fixture()
    result = economic_path_v2(raw.drop(index=1), actions, days, start=day_at(days, 0), end=day_at(days, -1), known_halts={str(day_at(days, 1).date())})
    assert result["gross_multiplier"] is None
    assert "missing_dividend_reinvestment_close" in result["reasons"][0]


def test_entry_entitlement_is_excluded_and_future_entitlement_is_ignored():
    days, raw, actions = fixture([100.0] * 4)
    actions.loc[0, ["ex_date", "event_type"]] = [day_at(days, 0), "EX_RIGHT"]
    entry = entitlement(day_at(days, 0), share_multiplier=3.0)
    future = entitlement(day_at(days, -1) + pd.Timedelta(days=1), share_multiplier=8.0)
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[entry, future])
    assert result["gross_multiplier"] == 1
    assert result["events"] == []


def test_open_exit_share_entitlement_is_ambiguous_but_cash_stays_cash():
    days, raw, actions = fixture([100.0] * 4)
    actions.loc[0, ["ex_date", "event_type"]] = [day_at(days, -1), "EX_RIGHT"]
    share = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[entitlement(day_at(days, -1), share_multiplier=2)])
    cash = economic_path_v2(
        raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[entitlement(day_at(days, -1), cash_per_old_share=10)], sell_tax=0.03
    )
    assert share["gross_multiplier"] is None
    assert "ambiguous_open_exit_entitlement" in share["reasons"][0]
    assert cash["gross_multiplier"] == pytest.approx(1.1)
    assert cash["net_multiplier"] == pytest.approx(1.07)


def test_explicit_noncalendar_source_mapping_does_not_suppress_unrelated_action():
    days, raw, actions = fixture([100.0, 100.0, 100.0, 100.0])
    announced = day_at(days, 0) + pd.Timedelta(days=1)
    # Omit this business day from this deliberately sparse calendar.
    calendar = days.delete(1)
    raw = raw.loc[raw.Date.isin(calendar)]
    actions.loc[0, ["ex_date", "event_type"]] = [announced, "EX_RIGHT"]
    item = replace(entitlement(day_at(days, 2), share_multiplier=1.1), announced_date=str(announced.date()))
    mapped = economic_path_v2(raw, actions, calendar, start=day_at(days, 0), end=day_at(days, -1), entitlements=[item])
    assert mapped["gross_multiplier"] == pytest.approx(1.1)
    unrelated = actions.copy()
    unrelated.loc[0, "ex_date"] = day_at(days, 2) + pd.Timedelta(hours=0)
    rejected = economic_path_v2(
        raw, pd.concat([actions, unrelated], ignore_index=True), calendar, start=day_at(days, 0), end=day_at(days, -1), entitlements=[item]
    )
    assert rejected["gross_multiplier"] is None
    assert any("ambiguous_same_day_actions" in reason for reason in rejected["reasons"])
    not_mapped = economic_path_v2(raw, actions, calendar, start=day_at(days, 0), end=day_at(days, -1))
    assert any("noncalendar_action" in reason for reason in not_mapped["reasons"])


def test_unrelated_noncalendar_event_remains_unknown_after_one_override():
    days, raw, actions = fixture([100.0] * 4)
    calendar = days.delete(2)
    raw = raw.loc[raw.Date.isin(calendar)]
    actions.loc[0, "event_type"] = "EX_RIGHT"
    other = actions.copy()
    other.loc[0, "ex_date"] = day_at(days, 2)
    result = economic_path_v2(
        raw,
        pd.concat([actions, other], ignore_index=True),
        calendar,
        start=day_at(days, 0),
        end=day_at(days, -1),
        entitlements=[entitlement(day_at(days, 1), share_multiplier=1.1)],
    )
    assert result["gross_multiplier"] is None
    assert any("noncalendar_action" in reason for reason in result["reasons"])


@pytest.mark.parametrize(
    "terms",
    [
        {"share_multiplier": 0},
        {"share_multiplier": np.inf},
        {"cash_per_old_share": -1},
        {"rights_per_old_share": np.nan},
        {"subscription_price": -1},
        {"rights_per_old_share": 0.1},
        {"code": ""},
    ],
)
def test_invalid_economic_terms_are_rejected(terms: dict[str, Any]):
    fields = {"code": "1234", "effective_date": "2020-01-07", "announced_date": "2020-01-07", **terms}
    with pytest.raises(ValueError):
        Entitlement(**fields)


def test_rights_require_evidence_and_entitlement_is_frozen():
    with pytest.raises(ValueError, match="evidence"):
        Entitlement("1234", "2020-01-07", "2020-01-07", rights_per_old_share=0.1, subscription_price=10)
    item = entitlement(pd.Timestamp("2020-01-07"))
    with pytest.raises(FrozenInstanceError):
        attribute = "share_multiplier"
        setattr(item, attribute, 2)
    with pytest.raises(TypeError):
        invalid_arguments: dict[str, Any] = {"unsupported": 1}
        Entitlement("1234", "2020-01-07", "2020-01-07", **invalid_arguments)


def test_duplicate_overrides_and_unbound_cash_are_unknown():
    days, raw, actions = fixture()
    actions.loc[0, "event_type"] = "EX_RIGHT"
    item = entitlement(day_at(days, 1), share_multiplier=1.1)
    duplicate = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[item, item])
    missing_source = economic_path_v2(
        raw, actions.iloc[:0], days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[entitlement(day_at(days, 1), cash_per_old_share=1)]
    )
    assert any("duplicate_or_conflicting_entitlements" in reason for reason in duplicate["reasons"])
    assert any("missing_override_action" in reason for reason in missing_source["reasons"])


def test_entitlement_cannot_explain_a_jump_in_the_wrong_direction():
    days, raw, actions = fixture([100.0, 200.0, 200.0, 200.0])
    result = economic_path_v2(
        raw, actions.iloc[:0], days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[entitlement(day_at(days, 1), share_multiplier=2)]
    )
    assert result["gross_multiplier"] is None
    assert "unexplained_raw_jump" in result["reasons"][0]


def test_missing_endpoint_cannot_be_carried_and_duplicate_quote_cannot_be_overridden():
    days, raw, actions = fixture()
    actions.loc[0, "event_type"] = "EX_RIGHT"
    endpoint = economic_path_v2(
        raw.drop(index=3), actions.iloc[:0], days, start=day_at(days, 0), end=day_at(days, -1), known_halts={str(day_at(days, -1).date())}
    )
    duplicate = economic_path_v2(
        pd.concat([raw, raw.iloc[[1]]]),
        actions,
        days,
        start=day_at(days, 0),
        end=day_at(days, -1),
        entitlements=[entitlement(day_at(days, 1), share_multiplier=1.1)],
    )
    assert "missing_endpoint_price" in endpoint["reasons"]
    assert any("duplicate_date" in reason for reason in duplicate["reasons"])


def test_unsupported_scenario_and_unrelated_economic_action_remain_rejected():
    days, raw, actions = fixture()
    with pytest.raises(ValueError, match="rights_scenario"):
        economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), rights_scenario="exercise")
    actions.loc[0, "event_type"] = "EX_RIGHT"
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1))
    assert any("unsupported_economic_action:EX_RIGHT" in reason for reason in result["reasons"])


def test_sole_unrelated_merger_is_not_swallowed_by_a_date_only_override():
    days, raw, actions = fixture([100.0] * 4)
    actions.loc[0, "event_type"] = "MERGER"
    result = economic_path_v2(
        raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[entitlement(day_at(days, 1), share_multiplier=1.1)]
    )
    assert result["status"] == "unknown"
    assert any("unsupported_action" in reason for reason in result["reasons"])
    with pytest.raises(ValueError, match="source_event_type"):
        entitlement(day_at(days, 1), share_multiplier=1.1, source_event_type="MERGER")


def test_binding_uses_only_original_ex_date_never_the_effective_date():
    days, raw, actions = fixture([100.0] * 4)
    actions.loc[0, ["ex_date", "event_type"]] = [day_at(days, 2), "EX_RIGHT"]
    item = replace(entitlement(day_at(days, 2), share_multiplier=1.1), announced_date=str(day_at(days, 1).date()))
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[item])
    assert result["status"] == "unknown"
    assert any("ambiguous_same_day_actions" in reason for reason in result["reasons"])


@pytest.mark.parametrize("bad", [-1.0, 0.0, np.inf, -np.inf])
def test_halt_cannot_turn_negative_zero_or_infinite_quotes_into_missing(bad: float):
    days, raw, actions = fixture([100.0] * 4)
    raw.loc[1, ["Open", "High", "Low", "Close"]] = bad
    result = economic_path_v2(raw, actions.iloc[:0], days, start=day_at(days, 0), end=day_at(days, -1), known_halts={str(day_at(days, 1).date())})
    assert result["status"] == "unknown"
    assert result["carried_days"] == 0
    assert any("invalid_ohlc" in reason for reason in result["reasons"])


def test_share_quantity_cannot_change_at_a_carried_pre_transformation_mark():
    days, raw, actions = fixture([100.0, np.nan, 5.0, 5.0])
    actions.loc[0, "event_type"] = "EX_RIGHT"
    result = economic_path_v2(
        raw,
        actions,
        days,
        start=day_at(days, 0),
        end=day_at(days, -1),
        known_halts={str(day_at(days, 1).date())},
        entitlements=[entitlement(day_at(days, 1), share_multiplier=20.0)],
    )
    assert result["status"] == "unknown"
    assert result["gross_multiplier"] is None
    assert any("share_change_requires_observed_effective_quote" in reason for reason in result["reasons"])
    assert all(mark["gross"] <= 1 for mark in result["marks"])


@pytest.mark.parametrize("original_ex_date", ["2020-01-03", "2020-01-06"])
def test_original_ex_date_before_or_at_entry_cannot_confer_later_entitlement(original_ex_date: str):
    days, raw, actions = fixture([100.0] * 4)
    actions.loc[0, ["ex_date", "event_type"]] = [pd.Timestamp(original_ex_date), "EX_RIGHT"]
    item = replace(entitlement(day_at(days, 1), share_multiplier=2.0), announced_date=original_ex_date)
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[item])
    assert result["status"] == "unknown"
    assert any("ownership_before_entry_unresolved" in reason for reason in result["reasons"])


def test_synthetic_share_entitlement_requires_source_evidence():
    days, raw, actions = fixture([100.0] * 4)
    item = entitlement(day_at(days, 1), share_multiplier=1.1, evidence_ids=())
    result = economic_path_v2(raw, actions.iloc[:0], days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[item])
    assert result["status"] == "unknown"
    assert any("synthetic_share_entitlement_requires_evidence" in reason for reason in result["reasons"])


def recovery_fixture(gap_count: int, restored: float, availability: str) -> tuple[pd.DatetimeIndex, pd.DataFrame, pd.DataFrame, dict[str, str]]:
    days = pd.bdate_range("2020-01-06", periods=gap_count + 3)
    prices = [100.0, *([np.nan] * gap_count), restored, restored]
    raw = pd.DataFrame({"Code": "1234", "Date": days, "Open": prices, "High": prices, "Low": prices, "Close": prices, "Volume": 1.0})
    actions = pd.DataFrame(columns=pd.Index(["code", "ex_date", "event_type", "price_factor", "cash_dividend_estimate"]))
    missing = {str(day_at(days, position).date()): availability for position in range(1, gap_count + 1)}
    return days, raw, actions, missing


@pytest.mark.parametrize("gap_count", [1, 2])
@pytest.mark.parametrize("availability", ["H", "N"])
@pytest.mark.parametrize("restored", [5.0, 200.0])
def test_recovery_after_carried_days_cannot_hide_an_unexplained_large_jump(gap_count: int, availability: str, restored: float):
    days, raw, actions, missing = recovery_fixture(gap_count, restored, availability)
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), unavailable_days=missing)
    assert result["status"] == "unknown"
    assert result["gross_multiplier"] is None
    assert any("unexplained_raw_jump_after_carry" in reason for reason in result["reasons"])


@pytest.mark.parametrize("gap_count", [1, 2])
@pytest.mark.parametrize("availability", ["H", "N"])
def test_small_recovery_change_keeps_terminal_model_and_incomplete_equity(gap_count: int, availability: str):
    days, raw, actions, missing = recovery_fixture(gap_count, 90.0, availability)
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), unavailable_days=missing)
    assert result["status"] == "modeled"
    assert result["gross_multiplier"] == pytest.approx(0.9)
    assert result["carried_days"] == gap_count
    assert result["complete_equity"] is False


@pytest.mark.parametrize("gap_count", [1, 2])
@pytest.mark.parametrize("availability", ["H", "N"])
def test_exact_admitted_share_terms_explain_the_bridge_from_last_observed_close(gap_count: int, availability: str):
    days, raw, actions, missing = recovery_fixture(gap_count, 5.0, availability)
    restored = day_at(days, gap_count + 1)
    result = economic_path_v2(
        raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), unavailable_days=missing, entitlements=[entitlement(restored, share_multiplier=20)]
    )
    assert result["status"] == "modeled"
    assert result["gross_multiplier"] == pytest.approx(1.0)
    diagnostic = result["recovery_quality_diagnostics"][0]
    assert diagnostic["source"] == "recovery_exact_share_terms"
    assert diagnostic["anchor_date"] == str(day_at(days, 0).date())
    assert diagnostic["anchor_raw_close"] == 100
    assert diagnostic["factor"] == pytest.approx(0.05)
    assert diagnostic["explains_jump"] is True


@pytest.mark.parametrize("event_kind", ["native_cash", "tiny_entitlement", "foreign_entitlement"])
def test_an_unrelated_event_or_source_factor_is_not_a_recovery_pass(event_kind: str):
    days, raw, actions, missing = recovery_fixture(1, 5.0, "H")
    restored = day_at(days, 2)
    terms = []
    if event_kind == "foreign_entitlement":
        terms = [replace(entitlement(restored, share_multiplier=20), code="9999")]
    else:
        actions.loc[0] = ["1234", restored, "CASH_DIVIDEND" if event_kind == "native_cash" else "EX_RIGHT", 0.05, 1.0]
        if event_kind == "tiny_entitlement":
            terms = [entitlement(restored, cash_per_old_share=1)]
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), unavailable_days=missing, entitlements=terms)
    assert result["status"] == "unknown"
    assert any("unexplained_raw_jump_after_carry" in reason for reason in result["reasons"])


@pytest.mark.parametrize("event_kind", ["ETF_SPLIT", "CASH_DIVIDEND"])
def test_supported_native_exact_economic_terms_can_explain_recovery(event_kind: str):
    days, raw, actions, missing = recovery_fixture(2, 25.0, "H")
    restored = day_at(days, 3)
    actions.loc[0] = ["1234", restored, event_kind, 0.25, 75.0]
    ratios = {str(restored.date()): 4.0} if event_kind == "ETF_SPLIT" else {}
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), unavailable_days=missing, split_ratios=ratios)
    assert result["status"] == "modeled"
    assert result["gross_multiplier"] == pytest.approx(1.0)
    assert result["recovery_quality_diagnostics"][0]["factor"] == pytest.approx(0.25)


@pytest.mark.parametrize("scenario,expected", [("lapse", 0.1), ("realize", 1.0)])
def test_recovery_rights_quote_quality_is_independent_of_the_holders_scenario(scenario: str, expected: float):
    days, raw, actions, missing = recovery_fixture(1, 10.0, "N")
    restored = day_at(days, 2)
    actions.loc[0] = ["1234", restored, "EX_RIGHT", 0.1, 0.0]
    term = entitlement(restored, rights_per_old_share=9.0, subscription_price=0.0)
    result = economic_path_v2(
        raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), unavailable_days=missing, entitlements=[term], rights_scenario=scenario
    )
    assert result["status"] == "modeled"
    assert result["gross_multiplier"] == pytest.approx(expected)
    diagnostic = result["recovery_quality_diagnostics"][0]
    assert diagnostic["source"] == "recovery_theoretical_ex_right_terms"
    assert diagnostic["factor"] == pytest.approx(0.1)
    assert diagnostic["source_factor_explains_jump"] is True


@pytest.mark.parametrize("rights,source_factor", [(9.0, 0.9), (0.1, 0.1)])
def test_recovery_rights_requires_both_terms_and_source_factor_to_explain(rights: float, source_factor: float):
    days, raw, actions, missing = recovery_fixture(1, 10.0, "N")
    restored = day_at(days, 2)
    actions.loc[0] = ["1234", restored, "EX_RIGHT", source_factor, 0.0]
    term = entitlement(restored, rights_per_old_share=rights, subscription_price=0.0)
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), unavailable_days=missing, entitlements=[term])
    assert result["status"] == "unknown"
    assert any("unexplained_raw_jump_after_carry" in reason for reason in result["reasons"])


@pytest.mark.parametrize("cash", [100.0, 101.0])
def test_invalid_zero_or_negative_theoretical_recovery_factor_is_unknown(cash: float):
    days, raw, actions, missing = recovery_fixture(1, 5.0, "H")
    restored = day_at(days, 2)
    actions.loc[0] = ["1234", restored, "CASH_DIVIDEND", 0.05, cash]
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), unavailable_days=missing)
    assert result["status"] == "unknown"
    assert any("invalid_recovery_economic_factor" in reason for reason in result["reasons"])
    assert result["recovery_quality_diagnostics"][0]["factor_valid"] is False


@pytest.mark.parametrize("scenario,expected", [("lapse", 0.1), ("realize", 1.0)])
def test_ordinary_rights_jump_requires_explicit_terms_and_keeps_scenario_independent_quality(scenario: str, expected: float):
    days, raw, actions = fixture([100.0, 10.0, 10.0, 10.0])
    event_day = day_at(days, 1)
    actions.loc[0, ["event_type", "price_factor", "cash_dividend_estimate"]] = ["EX_RIGHT", 0.1, 0.0]
    term = entitlement(event_day, rights_per_old_share=9.0, subscription_price=0.0)
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[term], rights_scenario=scenario)
    assert result["status"] == "modeled"
    assert result["gross_multiplier"] == pytest.approx(expected)
    assert result["complete_equity"] is True
    diagnostics = result["events"][0]["quality_diagnostics"]
    terms_diagnostic = next(value for value in diagnostics if value["source"] == "event_theoretical_ex_right_terms")
    assert terms_diagnostic["factor"] == pytest.approx(0.1)
    assert terms_diagnostic["source_factor_explains_jump"] is True
    assert terms_diagnostic["explains_jump"] is True


@pytest.mark.parametrize("scenario", ["lapse", "realize"])
@pytest.mark.parametrize("rights,source_factor", [(0.1, 0.1), (9.0, 0.9)])
def test_ordinary_rights_jump_rejects_mismatched_terms_or_source_factor_in_both_scenarios(scenario: str, rights: float, source_factor: float):
    days, raw, actions = fixture([100.0, 10.0, 10.0, 10.0])
    event_day = day_at(days, 1)
    actions.loc[0, ["event_type", "price_factor", "cash_dividend_estimate"]] = ["EX_RIGHT", source_factor, 0.0]
    term = entitlement(event_day, rights_per_old_share=rights, subscription_price=0.0)
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[term], rights_scenario=scenario)
    assert result["status"] == "unknown"
    assert result["gross_multiplier"] is None
    assert result["net_multiplier"] is None
    assert any("unexplained_raw_jump" in reason for reason in result["reasons"])


@pytest.mark.parametrize("scenario", ["lapse", "realize"])
@pytest.mark.parametrize("share,cash", [(0.5, 0.0), (1.0, 1.0), (2.0, 1.0)])
def test_ordinary_share_cash_jump_cannot_use_source_factor_to_override_conflicting_terms(scenario: str, share: float, cash: float):
    days, raw, actions = fixture([100.0, 10.0, 10.0, 10.0])
    actions.loc[0, ["event_type", "price_factor", "cash_dividend_estimate"]] = ["EX_RIGHT_AND_DIVIDEND", 0.1, cash]
    term = entitlement(day_at(days, 1), share_multiplier=share, cash_per_old_share=cash, source_event_type="EX_RIGHT_AND_DIVIDEND")
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[term], rights_scenario=scenario)
    assert result["status"] == "unknown"
    assert result["gross_multiplier"] is None
    assert result["net_multiplier"] is None
    assert any("unexplained_raw_jump" in reason for reason in result["reasons"])


@pytest.mark.parametrize("scenario", ["lapse", "realize"])
@pytest.mark.parametrize("share,cash,close", [(0.5, 0.0, 200.0), (1.0, 90.0, 10.0), (2.0, 20.0, 40.0)])
def test_ordinary_share_cash_jump_accepts_compatible_explicit_terms(scenario: str, share: float, cash: float, close: float):
    days, raw, actions = fixture([100.0, close, close, close])
    actions.loc[0, ["event_type", "price_factor", "cash_dividend_estimate"]] = ["EX_RIGHT_AND_DIVIDEND", close / 100, cash]
    term = entitlement(day_at(days, 1), share_multiplier=share, cash_per_old_share=cash, source_event_type="EX_RIGHT_AND_DIVIDEND")
    result = economic_path_v2(raw, actions, days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[term], rights_scenario=scenario)
    assert result["status"] == "modeled"
    assert result["gross_multiplier"] == pytest.approx(1.0)
    assert result["complete_equity"] is True
    source = "event_cash_share_terms" if cash > 0 else "event_exact_share_terms"
    diagnostic = next(value for value in result["events"][0]["quality_diagnostics"] if value["source"] == source)
    assert diagnostic["factor"] == pytest.approx(close / 100)
    assert diagnostic["explains_jump"] is True


@pytest.mark.parametrize("scenario", ["lapse", "realize"])
@pytest.mark.parametrize("share,close", [(0.5, 200.0), (20.0, 5.0)])
def test_ordinary_source_free_share_transformation_keeps_exact_term_quality_explanation(scenario: str, share: float, close: float):
    days, raw, actions = fixture([100.0, close, close, close])
    term = entitlement(day_at(days, 1), share_multiplier=share, source_event_type=None)
    result = economic_path_v2(raw, actions.iloc[:0], days, start=day_at(days, 0), end=day_at(days, -1), entitlements=[term], rights_scenario=scenario)
    assert result["status"] == "modeled"
    assert result["gross_multiplier"] == pytest.approx(1.0)
    event = result["events"][0]
    assert event["source_actions"] == []
    assert any(value["source"] == "reciprocal_exact_share_multiplier" and value["explains_jump"] for value in event["quality_diagnostics"])
    assert any(value["source"] == "event_exact_share_terms" and value["explains_jump"] for value in event["quality_diagnostics"])
