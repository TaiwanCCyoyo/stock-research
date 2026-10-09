from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from StockProject.backtest_cli import build_capital_mode_comparison, build_summary, write_comparison_artifacts


class DummyStrategy:
    __name__ = "DummyStrategy"


class DummyLoader:
    corporate_action_db = None

    def get_warnings(self) -> list[str]:
        return []

    def get_stock_data(self, code: str | None, adjust: bool = True) -> Any:
        import pandas as pd

        return pd.DataFrame([
            {
                "Date": pd.Timestamp("2025-01-02"),
                "Close": 100.0,
                "RawClose": 100.0,
                "SplitAdjustedClose": 100.0,
            }
        ])


class DummyBroker:
    cash = 1000.0
    positions: dict[str, int] = {}
    trades: list[dict[str, Any]] = []
    fee_rate = 0.0
    tax_rate = 0.0
    per_stock_initial_cash = None
    cash_blocked_entry_count = 3


class DummyEngine:
    loader = DummyLoader()
    data_cache: dict[str, Any] = {}
    equity_curve = [{"date": "2025-01-02", "equity": 1000.0}]
    price_curve = [{"date": "2025-01-02", "prices": {"A": 100.0}}]


def _args(tmp_path: Path, capital_mode: str) -> argparse.Namespace:
    return argparse.Namespace(
        output=str(tmp_path / "summary.json"),
        data_path=None,
        strategy="strategy.py",
        start="2025-01-01",
        end="2025-01-31",
        cash=1000.0,
        capital_mode=capital_mode,
        benchmark_code="0050",
        strategy_params={},
    )


def test_unconstrained_summary_nulls_return_dependent_metrics(tmp_path: Path) -> None:
    summary = build_summary(
        _args(tmp_path, "unconstrained"),
        ["A"],
        DummyStrategy,
        DummyBroker(),
        DummyEngine(),
        {"final_value": 1200.0, "total_pnl": 200.0, "return_rate": 20.0},
    )

    metrics = summary["metrics"]
    assert metrics["return_rate"] is None
    assert metrics["calmar_ratio"] is None
    assert metrics["max_drawdown_rate"] is None
    assert metrics["excess_return_rate"] is None
    assert metrics["cash_blocked_entry_count"] == 3
    assert metrics["trade_count"] == 0


def test_build_summary_flags_symbols_with_partial_trading_day_gaps(tmp_path: Path) -> None:
    import pandas as pd

    def frame(dates: list[str]) -> Any:
        return pd.DataFrame({
            "Date": [pd.Timestamp(d) for d in dates],
            "Close": [100.0] * len(dates),
            "RawClose": [100.0] * len(dates),
            "SplitAdjustedClose": [100.0] * len(dates),
        })

    calendar_dates = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09"]
    engine = DummyEngine()
    engine.data_cache = {
        "A": frame(calendar_dates),  # full coverage, anchors the calendar
        # B and C both trade on the first and last calendar day (so their own trading
        # span covers the full calendar) but are missing days in between -- genuine
        # gaps within their own span, not just a shorter listing history.
        "B": frame([calendar_dates[0]] + calendar_dates[3:]),  # missing 2 internal days -> under the default threshold (3)
        "C": frame([calendar_dates[0], calendar_dates[-1]]),  # missing 4 internal days -> over the default threshold (3)
    }

    summary = build_summary(
        _args(tmp_path, "shared"),
        ["A", "B", "C", "D"],  # D is requested but never loaded -> fully missing, not partial
        DummyStrategy,
        DummyBroker(),
        engine,
        {"final_value": 1000.0, "total_pnl": 0.0, "return_rate": 0.0},
    )

    partial = {item["code"]: item["missing_trading_day_count"] for item in summary["partial_data_symbols"]}
    assert partial == {"C": 4}
    assert any("C" in warning for warning in summary["warnings"])


