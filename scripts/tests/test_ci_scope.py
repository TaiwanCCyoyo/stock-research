"""Functional impact selection and native CI dispatch; never executes a full suite."""

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts import ci_scope

STRENGTH_TESTS = {"scripts/tests/test_strength_flags_v1.py", "scripts/tests/test_strength_flag_counts_v1.py"}


@pytest.mark.parametrize("status", ["A", "M"])
@pytest.mark.parametrize(
    "source",
    [
        "research_core/momentum_only_v1.py",
        "research_core/count_cube_v1.py",
        "research_core/pattern_scan_flags_v1.py",
        "research_core/hhhl_variants_observations.py",
        "research_core/maintained_adjusted_daily.py",
        "research_core/research_measurement_v1.py",
    ],
)
def test_strength_upstreams_select_both_downstream_tests(status: str, source: str) -> None:
    plan = ci_scope.make_plan([(status, source)])
    assert not plan["full"]
    assert "strength_flags" in plan["domains"]
    assert STRENGTH_TESTS <= set(plan["python_tests"])
    assert "scripts/tests/test_research_ledger.py" not in plan["python_tests"]


@pytest.mark.parametrize("status", ["A", "M"])
@pytest.mark.parametrize(
    "source",
    [
        "research_core/multiple_observations_v1.py",
        "research_core/strength_flags_v1.py",
        "research_core/strength_flag_counts_v1.py",
        "research_core/strength_flags_run_v1.py",
        "scripts/run_strength_flags.py",
        *sorted(STRENGTH_TESTS),
    ],
)
def test_strength_owned_sources_and_tests_select_the_complete_domain(status: str, source: str) -> None:
    plan = ci_scope.make_plan([(status, source)])
    assert not plan["full"] and not plan["frontend"]
    assert set(plan["domains"]) == {"strength_flags"}
    expected_tests = STRENGTH_TESTS.copy()
    if source in STRENGTH_TESTS:
        # This selector contract names the changed test, so the existing reference closure retains it too.
        expected_tests.add("scripts/tests/test_ci_scope.py")
    assert set(plan["python_tests"]) == expected_tests


@pytest.mark.parametrize("source", ["research_core/strength_flags_unreviewed_v2.py", "scripts/run_strength_unreviewed.py"])
def test_unknown_strength_sources_keep_full_safety_fallback(source: str) -> None:
    manifest = ci_scope.load_manifest()
    plan = ci_scope.make_plan([("A", source)])
    assert plan["full"] and plan["frontend"]
    assert plan["python_tests"] == ci_scope.test_inventory(ci_scope.ROOT, manifest)


