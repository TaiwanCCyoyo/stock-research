"""Fixed input identity, canonical handoff and S6 daily eligibility probes."""

import gzip
import hashlib
import json
import sqlite3
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core import pattern_scan_inputs_v1 as scan_inputs
from research_core.artifact_store import canonical, file_digest, object_digest
from research_core.pattern_scan_inputs_v1 import ROLES, TASK, daily_qualification, handoff_inputs, load_snapshot
from research_core.research_data_paths import DataRoots


def bundle(tmp_path: Path) -> tuple[DataRoots, Path, Path]:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    roots = DataRoots(primary, primary / "research_data")
    source = tmp_path / "source"
    inputs = source / "tasks" / TASK / "inputs" / "observed-v1"
    inputs.mkdir(parents=True)
    dates = ["2010-01-04", "2010-01-05", "2026-10-12"]
    rows = [
        (code, day, 10.0, 11.0, 9.0, 10.0, 100.0, provider)
        for code, provider in (("1101", "official"), ("0050", "official"), ("9999", "shioaji"))
        for day in pd.to_datetime(dates)
    ]
    pd.DataFrame(rows, columns=pd.Index(["Code", "Date", "Open", "High", "Low", "Close", "Volume", "Source"])).to_parquet(inputs / ROLES[0], index=False)
    with sqlite3.connect(inputs / "symbol_meta.sqlite") as connection:
        pd.DataFrame([
            {
                "code": "1101",
                "name": "Synthetic",
                "market": "TWSE",
                "security_category": "股票",
                "is_etf": 0,
                "industry_category": "test",
                "fetched_at": "2026-10-12",
            },
            {
                "code": "0050",
                "name": "Synthetic ETF",
                "market": "TWSE",
                "security_category": "ETF",
                "is_etf": 1,
                "industry_category": None,
                "fetched_at": "2026-10-12",
            },
            {
                "code": "9999",
                "name": "No official",
                "market": "TWSE",
                "security_category": "股票",
                "is_etf": 0,
                "industry_category": "test",
                "fetched_at": "2026-10-12",
            },
        ]).to_sql("symbol_meta", connection, index=False)
    with sqlite3.connect(inputs / "corporate_actions.sqlite") as connection:
        pd.DataFrame({
            "code": pd.Series(dtype=str),
            "ex_date": pd.Series(dtype=str),
            "event_type": pd.Series(dtype=str),
            "price_factor": pd.Series(dtype=float),
        }).to_sql("corporate_actions", connection, index=False)
    for name in ROLES[3:]:
        (inputs / name).write_bytes(b"{}")
    records = [
        {
            "role": role,
            "snapshot_path": f"tasks/{TASK}/inputs/observed-v1/{role}",
            "snapshot_sha256": file_digest(inputs / role),
            "snapshot_bytes": (inputs / role).stat().st_size,
        }
        for role in ROLES
    ]
    pins = {"cutoff": "2026-10-12", "frozen_inputs": {"records": records}, "price_observation": {"calendar": {"dates": dates, "sha256": object_digest(dates)}}}
    pins_path = source / "pins.json.gz"
    pins_path.write_bytes(gzip.compress(canonical(pins), mtime=0))
    return roots, source, pins_path


def test_physical_handoff_verified_reuse_and_full_calendar_reader(tmp_path: Path) -> None:
    roots, source, pins = bundle(tmp_path)
    destination = handoff_inputs(roots, source, pins)
    identity = file_digest(destination / "manifest.json")
    assert handoff_inputs(roots, source, pins) == destination
    snapshot = load_snapshot(roots, manifest_sha256=identity)
    assert snapshot.calendar.strftime("%Y-%m-%d").tolist() == ["2010-01-04", "2010-01-05", "2026-10-12"]
    assert snapshot.inventory.loc[snapshot.inventory["included"], "code"].tolist() == ["1101"]
    assert set(snapshot.prices["Code"]) == {"0050", "1101"}
    assert snapshot.stock("1101")["Close"].tolist() == [10.0, 10.0, 10.0]
    assert snapshot.stock("0050")["Close"].tolist() == [10.0, 10.0, 10.0]
    with pytest.raises(ValueError, match="outside"):
        snapshot.stock("9999")
    for name in ROLES:
        target = destination / name
        original = source / "tasks" / TASK / "inputs" / "observed-v1" / name
        assert target.read_bytes() == original.read_bytes()
        assert target.stat().st_nlink == 1 and not target.is_symlink()
    snapshot.verify_after()


