"""Seal and pinned-read behavior of sealed producer inputs on invented data only."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from research_core import producer_inputs
from research_core.artifact_store import file_digest
from research_core.feature_atlas_io import input_paths
from research_core.producer_inputs import FAMILY, PAYLOAD, open_producer_inputs, seal_producer_inputs, select_read_set
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_paths import DataRoots


@pytest.fixture
def roots(tmp_path: Path) -> DataRoots:
    primary = tmp_path / "primary checkout"
    (primary / ".git").mkdir(parents=True)
    return DataRoots(primary=primary, data=primary / "research_data")


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """Invented producer root, including files outside the research read set."""
    root = tmp_path / "producer data with spaces"
    root.mkdir()
    pd.DataFrame({"Code": ["2330", "2330"], "Date": pd.to_datetime(["2010-01-04", "2010-01-05"]), "Close": [64.9, 65.0]}).to_parquet(
        root / "price_daily.parquet"
    )
    (root / "2330_day.csv").write_text("Date,Close\n2010-01-04,64.9\n", encoding="utf-8")
    (root / "2330_min.csv").write_text("minute bars are excluded\n", encoding="utf-8")
    (root / "stock_symbol_mapping.json5").write_text('{"2330": "TSMC"}', encoding="utf-8")
    (root / "technical_features").mkdir()
    (root / "technical_features" / "2330.parquet").write_bytes(b"excluded")
    with closing(sqlite3.connect(root / "official_daily.sqlite")) as database:
        database.execute("CREATE TABLE excluded (x)")
    with closing(sqlite3.connect(root / "symbol_meta.sqlite")) as database:
        database.execute("CREATE TABLE symbol_meta (code TEXT PRIMARY KEY, name TEXT)")
        database.execute("INSERT INTO symbol_meta VALUES ('2330', 'TSMC')")
        database.commit()
    return root


def _member(roots: DataRoots, version: str, name: str) -> Path:
    return roots.primary / FAMILY / version / PAYLOAD / name


def test_seal_captures_read_set_and_wal_commits_without_sidecars(roots: DataRoots, source: Path) -> None:
    writer = sqlite3.connect(source / "corporate_actions.sqlite")
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE corporate_actions (code TEXT, ex_date TEXT)")
        writer.execute("INSERT INTO corporate_actions VALUES ('2330', '2010-06-01')")
        writer.commit()
        assert (source / "corporate_actions.sqlite-wal").stat().st_size > 0  # committed rows live only in the WAL
        result = seal_producer_inputs(source, roots, register=False)
    finally:
        writer.close()

    version = result["version_id"]
    sealed = open_producer_inputs(roots, version, result["manifest_sha256"])
    assert sorted(sealed.names()) == ["2330_day.csv", "corporate_actions.sqlite", "price_daily.parquet", "stock_symbol_mapping.json5", "symbol_meta.sqlite"]
    assert result["raw_input_period"] == {"start": "2010-01-04", "end": "2010-01-05", "reason": None}
    actions = sealed.path("corporate_actions.sqlite")
    with closing(sqlite3.connect(actions.as_uri() + "?mode=ro", uri=True)) as database:
        assert database.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert database.execute("SELECT code, ex_date FROM corporate_actions").fetchall() == [("2330", "2010-06-01")]
    assert sorted(path.name for path in actions.parent.iterdir() if "sqlite" in path.name) == ["corporate_actions.sqlite", "symbol_meta.sqlite"]
    assert all(not os.access(path, os.W_OK) for path in sealed.root.rglob("*") if path.is_file())
    sealed.verify_all()


def test_identical_content_reuses_one_version(roots: DataRoots, source: Path) -> None:
    first = seal_producer_inputs(source, roots, register=False)
    second = seal_producer_inputs(source, roots, register=False)
    assert second["version_id"] == first["version_id"] and second["reused_existing_version"] is True
    family = roots.primary / FAMILY
    assert sorted(path.name for path in family.iterdir()) == sorted([first["version_id"], "receipts"])
    assert len(list((family / "receipts" / first["version_id"]).iterdir())) == 2


def test_changed_source_gets_new_version_and_old_one_stays_readable(roots: DataRoots, source: Path) -> None:
    first = seal_producer_inputs(source, roots, register=False)
    (source / "2330_day.csv").write_text("Date,Close\n2010-01-04,64.9\n2010-01-05,65.0\n", encoding="utf-8")
    second = seal_producer_inputs(source, roots, register=False)
    assert second["version_id"] != first["version_id"]
    old = open_producer_inputs(roots, first["version_id"], first["manifest_sha256"])
    assert old.path("2330_day.csv").read_text(encoding="utf-8") == "Date,Close\n2010-01-04,64.9\n"


def test_pin_mismatch_and_missing_version_fail_without_live_fallback(roots: DataRoots, source: Path) -> None:
    version = seal_producer_inputs(source, roots, register=False)["version_id"]
    with pytest.raises(ValueError, match="pin mismatch"):
        open_producer_inputs(roots, version, "0" * 64)
    with pytest.raises(FileNotFoundError):
        open_producer_inputs(roots, "1" * 64, "1" * 64)
    with pytest.raises(ValueError, match="64-hex"):
        open_producer_inputs(roots, "latest", version)


def test_changed_or_extra_sealed_bytes_are_rejected(roots: DataRoots, source: Path) -> None:
    version = seal_producer_inputs(source, roots, register=False)["version_id"]
    member = _member(roots, version, "2330_day.csv")
    member.chmod(stat.S_IWRITE | stat.S_IREAD)
    member.write_text("Date,Close\n2010-01-04,99.9\n", encoding="utf-8")  # same size, different bytes
    with pytest.raises(ValueError, match="hash/size mismatch"):
        open_producer_inputs(roots, version, version).path("2330_day.csv")
    (member.parent / "2330_day.csv-shm").write_bytes(b"")
    with pytest.raises(ValueError, match="differ from manifest"):
        open_producer_inputs(roots, version, version)


def test_hardlinked_member_is_rejected(roots: DataRoots, source: Path, tmp_path: Path) -> None:
    version = seal_producer_inputs(source, roots, register=False)["version_id"]
    os.link(_member(roots, version, "2330_day.csv"), tmp_path / "alias.csv")
    with pytest.raises(ValueError, match="hardlinked"):
        open_producer_inputs(roots, version, version)


def test_seal_creates_no_link_and_reads_copy_nothing(roots: DataRoots, source: Path) -> None:
    version = seal_producer_inputs(source, roots, register=False)["version_id"]
    before = sorted(path for path in roots.primary.parent.rglob("*"))
    sealed = open_producer_inputs(roots, version, version)
    sealed.verify_all()
    assert sorted(path for path in roots.primary.parent.rglob("*")) == before
    for path in before:
        info = path.lstat()
        assert not stat.S_ISLNK(info.st_mode)
        assert not getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
        assert not stat.S_ISREG(info.st_mode) or info.st_nlink == 1


def test_registration_makes_the_version_discoverable_by_pin(roots: DataRoots, source: Path) -> None:
    result = seal_producer_inputs(source, roots)
    row = DataCatalog(roots).get("producer-inputs", result["version_id"], manifest_sha256=result["manifest_sha256"])
    assert row["kind"] == "prices" and row["manifest"]["scope"] == "primary"
    assert row["manifest"]["path"] == f"{FAMILY}/{result['version_id']}/manifest.json"


def test_failed_seal_publishes_nothing_and_removes_its_staging(roots: DataRoots, source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(path: Path) -> dict:
        raise RuntimeError("injected failure after capture")

    monkeypatch.setattr(producer_inputs, "_price_period", broken)
    with pytest.raises(RuntimeError, match="injected"):
        seal_producer_inputs(source, roots, register=False)
    assert list((roots.primary / FAMILY).iterdir()) == []


def test_source_changing_during_copy_fails(roots: DataRoots, source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = producer_inputs.copy_verified

    def racing(incoming: Path, outgoing: Path, expected: str) -> None:
        original(incoming, outgoing, expected)
        os.utime(incoming, ns=(incoming.stat().st_atime_ns, incoming.stat().st_mtime_ns + 1_000_000_000))

    monkeypatch.setattr(producer_inputs, "copy_verified", racing)
    with pytest.raises(ValueError, match="changed during seal"):
        seal_producer_inputs(source, roots, register=False)
    assert list((roots.primary / FAMILY).iterdir()) == []


def test_legacy_daily_inputs_are_optional_and_unfinished_ones_fail(source: Path) -> None:
    assert "adjusted_prices/daily/price_daily.parquet" not in select_read_set(source)
    legacy = source / "adjusted_prices" / "daily"
    legacy.mkdir(parents=True)
    (legacy / "price_daily.parquet").write_bytes((source / "price_daily.parquet").read_bytes())
    (legacy / "notes.txt").write_text("ignored", encoding="utf-8")
    assert "adjusted_prices/daily/price_daily.parquet" in select_read_set(source)
    assert "adjusted_prices/daily/notes.txt" not in select_read_set(source)
    (legacy / ".price_daily.parquet.seed-0.partial").write_bytes(b"")
    with pytest.raises(ValueError, match="unfinished"):
        select_read_set(source)


def test_pinned_root_layout_serves_existing_root_based_readers(roots: DataRoots, source: Path) -> None:
    """Readers joining `<root>/stock-data-downloader/data` read sealed bytes without code changes."""
    version = seal_producer_inputs(source, roots, register=False)["version_id"]
    sealed = open_producer_inputs(roots, version, version)
    paths = input_paths(sealed.root)
    assert paths["prices"] == sealed.data_root / "price_daily.parquet"
    assert file_digest(paths["prices"]) == file_digest(source / "price_daily.parquet")


def test_cli_seals_with_writer_gate_and_verifies_by_pin(
    roots: DataRoots, source: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import seal_producer_inputs as cli

    monkeypatch.setenv("STOCK_RESEARCH_DATA_ROOT", str(roots.data))
    monkeypatch.setattr(cli, "running_writers", lambda: ["StockProject-DailyUpdate"])
    with pytest.raises(RuntimeError, match="writers are running"):
        cli.main(["seal", "--source", str(source)])
    monkeypatch.setattr(cli, "running_writers", lambda: [])
    assert cli.main(["seal", "--source", str(source), "--allow-window"]) == 0
    sealed = json.loads(capsys.readouterr().out)
    assert sealed["registered"] is True
    assert cli.main(["verify", sealed["version_id"], "--manifest-sha256", sealed["manifest_sha256"]]) == 0
    assert Path(json.loads(capsys.readouterr().out)["data_root"]) == roots.primary / FAMILY / sealed["version_id"] / PAYLOAD


@pytest.mark.parametrize(
    ("moment", "refused"),
    [
        (datetime(2026, 10, 15, 18, 10), True),
        (datetime(2026, 10, 15, 17, 49), False),
        (datetime(2026, 10, 15, 19, 0), False),
        (datetime(2026, 10, 17, 18, 10), False),
    ],
)
def test_writer_window_refuses_weekday_evening(monkeypatch: pytest.MonkeyPatch, moment: datetime, refused: bool) -> None:
    from scripts import seal_producer_inputs as cli

    monkeypatch.setattr(cli, "running_writers", lambda: [])
    if refused:
        with pytest.raises(RuntimeError, match="write window"):
            cli.writer_gate(moment, allow_window=False)
        cli.writer_gate(moment, allow_window=True)
    else:
        cli.writer_gate(moment, allow_window=False)


def test_backtest_cli_reads_a_sealed_version_by_pin(roots: DataRoots, source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from StockProject import backtest_cli

    version = seal_producer_inputs(source, roots, register=False)["version_id"]
    monkeypatch.setenv("STOCK_RESEARCH_DATA_ROOT", str(roots.data))
    observed: dict[str, Path] = {}

    def resolve(value: str, **kwargs: Path) -> tuple[list[str], None]:
        observed["metadata"] = kwargs["symbol_meta_db"]
        return [value], None

    def loader(**kwargs: str) -> None:
        observed["prices"] = Path(kwargs["data_path"])
        raise RuntimeError("stop before loading")

    monkeypatch.setattr(backtest_cli, "resolve_codes", resolve)
    monkeypatch.setattr(backtest_cli, "DataLoader", loader)
    argv = ["backtest_cli", "--strategy", "unused.py", "--codes", "2330", "--producer-inputs", version]
    monkeypatch.setattr(sys, "argv", [*argv, "--producer-inputs-sha256", version])
    with pytest.raises(RuntimeError, match="stop before loading"):
        backtest_cli.main()
    data_root = roots.primary / FAMILY / version / PAYLOAD
    assert observed == {"prices": data_root, "metadata": data_root / "symbol_meta.sqlite"}
    monkeypatch.setattr(sys, "argv", [*argv, "--producer-inputs-sha256", "0" * 64])
    with pytest.raises(SystemExit):
        backtest_cli.main()


def test_sector_catalog_cli_requires_an_explicit_producer_source(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from scripts import build_sector_wave_catalog

    monkeypatch.setattr(sys, "argv", ["build_sector_wave_catalog", "--output-dir", "unused", "--run-id", "one"])
    with pytest.raises(SystemExit):
        build_sector_wave_catalog.main()


def test_backtest_summary_records_sealed_pin_and_path_outside_repo(roots: DataRoots, source: Path, tmp_path: Path) -> None:
    """A sealed root sits outside the worktree; the recorded path must still resolve for queries."""
    import argparse

    from scripts.stock_research_query import resolve_price_data_root
    from StockProject.backtest_cli import build_summary

    version = seal_producer_inputs(source, roots, register=False)["version_id"]
    sealed = open_producer_inputs(roots, version, version)
    pin = {"data_id": "producer-inputs", "version_id": version, "manifest_sha256": version}
    args = argparse.Namespace(
        output=str(tmp_path / "summary.json"),
        data_path=str(sealed.data_root),
        producer_inputs_pin=pin,
        strategy="strategy.py",
        start="2010-01-01",
        end="2010-01-31",
        cash=1000.0,
        capital_mode="shared",
        benchmark_code="0050",
        strategy_params={},
    )

    class Loader:
        corporate_action_db = None

        def get_warnings(self) -> list[str]:
            return []

        def get_stock_data(self, code: str | None, adjust: bool = True) -> pd.DataFrame:
            return pd.DataFrame([{"Date": pd.Timestamp("2010-01-04"), "Close": 64.9, "RawClose": 64.9, "SplitAdjustedClose": 64.9}])

    class Broker:
        cash, fee_rate, tax_rate, per_stock_initial_cash, cash_blocked_entry_count = 1000.0, 0.0, 0.0, None, 0
        positions: dict[str, int] = {}
        trades: list[dict[str, object]] = []

    class Engine:
        loader = Loader()
        data_cache: dict[str, object] = {}
        equity_curve = [{"date": "2010-01-04", "equity": 1000.0}]
        price_curve = [{"date": "2010-01-04", "prices": {"2330": 64.9}}]

    class Strategy:
        __name__ = "Strategy"

    summary = build_summary(args, ["2330"], Strategy, Broker(), Engine(), {"final_value": 1000.0, "total_pnl": 0.0, "return_rate": 0.0})
    assert summary["data"]["producer_inputs"] == pin
    assert resolve_price_data_root(summary["data"]["path"]) == sealed.data_root.resolve()
