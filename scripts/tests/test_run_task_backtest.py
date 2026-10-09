from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from scripts.run_task_backtest import run_backtest


def test_run_backtest_rejects_output_outside_task_runs(tmp_path: Path) -> None:
    """A caller such as the sweep runner cannot escape task-local run outputs."""
    task_root = tmp_path / "task"
    (task_root / "runs").mkdir(parents=True)

    with pytest.raises(SystemExit):
        run_backtest(
            argparse.Namespace(),
            task_root,
            task_root / "candidates" / "strategy.py",
            tmp_path / "outside.json",
        )
