"""Invented calendar/OHLC tests; no published artifacts are read."""

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core.derived_features import compute_features
from research_core.hhhl_variants_daily import bin_columns, bin_values, calculate_daily_features
from research_core.hhhl_variants_features import FEATURES, classify_feature
from research_core.hhhl_variants_observations import previous_completed_week_signal


def frames(count: int = 330, start: str = "2020-01-06"):
    dates = pd.bdate_range(start, periods=count)
    close = 100 + np.arange(count, dtype=float) / 10
    raw = pd.DataFrame({"Date": dates, "Open": close, "High": close + 1, "Low": close - 1, "Close": close, "VolumeLots": np.arange(count) + 100})
    adjusted = raw.loc[:, ["Date", "Open", "High", "Low", "Close"]].copy()
    return raw, adjusted


def calculate(raw: pd.DataFrame, adjusted: pd.DataFrame):
    return calculate_daily_features(raw, adjusted, np.full(len(raw), 1.7), np.ones(len(raw), dtype=bool))


def test_daily_formulas_windows_and_input_preservation():
    raw, adjusted = frames()
    original = raw.copy(deep=True)
    adjusted_original = adjusted.copy(deep=True)
    result = calculate(raw, adjusted)
    prepared = adjusted.drop(columns="Date").set_axis(pd.DatetimeIndex(raw.Date))
    prepared["Quality"] = True
    shared, _ = compute_features(prepared)
    np.testing.assert_allclose(result.atr_pct, shared.atr14_pct, equal_nan=True)
    assert result.C.iloc[:239].isna().all()
    assert result.C.iloc[239] == 4
    assert result.C2.iloc[:259].isna().all()
    assert result.C2.iloc[259] == pytest.approx(raw.Close.iloc[20:260].mean() / raw.Close.iloc[:240].mean() - 1)
    assert result.C3.iloc[239] == pytest.approx(raw.Close.iloc[239] / raw.Close.iloc[:240].mean() - 1)
    assert result.D.iloc[:250].isna().all()
    assert result.D.iloc[250] == pytest.approx(raw.Close.iloc[250] / raw.Close.iloc[:250].max())
    assert result.D2.iloc[250] == pytest.approx(raw.Close.iloc[250] / raw.Close.iloc[:250].min())
    assert result.ret120.iloc[:120].isna().all()
    assert result.ret120.iloc[120] == pytest.approx(raw.Close.iloc[120] / raw.Close.iloc[0] - 1)
    assert result.F.iloc[:133].isna().all()
    assert result.F.iloc[133] == pytest.approx(result.atr_pct.iloc[132] / result.atr_pct.iloc[13:133].median())
    assert result.prior_volume20.iloc[20] == pytest.approx(raw.VolumeLots.iloc[:20].mean())
    assert result.turnover20.iloc[20] == pytest.approx((raw.Close * raw.VolumeLots).iloc[:20].mean())
    assert (result.G == 1.7).all()
    pd.testing.assert_frame_equal(raw, original)
    pd.testing.assert_frame_equal(adjusted, adjusted_original)


def test_gap_resets_full_daily_windows_and_preserves_legacy_vx():
    raw, adjusted = frames(560)
    raw.loc[260, ["Open", "High", "Low", "Close"]] = np.nan
    adjusted.loc[260, ["Open", "High", "Low", "Close"]] = np.nan
    result = calculate(raw, adjusted)
    assert result.atr_pct.iloc[260:274].isna().all()
    assert pd.notna(result.atr_pct.iloc[274])
    assert result.ma20.iloc[260:280].isna().all()
    assert pd.notna(result.ma20.iloc[280])
    assert result.ret120.iloc[260:381].isna().all()
    assert pd.notna(result.ret120.iloc[381])
    assert result.D.iloc[260:511].isna().all()
    assert pd.notna(result.D.iloc[511])
    assert result.C2.iloc[260:520].isna().all()
    assert pd.notna(result.C2.iloc[520])
    assert result.F.iloc[261:394].isna().all()
    assert pd.notna(result.F.iloc[394])
    assert result.G.iloc[260] == 1.7
    assert pd.isna(result.G2_limit.iloc[260])
    assert pd.isna(result.G2_limit.iloc[261])
    assert result.turnover20.iloc[261:281].isna().all()
    assert pd.notna(result.turnover20.iloc[281])


