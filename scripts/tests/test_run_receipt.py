"""Live producer read guards, primary-root discovery and run receipts on invented data."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from research_core import live_producer
from research_core.live_producer import ProducerBusyError, ProducerChangedError, assert_producer_idle, read_stable, readonly_sqlite
from research_core.run_receipt import InputSpec, changed_results, fingerprint_inputs, write_run_receipt

WEEKDAY_EVENING = datetime(2026, 10, 15, 18, 10)
WEEKDAY_NIGHT = datetime(2026, 10, 15, 1, 30)


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", "-c", "init.templateDir=", "-c", "commit.gpgSign=false", "-c", "user.email=t@example.invalid", "-c", "user.name=T", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "primary checkout"
    root.mkdir()
    _git(["init", "-q", "-b", "main"], root)
    (root / "README.md").write_text("x\n", encoding="utf-8")
    _git(["add", "README.md"], root)
    _git(["commit", "-q", "-m", "init"], root)
    return root


@pytest.fixture
def producer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "producer data"
    root.mkdir()
    pd.DataFrame({"Code": ["2330"] * 3, "Date": pd.to_datetime(["2010-01-04", "2010-01-05", "2026-10-14"])}).to_parquet(root / "price_daily.parquet")
    (root / "data_quality_report.json").write_text('{"generated_at": "2026-10-14T10:26:14+00:00"}', encoding="utf-8")
    monkeypatch.setenv("STOCK_PRODUCER_DATA_ROOT", str(root))
    monkeypatch.setattr(live_producer, "running_producer_tasks", lambda: [])
    return root


@pytest.mark.parametrize(("moment", "busy"), [(WEEKDAY_EVENING, True), (datetime(2026, 10, 15, 18, 45), False), (datetime(2026, 10, 17, 18, 10), False)])
def test_write_window_refuses_weekday_evening(monkeypatch: pytest.MonkeyPatch, moment: datetime, busy: bool) -> None:
    monkeypatch.setattr(live_producer, "running_producer_tasks", lambda: [])
    if busy:
        with pytest.raises(ProducerBusyError, match="write window"):
            assert_producer_idle(moment)
    else:
        assert_producer_idle(moment)
    monkeypatch.setattr(live_producer, "running_producer_tasks", lambda: ["StockProject-OfficialBackfill"])
    with pytest.raises(ProducerBusyError):
        assert_producer_idle(WEEKDAY_NIGHT)


def test_read_stable_detects_a_file_rewritten_during_the_read(tmp_path: Path) -> None:
    path = tmp_path / "price_daily.parquet"
    path.write_bytes(b"old")

    def rewritten(target: Path) -> bytes:
        data = target.read_bytes()
        target.write_bytes(b"new bytes")
        return data

    with pytest.raises(ProducerChangedError):
        read_stable(path, rewritten)
    assert read_stable(path, Path.read_bytes) == b"new bytes"


def test_readonly_sqlite_cannot_write(tmp_path: Path) -> None:
    path = tmp_path / "symbol_meta.sqlite"
    with closing(sqlite3.connect(path)) as database:
        database.execute("CREATE TABLE symbol_meta (code TEXT)")
    with closing(readonly_sqlite(path)) as database, pytest.raises(sqlite3.OperationalError, match="readonly"):
        database.execute("INSERT INTO symbol_meta VALUES ('2330')")


def test_fingerprint_records_identity_and_wal_rows_without_copying(producer: Path) -> None:
    writer = sqlite3.connect(producer / "corporate_actions.sqlite")
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE corporate_actions (code TEXT, ex_date TEXT)")
        writer.executemany("INSERT INTO corporate_actions VALUES (?, ?)", [("2330", "2010-06-01"), ("2330", "2026-06-11")])
        writer.commit()
        before = sorted(path.name for path in producer.iterdir())
        result = fingerprint_inputs(
            [
                InputSpec("prices", producer / "price_daily.parquet", date_column="Date"),
                InputSpec("actions", producer / "corporate_actions.sqlite", tables={"corporate_actions": "ex_date"}),
            ],
            now=WEEKDAY_NIGHT,
        )
    finally:
        writer.close()
    prices, actions = result["inputs"]["prices"], result["inputs"]["actions"]
    assert prices["live_producer"] and prices["rows"] == 3 and prices["date_range"] == ["2010-01-04", "2026-10-14"]
    assert len(prices["sha256"]) == 64
    assert actions["tables"] == {"corporate_actions": {"rows": 2, "date_range": ["2010-06-01", "2026-06-11"]}}
    assert result["producer_as_of"]["data_quality_generated_at"] == "2026-10-14T10:26:14+00:00"
    assert sorted(path.name for path in producer.iterdir() if not path.name.endswith(("-wal", "-shm"))) == [
        name for name in before if not name.endswith(("-wal", "-shm"))
    ]


def test_fingerprint_refuses_live_reads_in_the_write_window(producer: Path, tmp_path: Path) -> None:
    with pytest.raises(ProducerBusyError):
        fingerprint_inputs([InputSpec("prices", producer / "price_daily.parquet")], now=WEEKDAY_EVENING)
    task_file = tmp_path / "task input.csv"
    task_file.write_text("a\n1\n", encoding="utf-8")
    assert fingerprint_inputs([InputSpec("task", task_file)], now=WEEKDAY_EVENING)["producer_as_of"] is None


def test_receipt_hashes_results_and_detects_later_edits(repo: Path, producer: Path) -> None:
    result = repo / "tasks" / "demo" / "runs" / "one" / "summary.json"
    result.parent.mkdir(parents=True)
    result.write_text('{"return": 0.1}\n', encoding="utf-8")
    mission = repo / "tasks" / "demo" / "mission.md"
    mission.write_text("# Demo\n", encoding="utf-8")
    inputs = fingerprint_inputs([InputSpec("prices", producer / "price_daily.parquet", date_column="Date")], now=WEEKDAY_NIGHT)
    receipt_path = result.parent / "receipt.json"
    receipt = write_run_receipt(
        receipt_path,
        run_id="one",
        definition="demo.v1",
        parameters={"horizon": 63},
        inputs=inputs,
        results={"summary": result},
        preregistration=mission,
        repo_root=repo,
    )
    assert receipt["code"] == {"commit": _git(["rev-parse", "HEAD"], repo), "dirty": False}
    assert receipt["results"]["summary"]["path"] == "tasks/demo/runs/one/summary.json"
    assert changed_results(receipt_path, repo) == []
    with pytest.raises(FileExistsError):
        write_run_receipt(receipt_path, run_id="one", definition="demo.v1", parameters={}, inputs=inputs, results={}, repo_root=repo)
    result.write_text('{"return": 0.2}\n', encoding="utf-8")
    assert changed_results(receipt_path, repo) == ["summary"]
    os.remove(result)
    assert changed_results(receipt_path, repo) == ["summary"]


def test_receipt_refuses_inputs_changed_during_the_run(repo: Path, producer: Path) -> None:
    """A writer that ran between the reads and the receipt is caught, including a SQLite WAL commit."""
    database = producer / "symbol_meta.sqlite"
    with closing(sqlite3.connect(database)) as setup:
        setup.execute("PRAGMA journal_mode=WAL")
        setup.execute("CREATE TABLE symbol_meta (code TEXT)")
        setup.commit()
    result = repo / "summary.json"
    result.write_text("{}\n", encoding="utf-8")
    specs = [InputSpec("prices", producer / "price_daily.parquet"), InputSpec("meta", database, tables={"symbol_meta": None})]
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        fingerprint = fingerprint_inputs(specs, now=WEEKDAY_NIGHT)
        writer.execute("INSERT INTO symbol_meta VALUES ('2330')")
        writer.commit()
        with pytest.raises(ProducerChangedError, match="meta"):
            write_run_receipt(repo / "r1.json", run_id="r", definition="d", parameters={}, inputs=fingerprint, results={"s": result}, repo_root=repo)
    finally:
        writer.close()
    fingerprint = fingerprint_inputs(specs, now=WEEKDAY_NIGHT)
    os.utime(producer / "price_daily.parquet", ns=(1, 1))
    with pytest.raises(ProducerChangedError, match="prices"):
        write_run_receipt(repo / "r2.json", run_id="r", definition="d", parameters={}, inputs=fingerprint, results={"s": result}, repo_root=repo)
    assert not (repo / "r1.json").exists() and not (repo / "r2.json").exists()
