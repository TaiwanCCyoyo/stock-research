"""Behavioral evidence tests: immutable inputs, partial sales, claims, and unknowns."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, Lock, Thread, local
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api.saved_research_studio import create_studio_router
from research_core import saved_research_studio as studio_core
from research_core.saved_research_studio import (
    MAX_PART_BYTES,
    SCHEMA,
    TRANSPORT_SCHEMA,
    SavedResearchStudio,
    StudioError,
    _catalog_benchmark,
    _catalog_display_names,
    _frozen_candles,
    _security_name,
    account_audit,
    build_run,
    read_studio_package,
    read_verified,
    research_history,
    synthetic_studio_package,
    valid_day,
    write_split_package,
)


def test_request_mode_mismatch_rejects_before_reading_private_package(tmp_path: Path) -> None:
    for package, requested in [(tmp_path / "missing.manifest.json", "public-synthetic"), (None, "local-private")]:
        app = FastAPI()
        app.include_router(create_studio_router(package, history_presentation_path=None))
        response = TestClient(app).get("/saved-research-studio/v1/runs", headers={"X-Research-Data-Mode": requested})
        assert response.status_code == 503
        assert response.headers["X-Research-Evidence-Error"] == "unavailable"
        assert "mode mismatch" in response.json()["detail"]


def evidence() -> tuple[dict, dict, list, list, dict]:
    run_id = "stock:test:normal"
    originals = [
        {"action": "BUY", "code": "2330", "date": "2020-01-01T09:00:00+08:00", "qty": 10, "price": 10, "total": -100, "order_id": "BUY-1"},
        {"action": "SELL", "code": "2330", "date": "2020-01-02T09:00:00+08:00", "qty": 4, "price": 15, "total": 60, "order_id": "SELL-1"},
        {"action": "DIVIDEND_ENTITLEMENT", "code": "2330", "date": "2020-01-02T10:00:00+08:00", "qualified_qty": 6, "entitlement_id": "div-1", "total": 0},
        {"action": "SPLIT", "code": "2330", "date": "2020-01-02T11:00:00+08:00", "qty": 6, "total": 0},
        {"action": "SELL", "code": "2330", "date": "2020-01-03T09:00:00+08:00", "qty": 12, "price": 20, "total": 240, "order_id": "SELL-2"},
        {"action": "BUY", "code": "2330", "date": "2020-01-03T10:00:00+08:00", "qty": 10, "price": 10, "total": -100, "order_id": "BUY-2"},
        {"action": "DIVIDEND", "code": "2330", "date": "2020-01-04T09:00:00+08:00", "entitlement_id": "div-1", "total": 6},
    ]
    events = [
        {
            "id": f"event-{i}",
            "date": e["date"],
            "action": e["action"],
            "code": e["code"],
            "quantity": e.get("qty"),
            "price": e.get("price"),
            "cashFlow": e["total"],
            "original": e,
        }
        for i, e in enumerate(originals)
    ]
    orders = [
        {"intent": {"order_id": e["order_id"], "code": e["code"], "side": e["action"], "decision_at": "2019-12-31T20:00:00+08:00"}, "lineage": None}
        for e in originals
        if "order_id" in e
    ]
    accounts = []
    equities = [1000, 1086, 1206, 1226]
    for i, (cash, qty, price, receivable) in enumerate([(900, 10, 10, 0), (960, 12, 10, 6), (1100, 10, 10, 6), (1106, 10, 12, 0)]):
        accounts.append({
            "date": f"2020-01-0{i + 1}T20:00:00+08:00",
            "cash_twd": cash,
            "tradable_positions": [
                {
                    "security_id": "2330",
                    "quantity": qty,
                    "raw_mark_twd": price,
                    "market_value_twd": qty * price,
                    "mark_quality": {"source_id": "frozen:abc", "modeled_mark": False, "observed_at": f"2020-01-0{i + 1}T13:30:00+08:00"},
                }
            ],
            "dividend_receivable_twd": receivable,
            "capital_return_receivable_twd": 0,
            "share_claims_value_twd": 0,
            "receivables": [],
            "share_claims": [],
        })
    run = {
        "id": run_id,
        "name": "保存案例",
        "from": "2020-01-01",
        "through": "2020-01-04",
        "initialCapital": 1000,
        "finalEquity": 1226,
        "netReturn": 0.226,
        "costs": 0,
        "method": {"status": "exploratory", "rules": ["一張試單"], "conclusion": "尚未採用", "parameters": {"final_strategy_approved": False}},
        "limitations": [],
        "nav": [{"date": f"2020-01-0{i + 1}", "equity": v} for i, v in enumerate(equities)],
        "events": events,
    }
    ledger = {"portfolio_id": run_id, "daily_states": accounts, "events": [{"source_event": event} for event in originals]}
    traces = [{"as_of": "2019-12-31T20:00:00+08:00", "unoccupied_top_five": [["2330", "whole_lot_affordable"]]}]
    candles = {
        code: [{"date": f"2020-01-0{i + 1}", "open": 10, "high": 12, "low": 9, "close": 10 + i, "sourceId": "frozen:abc"} for i in range(4)]
        for code in ["2330", "0050"]
    }
    return run, ledger, orders, traces, candles


def built() -> dict:
    return build_run(*evidence(), ["frozen:abc"])


def package(tmp_path: Path) -> tuple[Path, dict]:
    run = built()
    value = {"schema": SCHEMA, "runs": [run], "researchHistory": {"schema": "saved-research-history.v1", "historyComplete": False, "items": []}}
    path = tmp_path / "studio.json.gz"
    path.write_bytes(gzip.compress(json.dumps(value).encode()))
    return path, run


def split_package(tmp_path: Path) -> tuple[Path, dict, dict]:
    original, run = package(tmp_path)
    manifest_path = tmp_path / "studio.manifest.json"
    manifest = write_split_package(original.read_bytes(), manifest_path)
    return manifest_path, manifest, run


def replace_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_public_synthetic_studio_is_deterministic_and_does_not_read_private_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STOCK_RESEARCH_DATA_MODE", raising=False)
    monkeypatch.setenv("STOCK_SAVED_STUDIO_PACKAGE", "must-not-be-opened.manifest.json")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("synthetic mode must not access a private package or capture provider")

    monkeypatch.setattr(studio_core, "read_studio_package", forbidden)
    app = FastAPI()
    app.include_router(create_studio_router(capture_provider=forbidden))
    client = TestClient(app)
    result = client.get("/saved-research-studio/v1/runs").json()
    assert result["dataMode"] == "public-synthetic"
    assert result["synthetic"] is True
    assert len(result["runs"]) == 1
    run_id = result["runs"][0]["id"]
    detail = client.get("/saved-research-studio/v1/run", params={"run_id": run_id}).json()
    assert detail["positions"][0]["code"] == "demo-0-0"
    assert detail["reconciliation"]["verified"] is True
    assert detail["reconciliation"]["difference"] == 0
    history = client.get("/saved-research-studio/v1/research-history").json()
    assert history["synthetic"] is True and history["items"] == []
    assert synthetic_studio_package() == synthetic_studio_package()


def test_local_private_mode_reads_verified_external_split_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, manifest, run = split_package(tmp_path)
    original = {part["basename"]: (tmp_path / part["basename"]).read_bytes() for part in manifest["parts"]}
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")
    monkeypatch.setenv("STOCK_SAVED_STUDIO_PACKAGE", str(path.resolve()))
    app = FastAPI()
    app.include_router(create_studio_router(history_presentation_path=None))
    result = TestClient(app).get("/saved-research-studio/v1/runs")
    assert result.status_code == 200
    assert result.json()["dataMode"] == "local-private"
    assert result.json()["synthetic"] is False
    assert result.json()["runs"][0]["id"] == run["id"]
    assert all((tmp_path / basename).read_bytes() == payload for basename, payload in original.items())


@pytest.mark.parametrize("configured", [None, "missing.manifest.json"])
def test_local_private_missing_configuration_and_relative_path_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    configured: str | None,
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")
    if configured is None:
        monkeypatch.delenv("STOCK_SAVED_STUDIO_PACKAGE", raising=False)
    else:
        monkeypatch.setenv("STOCK_SAVED_STUDIO_PACKAGE", configured)
    app = FastAPI()
    app.include_router(create_studio_router())
    result = TestClient(app).get("/saved-research-studio/v1/runs")
    assert result.status_code == 503
    assert result.headers["X-Research-Evidence-Error"] == ("unavailable" if configured is None else "integrity")
    assert configured is None or configured not in result.text


@pytest.mark.parametrize("damage", ["missing", "tamper", "traversal"])
def test_local_private_external_transport_still_rejects_missing_tampered_and_unsafe_parts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    path, manifest, _ = split_package(tmp_path)
    part = tmp_path / manifest["parts"][0]["basename"]
    if damage == "missing":
        part.unlink()
    elif damage == "tamper":
        part.write_bytes(b"tampered")
    else:
        manifest["parts"][0]["basename"] = "../private-part.bin"
        replace_manifest(path, manifest)
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")
    monkeypatch.setenv("STOCK_SAVED_STUDIO_PACKAGE", str(path.resolve()))
    app = FastAPI()
    app.include_router(create_studio_router(history_presentation_path=None))
    result = TestClient(app).get("/saved-research-studio/v1/runs")
    assert result.status_code == 503
    assert result.headers["X-Research-Evidence-Error"] == ("unavailable" if damage == "missing" else "integrity")
    assert str(tmp_path) not in result.text


def test_split_transport_preserves_exact_gzip_bytes_and_large_package_content(tmp_path: Path) -> None:
    original, _ = package(tmp_path)
    value = read_studio_package(original)
    value["transportFixture"] = random.Random(7).randbytes(700_000).hex()
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    compressed = gzip.compress(raw, mtime=0)
    assert len(compressed) > MAX_PART_BYTES
    manifest_path = tmp_path / "studio.manifest.json"
    manifest = write_split_package(compressed, manifest_path)
    assert manifest["schema"] == TRANSPORT_SCHEMA
    assert len(manifest["parts"]) >= 2
    assert all(0 < part["bytes"] <= MAX_PART_BYTES for part in manifest["parts"])
    pieces = [(tmp_path / part["basename"]).read_bytes() for part in manifest["parts"]]
    assert b"".join(pieces) == compressed
    assert manifest["sha256"] == hashlib.sha256(compressed).hexdigest()
    assert read_studio_package(manifest_path) == value
    assert read_studio_package(original)["runs"] == value["runs"]


@pytest.mark.parametrize(
    "basename",
    [
        "../part.bin",
        "/part.bin",
        "D:/part.bin",
        "D:\\part.bin",
        "D:part.bin",
        "\\\\server\\part.bin",
        "sub/part.bin",
        "sub\\part.bin",
        "CON.bin",
        "nul",
        "part.bin.",
    ],
)
def test_split_transport_rejects_unsafe_windows_and_posix_part_paths(tmp_path: Path, basename: str) -> None:
    path, manifest, _ = split_package(tmp_path)
    manifest["parts"][0]["basename"] = basename
    replace_manifest(path, manifest)
    with pytest.raises(StudioError, match="basename|trailing-dot"):
        read_studio_package(path)


def test_split_transport_rejects_case_insensitive_duplicate_parts(tmp_path: Path) -> None:
    path, manifest, _ = split_package(tmp_path)
    duplicate = dict(manifest["parts"][0])
    duplicate["basename"] = duplicate["basename"].upper()
    manifest["parts"].append(duplicate)
    manifest["bytes"] *= 2
    replace_manifest(path, manifest)
    with pytest.raises(StudioError, match="duplicate"):
        read_studio_package(path)


def test_split_transport_rejects_corrupt_or_wrong_length_part(tmp_path: Path) -> None:
    path, manifest, _ = split_package(tmp_path)
    part_path = tmp_path / manifest["parts"][0]["basename"]
    original = part_path.read_bytes()
    part_path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(StudioError, match="part bytes/SHA-256"):
        read_studio_package(path)
    part_path.write_bytes(original[:-1])
    with pytest.raises(StudioError, match="part bytes/SHA-256"):
        read_studio_package(path)


def test_split_transport_verifies_whole_hash_after_valid_part_hashes(tmp_path: Path) -> None:
    path, manifest, _ = split_package(tmp_path)
    manifest["sha256"] = "0" * 64
    replace_manifest(path, manifest)
    with pytest.raises(StudioError, match="whole transport gzip"):
        read_studio_package(path)


def test_split_transport_missing_part_keeps_api_unavailable(tmp_path: Path) -> None:
    path, manifest, _ = split_package(tmp_path)
    (tmp_path / manifest["parts"][0]["basename"]).unlink()
    with pytest.raises(FileNotFoundError):
        read_studio_package(path)
    app = FastAPI()
    app.include_router(create_studio_router(path))
    response = TestClient(app).get("/saved-research-studio/v1/runs")
    assert response.status_code == 503
    assert response.headers["X-Research-Evidence-Error"] == "unavailable"
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize("corruption", ["manifest-json", "part-sha", "whole-sha", "transport-schema", "gzip", "package-schema", "nonfinite-json"])
def test_corrupt_package_returns_identifiable_503_without_source_path(tmp_path: Path, corruption: str) -> None:
    path, manifest, _ = split_package(tmp_path)
    if corruption == "manifest-json":
        path.write_bytes(b"{")
    elif corruption == "part-sha":
        part_path = tmp_path / manifest["parts"][0]["basename"]
        original = part_path.read_bytes()
        part_path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    elif corruption == "whole-sha":
        manifest["sha256"] = "0" * 64
        replace_manifest(path, manifest)
    elif corruption == "transport-schema":
        manifest["contentSchema"] = "unsupported.v2"
        replace_manifest(path, manifest)
    else:
        path = tmp_path / "corrupt.manifest.json"
        if corruption == "gzip":
            payload = b"\x1f\x8binvalid gzip stream"
        elif corruption == "package-schema":
            payload = gzip.compress(json.dumps({"schema": "unsupported.v2", "runs": []}).encode())
        else:
            payload = gzip.compress(json.dumps({"schema": SCHEMA, "runs": [], "invalid": float("nan")}).encode())
        write_split_package(payload, path)
    app = FastAPI()
    app.include_router(create_studio_router(path))
    client = TestClient(app)
    for endpoint in ["/runs", "/runs/unknown"]:
        response = client.get(f"/saved-research-studio/v1{endpoint}")
        assert response.status_code == 503
        assert response.headers["X-Research-Evidence-Error"] == "integrity"
        assert response.json()["detail"] == "策略證據包未通過完整性檢查，暫時無法讀取。"
        assert str(tmp_path) not in response.text


def test_api_reads_split_manifest_without_changing_run_evidence(tmp_path: Path) -> None:
    path, _, run = split_package(tmp_path)
    app = FastAPI()
    app.include_router(create_studio_router(path))
    client = TestClient(app)
    index = client.get("/saved-research-studio/v1/runs")
    assert index.status_code == 200
    assert index.json()["runs"][0]["id"] == run["id"]
    account = client.get(f"/saved-research-studio/v1/runs/{run['id']}/account", params={"date": "2020-01-04"})
    assert account.status_code == 200
    assert account.json()["verified"] is True
    assert account.json()["recordedEquity"] == 1226


@pytest.mark.parametrize(
    "field,changed",
    [
        ("bytes", 0),
        ("bytes", True),
        ("bytes", studio_core.MAX_TRANSPORT_BYTES + 1),
        ("sha256", "not-a-sha"),
    ],
)
def test_split_transport_rejects_invalid_whole_declarations(tmp_path: Path, field: str, changed: object) -> None:
    path, manifest, _ = split_package(tmp_path)
    manifest[field] = changed
    replace_manifest(path, manifest)
    with pytest.raises(StudioError, match="declared transport|SHA-256"):
        read_studio_package(path)


@pytest.mark.parametrize("changed", [0, True, MAX_PART_BYTES + 1])
def test_split_transport_rejects_invalid_part_size(tmp_path: Path, changed: object) -> None:
    path, manifest, _ = split_package(tmp_path)
    manifest["parts"][0]["bytes"] = changed
    replace_manifest(path, manifest)
    with pytest.raises(StudioError, match="declared transport"):
        read_studio_package(path)


def test_split_transport_bounds_manifest_parts_and_decompressed_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, manifest, _ = split_package(tmp_path)
    monkeypatch.setattr(studio_core, "MAX_MANIFEST_BYTES", path.stat().st_size - 1)
    with pytest.raises(StudioError, match="bounded size"):
        read_studio_package(path)
    monkeypatch.setattr(studio_core, "MAX_MANIFEST_BYTES", 64 * 1024)
    part_path = tmp_path / manifest["parts"][0]["basename"]
    part_path.write_bytes(part_path.read_bytes() + b"x" * MAX_PART_BYTES)
    with pytest.raises(StudioError, match="bounded size"):
        read_studio_package(path)
    part_path.write_bytes((tmp_path / "studio.json.gz").read_bytes())
    monkeypatch.setattr(studio_core, "MAX_PACKAGE_JSON_BYTES", 100)
    with pytest.raises(StudioError, match="decompressed presentation"):
        read_studio_package(path)


def test_split_transport_rejects_excess_parts_or_inconsistent_total(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, manifest, _ = split_package(tmp_path)
    monkeypatch.setattr(studio_core, "MAX_PARTS", 0)
    with pytest.raises(StudioError, match="part count"):
        read_studio_package(path)
    monkeypatch.setattr(studio_core, "MAX_PARTS", 512)
    manifest["bytes"] += 1
    replace_manifest(path, manifest)
    with pytest.raises(StudioError, match="sizes disagree"):
        read_studio_package(path)


def test_split_writer_refuses_existing_part_without_modifying_any_input(tmp_path: Path) -> None:
    original, _ = package(tmp_path)
    original_bytes = original.read_bytes()
    manifest_path = tmp_path / "studio.manifest.json"
    existing = tmp_path / "studio.part-00000.bin"
    existing.write_bytes(b"preserve me")
    with pytest.raises(StudioError, match="never overwrites"):
        write_split_package(original_bytes, manifest_path)
    assert existing.read_bytes() == b"preserve me"
    assert original.read_bytes() == original_bytes
    assert not manifest_path.exists()


def test_exporter_split_flag_creates_new_transport_and_preserves_old_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import export_saved_research_studio as exporter

    original, _ = package(tmp_path)
    original_bytes = original.read_bytes()
    value = read_studio_package(original)
    monkeypatch.setattr(exporter, "export_bundle", lambda *args: value)
    path = tmp_path / "export.manifest.json"
    monkeypatch.setattr("sys.argv", ["export_saved_research_studio", "--saved-runs", str(original), "--output", str(path), "--split-output"])
    assert exporter.main() == 0
    assert read_studio_package(path) == value
    manifest = json.loads(path.read_bytes())
    expected = gzip.compress(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(), mtime=0)
    assert manifest["sha256"] == hashlib.sha256(expected).hexdigest()
    assert original.read_bytes() == original_bytes


@pytest.mark.parametrize("filename", ["studio.gz", "studio.json.gz", "studio.bin", "studio"])
def test_split_writer_rejects_unreadable_output_suffix_before_creating_files(tmp_path: Path, filename: str) -> None:
    target = tmp_path / "not-created" / filename
    with pytest.raises(StudioError, match=".json suffix"):
        write_split_package(gzip.compress(b"{}"), target)
    assert not target.parent.exists()


@pytest.mark.parametrize("filename", ["studio.gz", "studio.json.gz", "studio.bin", "studio"])
def test_split_cli_rejects_output_suffix_before_reading_any_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], filename: str
) -> None:
    from scripts import export_saved_research_studio as exporter

    called = False

    def forbid_source_read(*args: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        raise AssertionError("invalid output must be rejected before source access")

    monkeypatch.setattr(exporter, "export_bundle", forbid_source_read)
    target = tmp_path / "not-created" / filename
    monkeypatch.setattr(
        "sys.argv", ["export_saved_research_studio", "--saved-runs", str(tmp_path / "missing-input.gz"), "--output", str(target), "--split-output"]
    )
    with pytest.raises(SystemExit) as error:
        exporter.main()
    assert error.value.code == 2
    assert "requires a .json manifest output" in capsys.readouterr().err
    assert not called
    assert not target.parent.exists()


def test_partial_sales_split_and_post_close_dividend_link_to_qualified_cycle() -> None:
    run = built()
    first, reopened = run["positions"]
    assert len(run["positions"]) == 2
    assert first["closeDate"] == "2020-01-03"
    assert first["realizedPnl"] == 206
    assert first["inflow"] == 306
    assert reopened["closeDate"] is None
    assert reopened["realizedPnl"] == 0
    assert reopened["unrealizedPnl"] == 20
    assert reopened["inflow"] == 0
    assert run["reconciliation"]["verified"] is True
    assert run["reconciliation"]["totalPnl"] == 226


def test_account_keeps_receivables_outside_cash_and_stock_value() -> None:
    run = built()
    day = run["accounts"][1]
    assert day["cash"] == 960
    assert day["holdings"][0]["marketValue"] == 120
    assert day["otherAssets"] == 6
    assert day["reconstructedEquity"] == 1086
    assert day["verified"] is True


def test_missing_mark_is_unknown_and_never_a_zero_valuation() -> None:
    _, ledger, *_ = evidence()
    state = copy.deepcopy(ledger["daily_states"][-1])
    state["tradable_positions"][0]["raw_mark_twd"] = None
    audit = account_audit(state, 1226)
    assert audit["holdings"][0]["marketValue"] is None
    assert audit["difference"] is None
    assert audit["reconstructedEquity"] is None
    assert not audit["verified"]


def test_open_partial_sale_separates_realized_and_unrealized_cost_basis() -> None:
    run, ledger, orders, traces, candles = evidence()
    run.update({"through": "2020-01-02", "finalEquity": 1080, "netReturn": 0.08})
    run["events"] = run["events"][:2]
    run["nav"] = [{"date": "2020-01-01", "equity": 1000}, {"date": "2020-01-02", "equity": 1080}]
    ledger["events"] = ledger["events"][:2]
    ledger["daily_states"] = ledger["daily_states"][:2]
    state = ledger["daily_states"][1]
    state["dividend_receivable_twd"] = 0
    state["tradable_positions"][0].update({"quantity": 6, "raw_mark_twd": 20, "market_value_twd": 120})
    result = build_run(run, ledger, orders, traces, candles, [])
    trade = result["positions"][0]
    assert trade["remainingCost"] == 60
    assert trade["realizedPnl"] == 20
    assert trade["unrealizedPnl"] == 60
    assert trade["pnl"] == 80
    assert result["reconciliation"]["verified"]


def test_unrelated_dividend_is_not_attached_to_latest_trade() -> None:
    run, ledger, orders, traces, candles = evidence()
    run["events"][-1]["original"]["entitlement_id"] = "not-qualified"
    result = build_run(run, ledger, orders, traces, candles, [])
    assert result["positions"][0]["inflow"] == 300
    assert result["positions"][1]["inflow"] == 0
    assert result["reconciliation"]["difference"] == -6
    assert not result["reconciliation"]["verified"]
    assert any("資格事件" in reason for reason in result["reconciliation"]["reasons"])


def test_old_rank_and_capture_not_synthesized() -> None:
    run = built()
    assert run["positions"][0]["fills"][0]["dailyRank"] is None
    assert "沒有保存當日排名" in run["positions"][0]["whySell"]
    assert run["captureAvgWeight"] is None
    assert run["positions"][0]["capture"]["days"] is None
    assert run["ownerAdopted"] is False


def test_saved_economic_add_probe_uses_exact_order_identity() -> None:
    run, ledger, orders, traces, candles = evidence()
    run["events"][0]["original"]["order_id"] = "ADD-1"
    orders[0]["intent"]["order_id"] = "ADD-1"
    probes: list[dict[str, Any]] = [
        {
            "as_of": "2019-12-31T20:00:00+08:00",
            "adds": [
                {"code": "2330", "order_id": "ADD-1", "economic_return": {"numerator": 11, "denominator": 100}, "reason": "proposed"},
                {"code": "2330", "order_id": None, "economic_return": {"numerator": 99, "denominator": 100}, "reason": "return_below_threshold"},
            ],
        }
    ]
    result = build_run(run, ledger, orders, traces, candles, [], probes)
    fill = result["positions"][0]["fills"][0]
    assert fill["kind"] == "add"
    assert fill["addSignal"]["economicReturn"] == 0.11
    probes[0]["adds"][0]["code"] = "0050"
    with pytest.raises(StudioError, match="add probe and matched order disagree"):
        build_run(run, ledger, orders, traces, candles, [], probes)


def test_order_identity_mismatch_rejected() -> None:
    run, ledger, orders, traces, candles = evidence()
    orders[0]["intent"]["code"] = "0050"
    with pytest.raises(StudioError, match="matched order disagree"):
        build_run(run, ledger, orders, traces, candles, [])


def test_saved_event_disagreement_rejected() -> None:
    run, ledger, orders, traces, candles = evidence()
    run["events"][0] = copy.deepcopy(run["events"][0])
    run["events"][0]["original"]["price"] = 999
    with pytest.raises(StudioError, match="verified ledger"):
        build_run(run, ledger, orders, traces, candles, [])


def test_frozen_source_hash_mismatch_rejected(tmp_path: Path) -> None:
    path = tmp_path / "source.json"
    path.write_bytes(b"original")
    digest = hashlib.sha256(b"original").hexdigest()
    assert read_verified(path, digest) == b"original"
    path.write_bytes(b"modified")
    with pytest.raises(StudioError, match="SHA-256 mismatch"):
        read_verified(path, digest)


@pytest.mark.parametrize("day", ["2020-02-30", "2020-1-01", "../2020-01-01", "2020-01-01T00:00:00"])
def test_invalid_date_rejected(day: str) -> None:
    with pytest.raises(StudioError):
        valid_day(day)


def test_daily_capture_uses_each_saved_date_and_preserves_unknown(tmp_path: Path) -> None:
    path, run = package(tmp_path)
    calls = []

    def provider(code: str, day: str) -> dict | None:
        calls.append((code, day))
        if day == "2020-01-02":
            return None
        return {"onMap": day >= "2020-01-03", "metric": 1.1, "name": "台積電", "catalogId": "c" * 64}

    service = SavedResearchStudio(path, provider)
    full = service.run(run["id"])
    assert set(day for _, day in calls) == set(run["accountDates"])
    assert len(calls) == 4
    assert full["captureAvgWeight"] is None
    assert full["positions"][0]["capture"] == {"days": 1, "knownDays": 2, "totalDays": 3, "bestMetric": 1.1, "missingReason": "部分持有日期的飆股狀態未知。"}
    assert full["positions"][1]["name"] == "台積電"
    exposure = service.exposure(run["id"])["rows"]
    assert exposure[1]["runawayWeight"] is None
    assert exposure[1]["unknownStockWeight"] == pytest.approx(120 / 1086)


def test_api_routes_read_package_and_validate_date(tmp_path: Path) -> None:
    path, run = package(tmp_path)
    app = FastAPI()
    app.include_router(create_studio_router(path), prefix="/history-api")
    client = TestClient(app)
    base = "/history-api/saved-research-studio/v1"
    assert client.get(f"{base}/runs").json()["runs"][0]["id"] == run["id"]
    assert client.get(f"{base}/runs/{run['id']}").json()["reconciliation"]["verified"]
    trade_id = run["positions"][0]["id"]
    assert client.get(f"{base}/runs/{run['id']}/trades/{trade_id}").json()["realizedPnl"] == 206
    assert client.get(f"{base}/runs/{run['id']}/account?date=2020-01-02").json()["otherAssets"] == 6
    assert client.get(f"{base}/runs/{run['id']}/account?date=2020-02-30").status_code == 422
    assert client.get(f"{base}/runs/{run['id']}/account?date=2020-01-05").status_code == 404
    assert client.get(f"{base}/runs/{run['id']}/trades/unknown").status_code == 404
    assert client.get(f"{base}/runs/unknown").status_code == 404
    assert client.get(f"{base}/research-history").json()["historyComplete"] is False


@pytest.mark.parametrize(
    "opaque_id",
    [
        "alpha/beta",
        "台灣策略",
        "alpha beta",
        " leading and trailing ",
        "alpha?beta",
        "alpha#beta",
        "alpha%20beta",
        "alpha&beta",
        "alpha+beta",
        ".",
        "..",
        "alpha.beta",
        "策略 / 空白? #%&+..",
        "line\nbreak",
    ],
)
def test_query_routes_roundtrip_opaque_ids_from_verified_package(tmp_path: Path, opaque_id: str) -> None:
    original_path, _ = package(tmp_path)
    value = read_studio_package(original_path)
    run = value["runs"][0]
    run["id"] = opaque_id
    run["positions"][0]["id"] = opaque_id
    path = tmp_path / "opaque.manifest.json"
    write_split_package(gzip.compress(json.dumps(value, ensure_ascii=False).encode(), mtime=0), path)
    app = FastAPI()
    app.include_router(create_studio_router(path, history_presentation_path=None), prefix="/history-api")
    client = TestClient(app)
    base = "/history-api/saved-research-studio/v1"
    response = client.get(f"{base}/run", params={"run_id": opaque_id})
    assert response.status_code == 200
    assert response.json()["id"] == opaque_id
    trade = client.get(f"{base}/trade", params={"run_id": opaque_id, "trade_id": opaque_id})
    assert trade.status_code == 200
    assert trade.json()["id"] == opaque_id
    assert trade.json()["realizedPnl"] == 206
    account = client.get(f"{base}/account", params={"run_id": opaque_id, "date": "2020-01-02"})
    assert account.status_code == 200
    assert account.json()["otherAssets"] == 6
    exposure = client.get(f"{base}/exposure", params={"run_id": opaque_id})
    assert exposure.status_code == 200
    assert exposure.json()["runId"] == opaque_id
    assert len(exposure.json()["rows"]) == 4
    unknown_run = opaque_id + "/unknown? #%&+"
    for endpoint in ("run", "trade", "account", "exposure"):
        params = {"run_id": unknown_run, "trade_id": opaque_id, "date": "2020-01-02"}
        assert client.get(f"{base}/{endpoint}", params=params).status_code == 404
    assert client.get(f"{base}/trade", params={"run_id": opaque_id, "trade_id": "unknown/交易? #%&+"}).status_code == 404
    assert client.get(f"{base}/account", params={"run_id": opaque_id, "date": "2020-01-05"}).status_code == 404
    assert client.get(f"{base}/account", params={"run_id": opaque_id, "date": "2020-02-30"}).status_code == 422


@pytest.mark.parametrize(
    "endpoint,required",
    [
        ("run", ["run_id"]),
        ("trade", ["run_id", "trade_id"]),
        ("account", ["run_id", "date"]),
        ("exposure", ["run_id"]),
    ],
)
def test_query_route_parameters_are_required_query_fields(tmp_path: Path, endpoint: str, required: list[str]) -> None:
    path, _ = package(tmp_path)
    app = FastAPI()
    app.include_router(create_studio_router(path, history_presentation_path=None))
    response = TestClient(app).get(f"/saved-research-studio/v1/{endpoint}")
    assert response.status_code == 422
    assert {tuple(error["loc"]) for error in response.json()["detail"]} == {("query", name) for name in required}


def test_legacy_path_ids_stay_path_parameters_on_dual_route_handlers(tmp_path: Path) -> None:
    path, run = package(tmp_path)
    app = FastAPI()
    app.include_router(create_studio_router(path, history_presentation_path=None))
    client = TestClient(app)
    base = "/saved-research-studio/v1"
    params = {"run_id": "ignored-query/unknown", "trade_id": "ignored-query/trade", "date": "2020-01-02"}
    assert client.get(f"{base}/runs/{run['id']}", params=params).json()["id"] == run["id"]
    trade_id = run["positions"][0]["id"]
    assert client.get(f"{base}/runs/{run['id']}/trades/{trade_id}", params=params).json()["id"] == trade_id
    assert client.get(f"{base}/runs/{run['id']}/account", params=params).json()["otherAssets"] == 6
    assert client.get(f"{base}/runs/{run['id']}/exposure", params=params).json()["runId"] == run["id"]


def test_capture_loading_does_not_permanently_cache_unknown(tmp_path: Path) -> None:
    path, run = package(tmp_path)

    class Provider:
        ready = False

        def state(self) -> str:
            return "ready" if self.ready else "loading"

        def __call__(self, code: str, day: str) -> dict:
            assert self.ready
            return {"onMap": True, "metric": 1.2}

    provider = Provider()
    service = SavedResearchStudio(path, provider)
    assert service.run(run["id"])["captureState"] == "loading"
    assert service.run(run["id"])["captureAvgWeight"] is None
    provider.ready = True
    full = service.run(run["id"])
    assert full["captureState"] == "ready"
    assert full["capturedClosedTradeCount"] == 1
    assert full["captureAvgWeight"] > 0


def test_research_index_discovers_new_reports_without_owner_adoption(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    task = tasks / "20261008-new-study"
    task.mkdir(parents=True)
    (task / "report.md").write_text("# 新研究\n\n原文結論仍待研究端確認。\n", encoding="utf-8")
    planned = tasks / "20261009-planned"
    planned.mkdir()
    (planned / "mission.md").write_text("# 研究規劃\n\n還沒有結果。\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema_version": "research-registry.v1", "history_complete": False, "events": []}))
    history = research_history(tasks, registry)
    assert len(history["items"]) == 2
    assert history["historyComplete"] is False
    assert history["items"][0]["status"] == "研究中"
    assert history["items"][1]["reviewConfirmed"] is False
    assert history["items"][1]["originalSummary"] == "原文結論仍待研究端確認。"


def history_projection_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    path, _ = package(tmp_path)
    value = read_studio_package(path)
    value["researchHistory"] = {
        "schema": "saved-research-history.v1",
        "historyComplete": False,
        "sourceIds": ["unchanged-formal-evidence"],
        "items": [
            {"id": "20261008-strategy-studio", "status": "已保存報告", "outcome": None, "originalSummary": "網站工程報告"},
            {"id": "20261007-failed-research", "status": "行不通", "outcome": "candidate_failed", "originalSummary": "原始失敗研究"},
            {"id": "20261006-no-category", "status": "研究中", "outcome": None, "originalSummary": "分類未指定"},
            {"id": "20261005-unmapped", "status": "資料不足", "outcome": "data_blocked", "originalSummary": "未列在呈現 metadata"},
        ],
    }
    for index, item in enumerate(value["researchHistory"]["items"]):
        item.update({
            "date": f"2026-10-{8 - index:02d}",
            "title": item["id"],
            "conclusion": item["originalSummary"],
            "reportPath": f"tasks/{item['id']}/report.md",
            "reviewConfirmed": False,
            "evidenceState": "published_report_not_owner_adoption",
            "registryEventIds": [],
        })
    path.write_bytes(gzip.compress(json.dumps(value, ensure_ascii=False).encode()))
    presentation_path = tmp_path / "presentation.json"
    presentation_path.write_text(
        json.dumps(
            {
                "schema": "research-presentation.v1",
                "studies": {
                    "20261008-strategy-studio": {"category": "infrastructure"},
                    "20261007-failed-research": {"category": "research", "plainConclusion": "呈現摘要不能覆寫保存原文"},
                    "20261006-no-category": {"plainTitle": "未指定 category 仍保留"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path, presentation_path, value


def test_history_projection_excludes_only_explicit_infrastructure_without_changing_package(tmp_path: Path) -> None:
    path, presentation_path, original = history_projection_fixture(tmp_path)
    original_bytes = path.read_bytes()
    service = SavedResearchStudio(path, history_presentation_path=presentation_path)
    projected = service.history()
    expected_items = copy.deepcopy(original["researchHistory"]["items"][1:])
    expected_items[0].update({
        "conclusion": "呈現摘要不能覆寫保存原文",
        "summarySource": "presentation-metadata",
        "sourceNote": "呈現摘要尚未由研究端核對。",
    })
    expected_items[1].update({
        "title": "未指定 category 仍保留",
        "savedTitle": "20261006-no-category",
        "summarySource": "presentation-metadata",
        "sourceNote": "呈現摘要尚未由研究端核對。",
    })
    assert projected["items"] == expected_items
    assert projected["excludedInfrastructureCount"] == 1
    assert projected["sourceIds"] == original["researchHistory"]["sourceIds"]
    assert read_studio_package(path) == original
    assert path.read_bytes() == original_bytes
    projected["items"][0]["status"] = "caller cannot change saved verdict"
    assert service.history()["items"][0]["status"] == "行不通"
    app = FastAPI()
    app.include_router(create_studio_router(path, history_presentation_path=presentation_path))
    response = TestClient(app).get("/saved-research-studio/v1/research-history")
    assert response.status_code == 200
    assert response.json()["items"] == expected_items
    assert response.json()["excludedInfrastructureCount"] == 1


def test_history_without_presentation_path_keeps_every_saved_item(tmp_path: Path) -> None:
    path, _, original = history_projection_fixture(tmp_path)
    projected = SavedResearchStudio(path).history()
    assert projected["items"] == original["researchHistory"]["items"]
    assert projected["excludedInfrastructureCount"] == 0
    app = FastAPI()
    app.include_router(create_studio_router(path, history_presentation_path=None))
    response = TestClient(app).get("/saved-research-studio/v1/research-history")
    assert response.status_code == 200
    assert response.json() == {**projected, "dataMode": "local-private", "synthetic": False}


@pytest.mark.parametrize("category", [None, "engineering", "Research", False, ["infrastructure"], {}])
def test_invalid_history_category_returns_503_instead_of_silently_filtering(tmp_path: Path, category: Any) -> None:
    path, presentation_path, original = history_projection_fixture(tmp_path)
    metadata = json.loads(presentation_path.read_bytes())
    metadata["studies"]["20261008-strategy-studio"]["category"] = category
    presentation_path.write_text(json.dumps(metadata), encoding="utf-8")
    app = FastAPI()
    app.include_router(create_studio_router(path, history_presentation_path=presentation_path))
    client = TestClient(app)
    response = client.get("/saved-research-studio/v1/research-history")
    assert response.status_code == 503
    assert response.headers["X-Research-Evidence-Error"] == "integrity"
    assert str(tmp_path) not in response.text
    assert client.get("/saved-research-studio/v1/runs").status_code == 200
    assert read_studio_package(path) == original


@pytest.mark.parametrize("bad_metadata", [None, "{"])
def test_requested_history_policy_missing_or_malformed_is_unavailable(tmp_path: Path, bad_metadata: str | None) -> None:
    path, presentation_path, _ = history_projection_fixture(tmp_path)
    if bad_metadata is None:
        presentation_path.unlink()
    else:
        presentation_path.write_text(bad_metadata, encoding="utf-8")
    app = FastAPI()
    app.include_router(create_studio_router(path, history_presentation_path=presentation_path))
    response = TestClient(app).get("/saved-research-studio/v1/research-history")
    assert response.status_code == 503
    assert response.headers["X-Research-Evidence-Error"] == ("unavailable" if bad_metadata is None else "integrity")
    assert str(tmp_path) not in response.text


MISSING_FIELD = object()


@pytest.mark.parametrize(
    "field_path,replacement",
    [
        (("runs",), MISSING_FIELD),
        (("runs",), {}),
        (("runs",), None),
        (("runs", 0, "id"), MISSING_FIELD),
        (("runs", 0, "id"), []),
        (("runs", 1), None),
        (("runs", 1, "id"), MISSING_FIELD),
        (("runs", 1, "id"), "stock:test:normal"),
        (("runs", 0, "from"), "2020-01-32"),
        (("runs", 0, "through"), MISSING_FIELD),
        (("runs", 0, "accountDates"), None),
        (("runs", 0, "accountDates", 1), 123),
        (("runs", 0, "accountDates", 1), "2020-01-01"),
        (("runs", 0, "limitations"), {}),
        (("runs", 0, "positions"), MISSING_FIELD),
        (("runs", 0, "positions"), {}),
        (("runs", 0, "positions", 1), []),
        (("runs", 0, "positions", 1, "id"), MISSING_FIELD),
        (("runs", 0, "positions", 1, "id"), "stock:test:normal:cycle:0"),
        (("runs", 0, "positions", 0, "openDate"), "yesterday"),
        (("runs", 0, "positions", 0, "capture"), None),
        (("runs", 0, "positions", 0, "capture", "knownDays"), "1"),
        (("runs", 0, "positions", 0, "fills", 1), None),
        (("runs", 0, "positions", 0, "fills", 1, "id"), "event-0"),
        (("runs", 0, "positions", 0, "fills", 1, "original"), []),
        (("runs", 0, "positions", 0, "fills", 1, "entryCandidates"), {}),
        (("runs", 0, "positions", 0, "fills", 1, "price"), "15"),
        (("runs", 0, "positions", 0, "candles", 1), None),
        (("runs", 0, "positions", 0, "candles", 1, "close"), "10"),
        (("runs", 0, "accounts"), None),
        (("runs", 0, "accounts", 1), False),
        (("runs", 0, "accounts", 1, "date"), "2020-01-01"),
        (("runs", 0, "accounts", 1, "holdings"), {}),
        (("runs", 0, "accounts", 0, "holdings", 1), None),
        (("runs", 0, "accounts", 0, "holdings", 1, "code"), "2330"),
        (("runs", 0, "accounts", 0, "cash"), "900"),
        (("runs", 0, "accounts", 0, "recordedEquity"), None),
        (("runs", 0, "accounts", 0, "holdings", 0, "marketValue"), "100"),
        (("runs", 0, "nav", 1), None),
        (("runs", 0, "nav", 1, "equity"), "1086"),
        (("runs", 0, "method"), None),
        (("runs", 0, "method", "rules"), MISSING_FIELD),
        (("runs", 0, "method", "rules"), {}),
        (("runs", 0, "method", "rules"), ["valid first rule", None]),
        (("runs", 0, "statistics", "histogram"), MISSING_FIELD),
        (("runs", 0, "statistics", "histogram"), {}),
        (("runs", 0, "statistics", "histogram", 1), []),
        (("runs", 0, "statistics", "histogram", 1, "count"), None),
        (("runs", 0, "statistics", "monthlyReturns"), [{"month": "2020-01", "return": 0.1}, None]),
        (("runs", 0, "statistics", "longestLosingStreak"), None),
        (("runs", 0, "statistics", "longestUnderwater", "until"), "later"),
        (("runs", 0, "reconciliation", "reasons"), "unknown"),
        (("runs", 0, "reconciliation", "verified"), "yes"),
        (("runs", 0, "benchmark"), None),
        (("researchHistory",), MISSING_FIELD),
        (("researchHistory",), []),
        (("researchHistory", "items"), {}),
        (("researchHistory", "items", 1), None),
        (("researchHistory", "items", 1, "id"), MISSING_FIELD),
        (("researchHistory", "items", 1, "id"), "20261008-strategy-studio"),
        (("researchHistory", "items", 1, "registryEventIds"), "event"),
    ],
)
def test_valid_json_with_invalid_required_structure_returns_integrity_503(tmp_path: Path, field_path: tuple[str | int, ...], replacement: Any) -> None:
    path, _, original = history_projection_fixture(tmp_path)
    changed = copy.deepcopy(original)
    if field_path[:2] == ("runs", 1):
        other = copy.deepcopy(changed["runs"][0])
        other["id"] = "stock:another:normal"
        changed["runs"].append(other)
    if field_path[:6] == ("runs", 0, "accounts", 0, "holdings", 1):
        other_holding = copy.deepcopy(changed["runs"][0]["accounts"][0]["holdings"][0])
        other_holding["code"] = "other-code"
        changed["runs"][0]["accounts"][0]["holdings"].append(other_holding)
    target: Any = changed
    for key in field_path[:-1]:
        target = target[key]
    if replacement is MISSING_FIELD:
        del target[field_path[-1]]
    else:
        target[field_path[-1]] = replacement
    path.write_bytes(gzip.compress(json.dumps(changed, ensure_ascii=False).encode()))
    app = FastAPI()
    app.include_router(create_studio_router(path, history_presentation_path=None))
    client = TestClient(app)
    for endpoint in ("runs", "research-history"):
        response = client.get(f"/saved-research-studio/v1/{endpoint}")
        assert response.status_code == 503
        assert response.headers["X-Research-Evidence-Error"] == "integrity"
        assert str(tmp_path) not in response.text


def test_failed_structure_is_never_partially_cached_and_same_service_can_retry(tmp_path: Path) -> None:
    path, _, original = history_projection_fixture(tmp_path)
    changed = copy.deepcopy(original)
    changed["runs"].append({"id": "partially-invalid-later-run"})
    path.write_bytes(gzip.compress(json.dumps(changed).encode()))
    service = SavedResearchStudio(path)
    with pytest.raises(StudioError):
        service.index()
    assert service._package is None
    path.write_bytes(gzip.compress(json.dumps(original).encode()))
    run = original["runs"][0]
    assert service.index()["runs"][0]["id"] == run["id"]
    assert service.run(run["id"])["positions"] == run["positions"]
    assert service.trade(run["id"], run["positions"][0]["id"]) == run["positions"][0]
    assert service.account(run["id"], "2020-01-04")["recordedEquity"] == 1226
    assert service.history()["items"] == original["researchHistory"]["items"]


@pytest.mark.parametrize("blocked_target,operation", [("manifest", "stat"), ("manifest", "open"), ("part", "stat"), ("part", "open")])
def test_manifest_and_part_permission_failures_return_unavailable_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blocked_target: str, operation: str
) -> None:
    path, manifest, _ = split_package(tmp_path)
    blocked = path if blocked_target == "manifest" else tmp_path / manifest["parts"][0]["basename"]
    original_operation = getattr(Path, operation)

    def deny_selected_file(target: Path, *args: Any, **kwargs: Any) -> Any:
        if target == blocked:
            raise PermissionError(13, "read denied", str(blocked))
        return original_operation(target, *args, **kwargs)

    monkeypatch.setattr(Path, operation, deny_selected_file)
    app = FastAPI()
    app.include_router(create_studio_router(path, history_presentation_path=None))
    response = TestClient(app).get("/saved-research-studio/v1/runs")
    assert response.status_code == 503
    assert response.headers["X-Research-Evidence-Error"] == "unavailable"
    assert str(tmp_path) not in response.text


def test_nullable_evidence_is_preserved_and_nonpositive_equity_does_not_redefine_results(tmp_path: Path) -> None:
    path, _, original = history_projection_fixture(tmp_path)
    run = original["runs"][0]
    run["accounts"][0]["holdings"][0]["price"] = None
    run["accounts"][0]["holdings"][0]["marketValue"] = None
    run["accounts"][0]["otherAssets"] = None
    run["nav"][0]["benchmarkEquity"] = None
    run["accounts"][1]["recordedEquity"] = 0
    run["accounts"][2]["recordedEquity"] = -1
    run["futureEvidence"] = {"customSeries": [{"value": None}], "events": [{"type": "extension"}]}
    path.write_bytes(gzip.compress(json.dumps(original).encode()))
    assert read_studio_package(path) == original
    service = SavedResearchStudio(path)
    assert service.account(run["id"], "2020-01-01")["holdings"][0]["marketValue"] is None
    rows = service.exposure(run["id"])["rows"]
    for row in rows[1:3]:
        assert all(row[key] is None for key in ("runawayWeight", "otherStockWeight", "cashWeight", "otherAssetsWeight", "unknownStockWeight"))
        assert not row["known"]
    assert service.run(run["id"])["studyStatus"] == run["studyStatus"]


def test_benchmark_reads_fixed_catalog_raw_series_and_checks_pin(tmp_path: Path) -> None:
    calendar = {"calendar_id": "calendar-1", "dates": ["2020-01-01", "2020-01-02"]}
    series = {"code": "0050", "calendar_id": "calendar-1", "raw": [100, 110]}
    references = []
    for filename, value in [("calendar.json", calendar), ("0050.json.gz", series)]:
        raw = json.dumps(value).encode()
        if filename.endswith(".gz"):
            raw = gzip.compress(raw)
        (tmp_path / filename).write_bytes(raw)
        references.append({"path": filename, "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {"calendar": references[0], "series": {"0050": references[1]}}
    raw = json.dumps(manifest).encode()
    path = tmp_path / "manifest.json"
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    rows, sources = _catalog_benchmark(path, digest)
    assert [row["close"] for row in rows] == [100, 110]
    assert rows[0]["open"] is None
    assert len(sources) == 3
    with pytest.raises(StudioError, match="SHA-256 mismatch"):
        _catalog_benchmark(path, "0" * 64)


def test_presentation_metadata_enriches_discovery_but_cannot_override_formal_outcome(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    task = tasks / "20261008-new-study"
    task.mkdir(parents=True)
    (task / "report.md").write_text("# 原始標題\n\n原始結論。\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema_version": "research-registry.v1", "history_complete": False, "events": []}))
    presentation = tmp_path / "presentation.json"
    metadata: dict[str, Any] = {
        "schema": "research-presentation.v1",
        "studies": {
            "20261008-new-study": {
                "plainTitle": "白話標題",
                "plainConclusion": "白話摘要。",
                "status": "已結案",
                "reviewConfirmed": False,
                "sourceNote": "Claude 示範改寫，研究端尚未核對。",
            },
            "20261009-not-discovered": {"plainTitle": "不得自行加入歷史清單", "status": "研究中"},
        },
    }
    presentation.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    history = research_history(tasks, registry, presentation)
    assert len(history["items"]) == 1
    row = history["items"][0]
    assert row["title"] == "白話標題"
    assert row["originalSummary"] == "原始結論。"
    assert row["status"] == "已保存報告"
    assert row["draftStatus"] == "已結案"
    assert row["summarySource"] == "presentation-metadata"
    assert row["reviewConfirmed"] is False
    result = {
        "schema_version": "research-result.v1",
        "study_id": "study",
        "candidate_id": "candidate",
        "run_id": "run",
        "phase": "exploration",
        "outcome": "candidate_failed",
        "identities": {key: "v1" for key in ("owner_contract", "metric_contract", "execution_contract", "data_snapshot", "code", "runtime")},
        "window": {"start": "2020-01-01", "end": "2020-01-02"},
        "metrics": {},
        "artifacts": [],
        "limitations": [],
        "supersedes": [],
    }
    (task / "research_result.json").write_text(json.dumps(result))
    verified = research_history(tasks, registry, presentation)["items"][0]
    assert verified["status"] == "行不通"
    assert verified["draftStatus"] is None
    assert verified["outcome"] == "candidate_failed"
    metadata["studies"]["20261008-new-study"]["status"] = "已採用"
    presentation.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(StudioError, match="cannot declare owner adoption"):
        research_history(tasks, registry, presentation)


@pytest.mark.parametrize("missing", [None, float("nan"), "None", "null", " NaN ", "", "<NA>", 2330])
def test_missing_security_names_never_become_string_placeholders(missing: object) -> None:
    assert _security_name(missing) is None


def test_frozen_price_null_name_stays_null(tmp_path: Path) -> None:
    import pandas as pd

    path = tmp_path / "price-readset" / "twse-official" / "prices.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame({
        "code": ["2330", "0050"],
        "date": ["2020-01-01", "2020-01-01"],
        "open": [10.0, 100.0],
        "high": [11.0, 101.0],
        "low": [9.0, 99.0],
        "close": [10.0, 100.0],
        "name": [None, "元大台灣50"],
    }).to_parquet(path, index=False)
    raw = path.read_bytes()
    packet = {"inputs": {str(path): hashlib.sha256(raw).hexdigest()}}
    candles, _ = _frozen_candles(packet, {"2330", "0050"}, "2020-01-01", "2020-01-01")
    assert candles["2330"][0]["name"] is None
    assert candles["0050"][0]["name"] == "元大台灣50"


def test_pinned_catalog_display_names_work_before_map_ready(tmp_path: Path) -> None:
    rows = {
        "rows": [
            {"code": "2330", "security_id": "TW:2330", "name": "台積電", "industry": "不可回填歷史分類"},
            {"code": "2317", "security_id": "TW:2317", "name": None},
        ]
    }
    raw = gzip.compress(json.dumps(rows, ensure_ascii=False).encode())
    chunk = tmp_path / "securities.json.gz"
    chunk.write_bytes(raw)
    ref = {"path": chunk.name, "sha256": hashlib.sha256(raw).hexdigest(), "count": 2}
    manifest_raw = json.dumps({"tables": {"securities": [ref]}}).encode()
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(manifest_raw)
    digest = hashlib.sha256(manifest_raw).hexdigest()
    names, sources = _catalog_display_names(manifest, digest)
    assert names == {"2330": {"name": "台積電", "sourceId": f"security-name-source:{ref['sha256']}"}}
    assert len(sources) == 2
    run, ledger, orders, traces, candles = evidence()
    for candle in candles["2330"]:
        candle["name"] = None
    built_run = build_run(run, ledger, orders, traces, candles, [s["id"] for s in sources], display_names=names)
    assert built_run["positions"][0]["name"] == "台積電"
    assert built_run["positions"][0]["nameBasis"] == "catalog-snapshot-display-name-not-historical-classification"
    assert built_run["accounts"][0]["holdings"][0]["name"] == "台積電"
    package_path = tmp_path / "studio.json.gz"
    package_path.write_bytes(
        gzip.compress(
            json.dumps({
                "schema": SCHEMA,
                "runs": [built_run],
                "researchHistory": {"schema": "saved-research-history.v1", "historyComplete": False, "items": []},
            }).encode()
        )
    )

    class Provider:
        ready = False

        def state(self) -> str:
            return "ready" if self.ready else "loading"

        def __call__(self, code: str, day: str) -> dict:
            return {"onMap": True, "name": "None"}

    provider = Provider()
    service = SavedResearchStudio(package_path, provider)
    assert service.run(run["id"])["positions"][0]["name"] == "台積電"
    provider.ready = True
    assert service.run(run["id"])["positions"][0]["name"] == "台積電"
    assert service.account(run["id"], "2020-01-01")["holdings"][0]["name"] == "台積電"
    chunk.write_bytes(b"modified")
    with pytest.raises(StudioError, match="SHA-256 mismatch"):
        _catalog_display_names(manifest, digest)


def test_unavailable_name_without_catalog_falls_back_to_code() -> None:
    run, ledger, orders, traces, candles = evidence()
    for candle in candles["2330"]:
        candle["name"] = "None"
    result = build_run(run, ledger, orders, traces, candles, [])
    assert result["positions"][0]["name"] == "2330"
    assert result["positions"][0]["nameBasis"] == "code-only-name-unavailable"


def test_ready_capture_updates_name_and_catalog_provenance_for_trade_and_holding(tmp_path: Path) -> None:
    path, run = package(tmp_path)
    original_bytes = path.read_bytes()
    original = read_studio_package(path)
    catalog_id = "c" * 64

    def provider(code: str, day: str) -> dict[str, Any]:
        return {"onMap": True, "metric": 1.2, "name": "台積電", "catalogId": catalog_id}

    service = SavedResearchStudio(path, provider)
    projected = service.run(run["id"])
    for trade in projected["positions"]:
        assert trade["name"] == "台積電"
        assert trade["nameSourceId"] == f"security-name-catalog:{catalog_id}"
        assert trade["nameBasis"] == "catalog-snapshot-display-name-not-historical-classification"
    for day in run["accountDates"]:
        holding = service.account(run["id"], day)["holdings"][0]
        assert holding["name"] == "台積電"
        assert holding["nameSourceId"] == f"security-name-catalog:{catalog_id}"
        assert holding["nameBasis"] == "catalog-snapshot-display-name-not-historical-classification"
        assert holding["sourceId"] == "frozen:abc"
    assert service._load() == original
    assert path.read_bytes() == original_bytes
    assert read_studio_package(path) == original


@pytest.mark.parametrize(
    "status",
    [
        {"name": "台積電"},
        {"name": "台積電", "catalogId": None},
        {"name": "台積電", "catalogId": ""},
        {"name": "台積電", "catalogId": " "},
        {"name": "台積電", "catalogId": "None"},
        {"name": "台積電", "catalogId": False},
        {"name": "台積電", "catalogId": 123},
        {"name": "台積電", "catalogId": {}},
        {"catalogId": "c" * 64},
        {"name": None, "catalogId": "c" * 64},
        {"name": "", "catalogId": "c" * 64},
        {"name": "None", "catalogId": "c" * 64},
        {"name": "2330", "catalogId": "c" * 64},
        {"name": 123, "catalogId": "c" * 64},
    ],
)
def test_ready_capture_keeps_fallback_when_name_or_catalog_evidence_is_incomplete(tmp_path: Path, status: dict[str, Any]) -> None:
    path, run = package(tmp_path)

    def provider(code: str, day: str) -> dict[str, Any]:
        return {"onMap": True, "metric": 1.2, **status}

    service = SavedResearchStudio(path, provider)
    for original, projected in zip(run["positions"], service.run(run["id"])["positions"]):
        assert projected["name"] == original["name"]
        assert projected.get("nameSourceId") == original.get("nameSourceId")
        assert projected.get("nameBasis") == original.get("nameBasis")
    for original in run["accounts"]:
        holding = service.account(run["id"], original["date"])["holdings"][0]
        assert holding["name"] == original["holdings"][0]["name"]
        assert holding.get("nameSourceId") == original["holdings"][0].get("nameSourceId")
        assert holding.get("nameBasis") == original["holdings"][0].get("nameBasis")


def test_ready_capture_preserves_known_name_and_source_even_with_new_catalog(tmp_path: Path) -> None:
    path, _ = package(tmp_path)
    original = read_studio_package(path)
    run = original["runs"][0]
    labels = {"name": "原快照公司名", "nameSourceId": "frozen:known-name", "nameBasis": "frozen-source-display-name-not-certified-historical-name"}
    for trade in run["positions"]:
        trade.update(labels)
    for account in run["accounts"]:
        for holding in account["holdings"]:
            holding.update(labels)
    path.write_bytes(gzip.compress(json.dumps(original, ensure_ascii=False).encode()))
    original_bytes = path.read_bytes()

    def provider(code: str, day: str) -> dict[str, Any]:
        return {"onMap": True, "metric": 1.2, "name": "今日公司名", "catalogId": "c" * 64}

    service = SavedResearchStudio(path, provider)
    for trade in service.run(run["id"])["positions"]:
        assert {key: trade[key] for key in labels} == labels
    for account in run["accounts"]:
        holding = service.account(run["id"], account["date"])["holdings"][0]
        assert {key: holding[key] for key in labels} == labels
    assert service._load() == original
    assert path.read_bytes() == original_bytes
    assert read_studio_package(path) == original


def test_ready_capture_single_flight_for_concurrent_detail_and_exposure(tmp_path: Path) -> None:
    path, run = package(tmp_path)
    start = Barrier(3)
    entered = Event()
    release = Event()
    duplicate = Event()
    count_lock = Lock()
    calls = []

    def provider(code: str, day: str) -> dict:
        with count_lock:
            calls.append((code, day))
            if calls.count((code, day)) > 1:
                duplicate.set()
        if day == "2020-01-01":
            entered.set()
            assert release.wait(5)
        return {"onMap": True, "metric": 1.2}

    service = SavedResearchStudio(path, provider)

    def detail() -> dict:
        start.wait(5)
        return service.run(run["id"])

    def exposure() -> dict:
        start.wait(5)
        return service.exposure(run["id"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(detail)
        second = pool.submit(exposure)
        start.wait(5)
        try:
            assert entered.wait(5)
            assert not duplicate.wait(0.1)
        finally:
            release.set()
        assert first.result(timeout=5)["captureState"] == "ready"
        assert second.result(timeout=5)["captureState"] == "ready"
    assert len(calls) == 4
    assert len(set(calls)) == 4


def test_capture_different_runs_can_enrich_in_parallel(tmp_path: Path) -> None:
    path, run = package(tmp_path)
    other = copy.deepcopy(run)
    other["id"] = "stock:test:other"
    path.write_bytes(
        gzip.compress(
            json.dumps({
                "schema": SCHEMA,
                "runs": [run, other],
                "researchHistory": {"schema": "saved-research-history.v1", "historyComplete": False, "items": []},
            }).encode()
        )
    )
    both_providers = Barrier(2)
    context = local()

    def provider(code: str, day: str) -> dict:
        if not getattr(context, "entered", False):
            context.entered = True
            both_providers.wait(5)
        return {"onMap": True, "metric": 1.2}

    service = SavedResearchStudio(path, provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.run, run["id"])
        second = pool.submit(service.run, other["id"])
        assert first.result(timeout=5)["captureState"] == "ready"
        assert second.result(timeout=5)["captureState"] == "ready"


def test_capture_provider_reentrant_saved_evidence_read_does_not_deadlock(tmp_path: Path) -> None:
    path, run = package(tmp_path)
    nested = []

    def provider(code: str, day: str) -> dict:
        nested.append(service.account(run["id"], day)["recordedEquity"])
        return {"onMap": True, "metric": 1.2}

    service = SavedResearchStudio(path, provider)
    completed = Event()
    results, errors = [], []

    def read() -> None:
        try:
            results.append(service.run(run["id"]))
        except Exception as error:
            errors.append(error)
        finally:
            completed.set()

    thread = Thread(target=read, daemon=True)
    thread.start()
    assert completed.wait(5), "provider reentrant read deadlocked"
    thread.join(timeout=1)
    assert not errors
    assert results[0]["captureState"] == "ready"
    assert nested == [1000, 1086, 1206, 1226]


def test_offsetting_normalized_cashflows_cannot_fake_per_cycle_profits() -> None:
    run, ledger, orders, traces, candles = evidence()
    run["events"][0]["cashFlow"] = -110
    run["events"][5]["cashFlow"] = -90
    with pytest.raises(StudioError, match="normalized event cashFlow"):
        build_run(run, ledger, orders, traces, candles, [])


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("action", "SELL"),
        ("code", "0050"),
        ("date", "2020-01-01T10:00:00+08:00"),
        ("quantity", 9),
        ("price", 11),
        ("cashFlow", -110),
    ],
)
def test_normalized_event_fields_must_match_exact_original(field: str, changed: object) -> None:
    run, ledger, orders, traces, candles = evidence()
    run["events"][0][field] = changed
    with pytest.raises(StudioError, match=f"normalized event {field}"):
        build_run(run, ledger, orders, traces, candles, [])


@pytest.mark.parametrize(
    ("field", "changed", "message"),
    [
        ("finalEquity", 1236, "last saved NAV"),
        ("netReturn", 0.99, "net return disagrees"),
    ],
)
def test_return_and_final_equity_cannot_diverge_from_recorded_nav(field: str, changed: float, message: str) -> None:
    run, ledger, orders, traces, candles = evidence()
    run[field] = changed
    with pytest.raises(StudioError, match=message):
        build_run(run, ledger, orders, traces, candles, [])


def test_saved_nav_and_costs_are_bound_to_verified_native_measurement() -> None:
    run, ledger, orders, traces, candles = evidence()
    ledger["recorded_nav"] = copy.deepcopy(run["nav"])
    run["nav"][1]["equity"] += 1
    with pytest.raises(StudioError, match="saved NAV disagrees"):
        build_run(run, ledger, orders, traces, candles, [])
    run["nav"][1]["equity"] -= 1
    ledger["recorded_measurement"] = {"initial_capital_twd": 1000, "endpoint_equity_twd": 1226, "endpoint_net_return_fraction": 0.226, "costs_total_twd": 1}
    with pytest.raises(StudioError, match="saved costs disagrees"):
        build_run(run, ledger, orders, traces, candles, [])


def test_entry_trace_join_uses_exact_timestamp_and_missing_candidates_stay_unknown() -> None:
    run, ledger, orders, traces, candles = evidence()
    other = copy.deepcopy(traces[0])
    other["as_of"] = "2019-12-31T09:00:00+08:00"
    other["unoccupied_top_five"] = [["0050", "whole_lot_affordable"]]
    result = build_run(run, ledger, orders, [other, *traces], candles, [])
    assert result["positions"][0]["fills"][0]["entryCandidates"][0]["code"] == "2330"
    with pytest.raises(StudioError, match="duplicate saved entry trace"):
        build_run(run, ledger, orders, [*traces, copy.deepcopy(traces[0])], candles, [])
    missing = {"as_of": traces[0]["as_of"]}
    result = build_run(run, ledger, orders, [missing], candles, [])
    assert result["positions"][0]["fills"][0]["entryCandidates"] is None
    result = build_run(run, ledger, orders, [other], candles, [])
    assert result["positions"][0]["fills"][0]["entryCandidates"] is None


def test_pending_entitlement_is_traceable_on_affected_cycle() -> None:
    run, ledger, orders, traces, candles = evidence()
    run["events"] = run["events"][:-1]
    ledger["events"] = ledger["events"][:-1]
    run["finalEquity"] = 1226
    ledger["daily_states"][-1]["cash_twd"] = 1100
    ledger["daily_states"][-1]["dividend_receivable_twd"] = 6
    result = build_run(run, ledger, orders, traces, candles, [])
    trade = result["positions"][0]
    assert trade["pnl"] == 200
    assert trade["pendingAssets"][0]["entitlementId"] == "div-1"
    assert trade["pendingAssets"][0]["eventId"] == "event-2"
    assert any("div-1" in reason and "尚未入帳" in reason for reason in trade["missingReasons"])
    assert result["reconciliation"]["verified"] is True


def test_unsupported_share_event_is_visible_on_affected_trade() -> None:
    run, ledger, orders, traces, candles = evidence()
    original = {"action": "SHARE_ENTITLEMENT", "code": "2330", "date": "2020-01-01T12:00:00+08:00", "total": 0}
    run["events"].insert(
        1,
        {
            "id": "share-event",
            "date": original["date"],
            "action": original["action"],
            "code": "2330",
            "quantity": None,
            "price": None,
            "cashFlow": 0,
            "original": original,
        },
    )
    ledger["events"].insert(1, {"source_event": original})
    result = build_run(run, ledger, orders, traces, candles, [])
    affected = result["positions"][0]
    assert any(fill["id"] == "share-event" for fill in affected["fills"])
    assert any("share-event" in reason for reason in affected["missingReasons"])
    assert not result["reconciliation"]["verified"]