@pytest.mark.parametrize(
    ("path", "domain", "consumer"),
    [
        ("research_core/opportunity_history_store.py", "opportunity", "tests/test_opportunity_history_api.py"),
        ("research_core/patterns/hhhl/v4/sources.zip", "hhhl", "scripts/tests/test_hhhl_v4_source.py"),
        ("research_core/patterns/hhhl/sources.json", "hhhl", "scripts/tests/test_pattern_sources.py"),
        ("tasks/20261010-hhhl-v4-probability/sources/hhhl_rule_v4.zip", "hhhl", "scripts/tests/test_validate_hhhl_v4_source.py"),
        ("research_core/multiple_outcomes_v1.py", "hhhl", "scripts/tests/test_multiple_outcomes_v1.py"),
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


@pytest.mark.parametrize("path", ["research_core/pattern_scan_daily_values_v1.py", "research_core/hhhl_variants_daily.py"])
def test_daily_conditions_kernels_select_the_shared_table_tests(path: str) -> None:
    """daily_conditions_v1 calls these PR17 kernels; changing one must still test the shared table."""
    plan = ci_scope.make_plan([("M", path)])
    assert not plan["full"]
    assert {"pattern_scan", "research_data"} <= set(plan["domains"])
    assert {"scripts/tests/test_daily_conditions_v1.py", "scripts/tests/test_maintained_adjusted_daily.py"} <= set(plan["python_tests"])
    if path.endswith("pattern_scan_daily_values_v1.py"):
        assert "scripts/tests/test_pattern_scan_daily_values_v1.py" in plan["python_tests"]


@pytest.mark.parametrize(
    ("path", "expected_domains", "existing_consumer_tests"),
    [
        (
            path,
            {"market_context", "method_environment", "sector", "opportunity", "research_data", "annual", "pattern_scan"},
            {
                "scripts/tests/test_method_environment_runner.py",
                "scripts/tests/test_sector_wave_catalog_io.py",
                "tests/test_opportunity_history_api.py",
            },
        )
        for path in ("research_core/market_context.py", "research_core/market_context_artifact.py")
    ]
    + [
        (
            path,
            {"hhhl", "opportunity", "research_data", "annual", "pattern_scan"},
            {"tests/test_opportunity_history_api.py", "scripts/tests/test_multiple_outcomes_v1.py"},
        )
        for path in ("research_core/hhhl_variants_paths.py", "research_core/hhhl_variants_observations.py")
    ],
)
def test_research_data_upstreams_keep_all_downstream_tests(path: str, expected_domains: set[str], existing_consumer_tests: set[str]) -> None:
    manifest = ci_scope.load_manifest()
    plan = ci_scope.make_plan([("M", path)])
    assert not plan["full"]
    assert set(plan["domains"]) == expected_domains | {"strength_flags"}
    assert set(manifest["domains"]["research_data"]["tests"]) <= set(plan["python_tests"])
    assert set(manifest["domains"]["annual"]["tests"]) <= set(plan["python_tests"])
    assert "scripts/tests/test_pattern_scan_shared_v1.py" in plan["python_tests"]
    assert existing_consumer_tests <= set(plan["python_tests"])
    assert plan["frontend"]
    assert "scripts/tests/test_research_ledger.py" not in plan["python_tests"]


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
        "research_core/json_integrity.py",
        "research_core/jobs.py",
        "uv.lock",
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
    "path",
    [
        "research_core/stock_feature_pool_v2.py",
        "research_core/feature_identity_v1.py",
    ],
)
def test_feature_block_upstreams_select_research_data_consumers(path: str) -> None:
    manifest = ci_scope.load_manifest()
    plan = ci_scope.make_plan([("M", path)])
    assert not plan["full"]
    assert set(plan["domains"]) == {"feature_blocks", "research_data", "annual", "pattern_scan", "strength_flags"}
    expected_tests = set(manifest["domains"]["feature_blocks"]["tests"]) | set(manifest["domains"]["research_data"]["tests"])
    expected_tests |= set(manifest["domains"]["annual"]["tests"])
    expected_tests |= set(manifest["domains"]["strength_flags"]["tests"])
    expected_tests |= {
        test for test in ci_scope.test_inventory(ci_scope.ROOT, manifest) if ci_scope.matches(test, manifest["domains"]["pattern_scan"]["tests"])
    }
    assert set(plan["python_tests"]) == expected_tests
    assert "scripts/tests/test_pattern_scan_shared_v1.py" in plan["python_tests"]
    assert not plan["frontend"]
    assert "scripts/tests/test_research_ledger.py" not in plan["python_tests"]


def test_feature_block_store_preserves_full_safety_fallback() -> None:
    manifest = ci_scope.load_manifest()
    plan = ci_scope.make_plan([("M", "research_core/feature_block_store_v1.py")])
    assert plan["full"]
    assert plan["python_tests"] == ci_scope.test_inventory(ci_scope.ROOT, manifest)
    assert plan["python_tests"] == manifest["reviewed_tests"]
    assert set(manifest["domains"]["research_data"]["tests"]) <= set(plan["python_tests"])


def test_feature_block_domain_routes_new_execution_contracts() -> None:
    plan = ci_scope.make_plan([("A", "research_core/stock_feature_pool_v1.py")])
    assert not plan["full"]
    assert "feature_blocks" in plan["domains"]
    assert "scripts/tests/test_stock_feature_pool_v1.py" in plan["python_tests"]
    assert "scripts/tests/test_feature_blocks_cli.py" in plan["python_tests"]
    assert "scripts/tests/test_prepared_stock_input_v1.py" in plan["python_tests"]
    # Shared numerical foundations retain the existing full safety fallback.
    assert ci_scope.make_plan([("A", "research_core/derived_features_selective_v1.py")])["full"]


ANNUAL_TESTS = {
    "scripts/tests/test_annual_completion.py",
    "scripts/tests/test_annual_completion_evidence.py",
    "scripts/tests/test_annual_completion_publication.py",
    "scripts/tests/test_annual_completion_report.py",
    "scripts/tests/test_annual_rotation.py",
    "scripts/tests/test_annual_statistics.py",
    "scripts/tests/test_annual_ranking_pool.py",
    "scripts/tests/test_annual_rotation_cli.py",
    "scripts/tests/test_annual_publication.py",
    "scripts/tests/test_annual_rotation_v2.py",
    "scripts/tests/test_json_integrity.py",
    "scripts/tests/test_verify_published_artifacts.py",
}

ANNUAL_COMPLETION_SOURCES = [
    "research_core/annual_rotation_v2.py",
    "research_core/annual_completion.py",
    "research_core/annual_completion_evidence.py",
    "research_core/annual_completion_publication.py",
    "research_core/annual_completion_report.py",
    "scripts/complete_annual_rotation.py",
    "scripts/package_annual_completion.py",
    "scripts/build_annual_completion_report.py",
]


@pytest.mark.parametrize(
    "source",
    [
        "research_core/annual_rotation.py",
        "research_core/annual_statistics.py",
        "research_core/annual_ranking_pool.py",
        "research_core/annual_publication.py",
        "tasks/20261013-annual-winner-rotation/run_study.py",
        "tasks/20261013-annual-winner-rotation/finalize_delivery.py",
    ],
)
def test_annual_sources_select_exact_annual_consumers(source: str) -> None:
    plan = ci_scope.make_plan([("M", source)])

    assert not plan["full"]
    assert plan["domains"] == ["annual"]
    assert ANNUAL_TESTS == set(plan["python_tests"])


@pytest.mark.parametrize("source", ANNUAL_COMPLETION_SOURCES)
@pytest.mark.parametrize("status", ["A", "M"])
def test_annual_completion_sources_include_economics_and_publication_consumers(source: str, status: str) -> None:
    plan = ci_scope.make_plan([(status, source)])

    assert not plan["full"]
    assert not plan["frontend"]
    assert plan["domains"] == ["annual"]
    assert set(plan["python_tests"]) == ANNUAL_TESTS


@pytest.mark.parametrize("status", ["A", "M"])
def test_shared_json_integrity_preserves_full_fallback(status: str) -> None:
    manifest = ci_scope.load_manifest()
    plan = ci_scope.make_plan([(status, "research_core/json_integrity.py")])

    assert plan["full"]
    assert plan["frontend"]
    assert plan["python_tests"] == ci_scope.test_inventory(ci_scope.ROOT, manifest)
    assert "scripts/tests/test_json_integrity.py" in plan["python_tests"]


@pytest.mark.parametrize(
    ("source", "expected_domains"),
    [
        ("research_core/research_data_builder.py", {"research_data", "annual", "pattern_scan"}),
        ("research_core/research_data_catalog.py", {"research_data", "annual", "pattern_scan"}),
        ("research_core/research_data_paths.py", {"research_data", "annual", "pattern_scan"}),
        ("research_core/research_measurement_v1.py", {"feature_blocks", "research_data", "annual", "pattern_scan"}),
        ("research_core/feature_identity_v1.py", {"feature_blocks", "research_data", "annual", "pattern_scan"}),
    ],
)
def test_annual_upstream_dependency_closure_selects_annual_consumers(source: str, expected_domains: set[str]) -> None:
    plan = ci_scope.make_plan([("M", source)])

    assert not plan["full"]
    assert set(plan["domains"]) == expected_domains | {"strength_flags"}
    assert ANNUAL_TESTS <= set(plan["python_tests"])
    assert "scripts/tests/test_pattern_scan_shared_v1.py" in plan["python_tests"]


@pytest.mark.parametrize("status", ["A", "M"])
@pytest.mark.parametrize(
    ("source", "expected_domains", "required_tests"),
    [
        (
            "scripts/pattern_scan.py",
            {"pattern_scan"},
            {"scripts/tests/test_pattern_scan_run_v1.py", "scripts/tests/test_pattern_scan_shared_v1.py"},
        ),
        (
            "research_core/pattern_scan_report_v1.py",
            {"pattern_scan"},
            {"scripts/tests/test_pattern_scan_report_v1.py"},
        ),
        (
            "scripts/export_pattern_scan_report.py",
            {"pattern_scan"},
            {"scripts/tests/test_pattern_scan_report_v1.py"},
        ),
        (
            "scripts/audit_pattern_scan_local_candidates.py",
            {"pattern_scan"},
            {"scripts/tests/test_pattern_scan_local_candidate_audit_v5.py"},
        ),
        (
            "research_core/research_data_file_bundle_v1.py",
            {"research_data", "annual", "pattern_scan"},
            {
                "scripts/tests/test_research_data_file_bundle_v1.py",
                "scripts/tests/test_annual_publication.py",
                "scripts/tests/test_pattern_scan_shared_v1.py",
            },
        ),
    ],
)
def test_known_pattern_scan_entry_and_shared_bundle_route_consumers(status: str, source: str, expected_domains: set[str], required_tests: set[str]) -> None:
    plan = ci_scope.make_plan([(status, source)])

    assert not plan["full"]
    assert not plan["frontend"]
    assert set(plan["domains"]) == expected_domains | {"strength_flags"}
    assert required_tests <= set(plan["python_tests"])
    assert "scripts/tests/test_research_ledger.py" not in plan["python_tests"]


def test_price_basis_keeps_global_full_fallback_and_includes_annual_tests() -> None:
    manifest = ci_scope.load_manifest()
    plan = ci_scope.make_plan([("M", "research_core/price_basis.py")])

    assert "research_core/price*" in manifest["full_paths"]
    assert plan["full"]
    assert plan["python_tests"] == ci_scope.test_inventory(ci_scope.ROOT, manifest)
    assert ANNUAL_TESTS <= set(plan["python_tests"])


def test_unknown_annual_source_keeps_full_fallback() -> None:
    plan = ci_scope.make_plan([("A", "research_core/annual_future_helper.py")])

    assert plan["full"]
    assert plan["python_tests"] == ci_scope.test_inventory(ci_scope.ROOT, ci_scope.load_manifest())


def test_unreviewed_future_test_keeps_full_inventory_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = ci_scope.load_manifest()
    manifest["test_roots"] = ["scripts/tests"]
    manifest["reviewed_tests"] = ["scripts/tests/test_annual_fixture.py"]
    monkeypatch.setattr(ci_scope, "load_manifest", lambda: manifest)
    root_test = tmp_path / "scripts/tests/test_annual_fixture.py"
    root_test.parent.mkdir(parents=True)
    root_test.write_text("def test_fixture(): pass\n", encoding="utf-8")
    future_test = root_test.parent / "test_annual_future.py"
    future_test.write_text("def test_future(): pass\n", encoding="utf-8")

    plan = ci_scope.make_plan([("M", "research_core/annual_rotation.py")], root=tmp_path)

    assert plan["full"]
    assert plan["python_tests"] == ["scripts/tests/test_annual_fixture.py", "scripts/tests/test_annual_future.py"]
    assert any("inventory differs" in reason for reason in plan["reasons"])


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


MARKET_TEST = "scripts/tests/test_research_execution_prices.py"


@pytest.mark.parametrize(
    ("path", "domain", "required"),
    [
        ("tasks/20991231-new-study/mission.md", "task_records", "scripts/tests/test_file_hygiene.py"),
        ("tasks/20991231-new-study/run_study.py", "task_records", "scripts/tests/test_research_evidence.py"),
        ("tasks/20991231-new-study/presentation.json", "task_records", "scripts/tests/test_study_presentation.py"),
        ("docs/en/new-guide.md", "prose", "scripts/tests/test_agent_instruction_contract.py"),
        ("docs/en/new-registry.json", "prose", "scripts/tests/test_file_hygiene.py"),
    ],
)
def test_unreferenced_new_record_selects_record_contracts_without_full_suite(path: str, domain: str, required: str) -> None:
    plan = ci_scope.make_plan([("A", path)])
    assert not plan["full"]
    assert domain in plan["domains"]
    assert required in plan["python_tests"]
    assert MARKET_TEST not in plan["python_tests"]


@pytest.mark.parametrize(
    ("status", "path"),
    [
        ("A", "tasks/20991231-new-study/web-report/index.html"),
        ("M", "tasks/20261013-pattern-scan/web-report/report.js"),
        ("D", "tasks/20261013-pattern-scan/web-report/report.js"),
    ],
)
def test_task_web_report_adds_frontend_without_full_suite(status: str, path: str) -> None:
    plan = ci_scope.make_plan([(status, path)])
    assert not plan["full"] and plan["frontend"]
    assert any("web-report frontend validation" in reason for reason in plan["reasons"])


def test_task_web_report_rename_checks_both_paths() -> None:
    changes = [
        ("R", "tasks/20261013-pattern-scan/web-report/report-old.js"),
        ("R", "tasks/20261013-pattern-scan/web-report/report.js"),
    ]
    plan = ci_scope.make_plan(changes)
    assert not plan["full"] and plan["frontend"]
    assert sum("web-report frontend validation" in reason for reason in plan["reasons"]) == 2


def test_new_file_in_owned_area_routes_like_a_modified_file() -> None:
    for path, domain in (
        ("research_core/hhhl_new_helper.py", "hhhl"),
        (".claude/skills/new/SKILL.md", "hooks"),
        ("tasks/20261013-pattern-scan/new-note.md", "pattern_scan"),
    ):
        plan = ci_scope.make_plan([("A", path)])
        assert not plan["full"], path
        assert domain in plan["domains"], path


@pytest.mark.parametrize("path", ["research_core/new_module.py", "research_core/new_notes.md", "unknown/new.py"])
def test_unowned_new_code_keeps_full_fallback(path: str) -> None:
    assert ci_scope.make_plan([("A", path)])["full"]


@pytest.mark.parametrize(
    ("changed", "importer"),
    [
        ("scripts/tests/test_research_causal_scenarios.py", "scripts/tests/test_research_chronology.py"),
        ("scripts/tests/test_research_cohort_lifecycle.py", "scripts/tests/test_research_chronology.py"),
        ("scripts/tests/test_close_review_execution.py", "scripts/tests/test_h05_allocation.py"),
    ],
)
def test_changed_test_also_selects_tests_that_import_it(changed: str, importer: str) -> None:
    plan = ci_scope.make_plan([("M", changed)])
    assert not plan["full"]
    assert {changed, importer} <= set(plan["python_tests"])


def test_changed_test_selects_the_transitive_importer_closure() -> None:
    plan = ci_scope.make_plan([("M", "scripts/tests/test_research_cohort_lifecycle.py")])
    assert not plan["full"]
    chain = [
        "scripts/tests/test_research_cohort_lifecycle.py",
        "scripts/tests/test_research_chronology.py",
        "scripts/tests/test_research_attempt_stress.py",
        "scripts/tests/test_research_capital_return_consumers.py",
    ]
    assert set(chain) <= set(plan["python_tests"])


def test_importer_closure_follows_chains_and_terminates_on_cycles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = {
        "test_a.py": "def test_a(): pass\n",
        "test_b.py": "from scripts.tests.test_a import test_a  # noqa: F401\nfrom scripts.tests import test_d  # noqa: F401\n",
        "test_c.py": "from scripts.tests.test_b import test_a  # noqa: F401\n",
        "test_d.py": "from scripts.tests import test_b  # noqa: F401\n",
        "test_e.py": "def test_e(): pass\n",
    }
    manifest = ci_scope.load_manifest()
    manifest["test_roots"] = ["scripts/tests"]
    manifest["reviewed_tests"] = [f"scripts/tests/{name}" for name in sources]
    manifest["domains"] = {"t": {"paths": [], "tests": ["scripts/tests/test_a.py"]}}
    monkeypatch.setattr(ci_scope, "load_manifest", lambda: manifest)
    for name, text in sources.items():
        (tmp_path / "scripts/tests" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "scripts/tests" / name).write_text(text, encoding="utf-8")
    plan = ci_scope.make_plan([("M", "scripts/tests/test_a.py")], root=tmp_path)
    assert not plan["full"]
    assert plan["python_tests"] == ["scripts/tests/test_a.py", "scripts/tests/test_b.py", "scripts/tests/test_c.py", "scripts/tests/test_d.py"]


def test_unmapped_test_file_runs_itself_without_full_suite() -> None:
    plan = ci_scope.make_plan([("M", "tests/test_generate_nightly_report.py")])
    assert not plan["full"]
    assert "tests/test_generate_nightly_report.py" in plan["python_tests"]
    assert MARKET_TEST not in plan["python_tests"]


@pytest.mark.parametrize(
    ("path", "required", "frontend"),
    [
        ("stock-data-downloader", "scripts/tests/test_ci_scope.py", False),
        (".gitmodules", "tests/test_producer_data_root.py", False),
        ("research_web/package-lock.json", "scripts/tests/test_opportunity_node_runtime.py", True),
        ("research_web/package.json", "scripts/tests/test_start_research_web.py", True),
        (".gitignore", "scripts/tests/test_audit_public_readiness.py", False),
    ],
)
def test_links_and_tool_manifests_select_their_readers(path: str, required: str, frontend: bool) -> None:
    plan = ci_scope.make_plan([("M", path)])
    assert not plan["full"]
    assert required in plan["python_tests"]
    assert plan["frontend"] is frontend
    assert MARKET_TEST not in plan["python_tests"]


def _record_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader: str) -> None:
    manifest = ci_scope.load_manifest()
    manifest["test_roots"] = ["scripts/tests"]
    manifest["reviewed_tests"] = ["scripts/tests/test_old_study.py", "scripts/tests/test_x.py"]
    manifest["domains"] = {
        "task_records": {"paths": [], "tests": []},
        "prose": {"paths": ["docs/*.md"], "tests": []},
        "x": {"paths": ["research_core/x_*"], "tests": ["scripts/tests/test_x.py"]},
    }
    monkeypatch.setattr(ci_scope, "load_manifest", lambda: manifest)
    for name, text in (
        ("scripts/tests/test_old_study.py", 'TASK = "tasks/20200101-old-study"\n'),
        ("scripts/tests/test_x.py", "def test_x(): pass\n"),
        ("tasks/20200101-old-study/run.py", 'SELF = "20200101-old-study"\n'),
        (reader, 'SOURCE = "tasks/20200101-old-study/data.json"\n'),
    ):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")


