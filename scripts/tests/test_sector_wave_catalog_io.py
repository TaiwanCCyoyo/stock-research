from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from research_core.sector_waves import compare_peer, detect_episodes, select_wave_winner
from scripts.build_sector_wave_catalog import (
    CatalogIOError,
    _actions,
    _bars_for_code,
    _input_sha,
    _load_prices,
    _path_quality_flags,
    _sha,
    build_bundle,
    validate_bundle,
)
from StockProject.engine.data_loader import DataLoader


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    data = root / "shioaji_stock_prices" / "data"
    data.mkdir(parents=True)
    (root / "tasks" / "20261002-sector-wave-catalog").mkdir(parents=True)
    (root / "research_core").mkdir()
    (root / "StockProject" / "engine").mkdir(parents=True)
    (root / "docs" / "en").mkdir(parents=True)
    for path in [
        root / "tasks" / "20261002-sector-wave-catalog" / "mission.md",
        root / "docs" / "en" / "research-owner-contract.md",
        root / "docs" / "en" / "research-foundation.md",
        root / "docs" / "en" / "research-registry.json",
        root / "uv.lock",
        root / "StockProject" / "engine" / "data_loader.py",
        root / "research_core" / "sector_waves.py",
        root / "research_core" / "sector_groups.py",
        root / "research_core" / "evidence.py",
    ]:
        path.write_text("x", encoding="utf-8")
    (data / "value_chain_classification.json").write_text(
        json.dumps({
            "schema_version": 1,
            "snapshot_id": "s",
            "symbols": {},
            "chains": [
                {
                    "code": "x",
                    "name": "X",
                    "source_url": "u",
                    "nodes": [{"code": "n", "name": "N", "parent_code": None, "members": [{"code": "A", "name": "A"}, {"code": "C", "name": "C"}]}],
                }
            ],
        }),
        encoding="utf-8",
    )
    (root / "research_core" / "sector_groups.v1.json").write_text(
        json.dumps({
            "schema_version": "sector-groups.v1",
            "groups": [{"group_id": "x", "label": "X", "selectors": [{"chain_code": "x", "node_code": "n"}], "exclude_selectors": []}],
        }),
        encoding="utf-8",
    )
    prices = pd.DataFrame({
        "Code": ["A", "A", "A", "A", "A", "A"],
        "Date": pd.to_datetime(["2019-01-02", "2019-01-03", "2019-01-04", "2019-01-05", "2019-01-06", "2027-01-02"]),
        "Open": [100, 60, 72, 86.4, 103.68, 300],
        "High": [100, 60, 72, 86.4, 103.68, 300],
        "Low": [100, 60, 72, 86.4, 103.68, 300],
        "Close": [100, 60, 72, 86.4, 103.68, 300],
        "Volume": [1, 1, 1, 1, 1, 1],
        "Source": ["official", "official", "official", "official", "official", "official"],
    })
    prices.to_parquet(data / "price_daily.parquet")
    connection = sqlite3.connect(data / "symbol_meta.sqlite")
    connection.execute("CREATE TABLE symbol_meta(code, name, market, industry_category, is_etf, security_category, fetched_at)")
    connection.executemany(
        "INSERT INTO symbol_meta VALUES(?,?,?,?,?,?,?)",
        [
            ("A", "A", "TWSE", "x", 0, "股票", "2026-10-02"),
            ("B", "B", "TWSE", "x", 0, "股票", "2026-10-02"),
            ("C", "C", "TWSE", "x", 0, "股票", "2026-10-02"),
            ("F", "F", "上市", "x", 0, "債券", "2026-10-02"),
        ],
    )
    connection.commit()
    connection.close()
    connection = sqlite3.connect(data / "corporate_actions.sqlite")
    connection.execute("CREATE TABLE corporate_actions(code, ex_date, event_type, price_factor, previous_close)")
    connection.execute("INSERT INTO corporate_actions VALUES('A','2019-01-03','ETF_SPLIT',0.5,NULL)")
    connection.execute("INSERT INTO corporate_actions VALUES('A','2027-01-01','ETF_SPLIT',0.01,NULL)")
    connection.commit()
    connection.close()
    return root