def test_missing_high_resets_turnover_warmup_even_with_observed_raw_close():
    raw, adjusted = frames(95)
    raw.loc[40, "High"] = np.nan
    adjusted.loc[40, "High"] = np.nan
    result = calculate(raw, adjusted)
    # These use the previous 20 complete quotes, so the gap enters at t+1.
    assert pd.notna(result.turnover20.iloc[40])
    assert result.turnover20.iloc[41:61].isna().all()
    assert result.prior_volume20.iloc[41:61].isna().all()
    assert result.turnover20.iloc[61] == pytest.approx((raw.Close * raw.VolumeLots).iloc[41:61].mean())
    assert result.prior_volume20.iloc[61] == pytest.approx(raw.VolumeLots.iloc[41:61].mean())
    assert result.K.iloc[40:54].isna().all()
    assert pd.notna(result.K.iloc[54])
    assert result.K2.iloc[40] == raw.Close.iloc[40]
    assert result.G.iloc[40] == 1.7


@pytest.mark.parametrize("start", ["2020-01-06", "2020-01-08"])
def test_weekly_vectorization_matches_reference_on_every_day(start: str):
    raw, adjusted = frames(135, start)
    raw.loc[73, ["Open", "High", "Low", "Close"]] = np.nan
    adjusted.loc[73, ["Open", "High", "Low", "Close"]] = np.nan
    # Remove a whole holiday week: observed weeks stay consecutive.
    holiday = raw.Date.between("2020-02-03", "2020-02-07")
    raw, adjusted = raw.loc[~holiday].reset_index(drop=True), adjusted.loc[~holiday].reset_index(drop=True)
    result = calculate(raw, adjusted)
    dates: list[date] = [day.date() for day in raw.Date]
    closes = [None if pd.isna(value) else float(value) for value in raw.Close]
    for i, actual in enumerate(result.C4):
        expected = previous_completed_week_signal(dates, closes, i)
        assert pd.isna(actual) if expected is None else bool(actual) == expected


def test_weekly_friday_excludes_current_week_and_constant_is_false():
    raw, adjusted = frames(70)
    raw.loc[:, "Close"] = 100.0
    raw.loc[:, "Open"] = 100.0
    raw.loc[:, "High"] = 101.0
    raw.loc[:, "Low"] = 99.0
    adjusted.loc[:, ["Open", "High", "Low", "Close"]] = raw.loc[:, ["Open", "High", "Low", "Close"]]
    result = calculate(raw, adjusted)
    assert result.C4.iloc[:55].isna().all()
    assert not bool(result.C4.iloc[55])
    adjusted.loc[59, ["Open", "Close", "High", "Low"]] = [200, 200, 201, 199]
    changed = calculate(raw, adjusted)
    assert not bool(changed.C4.iloc[59])
    assert bool(changed.C4.iloc[60])


def test_raw_limit_adjusted_position_zero_spread_and_zero_atr():
    raw, adjusted = frames(145)
    raw.loc[1, "Close"] = raw.Close.iloc[0] * 1.10
    adjusted.loc[1, ["Open", "Close", "High", "Low"]] = [101, 101, 102, 98]
    adjusted.loc[2, ["Open", "Close", "High", "Low"]] = [100, 100, 100, 100]
    result = calculate(raw, adjusted)
    assert bool(result.G2_limit.iloc[1])
    assert bool(result.G2_position.iloc[1])
    assert pd.isna(result.G2_position.iloc[2])
    adjusted.loc[:, ["Open", "Close", "High", "Low"]] = 100.0
    zero = calculate(raw, adjusted)
    assert zero.K.iloc[13] == 0
    assert zero.F.isna().all()


def test_calendar_mismatch_and_duplicate_dates_are_rejected():
    raw, adjusted = frames(25)
    adjusted.loc[1, "Date"] += pd.Timedelta(days=10)
    with pytest.raises(ValueError, match="calendar"):
        calculate(raw, adjusted)
    raw.loc[1, "Date"] = raw.Date.iloc[0]
    with pytest.raises(ValueError, match="calendar"):
        calculate(raw, raw.drop(columns="VolumeLots"))


