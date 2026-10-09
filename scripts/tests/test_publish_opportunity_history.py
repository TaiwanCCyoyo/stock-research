from __future__ import annotations

import gzip
import hashlib
import json
import random
import shutil
from pathlib import Path

import pytest

from scripts import publish_opportunity_history as publication
from scripts.publish_opportunity_history import publish_catalog, restore_catalog


def fixture(root: Path) -> dict[str, bytes]:
    root.mkdir()
    extras = {}
    for name in ("sources", "gaps", "classifications"):
        raw = ('{ "rows": [{"reason": "未知\u3000availability"}] }\r\n').encode()
        (root / f"{name}.json").write_bytes(raw)
        extras[name] = {"path": f"{name}.json", "sha256": hashlib.sha256(raw).hexdigest()}
    manifest = {
        "schema_version": "opportunity-local-history-preview.v1",
        "extras": extras,
        "series": {"A": {"path": "series/A.json.gz"}},
        "calendar": {"path": "series/calendar.json"},
        "tables": {},
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (root / "series-manifest.json").write_bytes(b'{"schema_version":"opportunity-series-manifest.v1", "rows":[]}\n')
    for directory in ("series", "inputs", "native", "chunks"):
        (root / directory).mkdir()
        (root / directory / "local-only.json.gz").write_bytes(b"local sentinel")
    return {path.name: path.read_bytes() for path in root.glob("*.json")}


def test_exact_bytes_hashes_originals_and_truthful_git_restore(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    original = fixture(root)
    index = publish_catalog(root)
    assert len(index["publications"]) == 5
    assert not index["local_only_artifacts_available_from_publication"]
    for ref in index["publications"]:
        compressed = (root / ref["path"]).read_bytes()
        assert hashlib.sha256(compressed).hexdigest() == ref["sha256"]
        assert gzip.decompress(compressed) == original[ref["original_path"]]
        assert hashlib.sha256(original[ref["original_path"]]).hexdigest() == ref["decoded_sha256"] == ref["original_sha256"]
        assert (root / ref["original_path"]).read_bytes() == original[ref["original_path"]]
        assert len(compressed) <= 450_000
    checkout = tmp_path / "git-checkout"
    checkout.mkdir()
    for ref in index["publications"]:
        shutil.copyfile(root / ref["path"], checkout / ref["path"])
    shutil.copyfile(root / "bundle-index.json", checkout / "bundle-index.json")
    restored = tmp_path / "restored"
    result = restore_catalog(checkout / "bundle-index.json", restored)
    assert not result["local_only_artifacts_available"]
    assert result["recovery_gaps"]
    assert not (restored / "series/A.json.gz").exists()
    assert not (restored / "inputs").exists()
    assert not (restored / "chunks").exists()
    assert not result["tables_restored"] and not result["prices_restored"] and not result["fits_restored"]
    assert "chunks/**" in index["local_only_patterns"]
    for name, raw in original.items():
        assert (restored / name).read_bytes() == raw
    with pytest.raises(FileExistsError):
        restore_catalog(checkout / "bundle-index.json", restored)
    with pytest.raises(FileExistsError):
        publish_catalog(root)


def test_existing_mirror_refusal_preflight_preserves_originals(tmp_path: Path) -> None:
    original = fixture(tmp_path / "catalog")
    root = tmp_path / "catalog"
    (root / "sources.json.gz").write_bytes(b"preexisting")
    with pytest.raises(FileExistsError):
        publish_catalog(root)
    assert not (root / "manifest.json.gz").exists()
    assert (root / "sources.json.gz").read_bytes() == b"preexisting"
    assert all((root / name).read_bytes() == raw for name, raw in original.items())


def test_impossible_part_limit_refused_without_partial_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "catalog"
    fixture(root)
    monkeypatch.setattr(publication, "MAX_MIRROR_BYTES", 10)
    with pytest.raises(ValueError, match="Publication part exceeds"):
        publish_catalog(root)
    assert not (root / "bundle-index.json").exists()
    assert not list(root.glob("*.json.gz"))


def large_manifest(root: Path) -> bytes:
    fixture(root)
    prefix = b'{"padding":"'
    raw = prefix + b"x" * (publication.PART_RAW_BYTES - 1 - len(prefix))
    raw += "界".encode() + random.Random(0).randbytes(700_000).hex().encode()
    raw += b'",' + (root / "manifest.json").read_bytes()[1:]
    (root / "manifest.json").write_bytes(raw)
    return raw


def test_multipart_unicode_boundary_exact_bytes_and_manifest_restore(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    raw = large_manifest(root)
    index = publish_catalog(root)
    primary = index["primary_manifest"]
    assert index["schema_version"] == "opportunity-publication-index.v2"
    assert primary["format"] == "gzip-multipart-rawbytes" and primary["restore_required"]
    assert "path" not in primary
    assert index["metadata_file_count"] == 5 and index["multipart_metadata_count"] == 1
    assert index["mirror_file_count"] == 4 + len(primary["parts"])
    decoded_parts = []
    for number, part in enumerate(primary["parts"]):
        data = (root / part["path"]).read_bytes()
        assert len(data) == part["size_bytes"] <= 450_000
        assert hashlib.sha256(data).hexdigest() == part["sha256"]
        decoded = gzip.decompress(data)
        assert part["raw_offset"] == number * publication.PART_RAW_BYTES
        assert len(decoded) == part["raw_length"] <= 256 * 1024
        assert hashlib.sha256(decoded).hexdigest() == part["decoded_sha256"]
        decoded_parts.append(decoded)
    with pytest.raises(UnicodeDecodeError):
        decoded_parts[0].decode("utf-8")
    assert b"".join(decoded_parts) == raw
    assert (root / "manifest.json").read_bytes() == raw
    restore_catalog(root / "bundle-index.json", tmp_path / "restored")
    assert (tmp_path / "restored/manifest.json").read_bytes() == raw
    with pytest.raises(FileExistsError):
        publish_catalog(root)


@pytest.mark.parametrize("tamper", ["compressed", "offset", "decoded_hash", "full_hash", "schema"])
def test_multipart_corruption_refused_before_restore(tmp_path: Path, tamper: str) -> None:
    root = tmp_path / "catalog"
    large_manifest(root)
    index = publish_catalog(root)
    ref = next(item for item in index["publications"] if item["original_path"] == "manifest.json")
    if tamper == "compressed":
        (root / ref["parts"][0]["path"]).write_bytes(b"corrupt")
    elif tamper == "offset":
        ref["parts"][1]["raw_offset"] += 1
    elif tamper == "decoded_hash":
        ref["parts"][0]["decoded_sha256"] = "wrong"
    elif tamper == "full_hash":
        ref["original_sha256"] = "wrong"
    else:
        ref["schema_version"] = "wrong"
    (root / "bundle-index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(ValueError):
        restore_catalog(root / "bundle-index.json", tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_required_extra_hash_and_corrupt_mirror_rejected(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    fixture(root)
    (root / "gaps.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="extra hash mismatch"):
        publish_catalog(root)
    other = tmp_path / "other"
    fixture(other)
    publish_catalog(other)
    (other / "manifest.json.gz").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="mirror hash/size mismatch"):
        restore_catalog(other / "bundle-index.json", tmp_path / "restore")
    assert not (tmp_path / "restore").exists()