def test_bundle_filters_future_row_retains_no_bars_and_checks_integrity(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    output = root / "tasks" / "20261002-sector-wave-catalog" / "runs" / "one"
    manifest = build_bundle(root, output, "one")
    assert manifest["counts"]["securities"] == 3
    chunks = list((output / "chunks").glob("securities-*.json.gz"))
    with gzip.open(chunks[0], "rt", encoding="utf-8") as handle:
        rows = json.load(handle)
    assert next(row for row in rows if row["code"] == "C")["price_coverage_status"] == "no_bars"
    assert next(row for row in rows if row["code"] == "B")["coverage_status"] == "source_missing"
    assert manifest["coverage"]["excluded"] == 1
    assert _load_prices(root / "shioaji_stock_prices" / "data" / "price_daily.parquet")["Date"].max() == pd.Timestamp("2019-01-06")
    assert len(_actions(root / "shioaji_stock_prices" / "data" / "corporate_actions.sqlite", "A")) == 1
    with gzip.open(next((output / "chunks").glob("episodes-*.json.gz")), "rt", encoding="utf-8") as handle:
        episodes = json.load(handle)
    assert episodes[0]["adjusted_start_close"] == 50
    assert episodes[0]["adjusted_peak_close"] == pytest.approx(103.68)
    assert episodes[0]["peak_date"] == "2019-01-06"
    validate_bundle(output)
    with chunks[0].open("ab") as handle:
        handle.write(b"corrupt")
    with pytest.raises(CatalogIOError, match="hash"):
        validate_bundle(output)
    with pytest.raises(CatalogIOError, match="already exists"):
        build_bundle(root, output, "one")


def _replace_chunk(output: Path, table: str, rows: list[dict], *, refresh_receipt: bool = False) -> None:
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk = next(item for item in manifest["chunks"] if item["table"] == table)
    target = output / chunk["path"]
    with target.open("wb") as handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as zipped:
            zipped.write(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    chunk["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    receipt = output / "completion-receipt.json"
    if refresh_receipt:
        canonical_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        receipt.write_text(
            json.dumps({"run_id": manifest["run_id"], "manifest_canonical_sha256": canonical_hash, "counts": manifest["counts"]}, sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )
    else:
        receipt.unlink()


def test_qualifying_wave_includes_no_bars_peer_and_validator_rejects_semantic_tamper(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    output = root / "tasks" / "20261002-sector-wave-catalog" / "runs" / "wave"
    manifest = build_bundle(root, output, "wave")
    assert manifest["counts"]["waves"] == 1
    assert (output / "completion-receipt.json").is_file()
    wave_chunk = next(output / item["path"] for item in manifest["chunks"] if item["table"] == "waves")
    peer_chunk = next(output / item["path"] for item in manifest["chunks"] if item["table"] == "peers")
    with gzip.open(wave_chunk, "rt", encoding="utf-8") as handle:
        wave = json.load(handle)[0]
    with gzip.open(peer_chunk, "rt", encoding="utf-8") as handle:
        peers = json.load(handle)
    assert wave["winner_security_id"] == "TW:A"
    assert next(peer for peer in peers if peer["security_id"] == "TW:C")["null_reason"] == "no_bars"
    validate_bundle(output)
    wave["winner_security_id"] = "TW:C"
    _replace_chunk(output, "waves", [wave])
    with pytest.raises(CatalogIOError, match="invalid wave winner"):
        validate_bundle(output)


def test_price_adapter_uses_raw_turnover_and_permanent_layer_without_cash_window(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "Code": ["A", "A"],
        "Date": pd.to_datetime(["2019-01-02", "2019-01-03"]),
        "Open": [100, 50],
        "High": [100, 50],
        "Low": [100, 50],
        "Close": [100, 50],
        "Volume": [2, 3],
    })
    actions = pd.DataFrame({
        "Code": ["A"],
        "Date": pd.to_datetime(["2019-01-03"]),
        "event_type": ["CASH_DIVIDEND"],
        "price_factor": [0.5],
        "previous_close": [100],
    })
    bars, _ = _bars_for_code(frame, actions, DataLoader(tmp_path))
    assert [bar.close for bar in bars] == [100, 50]
    assert [bar.turnover_k_twd for bar in bars] == [200, 150]


def test_action_adapter_filters_bad_factors_and_accepts_numeric_factor_text(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "Code": ["A", "A"],
        "Date": pd.to_datetime(["2019-01-02", "2019-01-03"]),
        "Open": [100, 60],
        "High": [100, 60],
        "Low": [100, 60],
        "Close": [100, 60],
        "Volume": [1, 1],
    })
    unusable = pd.DataFrame({
        "Code": ["A", "A", "A"],
        "Date": pd.to_datetime(["2019-01-03"] * 3),
        "event_type": ["ETF_SPLIT", "ETF_SPLIT", "UNKNOWN"],
        "price_factor": [float("inf"), "not-a-number", "0.5"],
        "previous_close": [None, None, "100"],
    })
    bars, findings = _bars_for_code(frame, unusable, DataLoader(tmp_path))
    assert [bar.close for bar in bars] == [100, 60]
    assert all(bar.close != float("inf") for bar in bars)
    assert sum(item["reason"] == "unsupported_action_factor" for item in findings) == 3
    numeric_text = pd.DataFrame({
        "Code": ["A"],
        "Date": pd.to_datetime(["2019-01-03"]),
        "event_type": ["ETF_SPLIT"],
        "price_factor": [".5"],
        "previous_close": ["100"],
    })
    adjusted, findings = _bars_for_code(frame, numeric_text, DataLoader(tmp_path))
    assert [bar.close for bar in adjusted] == [50, 60]
    assert not any(item["reason"] == "unsupported_action_factor" for item in findings)


def test_invalid_and_duplicate_dates_flag_the_affected_interval(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "Code": ["A"] * 4,
        "Date": pd.to_datetime(["2019-01-02", "2019-01-03", "2019-01-04", "2019-01-04"]),
        "Open": [10, 10, 11, 12],
        "High": [10, 10, 11, 12],
        "Low": [10, 10, 11, 12],
        "Close": [10, float("nan"), 11, 12],
        "Volume": [1] * 4,
    })
    actions = pd.DataFrame({
        "Date": pd.Series(dtype="datetime64[ns]"),
        "event_type": pd.Series(dtype=str),
        "price_factor": pd.Series(dtype=float),
        "previous_close": pd.Series(dtype=float),
    })
    bars, _ = _bars_for_code(frame, actions, DataLoader(tmp_path))
    assert bars[0].quality_flags == ()
    assert set(bars[1].quality_flags) == {"duplicate_date", "invalid_price_removed"}


def test_input_hash_normalizes_text_newlines_but_retains_raw_byte_identity(tmp_path: Path) -> None:
    lf = tmp_path / "lf.txt"
    crlf = tmp_path / "crlf.txt"
    binary = tmp_path / "binary.bin"
    lf.write_bytes(b"one\ntwo\n")
    crlf.write_bytes(b"one\r\ntwo\r\n")
    binary.write_bytes(b"one\r\ntwo\r\n")
    assert _input_sha("mission", lf) == _input_sha("mission", crlf)
    crlf.write_bytes(b"one\r\nthree\r\n")
    assert _input_sha("mission", lf) != _input_sha("mission", crlf)
    assert _input_sha("price", lf) != _input_sha("price", binary)
    assert _sha(lf) != _sha(binary)


@pytest.mark.parametrize("invalid_close", [float("nan"), float("inf"), 0.0, -1.0])
def test_tail_invalid_price_quarantines_right_censored_episode_and_peer(tmp_path: Path, invalid_close: float) -> None:
    valid = [10.0, 12.0, 14.4, 17.28, 20.736]
    frame = pd.DataFrame({
        "Code": ["A"] * 6,
        "Date": pd.to_datetime(["2019-01-02", "2019-01-03", "2019-01-04", "2019-01-07", "2019-01-08", "2019-01-09"]),
        "Open": valid + [0],
        "High": valid + [0],
        "Low": valid + [0],
        "Close": valid + [invalid_close],
        "Volume": [1] * 6,
    })
    actions = pd.DataFrame({
        "Date": pd.Series(dtype="datetime64[ns]"),
        "event_type": pd.Series(dtype=str),
        "price_factor": pd.Series(dtype=float),
        "previous_close": pd.Series(dtype=float),
    })
    bars, _ = _bars_for_code(frame, actions, DataLoader(tmp_path))
    assert bars[-1].quality_flags == ("invalid_price_removed",)
    episode = detect_episodes("A", bars)[0]
    assert episode["right_censored"] is True
    assert episode["quality_flags"] == ("invalid_price_removed",)
    peer = compare_peer("wave", "TW:A", bars, episode["start_date"], "2019-01-09")
    assert peer["comparability_status"] == "quarantined"
    assert select_wave_winner([peer]) is None


def _read_table(output: Path, manifest: dict, table: str) -> list[dict]:
    chunk = next(item for item in manifest["chunks"] if item["table"] == table)
    with gzip.open(output / chunk["path"], "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _add_window_issue_prices(root: Path) -> None:
    data = root / "shioaji_stock_prices" / "data"
    prices = pd.read_parquet(data / "price_daily.parquet")
    extra = pd.DataFrame({
        "Code": ["A", "A", "A", "C", "C", "C", "C", "C", "C", "C"],
        "Date": pd.to_datetime([
            "2019-01-07",
            "2019-01-09",
            "2019-01-10",
            "2019-01-02",
            "2019-01-03",
            "2019-01-04",
            "2019-01-07",
            "2019-01-08",
            "2019-01-09",
            "2019-01-10",
        ]),
        "Open": [124.416, 0, 124.416, 20, 24, 28.8, 34.56, 41.472, 48, 34],
        "High": [124.416, 0, 124.416, 20, 24, 28.8, 34.56, 41.472, 48, 34],
        "Low": [124.416, 0, 124.416, 20, 24, 28.8, 34.56, 41.472, 48, 34],
        "Close": [124.416, float("nan"), 124.416, 20, 24, 28.8, 34.56, 41.472, 48, 34],
        "Volume": [1] * 10,
        "Source": ["official"] * 10,
    })
    pd.concat([prices, extra], ignore_index=True).to_parquet(data / "price_daily.parquet")


def test_bundle_window_quality_finding_quarantines_peer_without_backdating_outside_window(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _add_window_issue_prices(root)
    output = root / "tasks" / "20261002-sector-wave-catalog" / "runs" / "path-quality"
    manifest = build_bundle(root, output, "path-quality")
    waves = _read_table(output, manifest, "waves")
    peers = _read_table(output, manifest, "peers")
    assert len(waves) == 1
    assert waves[0]["winner_security_id"] == "TW:C"
    a_peer = next(peer for peer in peers if peer["security_id"] == "TW:A")
    assert a_peer["comparability_status"] == "quarantined"
    assert "invalid_price_removed" in a_peer["quality_flags"]
    assert a_peer["actual_end_date"] == "2019-01-07"
    assert select_wave_winner([a_peer]) is None
    findings = [{"date": "2019-01-09", "reason": "invalid_price_or_volume"}]
    assert _path_quality_flags(findings, "2019-01-11", "2019-01-12") == ()


@pytest.mark.parametrize(
    ("case", "expected_error"),
    [
        ("quarantined_missing_flag", "peer missing quality flags"),
        ("unavailable_missing_flag", "peer missing quality flags"),
        ("quality_marked_comparable", "quality peer marked comparable"),
    ],
)
def test_validator_rejects_quality_peer_tampering_after_hash_and_receipt_refresh(tmp_path: Path, case: str, expected_error: str) -> None:
    root = _repo(tmp_path)
    if case == "unavailable_missing_flag":
        data = root / "shioaji_stock_prices" / "data"
        prices = pd.read_parquet(data / "price_daily.parquet")
        invalid_c = pd.DataFrame({
            "Code": ["C"],
            "Date": pd.to_datetime(["2019-01-03"]),
            "Open": [0],
            "High": [0],
            "Low": [0],
            "Close": [float("nan")],
            "Volume": [1],
            "Source": ["official"],
        })
        pd.concat([prices, invalid_c], ignore_index=True).to_parquet(data / "price_daily.parquet")
    else:
        _add_window_issue_prices(root)
    output = root / "tasks" / "20261002-sector-wave-catalog" / "runs" / case
    manifest = build_bundle(root, output, case)
    peers = _read_table(output, manifest, "peers")
    peer = next(peer for peer in peers if peer["security_id"] == ("TW:C" if case == "unavailable_missing_flag" else "TW:A"))
    assert peer["quality_flags"]
    if case == "quality_marked_comparable":
        assert peer["common_window_endpoint_appreciation_fraction"] is not None
        peer["comparability_status"] = "comparable"
    else:
        if case == "unavailable_missing_flag":
            assert peer["common_window_endpoint_appreciation_fraction"] is None
        peer["quality_flags"] = []
    _replace_chunk(output, "peers", peers, refresh_receipt=True)
    with pytest.raises(CatalogIOError, match=expected_error):
        validate_bundle(output)
