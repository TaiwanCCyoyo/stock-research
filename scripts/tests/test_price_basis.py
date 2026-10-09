"""Hand-calculable price basis fixtures; never read market data or outcomes."""

from collections.abc import Sequence
from typing import cast

import numpy as np
import pandas as pd
import pytest

from research_core.price_basis import PriceBasis, prepare_prices


def quotes(values: Sequence[float] = (100.0, 100.0, 50.0, 50.0)) -> pd.DataFrame:
    return pd.DataFrame({
        "Code": "2330",
        "Date": pd.date_range("2020-01-01", periods=len(values)),
        **{column: values for column in ("Open", "High", "Low", "Close")},
        "Volume": 10.0,
    })


def actions(rows: Sequence[tuple[str, str, str, float]] = ()) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=pd.Index(["code", "ex_date", "event_type", "price_factor"]))


def prepare(
    raw: pd.DataFrame,
    rows: Sequence[tuple[str, str, str, float]] = (),
    basis: PriceBasis = "permanent_adjusted",
    calendar: pd.DatetimeIndex | None = None,
    cutoff: str | pd.Timestamp = "2020-01-04",
) -> pd.DataFrame:
    return prepare_prices(raw, actions(rows), pd.DatetimeIndex(raw.Date) if calendar is None else calendar, basis=basis, cutoff=cutoff)


@pytest.mark.parametrize("basis,expected", [("raw", [100, 100, 50, 50]), ("permanent_adjusted", [50] * 4), ("reference_factor_adjusted", [50] * 4)])
def test_split_three_bases_preserve_evidence_and_inputs(basis: PriceBasis, expected: list[int]) -> None:
    raw = quotes()
    original = raw.copy(deep=True)
    result = prepare(raw, [("2330", "2020-01-03", "ETF_SPLIT", 0.5)], basis)
    assert result.Close.tolist() == expected
    assert result.Quality.all()
    assert result.RawClose.tolist() == [100, 100, 50, 50]
    assert result.Turnover.tolist() == [1000, 1000, 500, 500]
    assert result.restatement_factor.tolist() == ([1] * 4 if basis == "raw" else [0.5, 0.5, 1, 1])
    pd.testing.assert_frame_equal(raw, original)


@pytest.mark.parametrize("basis,expected", [("raw", [100, 100, 50, 50]), ("permanent_adjusted", [100, 100, 50, 50]), ("reference_factor_adjusted", [50] * 4)])
def test_cash_three_bases(basis: PriceBasis, expected: list[int]) -> None:
    result = prepare(quotes(), [("2330", "2020-01-03", "CASH_DIVIDEND", 0.5)], basis)
    assert result.Close.tolist() == expected
    assert result.Quality.all()


def test_split_and_later_cash_hand_calculable_reference_basis() -> None:
    raw = quotes((100, 50, 40, 40))
    rows = [("2330", "2020-01-02", "ETF_SPLIT", 0.5), ("2330", "2020-01-03", "CASH_DIVIDEND", 0.8)]
    assert prepare(raw, rows, "reference_factor_adjusted").Close.tolist() == [40] * 4
    assert prepare(raw, rows).Close.tolist() == [50, 50, 40, 40]


def test_identical_duplicate_action_factor_applies_once() -> None:
    row = ("2330", "2020-01-03", "ETF_SPLIT", 0.5)
    assert prepare(quotes(), [row, row]).Close.tolist() == [50] * 4