def test_record_read_by_tests_and_owned_code_selects_those_readers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _record_fixture(tmp_path, monkeypatch, "research_core/x_reader.py")
    plan = ci_scope.make_plan([("M", "tasks/20200101-old-study/mission.md")], root=tmp_path)
    assert not plan["full"]
    assert {"task_records", "x"} <= set(plan["domains"])
    assert plan["python_tests"] == ["scripts/tests/test_old_study.py", "scripts/tests/test_x.py"]


def test_record_read_by_unmapped_code_keeps_full_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _record_fixture(tmp_path, monkeypatch, "scripts/unmapped_reader.py")
    plan = ci_scope.make_plan([("M", "tasks/20200101-old-study/mission.md")], root=tmp_path)
    assert plan["full"]
    assert any("referenced by unmapped code" in reason for reason in plan["reasons"])


def test_dashboard_identity_selects_api_and_launcher_consumers() -> None:
    plan = ci_scope.make_plan([("A", "research_core/dashboard_identity.py")])
    assert not plan["full"]
    assert "opportunity" in plan["domains"]
    assert plan["frontend"]
    assert {
        "scripts/tests/test_dashboard_identity.py",
        "scripts/tests/test_start_research_web.py",
        "tests/test_research_api.py",
    } <= set(plan["python_tests"])
    app = ci_scope.make_plan([("M", "research_api/main.py")])
    assert not app["full"] and app["frontend"]
    assert {
        "tests/test_research_api.py",
        "tests/test_research_api_security.py",
        "scripts/tests/test_private_artifacts.py",
        "scripts/tests/test_windows_viewer_launcher.py",
    } <= set(app["python_tests"])
    assert "scripts/tests/test_research_execution_prices.py" not in app["python_tests"]
    assert ci_scope.make_plan([("M", "research_api/__init__.py")])["full"]


