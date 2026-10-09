"""Synthetic snapshot-adapter regressions; no market files are read."""

from collections.abc import Sequence
from typing import cast

import numpy as np
import pandas as pd
import pytest

from research_core.feature_atlas_features import compute_features
from research_core.feature_atlas_io import (
    cross_sectional_features,
    market_regime,
    prepare_prices,
    security_inventory,
)


def quotes(close: list[float] | np.ndarray) -> pd.DataFrame:
    values = np.asarray(close, dtype=float)
    return pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=len(values)),
        "Code": "2330",
        "Open": values,
        "High": values * 1.01,
        "Low": values * 0.99,
        "Close": values,
        "Volume": 10.0,
        "Source": "official",
    })


def events(rows: Sequence[tuple[pd.Timestamp, str, float]] = ()) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=pd.Index(["ex_date", "event_type", "price_factor"]))


def prepared(raw: pd.DataFrame, actions: pd.DataFrame | None = None) -> pd.DataFrame:
    return prepare_prices(raw, events() if actions is None else actions, pd.DatetimeIndex(raw.Date.unique()).sort_values())


def test_permanent_split_removes_artificial_jump_and_preserves_raw_turnover():
    raw = quotes([100.0, 100.0, 50.0, 50.0])
    adjusted = prepared(raw, events([(raw.Date.iloc[2], "ETF_SPLIT", 0.5)]))
    assert adjusted.Close.tolist() == [50.0] * 4
    assert adjusted.RawClose.tolist() == [100.0, 100.0, 50.0, 50.0]
    assert adjusted.Turnover.tolist() == [1000.0, 1000.0, 500.0, 500.0]
    assert adjusted.restatement_factor.tolist() == [0.5, 0.5, 1.0, 1.0]
    assert adjusted.Quality.all()
    assert adjusted.quality_reason.isna().all()
    assert prepared(raw).quality_reason.iloc[2] == "unexplained_adjusted_jump"


@pytest.mark.parametrize("kind", ["CASH_DIVIDEND", "EX_RIGHT_AND_DIVIDEND"])
def test_exact_cash_event_explains_negative_jump_without_restating_prices(kind: str):
    raw = quotes([100.0, 100.0, 50.0, 50.0])
    result = prepared(raw, events([(raw.Date.iloc[2], kind, 1.0)]))
    assert result.Quality.all()
    assert result.quality_reason.isna().all()
    assert result.Close.tolist() == raw.Close.tolist()
    assert result.RawClose.tolist() == raw.Close.tolist()
    assert result.restatement_factor.tolist() == [1.0] * 4
    assert result.Turnover.tolist() == [1000.0, 1000.0, 500.0, 500.0]


def test_combined_cash_event_preserves_permanent_factor_and_remaining_decline():
    raw = quotes([100.0, 100.0, 30.0, 30.0])
    result = prepared(raw, events([(raw.Date.iloc[2], "EX_RIGHT_AND_DIVIDEND", 0.8)]))
    assert result.Quality.all()
    assert result.quality_reason.isna().all()
    assert result.Close.tolist() == [80.0, 80.0, 30.0, 30.0]
    assert result.RawClose.tolist() == [100.0, 100.0, 30.0, 30.0]
    assert result.restatement_factor.tolist() == [0.8, 0.8, 1.0, 1.0]
    assert result.Turnover.tolist() == [1000.0, 1000.0, 300.0, 300.0]


@pytest.mark.parametrize("kind", ["CASH_DIVIDEND", "EX_RIGHT_AND_DIVIDEND"])
def test_cash_event_does_not_explain_positive_jump(kind: str):
    raw = quotes([100.0, 100.0, 150.0, 150.0])
    result = prepared(raw, events([(raw.Date.iloc[2], kind, 0.5)]))
    assert not result.Quality.iloc[2]
    assert result.quality_reason.iloc[2] == "unexplained_adjusted_jump"
    assert pd.isna(result.Close.iloc[2])


def test_negative_jump_without_cash_event_remains_unexplained():
    result = prepared(quotes([100.0, 100.0, 50.0, 50.0]))
    assert not result.Quality.iloc[2]
    assert result.quality_reason.iloc[2] == "unexplained_adjusted_jump"


