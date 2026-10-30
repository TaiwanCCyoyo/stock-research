"""Primary dashboard return flow, with no live servers or process launches."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette.requests import Request

from research_api import development_previews as api
from research_core import development_previews as previews
from research_core.dashboard_identity import dashboard_identity


@pytest.fixture
def main_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    primary = tmp_path / "primary"
    (primary / "scripts").mkdir(parents=True)
    (primary / "scripts/start_research_web.py").write_text("", encoding="utf-8")
    (primary / ".tmp/development-previews").mkdir(parents=True)
    monkeypatch.setattr(previews, "primary_checkout", lambda root: primary)
    monkeypatch.setattr(previews, "_git", lambda root, *args: "main")
    monkeypatch.setattr(previews, "_available", lambda port: True)
    monkeypatch.setattr(previews, "_json_response", lambda port, path: None)
    return primary


def ready_services(main_root: Path, monkeypatch: pytest.MonkeyPatch) -> dict[tuple[int, str], dict]:
    expected = previews.main_environment(main_root, {})
    identities = {
        (5177, "/__research_service__"): {
            "schema": "stock-research-service.v1",
            "service": "research-web",
            "projectRoot": str(main_root),
            "dataMode": "public-synthetic",
            "build": "production",
            "apiTarget": "http://127.0.0.1:8517",
            "release": "release123",
        },
        (8517, "/__research_service__"): {
            "schema": "stock-research-service.v1",
            "service": "history-api",
            "projectRoot": str(main_root),
            **dashboard_identity(expected),
        },
        (5177, "/reports/index.json"): {"version": "release123"},
        (5177, "/release.json"): {"version": "release123"},
    }
    monkeypatch.setattr(previews, "_json_response", lambda port, path: identities.get((port, path)))
    return identities


def test_main_ready_reuses_verified_production_service(main_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready_services(main_root, monkeypatch)
    detach = MagicMock()
    monkeypatch.setattr(previews, "_detach", detach)
    assert previews.open_main(root=main_root, environment={}) == {"status": "ready", "url": "http://127.0.0.1:5177/", "message": "正式版已就緒。"}
    detach.assert_not_called()


def test_stopped_main_launches_once_and_waits_for_build_deadline(main_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    detach = MagicMock(return_value=321)
    monkeypatch.setattr(previews, "_detach", detach)
    clock = [1000.0]
    monkeypatch.setattr(previews.time, "time", lambda: clock[0])
    assert previews.main_status(root=main_root, environment={})["status"] == "stopped"
    assert previews.open_main(root=main_root, environment={})["status"] == "starting"
    clock[0] += 650
    assert previews.open_main(root=main_root, environment={})["status"] == "starting"
    detach.assert_called_once()
    assert detach.call_args.args == ("main",)
    clock[0] += 71
    assert previews.main_status(root=main_root, environment={})["status"] == "stopped"


def test_main_operation_lock_prevents_duplicate_launch(main_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(previews, "try_os_lock", lambda handle: False)
    detach = MagicMock()
    monkeypatch.setattr(previews, "_detach", detach)
    with pytest.raises(previews.PreviewError, match="另一個"):
        previews.open_main(root=main_root, environment={})
    detach.assert_not_called()


def test_partial_matching_main_can_fill_missing_service(main_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    identities = ready_services(main_root, monkeypatch)
    del identities[(5177, "/__research_service__")]
    monkeypatch.setattr(previews, "_detach", lambda *args, **kwargs: 123)
    assert previews.open_main(root=main_root, environment={})["status"] == "starting"


@pytest.mark.parametrize("fault", ["root", "mode", "config", "api", "development", "index", "release"])
def test_wrong_main_identity_or_release_is_never_reused(main_root: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    identities = ready_services(main_root, monkeypatch)
    web, backend = identities[(5177, "/__research_service__")], identities[(8517, "/__research_service__")]
    if fault == "root":
        backend["projectRoot"] = str(main_root / "some-worktree")
    elif fault == "mode":
        web["dataMode"] = "local-private"
    elif fault == "config":
        backend["configId"] = "different"
    elif fault == "api":
        web["apiTarget"] = "http://127.0.0.1:20001"
    elif fault == "development":
        web["build"] = "development"
    elif fault == "index":
        identities[(5177, "/reports/index.json")]["version"] = "development"
    else:
        identities[(5177, "/release.json")]["version"] = "old"
    detach = MagicMock()
    monkeypatch.setattr(previews, "_detach", detach)
    assert previews.open_main(root=main_root, environment={})["status"] == "unavailable"
    detach.assert_not_called()


def test_main_requires_primary_main_branch_and_free_or_identified_ports(main_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(previews, "_git", lambda root, *args: "codex/other")
    assert previews.main_status(root=main_root, environment={})["status"] == "unavailable"
    monkeypatch.setattr(previews, "_git", lambda root, *args: "main")
    monkeypatch.setattr(previews, "_available", lambda port: False)
    assert previews.main_status(root=main_root, environment={})["status"] == "unavailable"


def test_main_fresh_configuration_strips_preview_and_build_overrides(main_root: Path) -> None:
    (main_root / ".env.local").write_text("STOCK_PRODUCER_DATA_ROOT=D:/canonical\nSTOCK_RESEARCH_DATA_MODE=public-synthetic\n", encoding="utf-8")
    inherited = {
        "PATH": "normal-path",
        "STOCK_PRODUCER_DATA_ROOT": "D:/wrong",
        "STOCK_RESEARCH_DATA_MODE": "local-private",
        "VITE_ARTIFACT_MODE": "local-private",
        "RESEARCH_PREVIEW_ID": "example",
        "RESEARCH_PREVIEW_CONFIG_ID": "other",
        "RESEARCH_WEB_VERSION": "development",
        "RESEARCH_WEB_BUILD": "development",
        "RESEARCH_DESKTOP_PYTHON": "wrong-python",
        "RESEARCH_WEB_BUILD_OUT_DIR": "wrong-dist",
        "RESEARCH_WEB_URL": "http://127.0.0.1:20000",
        "RESEARCH_WEB_API_TARGET": "http://127.0.0.1:20001",
    }
    cleaned = previews.main_environment(main_root, inherited)
    assert cleaned["STOCK_PRODUCER_DATA_ROOT"] == "D:/canonical"
    assert cleaned["STOCK_RESEARCH_DATA_MODE"] == cleaned["VITE_ARTIFACT_MODE"] == "public-synthetic"
    assert cleaned["PATH"] == "normal-path"
    assert not any(key.startswith(("RESEARCH_PREVIEW_", "RESEARCH_DESKTOP_", "RESEARCH_WEB_BUILD")) for key in cleaned)
    assert "RESEARCH_WEB_VERSION" not in cleaned and "RESEARCH_WEB_URL" not in cleaned
    assert cleaned["VITE_API_BASE"] == "/api"


def test_detach_waits_for_helper_exit_before_returning_pid(main_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = MagicMock(return_value=subprocess.CompletedProcess([], 0, b"12345"))
    monkeypatch.setattr(previews.subprocess, "run", run)
    assert previews._detach("main", root=main_root, environment={"PATH": "x"}) == 12345
    command = run.call_args.args[0]
    assert command[-3:] == ["-m", "research_core.development_previews", "--detach-main"]
    assert run.call_args.kwargs["cwd"] == main_root
    assert run.call_args.kwargs["timeout"] == 20
    assert run.call_args.kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    run.return_value = subprocess.CompletedProcess([], 1, b"not-a-pid")
    with pytest.raises(previews.PreviewError, match="未能"):
        previews._detach("main", root=main_root, environment={})


def test_detached_main_uses_fixed_primary_production_command(main_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    popen = MagicMock(return_value=MagicMock(pid=9988))
    monkeypatch.setattr(previews.subprocess, "Popen", popen)
    environment = {
        "RESEARCH_PREVIEW_ID": "example",
        "RESEARCH_PREVIEW_MAIN_URL": "http://127.0.0.1:15177/",
        "RESEARCH_PREVIEW_MAIN_API_TARGET": "http://127.0.0.1:18517/",
        "RESEARCH_WEB_VERSION": "development",
    }
    assert previews._spawn_detached("main", root=main_root, environment=environment) == 9988
    command = popen.call_args.args[0]
    assert command[2] == str(main_root / "scripts/start_research_web.py")
    assert "--dev" not in command and "--desktop" in command and "--no-browser" in command
    assert command[-4:] == ["--web-port", "15177", "--api-port", "18517"]
    assert popen.call_args.kwargs["cwd"] == main_root
    assert not any(key.startswith("RESEARCH_PREVIEW_") for key in popen.call_args.kwargs["env"])
    assert "RESEARCH_WEB_VERSION" not in popen.call_args.kwargs["env"]
    assert popen.call_args.kwargs["close_fds"] is True


@pytest.mark.parametrize("value", ["https://evil.example", "http://localhost:5177", "http://127.0.0.1:0", "http://127.0.0.1:5177/#report/x"])
def test_main_url_cannot_be_arbitrary_target(main_root: Path, value: str) -> None:
    assert previews.main_status(root=main_root, environment={"RESEARCH_PREVIEW_MAIN_URL": value})["status"] == "unavailable"


def test_main_http_endpoints_keep_origin_host_and_custom_header_guards(main_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_WEB_URL", "http://127.0.0.1:20000")
    monkeypatch.setenv("RESEARCH_WEB_API_TARGET", "http://127.0.0.1:20001")
    operation = MagicMock(return_value={"status": "starting", "url": None, "message": "啟動中"})
    monkeypatch.setattr(api, "open_main", operation)
    router = api.create_development_preview_router(main_root)
    endpoint = next(route.endpoint for route in router.routes if isinstance(route, APIRoute) and route.path == "/development-main/open")

    def request(origin: str | None = "http://127.0.0.1:20000", host: str = "127.0.0.1:20001", client: str = "127.0.0.1", header: bool = True) -> Request:
        headers = [(b"host", host.encode())]
        if origin is not None:
            headers.append((b"origin", origin.encode()))
        if header:
            headers.append((b"x-requested-with", b"development-preview"))
        return Request({"type": "http", "method": "POST", "path": "/development-main/open", "headers": headers, "client": (client, 123)})

    for invalid in (
        request(origin=None),
        request(origin="https://evil.example"),
        request(host="evil.example"),
        request(client="192.168.1.2"),
        request(header=False),
    ):
        with pytest.raises(HTTPException) as exc:
            endpoint(invalid)
        assert exc.value.status_code == 403
    operation.assert_not_called()
    assert endpoint(request())["status"] == "starting"
    operation.assert_called_once()


def test_stale_main_start_record_has_bounded_wait(main_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = main_root / ".tmp/development-previews/.main.launch.json"
    path.write_text(json.dumps({"started": 1000, "pid": 42}), encoding="utf-8")
    monkeypatch.setattr(previews.time, "time", lambda: 2000)
    assert previews.main_status(root=main_root, environment={})["status"] == "stopped"
