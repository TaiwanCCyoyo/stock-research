"""Live producer read guards, primary-root discovery and run receipts on invented data."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from research_core import live_producer
from research_core.artifact_store import file_digest
from research_core.live_producer import ProducerBusyError, ProducerChangedError, assert_producer_idle, read_stable, readonly_sqlite
from research_core.run_receipt import InputSpec, assert_inputs_unchanged, changed_inputs, changed_results, fingerprint_inputs, write_run_receipt

TAIPEI = timezone(timedelta(hours=8))
WEEKDAY_EVENING = datetime(2026, 10, 15, 18, 10, tzinfo=TAIPEI)
WEEKDAY_NIGHT = datetime(2026, 10, 15, 1, 30, tzinfo=TAIPEI)


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


@pytest.mark.parametrize(
    ("moment", "busy"),
    [
        (WEEKDAY_EVENING, True),
        (datetime(2026, 10, 15, 10, 10, tzinfo=timezone.utc), True),
        (datetime(2026, 10, 15, 18, 10, tzinfo=timezone.utc), False),
        (datetime(2026, 10, 15, 18, 45, tzinfo=TAIPEI), False),
        (datetime(2026, 10, 17, 18, 10, tzinfo=TAIPEI), False),
    ],
)
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
    assert "sha256" not in prices, "inputs are described, not hashed (owner decision 2026-10-19)"
    assert prices["bytes"] > 0 and prices["mtime_ns"] > 0
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
    _git(["add", "tasks/demo/mission.md"], repo)
    _git(["commit", "-q", "-m", "preregister"], repo)
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


def test_receipt_records_inputs_changed_during_the_run(repo: Path, producer: Path) -> None:
    """A writer between the reads and the receipt is recorded, including a SQLite WAL commit; the result is still saved."""
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
        first = write_run_receipt(repo / "r1.json", run_id="r", definition="d", parameters={}, inputs=fingerprint, results={"s": result}, repo_root=repo)
    finally:
        writer.close()
    assert first["inputs_changed_during_run"] == ["meta"]
    fingerprint = fingerprint_inputs(specs, now=WEEKDAY_NIGHT)
    os.utime(producer / "price_daily.parquet", ns=(1, 1))
    second = write_run_receipt(repo / "r2.json", run_id="r", definition="d", parameters={}, inputs=fingerprint, results={"s": result}, repo_root=repo)
    assert second["inputs_changed_during_run"] == ["prices"]
    assert (repo / "r1.json").exists() and (repo / "r2.json").exists(), "a finished result is saved, with the change recorded"
    with pytest.raises(ProducerChangedError, match="prices"):
        assert_inputs_unchanged(fingerprint)


def test_receipt_records_shared_generation_reads_as_information(repo: Path, producer: Path, tmp_path: Path) -> None:
    generation = tmp_path / "shared" / "derived" / "demo-v1" / "generations" / "g1"
    generation.mkdir(parents=True)
    (generation / "status.json").write_text('{"generation": "g1"}\n', encoding="utf-8")
    (generation / "raw.parquet").write_bytes(b"not re-read by the receipt")
    record = {
        "family": "demo-v1",
        "generation": "g1",
        "file": str(generation / "raw.parquet"),
        "sha256": "a" * 64,
        "status_sha256": file_digest(generation / "status.json"),
    }
    result = repo / "summary.json"
    result.write_text("{}\n", encoding="utf-8")
    inputs = fingerprint_inputs([InputSpec("prices", producer / "price_daily.parquet")], now=WEEKDAY_NIGHT)
    receipt = write_run_receipt(
        repo / "r1.json", run_id="r", definition="d", parameters={}, inputs=inputs, results={"s": result}, repo_root=repo, shared_data=[record]
    )
    described = {"family": "demo-v1", "generation": "g1", "file": record["file"]}
    assert receipt["shared_data"] == [described], "digests from the reader are dropped; only the description is kept"
    plain = write_run_receipt(repo / "r2.json", run_id="r", definition="d", parameters={}, inputs=inputs, results={"s": result}, repo_root=repo)
    assert "shared_data" not in plain, "receipts without shared reads keep their earlier shape"
    (generation / "status.json").unlink()
    pruned = write_run_receipt(
        repo / "r3.json", run_id="r", definition="d", parameters={}, inputs=inputs, results={"s": result}, repo_root=repo, shared_data=[record]
    )
    assert pruned["shared_data"] == [described], "a generation pruned after it was read does not block saving the result"


def test_fingerprint_of_task_inputs_needs_no_producer_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import run_receipt

    def unconfigured() -> Path:
        raise RuntimeError("no producer root configured")

    monkeypatch.setattr(run_receipt, "producer_data_root", unconfigured)
    task_file = tmp_path / "labels.csv"
    task_file.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot classify"):
        fingerprint_inputs([InputSpec("labels", task_file)], now=WEEKDAY_EVENING)
    result = fingerprint_inputs([InputSpec("labels", task_file, live_producer=False)], now=WEEKDAY_EVENING)
    assert result["producer_as_of"] is None and result["inputs"]["labels"]["live_producer"] is False


def test_naive_timestamps_are_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        assert_producer_idle(datetime(2026, 10, 15, 1, 30))


def test_task_input_declared_under_the_producer_root_is_rejected(producer: Path) -> None:
    with pytest.raises(ValueError, match="declared task-owned"):
        fingerprint_inputs([InputSpec("prices", producer / "price_daily.parquet", live_producer=False)], now=WEEKDAY_NIGHT)


def test_directory_listing_fingerprint_detects_a_rewritten_csv(repo: Path, producer: Path) -> None:
    day_csv = producer / "2330_day.csv"
    day_csv.write_text("Date,Close\n2010-01-04,64.9\n", encoding="utf-8")
    fingerprint = fingerprint_inputs([InputSpec("day_csv", producer, pattern="*_day.csv")], now=WEEKDAY_NIGHT)
    assert fingerprint["inputs"]["day_csv"]["files"] == 1 and fingerprint["inputs"]["day_csv"]["live_producer"]
    assert "listing_sha256" not in fingerprint["inputs"]["day_csv"], "a directory input is described, not hashed"
    result = repo / "summary.json"
    result.write_text("{}\n", encoding="utf-8")
    day_csv.write_text("Date,Close\n2010-01-04,64.9\n2010-01-05,65.0\n", encoding="utf-8")
    assert changed_inputs(fingerprint) == ["day_csv"]
    with pytest.raises(ProducerChangedError, match="day_csv"):
        assert_inputs_unchanged(fingerprint)


PINNED_READER = """
def write(path):
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO corporate_actions VALUES ('2330')")
"""


def test_sqlite_reads_readonly_routes_a_modules_connect(tmp_path: Path) -> None:
    import types

    from research_core.live_producer import sqlite_reads_readonly

    database = tmp_path / "corporate_actions.sqlite"
    with closing(sqlite3.connect(database)) as setup:
        setup.execute("CREATE TABLE corporate_actions (code TEXT)")
        setup.commit()
    module = types.ModuleType("pinned_reader")
    module.sqlite3 = sqlite3  # type: ignore[attr-defined]
    exec(PINNED_READER, module.__dict__)  # noqa: S102 - stands in for a pinned module that calls sqlite3.connect
    with sqlite_reads_readonly(module), pytest.raises(sqlite3.OperationalError, match="readonly"):
        module.write(database)
    assert module.sqlite3 is sqlite3


def test_receipt_names_a_committed_preregistration_by_path(repo: Path, producer: Path, tmp_path: Path) -> None:
    result = repo / "summary.json"
    result.write_text("{}\n", encoding="utf-8")
    mission = repo / "mission.md"
    mission.write_text("# Demo\n", encoding="utf-8")
    _git(["add", "mission.md"], repo)
    _git(["commit", "-q", "-m", "preregister"], repo)
    inputs = fingerprint_inputs([InputSpec("prices", producer / "price_daily.parquet")], now=WEEKDAY_NIGHT)
    receipt = write_run_receipt(
        repo / "r1.json", run_id="r", definition="d", parameters={}, inputs=inputs, results={"s": result}, preregistration=mission, repo_root=repo
    )
    assert receipt["preregistration"] == {"path": "mission.md"}, "a source is named, not hashed"
    with pytest.raises(FileNotFoundError, match="preregistration"):
        write_run_receipt(
            repo / "r2.json",
            run_id="r",
            definition="d",
            parameters={},
            inputs=inputs,
            results={"s": result},
            preregistration=repo / "missing.md",
            repo_root=repo,
        )
    untracked = repo / "draft.md"
    untracked.write_text("# Draft\n", encoding="utf-8")
    outside = tmp_path / "elsewhere.md"
    outside.write_text("# Elsewhere\n", encoding="utf-8")
    for path, reason in ((untracked, "not tracked"), (outside, "outside the repository")):
        with pytest.raises(ValueError, match=reason):
            write_run_receipt(
                repo / "r3.json", run_id="r", definition="d", parameters={}, inputs=inputs, results={"s": result}, preregistration=path, repo_root=repo
            )
    mission.write_text("# Demo, edited after the commit\n", encoding="utf-8")
    with pytest.raises(ValueError, match="differs from the recorded commit"):
        write_run_receipt(
            repo / "r3.json", run_id="r", definition="d", parameters={}, inputs=inputs, results={"s": result}, preregistration=mission, repo_root=repo
        )
    assert not (repo / "r2.json").exists() and not (repo / "r3.json").exists()


def test_nested_reader_digests_are_dropped_from_shared_reads() -> None:
    from research_core.run_receipt import _describe_shared_read

    record = {
        "family": "adjusted-daily-v1",
        "generation": "g1",
        "sha256": "a" * 64,
        "status_sha256": "b" * 64,
        "actions_sha256": "c" * 64,
        "calendar": {"sessions": 3, "first": "2026-10-01", "sha256": "d" * 64, "file_sha256": "e" * 64},
        "prices": {"basis": "raw", "sha256": "f" * 64},
    }
    assert _describe_shared_read(record) == {
        "family": "adjusted-daily-v1",
        "generation": "g1",
        "calendar": {"sessions": 3, "first": "2026-10-01"},
        "prices": {"basis": "raw"},
    }


def test_a_renamed_directory_file_with_equal_totals_is_recorded(producer: Path) -> None:
    first = producer / "2330_day.csv"
    first.write_text("Date,Close\n", encoding="utf-8")
    fingerprint = fingerprint_inputs([InputSpec("day_csv", producer, pattern="*_day.csv")], now=WEEKDAY_NIGHT)
    assert fingerprint["inputs"]["day_csv"]["listing"][0][0] == "2330_day.csv"
    stat = first.stat()
    renamed = producer / "2317_day.csv"
    first.rename(renamed)
    os.utime(renamed, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # same size, same mtime, new name
    assert changed_inputs(fingerprint) == ["day_csv"]


def test_an_input_vanishing_during_the_recheck_is_recorded_not_raised(producer: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import run_receipt

    fingerprint = fingerprint_inputs([InputSpec("prices", producer / "price_daily.parquet")], now=WEEKDAY_NIGHT)

    def vanished(path: Path) -> object:
        raise FileNotFoundError(path)

    monkeypatch.setattr(run_receipt, "stat_identity", vanished)
    assert changed_inputs(fingerprint) == ["prices"]