def test_new_path_and_union_fail_safe() -> None:
    assert ci_scope.make_plan([("M", "research_web/src/app/App.tsx"), ("A", "unknown/new.py")])["full"]
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


@pytest.mark.parametrize("exit_code", [0, 7])
def test_executor_passes_actual_selected_paths_and_failure(monkeypatch: pytest.MonkeyPatch, exit_code: int) -> None:
    plan = ci_scope.make_plan([("M", "research_core/hhhl_transition.py")])
    observed: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed.append(command)
        assert kwargs["cwd"] == ci_scope.ROOT
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(command, exit_code)

    monkeypatch.setattr(ci_scope.subprocess, "run", fake_run)
    assert ci_scope.execute_plan(plan) == exit_code
    assert observed == [ci_scope.pytest_command(plan["python_tests"])]
    assert observed[0][-len(plan["python_tests"]) :] == plan["python_tests"]
    assert "scripts/tests/test_research_ledger.py" not in observed[0]


def test_large_plans_use_bounded_workers_and_small_plans_stay_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    many = [f"scripts/tests/test_{index}.py" for index in range(ci_scope.PARALLEL_MIN_FILES)]
    monkeypatch.setattr(ci_scope.os, "cpu_count", lambda: 16)
    assert ci_scope.pytest_command(many)[:6] == [sys.executable, "-m", "pytest", "--durations=20", "-n", "4"]
    assert "-n" not in ci_scope.pytest_command(many[:-1])
    monkeypatch.setattr(ci_scope.os, "cpu_count", lambda: 1)
    assert "-n" not in ci_scope.pytest_command(many)


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


