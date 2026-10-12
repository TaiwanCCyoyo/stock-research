"""Invented calendars verify immutable decisions and exact replay parity."""

from typing import Any, cast
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from research_core import research_data_extension as extension
from research_core.derived_features_selective_v1 import ALL_FEATURES, compute_selected


def frame(seed: int = 0, length: int = 180) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 2, length))
    return pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Quality": True},
        index=pd.bdate_range("2020-01-01", periods=length, name="calendar"),
    )


@pytest.mark.parametrize("seed", [0, 7, 33])
@pytest.mark.parametrize("cut", [0, 1, 13, 14, 60, 179, 180])
@pytest.mark.parametrize("gap", [None, 59, 60])
def test_exact_replay_parity_without_input_mutation(seed: int, cut: int, gap: int | None):
    prepared = frame(seed)
    if gap is not None:
        prepared.loc[prepared.index[gap], "Quality"] = False
    old = prepared.iloc[:cut].copy(deep=True)
    old_daily, old_pivots = compute_selected(old, ALL_FEATURES)
    snapshots = [item.copy(deep=True) for item in (old, prepared, old_daily, old_pivots)]
    daily, pivots, receipt = extension.extend_selected(old, prepared, old_daily, old_pivots, ALL_FEATURES)
    expected_daily, expected_pivots = compute_selected(prepared, ALL_FEATURES)
    pd.testing.assert_frame_equal(daily, expected_daily, check_exact=True)
    pd.testing.assert_frame_equal(pivots, expected_pivots, check_exact=True)
    assert receipt["mode"] == "exact_state_replay"
    assert receipt["state_replay_rows"] == len(prepared)
    assert receipt["verification_replay_rows"] == cut
    assert receipt["appended_rows"] == len(prepared) - cut
    for original, snapshot in zip((old, prepared, old_daily, old_pivots), snapshots):
        pd.testing.assert_frame_equal(original, snapshot, check_exact=True)


def test_old_extreme_new_confirmation_retains_global_positions():
    prepared = frame(length=19)
    close = np.r_[np.full(14, 100), 100, 96, 96, 100, 100]
    for column, offset in (("Open", 0), ("Close", 0), ("High", 1), ("Low", -1)):
        prepared[column] = close + offset
    old = prepared.iloc[:15]
    old_daily, old_pivots = compute_selected(old, ["pivots_1p5"])
    daily, pivots, receipt = extension.extend_selected(old, prepared, old_daily, old_pivots, ["pivots_1p5"])
    expected_daily, expected_pivots = compute_selected(prepared, ["pivots_1p5"])
    pd.testing.assert_frame_equal(daily, expected_daily, check_exact=True)
    pd.testing.assert_frame_equal(pivots, expected_pivots, check_exact=True)
    assert pivots.extreme_index.tolist() == [14, 16]
    assert pivots.confirmation_index.tolist() == [15, 17]
    assert receipt["appended_pivots"] == 2


@pytest.mark.parametrize("correction", ["price", "calendar", "truncate", "dtype", "extra_column"])
def test_history_correction_requires_rebuild_and_rejects_append(correction: str):
    old = frame(length=30)
    new = frame(length=40)
    if correction == "price":
        new.iloc[2, new.columns.get_loc("Close")] += 0.1
    elif correction == "calendar":
        new = pd.concat([new.iloc[:2], new.iloc[3:]])
    elif correction == "truncate":
        new = old.iloc[:20]
    elif correction == "dtype":
        new["Quality"] = new["Quality"].astype("boolean")
    else:
        new["RawClose"] = new["Close"]
    plan = extension.plan_extension({"A": old}, {"A": new}, {}, {})
    assert plan["stocks"]["A"]["action"] == "rebuild_stock"
    old_daily, old_pivots = compute_selected(old, ["EMA10"])
    with pytest.raises(ValueError, match="exact historical"):
        extension.extend_selected(old, new, old_daily, old_pivots, ["EMA10"])


def test_classification_factor_definition_new_stock_and_label_tail():
    old = frame(length=30)
    new = frame(length=40)
    originals = [item.copy(deep=True) for item in (old, new)]
    plan = extension.plan_extension({"A": old, "B": old}, {"A": new, "B": old, "C": new}, {}, {}, retrospective_tail=10)
    assert {code: info["action"] for code, info in plan["stocks"].items()} == {"A": "append", "B": "unchanged", "C": "append"}
    assert plan["stocks"]["A"]["old_rows"] == 30
    assert plan["stocks"]["A"]["new_rows"] == 40
    assert plan["stocks"]["A"]["tail_start"] == 20
    assert plan["stocks"]["C"]["tail_start"] == 0
    for tail, start in ((0, 30), (252, 0)):
        result = extension.plan_extension({"A": old}, {"A": new}, {}, {}, retrospective_tail=tail)
        assert result["stocks"]["A"]["tail_start"] == start
    factor = extension.plan_extension({"A": old}, {"A": new}, {}, {}, factor_changed=["A"])
    assert factor["stocks"]["A"]["action"] == "rebuild_stock"
    assert factor["stocks"]["A"]["reason"] == "factor_changed"
    definition = extension.plan_extension({"A": old}, {"A": new, "C": new}, {"v": 1}, {"v": 2})
    assert definition["definition_changed"]
    assert all(info["action"] == "rebuild_all_definition" for info in definition["stocks"].values())
    for actual, original in zip((old, new), originals):
        pd.testing.assert_frame_equal(actual, original, check_exact=True)


