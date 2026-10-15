"""Fixed-input preparation and profiling with invented snapshots and workers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pyarrow.parquet as pq
import pytest

from research_core import pattern_scan_pipeline_v1 as pipeline
from research_core.artifact_store import canonical, file_digest, read_json
from research_core.pattern_scan_inputs_v1 import ScanSnapshot
from research_core.research_data_paths import DataRoots


@dataclass
class FakeSnapshot:
    roots: DataRoots
    inventory: pd.DataFrame
    calendar: pd.DatetimeIndex
    prices: pd.DataFrame
    actions: pd.DataFrame
    input_id: str = "invented-input.v1"
    manifest_sha256: str = "invented-manifest-pin"
    changed: bool = False
    stock_calls: int = 0

    def verify_after(self) -> None:
        if self.changed:
            raise ValueError("fixed input changed")

    def stock(self, code: str) -> pd.DataFrame:
        self.stock_calls += 1
        return pd.DataFrame({"Close": [10.0, 11.0, 12.0]}, index=self.calendar)


@pytest.fixture
def snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeSnapshot:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    roots = DataRoots(primary, primary / "research_data")
    inventory = pd.DataFrame({"code": ["0001", "0020", "0050"], "included": [True, True, False], "industry_ref": ["invented-a", "invented-b", "excluded"]})
    calendar = pd.date_range("2020-01-01", periods=3)

    def source_check(source: dict[str, Any]) -> None:
        if source != {"source_id": "fixed-synthetic-source"}:
            raise ValueError("fixed source changed")

    monkeypatch.setattr(pipeline, "verify_source", source_check)
    return FakeSnapshot(roots, inventory, calendar, pd.DataFrame(), pd.DataFrame(columns=pd.Index(["code"])))


SOURCE = {"source_id": "fixed-synthetic-source"}


def _prepare(
    snapshot: FakeSnapshot, *, codes: tuple[str, ...] = ("0020", "0001"), source: dict[str, Any] | None = None, authorized: bool = True
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    run = snapshot.roots.primary / ".tmp" / "pattern-scan-execution" / "invented-run"
    return pipeline.prepare_requests(cast(ScanSnapshot, snapshot), codes, SOURCE if source is None else source, run, calculation_authorized=authorized)


def test_prepare_authority_and_ordinary_reference_only(snapshot: FakeSnapshot) -> None:
    with pytest.raises(PermissionError, match="authorization"):
        _prepare(snapshot, authorized=False)
    for codes in (("0050",), ("unknown",), ("0001", "0001"), ()):
        with pytest.raises(ValueError):
            _prepare(snapshot, codes=codes)
    assert snapshot.stock_calls == 0
    assert not (snapshot.roots.primary / ".tmp").exists()


def test_exact_resume_preserves_prepared_bytes_mtime_and_calls(snapshot: FakeSnapshot) -> None:
    requests, measurement = _prepare(snapshot)
    assert [row["code"] for row in requests] == ["0001", "0020"]
    assert all(row["calculation_authorized"] is True for row in requests)
    assert measurement["wall_seconds"] >= 0
    paths = [Path(row["prepared_path"]) for row in requests]
    for path in paths:
        metadata = pq.read_metadata(path)
        codecs = {
            metadata.row_group(row).column(column).compression
            for row in range(metadata.num_row_groups)
            for column in range(metadata.row_group(row).num_columns)
        }
        assert codecs == {"ZSTD"}
        pd.testing.assert_frame_equal(
            pd.read_parquet(path),
            pd.DataFrame({"Close": [10.0, 11.0, 12.0]}, index=snapshot.calendar),
            check_exact=True,
            check_freq=False,
        )
    before = {str(path): (file_digest(path), path.stat().st_mtime_ns) for path in paths}
    calls = snapshot.stock_calls
    repeated, _ = _prepare(snapshot)
    assert repeated == requests and snapshot.stock_calls == calls
    assert before == {str(path): (file_digest(path), path.stat().st_mtime_ns) for path in paths}


@pytest.mark.parametrize("damage", ("missing_receipt", "invalid_json", "identity", "payload", "schema", "manifest", "rows"))
def test_missing_or_corrupt_prepared_resume_fails(snapshot: FakeSnapshot, damage: str) -> None:
    requests, _ = _prepare(snapshot)
    path = Path(requests[0]["prepared_path"])
    receipt = path.with_suffix(".json")
    if damage == "missing_receipt":
        receipt.unlink()
    elif damage == "invalid_json":
        receipt.write_text("{", encoding="utf-8")
    elif damage == "identity":
        body = read_json(receipt)
        body["identity"]["input_id"] = "other-input"
        receipt.write_bytes(canonical(body))
    elif damage == "payload":
        path.write_bytes(b"changed invented prepared bytes")
    else:
        body = read_json(receipt)
        key, value = {"schema": ("schema", "wrong-schema"), "manifest": ("input_manifest_sha256", "changed-pin"), "rows": ("rows", 4)}[damage]
        body[key] = value
        receipt.write_bytes(canonical(body))
    calls = snapshot.stock_calls
    with pytest.raises((ValueError, FileNotFoundError)):
        _prepare(snapshot)
    assert snapshot.stock_calls == calls


def test_source_or_input_drift_stops_preparation(snapshot: FakeSnapshot) -> None:
    with pytest.raises(ValueError, match="source changed"):
        _prepare(snapshot, source={"source_id": "changed"})
    snapshot.changed = True
    with pytest.raises(ValueError, match="input changed"):
        _prepare(snapshot)
    assert snapshot.stock_calls == 0


def _profile_worker(packets: list[dict[str, Any]], **limits: Any) -> dict[str, Any]:
    workers = limits["workers"]
    results = [
        {
            "code": row["code"],
            "artifacts": [{"path": "invented.parquet", "sha256": file_digest(Path(row["prepared_path"]))}],
            "rows": {"prices": 3},
            "measurements": [{"phase": name, "wall_seconds": 0.25} for name in ("load_prepared", "stock_calculation", "serialize")],
        }
        for row in packets
    ]
    return {
        "workers": workers,
        "coordinator_measurement": {"wall_seconds": {1: 6.0, 2: 3.0, 4: 4.0}[workers]},
        "workers_receipts": [{"job_memory": {"peak_committed_bytes": 100_000}, "measurement": {"wall_seconds": 2.0}, "results": results}],
        "results": results,
    }


def test_profile_measures_same_inputs_and_selects_finite_config(snapshot: FakeSnapshot, monkeypatch: pytest.MonkeyPatch) -> None:
    requests, _ = _prepare(snapshot)
    calls: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []

    def worker(packets: list[dict[str, Any]], **limits: Any) -> dict[str, Any]:
        calls.append((packets, limits))
        return _profile_worker(packets, **limits)

    monkeypatch.setattr(pipeline, "run_requests", worker)
    result = pipeline.profile_requests(requests, memory_bytes=1_000_000, estimated_worker_bytes=100_000, stocks_per_process=2, timeout_seconds=60)
    assert [limits["workers"] for _, limits in calls] == [1, 2, 4]
    assert len({packets[0]["run_root"] for packets, _ in calls}) == 3
    for packets, limits in calls:
        assert limits["timeout_seconds"] == 60 and limits["stocks_per_process"] == 2
        for original, copied in zip(requests, packets, strict=True):
            assert original["prepared_path"] != copied["prepared_path"]
            assert file_digest(Path(copied["prepared_path"])) == original["prepared_sha256"]
    assert result["same_file_identities"] is True
    selected = result["selected"]
    assert selected["workers"] == selected["inflight_processes"] == 2
    assert selected["memory_cap_bytes"] == 1_000_000
    assert selected["estimated_worker_bytes"] == 125_000
    assert selected["observed_peak_job_committed_bytes"] == 100_000


@pytest.mark.parametrize("damage", ("hash", "rows", "code"))
def test_profile_rejects_serial_parallel_identity_mismatch(snapshot: FakeSnapshot, monkeypatch: pytest.MonkeyPatch, damage: str) -> None:
    requests, _ = _prepare(snapshot)

    def worker(packets: list[dict[str, Any]], **limits: Any) -> dict[str, Any]:
        receipt = _profile_worker(packets, **limits)
        if limits["workers"] == 2:
            row = receipt["results"][0]
            if damage == "hash":
                row["artifacts"][0]["sha256"] = "changed"
            elif damage == "rows":
                row["rows"]["prices"] = 4
            else:
                row["code"] = "other-code"
        return receipt

    monkeypatch.setattr(pipeline, "run_requests", worker)
    with pytest.raises(ValueError, match="identities or integer rows differ"):
        pipeline.profile_requests(requests, memory_bytes=1_000_000, estimated_worker_bytes=100_000)


def test_representatives_use_internal_gaps_not_listing_or_truncated_slots(snapshot: FakeSnapshot) -> None:
    snapshot.calendar = pd.date_range("2010-01-04", periods=10)
    snapshot.inventory = pd.DataFrame({"code": ["long", "new", "gap", "tail", "actions"], "included": True, "industry_ref": "invented"})
    dates = {
        "long": list(snapshot.calendar),
        "new": list(snapshot.calendar[-3:]),
        "gap": [snapshot.calendar[i] for i in (0, 1, 5, 9)],
        "tail": list(snapshot.calendar[:3]),
        "actions": list(snapshot.calendar),
    }
    # A new listing after 2019 belongs to the same much longer common calendar.
    snapshot.calendar = pd.DatetimeIndex(snapshot.calendar.append(pd.date_range("2020-01-01", periods=3)))
    dates["new"] = list(snapshot.calendar[-3:])
    dates["long"] = dates["actions"] = list(snapshot.calendar)
    snapshot.prices = pd.DataFrame([{"Code": code, "Date": day} for code, rows in dates.items() for day in rows])
    snapshot.actions = pd.DataFrame({"code": ["actions", "actions"]})
    codes, strata = pipeline.representative_codes(cast(ScanSnapshot, snapshot))
    assert strata["new_listing"] == "new"
    assert strata["missing_calendar_slots"] == "gap"
    assert strata["truncated_tail"] == "tail"
    assert strata["corporate_actions"] == "actions"
    assert strata["long_history"] in {"long", "actions"}
    assert set(codes) == {code for code in strata.values() if code is not None}


def test_unavailable_representative_strata_are_explicit_unknown(snapshot: FakeSnapshot) -> None:
    snapshot.calendar = pd.date_range("2010-01-04", periods=3)
    snapshot.inventory = pd.DataFrame({"code": ["long"], "included": [True], "industry_ref": ["invented"]})
    snapshot.prices = pd.DataFrame({"Code": "long", "Date": snapshot.calendar})
    codes, strata = pipeline.representative_codes(cast(ScanSnapshot, snapshot))
    assert codes == ("long",)
    assert strata == {
        "long_history": "long",
        "new_listing": None,
        "missing_calendar_slots": None,
        "corporate_actions": None,
        "truncated_tail": None,
        "middle_history": "long",
    }
    snapshot.prices = snapshot.prices.iloc[1:]
    with pytest.raises(ValueError, match="long-history"):
        pipeline.representative_codes(cast(ScanSnapshot, snapshot))


def test_profile_no_measured_mode_fits_boosted_memory_estimate(snapshot: FakeSnapshot, monkeypatch: pytest.MonkeyPatch) -> None:
    requests, _ = _prepare(snapshot)
    monkeypatch.setattr(pipeline, "run_requests", _profile_worker)
    with pytest.raises(ValueError, match="memory"):
        pipeline.profile_requests(requests, memory_bytes=120_000, estimated_worker_bytes=100_000)
