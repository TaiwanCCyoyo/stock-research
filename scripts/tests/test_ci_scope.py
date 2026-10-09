import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts import ci_scope


@pytest.mark.parametrize("path", ["README.md", "AGENTS.md", "docs/en/guide.md", "docs/中文 空白.RST"])
def test_known_prose_skips_tests(path: str) -> None:
    assert not ci_scope.needs_tests([path])


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        ".github/guide.md",
        "scripts/ci_scope.py",
        "scripts/guide.md",
        "tests/fixture.md",
        ".codex/hooks/guide.md",
        ".pre-commit-config.yaml",
        "pyproject.toml",
        "uv.lock",
        "requirements.txt",
        "shioaji_stock_prices",
        "src/module.py",
        "research_web/package-lock.json",
        "docs/example.py",
        "docs/example.html",
        "unknown/file.md",
        "unknown",
        "script\nname.py",
    ],
)
def test_code_dependencies_configuration_and_unknown_paths_run_tests(path: str) -> None:
    assert ci_scope.needs_tests(["docs/guide.md", path])


def test_windows_paths() -> None:
    assert not ci_scope.needs_tests([r"docs\en\guide.md"])
    assert ci_scope.needs_tests([r"scripts\guide.md"])


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"core.hooksPath={repo / '.no-hooks'}",
            "-c",
            "user.name=CI Scope Test",
            "-c",
            "user.email=ci-scope@example.invalid",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    return result.stdout.strip()


