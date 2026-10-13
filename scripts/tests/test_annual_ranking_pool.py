import pandas as pd
import pytest

from research_core.annual_ranking_pool import rank_panel


def synthetic_panel() -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    calendar = pd.DatetimeIndex(["2020-12-31", "2021-01-04", "2021-12-30", "2022-01-03"])
    records = []
    prices_by_code = {
        "1234": [100.0, 100.0, 90.0, 100.0],
        "2345": [80.0, 80.0, 100.0, 70.0],
    }
    for code, closes in prices_by_code.items():
        for date, close in zip(calendar, closes, strict=True):
            records.append({
                "Code": code,
                "Date": date,
                "Open": close,
                "High": close,
                "Low": close,
                "Close": close,
                "Volume": 1.0,
            })
    actions = pd.DataFrame({name: [] for name in ("code", "ex_date", "event_type", "price_factor", "cash_dividend_estimate")})
    return pd.DataFrame(records), actions, calendar


def test_serial_and_two_worker_results_are_exact_and_sorted() -> None:
    prices, actions, calendar = synthetic_panel()

    serial = rank_panel(prices, actions, calendar, [2021, 2022], workers=1)
    parallel = rank_panel(prices, actions, calendar, [2021, 2022], workers=2)

    assert serial["rows"] == parallel["rows"]
    assert [(row["year"], row["code"]) for row in parallel["rows"]] == [
        (2021, "1234"),
        (2021, "2345"),
        (2022, "1234"),
        (2022, "2345"),
    ]
    assert parallel["performance"]["peak_inflight_stock_jobs"] <= 2
    assert parallel["performance"]["pickle_serialized_input_bytes_status"] == "unknown"


def test_subset_matches_rows_from_complete_panel() -> None:
    prices, actions, calendar = synthetic_panel()

    complete = rank_panel(prices, actions, calendar, [2021, 2022])
    subset = rank_panel(prices, actions, calendar, [2021, 2022], codes=["2345"])

    assert subset["rows"] == [row for row in complete["rows"] if row["code"] == "2345"]
    assert subset["performance"]["stock_count"] == 1


def test_worker_count_above_supported_bound_is_rejected() -> None:
    prices, actions, calendar = synthetic_panel()

    with pytest.raises(ValueError, match="workers must be 1 or 2"):
        rank_panel(prices, actions, calendar, [2021], workers=3)
