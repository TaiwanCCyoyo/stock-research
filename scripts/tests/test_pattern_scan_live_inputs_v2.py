"""Synthetic live-source reader regression tests; no producer or scheduler reads."""

from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core import pattern_scan_live_inputs_v2 as live
from research_core import run_receipt
from research_core.artifact_store import canonical, object_digest
from research_core.live_producer import ProducerChangedError
from research_core.research_data_paths import DataRoots


@pytest.fixture
def sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[DataRoots, Path, Path]:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    roots = DataRoots(primary, primary / "research_data")
    producer = tmp_path / "live producer"
    producer.mkdir()
    monkeypatch.setattr(live, "producer_data_root", lambda: producer)
    monkeypatch.setattr(run_receipt, "producer_data_root", lambda: producer)
    monkeypatch.setattr(run_receipt, "assert_producer_idle", lambda now: None)
    dates = ["2010-01-04", "2010-01-05", "2026-10-12"]
    rows = [
        (code, day, 10.0, 11.0, 9.0, 10.0, 100.0, source)
        for code, source in (("1101", "official"), ("0050", "official"), ("9999", "shioaji"))
        for day in pd.to_datetime([*dates, "2026-10-14"])
    ]
    pd.DataFrame(rows, columns=pd.Index(live.PRICE_COLUMNS)).to_parquet(producer / "price_daily.parquet", index=False)
    with closing(sqlite3.connect(producer / "symbol_meta.sqlite")) as connection:
        pd.DataFrame([
            {"code": code, "name": code, "market": "TWSE", "security_category": category, "is_etf": etf}
            for code, category, etf in (("1101", "股票", 0), ("0050", "ETF", 1), ("9999", "股票", 0), ("8888", "股票", 0))
        ]).to_sql("symbol_meta", connection, index=False)
    with closing(sqlite3.connect(producer / "corporate_actions.sqlite")) as connection:
        pd.DataFrame([{"code": "1101", "ex_date": day, "event_type": "CASH_DIVIDEND", "price_factor": 0.99} for day in ("2010-01-05", "2026-10-14")]).to_sql(
            "corporate_actions", connection, index=False
        )
    pins = primary / "pins.json.gz"
    pins.write_bytes(
        gzip.compress(
            canonical({
                "cutoff": dates[-1],
                "price_observation": {"calendar": {"dates": dates, "sha256": object_digest(dates)}},
                # Deliberately no physical snapshot manifest.
            })
        )
    )
    return roots, producer, pins


def test_live_reader_filters_study_but_fingerprints_full_sources(sources: tuple[DataRoots, Path, Path]) -> None:
    roots, producer, pins = sources
    before = {path.name: path.read_bytes() for path in producer.iterdir()}
    loaded = live.load_live_inputs(roots, pins_path=pins)
    assert set(loaded.prices.Code) == {"1101", "0050"}
    assert len(loaded.prices) == 6
    assert loaded.actions.ex_date.tolist() == ["2010-01-05"]
    assert loaded.inventory.loc[loaded.inventory.included, "code"].tolist() == ["1101"]
    assert set(loaded.inventory.code) == {"1101", "0050", "9999", "8888"}
    assert loaded.fingerprint["inputs"]["price_daily"]["date_range"] == ["2010-01-04", "2026-10-14"]
    assert loaded.fingerprint["inputs"]["corporate_actions"]["tables"]["corporate_actions"]["date_range"] == ["2010-01-05", "2026-10-14"]
    assert loaded.stock("1101").Close.tolist() == [9.9, 10.0, 10.0]
    assert loaded.stock("0050").Close.tolist() == [10.0] * 3
    with pytest.raises(ValueError, match="outside"):
        loaded.stock("9999")
    loaded.verify_after()
    assert {path.name: path.read_bytes() for path in producer.iterdir()} == before
    assert not (roots.primary / "tasks").exists()


