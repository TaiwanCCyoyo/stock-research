from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from research_core.saved_research_studio import synthetic_studio_package, write_split_package
from scripts import start_research_web as launcher


def test_direct_script_entry_imports_shared_helpers() -> None:
    import sys

    result = subprocess.run([sys.executable, str(Path(launcher.__file__)), "--help"], capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0, result.stderr
    assert "--api-port" in result.stdout


def test_help_uses_utf8_even_when_redirected_stream_defaults_to_cp1252() -> None:
    import sys

    result = subprocess.run(
        [sys.executable, str(Path(launcher.__file__)), "--help"],
        env={**launcher.os.environ, "PYTHONIOENCODING": "cp1252"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "啟動研究網站與歷史 API" in result.stdout


@pytest.fixture(autouse=True)
def isolated_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never inherit workstation private settings or query real services."""
    for key in (*launcher.MODE_KEYS, *launcher.PATH_KEYS):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(launcher, "primary_checkout", lambda root: None)


def private_settings(tmp_path: Path) -> dict[str, str]:
    package = tmp_path / "synthetic studio.json"
    package.write_text(json.dumps(synthetic_studio_package()), encoding="utf-8")
    return {
        "STOCK_PRIVATE_ARTIFACT_ROOT": str(tmp_path),
        "STOCK_SAVED_STUDIO_PACKAGE": str(package),
    }


def test_unconfigured_defaults_synthetic_without_mutating_environment(tmp_path: Path) -> None:
    environment = {"UNRELATED": "preserved"}
    resolved = launcher.launch_environment(tmp_path, environment)
    assert environment == {"UNRELATED": "preserved"}
    assert resolved["UNRELATED"] == "preserved"
    assert all(resolved[key] == "public-synthetic" for key in launcher.MODE_KEYS)


def test_linked_checkout_reads_primary_settings(tmp_path: Path) -> None:
    settings = private_settings(tmp_path)
    (tmp_path / ".env.local").write_text("\n".join(f'{key}="{value}"' for key, value in settings.items()), encoding="utf-8")
    with patch.object(launcher, "primary_checkout", return_value=tmp_path):
        resolved = launcher.launch_environment(tmp_path / "linked", {})
    assert all(resolved[key] == "local-private" for key in launcher.MODE_KEYS)
    assert all(resolved[key] == value for key, value in settings.items())


def test_process_paths_override_file_and_duplicate_keys_fail(tmp_path: Path) -> None:
    settings = private_settings(tmp_path)
    env_file = tmp_path / ".env.local"
    env_file.write_text("STOCK_SAVED_STUDIO_PACKAGE=missing\n", encoding="utf-8")
    with patch.object(launcher, "primary_checkout", return_value=tmp_path):
        assert launcher.launch_environment(tmp_path, settings)["STOCK_SAVED_STUDIO_PACKAGE"] == settings["STOCK_SAVED_STUDIO_PACKAGE"]
        env_file.write_text("STOCK_SAVED_STUDIO_PACKAGE=one\nSTOCK_SAVED_STUDIO_PACKAGE=two\n", encoding="utf-8")
        with pytest.raises(ValueError, match="set 2 times"):
            launcher.launch_environment(tmp_path, {})


def test_explicit_demo_overrides_file_private_modes_without_reading_package(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text(
        "\n".join(["STOCK_RESEARCH_DATA_MODE=local-private", "VITE_ARTIFACT_MODE=local-private", "STOCK_SAVED_STUDIO_PACKAGE=missing"]),
        encoding="utf-8",
    )
    with (
        patch.object(launcher, "primary_checkout", return_value=tmp_path),
        patch.object(launcher, "read_studio_package") as reader,
    ):
        resolved = launcher.launch_environment(tmp_path, {"VITE_ARTIFACT_MODE": "public-synthetic"})
    reader.assert_not_called()
    assert all(resolved[key] == "public-synthetic" for key in launcher.MODE_KEYS)


@pytest.mark.parametrize(
    "settings",
    [
        {"VITE_ARTIFACT_MODE": "invalid"},
        {"VITE_ARTIFACT_MODE": ""},
        {"VITE_ARTIFACT_MODE": "local-private", "STOCK_RESEARCH_DATA_MODE": "public-synthetic"},
        {"STOCK_PRIVATE_ARTIFACT_ROOT": "relative"},
        {"STOCK_PRIVATE_ARTIFACT_ROOT": "", "STOCK_SAVED_STUDIO_PACKAGE": "relative"},
    ],
)
def test_invalid_or_partial_settings_fail(tmp_path: Path, settings: dict[str, str]) -> None:
    with pytest.raises(RuntimeError):
        launcher.launch_environment(tmp_path, settings)


def test_invalid_and_split_packages_use_existing_integrity_reader(tmp_path: Path) -> None:
    import gzip

    settings = private_settings(tmp_path)
    package = Path(settings["STOCK_SAVED_STUDIO_PACKAGE"])
    package.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="完整性驗證"):
        launcher.launch_environment(tmp_path, settings)
    manifest = tmp_path / "studio.manifest.json"
    write_split_package(gzip.compress(json.dumps(synthetic_studio_package()).encode()), manifest)
    settings["STOCK_SAVED_STUDIO_PACKAGE"] = str(manifest)
    assert launcher.launch_environment(tmp_path, settings)["VITE_ARTIFACT_MODE"] == "local-private"
    part = next(tmp_path.glob("*.bin"))
    part.write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="完整性驗證"):
        launcher.launch_environment(tmp_path, settings)


def test_live_mode_and_proxy_mismatch_are_refused() -> None:
    environment = {"VITE_ARTIFACT_MODE": "local-private", "RESEARCH_WEB_API_TARGET": "http://127.0.0.1:18517"}
    response = MagicMock()
    with patch.object(launcher.urllib.request, "urlopen", return_value=response) as request:
        response.__enter__.return_value.read.return_value = b'{"dataMode":"public-synthetic"}'
        with pytest.raises(RuntimeError, match="資料模式"):
            launcher._verify_live_mode("history-api", 18517, environment)
        assert request.call_args.args[0].endswith("/__research_service__")
        response.__enter__.return_value.read.return_value = b'{"dataMode":"local-private","apiTarget":"wrong"}'
        with pytest.raises(RuntimeError, match="proxy"):
            launcher._verify_live_mode("research-web", 15177, environment)


@pytest.mark.parametrize("missing_identity", [False, True])
def test_changed_private_source_or_missing_identity_refuses_reuse(tmp_path: Path, missing_identity: bool) -> None:
    environment = {
        **private_settings(tmp_path),
        "VITE_ARTIFACT_MODE": "local-private",
        "STOCK_RESEARCH_DATA_MODE": "local-private",
    }
    running = dict(environment)
    running["STOCK_SAVED_STUDIO_PACKAGE"] = str(tmp_path / "older-package.json")
    payload = launcher.dashboard_identity(running)
    if missing_identity:
        payload.pop("configId")
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    with patch.object(launcher.urllib.request, "urlopen", return_value=response):
        with pytest.raises(RuntimeError, match="設定身份|來源設定"):
            launcher._verify_live_mode("history-api", 18517, environment)


def test_check_uses_identity_only_never_studio_runs(tmp_path: Path) -> None:
    environment = {"VITE_ARTIFACT_MODE": "public-synthetic", "STOCK_RESEARCH_DATA_MODE": "public-synthetic"}
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({
        **launcher.dashboard_identity({**environment, "RESEARCH_WEB_URL": "http://127.0.0.1:15177"}),
        "apiTarget": "http://127.0.0.1:18517",
        "build": "production",
    }).encode()
    with (
        patch.object(launcher, "project_root", return_value=tmp_path),
        patch.object(launcher, "_inspect_service", return_value="reusable"),
        patch.object(launcher.urllib.request, "urlopen", return_value=response) as request,
    ):
        assert launcher.run(check=True, api_port=18517, web_port=15177) == 0
    assert [item.args[0] for item in request.call_args_list] == [
        "http://127.0.0.1:18517/__research_service__",
        "http://127.0.0.1:15177/__research_service__",
    ]


def test_check_reports_mode_without_starting_services(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with (
        patch.object(launcher, "project_root", return_value=tmp_path),
        patch.object(launcher, "_inspect_service", return_value="stopped") as inspect,
        patch.object(launcher, "_start_child") as start,
    ):
        assert launcher.run(check=True, api_port=18517, web_port=15177) == 1
    start.assert_not_called()
    assert inspect.call_args_list == [call("history-api", 18517, tmp_path), call("research-web", 15177, tmp_path)]
    assert "public-synthetic" in capsys.readouterr().out


def test_check_private_reports_verified_package(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    settings = private_settings(tmp_path)
    with (
        patch.dict(launcher.os.environ, settings),
        patch.object(launcher, "project_root", return_value=tmp_path),
        patch.object(launcher, "_inspect_service", return_value="stopped"),
        patch.object(launcher, "_start_child") as start,
    ):
        assert launcher.run(check=True, api_port=18517, web_port=15177) == 1
    start.assert_not_called()
    output = capsys.readouterr().out
    assert "local-private" in output
    assert "已通過 reader 完整性驗證" in output


def test_custom_ports_reach_commands_and_child_environment(tmp_path: Path) -> None:
    with patch.object(launcher.shutil, "which", return_value="executable"):
        assert launcher._command("history-api", tmp_path, 18517)[-1] == "18517"
        assert "15177" in launcher._command("research-web", tmp_path, 15177)
    environment = {"VITE_ARTIFACT_MODE": "public-synthetic"}
    with patch.object(launcher.subprocess, "Popen") as popen, patch.object(launcher, "_command", return_value=["command"]):
        child = launcher._start_child("history-api", tmp_path, tmp_path, environment, 18517)
    assert popen.call_args.kwargs["env"] is environment
    child.log_file.close()


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
        patch.object(launcher, "_build_website", return_value="current"),
        patch.object(launcher, "_start_child", side_effect=lambda *args: next(created)) as start,
        patch.object(launcher, "_wait_until_ready", side_effect=[None, RuntimeError("web failed")]),
        patch.object(launcher, "_verify_live_mode"),
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
        patch.object(launcher, "_build_website", return_value="current"),
        patch.object(launcher, "_start_child", return_value=child),
        patch.object(launcher, "_wait_until_ready"),
        patch.object(launcher, "_verify_live_mode"),
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
        patch.object(launcher, "_build_website", return_value="current"),
        patch.object(launcher, "_start_child", side_effect=lambda *args: next(created)),
        patch.object(launcher, "_wait_until_ready"),
        patch.object(launcher, "_verify_live_mode"),
        patch.object(launcher, "_stop_child") as stop,
    ):
        result = launcher.run(no_browser=True)

    assert result == 1
    assert "意外結束（結束碼 0）" in capsys.readouterr().err
    assert stop.call_args_list == [call(children[1]), call(children[0])]


def test_run_tells_the_api_which_website_url_to_point_to(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    child = launcher.ManagedChild("history-api", MagicMock(), io.BytesIO())

    with (
        patch.object(launcher, "project_root", return_value=root),
        patch.object(launcher, "_inspect_service", return_value="stopped"),
        patch.object(launcher, "_configure_logging", return_value=tmp_path),
        patch.object(launcher, "_build_website", return_value="current"),
        patch.object(launcher, "_start_child", return_value=child) as start,
        patch.object(launcher, "_wait_until_ready", side_effect=RuntimeError("stop after first start")),
        patch.object(launcher, "_verify_live_mode"),
        patch.object(launcher, "_stop_child"),
    ):
        launcher.run(no_browser=True, api_port=18517, web_port=15177)

    environment = start.call_args.args[3]
    assert environment["RESEARCH_WEB_URL"] == "http://127.0.0.1:15177"


def test_reused_api_must_point_to_the_same_website_url() -> None:
    environment = {"VITE_ARTIFACT_MODE": "public-synthetic", "RESEARCH_WEB_URL": "http://127.0.0.1:15177"}
    running = launcher.dashboard_identity({"RESEARCH_WEB_URL": "http://127.0.0.1:5177"})
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(running).encode()
    with patch.object(launcher.urllib.request, "urlopen", return_value=response):
        with pytest.raises(RuntimeError, match="網站網址"):
            launcher._verify_live_mode("history-api", 18517, environment)
        running["webUrl"] = "http://127.0.0.1:15177"
        response.__enter__.return_value.read.return_value = json.dumps(running).encode()
        launcher._verify_live_mode("history-api", 18517, environment)


def test_website_command_serves_production_by_default_and_dev_on_request(tmp_path: Path) -> None:
    with patch.object(launcher.shutil, "which", return_value="npm"):
        assert "preview" in launcher._command("research-web", tmp_path, 15177)
        assert "dev" in launcher._command("research-web", tmp_path, 15177, dev=True)
        assert "preview" not in launcher._command("research-web", tmp_path, 15177, dev=True)


@pytest.mark.parametrize(("reported", "expected"), [(None, "production"), ("development", "production"), ("production", "development")])
def test_reuse_refuses_a_website_of_the_other_build(reported: str | None, expected: str) -> None:
    environment = {
        "VITE_ARTIFACT_MODE": "public-synthetic",
        "RESEARCH_WEB_API_TARGET": "http://127.0.0.1:18517",
        launcher.BUILD_KEY: expected,
    }
    payload = {"dataMode": "public-synthetic", "apiTarget": "http://127.0.0.1:18517"}
    if reported:
        payload["build"] = reported
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    with patch.object(launcher.urllib.request, "urlopen", return_value=response):
        with pytest.raises(RuntimeError, match="開發模式|正式版"):
            launcher._verify_live_mode("research-web", 15177, environment)


@pytest.mark.parametrize("dev", [False, True])
def test_run_builds_the_website_only_for_production(tmp_path: Path, dev: bool) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    children = iter((launcher.ManagedChild("history-api", MagicMock(), io.BytesIO()), launcher.ManagedChild("research-web", MagicMock(), io.BytesIO())))
    with (
        patch.object(launcher, "project_root", return_value=root),
        patch.object(launcher, "_inspect_service", return_value="stopped"),
        patch.object(launcher, "_configure_logging", return_value=tmp_path),
        patch.object(launcher, "_build_website", return_value="built") as build,
        patch.object(launcher, "_start_child", side_effect=lambda *args: next(children)) as start,
        patch.object(launcher, "_wait_until_ready", side_effect=[None, RuntimeError("stop here")]),
        patch.object(launcher, "_verify_live_mode"),
        patch.object(launcher, "_stop_child"),
    ):
        launcher.run(no_browser=True, dev=dev)
    assert build.called is (not dev)
    assert start.call_args_list[1].args[-1] is dev
    assert start.call_args_list[1].args[3][launcher.BUILD_KEY] == ("development" if dev else "production")


def test_failed_build_stops_before_starting_services(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    result = MagicMock(returncode=1, stdout=b"[dashboard] build failed")
    with (
        patch.object(launcher, "project_root", return_value=root),
        patch.object(launcher, "_inspect_service", return_value="stopped"),
        patch.object(launcher, "_configure_logging", return_value=tmp_path),
        patch.object(launcher.shutil, "which", return_value="npm"),
        patch.object(launcher.subprocess, "run", return_value=result),
        patch.object(launcher, "_start_child") as start,
    ):
        assert launcher.run(no_browser=True) == 1
    start.assert_not_called()
    err = capsys.readouterr().err
    assert "建置網站失敗" in err and "--dev" in err
    assert (tmp_path / "build.log").read_bytes() == b"[dashboard] build failed"
