from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from research_core import live_producer
from research_core.producer_data import ENV_KEY, REPO_ROOT, SENTINEL, ProducerRootError, primary_checkout, producer_data_root
from StockProject import backtest_cli


def _producer_root(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / SENTINEL).write_bytes(b"")
    return path


def _git(*args: str, cwd: Path) -> None:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args], cwd=cwd, env=environment, check=True, capture_output=True)


@pytest.fixture()
def checkouts(tmp_path: Path) -> tuple[Path, Path]:
    """A primary checkout with one linked worktree, both paths containing spaces."""
    primary = tmp_path / "primary checkout"
    primary.mkdir()
    _git("init", "-q", "-b", "main", cwd=primary)
    (primary / "README.md").write_text("x\n", encoding="utf-8")
    _git("add", "README.md", cwd=primary)
    _git("commit", "-q", "-m", "init", cwd=primary)
    worktree = tmp_path / "linked worktree"
    _git("worktree", "add", "-q", "-b", "task", str(worktree), cwd=primary)
    return primary, worktree


def test_a_linked_worktree_resolves_through_the_primary_env_file(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = checkouts
    live = _producer_root(tmp_path / "Stock Data" / "producer")
    (primary / ".env.local").write_text(f"﻿OTHER=1\n{ENV_KEY}={live}\nSECRET=never-loaded\n", encoding="utf-8")

    assert primary_checkout(worktree.resolve()) == primary.resolve()
    assert producer_data_root(environ={}, repo_root=worktree) == live.resolve()
    assert producer_data_root(environ={}, repo_root=primary) == live.resolve()
    assert "SECRET" not in os.environ


def test_the_environment_wins_over_the_primary_env_file(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = checkouts
    (primary / ".env.local").write_text(f"{ENV_KEY}={_producer_root(tmp_path / 'file')}\n", encoding="utf-8")
    chosen = _producer_root(tmp_path / "env")

    assert producer_data_root(environ={ENV_KEY: str(chosen)}, repo_root=worktree) == chosen.resolve()


def test_missing_everywhere_fails_and_names_both_sources(checkouts: tuple[Path, Path]) -> None:
    primary, worktree = checkouts

    with pytest.raises(ProducerRootError, match="process environment") as error:
        producer_data_root(environ={}, repo_root=worktree)
    assert str(primary.resolve() / ".env.local") in str(error.value)


def test_outside_any_repository_fails_without_fallback(tmp_path: Path) -> None:
    bare = tmp_path / "not a checkout"
    _producer_root(bare / "stock-data-downloader" / "data")

    with pytest.raises(ProducerRootError, match="no primary checkout"):
        producer_data_root(environ={}, repo_root=bare)


def test_a_code_only_directory_fails_the_sentinel_check(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    """The post-move submodule data/ keeps only the tracked category table."""
    primary, worktree = checkouts
    code_only = tmp_path / "code only"
    code_only.mkdir()
    (code_only / "stock_category.json5").write_text("{}\n", encoding="utf-8")
    (primary / ".env.local").write_text(f"{ENV_KEY}={code_only}\n", encoding="utf-8")

    with pytest.raises(ProducerRootError, match=f"no {SENTINEL}"):
        producer_data_root(environ={}, repo_root=worktree)
    with pytest.raises(ProducerRootError, match=f"no {SENTINEL}"):
        producer_data_root(environ={ENV_KEY: str(code_only)}, repo_root=worktree)


@pytest.mark.parametrize("line", [ENV_KEY, f"{ENV_KEY}=", f"{ENV_KEY}=relative/data", f"{ENV_KEY}=\\rootless"])
def test_a_broken_env_file_entry_fails(checkouts: tuple[Path, Path], line: str) -> None:
    primary, worktree = checkouts
    (primary / ".env.local").write_text(f"{line}\n", encoding="utf-8")

    with pytest.raises(ProducerRootError):
        producer_data_root(environ={}, repo_root=worktree)


def test_a_duplicated_env_file_key_fails(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = checkouts
    root = _producer_root(tmp_path / "root")
    (primary / ".env.local").write_text(f"{ENV_KEY}={root}\n{ENV_KEY}={root}\n", encoding="utf-8")

    with pytest.raises(ProducerRootError, match="2 times"):
        producer_data_root(environ={}, repo_root=worktree)


@pytest.mark.skipif(os.name != "nt", reason="Windows path forms")
def test_windows_path_forms(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = checkouts
    root = _producer_root(tmp_path / "windows root")
    forward = root.as_posix()
    (primary / ".env.local").write_text(f'{ENV_KEY}="{forward}"\r\n', encoding="utf-8")

    assert producer_data_root(environ={}, repo_root=worktree) == root.resolve()
    for value in ("D:relative", "\\rootless"):
        with pytest.raises(ProducerRootError, match="absolute"):
            producer_data_root(environ={ENV_KEY: value}, repo_root=worktree)


def test_a_worktree_snapshot_is_never_silently_replaced_by_live_data(checkouts: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = checkouts
    (primary / ".env.local").write_text(f"{ENV_KEY}={_producer_root(tmp_path / 'live')}\n", encoding="utf-8")
    snapshot = _producer_root(worktree / "stock-data-downloader" / "data")

    with pytest.raises(ProducerRootError, match="never chosen automatically"):
        producer_data_root(environ={}, repo_root=worktree)
    assert producer_data_root(environ={ENV_KEY: str(snapshot)}, repo_root=worktree) == snapshot.resolve()


@pytest.mark.parametrize("configured", ["", " ", "relative/data"])
def test_nonabsolute_configuration_is_rejected(configured: str) -> None:
    with pytest.raises(ProducerRootError, match="absolute directory"):
        producer_data_root(environ={ENV_KEY: configured})


def test_missing_configured_root_never_falls_back(tmp_path: Path) -> None:
    with pytest.raises(ProducerRootError, match="no automatic fallback"):
        producer_data_root(environ={ENV_KEY: str(tmp_path / "missing")})


def test_explicit_external_root_is_shared_by_query_and_metadata(tmp_path: Path) -> None:
    root = _producer_root(tmp_path / "external producer with spaces")
    environment = {**os.environ, ENV_KEY: str(root)}
    program = (
        "import json; from scripts.stock_research_query import DEFAULT_DATA_PATH; "
        "from StockProject.universe import DEFAULT_SYMBOL_META_DB; "
        "print(json.dumps([str(DEFAULT_DATA_PATH), str(DEFAULT_SYMBOL_META_DB)]))"
    )
    result = subprocess.run([sys.executable, "-c", program], cwd=REPO_ROOT, env=environment, capture_output=True, text=True, check=True)
    assert [Path(value) for value in json.loads(result.stdout)] == [root.resolve(), root.resolve() / "symbol_meta.sqlite"]


@pytest.mark.parametrize("selector", ["--codes", "--universes"])
@pytest.mark.parametrize("via_environment", [False, True])
def test_cli_routes_price_and_metadata_to_same_explicit_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, selector: str, via_environment: bool) -> None:
    root = _producer_root(tmp_path / "canonical data with spaces")
    argv = ["backtest_cli", "--strategy", "unused.py", selector, "@semis" if selector == "--codes" else "semis"]
    if via_environment:
        monkeypatch.setenv(ENV_KEY, str(root))
    else:
        argv.extend(["--data-path", str(root)])
    monkeypatch.setattr(sys, "argv", argv)
    observed: dict[str, Any] = {}

    class StopBeforeResearch(Exception):
        pass

    class Loader:
        _price_df = object()

        def __init__(self, **kwargs: Any) -> None:
            observed["price_root"] = Path(kwargs["data_path"])

        def load_all(self) -> None:
            pass

    def resolve(value: str, **kwargs: Any) -> tuple[list[str], str | None]:
        observed["metadata"] = kwargs["symbol_meta_db"]
        assert value == "@semis"
        if selector == "--codes":
            return ["synthetic"], "semis"
        raise StopBeforeResearch

    def stop(*args: Any, **kwargs: Any) -> None:
        raise StopBeforeResearch

    monkeypatch.setattr(backtest_cli, "DataLoader", Loader)
    monkeypatch.setattr(backtest_cli, "resolve_codes", resolve)
    monkeypatch.setattr(backtest_cli, "load_strategy_class", lambda _: object)
    monkeypatch.setattr(backtest_cli, "fingerprint_inputs", lambda specs: {"inputs": {}})
    monkeypatch.setattr(backtest_cli, "run_backtest_pass", stop)
    with pytest.raises(StopBeforeResearch):
        backtest_cli.main()
    assert observed == {"price_root": root.resolve(), "metadata": root.resolve() / "symbol_meta.sqlite"}


def test_consumers_resolve_one_producer_root(tmp_path: Path) -> None:
    root = _producer_root(tmp_path / "canonical producer with spaces")
    environment = {**os.environ, ENV_KEY: str(root)}
    program = (
        "import json; from research_core.producer_data import producer_data_root; "
        "from scripts.stock_research_query import DEFAULT_DATA_PATH; "
        "from StockProject.universe import DEFAULT_SYMBOL_META_DB; "
        "from research_lab.dashboard_core import SYMBOL_META_DB; "
        "from research_lab.display import SYMBOL_MAPPING_PATH; "
        "from scripts.prepare_nightly_research import DEFAULT_DATA_PATH as nightly; "
        "print(json.dumps([str(p) for p in [producer_data_root(), DEFAULT_DATA_PATH, "
        "DEFAULT_SYMBOL_META_DB.parent, SYMBOL_META_DB.parent, SYMBOL_MAPPING_PATH.parent, nightly]]))"
    )
    result = subprocess.run([sys.executable, "-c", program], cwd=REPO_ROOT, env=environment, capture_output=True, text=True, check=True)
    assert [Path(value) for value in json.loads(result.stdout)] == [root.resolve()] * 6


def _without_usable_root(tmp_path: Path, mode: str) -> dict[str, str]:
    """A child environment where resolving the default must fail, independent of conftest.py.

    "missing" guarantees failure on any machine. "unset" removes the variable; in a
    checkout without a valid primary `.env.local` (CI) resolution fails too, and in
    either case these callers must not resolve anything before they need it.
    """
    environment = {key: value for key, value in os.environ.items() if key != ENV_KEY}
    if mode == "missing":
        environment[ENV_KEY] = str(tmp_path / "missing")
    return environment


@pytest.mark.parametrize("mode", ["missing", "unset"])
def test_cli_modules_resolve_the_default_only_when_used(tmp_path: Path, mode: str) -> None:
    """An explicit --data-path must work without a configured producer root."""
    environment = _without_usable_root(tmp_path, mode)
    program = "import StockProject.backtest_cli, StockProject.universe, scripts.stock_research_query, scripts.prepare_nightly_research"
    result = subprocess.run([sys.executable, "-c", program], cwd=REPO_ROOT, env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    help_run = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "prepare_nightly_research.py"), "--help"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_run.returncode == 0, help_run.stderr


def test_backtest_cli_explicit_data_path_never_consults_the_resolver(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV_KEY, str(tmp_path / "missing"))
    root = tmp_path / "explicit"
    root.mkdir()
    monkeypatch.setattr(sys, "argv", ["backtest_cli", "--strategy", "unused.py", "--codes", "@semis", "--data-path", str(root)])
    observed: dict[str, Any] = {}

    class StopBeforeResearch(Exception):
        pass

    def resolve(value: str, **kwargs: Any) -> tuple[list[str], str | None]:
        observed["metadata"] = kwargs["symbol_meta_db"]
        raise StopBeforeResearch

    monkeypatch.setattr(backtest_cli, "resolve_codes", resolve)
    monkeypatch.setattr(backtest_cli, "load_strategy_class", lambda _: object)
    # With no resolvable root the explicit data cannot be classified, so the live-read gate
    # applies (fail closed); pin its clock and task state so the test is time-independent.
    monkeypatch.setattr(live_producer, "producer_time", lambda now=None: datetime(2026, 10, 15, 1, 30, tzinfo=timezone(timedelta(hours=8))))
    monkeypatch.setattr(live_producer, "running_producer_tasks", lambda: [])
    with pytest.raises(StopBeforeResearch):
        backtest_cli.main()
    assert observed == {"metadata": root / "symbol_meta.sqlite"}


def test_an_unconfigured_default_fails_loudly_when_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No silent fallback on use: the error names the setting instead of returning no files."""
    from StockProject import universe

    monkeypatch.setenv(ENV_KEY, str(tmp_path / "missing"))
    with pytest.raises(ProducerRootError, match=ENV_KEY):
        universe.resolve_industry_rule("Semiconductor")


def test_nightly_direct_script_can_resolve_producer_root(tmp_path: Path) -> None:
    environment = {**os.environ, ENV_KEY: str(_producer_root(tmp_path / "root"))}
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "prepare_nightly_research.py"), "--help"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--data-path" in result.stdout


@pytest.mark.parametrize("script", ["build_rotation_universe.py", "features.py", "verify_eligibility.py"])
def test_retained_generators_resolve_inputs_without_running_research(tmp_path: Path, script: str) -> None:
    root = _producer_root(tmp_path / "frozen producer input with spaces")
    environment = {**os.environ, ENV_KEY: str(root)}
    program = (
        "import json,runpy,sys; m=runpy.run_path(sys.argv[1], run_name='migration_probe'); "
        "print(json.dumps([str(m[k].parent) for k in ('PRICE', 'META') if k in m]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program, str(REPO_ROOT / "tasks" / "20260823-rotation-universe" / script)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    roots = [Path(value) for value in json.loads(result.stdout)]
    assert roots and all(value == root.resolve() for value in roots)
