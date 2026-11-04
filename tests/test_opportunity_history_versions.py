"""Artificial registered versions; real path/hash/cache gates, no market inputs.

The native research-semantic validators are isolated here: they have their own
frozen-publication tests. This fixture exercises HTTP selection and byte identity,
not certification of an invented market study.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api.history import history_router
from research_core import opportunity_history_store as stores
from research_core.opportunity_history_bundle import BundleUnavailable, catalog_entry
from research_core.opportunity_history_versions import HistoryVersions, history_pin
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_paths import DATA_ROOT_ENV, DataRoots
from scripts.query_opportunity_history import calendar_content_id

DAY = "2020-01-02"
BASE = "/opportunity-history/v1"


def save(root: Path, name: str, value: Any) -> dict[str, str]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(payload)
    return {"path": name, "sha256": hashlib.sha256(payload).hexdigest()}


def registered(roots: DataRoots, version: str, price: float) -> tuple[dict[str, str], Path]:
    root = roots.data / "patterns/opportunity-history-web" / version / "catalog-v2"
    calendar: dict[str, Any] = {"dates": [DAY, "2020-01-03"]}
    calendar["calendar_id"] = calendar_content_id(calendar)
    calendar_ref = save(root, "calendar.json", calendar)
    series = {
        "code": "SYNTH",
        "security_id": "synthetic-stock",
        "series_id": f"synthetic-series-{price}",
        "calendar_id": calendar["calendar_id"],
        "raw": [price, price + 1],
        "adjusted": [price, price + 1],
    }
    series_ref = save(root, "series.json", series)
    producer = {"input_receipt_sha256": "1" * 64}
    native = {
        "schema_version": "opportunity-native-results.v1",
        "security_id": series["security_id"],
        "series_id": series["series_id"],
        "calendar_id": calendar["calendar_id"],
        "input_identity": {"series_sha256": series_ref["sha256"], "calendar_sha256": calendar_ref["sha256"]},
        "code_identity": {"synthetic": True},
        "native": [
            {"method": method, "scale": scale, "status": "error", "error": "synthetic fixture has no native analysis"}
            for method in ("segments", "filter")
            for scale in ("fine", "balanced", "coarse")
        ],
    }
    native_ref: dict[str, Any] = save(root, "native.json", native)
    native_ref["receipt"] = save(
        root,
        "receipt.json",
        {
            "schema_version": "opportunity-native-receipt.v1",
            "sha256": native_ref["sha256"],
            "context": producer,
            "security_id": series["security_id"],
            "series_id": series["series_id"],
        },
    )
    securities = [{"code": "SYNTH", "name": "Synthetic only", "stock_opportunity_eligible": True}]
    manifest = {
        "schema_version": "synthetic-history-fixture.v1",
        "catalog_revision": "synthetic-v1",
        "adapter_revision": "synthetic",
        "gain_policy": "synthetic",
        "price_basis": "synthetic",
        "rule": "synthetic",
        "selector": "synthetic",
        "task": "synthetic-history-versions",
        "window": {"start": DAY, "end": "2020-01-03"},
        "analyzed_security_count": 1,
        "security_count": 1,
        "calendar_id": calendar["calendar_id"],
        "calendar": calendar_ref,
        "source_manifest": {"sha256": "2" * 64},
        "series_manifest": {"sha256": "3" * 64},
        "producer_identity": producer,
        "code_identity": native["code_identity"],
        "series": {"SYNTH": series_ref},
        "native": {"SYNTH": native_ref},
        "tables": {
            "securities": save(root, "securities.json", {"rows": securities}),
            "representative_intervals": save(root, "intervals.json", {"rows": []}),
            "baseline_waves": save(root, "waves.json", {"rows": []}),
        },
        "extras": {"classifications": save(root, "classifications.json", {"rows": []})},
    }
    ref = save(root, "manifest.json", manifest)
    entry = catalog_entry(manifest, version)
    entry["manifest"]["sha256"] = ref["sha256"]
    DataCatalog(roots).register([entry])
    return {"version_id": version, "manifest_sha256": ref["sha256"]}, root


Environment = tuple[DataRoots, HistoryVersions, TestClient, dict[str, str], dict[str, str], Path, Path]


@pytest.fixture
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Environment:
    (tmp_path / "primary/.git").mkdir(parents=True)
    roots = DataRoots.from_env({DATA_ROOT_ENV: str(tmp_path / "primary/research_data")})
    monkeypatch.setattr(stores, "validate_manifest_identity", lambda _manifest: {})
    monkeypatch.setattr(stores, "_validate_query_inputs", lambda *_args: None)
    monkeypatch.setattr(stores, "validate_query_tables", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(stores, "expected_source_runs", lambda _manifest: {"SYNTH": [0, 0]})
    monkeypatch.setattr(stores, "_selected_native", lambda _manifest, root, *_args: (json.loads((root / "native.json").read_bytes()), None, None))
    monkeypatch.setattr(
        stores,
        "build_frame",
        lambda catalog, date: {
            "schema": stores.SCHEMA,
            "catalogId": catalog["id"],
            "date": date,
            "rows": [{"code": "SYNTH", "raw": catalog["series"]["SYNTH"]["raw"][0]}],
        },
    )
    monkeypatch.setattr(stores, "WEB_STARTUP_CACHE", tmp_path / "startup-cache")
    monkeypatch.setattr(stores, "WEB_RECEIPT_CACHE", tmp_path / "receipt-cache")
    first, root_a = registered(roots, "synthetic/version-a", 10)
    second, root_b = registered(roots, "synthetic/version-b", 100)
    versions = HistoryVersions(roots=roots)
    app = FastAPI()
    app.include_router(history_router(versions=versions))
    return roots, versions, TestClient(app), first, second, root_a, root_b


def load(versions: HistoryVersions, pin: dict[str, str]) -> stores.HistoryStore:
    return versions.select(**pin).provider.get()


def test_two_registered_versions_bind_metadata_frames_details_and_status(environment: Environment) -> None:
    _, versions, client, first, second, _, _ = environment
    a, b = load(versions, first), load(versions, second)
    assert a is not b
    for pin, price in ((first, 10), (second, 100), (first, 10)):
        identity = {"versionId": pin["version_id"], "manifestSha256": pin["manifest_sha256"]}
        for path in ("/status", "/metadata", "/frame", "/security/SYNTH"):
            response = client.get(BASE + path, params=pin | {"date": DAY})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["bundleIdentity"] == identity
            if "catalogId" in result:
                assert result["catalogId"] == pin["manifest_sha256"]
            if path == "/frame":
                assert result["rows"][0]["raw"] == price
            if path == "/security/SYNTH":
                assert result["sample"]["points"][0]["raw"] == price


@pytest.mark.parametrize("path", ["/metadata", "/status", "/frame", "/directory", "/options", "/membership", "/security/SYNTH"])
def test_every_endpoint_rejects_partial_unknown_or_mismatched_pins(environment: Environment, path: str) -> None:
    _, _, client, first, second, _, _ = environment
    valid = {"date": DAY, "code": "SYNTH"}
    for bad in ({"version_id": first["version_id"]}, {"manifest_sha256": first["manifest_sha256"]}, first | {"version_id": "../escape"}):
        assert client.get(BASE + path, params=valid | bad).status_code == 422
    for bad in (first | {"version_id": "not-registered"}, first | {"manifest_sha256": second["manifest_sha256"]}):
        response = client.get(BASE + path, params=valid | bad)
        assert response.status_code == 503
        assert "Retry-After" not in response.headers


def test_duplicate_identity_and_noncanonical_digest_are_not_ambiguous(environment: Environment) -> None:
    _, _, client, first, _, _, _ = environment
    assert client.get(BASE + "/metadata", params=[*first.items(), ("version_id", "other")]).status_code == 422
    assert client.get(BASE + "/metadata", params=first | {"manifest_sha256": "invalid"}).status_code == 422


@pytest.mark.parametrize("change", ["missing", "tampered", "manifest"])
def test_unread_version_fails_closed_on_missing_or_changed_members(environment: Environment, change: str) -> None:
    _, versions, client, first, second, _, root_b = environment
    load(versions, first)
    if change == "missing":
        (root_b / "series.json").unlink()
    elif change == "tampered":
        (root_b / "series.json").write_text('{"tampered":true}', encoding="utf-8")
    else:
        (root_b / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises((BundleUnavailable, ValueError, OSError)):
        load(versions, second)
    response = client.get(BASE + "/metadata", params=second)
    assert response.status_code == 503 and "Retry-After" not in response.headers
    assert client.get(BASE + "/frame", params=first | {"date": DAY}).json()["rows"][0]["raw"] == 10


def test_detail_rechecks_disk_bytes_while_verified_memory_remains_immutable(environment: Environment) -> None:
    _, versions, client, first, _, root_a, _ = environment
    load(versions, first)
    (root_a / "series.json").write_text('{"changed":true}', encoding="utf-8")
    response = client.get(BASE + "/security/SYNTH", params=first | {"date": DAY})
    assert response.status_code == 503
    assert client.get(BASE + "/frame", params=first | {"date": DAY}).json()["rows"][0]["raw"] == 10


def test_registry_is_bounded_and_same_manifest_aliases_keep_full_identity(environment: Environment) -> None:
    roots, _, _, first, _, _, _ = environment
    alias, _ = registered(roots, "synthetic/alias", 10)
    assert alias["manifest_sha256"] == first["manifest_sha256"]
    versions = HistoryVersions(roots=roots, capacity=2)
    a, b = load(versions, first), load(versions, alias)
    assert a is not b and a.bundle_identity != b.bundle_identity
    assert a._startup_context(lambda *_: None)["version"] == first["version_id"]
    assert b._startup_context(lambda *_: None)["version"] == alias["version_id"]
    with pytest.raises(BundleUnavailable, match="capacity"):
        versions.select("third", "0" * 64)
    assert versions.select(**first).provider.get() is a


@pytest.mark.parametrize("version", ["", " ", "/absolute", "a//b", "a/../b", "a/./b", "a\\b", "C:alias", "a\x00b"])
def test_pin_rejects_unsafe_version_names(version: str) -> None:
    with pytest.raises(ValueError):
        history_pin(version, "a" * 64)


def test_pin_normalizes_digest_but_retains_registered_relative_version() -> None:
    assert history_pin("synthetic/version-a", "A" * 64) == ("synthetic/version-a", "a" * 64)
    assert history_pin(None, None) is None


def test_failed_reader_is_not_retried_and_other_version_remains_available(environment: Environment) -> None:
    _, versions, _, first, second, root_a, _ = environment
    selected = versions.select(**first)
    original = (root_a / "series.json").read_bytes()
    (root_a / "series.json").write_bytes(b"{}")
    with pytest.raises(ValueError):
        selected.provider.get()
    (root_a / "series.json").write_bytes(original)
    assert versions.select(**first) is selected
    assert selected.provider.status()["state"] == "failed"
    with pytest.raises(RuntimeError, match="unavailable"):
        selected.provider.get()
    assert load(versions, second).frame(DAY)["rows"][0]["raw"] == 100


def test_registered_pin_reuses_loaded_default_snapshot_and_capture(environment: Environment) -> None:
    roots, _, _, first, _, root_a, _ = environment
    default = stores.LazyHistoryStore(root_a.parent, first["manifest_sha256"], version_id=first["version_id"])
    snapshot = default.get()
    versions = HistoryVersions(default, roots=roots)
    selected = versions.select(**first)
    assert selected is versions.default
    assert selected.provider.get() is snapshot
    assert versions.select(**first) is selected


@pytest.mark.parametrize("mismatch", ["path", "version", "digest"])
def test_default_reuse_requires_complete_identity(environment: Environment, mismatch: str) -> None:
    roots, _, _, first, second, root_a, root_b = environment
    default = stores.LazyHistoryStore(root_a.parent, first["manifest_sha256"], version_id=first["version_id"])
    default.get()
    if mismatch == "path":
        default.bundle = root_b.parent
    elif mismatch == "version":
        default.version_id = "synthetic/other-alias"
    else:
        default.expected_sha = second["manifest_sha256"]
    versions = HistoryVersions(default, roots=roots)
    assert versions.select(**first).provider is not default


def test_default_cannot_authorize_an_unregistered_pin(environment: Environment) -> None:
    roots, _, _, first, _, root_a, _ = environment
    default = stores.LazyHistoryStore(root_a.parent, first["manifest_sha256"], version_id="not-registered")
    default.get()
    versions = HistoryVersions(default, roots=roots)
    with pytest.raises(BundleUnavailable):
        versions.select("not-registered", first["manifest_sha256"])


def test_same_digest_alias_does_not_reuse_default(environment: Environment) -> None:
    roots, _, _, first, _, root_a, _ = environment
    alias, _ = registered(roots, "synthetic/alias", 10)
    default = stores.LazyHistoryStore(root_a.parent, first["manifest_sha256"], version_id=first["version_id"])
    default.get()
    versions = HistoryVersions(default, roots=roots)
    assert versions.select(**alias).provider is not default
    assert versions.select(**first).provider is default


def test_injected_provider_is_not_reused_for_registered_pin(environment: Environment) -> None:
    class InjectedProvider(stores.LazyHistoryStore):
        pass

    roots, _, _, first, _, root_a, _ = environment
    default = InjectedProvider(root_a.parent, first["manifest_sha256"], version_id=first["version_id"])
    default.get()
    versions = HistoryVersions(default, roots=roots)
    assert versions.select(**first).provider is not default
