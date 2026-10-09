"""Characterization tests for DataLoader._apply_corporate_action_policy and
Broker.handle_split, pinned before expand-corporate-action-adjustments touches either.

See openspec/changes/expand-corporate-action-adjustments/ for the change this
safety net protects.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from StockProject.engine.broker import Broker
from StockProject.engine.data_loader import DataLoader

CA_COLUMNS = [
    "code",
    "ex_date",
    "event_type",
    "previous_close",
    "reference_price",
    "cash_dividend_estimate",
    "price_factor",
    "evidence_status",
]


def write_day_csv(data_root: Path, code: str, rows: list[tuple[str, float, float, float, float, int]]) -> Path:
    path = data_root / f"{code}_day.csv"
    lines = ["Date,Open,High,Low,Close,Volume"]
    for date, open_, high, low, close, volume in rows:
        lines.append(f"{date},{open_},{high},{low},{close},{volume}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_corporate_actions_db(data_root: Path, rows: list[tuple]) -> Path:
    db_path = data_root / "corporate_actions.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE corporate_actions ("
            "code TEXT, ex_date TEXT, event_type TEXT, previous_close REAL, "
            "reference_price REAL, cash_dividend_estimate REAL, price_factor REAL, "
            "evidence_status TEXT)"
        )
        conn.executemany(
            f"INSERT INTO corporate_actions ({', '.join(CA_COLUMNS)}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return db_path


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    """Four symbols: no corporate action, split only, cash dividend only, both."""
    root = tmp_path / "data"
    root.mkdir()
    write_day_csv(
        root,
        "NOACT",
        [
            ("2025-01-02", 10.0, 10.5, 9.5, 10.0, 100),
            ("2025-01-03", 10.0, 10.5, 9.5, 10.2, 100),
        ],
    )
    write_day_csv(
        root,
        "SPLITONLY",
        [
            ("2025-01-02", 200.0, 202.0, 198.0, 200.0, 500),
            ("2025-01-03", 100.0, 101.0, 99.0, 100.0, 900),
            ("2025-01-06", 101.0, 102.0, 100.0, 101.0, 700),
        ],
    )
    write_day_csv(
        root,
        "DIVONLY",
        [
            ("2025-01-02", 100.0, 102.0, 99.0, 100.0, 1000),
            ("2025-01-03", 96.0, 97.0, 94.0, 95.0, 1200),
            ("2025-01-06", 95.0, 99.0, 95.0, 98.0, 900),
            ("2025-01-07", 98.0, 101.0, 98.0, 101.0, 1100),
        ],
    )
    write_day_csv(
        root,
        "BOTH",
        [
            ("2025-01-02", 200.0, 202.0, 198.0, 200.0, 500),
            ("2025-01-03", 100.0, 101.0, 99.0, 100.0, 900),
            ("2025-01-06", 96.0, 97.0, 94.0, 95.0, 1200),
            ("2025-01-07", 98.0, 99.0, 97.0, 98.0, 1100),
            ("2025-01-08", 100.0, 102.0, 99.0, 101.0, 1300),
        ],
    )
    write_day_csv(
        root,
        "EXRIGHT",
        [
            ("2025-01-02", 110.0, 112.0, 108.0, 110.0, 400),
            ("2025-01-03", 100.0, 101.0, 99.0, 100.0, 600),
            ("2025-01-06", 101.0, 103.0, 100.0, 101.0, 500),
        ],
    )
    write_day_csv(
        root,
        "EXRIGHTDIV",
        [
            ("2025-01-02", 110.0, 112.0, 108.0, 110.0, 400),
            ("2025-01-03", 90.0, 92.0, 89.0, 90.0, 600),
            ("2025-01-06", 92.0, 93.0, 91.0, 92.0, 500),
            ("2025-01-07", 96.0, 97.0, 95.0, 96.0, 500),
        ],
    )
    write_day_csv(
        root,
        "CAPRED",
        [
            ("2025-01-02", 50.0, 51.0, 49.0, 50.0, 300),
            ("2025-01-03", 60.0, 61.0, 59.0, 60.0, 350),
        ],
    )
    write_day_csv(
        root,
        "CAPREDNE",
        [
            ("2025-01-02", 50.0, 51.0, 49.0, 50.0, 300),
            ("2025-01-03", 60.0, 61.0, 59.0, 60.0, 350),
        ],
    )
    write_corporate_actions_db(
        root,
        [
            ("SPLITONLY", "2025-01-03", "ETF_SPLIT", None, None, None, 0.5, "REFERENCE_PRICE_ONLY"),
            ("DIVONLY", "2025-01-03", "CASH_DIVIDEND", 100.0, 95.0, 5.0, 0.95, "FULL"),
            ("BOTH", "2025-01-03", "ETF_SPLIT", None, None, None, 0.5, "REFERENCE_PRICE_ONLY"),
            ("BOTH", "2025-01-06", "CASH_DIVIDEND", 100.0, 95.0, 5.0, 0.95, "FULL"),
            ("EXRIGHT", "2025-01-03", "EX_RIGHT", None, None, None, 0.9, "REFERENCE_PRICE_ONLY"),
            (
                "EXRIGHTDIV",
                "2025-01-03",
                "EX_RIGHT_AND_DIVIDEND",
                95.0,
                85.5,
                5.0,
                0.9,
                "REFERENCE_PRICE_ONLY",
            ),
            ("CAPRED", "2025-01-03", "CASH_CAPITAL_REDUCTION", None, None, None, 1.2, "REFERENCE_PRICE_ONLY"),
            (
                "CAPREDNE",
                "2025-01-03",
                "CASH_CAPITAL_REDUCTION",
                None,
                None,
                None,
                None,
                "REFERENCE_PRICE_ONLY",
            ),
        ],
    )
    return root


def test_no_corporate_action_leaves_signal_prices_equal_to_raw(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_all()

    df = loader.get_stock_data("NOACT")

    assert list(df["SplitAdjustmentFactor"]) == [1.0, 1.0]
    assert list(df["DividendSignalFactor"]) == [1.0, 1.0]
    assert list(df["SignalClose"]) == list(df["RawClose"])
    assert list(df["CorporateActionTypes"]) == ["", ""]
    assert list(df["SignalPricePolicy"]) == ["split_adjusted", "split_adjusted"]


def test_split_only_characterization(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_all()

    df = loader.get_stock_data("SPLITONLY")

    assert list(df["SplitAdjustmentFactor"]) == [0.5, 1.0, 1.0]
    assert list(df["SplitAdjustedClose"]) == [100.0, 100.0, 101.0]
    assert list(df["SignalClose"]) == [100.0, 100.0, 101.0]
    assert list(df["DividendSignalFactor"]) == [1.0, 1.0, 1.0]
    assert list(df["CorporateActionTypes"]) == ["", "ETF_SPLIT", ""]


def test_cash_dividend_only_characterization(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_all()

    df = loader.get_stock_data("DIVONLY")

    assert df.iloc[1]["SignalPricePolicy"] == "cash_dividend_window"
    assert df.iloc[1]["SignalClose"] == pytest.approx(95.0 / 0.95, abs=1e-4)
    assert bool(df.iloc[1]["DividendWindowActive"]) is True
    assert bool(df.iloc[3]["DividendFilled"]) is True
    assert list(df["CorporateActionTypes"]) == ["", "CASH_DIVIDEND", "", ""]


def test_split_and_cash_dividend_combined_characterization(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_all()

    df = loader.get_stock_data("BOTH")

    assert list(df["SplitAdjustmentFactor"]) == [0.5, 1.0, 1.0, 1.0, 1.0]
    assert list(df["SplitAdjustedClose"]) == [100.0, 100.0, 95.0, 98.0, 101.0]
    assert df.iloc[2]["SignalClose"] == pytest.approx(100.0, abs=1e-4)
    assert df.iloc[3]["SignalClose"] == pytest.approx(103.1579, abs=1e-4)
    assert df.iloc[4]["SignalClose"] == pytest.approx(101.0, abs=1e-4)
    assert bool(df.iloc[4]["DividendFilled"]) is True
    assert list(df["CorporateActionTypes"]) == ["", "ETF_SPLIT", "CASH_DIVIDEND", "", ""]


def test_broker_handle_split_scales_held_quantity() -> None:
    broker = Broker(initial_cash=0, fee_rate=0, tax_rate=0)
    broker.positions["2330"] = 100

    broker.handle_split("2025-01-03", {"Code": "2330", "price_factor": 0.5, "evidence_status": "REFERENCE_PRICE_ONLY"})

    assert broker.positions["2330"] == 200
    trade = broker.trades[-1]
    assert trade["action"] == "SPLIT"
    assert trade["old_qty"] == 100
    assert trade["new_qty"] == 200
    assert trade["qty"] == 100
    assert trade["price_factor"] == 0.5


def test_broker_handle_split_is_noop_without_a_held_position() -> None:
    broker = Broker(initial_cash=0, fee_rate=0, tax_rate=0)

    broker.handle_split("2025-01-03", {"Code": "2330", "price_factor": 0.5, "evidence_status": "REFERENCE_PRICE_ONLY"})

    assert broker.positions == {}
    assert broker.trades == []


def test_broker_handle_split_is_noop_for_invalid_price_factor() -> None:
    broker = Broker(initial_cash=0, fee_rate=0, tax_rate=0)
    broker.positions["2330"] = 100

    broker.handle_split("2025-01-03", {"Code": "2330", "price_factor": 0, "evidence_status": "REFERENCE_PRICE_ONLY"})

    assert broker.positions["2330"] == 100
    assert broker.trades == []


def test_ex_right_adjusts_signal_price_only(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_all()

    df = loader.get_stock_data("EXRIGHT")

    assert list(df["SplitAdjustmentFactor"]) == [0.9, 1.0, 1.0]
    assert list(df["SignalClose"]) == [99.0, 100.0, 101.0]
    assert list(df["CorporateActionTypes"]) == ["", "EX_RIGHT", ""]
    assert loader.get_warnings() == []


def test_ex_right_does_not_change_broker_share_count(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_symbols(["EXRIGHT"])

    splits = loader.get_splits_for_date(pd.Timestamp("2025-01-03"))

    assert "EXRIGHT" not in splits["Code"].astype(str).tolist()


def test_ex_right_and_dividend_applies_price_factor_then_cash_window(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_all()

    df = loader.get_stock_data("EXRIGHTDIV")

    assert list(df["SplitAdjustmentFactor"]) == [0.9, 1.0, 1.0, 1.0]
    assert df.iloc[0]["SignalClose"] == pytest.approx(99.0, abs=1e-4)
    assert df.iloc[1]["SignalClose"] == pytest.approx(100.0, abs=1e-4)
    assert df.iloc[2]["SignalClose"] == pytest.approx(102.2222, abs=1e-4)
    assert df.iloc[3]["SignalClose"] == pytest.approx(96.0, abs=1e-4)
    assert bool(df.iloc[3]["DividendFilled"]) is True
    assert list(df["CorporateActionTypes"]) == ["", "EX_RIGHT_AND_DIVIDEND", "", ""]


def test_capital_reduction_with_valid_factor_adjusts_price(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_all()

    df = loader.get_stock_data("CAPRED")

    assert list(df["SplitAdjustmentFactor"]) == [1.2, 1.0]
    assert list(df["SignalClose"]) == [60.0, 60.0]
    assert list(df["CorporateActionTypes"]) == ["", "CASH_CAPITAL_REDUCTION"]
    assert loader.get_warnings() == []


def test_capital_reduction_with_valid_factor_feeds_broker_share_count(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_symbols(["CAPRED"])
    broker = Broker(initial_cash=0, fee_rate=0, tax_rate=0)
    broker.positions["CAPRED"] = 1000

    splits = loader.get_splits_for_date(pd.Timestamp("2025-01-03"))
    for _, row in splits.iterrows():
        broker.handle_split(row["Date"], {str(key): value for key, value in row.items()})

    assert broker.positions["CAPRED"] == 833


@pytest.mark.parametrize(
    ("price_factor", "previous_close"),
    [(None, 100.0), (float("nan"), 100.0), (0.95, None), (0.95, float("nan")), (0.0, 100.0), (-0.1, 100.0)],
)
def test_cash_window_missing_scalars_preserve_raw_prices_across_gaps(
    price_factor: float | None,
    previous_close: float | None,
) -> None:
    # The ex-date is absent from the price rows. Missing scalar guards must
    # still run before numeric conversion and must not invent a cash window.
    dates = pd.to_datetime(["2025-01-02", "2025-01-06", "2025-01-08"])
    raw = pd.DataFrame({"Date": dates, **{column: [100.0, 95.0, 96.0] for column in ("Open", "High", "Low", "Close")}})
    actions = pd.DataFrame({
        "Date": [pd.Timestamp("2025-01-03")],
        "Code": ["FICTIONAL"],
        "event_type": ["CASH_DIVIDEND"],
        "price_factor": [price_factor],
        "previous_close": [previous_close],
    })
    loader = DataLoader()
    result = loader._apply_corporate_action_policy(raw, actions)
    assert result["SignalClose"].tolist() == [100.0, 95.0, 96.0]
    assert result["RawClose"].tolist() == [100.0, 95.0, 96.0]
    assert result["DividendSignalFactor"].tolist() == [1.0, 1.0, 1.0]
    assert result["DividendWindowActive"].tolist() == [False, False, False]
    assert result["DividendFilled"].tolist() == [False, False, False]
    assert loader.get_warnings() == []
    assert raw.columns.tolist() == ["Date", "Open", "High", "Low", "Close"]


def test_capital_reduction_without_valid_factor_stays_unsupported(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_all()

    df = loader.get_stock_data("CAPREDNE")

    assert list(df["SplitAdjustmentFactor"]) == [1.0, 1.0]
    assert list(df["SignalClose"]) == list(df["RawClose"])
    warnings = loader.get_warnings()
    assert any("CAPREDNE" in warning and "CASH_CAPITAL_REDUCTION" in warning for warning in warnings)


def test_capital_reduction_without_valid_factor_excluded_from_broker_feed(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_symbols(["CAPREDNE"])

    splits = loader.get_splits_for_date(pd.Timestamp("2025-01-03"))

    assert "CAPREDNE" not in splits["Code"].astype(str).tolist()


def test_corporate_action_index_takes_precedence_over_yfinance_fallback(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_all()

    df = loader.get_stock_data("DIVONLY")

    assert "Adj_Close" not in df.columns
    assert "SignalClose" in df.columns
    assert not any("yfinance" in warning for warning in loader.get_warnings())


def test_yfinance_fallback_used_and_flagged_when_index_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    write_day_csv(
        root,
        "DIVFALLBACK",
        [
            ("2025-01-02", 100.0, 102.0, 99.0, 100.0, 1000),
            ("2025-01-03", 96.0, 97.0, 94.0, 95.0, 1200),
        ],
    )
    div_df = pd.DataFrame({"Date": [pd.Timestamp("2025-01-03")], "Code": ["DIVFALLBACK"], "Dividends": [5.0]})
    div_df.to_parquet(root / "dividends.parquet")

    loader = DataLoader(str(root))
    loader.load_all()

    df = loader.get_stock_data("DIVFALLBACK")

    assert "Adj_Close" in df.columns
    assert any("yfinance" in warning and "dividends.parquet" in warning for warning in loader.get_warnings())
