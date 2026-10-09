"""Security hardening for the read-only API and task path resolution."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from research_api import main as api_main

CSRF_HEADER = {"X-Requested-With": "research-web"}


def test_backtest_routes_are_unavailable_even_with_custom_header() -> None:
    client = TestClient(api_main.app)
    route_paths = {getattr(route, "path", None) for route in api_main.app.routes}

    assert not any(path and path.startswith("/backtests") for path in route_paths)
    for method in (client.get, client.post):
        response = method("/backtests", headers=CSRF_HEADER)
        # When the optional frontend is mounted, StaticFiles answers POST with
        # 405; otherwise both methods are 404. Neither can launch a backtest.
        assert response.status_code in {404, 405}


def test_task_id_traversal_is_rejected_on_read_endpoints() -> None:
    client = TestClient(api_main.app)
    for path in ["/tasks/..%2Foutside", "/tasks/..%2Foutside/strategies", "/tasks/..%2Foutside/trades"]:
        response = client.get(path)
        assert response.status_code == 404, path


def test_resolve_task_root_rejects_escaping_paths() -> None:
    from scripts.stock_research_query import QueryError, resolve_task_root

    with pytest.raises(QueryError):
        resolve_task_root("../outside")


def test_read_api_does_not_import_static_report_dependencies(tmp_path: Path) -> None:
    """The viewer reads task artifacts without importing optional Panel/Plotly."""
    script = textwrap.dedent(
        """
        import importlib.abc
        import json
        import sys
        from pathlib import Path

        class BlockStaticReportImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "panel" or fullname.startswith("panel."):
                    raise ModuleNotFoundError("panel import blocked", name=fullname)
                if fullname == "plotly" or fullname.startswith("plotly."):
                    raise ModuleNotFoundError("plotly import blocked", name=fullname)
                return None

        sys.meta_path.insert(0, BlockStaticReportImports())

        from fastapi.testclient import TestClient
        from research_api.main import create_app
        from research_lab import dashboard_core
        from scripts import stock_research_query

        root = Path(sys.argv[1])
        tasks_root = root / "tasks"
        task_dir = tasks_root / "task-a"
        task_dir.mkdir(parents=True)
        (task_dir / "summary.json").write_text(
            json.dumps({"metrics": {"return_rate": 0.1}, "trades": []}),
            encoding="utf-8",
        )
        dashboard_core.TASKS_ROOT = tasks_root
        stock_research_query.TASKS_ROOT = tasks_root

        client = TestClient(create_app())
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/tasks").json()["tasks"][0]["task"] == "task-a"
        assert client.get("/tasks/task-a").status_code == 200
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_path_under_rejects_run_name_escape(tmp_path: Path) -> None:
    from scripts.run_task_backtest import path_under

    with pytest.raises(SystemExit):
        path_under(tmp_path / "runs", "../evil.json", "--run-name")


def test_post_heartbeat_without_csrf_header_is_rejected() -> None:
    response = TestClient(api_main.app).post("/heartbeat")

    assert response.status_code == 403


def test_post_heartbeat_with_csrf_header_records_last_seen() -> None:
    client = TestClient(api_main.app)

    response = client.post("/heartbeat", headers=CSRF_HEADER)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert api_main.heartbeat.last_seen is not None


def test_post_shutdown_without_csrf_header_is_rejected() -> None:
    response = TestClient(api_main.app).post("/shutdown")

    assert response.status_code == 403


def test_post_shutdown_without_owning_server_is_a_harmless_no_op() -> None:
    """Under TestClient (and the Vite-dev `open_research_api.cmd` process), no
    research_api.__main__ launcher ever sets app.state.server — shutdown must
    still respond cleanly rather than raising."""
    response = TestClient(api_main.app).post("/shutdown", headers=CSRF_HEADER)

    assert response.status_code == 200
    assert response.json() == {"status": "shutting down"}


def test_post_shutdown_signals_the_owning_server_to_exit() -> None:
    class FakeServer:
        should_exit = False

    fake_server = FakeServer()
    api_main.app.state.server = fake_server
    try:
        response = TestClient(api_main.app).post("/shutdown", headers=CSRF_HEADER)
    finally:
        del api_main.app.state.server

    assert response.status_code == 200
    assert fake_server.should_exit is True
