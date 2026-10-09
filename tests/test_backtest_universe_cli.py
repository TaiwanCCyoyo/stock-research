from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from StockProject.backtest_cli import build_summary, build_universe_comparison, write_universe_comparison_artifacts


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
    cash_blocked_entry_count = 0


class DummyEngine:
    loader = DummyLoader()
    data_cache: dict[str, Any] = {}
    equity_curve = [{"date": "2025-01-02", "equity": 1000.0}]
    price_curve = [{"date": "2025-01-02", "prices": {"A": 100.0}}]


def _args(tmp_path: Path, universe_name: str | None) -> argparse.Namespace:
    args = argparse.Namespace(
        output=str(tmp_path / "summary.json"),
        data_path=None,
        strategy="strategy.py",
        start="2025-01-01",
        end="2025-01-31",
        cash=1000.0,
        capital_mode="shared",
        benchmark_code="0050",
        strategy_params={},
    )
    args.universe_name = universe_name
    return args


def test_build_summary_records_universe_name_when_present(tmp_path: Path) -> None:
    summary = build_summary(
        _args(tmp_path, "semiconductor"),
        ["A"],
        DummyStrategy,
        DummyBroker(),
        DummyEngine(),
        {"final_value": 1200.0, "total_pnl": 200.0, "return_rate": 20.0},
    )

    assert summary["run"]["universe"] == "semiconductor"


def test_build_summary_records_no_universe_for_plain_codes(tmp_path: Path) -> None:
    summary = build_summary(
        _args(tmp_path, None),
        ["A"],
        DummyStrategy,
        DummyBroker(),
        DummyEngine(),
        {"final_value": 1200.0, "total_pnl": 200.0, "return_rate": 20.0},
    )

    assert summary["run"]["universe"] is None


def test_build_universe_comparison_reports_headline_metrics_per_universe() -> None:
    semis = {
        "run": {"codes": ["2330", "2454"]},
        "metrics": {"return_rate": 12.0, "max_drawdown_rate": -5.0, "win_rate": 60.0, "payoff_ratio": 2.0, "expectancy": 5.0, "cash_blocked_entry_count": 0},
    }
    blue_chips = {
        "run": {"codes": ["2330", "2317"]},
        "metrics": {"return_rate": 8.0, "max_drawdown_rate": -3.0, "win_rate": 55.0, "payoff_ratio": 1.5, "expectancy": 3.0, "cash_blocked_entry_count": 1},
    }

    comparison = build_universe_comparison({"semiconductor": semis, "core_blue_chips": blue_chips})

    assert comparison["universes"]["semiconductor"]["return_rate"] == 12.0
    assert comparison["universes"]["semiconductor"]["codes"] == ["2330", "2454"]
    assert comparison["universes"]["core_blue_chips"]["max_drawdown_rate"] == -3.0


def test_write_universe_comparison_artifacts_writes_option_a_files(tmp_path: Path) -> None:
    summaries = {
        "semiconductor": {"run": {"codes": ["2330"]}, "metrics": {}},
        "core_blue_chips": {"run": {"codes": ["2330", "2317"]}, "metrics": {}},
    }
    output_path = tmp_path / "summary.json"

    write_universe_comparison_artifacts(output_path, summaries, default_universe="semiconductor")

    assert json.loads((tmp_path / "summary_semiconductor.json").read_text(encoding="utf-8")) == summaries["semiconductor"]
    assert (tmp_path / "summary_core_blue_chips.json").is_file()
    assert (tmp_path / "comparison.json").is_file()
    assert json.loads(output_path.read_text(encoding="utf-8")) == summaries["semiconductor"]