def test_build_summary_does_not_flag_a_late_listing_as_a_data_gap(tmp_path: Path) -> None:
    """A symbol that only started trading partway through the window (e.g. a late
    listing) must not be flagged just because it lacks days that predate its own
    first trade -- only real gaps within its own trading span count."""
    import pandas as pd

    def frame(dates: list[str]) -> Any:
        return pd.DataFrame({
            "Date": [pd.Timestamp(d) for d in dates],
            "Close": [100.0] * len(dates),
            "RawClose": [100.0] * len(dates),
            "SplitAdjustedClose": [100.0] * len(dates),
        })

    calendar_dates = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09"]
    engine = DummyEngine()
    engine.data_cache = {
        "A": frame(calendar_dates),  # full coverage, anchors the calendar
        "E": frame(calendar_dates[3:]),  # listed late; complete for its own span
    }

    args = _args(tmp_path, "shared")
    args.partial_data_gap_threshold = 1  # low threshold: any un-clamped leakage would trip it

    summary = build_summary(
        args,
        ["A", "E"],
        DummyStrategy,
        DummyBroker(),
        engine,
        {"final_value": 1000.0, "total_pnl": 0.0, "return_rate": 0.0},
    )

    assert summary["partial_data_symbols"] == []


def test_build_capital_mode_comparison_flags_contention_symbols() -> None:
    shared = {
        "run": {"capital_mode": "shared"},
        "metrics": {"return_rate": -1.0, "max_drawdown_rate": -12.5, "win_rate": 20.0, "payoff_ratio": 0.5, "expectancy": -10.0, "cash_blocked_entry_count": 2},
        "symbols": {"A": {"total_pnl": -50.0}, "B": {"total_pnl": 10.0}},
    }
    per_stock = {
        "run": {"capital_mode": "per_stock"},
        "metrics": {"return_rate": 3.0, "max_drawdown_rate": -8.0, "win_rate": 60.0, "payoff_ratio": 2.0, "expectancy": 30.0, "cash_blocked_entry_count": 0},
        "symbols": {"A": {"total_pnl": 20.0}, "B": {"total_pnl": -5.0}},
    }
    unconstrained = {
        "run": {"capital_mode": "unconstrained"},
        "metrics": {"return_rate": None, "max_drawdown_rate": None, "win_rate": 70.0, "payoff_ratio": 2.5, "expectancy": 40.0, "cash_blocked_entry_count": 0},
        "symbols": {"A": {"total_pnl": 25.0}},
    }

    comparison = build_capital_mode_comparison({"shared": shared, "per_stock": per_stock, "unconstrained": unconstrained})

    assert comparison["modes"]["shared"]["cash_blocked_entry_count"] == 2
    assert comparison["modes"]["shared"]["max_drawdown_rate"] == -12.5
    assert comparison["modes"]["per_stock"]["max_drawdown_rate"] == -8.0
    assert comparison["modes"]["unconstrained"]["max_drawdown_rate"] is None
    assert comparison["symbols"]["A"]["contention_affected"] is True
    assert comparison["symbols"]["B"]["contention_affected"] is False


def test_write_comparison_artifacts_writes_option_a_files(tmp_path: Path) -> None:
    summaries = {
        "shared": {"run": {"capital_mode": "shared"}, "metrics": {}, "symbols": {}},
        "per_stock": {"run": {"capital_mode": "per_stock"}, "metrics": {}, "symbols": {}},
        "unconstrained": {"run": {"capital_mode": "unconstrained"}, "metrics": {}, "symbols": {}},
    }
    output_path = tmp_path / "summary.json"

    write_comparison_artifacts(output_path, summaries)

    assert json.loads((tmp_path / "summary_shared.json").read_text(encoding="utf-8")) == summaries["shared"]
    assert (tmp_path / "summary_per_stock.json").is_file()
    assert (tmp_path / "summary_unconstrained.json").is_file()
    assert (tmp_path / "comparison.json").is_file()
    assert json.loads(output_path.read_text(encoding="utf-8")) == summaries["shared"]