@pytest.mark.parametrize(
    "rows,reason",
    [
        ([("ETF_SPLIT", 0.5), ("ETF_SPLIT", 0.6)], "ambiguous_or_missing_action_factor"),
        ([("ETF_SPLIT", 0.5), ("EX_RIGHT", 0.5)], "ambiguous_same_day_actions"),
        ([("ETF_SPLIT", np.nan)], "ambiguous_or_missing_action_factor"),
        ([("ETF_SPLIT", 0)], "ambiguous_or_missing_action_factor"),
        ([("ETF_SPLIT", np.inf)], "ambiguous_or_missing_action_factor"),
        ([("UNKNOWN", 0.5)], "unsupported_action"),
    ],
)
def test_unproved_actions_invalidate_prefix_including_event_day(rows: list[tuple[str, float]], reason: str) -> None:
    raw = quotes((100,) * 4)
    result = prepare(raw, [("2330", "2020-01-03", kind, factor) for kind, factor in rows])
    assert result.Quality.tolist() == [False, False, False, True]
    assert result.Close.iloc[:3].isna().all()
    assert result.RawClose.tolist() == [100] * 4
    assert result.restatement_factor.iloc[:3].isna().all()
    assert result.quality_reason.iloc[:3].tolist() == [reason] * 3
    assert result.corporate_action_types.iloc[2] == ",".join(sorted({kind for kind, _ in rows}))


def test_cash_and_split_same_day_selected_only_for_reference() -> None:
    rows = [("2330", "2020-01-03", "ETF_SPLIT", 0.5), ("2330", "2020-01-03", "CASH_DIVIDEND", 0.5)]
    assert prepare(quotes(), rows).Quality.all()
    result = prepare(quotes(), rows, "reference_factor_adjusted")
    assert result.quality_reason.iloc[0] == "ambiguous_same_day_actions"
    assert result.corporate_action_types.iloc[2] == "CASH_DIVIDEND,ETF_SPLIT"


def test_raw_missing_factor_preserves_flat_quotes_but_cannot_explain_large_jump() -> None:
    rows = [("2330", "2020-01-03", "ETF_SPLIT", np.nan)]
    flat = prepare(quotes((100,) * 4), rows, "raw")
    assert flat.Quality.all()
    assert flat.Close.tolist() == [100] * 4
    result = prepare(quotes(), rows, "raw")
    assert result.Quality.tolist() == [True, True, False, True]
    assert result.quality_reason.iloc[2] == "unexplained_raw_jump"
    assert result.Close.iloc[:2].tolist() == [100, 100]
    assert pd.isna(result.Close.iloc[2])
    assert result.Close.iloc[3] == 50
    assert result.RawClose.tolist() == [100, 100, 50, 50]
    assert result.restatement_factor.tolist() == [1] * 4


def test_cash_missing_factor_is_ignored_only_for_permanent() -> None:
    rows = [("2330", "2020-01-03", "CASH_DIVIDEND", np.nan)]
    flat = quotes((100,) * 4)
    permanent = prepare(flat, rows)
    assert permanent.Quality.all()
    assert permanent.Close.tolist() == [100] * 4
    assert permanent.restatement_factor.tolist() == [1] * 4
    assert not prepare(flat, rows, "reference_factor_adjusted").Quality.iloc[:3].any()
    jumped = prepare(quotes(), rows)
    assert jumped.Quality.tolist() == [True, True, False, True]
    assert jumped.quality_reason.iloc[2] == "unexplained_adjusted_jump"


@pytest.mark.parametrize("basis", ["raw", "permanent_adjusted", "reference_factor_adjusted"])
def test_unexplained_jump_and_cash_positive_jump(basis: PriceBasis) -> None:
    raw = quotes((100, 100, 150, 150))
    result = prepare(raw, basis=basis)
    assert not result.Quality.iloc[2]
    result = prepare(raw, [("2330", "2020-01-03", "CASH_DIVIDEND", 1)], basis)
    assert not result.Quality.iloc[2]


