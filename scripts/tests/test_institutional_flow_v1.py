from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

import pandas as pd
import pytest

import research_core.institutional_flow_v1 as flow


def _rows(calendar: pd.DatetimeIndex, *, net: float = 10.0, volume: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame({
        "code": "2330",
        "date": calendar.strftime("%Y-%m-%d"),
        "market": "TWSE",
        "source": "synthetic-v1",
        "three_institutions_net": net,
        "foreign_total_net": net,
        "trust_net": net,
        "volume": volume,
    })


def _coverage(calendar: pd.DatetimeIndex, source: str = "synthetic-v1") -> dict[str, dict[str, object]]:
    return {"TWSE": {"from": cast(pd.Timestamp, calendar[0]).date().isoformat(), "to": cast(pd.Timestamp, calendar[-1]).date().isoformat(), "source": source}}


def test_institutional_window_uses_prior_sixty_sessions_and_shares() -> None:
    calendar = pd.date_range("2024-01-02", periods=61)
    rows = _rows(calendar)
    # A massive t-day buy would pass if accidentally included; 60 prior days yield 10% of shares.
    rows.loc[60, "three_institutions_net"] = 100_000
    volume = pd.Series(100.0, index=calendar)
    result = flow.institutional_daily(rows, calendar, "2330", "TWSE", volume, _coverage(calendar))

    assert result.iloc[:60]["INST"].eq(-1).all()
    assert result.iloc[60]["three_institutions_net_buy_fraction"] == 1.0
    assert result.iloc[60]["three_institutions_net_volume_ratio"] == 0.1
    assert result.iloc[60]["INST"] == 1


def test_missing_day_is_unknown_and_negative_net_counts_as_non_buy() -> None:
    calendar = pd.date_range("2024-01-02", periods=82)
    rows = _rows(calendar)
    rows.loc[30, "three_institutions_net"] = -10
    rows = rows.drop(index=20)
    volume = pd.Series(100.0, index=calendar)
    result = flow.institutional_daily(rows, calendar, "2330", "TWSE", volume, _coverage(calendar))

    assert result.iloc[60]["INST"] == -1  # the omitted row lies inside t-60..t-1
    # Once the missing session ages out, the negative net remains a known non-buy.
    assert result.iloc[81]["three_institutions_net_buy_fraction"] < 1.0
    assert result.iloc[81]["three_institutions_net_volume_ratio"] == pytest.approx(580 / 6000)
    assert result.iloc[81]["INST"] == 1


def test_continuous_coverage_requires_ok_checkpoint_exact_rows_and_one_source() -> None:
    calendar = pd.date_range("2024-01-02", periods=6)
    rows = pd.concat([_rows(pd.DatetimeIndex([day])) for day in calendar], ignore_index=True)
    logs = pd.DataFrame({
        "market": ["TWSE"] * 6,
        "date": calendar.strftime("%Y-%m-%d"),
        "status": ["ok", "ok", "ok", "failed", "ok", "ok"],
        "row_count": [1, 1, 1, 1, 2, 1],
    })
    # Day 2 also has conflicting actual sources; day 4 has checkpoint row_count mismatch.
    rows.loc[1, "source"] = "another-source"
    coverage = flow.continuous_coverage(logs, rows, calendar)

    assert coverage["TWSE"]["from"] == cast(pd.Timestamp, calendar[5]).date().isoformat()
    assert coverage["TWSE"]["to"] == cast(pd.Timestamp, calendar[5]).date().isoformat()
    assert coverage["TWSE"]["sessions"] == 1
    assert coverage["TWSE"]["earlier_complete_sessions_excluded"] == 3


def test_read_institutional_uses_configured_root_and_idle_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "institutional.sqlite"
    calendar = pd.date_range("2024-01-02", periods=2)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE institutional_daily (market TEXT, date TEXT, code TEXT, source TEXT, "
            "three_institutions_net REAL, foreign_total_net REAL, trust_net REAL)"
        )
        connection.execute("CREATE TABLE institutional_fetch_log (market TEXT, date TEXT, status TEXT, row_count INTEGER)")
        connection.execute("INSERT INTO institutional_daily VALUES ('TWSE','2024-01-02','2330','synthetic-v1',10,8,2)")
        connection.execute("INSERT INTO institutional_fetch_log VALUES ('TWSE','2024-01-02','ok',1)")

    calls: list[str] = []
    monkeypatch.setattr(flow, "producer_data_root", lambda: tmp_path)
    result = flow.read_institutional(calendar, idle_check=lambda: calls.append("idle"))

    assert result.path == path
    assert calls == ["idle", "idle"]
    assert result.rows.loc[0, "three_institutions_net"] == 10  # raw shares, no lot conversion
    assert result.coverage["TWSE"]["from"] == cast(pd.Timestamp, calendar[0]).date().isoformat()  # ends at last real checkpoint
