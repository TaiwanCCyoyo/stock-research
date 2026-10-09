from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.opportunity_native_receipt_cache as cache
from scripts.opportunity_native_receipt_cache import load_receipt, save_receipt, semantic_receipt_cache

KEY = "a" * 64
RECEIPT = {
    "schema": "opportunity-native-source-semantics.v1",
    "status": "verified",
    "failed_method_count": 0,
    "failed_scopes": [],
    "method_count": 6,
    "wave_count": 12,
    "launch_count": 4,
}
COMPACT_RECEIPT = {
    "schema": "opportunity-native-source-semantics.v1",
    "status": "verified",
    "method_count": 6,
    "wave_count": 12,
    "launch_count": 4,
}


def test_cache_is_opt_in_and_nested_context_restores_parent(tmp_path: Path):
    assert load_receipt(KEY) is None
    save_receipt(KEY, RECEIPT)
    assert not list(tmp_path.iterdir())

    with semantic_receipt_cache(tmp_path):
        save_receipt(KEY, RECEIPT)
        assert load_receipt(KEY) == COMPACT_RECEIPT
        with semantic_receipt_cache(None):
            assert load_receipt(KEY) is None
        assert load_receipt(KEY) == COMPACT_RECEIPT
    assert load_receipt(KEY) is None


def test_cache_envelope_binds_key_and_receipt_digest(tmp_path: Path):
    with semantic_receipt_cache(tmp_path):
        save_receipt(KEY, RECEIPT)
    path = tmp_path / f"{KEY}.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["receipt"] == COMPACT_RECEIPT

    envelope["key"] = "b" * 64
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with semantic_receipt_cache(tmp_path):
        assert load_receipt(KEY) is None

    envelope["key"] = KEY
    envelope["receiptSha256"] = "0" * 64
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with semantic_receipt_cache(tmp_path):
        assert load_receipt(KEY) is None


@pytest.mark.parametrize("bad_key", ["", "g" * 64, "a" * 63, "a" * 65])
def test_cache_rejects_non_sha256_keys(bad_key: str):
    with pytest.raises(ValueError, match="64 hexadecimal"):
        load_receipt(bad_key)
    with pytest.raises(ValueError, match="64 hexadecimal"):
        save_receipt(bad_key, RECEIPT)


def test_partial_and_invalid_count_receipts_are_never_saved(tmp_path: Path):
    partial = RECEIPT | {"status": "partial"}
    with semantic_receipt_cache(tmp_path):
        with pytest.raises(ValueError, match="complete verified"):
            save_receipt(KEY, partial)
        with pytest.raises(ValueError, match="nonnegative integer"):
            save_receipt(KEY, RECEIPT | {"wave_count": True})
    assert not (tmp_path / f"{KEY}.json").exists()


def test_read_and_write_oserror_are_cache_misses(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    with semantic_receipt_cache(tmp_path):
        save_receipt(KEY, RECEIPT)
    with semantic_receipt_cache(tmp_path):
        monkeypatch.setattr(cache, "_regular_file_descriptor", lambda _path: (_ for _ in ()).throw(PermissionError("denied")))
        assert load_receipt(KEY) is None

        monkeypatch.undo()
        monkeypatch.setattr(cache.os, "replace", lambda *_args: (_ for _ in ()).throw(PermissionError("denied")))
        save_receipt("c" * 64, RECEIPT)
    assert not (tmp_path / f"{'c' * 64}.json").exists()
    assert not list(tmp_path.glob(".native-verification-*.tmp"))


def test_damaged_json_is_a_miss(tmp_path: Path):
    (tmp_path / f"{KEY}.json").write_text("{broken", encoding="utf-8")
    with semantic_receipt_cache(tmp_path):
        assert load_receipt(KEY) is None


def test_oversized_cache_entry_is_a_miss_without_parsing(tmp_path: Path):
    (tmp_path / f"{KEY}.json").write_bytes(b" " * (cache.MAX_CACHE_BYTES + 1))
    with semantic_receipt_cache(tmp_path):
        assert load_receipt(KEY) is None