@pytest.mark.parametrize("feature_id", list(FEATURES))
def test_column_bins_match_scalar_inventory_at_every_edge(feature_id: str):
    definition = FEATURES[feature_id]
    examples: list[Any]
    if definition.categories:
        examples = [value for _, value in definition.categories]
    else:
        edges = sorted({value for interval in definition.numeric_bins for value in (interval.lower, interval.upper) if value is not None})
        examples = [0.0]
        for edge in edges:
            examples += [max(0, edge - 1), edge, edge + 1] if definition.discrete_count else [np.nextafter(edge, -np.inf), edge, np.nextafter(edge, np.inf)]
    values = pd.Series(examples)
    actual = bin_values(feature_id, values)
    for index, example in enumerate(examples):
        scalar = classify_feature(feature_id, example)
        assert actual.loc[index, f"{feature_id}_bin"] == scalar.bin_id
        assert actual.loc[index, f"{feature_id}_status"] == scalar.status


def test_bins_unknown_applicability_and_absent_columns():
    values = pd.DataFrame({
        "F": [0.7, 1.0, np.nan],
        "A": [0.1, 0.2, 0.3],
        "A_applicable": [False, True, True],
        "A_unknown_reason": [None, "warmup_insufficient", None],
        "I": ["unknown", "up", None],
    })
    result = bin_columns(values)
    assert result.F_bin.iloc[:2].tolist() == ["le070", "070to100"]
    assert pd.isna(result.F_bin.iloc[2])
    assert result.F_status.iloc[2] == "feature_unknown"
    assert result.A_status.tolist() == ["not_applicable", "feature_unknown", "known"]
    assert result.A_reason.iloc[:2].tolist() == ["outside_feature_cohort", "warmup_insufficient"]
    assert pd.isna(result.A_reason.iloc[2])
    assert result.I_reason.iloc[0] == "source_market_unknown"
    assert result.K3_status.eq("feature_unknown").all()
    assert result.K3_bin.isna().all()
    assert result.I_bin.isna().tolist() == [True, False, True]
    assert result.shape[1] == 24 * 3
    counts = bin_values("C", pd.Series([0.0, 2.0, 4.0, np.nan]))
    assert counts.C_bin.iloc[:3].tolist() == ["none", "partial", "all"]
    assert pd.isna(counts.C_bin.iloc[3])
    assert counts.C_status.iloc[3] == "feature_unknown"


@pytest.mark.parametrize("values", [[0, 1], [True, 0], ["true", "false"]])
def test_bool_bins_reject_numeric_aliases(values: list[object]):
    with pytest.raises(ValueError, match="unexpected"):
        bin_values("G2_limit", pd.Series(values))


@pytest.mark.parametrize("values", [[-1], [1.5], [True]])
def test_count_bins_reject_invalid_counts(values: list[object]):
    with pytest.raises(ValueError):
        bin_values("E3", pd.Series(values))


def test_nonfinite_missing_counts_and_invalid_reason():
    result = bin_values("G", pd.Series([np.nan, np.inf, -np.inf, 0.0]))
    assert result.G_status.tolist() == ["feature_unknown"] * 3 + ["known"]
    assert result.G_bin.iloc[-1] == "lt150"
    with pytest.raises(ValueError, match="nonempty"):
        bin_values("F", pd.Series([1.0]), unknown_reason=" ")


