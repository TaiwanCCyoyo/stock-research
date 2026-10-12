"""Synthetic fixed-inventory flag aggregation and unknown cost regressions."""

from typing import cast

import pandas as pd
import pytest

from research_core.hhhl_variants_flag_summary import FlagSummaries


def _record(**overrides: object) -> dict:
    return {
        "cohort_id": "P-clean",
        "split_id": "development",
        "year": 2020,
        "code": "0001",
        "event_id": "e1",
        "flag_id": "X2",
        "landmark": 5,
        "horizon": 126,
        "calendar_full": True,
        "label": "hit",
        "riskset_eligible": True,
        "raw_flag_state": "triggered",
        "flag_state": "triggered",
        "rise_bin": "lt1",
        "trigger_return": -0.2,
        **overrides,
    }


def _pooled(frame: pd.DataFrame, kind: str, **filters: object) -> pd.Series:
    mask = (
        frame["row_kind"].eq(kind)
        & frame["flag_id"].eq("X2")
        & frame["landmark"].eq(5)
        & frame["horizon"].eq(126)
        & frame["split_id"].eq("development")
        & frame["cohort_id"].eq("P-clean")
    )
    for name, value in filters.items():
        mask &= frame[name].eq(value)
    return cast(pd.Series, cast(pd.DataFrame, frame.loc[mask]).iloc[0])


def test_zero_inventory_has_every_prescribed_cell() -> None:
    result = FlagSummaries().finalize()
    assert result["row_kind"].eq("flag").sum() == 5760
    assert result["row_kind"].eq("reverse_flag").sum() == 480
    assert len(result) == 62400
    assert result["known_n"].sum() == 0
    assert cast(pd.Series, result["hit_rate"]).isna().to_numpy(dtype=bool).all()
    full = cast(pd.DataFrame, result[result["row_kind"].eq("reverse_flag") & result["scope"].eq("full")])
    assert cast(pd.Series, full["landmark"]).equals(cast(pd.Series, full["horizon"]))


def test_early_hit_is_reverse_denominator_without_new_riskset() -> None:
    accumulator = FlagSummaries()
    accumulator.add_flags(pd.DataFrame([_record(riskset_eligible=False, raw_flag_state="triggered", flag_state="all_false")]))
    result = accumulator.finalize()
    reverse = _pooled(result, "reverse_flag")
    assert reverse["hit_n"] == reverse["hit_flag_all_false_n"] == 1
    assert reverse["cost_denominator_n"] == 1 and reverse["cost_lower"] == 0
    assert result.loc[result["row_kind"].eq("flag"), "known_n"].sum() == 0
    assert reverse["trigger_return_n"] == 0


def test_unknown_hit_flag_widens_all_hit_cost_and_nonhits_include_flat_win() -> None:
    accumulator = FlagSummaries()
    accumulator.add_flags(
        pd.DataFrame([
            _record(),
            _record(event_id="e2", code="0002", flag_state="unknown", raw_flag_state="unknown", trigger_return=None),
            _record(event_id="e3", code="0003", label="flat-win", flag_state="all_false", raw_flag_state="all_false"),
            _record(event_id="e4", code="0004", label="loss"),
            _record(event_id="e5", code="0005", label="unknown", flag_state="unknown", raw_flag_state="unknown"),
        ])
    )
    reverse = _pooled(accumulator.finalize(), "reverse_flag")
    assert reverse["hit_flag_known_rate"] == 1
    assert reverse["cost_denominator_n"] == 2
    assert reverse["cost_lower"] == 0.5 and reverse["cost_upper"] == 1
    assert reverse["nonhit_flag_all_n"] == 2 and reverse["nonhit_flag_known_rate"] == 0.5
    assert reverse["excluded_unknown_label_n"] == 1 and reverse["unknown_n"] == 0
    assert reverse["known_security_n"] == 4
    assert reverse["flag_triggered_n"] == 2
    assert reverse["flag_all_false_n"] == reverse["flag_unknown_n"] == 1
    assert reverse["flag_denominator_n"] == 4
    assert cast(bool, pd.isna(reverse["riskset_n"]))
    assert reverse["feature_price_basis"] == "frozen_v4_factor"


def test_rise_groups_censoring_and_raw_state_use_fixed_target() -> None:
    accumulator = FlagSummaries()
    accumulator.add_flags(
        pd.DataFrame([
            _record(label="loss", rise_bin="lt1"),
            _record(event_id="e2", label="flat-win", rise_bin="b1_1p10", flag_state="all_false", raw_flag_state="all_false"),
            _record(event_id="e3", calendar_full=False, label="unknown", rise_bin="lt1"),
        ])
    )
    result = accumulator.finalize()
    triggered = _pooled(result, "flag", flag_state="triggered", return_bin="pooled")
    assert triggered["loss_n"] == 1 and triggered["censored_n"] == 1
    assert triggered["riskset_n"] == triggered["flag_denominator_n"] == triggered["flag_triggered_n"] == 2
    assert triggered["flag_all_false_n"] == triggered["flag_unknown_n"] == 0
    lt1 = _pooled(result, "flag", flag_state="triggered", return_bin="lt1")
    assert lt1["known_n"] == 1
    winning = _pooled(result, "flag", flag_state="all_false", return_bin="b1_1p10")
    assert winning["flat_win_n"] == 1
    reverse = _pooled(result, "reverse_flag")
    assert reverse["excluded_censored_n"] == 1 and reverse["censored_n"] == 0


def test_drop_best_year_removes_entire_year_and_return_values() -> None:
    accumulator = FlagSummaries()
    accumulator.add_flags(
        pd.DataFrame([
            _record(year=2020, trigger_return=-0.1),
            _record(event_id="e2", year=2020, code="0002", trigger_return=None),
            _record(event_id="e3", year=2021, code="0003", trigger_return=-0.3),
            _record(event_id="e4", year=2021, code="0004", label="loss", trigger_return=-0.5),
        ])
    )
    result = accumulator.finalize()
    reverse = _pooled(result, "reverse_flag")
    assert reverse["trigger_return_n"] == 3 and reverse["trigger_return_unknown_n"] == 1
    assert reverse["trigger_return_median"] == pytest.approx(-0.3)
    assert reverse["trigger_return_p10"] == pytest.approx(-0.46)
    drop = _pooled(result, "drop_best_year", base_row_kind="reverse_flag")
    assert drop["removed_year"] == 2020 and drop["hit_n"] == 1
    assert drop["trigger_return_n"] == 2 and drop["trigger_return_unknown_n"] == 0
    assert drop["trigger_return_median"] == pytest.approx(-0.4)
    year = _pooled(result, "year", base_row_kind="reverse_flag", year=2020)
    assert year["trigger_return_n"] == year["trigger_return_unknown_n"] == 1
    assert year["flag_denominator_n"] == 2 and drop["flag_denominator_n"] == 2


def test_controls_and_invalid_full_scope_are_rejected_before_mutation() -> None:
    accumulator = FlagSummaries()
    with pytest.raises(ValueError, match="P cohort"):
        accumulator.add_flags(pd.DataFrame([_record(), _record(cohort_id="C-nh")]))
    with pytest.raises(ValueError, match="inventory"):
        accumulator.add_flags(pd.DataFrame([_record(landmark=252, horizon=126)]))
    assert accumulator.finalize()["known_n"].sum() == 0