@pytest.mark.parametrize("kind", ["CASH_DIVIDEND", "EX_RIGHT_AND_DIVIDEND"])
def test_noncalendar_cash_event_does_not_explain_next_session_jump(kind: str):
    raw = quotes([100.0, 100.0, 50.0, 50.0])
    raw["Date"] = pd.to_datetime(["2020-01-03", "2020-01-06", "2020-01-08", "2020-01-09"])
    result = prepared(raw, events([(cast(pd.Timestamp, pd.Timestamp("2020-01-07")), kind, 1.0)]))
    assert not result.Quality.iloc[2]
    assert result.quality_reason.iloc[2] == "unexplained_adjusted_jump"


@pytest.mark.parametrize("failure", ["unsupported", "invalid_ohlc", "ambiguous_factor"])
def test_cash_event_never_overrides_other_price_quality_failures(failure: str):
    raw = quotes([100.0, 100.0, 50.0, 50.0])
    day = raw.Date.iloc[2]
    action_rows = [(day, "CASH_DIVIDEND", 0.5)]
    if failure == "unsupported":
        action_rows.append((day, "UNSUPPORTED_TEST_ACTION", 1.0))
        reason = "unsupported_action"
    elif failure == "invalid_ohlc":
        raw.loc[2, "High"] = 49.0
        reason = "invalid_ohlc"
    else:
        action_rows.extend([(day, "ETF_SPLIT", 0.5), (day, "ETF_SPLIT", 0.6)])
        reason = "ambiguous_or_missing_action_factor"
    result = prepared(raw, events(action_rows))
    assert not result.Quality.iloc[2]
    assert reason in result.quality_reason.iloc[2]
    assert result.loc[day, ["Open", "High", "Low", "Close", "Turnover"]].isna().all()
    assert result.RawClose.iloc[2] == 50.0


def test_future_common_factor_preserves_past_ratio_features():
    raw = quotes(100 + np.arange(180, dtype=float) * 0.2)
    baseline = prepared(raw)
    adjusted = prepared(raw, events([(raw.Date.iloc[170], "ETF_SPLIT", 0.5)]))
    pd.testing.assert_frame_equal(
        compute_features(baseline.iloc[:170]),
        compute_features(adjusted.iloc[:170]),
        atol=1e-10,
        rtol=1e-10,
    )
    assert (adjusted.Close.iloc[:170] == baseline.Close.iloc[:170] * 0.5).all()
    pd.testing.assert_series_equal(adjusted.Turnover.iloc[:170], baseline.Turnover.iloc[:170])


@pytest.mark.parametrize(
    ("action_rows", "reason"),
    [
        ([("ETF_SPLIT", np.nan)], "ambiguous_or_missing_action_factor"),
        ([("ETF_SPLIT", 0)], "ambiguous_or_missing_action_factor"),
        ([("ETF_SPLIT", 0.5), ("ETF_SPLIT", 0.6)], "ambiguous_or_missing_action_factor"),
        ([("ETF_SPLIT", 0.5), ("EX_RIGHT", 0.5)], "ambiguous_or_missing_action_factor"),
        ([("UNSUPPORTED_TEST_ACTION", 1.0)], "unsupported_action"),
    ],
)
def test_unusable_actions_make_explicit_price_gaps(action_rows: list[tuple[str, float]], reason: str):
    raw = quotes([100.0] * 5)
    day = raw.Date.iloc[2]
    result = prepared(raw, events([(day, kind, factor) for kind, factor in action_rows]))
    assert not result.Quality.iloc[2]
    assert reason in result.quality_reason.iloc[2]
    assert result.loc[day, ["Open", "High", "Low", "Close", "Turnover"]].isna().all()
    assert result.RawClose.iloc[2] == 100


def test_missing_quote_duplicate_and_bad_ohlc_are_separate_quality_states():
    raw = quotes([100.0] * 6)
    calendar = pd.DatetimeIndex(raw.Date)
    raw.loc[2, "High"] = 99
    raw.loc[3, "Low"] = 101
    raw.loc[4, "Close"] = 0
    raw = pd.concat([raw.drop(index=1), raw.iloc[[0]]], ignore_index=True)
    result = prepare_prices(raw, events(), calendar)
    assert "duplicate_date" in result.quality_reason.iloc[0]
    assert result.quality_reason.iloc[1] == "missing_official_quote"
    assert result.quality_reason.iloc[2:5].tolist() == ["invalid_ohlc"] * 3
    assert result.Close.iloc[:5].isna().all()
    assert result.Quality.iloc[5]


