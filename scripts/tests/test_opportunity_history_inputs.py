from __future__ import annotations

import gzip
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core.opportunity_history_inputs import (
    PERMANENT_EVENTS,
    build_series,
    export_series,
    file_hash,
    snapshot_inputs,
)


def quotes(code: str = "2330") -> pd.DataFrame:
    return pd.DataFrame([
        {"Code": code, "Date": date, "Open": close, "High": close, "Low": close, "Close": close, "Volume": volume, "Source": source}
        for date, close, volume, source in [("2010-01-04", 100.12345, -1, "official"), ("2010-01-06", 50.0, 1, "shioaji"), ("2010-01-07", 100.0, 1, "official")]
    ])


def make_series(events: list[dict[str, Any]], frame: pd.DataFrame | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_series(
        quotes() if frame is None else frame,
        ["2010-01-04", "2010-01-05", "2010-01-06", "2010-01-07"],
        code="2330",
        metadata=metadata or {"security_category": "股票"},
        name="Test",
        calendar_id="test",
        events=events,
        cutoff="2010-01-07",
    )


def event(kind: str = "EX_RIGHT", factor: float | None = 0.5, date: str = "2010-01-06") -> dict[str, Any]:
    return {"ex_date": date, "event_type": kind, "price_factor": factor}


@pytest.mark.parametrize("kind", sorted(PERMANENT_EVENTS))
def test_permanent_dates_rounding_and_duplicate(kind: str) -> None:
    result = make_series([event(kind), event(kind), event("CASH_DIVIDEND", 0.8), event(kind, 0.1, "2010-01-08"), event(kind, 0.1, "2009-12-01")])
    assert result["raw"] == [100.12345, None, 50, 100]
    assert result["adjusted"] == [50.0617, None, 50, 100]
    assert result["numeric_flags"] == {}
    assert result["volume_flags"] == {"0": ["invalid_volume"]}
    assert result["sources"] == ["official", None, "shioaji", "official"]
    assert result["coverage"]["missing_count"] == 1
    assert result["coverage_caveats"]


def test_cash_does_not_apply_window_or_permanent_factor() -> None:
    result = make_series([event("CASH_DIVIDEND", 0.8)])
    assert result["adjusted"] == [100.1235, None, 50, 100]
    assert result["action_barriers"] == []


def test_source_missing_summary_counts_observed_rows_only() -> None:
    dates = [f"2010-01-{day:02}" for day in range(4, 10)]
    frame = pd.DataFrame([
        {"Code": "2330", "Date": date, "Open": 100, "High": 100, "Low": 100, "Close": 100, "Volume": 1, "Source": source}
        for date, source in zip(dates[:5], [None, float("nan"), pd.NA, "official", "shioaji"], strict=True)
    ])
    result = build_series(
        frame,
        dates,
        code="2330",
        metadata={"security_category": "股票"},
        name="Test",
        calendar_id="test",
        events=[],
        cutoff=dates[-1],
    )
    assert result["sources"] == [None, None, None, "official", "shioaji", None]
    assert result["coverage"]["source_counts"] == {"official": 1, "shioaji": 1}
    assert result["coverage"]["source_missing_count"] == 3
    assert result["coverage"]["date_count"] == 5
    assert result["coverage"]["missing_count"] == 1
    assert not {"nan", "None", "<NA>"} & result["coverage"]["source_counts"].keys()
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("factor", [None, 0, -1, float("nan"), float("inf")])
def test_unresolved_factor_flags_first_quote_only(factor: float | None) -> None:
    result = make_series([event(factor=factor, date="2010-01-05")])
    assert result["numeric_flags"] == {"2": ["action_barrier"]}
    assert result["raw"][2] == result["adjusted"][2] == 50
    assert result["action_barriers"][0]["index"] == 2
    json.dumps(result, allow_nan=False)


def test_conflict_and_unsupported_are_edge_barriers() -> None:
    result = make_series([event(), event(factor=0.6), event("UNKNOWN", 1, "2010-01-07")])
    assert result["adjusted"][0] == 100.1235
    assert result["numeric_flags"] == {"2": ["action_barrier"], "3": ["action_barrier"]}
    assert [item["reason"] for item in result["action_barriers"]] == ["conflicting_action_records", "unsupported_action_type"]


@pytest.mark.parametrize("date", ["2009-12-01", "2010-01-04"])
def test_unresolved_action_without_prior_quote_is_coverage_only(date: str) -> None:
    result = make_series([event(factor=None, date=date)])
    assert result["numeric_flags"] == {}
    assert result["action_barriers"][0]["index"] is None
    assert not result["action_barriers"][0]["continuity_edge_observed"]
    assert "unresolved_action_without_observed_continuity_edge" in result["coverage_caveats"]


def test_action_source_locator_preserves_observation_not_availability() -> None:
    record = event() | {"source": "TWSE", "market": "twse", "evidence_status": "official", "fetched_at": "2026-10-04T00:00:00Z"}
    saved = make_series([record])["corporate_actions"][0]
    assert saved["source"] == "TWSE"
    assert saved["market"] == "twse"
    assert saved["evidence_status"] == "official"
    assert saved["fetched_at"] == record["fetched_at"]
    assert saved["sql_locator"]["key"] == {"source": "TWSE", "market": "twse", "code": "2330", "ex_date": "2010-01-06"}
    assert saved["first_available_at"] is None
    assert saved["availability_reason"] == "unknown_first_availability"


def test_adjustment_failure_is_independent_from_raw_and_volume() -> None:
    result = make_series([event(factor=1e-300), event(factor=1e-300, date="2010-01-07")])
    assert result["raw"][0] > 0
    assert result["adjusted"][0] is None
    assert result["numeric_flags"]["0"] == ["unusable_adjusted_close"]


def fixture_sources(tmp_path: Path) -> dict[str, Path]:
    directory = tmp_path / "來源 inputs with spaces"
    directory.mkdir()
    pd.concat([quotes(), quotes("0050"), quotes("9999"), quotes("7777")]).to_parquet(directory / "price_daily.parquet")
    with sqlite3.connect(directory / "corporate_actions.sqlite") as db:
        db.execute("CREATE TABLE corporate_actions (code TEXT, ex_date TEXT, event_type TEXT, price_factor REAL)")
        db.execute("INSERT INTO corporate_actions VALUES ('2330','2010-01-06','EX_RIGHT',0.5)")
    with sqlite3.connect(directory / "symbol_meta.sqlite") as db:
        db.execute("CREATE TABLE symbol_meta (code TEXT, name TEXT, security_category TEXT, fetched_at TEXT)")
        db.execute("INSERT INTO symbol_meta VALUES ('2330','Test','股票','2026-10-04')")
        db.execute("INSERT INTO symbol_meta VALUES ('7777','Innovative','創新板','2026-10-04')")
    (directory / "stock_symbol_mapping.json5").write_text(json.dumps({"9999": "Unknown"}), encoding="utf-8")
    (directory / "value_chain_classification.json").write_text(json.dumps({"symbols": {"9999": {"listing_segments": ["本國上市公司"]}}}), encoding="utf-8")
    return {path.name: path for path in directory.iterdir()}


def test_snapshot_export_hashes_sources_roles_and_overwrite(tmp_path: Path) -> None:
    paths = fixture_sources(tmp_path)
    originals = {name: file_hash(path) for name, path in paths.items()}
    snapshot = tmp_path / "snapshot"
    receipt = snapshot_inputs(paths, snapshot, originals)
    assert {name: file_hash(path) for name, path in paths.items()} == originals
    assert [item["quick_check"] for item in receipt["files"] if item["name"].endswith(".sqlite")] == ["ok", "ok"]
    output = tmp_path / "catalog-v1"
    manifest = export_series(snapshot, output)
    assert manifest["count"] == 4
    assert manifest["calendar"]["count"] == 3
    rows = {row["code"]: row for row in manifest["rows"]}
    assert rows["0050"]["instrument_role"] == "benchmark"
    assert rows["7777"]["cohort"] == "innovation_board"
    assert rows["9999"]["instrument_role"] == "unresolved_identity"
    assert rows["2330"]["coverage"]["source_counts"] == {"official": 2, "shioaji": 1}
    series = json.loads(gzip.decompress((output / rows["9999"]["path"]).read_bytes()))
    assert series["listing_segments_snapshot_clue"] == ["本國上市公司"]
    output2 = tmp_path / "catalog-v1-again"
    assert export_series(snapshot, output2) == manifest
    assert file_hash(output / rows["2330"]["path"]) == file_hash(output2 / rows["2330"]["path"])
    with pytest.raises(FileExistsError):
        snapshot_inputs(paths, snapshot)
    with pytest.raises(FileExistsError):
        export_series(snapshot, output)


def test_preflight_hash_refusal_does_not_create_target(tmp_path: Path) -> None:
    paths = fixture_sources(tmp_path)
    target = tmp_path / "no-mutation"
    with pytest.raises(ValueError, match="Source hash mismatch"):
        snapshot_inputs(paths, target, {"price_daily.parquet": "bad"})
    assert not target.exists()


def test_nonempty_committed_wal_refused_even_when_main_hash_is_pinned(tmp_path: Path) -> None:
    source = tmp_path / "wal.sqlite"
    with sqlite3.connect(source) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE example (n INTEGER)")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        original = file_hash(source)
        writer.execute("INSERT INTO example VALUES (7)")
        writer.commit()
        assert file_hash(source) == original
        wal = Path(str(source) + "-wal")
        wal_before = wal.read_bytes()
        target = tmp_path / "snapshot"
        with pytest.raises(ValueError, match="Nonempty source WAL.*checkpointed coherent"):
            snapshot_inputs({source.name: source}, target, {source.name: original})
        assert file_hash(source) == original and wal.read_bytes() == wal_before
        assert not target.exists()


def test_checkpointed_same_logical_rows_backup_succeeds_without_source_mutation(tmp_path: Path) -> None:
    source = tmp_path / "checkpointed.sqlite"
    with sqlite3.connect(source) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE example (n INTEGER)")
        writer.execute("INSERT INTO example VALUES (7)")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        original = file_hash(source)
        wal = Path(str(source) + "-wal")
        assert wal.stat().st_size == 0
        receipt = snapshot_inputs({source.name: source}, tmp_path / "snapshot", {source.name: original})
        assert file_hash(source) == original and wal.stat().st_size == 0
        assert receipt["files"][0]["source_sha256"] == original
        with sqlite3.connect(tmp_path / "snapshot" / source.name) as pinned:
            assert pinned.execute("SELECT n FROM example").fetchall() == [(7,)]


@pytest.mark.parametrize("wal_change", ["create_empty", "create_nonempty", "change_empty"])
def test_wal_identity_change_during_backup_refuses_receipt_and_preserves_partial_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wal_change: str,
) -> None:
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as writer:
        writer.execute("CREATE TABLE example (n INTEGER)")
        writer.execute("INSERT INTO example VALUES (7)")
    wal = Path(str(source) + "-wal")
    if wal_change == "change_empty":
        wal.write_bytes(b"")
    original = file_hash(source)
    real_connect = sqlite3.connect

    class ChangingConnection(sqlite3.Connection):
        def backup(self, target: sqlite3.Connection, **kwargs: Any) -> None:
            super().backup(target, **kwargs)
            if wal_change == "change_empty":
                before = wal.stat()
                os.utime(wal, ns=(before.st_atime_ns, before.st_mtime_ns + 10_000_000))
            else:
                wal.write_bytes(b"committed WAL fixture" if wal_change == "create_nonempty" else b"")

    def connect(database: Any, **kwargs: Any) -> sqlite3.Connection:
        return real_connect(database, factory=ChangingConnection, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    target = tmp_path / "partial"
    with pytest.raises(ValueError, match="WAL"):
        snapshot_inputs({source.name: source}, target, {source.name: original})
    assert file_hash(source) == original
    assert (target / source.name).exists()
    assert not (target / "input-receipt.json").exists()
    with pytest.raises(FileExistsError, match="Refusing nonempty target"):
        snapshot_inputs({source.name: source}, target)


def test_cli_receipt_with_windows_safe_space_paths(tmp_path: Path) -> None:
    paths = fixture_sources(tmp_path)
    output = tmp_path / "輸出 catalog"
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "prepare_opportunity_history.py"),
        "--source-dir",
        str(paths["price_daily.parquet"].parent),
        "--snapshot-dir",
        str(tmp_path / "固定 snapshot"),
        "--output-dir",
        str(output),
        "--mapping-path",
        str(paths["stock_symbol_mapping.json5"]),
        "--expected-price-hash",
        file_hash(paths["price_daily.parquet"]),
        "--expected-actions-hash",
        file_hash(paths["corporate_actions.sqlite"]),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True)
    assert json.loads(completed.stdout)["count"] == 4
    assert (output / "series-manifest.json").exists()
    blocked = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert blocked.returncode != 0
    assert "Refusing nonempty target" in blocked.stderr