@pytest.mark.parametrize("change", ["prose", "delete_code", "code_to_docs", "docs_to_code", "non_ascii_code"])
def test_real_cli_classifies_complete_diff(tmp_path: Path, change: str) -> None:
    repo = tmp_path / "checkout with spaces"
    repo.mkdir()
    git(repo, "init")
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text("example\n", encoding="utf-8")
    (repo / "code.py").write_text("print('example')\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Initial fixture")
    base = git(repo, "rev-parse", "HEAD")
    if change == "prose":
        (repo / "docs" / "中文 guide.md").write_text("prose\n", encoding="utf-8")
    elif change == "delete_code":
        (repo / "code.py").unlink()
    elif change == "code_to_docs":
        (repo / "code.py").rename(repo / "docs" / "code.md")
    elif change == "docs_to_code":
        (repo / "docs" / "guide.md").rename(repo / "guide.py")
    else:
        (repo / "中文 code.py").write_text("print('example')\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "Changed fixture")
    output = tmp_path / "github output.txt"
    output.write_text("existing=value\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(Path(ci_scope.__file__).resolve()), "--base", base, "--head", "HEAD", "--output", str(output)],
        cwd=repo,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    expected = "false" if change == "prose" else "true"
    assert output.read_text(encoding="utf-8") == f"existing=value\nrun_tests={expected}\n"


def test_cli_git_failure_does_not_publish_skip(tmp_path: Path) -> None:
    git(tmp_path, "init")
    output = tmp_path / "output.txt"
    result = subprocess.run(
        [sys.executable, str(Path(ci_scope.__file__).resolve()), "--base", "missing", "--head", "HEAD", "--output", str(output)],
        cwd=tmp_path,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert not output.exists()


@pytest.mark.parametrize("filename", ["README.md", "code.py"])
@pytest.mark.parametrize("head_form", ["HEAD", "sha"])
def test_initial_push_runs_all_tests_without_parent(tmp_path: Path, filename: str, head_form: str) -> None:
    git(tmp_path, "init")
    (tmp_path / filename).write_text("root fixture\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "Only root commit")
    assert git(tmp_path, "rev-list", "--count", "HEAD") == "1"
    head = "HEAD" if head_form == "HEAD" else git(tmp_path, "rev-parse", "HEAD")
    output = tmp_path / "output.txt"
    result = subprocess.run(
        [sys.executable, str(Path(ci_scope.__file__).resolve()), "--base", "0" * 40, "--head", head, "--output", str(output)],
        cwd=tmp_path,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8") == "run_tests=true\n"


@pytest.mark.parametrize("invalid", ["missing_head", "unborn_head", "non_repo", "short_null", "long_null"])
def test_initial_push_does_not_mask_git_errors(tmp_path: Path, invalid: str) -> None:
    base = "0" * 40
    head = "HEAD"
    if invalid != "non_repo":
        git(tmp_path, "init")
    if invalid not in {"unborn_head", "non_repo"}:
        (tmp_path / "README.md").write_text("root fixture\n", encoding="utf-8")
        git(tmp_path, "add", ".")
        git(tmp_path, "commit", "-m", "Root fixture")
    if invalid == "missing_head":
        head = "missing"
    elif invalid == "short_null":
        base = "0" * 39
    elif invalid == "long_null":
        base = "0" * 41
    output = tmp_path / "output.txt"
    result = subprocess.run(
        [sys.executable, str(Path(ci_scope.__file__).resolve()), "--base", base, "--head", head, "--output", str(output)],
        cwd=tmp_path,
        env={**os.environ, "GIT_CEILING_DIRECTORIES": str(tmp_path.parent)},
        capture_output=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert not output.exists()


@pytest.mark.skipif(os.name != "nt", reason="Exercise the Windows CI native-command dispatch")
@pytest.mark.parametrize("base", ["0" * 40, "1" * 40, "0" * 39, "0" * 41])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_repository_checks_dispatch_and_failure_status(tmp_path: Path, base: str, exit_code: int) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None, "Windows CI needs PowerShell"
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    step = next(step for step in workflow["jobs"]["repository-checks"]["steps"] if step.get("name") == "Repository checks")
    fake_uv = tmp_path / "uv.cmd"
    fake_uv.write_text('@echo off\n> "%CI_ARGS_FILE%" echo %*\nexit /b %CI_EXIT_CODE%\n', encoding="ascii")
    args_file = tmp_path / "arguments.txt"
    environment = dict(os.environ)
    environment.update(
        PATH=str(tmp_path) + os.pathsep + os.environ.get("PATH", ""),
        CHECK_BASE=base,
        CHECK_HEAD="2" * 40,
        CI_ARGS_FILE=str(args_file),
        CI_EXIT_CODE=str(exit_code),
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", step["run"]],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == exit_code, result.stderr
    arguments = args_file.read_text(encoding="ascii")
    assert "pre-commit run" in arguments
    if base == "0" * 40:
        assert "--all-files" in arguments
        assert "--from-ref" not in arguments
    else:
        assert f"--from-ref {base}" in arguments
        assert "--to-ref " + "2" * 40 in arguments
        assert "--all-files" not in arguments


def test_nul_delimited_paths_preserve_newlines_and_non_ascii(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert "--no-renames" in command
        assert "-z" in command
        assert kwargs["check"] is True
        return subprocess.CompletedProcess(command, 0, os.fsencode("docs/中文\nname.md\0script\nname.py\0"))

    monkeypatch.setattr(ci_scope.subprocess, "run", fake_run)
    assert ci_scope.select_scope("base", "head")


def test_workflow_keeps_required_checks_and_gates_only_test_work() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert "paths-ignore" not in workflow["on"]["pull_request"]
    job = workflow["jobs"]["repository-checks"]
    assert job["name"] == "repository-checks"
    assert "if" not in job
    # runner context is unavailable at job.env and would reject the workflow.
    assert all("runner." not in value for value in job.get("env", {}).values())
    steps = job["steps"]
    scope_index = next(i for i, step in enumerate(steps) if step.get("id") == "scope")
    install_index = next(i for i, step in enumerate(steps) if step.get("name") == "Install dependencies")
    assert scope_index < install_index
    assert "--no-project" in steps[scope_index]["run"]
    by_name = {step["name"]: step for step in steps if "name" in step}
    for name in [
        "Headless compatibility without optional viewers",
        "Install optional tools for development checks",
        "Tests",
        "Optional viewer and legacy rendering compatibility",
    ]:
        assert by_name[name]["if"] == "steps.scope.outputs.run_tests == 'true'"
    for name in ["Install dependencies", "Repository checks"]:
        assert "if" not in by_name[name]
    assert "--from-ref" in by_name["Repository checks"]["run"]
    concurrency = workflow["concurrency"]
    assert "github.event.pull_request.number || github.run_id" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
    hook_cache = by_name["Cache hook environments"]["with"]
    assert hook_cache["path"] == "${{ env.PRE_COMMIT_HOME }}"
    assert "restore-keys" not in hook_cache
    for identity in ["runner.os", "runner.arch", "steps.hook-python.outputs.identity", "steps.scope.outputs.run_tests"]:
        assert identity in hook_cache["key"]
