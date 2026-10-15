"""Pin, catalog resolution and copy-boundary tests on invented data; no live inputs."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_api.history import history_router
from research_core import opportunity_history_bundle as bundle
from research_core import opportunity_history_store as store
from research_core.opportunity_history_bundle import BundleUnavailable
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_paths import DATA_ROOT_ENV, DataRoots


def manifest_fields() -> dict[str, Any]:
    return {
        "schema_version": "opportunity-local-history-preview.v1",
        "catalog_revision": "fixture-revision",
        "adapter_revision": "a" * 64,
        "gain_policy": "fixture-gain",
        "price_basis": "fixture-basis",
        "rule": "fixture-rule",
        "selector": "fixture-selector",
        "task": "fixture-task",
        "window": {"start": "2010-01-04", "end": "2010-01-06"},
        "analyzed_security_count": 2,
        "security_count": 3,
        "calendar_id": "sha256:" + "1" * 64,
        "calendar": {"sha256": "2" * 64},
        "source_manifest": {"sha256": "3" * 64},
        "series_manifest": {"sha256": "4" * 64},
        "producer_identity": {"input_receipt_sha256": "5" * 64},
    }


def make_source(root: Path) -> tuple[Path, str]:
    """A tiny producer directory whose manifest digest is the pin under test."""
    source = root / "producer"
    (source / "runs/native").mkdir(parents=True)
    (source / "catalog-v2/chunks").mkdir(parents=True)
    payload = json.dumps(manifest_fields(), sort_keys=True).encode()
    (source / "catalog-v2/manifest.json").write_bytes(payload)
    (source / "catalog-v2/chunks/a.json.gz").write_bytes(b"invented series")
    (source / "runs/native/1101.json.gz").write_bytes(b"invented native result")
    return source, hashlib.sha256(payload).hexdigest()


@pytest.fixture
def roots(tmp_path: Path) -> DataRoots:
    (tmp_path / "primary/.git").mkdir(parents=True)
    return DataRoots.from_env({DATA_ROOT_ENV: str(tmp_path / "primary/research_data")})


def tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


def restore(source: Path, roots: DataRoots, pin: str, gate: Any = None) -> dict[str, Any]:
    return bundle.restore_bundle(source, roots, gate=gate or (lambda *_: None), expected_manifest_sha256=pin, progress=lambda _message: None)


def test_default_pin_is_the_original_manifest_not_the_rewritten_form() -> None:
    assert store.DEFAULT_SHA == bundle.ORIGINAL_MANIFEST_SHA256 == bundle.BUNDLE_VERSION
    assert store.DEFAULT_SHA.startswith("c7848ae7")


def test_store_accepts_only_the_pinned_manifest_bytes(tmp_path: Path) -> None:
    source, pin = make_source(tmp_path)
    with pytest.raises(ValueError, match="hash mismatch"):
        store.HistoryStore(source, "0" * 64)
    # A matching pin passes the trust gate and proceeds to the next structural check.
    other = b'{"schema_version": "other"}'
    (source / "catalog-v2/manifest.json").write_bytes(other)
    with pytest.raises(ValueError, match="schema_version"):
        store.HistoryStore(source, hashlib.sha256(other).hexdigest())
    with pytest.raises(ValueError, match="hash mismatch"):
        store.HistoryStore(source, pin)


def test_restore_copies_every_byte_and_registers_a_resolvable_entry(tmp_path: Path, roots: DataRoots) -> None:
    source, pin = make_source(tmp_path)
    before = tree(source)
    seen: list[Path] = []
    result = restore(source, roots, pin, gate=lambda staging, sha: seen.append(staging))
    resolved = bundle.resolve_history_bundle(roots, version_id=pin, manifest_sha256=pin)
    assert resolved.path == roots.data / "patterns/opportunity-history-web" / pin
    assert result["files"] == len(before) == 3
    assert tree(source) == before
    copied = tree(resolved.path)
    assert copied.pop("copy-receipt.json")
    assert copied == before
    # The reader gate ran on the staged copy before it was published.
    assert len(seen) == 1 and seen[0].name.startswith(".staging-") and not seen[0].exists()
    entry = DataCatalog(roots).get(bundle.DATA_ID, pin, manifest_sha256=pin)
    assert entry["status"] == "legacy" and entry["reader"] == "metadata_only"
    assert entry["coverage"]["raw_input_period"] == {"start": "2010-01-04", "end": "2010-01-06", "reason": None}
    receipt = json.loads((resolved.path / "copy-receipt.json").read_bytes())
    assert {item["path"] for item in receipt["files"]} == set(before)


def test_restore_refuses_wrong_source_manifest_and_writes_nothing(tmp_path: Path, roots: DataRoots) -> None:
    source, _ = make_source(tmp_path)
    with pytest.raises(ValueError, match="pinned original bytes"):
        restore(source, roots, "0" * 64)
    assert not roots.data.exists()


def test_restore_never_overwrites_an_existing_destination(tmp_path: Path, roots: DataRoots) -> None:
    source, pin = make_source(tmp_path)
    destination = roots.data / "patterns/opportunity-history-web" / pin
    destination.mkdir(parents=True)
    (destination / "keep.json").write_bytes(b"existing evidence")
    with pytest.raises(FileExistsError, match="not overwritten"):
        restore(source, roots, pin)
    assert tree(destination) == {"keep.json": hashlib.sha256(b"existing evidence").hexdigest()}


def test_failed_gate_leaves_staging_for_inspection_and_no_final_directory(tmp_path: Path, roots: DataRoots) -> None:
    source, pin = make_source(tmp_path)

    def reject(*_: object) -> None:
        raise ValueError("Configured catalog manifest hash mismatch")

    with pytest.raises(ValueError, match="hash mismatch"):
        restore(source, roots, pin, gate=reject)
    parent = roots.data / "patterns/opportunity-history-web"
    staged = list(parent.iterdir())
    assert len(staged) == 1 and staged[0].name.startswith(".staging-")
    assert tree(staged[0])["catalog-v2/manifest.json"] == tree(source)["catalog-v2/manifest.json"]
    with pytest.raises(BundleUnavailable):
        bundle.resolve_history_bundle(roots, version_id=pin, manifest_sha256=pin)


def test_source_changing_between_hash_and_copy_is_detected(tmp_path: Path, roots: DataRoots, monkeypatch: pytest.MonkeyPatch) -> None:
    source, pin = make_source(tmp_path)
    real = bundle._copy_member

    def tamper(src: Path, dst: Path, expected: dict[str, Any]) -> None:
        if expected["path"].endswith("a.json.gz"):
            src.write_bytes(b"changed after hashing")
        real(src, dst, expected)

    monkeypatch.setattr(bundle, "_copy_member", tamper)
    with pytest.raises(ValueError, match="changed during copy"):
        restore(source, roots, pin)
    assert not (roots.data / "patterns/opportunity-history-web" / pin).exists()


def test_hardlinked_source_member_is_rejected_before_any_write(tmp_path: Path, roots: DataRoots) -> None:
    source, pin = make_source(tmp_path)
    os.link(source / "runs/native/1101.json.gz", tmp_path / "alias.json.gz")
    with pytest.raises(ValueError, match="hardlinked"):
        restore(source, roots, pin)
    assert not roots.data.exists()


def test_missing_catalog_entry_is_unavailable_not_a_fallback(roots: DataRoots) -> None:
    with pytest.raises(BundleUnavailable):
        bundle.resolve_history_bundle(roots)


def test_unset_data_root_is_reported_without_guessing(tmp_path: Path) -> None:
    with pytest.raises(BundleUnavailable, match="not configured"):
        bundle.history_data_roots(environ={}, repo_root=tmp_path)


def test_data_root_may_come_from_the_primary_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    (primary / ".env.local").write_text(f"{DATA_ROOT_ENV}={primary / 'research_data'}\n", encoding="utf-8")
    monkeypatch.setattr(bundle, "primary_checkout", lambda _repo: primary)
    assert bundle.history_data_roots(environ={}, repo_root=tmp_path).data == primary / "research_data"


def test_dashboard_resolves_through_the_catalog_and_opens_the_pinned_bundle(tmp_path: Path, roots: DataRoots, monkeypatch: pytest.MonkeyPatch) -> None:
    source, pin = make_source(tmp_path)
    restore(source, roots, pin)
    opened: list[tuple[Path, str]] = []

    class Recorder:
        def __init__(self, path: Path, sha: str, **_: object) -> None:
            opened.append((path, sha))

    # The reader gate itself has its own tests; here only the located path and pin matter.
    monkeypatch.setattr(store, "HistoryStore", Recorder)
    monkeypatch.setattr(store, "resolve_history_bundle", lambda: bundle.resolve_history_bundle(roots, version_id=pin, manifest_sha256=pin))
    LazyHistoryStore = store.LazyHistoryStore
    LazyHistoryStore(expected_sha=pin).get()
    assert opened == [(roots.data / "patterns/opportunity-history-web" / pin, pin)]


def test_unavailable_bundle_shows_as_failed_and_503(roots: DataRoots, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATA_ROOT_ENV, str(roots.data))
    provider = store.LazyHistoryStore()
    app = FastAPI()
    app.include_router(history_router(provider))
    client = TestClient(app)
    assert client.get("/opportunity-history/v1/metadata").status_code == 503
    assert provider._worker is not None
    provider._worker.join(timeout=30)
    assert client.get("/opportunity-history/v1/status").json()["state"] == "failed"