def test_zero_volume_is_observed_zero_and_missing_volume_is_unknown():
    raw = quotes([100.0] * 5)
    raw["Volume"] = [0, np.nan, -1, np.inf, 10]
    result = prepared(raw)
    assert result.Quality.all()
    assert result.volume_status.tolist() == ["zero", "missing_or_invalid", "missing_or_invalid", "missing_or_invalid", "observed"]
    assert result.Turnover.iloc[0] == 0
    assert result.VolumeLots.iloc[0] == 0
    assert result.Turnover.iloc[1:4].isna().all()
    assert result.Close.notna().all()
    assert result.Turnover.iloc[4] == 1000


def test_security_inventory_keeps_reference_labels_and_excluded_names():
    prices = pd.DataFrame({"Code": ["2330", "6488", "0050", "9999"]})
    metadata = pd.DataFrame([
        {
            "code": "2330",
            "name": "Ordinary TWSE",
            "market": "TWSE",
            "is_etf": 0,
            "security_category": "股票",
            "industry_category": "semiconductor",
            "fetched_at": "2026-01-01",
        },
        {"code": "6488", "name": np.nan, "market": "上櫃", "is_etf": 0, "security_category": "股票", "industry_category": np.nan},
        {"code": "0050", "name": "Excluded ETF", "market": "上市", "is_etf": 1, "security_category": "ETF", "industry_category": None},
        {"code": "1234", "name": "No window quotes", "market": "上市", "is_etf": 0, "security_category": "股票", "industry_category": "other"},
    ])
    inventory = {row["code"]: row for row in security_inventory(prices, metadata)}
    assert inventory["2330"]["included"]
    assert inventory["6488"]["included"]
    assert inventory["6488"]["industry_ref"] == "unknown"
    assert inventory["6488"]["name"] is None
    assert inventory["0050"]["exclusion_reason"] == "not_ordinary_reference"
    assert inventory["0050"]["name"] == "Excluded ETF"
    assert inventory["1234"]["exclusion_reason"] == "no_official_prices_in_window"
    assert inventory["9999"]["exclusion_reason"] == "metadata_unavailable"
    assert all(row["classification_basis"] == "current_metadata_reference" for row in inventory.values())
    assert not any(row["historical_membership_known"] for row in inventory.values())


def test_contemporaneous_ranks_do_not_filter_on_future_outcomes():
    day, next_day = pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-02")
    frame = pd.DataFrame({
        "asof_date": [day] * 6 + [next_day],
        "ret20": [1, 2, 3, 4, 100, np.nan, 10],
        "ret60": [1, 2, 3, 4, 100, np.nan, 10],
        "base_eligible": [True, True, True, True, False, True, True],
        "label_63": [np.nan, 0, 1, 1, 1, 0, 1],
        "label_126": [np.nan] * 7,
    })
    benchmark = pd.Series([2.0], index=[day])
    result = cross_sectional_features(frame, benchmark)
    assert result.rs20_percentile.iloc[:4].tolist() == [0.25, 0.5, 0.75, 1.0]
    assert result.rs60_percentile.iloc[:4].tolist() == [0.25, 0.5, 0.75, 1.0]
    assert result.F36.iloc[:4].tolist() == [0, 0, 0, 1]
    assert result.F37.iloc[:4].tolist() == [0, 0, 0, 1]
    assert result.F36.iloc[4:6].isna().all()
    assert result.rs20_percentile.iloc[6] == 1
    assert result.F38.iloc[:4].tolist() == [0, 0, 1, 1]
    assert pd.isna(result.F38.iloc[6])
    changed = frame.copy()
    changed["label_63"] = 0
    changed["label_126"] = 1
    pd.testing.assert_frame_equal(result, cross_sectional_features(changed, benchmark))


def test_tied_contemporaneous_ranks_use_average_percentile():
    day = pd.Timestamp("2020-01-01")
    frame = pd.DataFrame({"asof_date": [day] * 3, "ret20": [1, 2, 2], "ret60": [1, 2, 2], "base_eligible": True})
    result = cross_sectional_features(frame, pd.Series([0], index=[day]))
    assert result.rs20_percentile.tolist() == pytest.approx([1 / 3, 2.5 / 3, 2.5 / 3])


def test_market_regime_keeps_mixed_boundaries_and_unknowns():
    frame = pd.DataFrame(
        {
            "dist_ma60": [1, -1, 1, -1, 0, 1, np.nan],
            "ma60_slope20": [1, -1, -1, 1, 1, np.nan, 1],
        },
        index=pd.Index(list("abcdefg")),
    )
    result = market_regime(frame)
    assert result.tolist() == ["up", "down", "mixed", "mixed", "mixed", "unknown", "unknown"]
    pd.testing.assert_index_equal(result.index, frame.index)