@pytest.mark.parametrize("basis", ["raw", "permanent_adjusted", "reference_factor_adjusted"])
@pytest.mark.parametrize("kind,factor,after", [("ETF_SPLIT", 0.5, 50.0), ("ETF_REVERSE_SPLIT", 2.0, 200.0), ("CASH_DIVIDEND", 0.5, 50.0)])
def test_valid_recorded_factor_explains_only_matching_large_jump(basis: PriceBasis, kind: str, factor: float, after: float) -> None:
    raw = quotes((100.0, 100.0, after, after))
    result = prepare(raw, [("2330", "2020-01-03", kind, factor)], basis)
    assert result.Quality.all()
    assert result.quality_reason.isna().all()
    assert result.RawClose.tolist() == [100.0, 100.0, after, after]
    restated = basis != "raw" and (kind != "CASH_DIVIDEND" or basis == "reference_factor_adjusted")
    assert result.Close.tolist() == ([after] * 4 if restated else raw.Close.tolist())


@pytest.mark.parametrize("basis", ["raw", "permanent_adjusted", "reference_factor_adjusted"])
@pytest.mark.parametrize("factor,after", [(1.1, 50.0), (0.9, 10.0), (0.5, 10.0), (0.5, 200.0)])
def test_cash_cannot_explain_wrong_direction_or_large_normalized_residual(basis: PriceBasis, factor: float, after: float) -> None:
    result = prepare(quotes((100.0, 100.0, after, after)), [("2330", "2020-01-03", "CASH_DIVIDEND", factor)], basis)
    assert not result.Quality.iloc[2]
    assert pd.isna(result.Close.iloc[2])
    assert result.RawClose.iloc[2] == after
    if factor > 1 and basis == "reference_factor_adjusted":
        assert result.quality_reason.iloc[:3].tolist() == ["ambiguous_or_missing_action_factor"] * 3
    else:
        assert result.quality_reason.iloc[2] == ("unexplained_raw_jump" if basis == "raw" else "unexplained_adjusted_jump")


@pytest.mark.parametrize("kind,factor,after", [("ETF_SPLIT", 2.0, 200.0), ("ETF_REVERSE_SPLIT", 0.5, 50.0)])
@pytest.mark.parametrize("basis", ["raw", "permanent_adjusted", "reference_factor_adjusted"])
def test_split_factor_direction_must_agree_with_event_type(basis: PriceBasis, kind: str, factor: float, after: float) -> None:
    result = prepare(quotes((100.0, 100.0, after, after)), [("2330", "2020-01-03", kind, factor)], basis)
    if basis == "raw":
        assert result.Quality.tolist() == [True, True, False, True]
        assert result.quality_reason.iloc[2] == "unexplained_raw_jump"
        assert result.restatement_factor.tolist() == [1] * 4
    else:
        assert result.Quality.tolist() == [False, False, False, True]
        assert result.quality_reason.iloc[:3].tolist() == ["ambiguous_or_missing_action_factor"] * 3
        assert result.restatement_factor.iloc[:3].isna().all()


@pytest.mark.parametrize("kind,factor,after", [("ETF_SPLIT", 0.5, 200.0), ("ETF_REVERSE_SPLIT", 2.0, 50.0), ("EX_RIGHT", 2.0, 50.0)])
def test_raw_jump_direction_must_agree_with_recorded_factor(kind: str, factor: float, after: float) -> None:
    result = prepare(quotes((100.0, 100.0, after, after)), [("2330", "2020-01-03", kind, factor)], "raw")
    assert result.Quality.tolist() == [True, True, False, True]
    assert result.quality_reason.iloc[2] == "unexplained_raw_jump"


@pytest.mark.parametrize("factor", [np.nan, np.inf, 0.0, -0.5, 1.0])
def test_raw_large_jump_needs_finite_positive_nonunit_factor(factor: float) -> None:
    result = prepare(quotes(), [("2330", "2020-01-03", "ETF_SPLIT", factor)], "raw")
    assert result.Quality.tolist() == [True, True, False, True]
    assert result.quality_reason.iloc[2] == "unexplained_raw_jump"


