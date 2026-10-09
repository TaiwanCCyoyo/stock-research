"""Lazy task discovery: lightweight index for the selector, full bundle on demand."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pytest import MonkeyPatch

from research_lab import dashboard_core, display


def make_task_dir(
    tasks_root: Path,
    task_id: str,
    metrics: dict | None = None,
    mtime: float | None = None,
    title: str | None = None,
) -> Path:
    root = tasks_root / task_id
    root.mkdir(parents=True)
    (root / "summary.json").write_text(
        json.dumps({"metrics": metrics or {"return_rate": 0.1}, "trades": []}),
        encoding="utf-8",
    )
    if title is not None:
        title_dir = root / "research_dashboard"
        title_dir.mkdir(parents=True)
        (title_dir / "title.txt").write_text(title, encoding="utf-8")
    if mtime is not None:
        os.utime(root, (mtime, mtime))
    return root


def test_discover_task_index_lists_tasks_without_parsing_summary(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    make_task_dir(tmp_path, "task-a", mtime=1000.0)
    make_task_dir(tmp_path, "task-b", mtime=2000.0)
    (tmp_path / "not-a-task").mkdir()
    monkeypatch.setattr(dashboard_core, "TASKS_ROOT", tmp_path)

    def forbid_read_json(*args: object, **kwargs: object) -> dict:
        raise AssertionError("discover_task_index must not parse summary.json")

    monkeypatch.setattr(dashboard_core, "read_json", forbid_read_json)

    rows = dashboard_core.discover_task_index()

    assert [row["task"] for row in rows] == ["task-b", "task-a"]


def test_discover_task_index_reads_title_without_parsing_summary(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    make_task_dir(tmp_path, "task-a", mtime=1000.0, title="人類可讀標題")
    make_task_dir(tmp_path, "task-b", mtime=2000.0)
    monkeypatch.setattr(dashboard_core, "TASKS_ROOT", tmp_path)

    def forbid_read_json(*args: object, **kwargs: object) -> dict:
        raise AssertionError("discover_task_index must not parse summary.json")

    monkeypatch.setattr(dashboard_core, "read_json", forbid_read_json)

    rows = {row["task"]: row["title"] for row in dashboard_core.discover_task_index()}

    assert rows["task-a"] == "人類可讀標題"
    assert rows["task-b"] == "task-b"


def test_discover_task_index_reflects_new_and_removed_tasks(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """The index is rebuilt from the directory on each call, so it is never stale."""
    monkeypatch.setattr(dashboard_core, "TASKS_ROOT", tmp_path)
    make_task_dir(tmp_path, "task-a", mtime=1000.0)
    assert [row["task"] for row in dashboard_core.discover_task_index()] == ["task-a"]

    make_task_dir(tmp_path, "task-b", mtime=2000.0)
    assert [row["task"] for row in dashboard_core.discover_task_index()] == ["task-b", "task-a"]

    (tmp_path / "task-a" / "summary.json").unlink()
    assert [row["task"] for row in dashboard_core.discover_task_index()] == ["task-b"]


def test_task_options_accepts_index_rows(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dashboard_core, "TASKS_ROOT", tmp_path)
    make_task_dir(tmp_path, "task-a", mtime=1000.0)

    options = dashboard_core.task_options(dashboard_core.discover_task_index())

    assert options == {"task-a": "task-a"}


def test_load_task_summary_reads_selected_task(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dashboard_core, "TASKS_ROOT", tmp_path)
    make_task_dir(tmp_path, "task-a", metrics={"return_rate": 0.42})

    summary = dashboard_core.load_task_summary("task-a")

    assert summary["metrics"]["return_rate"] == 0.42


def test_load_task_bundle_still_loads_full_bundle_for_index_task(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dashboard_core, "TASKS_ROOT", tmp_path)
    make_task_dir(tmp_path, "task-a", metrics={"return_rate": 0.42})

    task_id = dashboard_core.discover_task_index()[0]["task"]
    bundle = dashboard_core.load_task_bundle(task_id)

    assert bundle["task"] == "task-a"
    assert bundle["summary"]["metrics"]["return_rate"] == 0.42


def test_load_task_bundle_includes_title_and_falls_back_to_task_id(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dashboard_core, "TASKS_ROOT", tmp_path)
    make_task_dir(tmp_path, "task-a", title="人類可讀標題")
    make_task_dir(tmp_path, "task-b")

    assert dashboard_core.load_task_bundle("task-a")["title"] == "人類可讀標題"
    assert dashboard_core.load_task_bundle("task-b")["title"] == "task-b"


def test_load_task_bundle_stock_names_uses_mapping_for_referenced_codes_only(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dashboard_core, "TASKS_ROOT", tmp_path)
    root = make_task_dir(tmp_path, "task-a")
    (root / "summary.json").write_text(
        json.dumps({"run": {"codes": ["2330"]}, "trades": [{"code": "2330"}]}),
        encoding="utf-8",
    )
    mapping_path = tmp_path / "stock_symbol_mapping.json5"
    mapping_path.write_text('{"2330": "台積電", "9999": "他股"}', encoding="utf-8")
    monkeypatch.setattr(display, "SYMBOL_MAPPING_PATH", mapping_path)
    display.stock_names.cache_clear()

    bundle = dashboard_core.load_task_bundle("task-a")

    assert bundle["stock_names"] == {"2330": "台積電"}
    display.stock_names.cache_clear()


def test_load_task_bundle_stock_names_empty_when_mapping_missing(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dashboard_core, "TASKS_ROOT", tmp_path)
    root = make_task_dir(tmp_path, "task-a")
    (root / "summary.json").write_text(json.dumps({"run": {"codes": ["2330"]}}), encoding="utf-8")
    monkeypatch.setattr(display, "SYMBOL_MAPPING_PATH", tmp_path / "missing.json5")
    display.stock_names.cache_clear()

    bundle = dashboard_core.load_task_bundle("task-a")

    assert bundle["stock_names"] == {}
    display.stock_names.cache_clear()


def test_load_task_bundle_stock_names_includes_mode_summary_codes(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dashboard_core, "TASKS_ROOT", tmp_path)
    root = make_task_dir(tmp_path, "task-a")
    (root / "summary.json").write_text(json.dumps({"run": {"codes": ["2330"]}}), encoding="utf-8")
    (root / "summary_shared.json").write_text(
        json.dumps({"run": {"codes": []}, "trades": [{"code": "2352"}]}),
        encoding="utf-8",
    )
    mapping_path = tmp_path / "stock_symbol_mapping.json5"
    mapping_path.write_text('{"2330": "台積電", "2352": "燦坤"}', encoding="utf-8")
    monkeypatch.setattr(display, "SYMBOL_MAPPING_PATH", mapping_path)
    display.stock_names.cache_clear()

    bundle = dashboard_core.load_task_bundle("task-a")

    assert bundle["stock_names"] == {"2330": "台積電", "2352": "燦坤"}
    display.stock_names.cache_clear()
