"""Functional impact selection and native CI dispatch; never executes a full suite."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts import ci_scope


@pytest.mark.parametrize(
    ("path", "domain", "consumer"),
    [
        ("research_core/opportunity_history_store.py", "opportunity", "tests/test_opportunity_history_api.py"),
        ("research_core/patterns/hhhl/v4/sources.zip", "hhhl", "scripts/tests/test_hhhl_v4_source.py"),
        ("research_core/patterns/hhhl/sources.json", "hhhl", "scripts/tests/test_pattern_sources.py"),
        ("tasks/20261010-hhhl-v4-probability/sources/hhhl_rule_v4.zip", "hhhl", "scripts/tests/test_validate_hhhl_v4_source.py"),
        ("research_core/feature_atlas_features.py", "atlas", "scripts/tests/test_build_feature_discrimination_atlas.py"),
        ("research_core/sector_waves.py", "sector", "scripts/tests/test_sector_wave_catalog_io.py"),
        ("research_core/market_context.py", "market_context", "scripts/tests/test_market_context.py"),
        ("research_core/method_environment_interactions.py", "method_environment", "scripts/tests/test_method_environment_runner.py"),
    ],
)
def test_domain_and_downstream_union(path: str, domain: str, consumer: str) -> None:
    plan = ci_scope.make_plan([("M", path)])
    assert not plan["full"]
    assert domain in plan["domains"]
    assert consumer in plan["python_tests"]
    assert "tests/test_opportunity_history_api.py" in plan["python_tests"]
    assert plan["frontend"]
    assert "scripts/tests/test_research_ledger.py" not in plan["python_tests"]
    assert plan["reasons"]


@pytest.mark.parametrize("path", ["research_web/src/app/App.tsx", r"research_web\src\components\Legend.tsx"])
def test_pure_ui_checks_frontend_without_market_tests(path: str) -> None:
    plan = ci_scope.make_plan([("M", path)])
    assert not plan["full"]
    assert plan["frontend"]
    assert plan["python_tests"] == []


def test_api_export_adds_python_contracts() -> None:
    plan = ci_scope.make_plan([("M", "research_web/src/api/artifacts.ts")])
    assert not plan["full"]
    assert "scripts/tests/test_saved_research_studio.py" in plan["python_tests"]
    assert "tests/test_research_api_security.py" in plan["python_tests"]


@pytest.mark.parametrize("path", ["AGENTS.md", ".codex/hooks/post_tool_use.py", "docs/en/git-workflow.md"])
def test_instructions_and_prose_keep_contracts_without_market_compute(path: str) -> None:
    plan = ci_scope.make_plan([("M", path)])
    assert not plan["full"]
    assert "scripts/tests/test_agent_instruction_contract.py" in plan["python_tests"]
    assert "scripts/tests/test_research_execution_prices.py" not in plan["python_tests"]


@pytest.mark.parametrize(
    "path",
    [
        "research_core/price_basis.py",
        "research_core/ledger.py",
        "research_core/derived_cache.py",
        "research_core/artifact_store.py",
        "research_core/evidence.py",
        "research_core/jobs.py",
        "uv.lock",
        "stock-data-downloader",
        "research_web/package-lock.json",
        "pyproject.toml",
        "tests/conftest.py",
        ".github/dependabot.yml",
        "unknown/new.py",
        "tests/test_new_consumer.py",
    ],
)
def test_unknown_and_shared_fallback_contains_every_test(path: str) -> None:
    plan = ci_scope.make_plan([("M", path)])
    assert plan["full"]
    assert plan["frontend"]
    assert plan["python_tests"] == ci_scope.test_inventory(ci_scope.ROOT, ci_scope.load_manifest())
    assert "tests/test_data_loader_symbols.py" in plan["python_tests"]
    assert ".claude/hooks/tests/test_claude_post_tool_use_hygiene.py" in plan["python_tests"]


CI_CONTRACT_TESTS = ["scripts/tests/test_ci_scope.py", "scripts/tests/test_file_hygiene.py", "scripts/tests/test_mypy_scopes.py"]


@pytest.mark.parametrize(
    "changes",
    [
        [("M", ".github/workflows/ci.yml")],
        [("M", "scripts/ci_scope.py")],
        [("M", "scripts/ci_test_domains.json")],
        [("M", "scripts/tests/test_ci_scope.py")],
        [("M", ".github/workflows/ci.yml"), ("M", "scripts/ci_scope.py"), ("M", "scripts/ci_test_domains.json"), ("M", "scripts/tests/test_ci_scope.py")],
    ],
)
def test_ci_only_changes_select_ci_contracts_without_full_suite(changes: list[tuple[str, str]]) -> None:
    plan = ci_scope.make_plan(changes)
    assert not plan["full"]
    assert not plan["frontend"]
    assert set(CI_CONTRACT_TESTS) <= set(plan["python_tests"])
    if all(path != "scripts/tests/test_ci_scope.py" for _status, path in changes):
        assert sorted(plan["python_tests"]) == CI_CONTRACT_TESTS
    else:  # the test file is also a hooks-domain contract; still a small targeted set, never the suite
        assert len(plan["python_tests"]) < plan["inventory_count"] // 10


def test_ci_only_exception_does_not_cover_other_workflows_or_mixed_changes() -> None:
    assert ci_scope.make_plan([("M", ".github/workflows/other.yml")])["full"]
    mixed = ci_scope.make_plan([("M", ".github/workflows/ci.yml"), ("M", "research_core/ledger.py")])
    assert mixed["full"]


def test_new_file_is_routed_only_when_a_domain_names_its_exact_path() -> None:
    named = ci_scope.make_plan([("A", "scripts/ci_test_domains.json")])
    assert not named["full"] and "scripts/tests/test_ci_scope.py" in named["python_tests"]
    assert ci_scope.make_plan([("A", "research_core/new_module.py")])["full"]  # wildcard owner only


def test_new_path_and_union_fail_safe() -> None:
    assert ci_scope.make_plan([("M", "research_web/src/app/App.tsx"), ("A", "docs/new.md")])["full"]
    plan = ci_scope.make_plan([("M", "research_core/hhhl_transition.py"), ("M", ".codex/skills/new/SKILL.md")])
    assert not plan["full"]
    assert "scripts/tests/test_hhhl_transition.py" in plan["python_tests"]
    assert "scripts/tests/test_agent_instruction_contract.py" in plan["python_tests"]


def test_inventory_records_all_roots_and_full_only() -> None:
    inventory = ci_scope.inventory_domains(ci_scope.ROOT, ci_scope.load_manifest())
    assert len(inventory) > 150
    assert inventory["scripts/tests/test_research_ledger.py"] == []
    assert "hhhl" in inventory["scripts/tests/test_hhhl_v4_source.py"]
    assert set(inventory) == set(ci_scope.test_inventory(ci_scope.ROOT, ci_scope.load_manifest()))


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", f"core.hooksPath={repo / '.no-hooks'}", "-c", "user.name=CI Fixture", "-c", "user.email=ci@example.invalid", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    ).stdout.strip()


def write(repo: Path, path: str, value: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def test_real_git_merge_base_ignores_unrelated_base_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "checkout with spaces"
    repo.mkdir()
    git(repo, "init")
    write(repo, "research_web/src/app/App.tsx", "initial\n")
    common = commit(repo, "initial")
    git(repo, "checkout", "-b", "target")
    write(repo, "research_core/ledger.py", "base-only\n")
    base = commit(repo, "target core change")
    git(repo, "checkout", "-b", "feature", common)
    write(repo, "research_web/src/app/App.tsx", "changed\n")
    head = commit(repo, "UI change")
    monkeypatch.chdir(repo)
    plan = ci_scope.select_plan(base, head)
    assert plan["merge_base"] == common
    assert not plan["full"]
    assert plan["frontend"]
    assert plan["python_tests"] == []


@pytest.mark.parametrize("operation", ["delete", "rename_to_docs", "non_ascii"])
def test_real_git_deletion_and_rename_unknown_paths_do_not_disappear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    git(tmp_path, "init")
    write(tmp_path, "unknown.py", "fixture\n")
    base = commit(tmp_path, "initial")
    source = tmp_path / "unknown.py"
    if operation == "delete":
        source.unlink()
    elif operation == "rename_to_docs":
        (tmp_path / "docs").mkdir()
        source.rename(tmp_path / "docs/guide.md")
    else:
        source.rename(tmp_path / "測試.py")
    head = commit(tmp_path, "changed")
    monkeypatch.chdir(tmp_path)
    assert ci_scope.select_plan(base, head)["full"]


def test_nul_parser_keeps_both_rename_paths_and_newlines() -> None:
    payload = b"R100\0unknown.py\0docs/guide.md\0M\0script\nname.py\0"
    assert ci_scope.parse_changes(payload) == [("R", "unknown.py"), ("R", "docs/guide.md"), ("M", "script\nname.py")]
    with pytest.raises(ValueError):
        ci_scope.parse_changes(b"R100\0old.py\0")


def test_initial_and_explicit_full_only_select_never_execute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git(tmp_path, "init")
    write(tmp_path, "README.md", "fixture\n")
    commit(tmp_path, "root")
    monkeypatch.chdir(tmp_path)
    assert ci_scope.select_plan("0" * 40, "HEAD")["full"]
    assert ci_scope.make_plan([], force_full=True)["full"]


def test_cli_failure_does_not_emit_green_output(tmp_path: Path) -> None:
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


def test_executor_passes_actual_selected_paths_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = ci_scope.make_plan([("M", "research_core/hhhl_transition.py")])
    observed: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed.append(command)
        assert kwargs["cwd"] == ci_scope.ROOT
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(ci_scope.subprocess, "run", fake_run)
    assert ci_scope.execute_plan(plan) == 7
    assert observed == [[sys.executable, "-m", "pytest", *plan["python_tests"]]]
    assert "scripts/tests/test_research_ledger.py" not in observed[0]


def test_executor_rejects_unsafe_or_empty_plan() -> None:
    with pytest.raises(ValueError):
        ci_scope.execute_plan({"python_tests": ["../private.py"], "frontend": False})
    with pytest.raises(ValueError):
        ci_scope.execute_plan({"python_tests": [], "frontend": False})
    assert ci_scope.execute_plan({"python_tests": [], "frontend": True}) == 0


def test_manual_cli_plan_is_serialized_without_executing(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    output = tmp_path / "output.txt"
    result = subprocess.run(
        [sys.executable, str(Path(ci_scope.__file__).resolve()), "--full", "--plan", str(plan_path), "--output", str(output)],
        cwd=ci_scope.ROOT,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(plan_path.read_text(encoding="utf-8"))["full"]
    assert "full=true" in output.read_text(encoding="utf-8")


def test_workflow_retains_stable_check_and_explicit_full_entry() -> None:
    workflow = yaml.load((ci_scope.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert "push" not in workflow["on"]
    assert "schedule" not in workflow["on"]
    assert "workflow_dispatch" in workflow["on"]
    assert "paths-ignore" not in workflow["on"]["pull_request"]
    job = workflow["jobs"]["repository-checks"]
    assert job["name"] == "repository-checks"
    assert "if" not in job
    steps = {step["name"]: step for step in job["steps"] if "name" in step}
    assert "--full" in steps["Select test scope"]["run"]
    assert "--execute" in steps["Selected Python tests"]["run"]
    assert "SKIP" not in steps["Repository checks"].get("env", {})
    assert "if" not in steps["Repository checks"]
    assert "steps.scope.outputs.frontend" in steps["Frontend validation"]["if"]
    assert all(command in steps["Frontend validation"]["run"] for command in ["npm test", "npm run lint", "npm run build"])
    # test:local-data reads private local artifacts that a public hosted runner never has; run it locally only
    assert "test:local-data" not in steps["Frontend validation"]["run"]


@pytest.mark.skipif(os.name != "nt", reason="Windows CI native command dispatch")
@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch"])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_repository_check_native_dispatch(tmp_path: Path, event: str, exit_code: int) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None
    workflow = yaml.load((ci_scope.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    step = next(step for step in workflow["jobs"]["repository-checks"]["steps"] if step.get("name") == "Repository checks")
    (tmp_path / "uv.cmd").write_text('@echo off\n> "%CI_ARGS_FILE%" echo %*\nexit /b %CI_EXIT_CODE%\n', encoding="ascii")
    args_file = tmp_path / "arguments.txt"
    environment = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ.get("PATH", ""),
        "CHECK_EVENT": event,
        "CHECK_BASE": "1" * 40,
        "CHECK_HEAD": "2" * 40,
        "CI_ARGS_FILE": str(args_file),
        "CI_EXIT_CODE": str(exit_code),
    }
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", step["run"]], cwd=tmp_path, env=environment, capture_output=True, timeout=30)
    assert result.returncode == exit_code, result.stderr
    arguments = args_file.read_text(encoding="ascii")
    assert "pre-commit run" in arguments
    if event == "workflow_dispatch":
        assert "--all-files" in arguments
        assert "--from-ref" not in arguments
    else:
        assert "--from-ref " + "1" * 40 in arguments
        assert "--to-ref " + "2" * 40 in arguments
        assert "--all-files" not in arguments


def test_changed_inventory_forces_full_without_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = ci_scope.load_manifest()
    manifest["reviewed_tests"] = manifest["reviewed_tests"][:-1]
    monkeypatch.setattr(ci_scope, "load_manifest", lambda: manifest)
    plan = ci_scope.make_plan([("M", "research_web/src/app/App.tsx")])
    assert plan["full"]
    assert any("inventory differs" in reason for reason in plan["reasons"])


def test_draft_full_gate_blocks_without_certifying_or_running_tests() -> None:
    workflow = yaml.load((ci_scope.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert "ready_for_review" in workflow["on"]["pull_request"]["types"]
    steps = workflow["jobs"]["repository-checks"]["steps"]
    gate = next(step for step in steps if step.get("name") == "Draft full validation remains pending")
    assert "github.event.pull_request.draft" in gate["if"]
    assert "steps.scope.outputs.full == 'true'" in gate["if"]
    assert steps.index(gate) < next(i for i, step in enumerate(steps) if step.get("name") == "Selected Python tests")


@pytest.mark.skipif(shutil.which("pwsh") is None and shutil.which("powershell") is None, reason="PowerShell is unavailable; YAML gate contract remains covered")
def test_draft_full_gate_native_exit(tmp_path: Path) -> None:
    workflow = yaml.load((ci_scope.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    gate = next(step for step in workflow["jobs"]["repository-checks"]["steps"] if step.get("name") == "Draft full validation remains pending")
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", gate["run"]], cwd=tmp_path, capture_output=True, timeout=30)
    assert result.returncode == 1
    assert b"validation remains pending" in result.stdout


@pytest.mark.parametrize("filename", ["test_widget.py", "widget_test.py"])
def test_full_inventory_executes_both_pytest_filename_styles(tmp_path: Path, filename: str) -> None:
    target = tmp_path / "tests" / filename
    target.parent.mkdir()
    target.write_text(
        "from pathlib import Path\n"
        "def test_actual_execution():\n"
        "    Path(__file__).with_suffix('.executed').write_text('ran')\n"
        "    assert False, 'new-test-executed'\n",
        encoding="utf-8",
    )
    plan = ci_scope.make_plan([("A", f"tests/{filename}")], root=tmp_path)
    assert plan["full"]
    assert plan["python_tests"] == [f"tests/{filename}"]
    # This invokes only the one synthetic failing fixture, never the repository suite.
    assert ci_scope.execute_plan(plan, root=tmp_path) == 1
    assert target.with_suffix(".executed").read_text() == "ran"


@pytest.mark.parametrize("source", ["research_core/patterns/hhhl/sources.json", "research_core/patterns/hhhl/v4/sources.zip"])
def test_hhhl_sources_select_fresh_process_consumer(source: str) -> None:
    plan = ci_scope.make_plan([("M", source)])
    assert not plan["full"]
    assert "scripts/tests/test_cache_execution.py" in plan["python_tests"]


@pytest.mark.parametrize(
    "source", ["research_core/feature_atlas_outcomes.py", "research_core/market_context.py", "research_core/method_environment_interactions.py"]
)
def test_shared_research_domains_include_industry_role_consumers(source: str) -> None:
    plan = ci_scope.make_plan([("M", source)])
    assert not plan["full"]
    assert "scripts/tests/test_industry_role_comparison.py" in plan["python_tests"]
    assert "scripts/tests/test_industry_role_runner.py" in plan["python_tests"]


def test_atlas_verification_includes_hhhl_builders_and_cycle_is_finite() -> None:
    plan = ci_scope.make_plan([("M", "research_core/feature_atlas_dataset.py")])
    assert not plan["full"]
    assert "scripts/tests/test_build_hhhl_v4_probability.py" in plan["python_tests"]
    assert "scripts/tests/test_validate_hhhl_v4_source.py" in plan["python_tests"]
    assert {"sector", "method_environment", "hhhl", "opportunity", "atlas"} <= set(plan["domains"])
    assert "scripts/tests/test_research_ledger.py" not in plan["python_tests"]


def test_draft_runs_hosted_contracts_and_hooks_before_pending_gate() -> None:
    workflow = yaml.load((ci_scope.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["repository-checks"]["steps"]
    indices = {step["name"]: i for i, step in enumerate(steps) if "name" in step}
    assert (
        indices["Repository checks"]
        < indices["Draft selector and CI contracts"]
        < indices["Draft full validation remains pending"]
        < indices["Selected Python tests"]
    )
    targeted = steps[indices["Draft selector and CI contracts"]]
    assert "scripts/tests/test_ci_scope.py" in targeted["run"]
    assert "scripts/tests/test_mypy_scopes.py" in targeted["run"]
    assert "scripts/tests/test_file_hygiene.py" in targeted["run"]
    assert "--execute" not in targeted["run"]


def test_pinned_node_and_built_frontend_precede_python_consumers() -> None:
    workflow = yaml.load((ci_scope.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["repository-checks"]["steps"]
    indices = {step["name"]: i for i, step in enumerate(steps) if "name" in step}
    assert indices["Setup Node"] < indices["Frontend validation"] < indices["Selected Python tests"]
    assert "npm run build" in steps[indices["Frontend validation"]]["run"]
    assert steps[indices["Setup Node"]]["with"]["node-version"] == "24"


def test_changed_suffix_style_hook_test_is_always_selected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    names = [".codex/hooks/tests/test_existing.py", ".codex/hooks/tests/checker_test.py"]
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_example(): pass\n", encoding="utf-8")
    manifest = ci_scope.load_manifest()
    manifest["reviewed_tests"] = names
    monkeypatch.setattr(ci_scope, "load_manifest", lambda: manifest)
    plan = ci_scope.make_plan([("M", names[1])], root=tmp_path)
    assert not plan["full"]
    assert set(plan["python_tests"]) == set(names)
