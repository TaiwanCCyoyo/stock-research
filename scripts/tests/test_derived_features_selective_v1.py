"""Invented-input numerical parity and selective dependency regression tests."""

from collections.abc import Iterable
from typing import cast
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from research_core import derived_features_selective_v1 as selective
from research_core.derived_features import compute_features, definition_metadata


def frame(length: int) -> pd.DataFrame:
    close = 100 + 20 * np.sin(np.arange(length) / 7)
    return pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Quality": True, "RawClose": close},
        index=pd.bdate_range("2020-01-01", periods=length, name="calendar"),
    )


@pytest.mark.parametrize("length", [0, 1, 4, 13, 14, 19, 60, 180])
@pytest.mark.parametrize("invalid", [None, "quality", "missing_quality", "missing", "infinite", "negative", "inconsistent"])
def test_exact_parity_for_every_request_and_calendar(length: int, invalid: str | None):
    prepared = frame(length)
    if length > 70 and invalid:
        day = prepared.index[65]
        if invalid == "quality":
            prepared.loc[day, "Quality"] = False
        elif invalid == "missing_quality":
            prepared["Quality"] = prepared["Quality"].astype("boolean")
            prepared.loc[day, "Quality"] = pd.NA
        else:
            prepared.loc[day, "Low"] = {"missing": np.nan, "infinite": np.inf, "negative": -1, "inconsistent": 300}[invalid]
    original = prepared.copy(deep=True)
    expected_daily, expected_pivots = compute_features(prepared)
    requests = [selective.ALL_FEATURES, *[(name,) for name in selective.ALL_FEATURES]]
    for names in requests:
        daily, pivots = selective.compute_selected(prepared, reversed(names))
        columns = [name for name in selective.DAILY_FEATURES if name in names]
        pd.testing.assert_frame_equal(daily, expected_daily.loc[:, columns], check_exact=True)
        ks = [k for name, k in selective.PIVOT_FEATURES.items() if name in names]
        expected = expected_pivots.loc[expected_pivots.k.isin(ks)].reset_index(drop=True)
        pd.testing.assert_frame_equal(pivots, expected, check_exact=True)
    pd.testing.assert_frame_equal(prepared, original, check_exact=True)


def test_equal_extrema_confirmation_and_prefix_availability():
    close = np.r_[np.full(14, 100), 100, 96, 96, 100, 100]
    prepared = frame(len(close))
    for column, offset in (("Open", 0), ("Close", 0), ("High", 1), ("Low", -1)):
        prepared[column] = close + offset
    daily, pivots = selective.compute_selected(prepared, ["pivots_1p5"])
    assert daily.shape == (len(close), 0)
    assert pivots.extreme_index.tolist() == [14, 16]
    assert pivots.confirmation_index.tolist() == [15, 17]
    assert pivots.kind.tolist() == ["high", "low"]
    assert pivots.extreme_date.tolist() == [prepared.index[14], prepared.index[16]]
    assert pivots.confirmed_at.tolist() == [prepared.index[15], prepared.index[17]]
    for length in (1, 13, 14, 15, 16, 17, 18, 19):
        _, prefix = selective.compute_selected(prepared.iloc[:length], ["pivots_1p5"])
        pd.testing.assert_frame_equal(prefix, pivots.loc[pivots.confirmation_index < length].reset_index(drop=True))


@pytest.mark.parametrize(
    "names, forbidden",
    [
        ([], ["_atr", "_pivots", "_selected_convenience", "_ema", "_rolling_mean", "_rolling_std"]),
        (["SMA5"], ["_atr", "_pivots", "_ema", "_rolling_std"]),
        (["EMA10"], ["_atr", "_pivots", "_rolling_mean", "_rolling_std"]),
        (["BB20_Middle"], ["_atr", "_pivots", "_ema", "_rolling_std"]),
        (["BB20_Upper"], ["_atr", "_pivots", "_ema"]),
        (["atr14_pct"], ["_pivots", "_selected_convenience"]),
        (["pivots_4"], ["_selected_convenience", "_ema", "_rolling_mean", "_rolling_std"]),
    ],
)
def test_unrelated_dependencies_never_invoked(monkeypatch: pytest.MonkeyPatch, names: list[str], forbidden: list[str]):
    for helper in forbidden:
        monkeypatch.setattr(selective, helper, Mock(side_effect=AssertionError(f"unnecessary {helper}")))
    daily, pivots = selective.compute_selected(frame(160), names)
    assert daily.columns.tolist() == [name for name in selective.DAILY_FEATURES if name in names]
    if "pivots_4" in names:
        assert not pivots.empty and set(pivots.k) == {4.0}
    else:
        assert pivots.empty


