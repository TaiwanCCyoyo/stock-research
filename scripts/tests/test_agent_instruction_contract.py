import json
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_pre_commit_mypy_receives_targeted_python_files() -> None:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    local_repo = next(repo for repo in config["repos"] if repo["repo"] == "local")
    mypy_hook = next(hook for hook in local_repo["hooks"] if hook["id"] == "mypy")

    # test_mypy_scopes exercises the configured entrypoint with real Mypy.
    assert mypy_hook.get("require_serial", False) is True
    assert mypy_hook.get("pass_filenames", True) is True
    assert mypy_hook["types"] == ["python"]


def test_claude_uses_pyright_lsp_without_project_ruff_lsp() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))

    assert settings["enabledPlugins"]["pyright-lsp@claude-plugins-official"] is True
    assert "ruff-lsp@agent-starter-kit" not in settings["enabledPlugins"]
    assert "agent-starter-kit" not in settings["extraKnownMarketplaces"]
    assert not (ROOT / ".claude" / "marketplace").exists()


def test_claude_native_workflow_does_not_require_external_workflow_plugins() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    plugins = settings["enabledPlugins"]

    assert plugins["superpowers@claude-plugins-official"] is False
    assert plugins["ponytail@ponytail"] is False
    assert plugins["andrej-karpathy-skills@karpathy-skills"] is False
    assert plugins["github@claude-plugins-official"] is True
    assert plugins["skill-creator@claude-plugins-official"] is True
    assert not (ROOT / ".codex" / "skills" / "karpathy-guidelines").exists()


def test_claude_and_codex_use_read_only_ruff_diagnostics() -> None:
    claude_settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    codex_config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))

    assert set(claude_settings["hooks"]) == {"PostToolUse"}
    assert claude_settings["hooks"]["PostToolUse"][0]["matcher"] == "Edit|Write"
    assert codex_config["hooks"]["PostToolUse"][0]["matcher"] == "apply_patch|Edit|Write"
    assert (ROOT / ".claude" / "hooks" / "claude_post_tool_use_hygiene.py").exists()
    assert (ROOT / ".codex" / "hooks" / "codex_post_tool_use_hygiene.py").exists()

    claude_hook = (ROOT / ".claude" / "hooks" / "claude_post_tool_use_hygiene.py").read_text(encoding="utf-8")
    codex_hook = (ROOT / ".codex" / "hooks" / "codex_post_tool_use_hygiene.py").read_text(encoding="utf-8")
    assert '"E722,F601,F602,F634"' in claude_hook
    assert '"--no-fix"' in claude_hook
    assert '"F401,F841,F842"' in codex_hook


def test_session_hooks_do_not_depend_on_shared_memory_bootstrap() -> None:
    """The retired shared-memory bootstrap forced hooks to mutate `sys.path` before
    importing, which only linted with an `E402` exemption. Both are gone, and this
    guards the exemption against creeping back.

    It checks for that specific exemption rather than for any `[lint.per-file-ignores]`
    table: research scripts under `tasks/` legitimately carry a `T201` ignore, because
    their stdout is the study's report rather than incidental logging, and that has
    nothing to do with how the hooks import.
    """
    ruff_config = tomllib.loads((ROOT / "ruff.toml").read_text(encoding="utf-8"))
    per_file_ignores = ruff_config.get("lint", {}).get("per-file-ignores", {})

    assert "E402" not in str(ruff_config)
    for pattern, codes in per_file_ignores.items():
        assert not pattern.startswith((".claude", ".codex", ".agent", "scripts")), pattern
        assert set(codes) <= {"T201"}, pattern


def test_codex_uses_native_memories_without_project_mcp_servers() -> None:
    config = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))

    assert config["features"]["hooks"] is True
    assert config["features"]["memories"] is True
    assert "mcp_servers" not in config
    assert not (ROOT / ".mcp.json").exists()


def test_agent_hook_configs_have_no_stop_event() -> None:
    codex = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))

    assert set(codex["hooks"]) == {"PostToolUse"}


def test_codex_agents_keep_unique_roles_and_bounded_permissions() -> None:
    agent_dir = ROOT / ".codex" / "agents"

    assert {
        "commit-specialist",
        "doc-translator",
        "signal-miner",
        "task-worker",
        "researcher",
    }.issubset({path.stem for path in agent_dir.glob("*.toml")})

    names: set[str] = set()
    writable = {"task_worker", "commit-specialist", "doc_translator", "researcher"}
    for path in agent_dir.glob("*.toml"):
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        assert config["name"] not in names
        names.add(config["name"])
        assert config["model"]
        assert config["model_reasoning_effort"] in {"low", "medium", "high", "xhigh", "max", "ultra"}
        assert config["sandbox_mode"] == ("workspace-write" if config["name"] in writable else "read-only")