PRODUCER_ROOT = "stock-data-downloader"
CODE_LOADERS = {"spec_from_file_location", "run_path", "import_module", "insert", "append"}


def runs_producer_code(source: str) -> bool:
    """A test that loads code from the producer submodule, not just its data.

    Parsed rather than text-matched, so a test that only mentions the producer in a string or
    docstring (including this detector's own fixtures) is not flagged. A value is tainted when it
    is the producer root constant or is built from a tainted name; a load is a call to an import
    or sys.path mutator that receives a tainted value.
    """
    tree = ast.parse(source)

    def tainted(node: ast.AST, names: set[str]) -> bool:
        return any(
            (isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value.replace("\\", "/").split("/")[0] == PRODUCER_ROOT)
            or (isinstance(sub, ast.Name) and sub.id in names)
            for sub in ast.walk(node)
        )

    names: set[str] = set()
    changed = True
    while changed:  # propagate through chains such as ROOT = REPO / "..." ; SCRIPT = ROOT / "scripts"
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and tainted(node.value, names):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id not in names:
                        names.add(target.id)
                        changed = True
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            if called in CODE_LOADERS and any(tainted(arg, names) for arg in node.args):
                return True
    return False


def test_producer_code_detector_flags_the_old_import_style() -> None:
    old = (
        "import importlib.util, sys\n"
        'ROOT = REPO / "stock-data-downloader"\n'
        "sys.path.insert(0, str(ROOT))\n"
        'SPEC = importlib.util.spec_from_file_location("x", ROOT / "scripts" / "b.py")\n'
    )
    assert runs_producer_code(old)
    assert runs_producer_code('import runpy\nrunpy.run_path("stock-data-downloader/scripts/b.py")\n')  # one whole-path literal
    assert not runs_producer_code('"""stock-data-downloader produces price_daily.parquet; stock-research only consumes it."""\n')