def test_reasons_distinguish_initial_warmup_current_missing_and_gap_recovery():
    raw, adjusted = frames(560)
    raw.loc[260, "High"] = np.nan
    adjusted.loc[260, "High"] = np.nan
    result = calculate(raw, adjusted)
    assert result.D.iloc[:250].isna().all()
    assert result.D_unknown_reason.iloc[:250].eq("warmup_insufficient").all()
    assert pd.isna(result.D_unknown_reason.iloc[250])
    assert result.D_unknown_reason.iloc[260] == "missing_price"
    assert result.D_unknown_reason.iloc[261] == "warmup_insufficient_after_gap"
    assert pd.isna(result.D_unknown_reason.iloc[511])
    assert result.K_unknown_reason.iloc[260] == "missing_price"
    assert result.K_unknown_reason.iloc[261] == "warmup_insufficient_after_gap"
    assert pd.isna(result.K_unknown_reason.iloc[274])
    assert result.F_unknown_reason.iloc[132] == "warmup_insufficient"
    assert pd.notna(result.F.iloc[260])
    assert pd.isna(result.F_unknown_reason.iloc[260])
    assert result.F_unknown_reason.iloc[261] == "warmup_insufficient_after_gap"
    assert pd.isna(result.F_unknown_reason.iloc[394])
    assert pd.isna(result.G_unknown_reason.iloc[260])
    assert pd.isna(result.K2_unknown_reason.iloc[260])
    binned = bin_columns(result)
    assert binned.D_status.iloc[0] == "feature_unknown"
    assert binned.D_reason.iloc[0] == "warmup_insufficient"
    assert binned.D_reason.iloc[260] == "missing_price"
    assert binned.D_reason.iloc[261] == "warmup_insufficient_after_gap"


def test_legacy_raw_and_flat_range_reasons_preserve_known_values():
    raw, adjusted = frames(180)
    adjusted.loc[40, ["Open", "High", "Low", "Close"]] = 100.0
    raw.loc[42, "Close"] = np.nan
    vx = np.full(len(raw), 1.7)
    vx[40] = np.nan
    vx[44] = np.inf
    result = calculate_daily_features(raw, adjusted, vx, np.ones(len(raw), dtype=bool))
    assert result.G_unknown_reason.iloc[40] == "legacy_vx_unknown"
    assert result.G_unknown_reason.iloc[44] == "legacy_vx_unknown"
    assert result.G2_position_unknown_reason.iloc[40] == "flat_price_range"
    assert result.G2_limit_unknown_reason.iloc[0] == "warmup_insufficient"
    assert result.G2_limit_unknown_reason.iloc[42:44].eq("missing_raw_close").all()
    assert result.K2_unknown_reason.iloc[42] == "missing_raw_close"
    assert pd.isna(result.K2_unknown_reason.iloc[41])


def test_weekly_reasons_exclude_current_week_missing_quote():
    raw, adjusted = frames(125)
    adjusted.loc[60, "High"] = np.nan
    result = calculate(raw, adjusted)
    assert result.C4_unknown_reason.iloc[0] == "warmup_insufficient"
    assert pd.notna(result.C4.iloc[60])
    assert pd.isna(result.C4_unknown_reason.iloc[60])
    assert result.C4_unknown_reason.iloc[65] == "warmup_insufficient_after_gap"
    assert pd.isna(result.C4_unknown_reason.iloc[120])


def test_categorical_unknown_reason_survives_validation_and_bin_assignment():
    values = pd.Series([np.nan, 0.8, np.nan], index=["missing", "known", "warmup"])
    reasons = pd.Series(pd.Categorical(["missing_price", None, "warmup_insufficient"]), index=values.index)
    result = bin_values("F", values, unknown_reason=reasons)
    assert result.F_status.tolist() == ["feature_unknown", "known", "feature_unknown"]
    assert result.F_reason.loc["missing"] == "missing_price"
    assert pd.isna(result.F_reason.loc["known"])
    assert result.F_reason.loc["warmup"] == "warmup_insufficient"
    assert result.F_bin.loc["known"] == "070to100"


@pytest.mark.parametrize("invalid", ["", " "])
def test_categorical_empty_unknown_reason_is_rejected(invalid: str):
    reasons = pd.Series(pd.Categorical(["missing_price", invalid]))
    with pytest.raises(ValueError, match="nonempty"):
        bin_values("F", pd.Series([np.nan, np.nan]), unknown_reason=reasons)


def test_categorical_type_predicate_masks_are_plain_booleans():
    values = pd.Series(pd.Categorical(["down", "up", None]))
    result = bin_values("I", values)
    assert result.I_bin.iloc[:2].tolist() == ["down", "up"]
    assert result.I_status.iloc[2] == "feature_unknown"
    mixed_bool = pd.Series(pd.Categorical([True, "false"]))
    with pytest.raises(ValueError, match="unexpected"):
        bin_values("G2_limit", mixed_bool)