def test_deletion_and_invalid_calendars_are_rejected():
    old = frame(length=3)
    with pytest.raises(ValueError, match="deletion"):
        extension.plan_extension({"A": old}, {}, {}, {})
    with pytest.raises(ValueError, match="calendar"):
        extension.plan_extension({}, {"A": old.iloc[::-1]}, {}, {})
    with pytest.raises(ValueError, match="calendar"):
        extension.plan_extension({"A": old}, {"A": pd.concat([old, old.iloc[-1:]])}, {}, {})
    for tail in (-1, True, 2.5):
        with pytest.raises(ValueError, match="retrospective_tail"):
            extension.plan_extension({}, {}, {}, {}, retrospective_tail=cast(Any, tail))
    with pytest.raises(ValueError, match="unknown stock"):
        extension.plan_extension({}, {}, {}, {}, factor_changed=["unknown"])


@pytest.mark.parametrize("corruption", ["daily_value", "daily_column", "pivot_value", "pivot_order"])
def test_old_outputs_are_verified_before_extension(corruption: str):
    old = frame(length=160)
    daily, pivots = compute_selected(old, ALL_FEATURES)
    assert len(pivots) > 1
    if corruption == "daily_value":
        daily.iloc[-1, 0] += 1
    elif corruption == "daily_column":
        daily = daily.drop(columns="EMA5")
    elif corruption == "pivot_value":
        pivots.loc[0, "price"] += 1
    else:
        pivots = pivots.iloc[::-1].reset_index(drop=True)
    with pytest.raises(ValueError, match="old outputs differ"):
        extension.extend_selected(old, old, daily, pivots, ALL_FEATURES)


def test_addition_computes_only_missing_columns(monkeypatch: pytest.MonkeyPatch):
    prepared = frame()
    existing, _ = compute_selected(prepared, ["EMA10", "SMA5"])
    original = existing.copy(deep=True)
    compute = Mock(wraps=compute_selected)
    monkeypatch.setattr(extension, "compute_selected", compute)
    daily, pivots, receipt = extension.add_selected(prepared, existing, ["SMA5", "EMA10", "ATR14", "pivots_4"])
    assert [call.args[1] for call in compute.call_args_list] == [[], ["ATR14", "pivots_4"]]
    expected_daily, expected_pivots = compute_selected(prepared, ["SMA5", "EMA10", "ATR14", "pivots_4"])
    pd.testing.assert_frame_equal(daily, expected_daily, check_exact=True)
    pd.testing.assert_frame_equal(pivots, expected_pivots, check_exact=True)
    pd.testing.assert_frame_equal(existing, original, check_exact=True)
    assert receipt["computed_features"] == ["ATR14", "pivots_4"]
    assert receipt["reused_features"] == ["SMA5", "EMA10"]
    assert not receipt["reused_values_verified"]


@pytest.mark.parametrize("corruption", ["unknown", "duplicate", "calendar", "dtype"])
def test_addition_rejects_bad_schema_without_silent_repair(corruption: str):
    prepared = frame()
    existing, _ = compute_selected(prepared, ["SMA5"])
    if corruption == "unknown":
        existing["unrecognized"] = 1.0
    elif corruption == "duplicate":
        existing = pd.concat([existing, existing], axis=1)
    elif corruption == "calendar":
        existing = existing.iloc[:-1]
    else:
        existing["SMA5"] = "bad"
    with pytest.raises(ValueError):
        extension.add_selected(prepared, existing, ["EMA10"])


def test_feature_validation_and_compute_failure_propagate(monkeypatch: pytest.MonkeyPatch):
    prepared = frame()
    existing, _ = compute_selected(prepared, ["SMA5"])
    for request in (["EMA10", "EMA10"], ["unknown"]):
        with pytest.raises(ValueError):
            extension.add_selected(prepared, existing, request)
    with pytest.raises(TypeError):
        extension.add_selected(prepared, existing, "EMA10")
    failure = Mock(side_effect=OSError("fixture read failure"))
    monkeypatch.setattr(extension, "compute_selected", failure)
    with pytest.raises(OSError, match="fixture read failure"):
        extension.add_selected(prepared, existing, ["EMA10"])
