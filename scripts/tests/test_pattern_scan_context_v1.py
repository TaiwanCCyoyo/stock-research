"""Public 0050 context parity over invented complete ordinary-stock grids."""

from typing import cast

import numpy as np
import pandas as pd
import pytest

from research_core.market_context import compute_context_rows
from research_core.pattern_scan_context_v1 import build_context

POOL = ("TW:001", "TW:002")


def inputs(length: int = 85) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2020-01-06", periods=length)
    prices = np.r_[np.full(21, 100.0), np.full(21, 104.0), np.full(21, 108.16), np.full(22, 100.0)][:length]
    benchmark = pd.DataFrame({"Close": prices, "Quality": True, "security_id": "TW:0050"}, index=dates)
    stocks = pd.DataFrame([
        {"security_id": security, "t0": day.strftime("%Y-%m-%d"), "calendar_index": index} for security in POOL for index, day in enumerate(dates)
    ])
    return stocks, benchmark


def test_public_rules_exact_parity_and_separate_hindsight() -> None:
    stocks, benchmark = inputs()
    originals = stocks.copy(deep=True), benchmark.copy(deep=True)
    result = build_context(stocks, benchmark, POOL)
    dates = cast(pd.DatetimeIndex, benchmark.index).strftime("%Y-%m-%d").tolist()
    closes = benchmark.Close.tolist()
    for layer, column, prefix in (("past_only", "MKT", "MKT"), ("retrospective", "retrospective_state", "retrospective")):
        expected = compute_context_rows(dates, closes, layer=layer)
        assert result[column].tolist() == [row["state"] for row in expected]
        assert result[f"{prefix}_unknown_reason"].tolist() == [row["missing_reason"] for row in expected]
        assert result[f"{prefix}_information_cutoff"].tolist() == [row["information_cutoff"] for row in expected]
    assert result.MKT.iloc[20] == "consolidation" and result.MKT.iloc[21] == "up"
    assert result.retrospective_state.iloc[11] == "up"
    assert result.attrs["coverage"]["ordinary_security_n"] == 2
    assert result.attrs["coverage"]["historical_availability_certified"] is False
    pd.testing.assert_frame_equal(stocks, originals[0])
    pd.testing.assert_frame_equal(benchmark, originals[1])


def test_missing_benchmark_span_is_unknown_not_mixed() -> None:
    stocks, benchmark = inputs()
    benchmark.loc[benchmark.index[:5], "Close"] = np.nan
    benchmark.loc[benchmark.index[35], "Quality"] = False
    result = build_context(stocks, benchmark, POOL)
    assert result.MKT.iloc[:25].eq("unknown").all()
    assert result.MKT.iloc[24] == "unknown" and result.MKT_unknown_reason.iloc[24] == "unusable_observations"
    assert result.MKT.iloc[35:56].eq("unknown").all()
    assert result.attrs["coverage"]["first_usable_benchmark_date"] == cast(pd.DatetimeIndex, benchmark.index)[5].strftime("%Y-%m-%d")
    assert result.attrs["coverage"]["usable_benchmark_n"] == len(benchmark) - 6
    assert result.retrospective_unknown_reason.iloc[-10:].eq("future_unavailable").all()


def test_future_benchmark_changes_do_not_change_past_only_rows() -> None:
    stocks, benchmark = inputs()
    baseline = build_context(stocks, benchmark, POOL)
    changed = benchmark.copy()
    changed.loc[changed.index[40:], "Close"] = 1000.0
    changed.loc[changed.index[60:], "Quality"] = False
    result = build_context(stocks, changed, POOL)
    columns = [column for column in baseline if column.startswith("MKT")]
    pd.testing.assert_frame_equal(result.loc[:39, columns], baseline.loc[:39, columns])
    assert not result.retrospective_state.iloc[30:40].equals(baseline.retrospective_state.iloc[30:40])
    prefix = build_context(stocks.loc[stocks.calendar_index.lt(40)], benchmark.iloc[:40], POOL)
    pd.testing.assert_frame_equal(prefix[columns], baseline.loc[:39, columns])


@pytest.mark.parametrize("invalid", ["partial_pool", "missing_session", "duplicate", "date", "index", "benchmark_identity", "timezone", "quality", "expected"])
def test_complete_grid_and_benchmark_contract_rejections(invalid: str) -> None:
    stocks, benchmark = inputs()
    expected = POOL
    if invalid == "partial_pool":
        stocks = stocks.loc[stocks.security_id.eq(POOL[0])]
    elif invalid == "missing_session":
        stocks = stocks.iloc[1:]
    elif invalid == "duplicate":
        stocks = pd.concat([stocks.iloc[:-1], stocks.iloc[:1]])
    elif invalid == "date":
        stocks.loc[0, "t0"] = "2020-1-6"
    elif invalid == "index":
        stocks.loc[0, "calendar_index"] = -1
    elif invalid == "benchmark_identity":
        benchmark["security_id"] = "TW:ordinary"
    elif invalid == "timezone":
        benchmark.index = cast(pd.DatetimeIndex, benchmark.index).tz_localize("Asia/Taipei")
    elif invalid == "quality":
        benchmark["Quality"] = 1
    else:
        expected = (POOL[0], POOL[0])
    with pytest.raises(ValueError):
        build_context(stocks, benchmark, expected)


def test_all_missing_preserves_complete_calendar_and_coverage() -> None:
    stocks, benchmark = inputs()
    benchmark["Close"] = np.nan
    result = build_context(stocks, benchmark, POOL)
    assert len(result) == len(benchmark)
    assert result.MKT.eq("unknown").all() and result.retrospective_state.eq("unknown").all()
    assert result.attrs["coverage"]["first_usable_benchmark_date"] is None
    assert result.attrs["coverage"]["last_usable_benchmark_date"] is None