@pytest.mark.parametrize(
    "rows",
    [
        [("ETF_SPLIT", 0.5), ("ETF_SPLIT", 0.6)],
        [("ETF_SPLIT", 0.5), ("ETF_SPLIT", np.nan)],
        [("ETF_SPLIT", 0.5), ("CASH_DIVIDEND", 0.5)],
        [("ETF_SPLIT", 0.5), ("UNKNOWN", 0.5)],
    ],
)
def test_raw_event_explanation_requires_one_known_kind_with_all_factors_agreeing(rows: list[tuple[str, float]]) -> None:
    result = prepare(quotes(), [("2330", "2020-01-03", kind, factor) for kind, factor in rows], "raw")
    assert result.Quality.tolist() == [True, True, False, True]
    expected_reason = "unsupported_action" if any(kind == "UNKNOWN" for kind, _ in rows) else "unexplained_raw_jump"
    assert expected_reason in result.quality_reason.iloc[2]
    assert result.corporate_action_types.iloc[2] == ",".join(sorted({kind for kind, _ in rows}))


@pytest.mark.parametrize("basis", ["raw", "permanent_adjusted"])
def test_agreed_duplicate_cash_factor_can_explain_jump_once(basis: PriceBasis) -> None:
    row = ("2330", "2020-01-03", "CASH_DIVIDEND", 0.5)
    result = prepare(quotes(), [row, row], basis)
    assert result.Quality.all()
    assert result.Close.tolist() == [100, 100, 50, 50]


@pytest.mark.parametrize("basis", ["raw", "permanent_adjusted"])
def test_conflicting_duplicate_cash_factors_cannot_explain_jump(basis: PriceBasis) -> None:
    rows = [("2330", "2020-01-03", "CASH_DIVIDEND", 0.5), ("2330", "2020-01-03", "CASH_DIVIDEND", 0.6)]
    result = prepare(quotes(), rows, basis)
    assert result.Quality.tolist() == [True, True, False, True]
    assert result.quality_reason.iloc[2] == ("unexplained_raw_jump" if basis == "raw" else "unexplained_adjusted_jump")


@pytest.mark.parametrize("basis", ["permanent_adjusted", "reference_factor_adjusted"])
def test_selected_combined_cash_rights_factor_rejects_upward_factor(basis: PriceBasis) -> None:
    result = prepare(quotes((100,) * 4), [("2330", "2020-01-03", "EX_RIGHT_AND_DIVIDEND", 1.1)], basis)
    assert result.Quality.tolist() == [False, False, False, True]
    assert result.quality_reason.iloc[:3].tolist() == ["ambiguous_or_missing_action_factor"] * 3


@pytest.mark.parametrize("basis", ["permanent_adjusted", "reference_factor_adjusted"])
def test_selected_ex_right_upward_factor_invalidates_prefix_even_without_large_jump(basis: PriceBasis) -> None:
    raw = quotes((100,) * 4)
    result = prepare(raw, [("2330", "2020-01-03", "EX_RIGHT", 1.1)], basis)
    assert result.Quality.tolist() == [False, False, False, True]
    assert result.quality_reason.iloc[:3].tolist() == ["ambiguous_or_missing_action_factor"] * 3
    assert result.restatement_factor.iloc[:3].isna().all()
    assert result.loc[:, ["Open", "High", "Low", "Close"]].iloc[:3].isna().all().all()
    assert result.RawClose.tolist() == [100] * 4
    assert result.Close.iloc[3] == 100
    assert result.corporate_action_types.iloc[2] == "EX_RIGHT"


@pytest.mark.parametrize("basis", ["permanent_adjusted", "reference_factor_adjusted"])
@pytest.mark.parametrize("factor,after", [(0.9, 90.0), (1.0, 100.0)])
def test_selected_ex_right_downward_and_unit_factors_remain_usable(basis: PriceBasis, factor: float, after: float) -> None:
    result = prepare(quotes((100.0, 100.0, after, after)), [("2330", "2020-01-03", "EX_RIGHT", factor)], basis)
    assert result.Quality.all()
    assert result.quality_reason.isna().all()
    assert result.Close.tolist() == pytest.approx([after] * 4)
    assert result.restatement_factor.tolist() == [factor, factor, 1, 1]


