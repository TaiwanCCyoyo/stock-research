"""Synthetic persisted generations exercise the dashboard without producer reads."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from threading import Event
from typing import Any

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api.shared_data import create_shared_data_router
from research_core import live_producer, shared_data_view
from research_core import maintained_adjusted_daily as maintained
from research_core.artifact_store import file_digest, write_json
from research_core.shared_data_view import SharedDataView


def _publish(root: Path, generation: str, value: float = 10.0) -> Path:
    """Write a tiny reader-compatible generation, never invoking maintenance."""
    family = root / "derived" / maintained.FAMILY
    directory = family / "generations" / generation
    directory.mkdir(parents=True)
    dates = pd.to_datetime(["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15"])
    # Invalid rows deliberately contain plausible non-null numbers: the viewer
    # must blank them based on Quality rather than trust their stored values.
    prices = pd.DataFrame({
        "Code": ["2330"] * 4,
        "Date": dates,
        "Open": [value] * 4,
        "High": [value + 1] * 4,
        "Low": [value - 1] * 4,
        "Close": [value] * 4,
        "VolumeLots": [100.0] * 4,
        "Quality": [True, False, False, True],
        "quality_reason": ["", "missing_official_quote", "invalid_ohlc", ""],
    })

    def table(name: str, frame: pd.DataFrame) -> dict[str, Any]:
        path = directory / name
        frame.to_parquet(path, index=False)
        return {"file": name, "sha256": file_digest(path), "bytes": path.stat().st_size, "rows": len(frame)}

    bases = {basis: table(f"{basis}.parquet", prices) for basis in maintained.BASES}
    daily = pd.DataFrame({"Code": ["2330"] * 4, "Date": dates, "SMA5": [value] * 4})
    pivots = pd.DataFrame({
        "Code": ["2330"],
        "k": [1.5],
        "extreme_date": dates[:1],
        "confirmed_at": dates[3:],
        "kind": ["high"],
        "price": [value + 1],
    })
    status = {
        "family": maintained.FAMILY,
        "generation": generation,
        "asof": "2026-10-15",
        "codes": 1,
        "bases": bases,
        "technical": {
            "definition": {"version": "technical-daily-v1", "basis": shared_data_view.REFERENCE},
            "tables": {"daily": table("technical.parquet", daily), "pivots": table("pivots.parquet", pivots)},
        },
    }
    write_json(directory / "status.json", status)
    pointer = family / "current.next.json"
    pointer.write_text(json.dumps({"generation": generation, "status_sha256": file_digest(directory / "status.json")}), encoding="utf-8")
    pointer.replace(family / "current.json")
    return directory


@pytest.fixture()
def viewer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SharedDataView]:
    _publish(tmp_path, "generation-one")
    monkeypatch.setattr(shared_data_view, "symbol_names", lambda: {"2330": ("Synthetic", "TEST")})
    store = SharedDataView(tmp_path)
    store.prepare(wait=True)
    try:
        yield store
    finally:
        store.close()


def _client(store: SharedDataView) -> TestClient:
    app = FastAPI()
    app.include_router(create_shared_data_router(store))
    return TestClient(app)


def test_invalid_and_missing_rows_keep_dates_but_render_whitespace(viewer: SharedDataView) -> None:
    result = viewer.series("2330", shared_data_view.REFERENCE, None, None)
    assert result["dates"] == ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15"]
    for column in ("open", "high", "low", "close", "volume"):
        assert result[column][1:3] == [None, None]
        assert result[column][0] is not None and result[column][3] is not None
    assert result["quality_reason"] == ["", "missing_official_quote", "invalid_ohlc", ""]
    assert result["tech"]["SMA5"] == [10.0, None, None, 10.0]
    assert result["pivots"][0]["confirmed_at"] == "2026-10-15"


@pytest.mark.parametrize("basis", ["raw", "permanent_adjusted"])
def test_other_price_bases_never_attach_reference_technical_values(viewer: SharedDataView, basis: str) -> None:
    result = viewer.series("2330", basis, None, None)
    assert result["basis"] == basis
    assert result["tech"] == {}
    assert result["pivots"] == []


def test_date_filter_aligns_prices_technical_and_pivots(viewer: SharedDataView) -> None:
    result = viewer.series("2330", shared_data_view.REFERENCE, "2026-10-14", "2026-10-15")
    assert result["dates"] == ["2026-10-14", "2026-10-15"]
    assert result["close"] == [None, 10.0]
    assert result["tech"]["SMA5"] == [None, 10.0]
    assert result["pivots"] == []
    empty = viewer.series("2330", shared_data_view.REFERENCE, "2030-01-01", None)
    assert empty["dates"] == empty["close"] == []


def test_http_unknown_symbol_and_invalid_date_range(viewer: SharedDataView, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")
    client = _client(viewer)
    base = "/shared-data/v1/adjusted-daily-v1/series"
    assert client.get(f"{base}/9999").status_code == 404
    assert client.get(f"{base}/2330?from=2026-10-15&to=2026-10-12").status_code == 422
    assert client.get(f"{base}/2330?from=not-a-date").status_code == 422
    assert client.get(f"{base}/2330?basis=unknown").status_code == 422
    response = client.get(f"{base}/2330?from=2026-10-15")
    assert response.status_code == 200
    assert response.json()["close"] == [10.0]


def test_generation_change_rewarms_and_returns_explicit_retry(viewer: SharedDataView, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")
    entered, release = Event(), Event()
    warm = viewer._warm

    def blocked(status: dict[str, Any]) -> list[dict[str, Any]]:
        entered.set()
        if not release.wait(10):
            raise RuntimeError("test did not release warmup")
        return warm(status)

    monkeypatch.setattr(viewer, "_warm", blocked)
    _publish(viewer.root, "generation-two", 20.0)
    try:
        response = _client(viewer).get("/shared-data/v1/adjusted-daily-v1/symbols")
        assert entered.wait(2)
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "1"
    finally:
        release.set()
    viewer.prepare(wait=True)
    result = viewer.series("2330", shared_data_view.REFERENCE, None, None)
    assert result["generation"] == "generation-two"
    assert result["close"] == result["tech"]["SMA5"] == [20.0, None, None, 20.0]


def test_pointer_switch_during_series_never_mixes_generations(viewer: SharedDataView, monkeypatch: pytest.MonkeyPatch) -> None:
    read = maintained.read_adjusted_daily
    switched = False

    def switch_after_prices(*args: Any, **kwargs: Any) -> Any:
        nonlocal switched
        result = read(*args, **kwargs)
        if not switched:
            switched = True
            _publish(viewer.root, "generation-two", 20.0)
        return result

    monkeypatch.setattr(maintained, "read_adjusted_daily", switch_after_prices)
    result = viewer.series("2330", shared_data_view.REFERENCE, None, None)
    assert result["generation"] == "generation-one"
    assert result["close"] == result["tech"]["SMA5"] == [10.0, None, None, 10.0]
    viewer.prepare(wait=True)
    assert viewer.series("2330", shared_data_view.REFERENCE, None, None)["generation"] == "generation-two"


@pytest.mark.parametrize("file", ["status.json", "reference_factor_adjusted.parquet", "technical.parquet", "pivots.parquet"])
def test_pruned_generation_files_fail_explicitly(viewer: SharedDataView, monkeypatch: pytest.MonkeyPatch, file: str) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")
    (viewer.root / "derived" / maintained.FAMILY / "generations" / "generation-one" / file).unlink()
    response = _client(viewer).get("/shared-data/v1/adjusted-daily-v1/series/2330")
    assert response.status_code == 503
    assert response.json()["detail"]


@pytest.mark.parametrize("path", ["families", "adjusted-daily-v1/symbols", "adjusted-daily-v1/series/2330"])
def test_public_mode_refuses_before_accessing_private_data(viewer: SharedDataView, monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "public-synthetic")

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("public mode attempted private data access")

    monkeypatch.setattr(viewer, "status", forbidden)
    monkeypatch.setattr(shared_data_view, "symbol_names", forbidden)
    response = _client(viewer).get(f"/shared-data/v1/{path}")
    assert response.status_code == 503


def test_busy_producer_declines_metadata_before_resolving_or_reading_root(monkeypatch: pytest.MonkeyPatch) -> None:
    def busy() -> None:
        raise live_producer.ProducerBusyError("synthetic producer writer running")

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("busy producer must not be read")

    monkeypatch.setattr(live_producer, "assert_producer_idle", busy)
    monkeypatch.setattr(shared_data_view, "producer_data_root", forbidden)
    monkeypatch.setattr(live_producer, "readonly_sqlite", forbidden)
    assert shared_data_view.symbol_names() == {}
