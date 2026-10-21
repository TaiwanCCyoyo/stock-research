"""Synthetic persisted generations exercise the dashboard without producer reads."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
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
    assert store._names_future is not None
    store._names_future.result(timeout=3)
    store.prepare()
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
    def busy(**kwargs: Any) -> None:
        raise live_producer.ProducerBusyError("synthetic producer writer running")

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("busy producer must not be read")

    monkeypatch.setattr(live_producer, "assert_producer_idle", busy)
    monkeypatch.setattr(shared_data_view, "producer_data_root", forbidden)
    monkeypatch.setattr(live_producer, "readonly_sqlite", forbidden)
    assert shared_data_view.symbol_names() == {}


def test_empty_names_retry_in_background_only_after_cooldown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _publish(tmp_path, "generation-one")
    clock = [100.0]
    monkeypatch.setattr(shared_data_view, "time", SimpleNamespace(monotonic=lambda: clock[0], perf_counter=shared_data_view.time.perf_counter))
    attempts = []

    def names() -> dict[str, tuple[str, str]]:
        attempts.append(clock[0])
        return {} if len(attempts) == 1 else {"2330": ("合成名稱", "TEST")}

    monkeypatch.setattr(shared_data_view, "symbol_names", names)
    store = SharedDataView(tmp_path)
    try:
        store.prepare(wait=True)
        pending = store._names_future
        assert pending is not None
        pending.result(timeout=3)
        assert not store.symbols()["namesAvailable"]  # Harvest the empty result.
        for moment in (100.0, 130.0, 159.99):
            clock[0] = moment
            store.prepare()
        assert len(attempts) == 1
        clock[0] = 160.0
        store.prepare()
        pending = store._names_future
        assert pending is not None
        pending.result(timeout=3)
        assert store.symbols()["symbols"][0]["name"] == "合成名稱"
        clock[0] = 1000.0
        store.prepare()
        assert len(attempts) == 2
    finally:
        store.close()


@pytest.mark.parametrize("completed", [True, False])
@pytest.mark.parametrize("stale", [{}, {"2330": ("過期名稱", "TEST")}])
def test_first_names_read_never_blocks_http_or_overwrites_new_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, completed: bool, stale: dict[str, tuple[str, str]]
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")
    _publish(tmp_path, "generation-one")
    entered, release, fresh_entered, fresh_release = Event(), Event(), Event(), Event()
    calls: list[int] = []

    def names() -> dict[str, tuple[str, str]]:
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10), "first metadata read was not released"
            return stale
        fresh_entered.set()
        assert fresh_release.wait(10), "fresh metadata read was not released"
        return {"2330": ("新世代名稱", "TEST")}

    monkeypatch.setattr(shared_data_view, "symbol_names", names)
    store = SharedDataView(tmp_path)
    requests = ThreadPoolExecutor(max_workers=1)
    client = _client(store)

    def check_http(generation: str) -> None:
        for endpoint in ("symbols", "series/2330"):
            response = requests.submit(client.get, f"/shared-data/v1/adjusted-daily-v1/{endpoint}").result(timeout=3)
            assert response.status_code == 200
            assert response.json()["generation"] == generation
            if endpoint == "symbols":
                assert not response.json()["namesAvailable"]
                assert response.json()["symbols"][0]["name"] == "2330"

    try:
        requests.submit(store.prepare, wait=True).result(timeout=3)
        assert entered.wait(3)
        old = store._names_future
        assert old is not None
        check_http("generation-one")
        if completed:
            release.set()
            assert old.result(timeout=3) == stale
        _publish(tmp_path, "generation-two", 20.0)
        requests.submit(store.prepare, wait=True).result(timeout=3)
        check_http("generation-two")
        if not completed:
            assert store._names_future is old and calls == [1]
            assert not fresh_entered.is_set(), "stale running work must prevent replacement reads"
            release.set()
            old.result(timeout=3)
            store.prepare()
        assert fresh_entered.wait(3)
        assert calls == [1, 2]
        check_http("generation-two")
        current = store._names_future
        assert current is not None and current is not old
        fresh_release.set()
        current.result(timeout=3)
        response = client.get("/shared-data/v1/adjusted-daily-v1/symbols")
        assert response.status_code == 200
        assert response.json()["symbols"][0]["name"] == "新世代名稱"
        assert response.json()["namesAvailable"]
        assert client.get("/shared-data/v1/adjusted-daily-v1/series/2330").json()["close"] == [20.0, None, None, 20.0]
        assert calls == [1, 2], "stale empty results must not trigger a current-generation cooldown or extra read"
    finally:
        release.set()
        fresh_release.set()
        requests.shutdown(wait=True)
        store.close()


def test_discovery_labels_read_the_index_without_mutating_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "index.md"
    path.write_text("\n".join([shared_data_view.LABELS_START, "| `synthetic` | 中文名稱 | 能回答的問題 |", shared_data_view.LABELS_END]), encoding="utf-8")
    labels = shared_data_view.discovery_labels(path)
    assert labels == {"synthetic": {"display_title": "中文名稱", "purpose": "能回答的問題"}}
    monkeypatch.setattr(shared_data_view, "discovery_labels", lambda: labels)
    assert shared_data_view.family_summary({"family": "synthetic"})["purpose"] == "能回答的問題"


def test_repo_index_has_display_metadata_for_maintained_family() -> None:
    labels = shared_data_view.discovery_labels()
    assert labels["adjusted-daily-v1"]["display_title"] == "每日行情與技術指標"
    assert labels["adjusted-daily-v1"]["purpose"]


def test_failed_warmup_retries_same_generation_only_after_cooldown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _publish(tmp_path, "generation-one")
    monkeypatch.setattr(shared_data_view, "symbol_names", lambda: {})
    clock = [100.0]
    monkeypatch.setattr(shared_data_view, "time", SimpleNamespace(monotonic=lambda: clock[0], perf_counter=shared_data_view.time.perf_counter))
    read = maintained.read_adjusted_daily
    calls = 0

    def transient(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("temporary synthetic file access failure")
        return read(*args, **kwargs)

    monkeypatch.setattr(maintained, "read_adjusted_daily", transient)
    store = SharedDataView(tmp_path)
    try:
        with pytest.raises(shared_data_view.ViewUnavailable):
            store.prepare(wait=True)
        for moment in (100.0, 100.5, 100.99):
            clock[0] = moment
            with pytest.raises(shared_data_view.ViewUnavailable):
                store.prepare(wait=True)
        assert calls == 1, "requests within the cooldown must not enqueue another warmup"
        clock[0] = 101.0
        status, symbols = store.prepare(wait=True)
        assert status["generation"] == "generation-one"
        assert symbols[0]["code"] == "2330"
        assert store.series("2330", "raw", None, None)["close"] == [10.0, None, None, 10.0]
    finally:
        store.close()


@pytest.mark.parametrize("phase", ["warm", "series"])
@pytest.mark.parametrize("expected_error", [True, False])
def test_concurrent_file_change_is_503_but_programming_error_surfaces(
    viewer: SharedDataView, monkeypatch: pytest.MonkeyPatch, phase: str, expected_error: bool
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_DATA_MODE", "local-private")

    def fail(*args: Any, **kwargs: Any) -> Any:
        if expected_error:
            raise live_producer.ProducerChangedError("synthetic file changed during stable read")
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(maintained, "read_adjusted_daily", fail)
    if phase == "warm":
        _publish(viewer.root, "generation-two")
        error = shared_data_view.ViewUnavailable if expected_error else RuntimeError
        with pytest.raises(error):
            viewer.prepare(wait=True)
        path = "/shared-data/v1/adjusted-daily-v1/symbols"
    else:
        path = "/shared-data/v1/adjusted-daily-v1/series/2330"
    client = _client(viewer)
    if expected_error:
        assert client.get(path).status_code == 503
    else:
        with pytest.raises(RuntimeError, match="unexpected programming failure"):
            client.get(path)


@pytest.mark.parametrize(
    ("manifest", "securities", "analyzed"),
    [
        ({"schema_version": "feature-discrimination-atlas.v1", "tables": [{"security_id": "A"}, {"security_id": "A"}, {"security_id": "B"}]}, 2, None),
        ({"schema_version": "hhhl-probability.v4", "counts": {"securities": 7}}, 7, None),
        ({"schema_version": "market-context-manifest.v2", "security_id": "TEST"}, 1, None),
        ({"schema_version": "opportunity-local-history-preview.v1", "security_count": 8, "analyzed_security_count": 6}, 8, 6),
        ({"schema": "research-data-bundle.v1"}, None, None),
        ({"schema_version": "unknown", "security_count": 99}, None, None),
        ({"schema_version": "hhhl-probability.v4", "counts": {"securities": True}}, None, None),
    ],
)
def test_manifest_metadata_uses_schema_specific_counts_without_opening_members(
    tmp_path: Path, manifest: dict[str, Any], securities: int | None, analyzed: int | None
) -> None:
    path = tmp_path / "manifest.json"
    write_json(path, {**manifest, "artifacts": [{"path": "nonexistent-payload.parquet", "sha256": "not-a-real-hash"}]})
    result = shared_data_view.manifest_metadata(path, file_digest(path))
    assert result["security_count"] == securities
    assert result["analyzed_security_count"] == analyzed
    assert result["columns"] is None
    assert result["manifest_member_count"] == 1
    assert "artifacts" not in result


def test_catalog_enrichment_keeps_entries_with_missing_or_mismatched_manifests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "good.json"
    write_json(path, {"schema": "synthetic", "columns": ["Code", "Date"], "counts": {"rows": 99}})
    entries = [
        {"data_id": "good", "manifest": {"scope": "data", "path": "good.json", "sha256": file_digest(path)}},
        {"data_id": "mismatch", "manifest": {"scope": "data", "path": "good.json", "sha256": "0" * 64}},
        {"data_id": "absent", "manifest": {"scope": "data", "path": "absent.json", "sha256": "0" * 64}},
    ]
    roots = SimpleNamespace(artifact_path=lambda scope, name: tmp_path / name)
    store = SimpleNamespace(roots=roots, read=lambda: {"version_id": "synthetic", "entries": entries, "retired": []})
    monkeypatch.setattr(shared_data_view, "history_data_roots", lambda: roots)
    monkeypatch.setattr(shared_data_view, "DataCatalog", lambda roots: store)
    monkeypatch.setattr(shared_data_view, "discovery_labels", lambda: {"good": {"display_title": "測試資料", "purpose": "測試用途"}})
    result, error = shared_data_view.catalog_summary()
    assert error is None and result is not None
    good, mismatch, absent = result["entries"]
    assert good["viewer_metadata"]["columns"] == ["Code", "Date"]
    assert good["viewer_metadata"]["security_count"] is None
    assert good["metadata_error"] is None
    assert good["display_title"] == "測試資料" and good["purpose"] == "測試用途"
    for failed in (mismatch, absent):
        assert failed["viewer_metadata"] is None and failed["metadata_error"]
    assert "viewer_metadata" not in entries[0], "enrichment must not mutate catalog records"


def test_manifest_dictionary_inventory_counts_members_without_opening_them(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    write_json(
        path,
        {
            "schema_version": "hhhl-probability.v4",
            "artifacts": {"events.parquet": {"sha256": "synthetic"}, "summary.json": {"sha256": "synthetic"}},
        },
    )
    assert shared_data_view.manifest_metadata(path, file_digest(path))["manifest_member_count"] == 2


def test_manifest_changed_during_read_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "manifest.json"
    write_json(path, {"schema": "synthetic"})
    digest = file_digest(path)
    read = shared_data_view.read_json

    def changing(source: Path, **kwargs: Any) -> Any:
        result = read(source, **kwargs)
        source.write_text('{"schema":"changed"}', encoding="utf-8")
        return result

    monkeypatch.setattr(shared_data_view, "read_json", changing)
    with pytest.raises(ValueError, match="changed during"):
        shared_data_view.manifest_metadata(path, digest)


def test_oversized_manifest_is_refused_before_hashing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "manifest.json"
    with path.open("wb") as stream:
        stream.truncate(2_000_001)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("oversized manifest must not be hashed")

    monkeypatch.setattr(shared_data_view, "file_digest", forbidden)
    with pytest.raises(ValueError, match="size limit"):
        shared_data_view.manifest_metadata(path, "0" * 64)


def test_symbol_names_share_one_deadline_across_probes_and_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "symbol_meta.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE symbol_meta (code TEXT, name TEXT, market TEXT)")
    connection.execute("INSERT INTO symbol_meta VALUES ('2330', 'Synthetic', 'TEST')")
    connection.commit()
    connection.close()
    clock = [100.0]
    monkeypatch.setattr(shared_data_view, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(shared_data_view, "producer_data_root", lambda: tmp_path)
    probes: list[float] = []
    sqlite_budgets: list[float] = []
    original = live_producer.readonly_sqlite

    def idle(*, task_timeout: float) -> None:
        probes.append(task_timeout)
        clock[0] += 1.0

    def connect(source: Path, *, timeout: float) -> sqlite3.Connection:
        sqlite_budgets.append(timeout)
        clock[0] += 2.0
        return original(source, timeout=timeout)

    monkeypatch.setattr(live_producer, "assert_producer_idle", idle)
    monkeypatch.setattr(live_producer, "readonly_sqlite", connect)
    assert shared_data_view.symbol_names() == {"2330": ("Synthetic", "TEST")}
    assert probes == [5.0, 2.0]
    assert sqlite_budgets == [4.0]


def test_symbol_names_sqlite_progress_deadline_interrupts_and_closes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    closed: list[bool] = []
    handlers: list[Any] = []

    class Connection:
        row_factory: Any = None

        def set_progress_handler(self, callback: Any, steps: int) -> None:
            assert steps > 0
            handlers.append(callback)

        def execute(self, query: str) -> Any:
            assert handlers[0]() == 0
            clock[0] = 105.0
            assert handlers[0]() != 0, "SQLite work must stop at the overall deadline"
            raise sqlite3.OperationalError("interrupted")

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(shared_data_view, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(shared_data_view, "producer_data_root", lambda: tmp_path)
    monkeypatch.setattr(live_producer, "assert_producer_idle", lambda **kwargs: None)
    monkeypatch.setattr(live_producer, "readonly_sqlite", lambda path, **kwargs: Connection())
    monkeypatch.setattr(live_producer, "read_stable", lambda path, read: read(path))
    assert shared_data_view.symbol_names() == {}
    assert closed == [True]


def test_symbol_names_expired_probe_budget_prevents_sqlite_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]

    def idle(**kwargs: Any) -> None:
        clock[0] = 105.0

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("expired I/O budget must not start a SQLite read")

    monkeypatch.setattr(shared_data_view, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(shared_data_view, "producer_data_root", lambda: tmp_path)
    monkeypatch.setattr(live_producer, "assert_producer_idle", idle)
    monkeypatch.setattr(live_producer, "read_stable", lambda path, read: read(path))
    monkeypatch.setattr(live_producer, "readonly_sqlite", forbidden)
    assert shared_data_view.symbol_names() == {}