@pytest.mark.parametrize("basis", ["permanent_adjusted", "reference_factor_adjusted"])
def test_selected_ex_right_downward_factor_does_not_exempt_residual_large_jump(basis: PriceBasis) -> None:
    result = prepare(quotes((100, 100, 30, 30)), [("2330", "2020-01-03", "EX_RIGHT", 0.9)], basis)
    assert result.Quality.tolist() == [True, True, False, True]
    assert result.Close.iloc[:2].tolist() == pytest.approx([90, 90])
    assert result.quality_reason.iloc[2] == "unexplained_adjusted_jump"
    assert result.RawClose.iloc[2] == 30


@pytest.mark.parametrize("basis", ["permanent_adjusted", "reference_factor_adjusted"])
@pytest.mark.parametrize("factor", [0.9, 1.1])
def test_selected_ex_right_factor_validation_preserves_calendar_gap(basis: PriceBasis, factor: float) -> None:
    raw = quotes((100, 100, 90, 90))
    calendar = pd.DatetimeIndex(raw.Date)
    result = prepare(raw.drop(index=1), [("2330", "2020-01-03", "EX_RIGHT", factor)], basis, calendar=calendar)
    assert "missing_official_quote" in result.quality_reason.iloc[1]
    assert pd.isna(result.RawClose.iloc[1])
    assert pd.isna(result.Close.iloc[1])
    if factor > 1:
        assert result.Quality.tolist() == [False, False, False, True]
        assert all("ambiguous_or_missing_action_factor" in reason for reason in result.quality_reason.iloc[:3])
    else:
        assert result.Quality.tolist() == [True, False, True, True]
        assert result.Close.iloc[[0, 2, 3]].tolist() == pytest.approx([90] * 3)


def test_raw_flat_quotes_with_upward_ex_right_factor_are_not_restated_or_prefix_invalidated() -> None:
    result = prepare(quotes((100,) * 4), [("2330", "2020-01-03", "EX_RIGHT", 1.1)], "raw")
    assert result.Quality.all()
    assert result.Close.tolist() == [100] * 4
    assert result.restatement_factor.tolist() == [1] * 4


def test_restated_combined_cash_rights_factor_cannot_exempt_remaining_jump() -> None:
    result = prepare(quotes((100, 100, 30, 30)), [("2330", "2020-01-03", "EX_RIGHT_AND_DIVIDEND", 0.8)])
    assert result.Close.iloc[:2].tolist() == [80, 80]
    assert not result.Quality.iloc[2]
    assert result.quality_reason.iloc[2] == "unexplained_adjusted_jump"
    assert result.corporate_action_types.iloc[2] == "EX_RIGHT_AND_DIVIDEND"


@pytest.mark.parametrize("basis", ["raw", "permanent_adjusted"])
def test_noncalendar_cash_does_not_explain_next_session(basis: PriceBasis) -> None:
    raw = quotes()
    raw["Date"] = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-04", "2020-01-05"])
    result = prepare(raw, [("2330", "2020-01-03", "CASH_DIVIDEND", 0.5)], basis, cutoff="2020-01-05")
    assert not result.Quality.iloc[2]
    assert result.corporate_action_types.iloc[2] == "CASH_DIVIDEND"


def test_noncalendar_split_factor_does_not_explain_raw_next_session_jump() -> None:
    raw = quotes()
    raw["Date"] = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-04", "2020-01-05"])
    result = prepare(raw, [("2330", "2020-01-03", "ETF_SPLIT", 0.5)], "raw", cutoff="2020-01-05")
    assert result.Quality.tolist() == [True, True, False, True]
    assert result.quality_reason.iloc[2] == "unexplained_raw_jump"


