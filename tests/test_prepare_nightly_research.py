import argparse
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from scripts import prepare_nightly_research


def write_price_csv(data_root: Path, code: str = "2352") -> None:
    data_root.mkdir(parents=True)
    (data_root / f"{code}_day.csv").write_text(
        "Date,Open,High,Low,Close\n2025-01-02,10,12,9,11\n",
        encoding="utf-8",
    )


def test_data_audit_prefers_relative_paths(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    data_root = tmp_path / "stock-data-downloader" / "data"
    write_price_csv(data_root)

    audit = prepare_nightly_research.build_data_audit(data_root, ["2352"])

    assert audit["data_path"] == "stock-data-downloader/data"
    assert audit["price_file"] == "stock-data-downloader/data"


def test_template_flag_is_rejected_with_a_pointer_to_the_experiment_spec_flow() -> None:
    with pytest.raises(SystemExit):
        prepare_nightly_research.reject_retired_template_flag("two-b")


def test_template_flag_rejected_regardless_of_value() -> None:
    with pytest.raises(SystemExit):
        prepare_nightly_research.reject_retired_template_flag("none")


def test_omitted_template_flag_does_not_raise() -> None:
    prepare_nightly_research.reject_retired_template_flag(None)


def make_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "task": "demo-task",
        "codes": "2352",
        "start": "2022-01-01",
        "end": None,
        "data_path": "stock-data-downloader/data",
        "objective": None,
        "name": None,
        "template": None,
        "force": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_create_nightly_task_no_longer_writes_next_prompt(monkeypatch: MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = tmp_path / "repo"
    data_root = repo_root / "stock-data-downloader" / "data"
    write_price_csv(data_root, code="2352")
    monkeypatch.chdir(repo_root)
    monkeypatch.setattr(prepare_nightly_research, "REPO_ROOT", repo_root)
    monkeypatch.setattr(prepare_nightly_research, "TASKS_ROOT", repo_root / "tasks")

    prepare_nightly_research.create_nightly_task(make_args(name="Demo Title"))

    task_root = repo_root / "tasks" / "demo-task"
    assert (task_root / "mission.md").is_file()
    assert (task_root / "data_audit.json").is_file()
    assert (task_root / "research_dashboard" / "title.txt").read_text(encoding="utf-8") == "Demo Title"
    assert not (task_root / "next_prompt.md").exists()

    output = capsys.readouterr().out
    assert "next_prompt" not in output
    assert "seeded" not in output


def test_create_nightly_task_rejects_template_flag() -> None:
    with pytest.raises(SystemExit):
        prepare_nightly_research.create_nightly_task(make_args(template="two-b"))
