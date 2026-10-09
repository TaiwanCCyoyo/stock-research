from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from scripts import start_research_web as launcher


def test_read_identity_requires_schema_role_and_same_checkout(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    nested = checkout / "nested"
    nested.mkdir()
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({
        "schema": launcher.SCHEMA,
        "service": "history-api",
        "projectRoot": str(nested / ".."),
    }).encode()

    with patch.object(launcher.urllib.request, "urlopen", return_value=response):
        assert launcher._read_identity(8517, checkout) == (True, "身份正確")

    payload = {
        "schema": launcher.SCHEMA,
        "service": "research-web",
        "projectRoot": str(checkout),
    }
    response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    with patch.object(launcher.urllib.request, "urlopen", return_value=response):
        valid, reason = launcher._read_identity(8517, checkout)
    assert not valid
    assert "服務角色不符" in reason

    payload["service"] = "history-api"
    payload["projectRoot"] = str(tmp_path)
    response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    with patch.object(launcher.urllib.request, "urlopen", return_value=response):
        valid, reason = launcher._read_identity(8517, checkout)
    assert not valid
    assert "其他 checkout" in reason


def test_start_child_uses_argument_vector_and_hidden_windows_flag(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    command = ["C:/Program Files/node/npm.cmd", "--prefix", str(tmp_path / "research_web")]
    process = MagicMock()
    process.pid = 123

    with (
        patch.object(launcher, "_command", return_value=command),
        patch.object(launcher.subprocess, "Popen", return_value=process) as popen,
    ):
        child = launcher._start_child("research-web", tmp_path, log_dir)

    args, kwargs = popen.call_args
    assert args == (command,)
    assert kwargs.get("shell", False) is False
    assert kwargs["cwd"] == tmp_path
    assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert child.process is process
    assert child.log_file.closed is False
    child.log_file.close()


def test_run_cleans_up_only_started_children_when_later_service_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    first_child = launcher.ManagedChild("history-api", MagicMock(), io.BytesIO())
    second_child = launcher.ManagedChild("research-web", MagicMock(), io.BytesIO())
    created = iter((first_child, second_child))

    with (
        patch.object(launcher, "project_root", return_value=root),
        patch.object(launcher, "_inspect_service", return_value="stopped"),
        patch.object(launcher, "_configure_logging", return_value=tmp_path),
        patch.object(launcher, "_start_child", side_effect=lambda *args: next(created)) as start,
        patch.object(launcher, "_wait_until_ready", side_effect=[None, RuntimeError("web failed")]),
        patch.object(launcher, "_stop_child") as stop,
    ):
        result = launcher.run(no_browser=True)

    assert result == 1
    assert start.call_count == 2
    assert stop.call_args_list == [call(second_child), call(first_child)]
    assert "啟動失敗：web failed" in capsys.readouterr().err


def test_run_reports_exit_of_single_managed_child_when_other_service_is_reused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    process = MagicMock()
    process.poll.return_value = 0
    process.returncode = 0
    child = launcher.ManagedChild("research-web", process, io.BytesIO())

    with (
        patch.object(launcher, "project_root", return_value=root),
        patch.object(launcher, "_inspect_service", side_effect=("reusable", "stopped")),
        patch.object(launcher, "_configure_logging", return_value=tmp_path),
        patch.object(launcher, "_start_child", return_value=child),
        patch.object(launcher, "_wait_until_ready"),
        patch.object(launcher, "_stop_child") as stop,
    ):
        result = launcher.run(no_browser=True)

    assert result == 1
    assert "research-web 意外結束（結束碼 0）" in capsys.readouterr().err
    stop.assert_called_once_with(child)


def test_run_reports_children_that_exit_simultaneously(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    children = []
    for name in ("history-api", "research-web"):
        process = MagicMock()
        process.poll.return_value = 0
        process.returncode = 0
        children.append(launcher.ManagedChild(name, process, io.BytesIO()))
    created = iter(children)

    with (
        patch.object(launcher, "project_root", return_value=root),
        patch.object(launcher, "_inspect_service", return_value="stopped"),
        patch.object(launcher, "_configure_logging", return_value=tmp_path),
        patch.object(launcher, "_start_child", side_effect=lambda *args: next(created)),
        patch.object(launcher, "_wait_until_ready"),
        patch.object(launcher, "_stop_child") as stop,
    ):
        result = launcher.run(no_browser=True)

    assert result == 1
    assert "意外結束（結束碼 0）" in capsys.readouterr().err
    assert stop.call_args_list == [call(children[1]), call(children[0])]