def test_stale_source_and_existing_canonical_bundle_fail_closed(tmp_path: Path) -> None:
    roots, source, pins = bundle(tmp_path)
    original = source / "tasks" / TASK / "inputs" / "observed-v1" / ROLES[-1]
    original.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        handoff_inputs(roots, source, pins)
    assert not (roots.primary / "tasks" / TASK / "inputs" / "observed-v1").exists()


def test_mid_read_identity_changes_and_sidecars_rejected(tmp_path: Path) -> None:
    roots, source, pins = bundle(tmp_path)
    target = handoff_inputs(roots, source, pins)
    identity = file_digest(target / "manifest.json")
    with pytest.raises(ValueError, match="identity"):
        load_snapshot(roots, manifest_sha256="0" * 64)
    snapshot = load_snapshot(roots, manifest_sha256=identity)
    Path(str(target / "symbol_meta.sqlite") + "-wal").write_bytes(b"")
    with pytest.raises(ValueError, match="sidecar"):
        snapshot.verify_after()
    with pytest.raises(ValueError, match="sidecar"):
        handoff_inputs(roots, source, pins)


def test_calendar_hash_path_traversal_and_manifest_mismatch(tmp_path: Path) -> None:
    roots, source, pins = bundle(tmp_path)
    value = json.loads(gzip.decompress(pins.read_bytes()))
    value["frozen_inputs"]["records"][0]["snapshot_path"] = "tasks/../secret"
    pins.write_bytes(gzip.compress(canonical(value)))
    with pytest.raises(ValueError, match="unsafe"):
        handoff_inputs(roots, source, pins)
    roots, source, pins = bundle(tmp_path / "second")
    target = handoff_inputs(roots, source, pins)
    value = json.loads((target / "manifest.json").read_bytes())
    value["calendar"]["sha256"] = "0" * 64
    (target / "manifest.json").write_bytes(canonical(value))
    with pytest.raises(ValueError, match="calendar identity"):
        load_snapshot(roots, manifest_sha256=file_digest(target / "manifest.json"))
    with pytest.raises(ValueError, match="identity mismatch"):
        handoff_inputs(roots, source, pins)


def test_s6_qualifies_per_day_at_exact_turnover_and_recovers_after_gap() -> None:
    data = pd.DataFrame({"Quality": True, "VolumeLots": 100.0, "RawClose": 10.0}, index=pd.date_range("2020-01-01", periods=150))
    result = daily_qualification(data, ordinary_reference=True)
    assert not result.base_eligible.iloc[:59].any() and result.base_eligible.iloc[59:].all()
    # Current enormous turnover cannot rescue a low prior twenty-day mean.
    low = data.copy()
    low.loc[low.index[:60], "VolumeLots"] = 99.0
    low.loc[low.index[60], "VolumeLots"] = 100000.0
    assert not daily_qualification(low, ordinary_reference=True).base_eligible.iloc[60]
    gap = data.copy()
    gap.loc[gap.index[70], "Quality"] = False
    recovered = daily_qualification(gap, ordinary_reference=True)
    assert not recovered.base_eligible.iloc[70:130].any() and recovered.base_eligible.iloc[130]
    zero = data.copy()
    zero.loc[zero.index[65], "VolumeLots"] = 0.0
    assert not daily_qualification(zero, ordinary_reference=True).base_eligible.iloc[65]
    missing = data.copy()
    missing.loc[missing.index[65], "RawClose"] = np.nan
    assert not daily_qualification(missing, ordinary_reference=True).base_eligible.iloc[66:86].any()
    assert not daily_qualification(data, ordinary_reference=False).base_eligible.any()


