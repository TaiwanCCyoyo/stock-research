from __future__ import annotations

import argparse
from pathlib import Path

from pytest import MonkeyPatch

from scripts import run_task_backtest, run_task_param_sweep


def test_run_task_backtest_passes_capital_mode_all(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    output_path = runs_root / "summary.json"
    output_path.write_text(
        '{"schema_version":"1.0","generated_at":"2025-01-02T00:00:00","run":{},"strategy":{"name":"S"},"data":{},"metrics":{"return_rate":null,"final_value":1,"trade_count":0},"portfolio":{},"trades":[],"warnings":[]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(run_task_backtest, "APP_ROOT", tmp_path)
    monkeypatch.setattr(run_task_backtest.subprocess, "run", lambda command, cwd, check: commands.append(command))
    monkeypatch.setattr(run_task_backtest, "collect_run_artifacts", lambda task_root, output_path, summary: {})

    args = argparse.Namespace(
        codes="2330",
        start="2025-01-01",
        end=None,
        cash=1000.0,
        capital_mode="all",
        benchmark_code="0050",
        data_path="data",
        params_json=None,
        params_file=None,
        promote_summary=False,
    )

    run_task_backtest.run_backtest(args, tmp_path, tmp_path / "candidates" / "s.py", output_path)

    capital_index = commands[0].index("--capital-mode")
    assert commands[0][capital_index + 1] == "all"


def test_param_sweep_build_run_args_preserves_capital_mode_all() -> None:
    args = argparse.Namespace(
        codes="2330",
        start="2025-01-01",
        end=None,
        cash=1000.0,
        capital_mode="all",
        benchmark_code="0050",
        data_path="data",
    )

    run_args = run_task_param_sweep.build_run_args(args, {"window": 5})

    assert run_args.capital_mode == "all"


def test_promote_comparison_artifacts_copies_option_a_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    output_path = run_dir / "summary.json"
    for name in ["summary_shared.json", "summary_per_stock.json", "summary_unconstrained.json", "comparison.json"]:
        (run_dir / name).write_text(f'{{"name":"{name}"}}', encoding="utf-8")

    run_task_backtest.promote_comparison_artifacts(tmp_path, output_path)

    assert (tmp_path / "summary_shared.json").is_file()
    assert (tmp_path / "summary_per_stock.json").is_file()
    assert (tmp_path / "summary_unconstrained.json").is_file()
    assert (tmp_path / "comparison.json").is_file()
