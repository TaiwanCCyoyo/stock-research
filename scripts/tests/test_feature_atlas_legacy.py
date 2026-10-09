"""Hand-checked legacy components without loading a strategy or broker."""

import numpy as np
import pandas as pd
import pytest

from research_core.feature_atlas_legacy import _segment, compute_legacy_features


def bars(close: list[float] | np.ndarray) -> pd.DataFrame:
    values = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {"Open": values, "High": values + 2, "Low": values - 2, "Close": values},
        index=pd.date_range("2020-01-01", periods=len(values)),
    )


def bottom_fixture() -> pd.DataFrame:
    frame = bars([100.0] * 28)
    frame.loc[:, "Low"] = 90.0
    frame.loc[frame.index[20], "Low"] = 89.0
    return frame


@pytest.mark.parametrize("length", [1, 3, 14, 19])
def test_skipped_short_segments_equal_original_calculation(length: int):
    frame = bars(np.linspace(90.0, 110.0, length))
    actual = compute_legacy_features(frame)
    expected = _segment(frame)
    pd.testing.assert_frame_equal(actual, expected[actual.columns])


def test_new_low_does_not_reclaim_same_day_and_signal_is_consumed():
    result = compute_legacy_features(bottom_fixture())
    assert result.F33.iloc[:20].isna().all()
    assert result.F33.iloc[20:24].tolist() == [0.0, 1.0, 0.0, 0.0]


@pytest.mark.parametrize("reclaim_bar, expected", [(25, 1.0), (26, 0.0)])
def test_fifth_later_bar_reclaims_before_expiry_but_sixth_is_too_late(reclaim_bar: int, expected: float):
    frame = bottom_fixture()
    frame.loc[frame.index[21:reclaim_bar], ["Open", "Close"]] = 90.0
    result = compute_legacy_features(frame)
    assert result.F33.iloc[21:reclaim_bar].eq(0).all()
    assert result.F33.iloc[reclaim_bar] == expected


def test_new_strict_low_replaces_pending_level_and_restarts_expiry():
    frame = bottom_fixture()
    frame.loc[frame.index[21:27], ["Open", "Close"]] = 89.0
    frame.loc[frame.index[21], "Low"] = 89.0
    frame.loc[frame.index[22], "Low"] = 88.0
    frame.loc[frame.index[23:27], "Low"] = 89.0
    frame.loc[frame.index[27], ["Open", "Close"]] = 89.5
    result = compute_legacy_features(frame)
    assert result.F33.iloc[20:27].eq(0).all()
    # Below the original level 90, but above the replacement level 89;
    # index 27 is the fifth later bar since the replacement at index 22.
    assert result.F33.iloc[27] == 1.0


def test_sma_fraction_convergence_and_current_inclusive_trend_window():
    frame = bars([100.0] * 20)
    result = compute_legacy_features(frame)
    assert result.F34.iloc[:19].isna().all()
    assert result.F35.iloc[:19].isna().all()
    assert result.ma_convergence_fraction.iloc[:19].isna().all()
    assert result.ma_convergence_fraction.iloc[19] == 0
    assert pd.isna(result.F33.iloc[19])
    assert result.F34.iloc[19] == 1
    assert result.F35.iloc[19] == 1
    frame = bars([101.0] + [100.0] * 19)
    result = compute_legacy_features(frame)
    assert result.ma_convergence_fraction.iloc[-1] == pytest.approx(0.0005)
    assert result.F34.iloc[-1] == 1
    assert result.F35.iloc[-1] == 0


def test_convergence_threshold_is_inclusive():
    result = compute_legacy_features(bars([104.0] * 10 + [100.0] * 10))
    assert result.ma_convergence_fraction.iloc[-1] == 0.02
    assert result.F34.iloc[-1] == 1
    assert result.F35.iloc[-1] == 0
    frame = bars([100.0] * 19 + [140.0])
    result = compute_legacy_features(frame)
    assert result.ma_convergence_fraction.iloc[-1] == pytest.approx(6 / 140)
    assert result.F34.iloc[-1] == 0
    assert result.F35.iloc[-1] == 0


def test_prefix_and_positive_scale_invariance_and_input_preservation():
    rng = np.random.default_rng(17)
    frame = bars(100 + np.cumsum(rng.normal(0, 1, 90)))
    original = frame.copy(deep=True)
    full = compute_legacy_features(frame)
    for end in (19, 20, 21, 25, 70):
        pd.testing.assert_frame_equal(compute_legacy_features(frame.iloc[:end]), full.iloc[:end])
    pd.testing.assert_frame_equal(compute_legacy_features(frame * 7.3), full, atol=1e-12, rtol=1e-12)
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("column", ["Open", "High", "Low", "Close"])
def test_partial_ohlc_gap_resets_pending_and_full_warmup(column: str):
    frame = bars([100.0] * 50)
    frame.loc[:, "Low"] = 90.0
    frame.loc[frame.index[20], "Low"] = 89.0
    frame.loc[frame.index[21], column] = np.nan
    result = compute_legacy_features(frame)
    assert result.iloc[21].isna().all()
    pd.testing.assert_frame_equal(result.iloc[22:], compute_legacy_features(frame.iloc[22:]))
    assert result.F33.iloc[22:42].isna().all()
    assert result.F33.iloc[42] == 0
    assert result.F34.iloc[22:41].isna().all()
    assert result.F34.iloc[41] == 1
    assert result.F35.iloc[41] == 1


def test_invalid_index_or_prices_and_empty_input():
    frame = bars([100.0, 101.0])
    with pytest.raises(ValueError, match="sorted unique"):
        compute_legacy_features(frame.iloc[::-1])
    for value in (0.0, -1.0, np.inf):
        invalid = frame.copy()
        invalid.loc[invalid.index[0], "Close"] = value
        with pytest.raises(ValueError, match="positive"):
            compute_legacy_features(invalid)
    assert compute_legacy_features(frame.iloc[:0]).empty