def test_snapshot_verifies_the_parquet_buffer_and_consumed_sqlite_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    roots, source, pins = bundle(tmp_path)
    target = handoff_inputs(roots, source, pins)
    parquet_hashes: list[str] = []
    sqlite_hashes: list[str] = []
    original_read = scan_inputs.pd.read_parquet
    original_connect = sqlite3.connect

    def read_verified_buffer(buffer: BytesIO, **kwargs: Any) -> pd.DataFrame:
        assert isinstance(buffer, BytesIO)
        parquet_hashes.append(hashlib.sha256(buffer.getvalue()).hexdigest())
        return original_read(buffer, **kwargs)

    class ObservedConnection(sqlite3.Connection):
        def serialize(self, *, name: str = "main") -> bytes:
            raw = super().serialize(name=name)
            sqlite_hashes.append(hashlib.sha256(raw).hexdigest())
            return raw

    def observed_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return original_connect(*args, factory=ObservedConnection, **kwargs)

    monkeypatch.setattr(scan_inputs.pd, "read_parquet", read_verified_buffer)
    monkeypatch.setattr(scan_inputs.sqlite3, "connect", observed_connect)
    snapshot = load_snapshot(roots, manifest_sha256=file_digest(target / "manifest.json"))
    assert parquet_hashes == [file_digest(target / "price_daily.parquet")]
    assert set(sqlite_hashes) == {file_digest(target / "symbol_meta.sqlite"), file_digest(target / "corporate_actions.sqlite")}
    assert len(sqlite_hashes) == 2 and set(snapshot.prices.Code) == {"0050", "1101"}
    for role in ROLES:
        assert file_digest(target / role) == file_digest(source / "tasks" / TASK / "inputs" / "observed-v1" / role)


def test_changed_consumed_parquet_buffer_is_rejected_before_decode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    roots, source, pins = bundle(tmp_path)
    target = handoff_inputs(roots, source, pins)
    price = target / "price_daily.parquet"
    expected = file_digest(price)
    original_read = Path.read_bytes

    def corrupt_buffer(path: Path) -> bytes:
        raw = original_read(path)
        return raw[:-1] + bytes([raw[-1] ^ 1]) if path == price else raw

    def refuse_decode(*args: object, **kwargs: object) -> pd.DataFrame:
        raise AssertionError("changed consumed buffer must not reach the decoder")

    monkeypatch.setattr(Path, "read_bytes", corrupt_buffer)
    monkeypatch.setattr(scan_inputs.pd, "read_parquet", refuse_decode)
    with pytest.raises(ValueError, match="consumed.*price_daily.parquet"):
        load_snapshot(roots, manifest_sha256=file_digest(target / "manifest.json"))
    assert file_digest(price) == expected


def test_changed_consumed_sqlite_image_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    roots, source, pins = bundle(tmp_path)
    target = handoff_inputs(roots, source, pins)
    metadata = target / "symbol_meta.sqlite"
    expected = file_digest(metadata)
    original_connect = sqlite3.connect

    class CorruptedImage(sqlite3.Connection):
        def serialize(self, *, name: str = "main") -> bytes:
            return super().serialize(name=name) + b"changed"

    def corrupt_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return original_connect(*args, factory=CorruptedImage, **kwargs)

    monkeypatch.setattr(scan_inputs.sqlite3, "connect", corrupt_connect)
    with pytest.raises(ValueError, match="consumed.*symbol_meta.sqlite"):
        load_snapshot(roots, manifest_sha256=file_digest(target / "manifest.json"))
    assert file_digest(metadata) == expected