def test_only_requested_periods_and_shared_bollinger_dependencies(monkeypatch: pytest.MonkeyPatch):
    mean = Mock(wraps=selective._rolling_mean)
    ema = Mock(wraps=selective._ema)
    std = Mock(wraps=selective._rolling_std)
    monkeypatch.setattr(selective, "_rolling_mean", mean)
    monkeypatch.setattr(selective, "_ema", ema)
    monkeypatch.setattr(selective, "_rolling_std", std)
    selective.compute_selected(frame(160), ["SMA5", "SMA20", "EMA10", "BB20_Middle", "BB20_Upper", "BB20_Lower"])
    assert [call.args[1] for call in mean.call_args_list] == [5, 20]
    assert [call.args[1] for call in ema.call_args_list] == [10]
    assert std.call_count == 1


def test_pivots_share_atr_and_only_requested_multiplier(monkeypatch: pytest.MonkeyPatch):
    atr = Mock(wraps=selective._atr)
    pivots = Mock(wraps=selective._pivots)
    monkeypatch.setattr(selective, "_atr", atr)
    monkeypatch.setattr(selective, "_pivots", pivots)
    daily, _ = selective.compute_selected(frame(160), ["pivots_1p5", "ATR14", "atr14_pct"])
    assert daily.columns.tolist() == ["ATR14", "atr14_pct"]
    assert atr.call_count == 1
    assert pivots.call_args.args[-1] == (1.5,)


@pytest.mark.parametrize(
    "names, error",
    [
        (["SMA5", "SMA5"], ValueError),
        (["SMA240"], ValueError),
        (["unknown"], ValueError),
        ("SMA5", TypeError),
        ([None], TypeError),
        (None, TypeError),
    ],
)
def test_invalid_requests(names: object, error: type[Exception]):
    with pytest.raises(error):
        # Deliberately send malformed runtime values through the public API.
        selective.compute_selected(frame(10), cast(Iterable[str], names))


@pytest.mark.parametrize("case", ["missing", "unsorted", "duplicate", "timezone", "intraday", "nat", "index", "text", "bool", "duplicate_column"])
def test_prepared_contract_is_validated_even_for_empty_requests(case: str):
    prepared = frame(2)
    if case == "missing":
        prepared = prepared.drop(columns="Quality")
    elif case == "unsorted":
        prepared = prepared.iloc[::-1]
    elif case == "duplicate":
        prepared.index = pd.DatetimeIndex([prepared.index[0]] * 2)
    elif case == "timezone":
        prepared.index = pd.DatetimeIndex(prepared.index).tz_localize("UTC")
    elif case == "intraday":
        prepared.index += pd.Timedelta(hours=1)
    elif case == "nat":
        prepared.index = pd.DatetimeIndex([prepared.index[0], pd.NaT])
    elif case == "index":
        prepared = prepared.reset_index(drop=True)
    elif case == "text":
        prepared["Open"] = "100"
    elif case == "bool":
        prepared["Open"] = True
    elif case == "duplicate_column":
        prepared = pd.concat([prepared, prepared[["Open"]]], axis=1)
    with pytest.raises(ValueError):
        selective.compute_selected(prepared, [])


def test_non_dataframe_rejected():
    with pytest.raises(TypeError):
        selective.compute_selected(cast(pd.DataFrame, None), [])


def test_metadata_preserves_numerical_definitions():
    metadata = selective.definition_metadata()
    original = definition_metadata()
    assert metadata.pop("numerical_definition_version") == original["version"]
    assert metadata.pop("version") == "derived-features-selective.v1"
    original.pop("version")
    assert metadata == original


def test_zero_atr_and_all_invalid_data():
    prepared = frame(160)
    prepared[["Open", "High", "Low", "Close"]] = 100.0
    daily, pivots = selective.compute_selected(prepared, selective.ALL_FEATURES)
    expected, expected_pivots = compute_features(prepared)
    pd.testing.assert_frame_equal(daily, expected.loc[:, list(selective.DAILY_FEATURES)], check_exact=True)
    pd.testing.assert_frame_equal(pivots, expected_pivots)
    np.testing.assert_array_equal(daily["ATR14"].iloc[13:].to_numpy(), np.zeros(len(prepared) - 13))
    assert pivots.empty
    prepared["Quality"] = False
    daily, pivots = selective.compute_selected(prepared, selective.ALL_FEATURES)
    assert np.isnan(daily.to_numpy()).all() and pivots.empty
