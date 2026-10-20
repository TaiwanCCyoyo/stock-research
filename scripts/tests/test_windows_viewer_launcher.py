"""Run the Windows HTTP launcher without starting a service or accessing data."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd launcher")
def test_api_launcher_uses_optional_viewer_and_loopback(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "scripts" / "research" / "open_research_api.cmd"
    launcher = tmp_path / "scripts" / "research" / source.name
    launcher.parent.mkdir(parents=True)
    shutil.copyfile(source, launcher)
    (tmp_path / "uv.cmd").write_text("@echo off\necho %*\nexit /b 19\n", encoding="utf-8")
    result = subprocess.run(
        [os.environ["COMSPEC"], "/d", "/c", str(launcher)],
        cwd=tmp_path.parent,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 19, result.stdout + result.stderr
    assert result.stdout.strip() == "run --group viewer uvicorn research_api.main:app --host 127.0.0.1 --port 8503"


def dashboard_launcher_fixture(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    source = Path(__file__).resolve().parents[2] / "scripts" / "research" / "open_research_dashboard.cmd"
    launcher = tmp_path / "scripts" / "research" / source.name
    launcher.parent.mkdir(parents=True)
    shutil.copyfile(source, launcher)
    build_helper = tmp_path / "research_web" / "scripts" / "build-dashboard.mjs"
    build_helper.parent.mkdir(parents=True)
    build_helper.write_text("// mock launcher target\n", encoding="utf-8")
    (tmp_path / "research_web" / "dist").mkdir(parents=True)
    (tmp_path / "research_web" / "dist" / "index.html").write_text("", encoding="utf-8")
    environment = os.environ.copy()
    environment["RESEARCH_VIEWER_SKIP_BROWSER"] = "1"
    environment["PATH"] = f"{tmp_path};{environment['PATH']}"
    (tmp_path / "node.cmd").write_text(
        '@echo off\nif "%MOCK_NODE_EXIT_CODE%"=="" exit /b 0\nexit /b %MOCK_NODE_EXIT_CODE%\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.cmd").write_text(
        "@echo off\necho called>uv-called.txt\necho cwd=%CD%\necho %*\nexit /b 19\n",
        encoding="utf-8",
    )
    return launcher, environment


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd launcher")
def test_dashboard_launcher_resolves_repo_root_and_starts_module(tmp_path: Path) -> None:
    launcher, environment = dashboard_launcher_fixture(tmp_path)
    result = subprocess.run(
        [os.environ["COMSPEC"], "/d", "/c", str(launcher)],
        cwd=tmp_path.parent,
        capture_output=True,
        text=True,
        timeout=20,
        env=environment,
    )
    assert result.returncode == 19, result.stdout + result.stderr
    output = result.stdout.splitlines()
    assert output[0].casefold() == f"cwd={tmp_path}".casefold()
    assert output[1] == "run --group viewer python -m research_api"
    assert (tmp_path / "uv-called.txt").is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd launcher")
def test_dashboard_launcher_build_failure_stops_before_starting_api(tmp_path: Path) -> None:
    launcher, environment = dashboard_launcher_fixture(tmp_path)
    environment["MOCK_NODE_EXIT_CODE"] = "1"
    result = subprocess.run(
        [os.environ["COMSPEC"], "/d", "/c", str(launcher)],
        cwd=tmp_path.parent,
        capture_output=True,
        text=True,
        timeout=20,
        env=environment,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert not (tmp_path / "uv-called.txt").exists()