def test_producer_code_detector_does_not_flag_its_own_test_file() -> None:
    """Regression: the detector's fixtures mention the producer only inside strings."""
    assert not runs_producer_code(Path(__file__).read_text(encoding="utf-8"))


def test_ci_needs_no_producer_submodule_because_tests_never_run_producer_code() -> None:
    """stock-research consumes the producer's data, not its code: no checkout of the submodule in CI."""
    workflow = yaml.load((ci_scope.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    checkout = next(step for step in workflow["jobs"]["repository-checks"]["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert "submodules" not in checkout.get("with", {})
    offenders = [
        test
        for test in ci_scope.test_inventory(ci_scope.ROOT, ci_scope.load_manifest())
        if runs_producer_code((ci_scope.ROOT / test).read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_workflow_retains_stable_check_and_explicit_full_entry() -> None:
    workflow = yaml.load((ci_scope.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert "push" not in workflow["on"]
    assert "schedule" not in workflow["on"]
    assert "workflow_dispatch" in workflow["on"]
    assert "edited" in workflow["on"]["pull_request"]["types"]
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


def test_hook_environments_are_saved_after_preparation_before_downstream_checks() -> None:
    workflow = yaml.load((ci_scope.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    job = workflow["jobs"]["repository-checks"]
    steps = job["steps"]
    indices = {step["name"]: i for i, step in enumerate(steps) if "name" in step}
    restore = steps[indices["Restore hook environments"]]
    prepare = steps[indices["Prepare hook environments"]]
    save = steps[indices["Save hook environments"]]
    assert restore["id"] == "hook-cache"
    assert prepare["id"] == "hook-environments"
    assert restore["uses"].startswith("actions/cache/restore@")
    assert save["uses"].startswith("actions/cache/save@")
    assert restore["uses"].split("@")[1] == save["uses"].split("@")[1]
    assert restore["with"]["path"] == save["with"]["path"] == "${{ env.PRE_COMMIT_HOME }}"
    assert job["env"]["PRE_COMMIT_HOME"] == "${{ github.workspace }}/.cache/pre-commit"
    assert restore["with"]["key"] == (
        "pre-commit-${{ runner.os }}-${{ runner.arch }}-${{ steps.hook-python.outputs.identity }}-${{ hashFiles('.pre-commit-config.yaml', 'uv.lock') }}"
    )
    assert save["with"]["key"] == "${{ steps.hook-cache.outputs.cache-primary-key }}"
    assert prepare["if"] == "steps.hook-cache.outputs.cache-hit != 'true'"
    assert save["if"] == "steps.hook-cache.outputs.cache-hit != 'true' && steps.hook-environments.outcome == 'success'"
    assert (
        indices["Restore hook environments"]
        < indices["Prepare hook environments"]
        < indices["Save hook environments"]
        < indices["Repository checks"]
        < indices["Draft selector and CI contracts"]
        < indices["Selected Python tests"]
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows CI native command dispatch")
@pytest.mark.parametrize("exit_code", [0, 7])
def test_hook_environment_preparation_native_dispatch(tmp_path: Path, exit_code: int) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None
    workflow = yaml.load((ci_scope.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    step = next(step for step in workflow["jobs"]["repository-checks"]["steps"] if step.get("name") == "Prepare hook environments")
    (tmp_path / "uv.cmd").write_text('@echo off\n> "%CI_ARGS_FILE%" echo %*\nexit /b %CI_EXIT_CODE%\n', encoding="ascii")
    args_file = tmp_path / "arguments.txt"
    environment = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ.get("PATH", ""),
        "CI_ARGS_FILE": str(args_file),
        "CI_EXIT_CODE": str(exit_code),
    }
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", step["run"]], cwd=tmp_path, env=environment, capture_output=True, timeout=30)
    assert result.returncode == exit_code, result.stderr
    assert args_file.read_text(encoding="ascii").strip() == "run --no-sync pre-commit install-hooks"


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
    assert "--durations=20" in targeted["run"]


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


@pytest.mark.parametrize("change", [("A", "scripts/tests/test_hhhl_variants_checkout_identity.py"), ("M", ".gitattributes")])
def test_checkout_identity_consumer_is_selected_for_test_and_eol_policy(change: tuple[str, str]) -> None:
    plan = ci_scope.make_plan([change])
    assert not plan["full"]
    assert "scripts/tests/test_hhhl_variants_checkout_identity.py" in plan["python_tests"]
