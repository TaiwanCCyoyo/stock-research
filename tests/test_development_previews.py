"""Synthetic registry/lifecycle tests; never start workstation services."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api.development_previews import create_development_preview_router
from research_core import development_previews as previews
from research_core.dashboard_identity import dashboard_identity
from scripts import start_research_web as launcher


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    primary = tmp_path / "primary"
    target = primary / ".worktrees" / "example"
    (target / "scripts").mkdir(parents=True)
    (target / "research_web").mkdir()
    (target / "scripts" / "start_research_web.py").write_text("", encoding="utf-8")
    (target / "research_web" / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(previews, "primary_checkout", lambda root: primary)

    def git(root: Path, *args: str) -> str:
        if args[0] == "worktree":
            return f"worktree {primary}\0HEAD abc\0branch refs/heads/main\0\0worktree {target}\0HEAD def\0branch refs/heads/codex/example\0\0"
        return "codex/example" if args[0] == "branch" else "def123"

    monkeypatch.setattr(previews, "_git", git)
    monkeypatch.setattr(previews, "_available", lambda port: True)
    monkeypatch.setattr(previews, "_json_response", lambda port, path: None)
    return primary, target


def register_example(registry: tuple[Path, Path]) -> previews.Preview:
    primary, target = registry
    return previews.register(identifier="example", title="研究預覽", route="#report/example", worktree=target, pr=123, root=primary)


def test_register_uses_primary_registry_and_retire_preserves_target(registry: tuple[Path, Path]) -> None:
    primary, target = registry
    item = register_example(registry)
    assert item.web_port == 20000 and item.api_port == 20001
    assert (primary / ".tmp/development-previews/example.json").exists()
    assert not (target / ".tmp").exists()
    row = previews.list_previews(root=primary, environment={})["items"][0]
    assert row["status"] == "stopped" and row["head"] == "def123"
    previews.retire("example", root=primary)
    assert previews.list_previews(root=primary, environment={})["items"] == []
    assert (target / "scripts/start_research_web.py").exists()


@pytest.mark.parametrize("identifier,route", [("../x", "#home"), ("good", "https://evil.example/"), ("good", "#report/../x"), ("good", "#report/x?next=evil")])
def test_register_rejects_traversal_and_external_routes(registry: tuple[Path, Path], identifier: str, route: str) -> None:
    primary, target = registry
    with pytest.raises(previews.PreviewError):
        previews.register(identifier=identifier, title="test", route=route, worktree=target, root=primary)


def test_unregistered_directory_and_changed_branch_fail_closed(registry: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    primary, target = registry
    outsider = primary / "other"
    outsider.mkdir()
    with pytest.raises(previews.PreviewError, match="不屬於"):
        previews.register(identifier="other", title="other", route="#home", worktree=outsider, root=primary)
    register_example(registry)
    old_git = previews._git
    monkeypatch.setattr(previews, "_git", lambda root, *args: "codex/different" if args[0] == "branch" else old_git(root, *args))
    row = previews.list_previews(root=primary, environment={})["items"][0]
    assert row["status"] == "unavailable" and "分支已改變" in row["message"]


def test_open_is_fixed_hidden_launch_and_duplicate_click_is_idempotent(registry: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    primary, target = registry
    register_example(registry)
    popen = MagicMock(return_value=MagicMock(pid=1234))
    monkeypatch.setattr(previews.subprocess, "Popen", popen)
    detach = MagicMock(return_value=1234)
    monkeypatch.setattr(previews, "_detach", detach)
    env = {
        "RESEARCH_WEB_URL": "http://127.0.0.1:21000/",
        "RESEARCH_WEB_API_TARGET": "http://127.0.0.1:21001/",
        "RESEARCH_PREVIEW_MAIN_URL": "http://127.0.0.1:5177/",
        "RESEARCH_PREVIEW_MAIN_API_TARGET": "http://127.0.0.1:8517/",
        "STOCK_PRODUCER_DATA_ROOT": str(primary / "canonical"),
        "RESEARCH_WEB_VERSION": "old-release",
    }
    assert previews.open_preview("example", root=primary, environment=env)["status"] == "starting"
    assert previews.open_preview("example", root=primary, environment=env)["status"] == "starting"
    detach.assert_called_once()
    assert detach.call_args.args == ("preview",)
    assert detach.call_args.kwargs["identifier"] == "example"
    popen.assert_not_called()
    previews._spawn_detached("preview", root=primary, environment=detach.call_args.kwargs["environment"], identifier="example")
    popen.assert_called_once()
    args, kwargs = popen.call_args
    assert args[0][2] == str(target / "scripts/start_research_web.py")
    assert "--dev" in args[0] and "--desktop" in args[0] and "--no-browser" in args[0]
    assert kwargs["cwd"] == target
    assert kwargs["env"]["VITE_API_BASE"] == "/api"
    assert kwargs["env"]["STOCK_PRODUCER_DATA_ROOT"] == str(primary / "canonical")
    assert kwargs["env"]["RESEARCH_WEB_VERSION"] == "development"
    assert kwargs["env"]["RESEARCH_PREVIEW_MAIN_URL"] == env["RESEARCH_PREVIEW_MAIN_URL"]
    assert kwargs["env"]["RESEARCH_PREVIEW_MAIN_API_TARGET"] == env["RESEARCH_PREVIEW_MAIN_API_TARGET"]
    assert kwargs["creationflags"] == getattr(previews.subprocess, "CREATE_NO_WINDOW", 0) | getattr(previews.subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def test_ready_requires_same_worktree_data_config_and_development_index(registry: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    primary, target = registry
    item = register_example(registry)
    env = previews.preview_environment(primary, {})
    identities = {
        item.web_port: {
            "schema": "stock-research-service.v1",
            "service": "research-web",
            "projectRoot": str(target),
            "dataMode": "public-synthetic",
            "build": "development",
            "apiTarget": f"http://127.0.0.1:{item.api_port}",
        },
        item.api_port: {
            "schema": "stock-research-service.v1",
            "service": "history-api",
            "projectRoot": str(target),
            **dashboard_identity(env),
            "previewConfigId": previews._configuration(env),
        },
    }
    report = {"version": "development"}
    monkeypatch.setattr(previews, "_json_response", lambda port, path: report if path == "/reports/index.json" else identities[port])
    result = previews.list_previews(root=primary, environment={})["items"][0]
    assert result["status"] == "ready" and result["url"] == "http://127.0.0.1:20000/#report/example"
    identities[item.api_port]["previewConfigId"] = "different"
    assert previews.list_previews(root=primary, environment={})["items"][0]["status"] == "unavailable"
    identities[item.api_port]["previewConfigId"] = previews._configuration(env)
    fingerprint = identities[item.api_port].pop("configVersion")
    assert previews.list_previews(root=primary, environment={})["items"][0]["status"] == "unavailable"
    identities[item.api_port]["configVersion"] = fingerprint
    identities[item.api_port]["configId"] = "other-effective-roots"
    assert previews.list_previews(root=primary, environment={})["items"][0]["status"] == "unavailable"
    identities[item.api_port]["configId"] = dashboard_identity(env)["configId"]
    report["version"] = "old-release"
    assert previews.list_previews(root=primary, environment={})["items"][0]["status"] == "unavailable"


def test_public_synthetic_never_silently_becomes_private(registry: tuple[Path, Path]) -> None:
    primary, _ = registry
    settings = ["STOCK_RESEARCH_DATA_MODE=local-private", "VITE_ARTIFACT_MODE=local-private"]
    (primary / ".env.local").write_text("\n".join(settings) + "\n", encoding="utf-8")
    with pytest.raises(previews.PreviewError, match="不一致"):
        previews.preview_environment(primary, {"STOCK_RESEARCH_DATA_MODE": "public-synthetic"})


def test_registry_tampering_cannot_supply_command_or_arbitrary_port(registry: tuple[Path, Path]) -> None:
    primary, _ = registry
    item = register_example(registry)
    path = primary / ".tmp/development-previews/example.json"
    data = asdict(item)
    data["web_port"] = 8517
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(previews.PreviewError):
        previews.open_preview("example", root=primary, environment={})


def test_http_requires_local_host_origin_and_custom_header(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RESEARCH_WEB_URL", "http://127.0.0.1:5177")
    monkeypatch.setenv("RESEARCH_WEB_API_TARGET", "http://127.0.0.1:8517")
    open_call = MagicMock(return_value={"status": "starting", "url": None, "message": "啟動中"})
    monkeypatch.setattr("research_api.development_previews.open_preview", open_call)
    app = FastAPI()
    app.include_router(create_development_preview_router(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1:8517", client=("127.0.0.1", 1234)) as client:
        path = "/development-previews/example/open"
        assert client.post(path).status_code == 403
        headers = {"Origin": "http://127.0.0.1:5177", "X-Requested-With": "development-preview"}
        assert client.post(path, headers={**headers, "Origin": "https://evil.example"}).status_code == 403
        assert client.post(path, headers={**headers, "Host": "evil.example"}).status_code == 403
        assert client.post(path, headers=headers).status_code == 200
    open_call.assert_called_once()


def test_preview_api_identity_echoes_source_config_only_when_present() -> None:
    assert "previewConfigId" not in dashboard_identity({})
    assert dashboard_identity({"RESEARCH_PREVIEW_CONFIG_ID": "stamp"})["previewConfigId"] == "stamp"


def test_desktop_dev_api_reloads_only_code_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    popen = MagicMock(return_value=MagicMock(pid=12))
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    child = launcher._start_child("history-api", tmp_path, tmp_path, {"RESEARCH_DESKTOP_PYTHON": "python"}, dev=True)
    command = popen.call_args.args[0]
    assert command.count("--reload") == 1
    assert command[-4:] == ["--reload-dir", str(tmp_path / "research_api"), "--reload-dir", str(tmp_path / "research_core")]
    child.log_file.close()
