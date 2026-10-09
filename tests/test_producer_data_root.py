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
    assert producer_data_root() == REPO_ROOT / "shioaji_stock_prices" / "data"


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


def test_cli_unconfigured_preserves_legacy_loader_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STOCK_PRODUCER_DATA_ROOT", raising=False)
    monkeypatch.setattr(sys, "argv", ["backtest_cli", "--strategy", "unused.py", "--codes", "synthetic"])
    observed: list[dict[str, Any]] = []

    def resolve(value: str, **kwargs: Any) -> tuple[list[str], str | None]:
        assert kwargs == {}
        return [value], None

    def loader(**kwargs: Any) -> None:
        observed.append(kwargs)
        raise RuntimeError("stop before loading")

    monkeypatch.setattr(backtest_cli, "resolve_codes", resolve)
    monkeypatch.setattr(backtest_cli, "DataLoader", loader)
    with pytest.raises(RuntimeError, match="stop before loading"):
        backtest_cli.main()
    assert observed == [{}]