def test_readonly_transactions_never_serialize_backup_copy_or_immutable(
    sources: tuple[DataRoots, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots, _, pins = sources
    original = sqlite3.connect
    queries: list[str] = []
    connections: list[str] = []

    class Observed(sqlite3.Connection):
        def serialize(self, **kwargs: Any) -> bytes:
            pytest.fail("must not serialize live SQLite")

        def backup(self, *args: Any, **kwargs: Any) -> None:
            pytest.fail("must not back up live SQLite")

    def connect(database: str, **kwargs: Any) -> sqlite3.Connection:
        assert database.endswith("?mode=ro") and "immutable" not in database
        connections.append(database)
        connection = original(database, factory=Observed, **kwargs)
        connection.set_trace_callback(queries.append)
        return connection

    def no_copy(*args: Any, **kwargs: Any) -> None:
        pytest.fail("must not copy inputs")

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(shutil, "copyfile", no_copy)
    live.load_live_inputs(roots, pins_path=pins)
    assert len(connections) == 4  # fingerprint and consumption of both databases
    assert queries.count("BEGIN") == queries.count("COMMIT") == 4


@pytest.mark.parametrize("bad_date", ["2010-01-05 09:30", "2010-01-06"])
def test_raw_calendar_mismatch_rejected(sources: tuple[DataRoots, Path, Path], bad_date: str) -> None:
    roots, producer, pins = sources
    path = producer / "price_daily.parquet"
    frame = pd.read_parquet(path)
    frame.loc[1, "Date"] = pd.Timestamp(bad_date)
    frame.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="raw dates differ"):
        live.load_live_inputs(roots, pins_path=pins)


def test_raw_numeric_code_rejected(sources: tuple[DataRoots, Path, Path]) -> None:
    roots, producer, pins = sources
    path = producer / "price_daily.parquet"
    frame = pd.read_parquet(path)
    frame["Code"] = frame.Code.astype(int)
    frame.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="raw code identity"):
        live.load_live_inputs(roots, pins_path=pins)


@pytest.mark.parametrize("bad", ["digest", "cutoff", "start"])
def test_approved_pins_required(sources: tuple[DataRoots, Path, Path], bad: str) -> None:
    roots, _, pins = sources
    value = json.loads(gzip.decompress(pins.read_bytes()))
    calendar = value["price_observation"]["calendar"]
    if bad == "digest":
        calendar["sha256"] = "0" * 64
    elif bad == "cutoff":
        value["cutoff"] = "2026-10-14"
    else:
        calendar["dates"][0] = "2010-01-05"
        calendar["sha256"] = object_digest(calendar["dates"])
    pins.write_bytes(gzip.compress(canonical(value)))
    with pytest.raises(ValueError, match="calendar|approved"):
        live.load_live_inputs(roots, pins_path=pins)


def test_identity_excludes_capture_time_and_verification_detects_changes(
    sources: tuple[DataRoots, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots, producer, pins = sources
    fingerprint = live.fingerprint_inputs
    captures = iter(("first capture", "later capture"))

    def observed(specs: list[run_receipt.InputSpec]) -> dict[str, Any]:
        result = fingerprint(specs)
        result["captured_at_utc"] = next(captures)
        return result

    monkeypatch.setattr(live, "fingerprint_inputs", observed)
    first = live.load_live_inputs(roots, pins_path=pins)
    second = live.load_live_inputs(roots, pins_path=pins)
    assert first.input_id == second.input_id
    assert first.fingerprint["captured_at_utc"] != second.fingerprint["captured_at_utc"]
    with (producer / "price_daily.parquet").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ProducerChangedError, match="price_daily"):
        first.verify_after()


def test_mid_read_file_change_fails(sources: tuple[DataRoots, Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    roots, _, pins = sources
    original = pd.read_parquet

    def read(path: Path, **kwargs: Any) -> pd.DataFrame:
        frame = original(path, **kwargs)
        if "filters" in kwargs:
            with path.open("ab") as stream:
                stream.write(b"changed during read")
        return frame

    monkeypatch.setattr(pd, "read_parquet", read)
    with pytest.raises(ProducerChangedError, match="during read"):
        live.load_live_inputs(roots, pins_path=pins)
