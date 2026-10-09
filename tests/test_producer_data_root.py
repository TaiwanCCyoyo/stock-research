from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from research_core.producer_data import REPO_ROOT, producer_data_root
from StockProject import backtest_cli


def test_unconfigured_root_preserves_submodule_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STOCK_PRODUCER_DATA_ROOT", raising=False)
    assert producer_data_root() == REPO_ROOT / "stock-data-downloader" / "data"


def test_explicit_external_root_is_shared_by_query_and_metadata(tmp_path: Path) -> None:
    root = tmp_path / "external producer with spaces"
    root.mkdir()
    environment = {**os.environ, "STOCK_PRODUCER_DATA_ROOT": str(root)}
    program = (
        "import json; from scripts.stock_research_query import DEFAULT_DATA_PATH; "
        "from StockProject.universe import DEFAULT_SYMBOL_META_DB; "
        "print(json.dumps([str(DEFAULT_DATA_PATH), str(DEFAULT_SYMBOL_META_DB)]))"
    )
    result = subprocess.run([sys.executable, "-c", program], cwd=REPO_ROOT, env=environment, capture_output=True, text=True, check=True)
    assert [Path(value) for value in json.loads(result.stdout)] == [root.resolve(), root.resolve() / "symbol_meta.sqlite"]


@pytest.mark.parametrize("configured", ["", " ", "relative/data"])
def test_nonabsolute_configuration_is_rejected(monkeypatch: pytest.MonkeyPatch, configured: str) -> None:
    monkeypatch.setenv("STOCK_PRODUCER_DATA_ROOT", configured)
    with pytest.raises(ValueError, match="absolute directory"):
        producer_data_root()


def test_missing_configured_root_never_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STOCK_PRODUCER_DATA_ROOT", str(tmp_path / "missing"))
    with pytest.raises(FileNotFoundError, match="no automatic fallback"):
        producer_data_root()


@pytest.mark.parametrize("selector", ["--codes", "--universes"])
@pytest.mark.parametrize("via_environment", [False, True])
def test_cli_routes_price_and_metadata_to_same_explicit_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, selector: str, via_environment: bool) -> None:
    root = tmp_path / "canonical data with spaces"
    root.mkdir()
    argv = ["backtest_cli", "--strategy", "unused.py", selector, "@semis" if selector == "--codes" else "semis"]
    if via_environment:
        monkeypatch.setenv("STOCK_PRODUCER_DATA_ROOT", str(root))
    else:
        monkeypatch.delenv("STOCK_PRODUCER_DATA_ROOT", raising=False)
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
    monkeypatch.setattr(backtest_cli, "run_backtest_pass", stop)
    with pytest.raises(StopBeforeResearch):
        backtest_cli.main()
    assert observed == {"price_root": root.resolve(), "metadata": root.resolve() / "symbol_meta.sqlite"}


def test_cli_unconfigured_routes_price_and_metadata_to_submodule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STOCK_PRODUCER_DATA_ROOT", raising=False)
    monkeypatch.setattr(sys, "argv", ["backtest_cli", "--strategy", "unused.py", "--codes", "synthetic"])
    observed: list[dict[str, Any]] = []

    def resolve(value: str, **kwargs: Any) -> tuple[list[str], str | None]:
        assert kwargs == {"symbol_meta_db": REPO_ROOT / "stock-data-downloader" / "data" / "symbol_meta.sqlite"}
        return [value], None

    def loader(**kwargs: Any) -> None:
        observed.append(kwargs)
        raise RuntimeError("stop before loading")

    monkeypatch.setattr(backtest_cli, "resolve_codes", resolve)
    monkeypatch.setattr(backtest_cli, "DataLoader", loader)
    with pytest.raises(RuntimeError, match="stop before loading"):
        backtest_cli.main()
    assert observed == [{"data_path": str(REPO_ROOT / "stock-data-downloader" / "data")}]


@pytest.mark.parametrize("configured", [False, True])
def test_consumers_resolve_one_producer_root(tmp_path: Path, configured: bool) -> None:
    root = tmp_path / "canonical producer with spaces"
    root.mkdir()
    environment = dict(os.environ)
    environment.pop("STOCK_PRODUCER_DATA_ROOT", None)
    if configured:
        environment["STOCK_PRODUCER_DATA_ROOT"] = str(root)
    expected = root.resolve() if configured else REPO_ROOT / "stock-data-downloader" / "data"
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
    assert [Path(value) for value in json.loads(result.stdout)] == [expected] * 6


def test_nightly_direct_script_can_resolve_producer_root() -> None:
    environment = dict(os.environ)
    environment.pop("STOCK_PRODUCER_DATA_ROOT", None)
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
@pytest.mark.parametrize("configured", [False, True])
def test_retained_generators_resolve_inputs_without_running_research(tmp_path: Path, script: str, configured: bool) -> None:
    root = tmp_path / "frozen producer input with spaces"
    root.mkdir()
    environment = dict(os.environ)
    environment.pop("STOCK_PRODUCER_DATA_ROOT", None)
    if configured:
        environment["STOCK_PRODUCER_DATA_ROOT"] = str(root)
    expected = root.resolve() if configured else REPO_ROOT / "stock-data-downloader" / "data"
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
    assert roots and all(value == expected for value in roots)


def test_retained_legacy_checkout_is_not_accidentally_stageable(tmp_path: Path) -> None:
    repo = tmp_path / "migration checkout"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    (repo / ".gitignore").write_bytes((REPO_ROOT / ".gitignore").read_bytes())
    legacy = repo / "shioaji_stock_prices"
    legacy.mkdir()
    subprocess.run(["git", "init", str(legacy)], capture_output=True, check=True)
    (legacy / "data").mkdir()
    (legacy / "data" / "official_daily.sqlite").write_bytes(b"synthetic private input")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True, check=True)
    result = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True)
    assert result.stdout.split(b"\0") == [b".gitignore", b""]
