import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parents[3]


def load_hook() -> ModuleType:
    path = ROOT / ".codex" / "hooks" / "codex_post_tool_use_hygiene.py"
    spec = importlib.util.spec_from_file_location("codex_post_tool_use_hygiene", path)
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
        "F",
        "--ignore",
        "F401,F841,F842",
        "--output-format",
        "concise",
        "--",
        rel_path,
    ]


def test_apply_patch_python_target_runs_read_only_ruff_check(tmp_path: Path) -> None:
    target = tmp_path / "src" / "sample.py"
    target.parent.mkdir()
    target.write_text("value = 1\n", encoding="utf-8")
    patch_text = """*** Begin Patch
*** Update File: src/sample.py
@@
-value = 0
+value = 1
*** End Patch
"""
    payload = {"cwd": str(tmp_path), "tool_name": "apply_patch", "tool_input": {"cmd": patch_text}}

    exit_code, output, commands = invoke_main(payload, tmp_path, [(0, "", "")])

    assert exit_code == 0
    assert output == ""
    assert commands == [expected_command(tmp_path, "src/sample.py")]


def test_ruff_failure_reports_diagnostics_without_replacing_tool_result(tmp_path: Path) -> None:
    target = tmp_path / "src" / "sample.py"
    target.parent.mkdir()
    target.write_text("value = missing_name\n", encoding="utf-8")
    payload = {"cwd": str(tmp_path), "tool_name": "Write", "tool_input": {"file_path": str(target)}}

    exit_code, output, _commands = invoke_main(payload, tmp_path, [(1, "F821 undefined name", "")])

    assert exit_code == 0
    assert json.loads(output) == {
        "systemMessage": "Post-edit Ruff diagnostics (advisory; pre-commit remains required):\nF821 undefined name",
        "continue": True,
    }


def test_non_python_edit_is_ignored(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "sample.md"
    target.parent.mkdir()
    target.write_text("content\n", encoding="utf-8")
    payload = {"cwd": str(tmp_path), "tool_name": "Edit", "tool_input": {"file_path": str(target)}}

    exit_code, output, commands = invoke_main(payload, tmp_path, [])

    assert exit_code == 0
    assert output == ""
    assert commands == []


@pytest.mark.parametrize("input_kind", ["command", "raw"])
def test_multi_file_patch_runs_one_check_on_only_existing_in_repo_python_files(tmp_path: Path, input_kind: str) -> None:
    for name in ("one.py", "two.py", "notes.md"):
        (tmp_path / name).write_text("", encoding="utf-8")
    outside = tmp_path.parent / "outside.py"
    outside.write_text("", encoding="utf-8")
    patch_text = "\n".join([
        "*** Begin Patch",
        "*** Update File: one.py",
        "*** Update File: two.py",
        "*** Update File: one.py",
        "*** Update File: notes.md",
        "*** Delete File: gone.py",
        "*** Update File: ../outside.py",
        "*** End Patch",
    ])
    tool_input = {"command": patch_text} if input_kind == "command" else patch_text

    _code, output, commands = invoke_main({"tool_input": tool_input}, tmp_path, [(0, "", "")])

    assert output == ""
    assert commands == [expected_command(tmp_path, "one.py") + ["two.py"]]


def test_entrypoint_reports_real_ruff_failure_without_applying_configured_fixes(tmp_path: Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "ruff.toml").write_text("fix = true\nunsafe-fixes = true\n", encoding="utf-8")
    target = tmp_path / "sample.py"
    source = 'value = missing_name\ndata = {"key": 1, "key": 2}\n'
    target.write_text(source, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / ".codex/hooks/codex_post_tool_use_hygiene.py")],
        cwd=ROOT,
        input=json.dumps({
            "cwd": str(tmp_path),
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Update File: sample.py\n*** End Patch"},
        }),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    payload = json.loads(result.stdout)
    assert "F821" in payload["systemMessage"]
    assert payload["continue"] is True
    assert "stopReason" not in payload
    assert target.read_text(encoding="utf-8") == source


def test_linter_timeout_returns_actionable_diagnostic(tmp_path: Path) -> None:
    with patch.object(HOOK.subprocess, "run", side_effect=subprocess.TimeoutExpired("ruff", 15)) as run:
        code, stdout, stderr = HOOK.run(tmp_path, ["ruff", "check", "sample.py"])

    assert code == 124
    assert stdout == ""
    assert "exceeded 15 seconds" in stderr
    assert run.call_args.kwargs["timeout"] == 15


def test_file_content_with_patch_headers_does_not_expand_check_scope(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("", encoding="utf-8")
    unrelated = tmp_path / "unrelated.py"
    unrelated.write_text("", encoding="utf-8")
    payload = {"tool_input": {"file_path": str(target), "content": "*** Begin Patch\n*** Update File: unrelated.py\n*** End Patch"}}

    _code, _output, commands = invoke_main(payload, tmp_path, [(0, "", "")])

    assert commands == [expected_command(tmp_path, "sample.py")]


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
    payload = {"cwd": str(tmp_path), "tool_name": "shell", "tool_input": {"command": "echo hi"}}

    exit_code, output, commands = invoke_main(payload, tmp_path, [])

    assert exit_code == 0
    assert output == ""
    assert commands == []


def test_outside_file_is_not_checked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")
    _, output, commands = invoke_main({"tool_input": {"file_path": str(outside)}}, repo, [])
    assert output == "" and commands == []


def test_tool_failure_is_bounded_advisory(tmp_path: Path) -> None:
    (tmp_path / "one.py").write_text("value = 1\n", encoding="utf-8")
    _, output, _ = invoke_main({"tool_input": {"file_path": "one.py"}}, tmp_path, [(127, "", "x" * 10000)])
    result = json.loads(output)
    assert result["continue"] is True
    assert len(result["systemMessage"]) <= 6000
