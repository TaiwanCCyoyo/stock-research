"""Regressions for authenticated memo reuse and nonblocking initialization."""

from __future__ import annotations

import gzip
import json
import threading
from pathlib import Path

import pytest

from research_core.opportunity_history_store import HistoryLoading, LazyHistoryStore
from research_core.opportunity_startup_cache import StartupCache


def test_startup_context_checks_current_dependency_bytes_and_ignores_archival_links(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    from research_core.opportunity_history_store import HistoryStore

    price = tmp_path / "price.json"
    price.write_bytes(b"{}")
    ref = {"path": "price.json", "sha256": hashlib.sha256(price.read_bytes()).hexdigest()}
    store = HistoryStore.__new__(HistoryStore)
    store.identity = "external-pin"
    monkeypatch.setattr(store, "_path", lambda reference: tmp_path / reference["path"])
    store.manifest = {
        "calendar": ref,
        "series": {"2609": ref},
        "native": {"2609": ref},
        "tables": {name: ref for name in ("securities", "representative_intervals", "baseline_waves")},
        "extras": {"classifications": ref, "archivalPublication": {"path": "absent.json", "sha256": "0" * 64}},
    }
    context = store._startup_context(lambda *args: None)
    assert context["manifest"] == "external-pin"
    assert store._startup_context(lambda *args: None) == context
    price.write_bytes(b'{"changed":true}')
    with pytest.raises(ValueError, match="dependency hash mismatch"):
        store._startup_context(lambda *args: None)


def test_memo_requires_matching_sources_and_implementation(tmp_path: Path) -> None:
    cache = StartupCache(tmp_path / "memo")
    context = {"manifest": "pinned", "sources": "current-bytes", "implementation": "v1"}
    result = {"series": {"2609": {"raw": [20.0]}}, "nativeDisplay": {}}
    assert cache.load(context) is None
    cache.save(context, result)
    assert cache.load(context) == result
    assert cache.load(context | {"sources": "changed-price"}) is None
    assert cache.load(context | {"implementation": "v2"}) is None
    assert cache.load(context | {"manifest": "another-snapshot"}) is None


def test_edited_cache_cannot_mint_verified_projection(tmp_path: Path) -> None:
    cache = StartupCache(tmp_path)
    context = {"manifest": "pinned"}
    cache.save(context, {"series": {"2609": [10]}})
    path = cache._path(context)
    payload = path.read_bytes()
    envelope = json.loads(gzip.decompress(payload[65:]))
    envelope["projection"]["series"]["2609"] = [1000]
    # A forger can rewrite both the payload and ordinary public checksums.
    path.write_bytes(payload[:65] + gzip.compress(json.dumps(envelope).encode()))
    assert cache.load(context) is None


@pytest.mark.parametrize("corruption", [b"", b"garbage", b"0" * 65])
def test_corrupt_memo_is_only_a_cache_miss(tmp_path: Path, corruption: bytes) -> None:
    cache = StartupCache(tmp_path)
    context = {"manifest": "pinned"}
    cache.save(context, {"series": {}})
    cache._path(context).write_bytes(corruption)
    assert cache.load(context) is None


def test_missing_or_changed_private_cache_key_requires_revalidation(tmp_path: Path) -> None:
    cache = StartupCache(tmp_path)
    context = {"manifest": "pinned"}
    cache.save(context, {"series": {}})
    (tmp_path / "authentication.bin").write_bytes(b"x" * 32)
    assert cache.load(context) is None


def test_compressible_projection_can_exceed_file_limit_and_expansion_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import research_core.opportunity_startup_cache as module

    monkeypatch.setattr(module, "MAX_FILE_BYTES", 1024)
    monkeypatch.setattr(module, "MAX_DECODED_BYTES", 10000)
    cache = StartupCache(tmp_path)
    context = {"manifest": "pinned"}
    result = {"series": {"2609": [0] * 2000}}
    cache.save(context, result)
    assert cache.load(context) == result
    monkeypatch.setattr(module, "MAX_DECODED_BYTES", 1024)
    assert cache.load(context) is None


def test_failed_memo_replace_and_cleanup_leave_verified_history_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import research_core.opportunity_history_store as history_module
    import research_core.opportunity_startup_cache as cache_module

    cache = StartupCache(tmp_path)
    context = {"manifest": "pinned"}
    previous = {"series": {"2609": [10]}}
    cache.save(context, previous)
    original_bytes = cache._path(context).read_bytes()
    original_replace, original_unlink = cache_module.os.replace, Path.unlink

    def refuse_replace(source: str | Path, destination: str | Path) -> None:
        if Path(source).name.startswith(".startup-"):
            raise PermissionError("temporary memo is locked")
        original_replace(source, destination)

    def refuse_cleanup(path: Path, missing_ok: bool = False) -> None:
        if path.name.startswith(".startup-"):
            raise PermissionError("temporary memo cleanup is locked")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(cache_module.os, "replace", refuse_replace)
    monkeypatch.setattr(Path, "unlink", refuse_cleanup)

    class VerifiedStore:
        def __init__(self, *args: object, **kwargs: object) -> None:
            cache.save(context, {"series": {"2609": [20]}})

    monkeypatch.setattr(history_module, "HistoryStore", VerifiedStore)
    provider = LazyHistoryStore()
    provider.start()
    assert provider._worker is not None
    provider._worker.join(2)
    assert not provider._worker.is_alive()
    assert provider.status()["state"] == "ready"
    assert provider.get_ready() is provider.store
    assert cache._path(context).read_bytes() == original_bytes
    assert cache.load(context) == previous


def test_background_initialization_has_one_worker_and_no_partial_store(monkeypatch: pytest.MonkeyPatch) -> None:
    import research_core.opportunity_history_store as module

    entered, finish = threading.Event(), threading.Event()
    calls: list[int] = []

    class SlowStore:
        def __init__(self, *args: object, **kwargs: object) -> None:
            calls.append(1)
            entered.set()
            assert finish.wait(5)

    monkeypatch.setattr(module, "HistoryStore", SlowStore)
    provider = LazyHistoryStore()
    with pytest.raises(HistoryLoading):
        provider.get_ready()
    assert entered.wait(2)
    for _ in range(5):
        with pytest.raises(HistoryLoading):
            provider.get_ready()
    assert provider.status()["state"] == "loading"
    assert provider.store is None
    finish.set()
    assert provider._worker is not None
    provider._worker.join(2)
    assert provider.status()["state"] == "ready"
    assert provider.get_ready() is provider.store
    assert calls == [1]


def test_failed_background_snapshot_is_not_retried(tmp_path: Path) -> None:
    provider = LazyHistoryStore(tmp_path)
    with pytest.raises(HistoryLoading):
        provider.get_ready()
    assert provider._worker is not None
    provider._worker.join(2)
    assert provider.status()["state"] == "failed"
    with pytest.raises(RuntimeError, match="unavailable"):
        provider.get_ready()
    original = provider._worker
    provider.start()
    assert provider._worker is original
