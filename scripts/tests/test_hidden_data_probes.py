from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_core import research_data_paths, shared_data


@pytest.mark.parametrize("flag_present", [True, False])
def test_shared_worktree_probe_is_hidden_and_keeps_parsing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flag_present: bool) -> None:
    expected_flag = 0x08000000 if flag_present else 0
    if flag_present:
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", expected_flag, raising=False)
    else:
        monkeypatch.delattr(subprocess, "CREATE_NO_WINDOW", raising=False)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=f"worktree {tmp_path}\0HEAD abc\0", stderr="")

    monkeypatch.setattr(shared_data.subprocess, "run", fake_run)
    monkeypatch.setenv("VISIBLE_SETTING", "kept")
    monkeypatch.setenv("GIT_DIR", "must-not-leak")

    assert shared_data._worktrees(tmp_path) == [tmp_path.resolve()]
    command, kwargs = calls[0]
    assert command == ["git", "-c", "core.quotePath=false", "-C", str(tmp_path), "worktree", "list", "--porcelain", "-z"]
    assert kwargs["creationflags"] == expected_flag
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["check"] is False
    assert kwargs["timeout"] == 30
    environment = kwargs["env"]
    assert isinstance(environment, dict)
    assert environment["VISIBLE_SETTING"] == "kept"
    assert "GIT_DIR" not in environment


@pytest.mark.parametrize("flag_present", [True, False])
def test_data_root_git_probe_is_hidden_and_preserves_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flag_present: bool) -> None:
    expected_flag = 0x08000000 if flag_present else 0
    if flag_present:
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", expected_flag, raising=False)
    else:
        monkeypatch.delattr(subprocess, "CREATE_NO_WINDOW", raising=False)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="main\n", stderr="")

    monkeypatch.setattr(research_data_paths.subprocess, "run", fake_run)

    assert research_data_paths._git_read(tmp_path, "rev-parse", "--show-toplevel") == "main\n"
    command, kwargs = calls[0]
    assert command == ["git", "-c", "core.quotePath=false", "-C", str(tmp_path), "rev-parse", "--show-toplevel"]
    assert kwargs == {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "check": False,
        "creationflags": expected_flag,
    }


def test_shared_worktree_probe_fails_closed_on_git_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        shared_data.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=2, stdout="", stderr="denied"),
    )
    with pytest.raises(shared_data.SharedRootError, match="cannot list worktrees.*denied"):
        shared_data._worktrees(tmp_path)


def test_data_root_git_probe_fails_closed_on_git_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        research_data_paths.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=2, stdout="partial", stderr="denied"),
    )
    with pytest.raises(ValueError, match="Git worktree identity check failed.*denied.*partial"):
        research_data_paths._git_read(tmp_path, "rev-parse", "--show-toplevel")