def test_gaps_duplicates_invalid_ohlc_volume_are_retained() -> None:
    raw = quotes((100.0,) * 6)
    calendar = pd.DatetimeIndex(raw.Date)
    raw.loc[2, "High"] = 99
    raw.loc[3, "Close"] = np.inf
    raw.loc[4, "Low"] = 0
    raw.loc[5, "Volume"] = -1
    raw = pd.concat([raw.drop(index=1), raw.iloc[[0]]], ignore_index=True)
    result = prepare(raw, calendar=calendar, cutoff="2020-01-06")
    assert result.quality_reason.tolist() == ["duplicate_date", "missing_official_quote", "invalid_ohlc", "invalid_ohlc", "invalid_ohlc", None]
    assert result.Close.iloc[:5].isna().all()
    assert result.Quality.iloc[5]
    assert result.volume_status.iloc[5] == "missing_or_invalid"
    assert pd.isna(result.Turnover.iloc[5])


def test_volume_zero_and_unknown_do_not_change_price_quality() -> None:
    raw = quotes((100,) * 4)
    raw["Volume"] = [0, np.nan, np.inf, 10]
    result = prepare(raw)
    assert result.Quality.all()
    assert result.volume_status.tolist() == ["zero", "missing_or_invalid", "missing_or_invalid", "observed"]
    assert result.Turnover.iloc[0] == 0


def test_cutoff_ignores_future_actions_and_quotes_but_includes_later_calendar_action() -> None:
    raw = quotes((100,) * 4)
    calendar = pd.DatetimeIndex(raw.Date.iloc[:2])
    rows = [("2330", "2020-01-03", "ETF_SPLIT", 0.5), ("2330", "2020-01-04", "ETF_SPLIT", 0.5), ("9999", "2020-01-02", "ETF_SPLIT", 0.1)]
    result = prepare(raw, rows, calendar=calendar, cutoff="2020-01-03")
    assert result.Close.tolist() == [50, 50]
    assert len(result) == 2


@pytest.mark.parametrize(
    "calendar",
    [
        pd.DatetimeIndex(["2020-01-02", "2020-01-01"]),
        pd.DatetimeIndex(["2020-01-01", "2020-01-01"]),
        pd.DatetimeIndex(["2020-01-01 01:00"]),
        pd.DatetimeIndex(["2020-01-01"], tz="UTC"),
        pd.DatetimeIndex([pd.NaT]),
        pd.DatetimeIndex(["2020-01-05"]),
    ],
)
def test_calendar_rejects_unsorted_duplicate_intraday_timezone_missing_future(calendar: pd.DatetimeIndex) -> None:
    with pytest.raises(ValueError):
        prepare(quotes(), calendar=calendar)


@pytest.mark.parametrize("column,value", [("Date", "2020-01-01 01:00"), ("Date", None), ("Code", "9999"), ("Code", None)])
def test_invalid_quote_dates_and_symbol_fail_explicitly(column: str, value: str | None) -> None:
    raw = quotes()
    raw[column] = raw[column].astype(object)
    raw.loc[0, column] = value
    with pytest.raises(ValueError):
        prepare(raw)


@pytest.mark.parametrize("cutoff", [None, "2020-01-04 01:00", pd.Timestamp("2020-01-04", tz="UTC")])
def test_cutoff_is_required_daily_and_naive(cutoff: str | pd.Timestamp | None) -> None:
    with pytest.raises(ValueError):
        prepare(quotes(), cutoff=cast(str | pd.Timestamp, cutoff))


def test_invalid_action_date_and_basis_rejected() -> None:
    with pytest.raises(ValueError, match="Action dates"):
        prepare(quotes(), [("2330", "2020-01-03 01:00", "ETF_SPLIT", 0.5)])
    with pytest.raises(ValueError, match="Unknown price basis"):
        prepare(quotes(), basis=cast(PriceBasis, "total_return"))


def test_empty_calendar_and_raw_preserve_schema() -> None:
    result = prepare(quotes().iloc[:0], calendar=pd.DatetimeIndex([]))
    assert result.empty
    assert "RawClose" in result
    assert "quality_reason" in result
