import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parents[3]


def load_hook() -> ModuleType:
    path = ROOT / ".claude" / "hooks" / "claude_post_tool_use_hygiene.py"
    spec = importlib.util.spec_from_file_location("claude_post_tool_use_hygiene", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


HOOK = load_hook()


def invoke_main(payload: object, root: Path, run_results: list[tuple[int, str, str]]) -> tuple[int, str, list[list[str]]]:
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    commands: list[list[str]] = []
    results = iter(run_results)

    def fake_run(_root: Path, args: list[str]) -> tuple[int, str, str]:
        commands.append(args)
        return next(results)

    with (
        patch.object(HOOK.sys, "stdin", stdin),
        patch.object(HOOK.sys, "stdout", stdout),
        patch.object(HOOK, "repo_root", return_value=root),
        patch.object(HOOK, "run", side_effect=fake_run),
    ):
        exit_code = HOOK.main()

    return exit_code, stdout.getvalue(), commands


def expected_command(root: Path, rel_path: str) -> list[str]:
    return [
        "uv",
        "run",
        "--no-sync",
        "--project",
        str(root),
        "ruff",
        "check",
        "--no-fix",
        "--select",
        "E722,F601,F602,F634",
        "--output-format",
        "concise",
        "--",
        rel_path,
    ]


def test_clean_python_edit_runs_only_read_only_ruff_check(tmp_path: Path) -> None:
    target = tmp_path / "src" / "sample.py"
    target.parent.mkdir()
    target.write_text("value = 1\n", encoding="utf-8")
    payload = {"cwd": str(tmp_path), "tool_name": "Write", "tool_input": {"file_path": str(target)}}

    exit_code, output, commands = invoke_main(payload, tmp_path, [(0, "", "")])

    assert exit_code == 0
    assert output == ""
    assert commands == [expected_command(tmp_path, "src/sample.py")]


def test_ruff_failure_returns_claude_blocking_json(tmp_path: Path) -> None:
    target = tmp_path / "src" / "sample.py"
    target.parent.mkdir()
    target.write_text('{"a": 1, "a": 2}\n', encoding="utf-8")
    payload = {"cwd": str(tmp_path), "tool_name": "Edit", "tool_input": {"file_path": str(target)}}

    exit_code, output, _commands = invoke_main(payload, tmp_path, [(1, "F601 duplicate key", "")])

    assert exit_code == 0
    assert json.loads(output) == {
        "decision": "block",
        "reason": "`ruff check` failed on `src/sample.py`.\nF601 duplicate key",
    }


def test_non_python_edit_is_ignored(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "sample.md"
    target.parent.mkdir()
    target.write_text("content\n", encoding="utf-8")
    payload = {"cwd": str(tmp_path), "tool_name": "Write", "tool_input": {"file_path": str(target)}}

    exit_code, output, commands = invoke_main(payload, tmp_path, [])

    assert exit_code == 0
    assert output == ""
    assert commands == []


@pytest.mark.parametrize("raw_input", ["", "{not-json"])
def test_invalid_json_is_ignored(raw_input: str) -> None:
    stdin = io.StringIO(raw_input)
    stdout = io.StringIO()

    with patch.object(HOOK.sys, "stdin", stdin), patch.object(HOOK.sys, "stdout", stdout):
        exit_code = HOOK.main()

    assert exit_code == 0
    assert stdout.getvalue() == ""


@pytest.mark.parametrize("path_style", ["backslash", "forward-slash"])
def test_windows_path_input_becomes_repo_relative_argument(tmp_path: Path, path_style: str) -> None:
    target = tmp_path / "src" / "windows.py"
    target.parent.mkdir()
    target.write_text("value = 1\n", encoding="utf-8")
    file_path = str(target).replace("/", "\\") if path_style == "backslash" else target.as_posix()
    payload = {"cwd": str(tmp_path), "tool_input": {"file_path": file_path}}

    _exit_code, _output, commands = invoke_main(payload, tmp_path, [(0, "", "")])

    assert commands == [expected_command(tmp_path, "src/windows.py")]


def test_unknown_payload_does_not_scan_unrelated_dirty_files(tmp_path: Path) -> None:
    dirty = tmp_path / "src" / "unrelated.py"
    dirty.parent.mkdir()
    dirty.write_text("value = 1\n", encoding="utf-8")
    payload = {"cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {"command": "echo hi"}}

    exit_code, output, commands = invoke_main(payload, tmp_path, [])

    assert exit_code == 0
    assert output == ""
    assert commands == []


def test_option_like_filename_does_not_write_ruff_output(tmp_path: Path) -> None:
    target = tmp_path / "--output-file=victim.py"
    target.write_text('data = {"key": 1, "key": 2}\n', encoding="utf-8")
    (tmp_path / "victim.py").write_text("sentinel = 42\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text("fix = true\nunsafe-fixes = true\n", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    result = subprocess.run(
        [sys.executable, str(ROOT / ".claude/hooks/claude_post_tool_use_hygiene.py")],
        cwd=ROOT,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)},
        input=json.dumps({"cwd": str(tmp_path), "tool_name": "Write", "tool_input": {"file_path": str(target)}}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    payload = json.loads(result.stdout)
    assert "F601" in payload["reason"]
    assert "--output-file=victim.py" in payload["reason"]
    for name, content in before.items():
        assert (tmp_path / name).read_bytes() == content
