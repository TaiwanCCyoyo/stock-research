from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import pytest

from research_core import derived_features, live_producer, maintained_adjusted_daily, run_receipt, technical_daily_v1
from research_core.artifact_store import read_json, write_json
from research_core.shared_data import ENV_KEY


def _prepared(days: int = 320, gap: int | None = 150, seed: int = 7) -> pd.DataFrame:
    """A random-walk symbol with an invalid row at `gap`, shaped like a stored basis row set."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=days)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, days)))
    high, low = close * (1 + rng.uniform(0, 0.03, days)), close * (1 - rng.uniform(0, 0.03, days))
    opening = np.clip(close * (1 + rng.normal(0, 0.01, days)), low, high)
    frame = pd.DataFrame({"Open": opening, "High": high, "Low": low, "Close": close, "Turnover": rng.uniform(1e3, 5e3, days), "Quality": True}, index=dates)
    if gap is not None:
        frame.iloc[gap, frame.columns.get_loc("Close")] = np.nan
        frame.iloc[gap, frame.columns.get_loc("Quality")] = False
    return frame


def test_daily_values_are_causal_and_delegate_to_the_shared_kernels() -> None:
    prepared = _prepared()
    daily, pivots = technical_daily_v1.compute_technical("9999", prepared)

    assert daily["Date"].tolist() == prepared.index.tolist(), "one output row per input row, none dropped or filled"
    shared_daily, shared_pivots = derived_features.compute_features(prepared)
    for column in ("ATR14", "SMA20", "EMA60", "BB20_Upper"):
        pd.testing.assert_series_equal(daily[column], shared_daily[column].reset_index(drop=True), check_names=False)
    assert pivots["confirmed_at"].tolist() == shared_pivots["confirmed_at"].tolist()
    # Truncating the input never changes an earlier row: no column reads a later day.
    cut = 260
    prefix, _ = technical_daily_v1.compute_technical("9999", prepared.iloc[:cut])
    pd.testing.assert_frame_equal(prefix, daily.iloc[:cut])


def test_invalid_rows_reset_every_window() -> None:
    prepared = _prepared(days=320, gap=30)
    daily, _ = technical_daily_v1.compute_technical("9999", prepared)

    assert daily.loc[30, list(technical_daily_v1.INDICATOR_COLUMNS)].isna().all()
    assert daily["SMA20"].iloc[31:50].isna().all() and daily["SMA20"].notna().iloc[50]
    assert daily["SMA240"].iloc[:270].isna().all() and daily["SMA240"].notna().iloc[270], "240 consecutive valid rows after the gap"
    expected = prepared["Close"].iloc[31:271].mean()
    assert daily["SMA240"].iloc[270] == pytest.approx(expected, rel=1e-12)


def test_daily_pivot_columns_are_known_only_from_confirmation() -> None:
    daily, pivots = technical_daily_v1.compute_technical("9999", _prepared(gap=None))
    highs = pivots.loc[(pivots["k"] == 1.5) & (pivots["kind"] == "high")]
    assert len(highs) >= 2

    dates = daily.set_index("Date")
    assert set(dates.index[dates["ConfirmedHigh_k15"]]) == set(highs["confirmed_at"])
    first = highs.iloc[0]
    assert dates.loc[: first["confirmed_at"] - pd.Timedelta(days=1), "LastHigh_k15"].isna().all()
    assert dates.loc[first["confirmed_at"], "LastHigh_k15"] == first["price"]
    assert first["extreme_date"] < first["confirmed_at"], "the extreme is found only afterwards"


OHLC_COLUMNS = ("Open", "High", "Low", "Close")


def _producer(root: Path, days: int = 300) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    prepared = _prepared(days=days, gap=None)
    rows = [
        {"Code": code, "Date": day, **{column: getattr(row, column) * scale for column in OHLC_COLUMNS}, "Volume": 1000.0, "Source": "official"}
        for code, scale in (("2330", 1.0), ("6488", 0.5))
        for day, row in prepared.iterrows()
    ]
    pd.DataFrame(rows).to_parquet(root / "price_daily.parquet", index=False)
    with sqlite3.connect(root / "corporate_actions.sqlite") as connection:
        connection.execute("CREATE TABLE corporate_actions (code TEXT, ex_date TEXT, event_type TEXT, price_factor REAL)")
        ex_date = cast(pd.Timestamp, prepared.index[200]).date().isoformat()
        connection.execute("INSERT INTO corporate_actions VALUES ('2330', ?, 'CASH_DIVIDEND', 0.97)", (ex_date,))
    connection.close()
    return root


@pytest.fixture()
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    producer = _producer(tmp_path / "producer data")
    shared = tmp_path / "shared root"
    shared.mkdir()
    monkeypatch.setenv("STOCK_PRODUCER_DATA_ROOT", str(producer))
    monkeypatch.setenv(ENV_KEY, str(shared))
    monkeypatch.setattr(run_receipt, "assert_producer_idle", lambda now=None: None)
    monkeypatch.setattr(live_producer, "running_producer_tasks", lambda: [])
    return producer, shared


def test_update_stores_technical_tables_that_join_the_adjusted_prices(environment: tuple[Path, Path]) -> None:
    producer, _ = environment
    published = maintained_adjusted_daily.update(producer_root=producer)

    daily, record = maintained_adjusted_daily.read_technical(codes=["2330"], columns=["SMA20", "LastLow_k15"], prices=["Close", "Quality"])
    prices, _ = maintained_adjusted_daily.read_adjusted_daily("reference_factor_adjusted", codes=["2330"])
    assert record["generation"] == published["generation"] and record["definition"] == "technical-daily.v1"
    assert record["prices"]["generation"] == published["generation"], "indicators and prices come from one generation"
    assert daily[["Code", "Date", "Close"]].equals(prices[["Code", "Date", "Close"]])
    expected, expected_pivots = technical_daily_v1.compute_technical("2330", prices.set_index("Date"))
    pd.testing.assert_series_equal(daily["SMA20"], expected["SMA20"])

    pivots, _ = maintained_adjusted_daily.read_technical("pivots", codes=["2330"])
    pd.testing.assert_frame_equal(pivots, expected_pivots.reset_index(drop=True), check_dtype=False)
    status = maintained_adjusted_daily.current_generation()
    tables = status["technical"]["tables"]
    assert tables["daily"]["rows"] == status["bases"]["reference_factor_adjusted"]["rows"]
    assert status["technical"]["definition"]["basis"] == "reference_factor_adjusted"


def test_technical_reads_refuse_a_replaced_file_and_an_older_generation(environment: tuple[Path, Path]) -> None:
    producer, _ = environment
    maintained_adjusted_daily.update(producer_root=producer)
    status = maintained_adjusted_daily.current_generation()
    directory = Path(status["path"])

    target = directory / "technical_pivots.parquet"
    target.write_bytes(target.read_bytes() + b"x")
    with pytest.raises(ValueError, match="does not match the bytes/SHA-256"):
        maintained_adjusted_daily.read_technical("pivots")

    # A generation built before technical tables existed is refused, not read as empty.
    recorded = read_json(directory / "status.json")
    del recorded["technical"]
    (directory / "status.json").unlink()
    write_json(directory / "status.json", recorded)
    with pytest.raises(ValueError, match="has no technical tables"):
        maintained_adjusted_daily.read_technical(generation=status["generation"])
