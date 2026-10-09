"""Headless research must remain usable without either optional viewer stack."""

import subprocess
import sys
from pathlib import Path


def test_headless_readers_work_without_viewer_imports(tmp_path: Path) -> None:
    # A fresh interpreter catches eager imports even in a developer environment
    # where both optional groups have already been installed.
    probe = r"""
import importlib.abc
import json
import sys
from pathlib import Path

class NoViewer(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"panel", "plotly", "fastapi"}:
            raise AssertionError(f"headless path imported {fullname}")

sys.meta_path.insert(0, NoViewer())
from research_lab import dashboard_core
from research_core.evidence import task_catalog
from scripts import stock_research_query
from StockProject import backtest_cli

root = Path(sys.argv[1])
task = root / "synthetic"
task.mkdir()
(task / "summary.json").write_text(json.dumps({"metrics": {}, "trades": []}))
dashboard_core.TASKS_ROOT = root
stock_research_query.TASKS_ROOT = root
assert dashboard_core.discover_task_index()[0]["task"] == "synthetic"
assert dashboard_core.load_task_bundle("synthetic")["summary"]["trades"] == []
assert dashboard_core.capital_mode_pool_verdict("unconstrained", {})
assert stock_research_query.list_task_trades("synthetic")["trades"] == []
assert task_catalog(root)
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
