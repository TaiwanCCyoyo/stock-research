"""The optional legacy export still renders synthetic historical artifacts."""

import json
from pathlib import Path

from pytest import MonkeyPatch

from research_lab import dashboard_core
from scripts.build_research_dashboard import build_site


def test_static_export_preserves_input_and_renders_task(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    task = tasks / "synthetic"
    task.mkdir(parents=True)
    summary = task / "summary.json"
    original = json.dumps({
        "strategy": {"name": "TaskSimpleBuyHold", "params": {}},
        "run": {"codes": [], "initial_cash": 2000000},
        "metrics": {"return_rate": 0.0, "trade_count": 0},
        "portfolio": {"equity_curve": []},
        "trades": [],
    })
    summary.write_text(original, encoding="utf-8")
    site = tmp_path / "site"
    monkeypatch.setattr(dashboard_core, "TASKS_ROOT", tasks)
    monkeypatch.setattr(dashboard_core, "SITE_ROOT", site)

    assert build_site(site) == site
    assert (site / "index.html").is_file()
    assert "synthetic" in (site / "synthetic.html").read_text(encoding="utf-8")
    assert summary.read_text(encoding="utf-8") == original
