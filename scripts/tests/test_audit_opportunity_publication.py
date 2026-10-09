from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import audit_opportunity_publication as audit_module
from scripts.audit_opportunity_publication import audit_publication


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fixture_publication(root: Path, *, receipt_payload_sha: str | None = None) -> tuple[Path, str]:
    root.mkdir()
    native = gzip.compress(b'{"native":[],"kept":"exact original bytes"}', mtime=0)
    receipt = json.dumps({"sha256": receipt_payload_sha or sha(native)}).encode()
    (root / "native.json.gz").write_bytes(native)
    (root / "native.receipt.json").write_bytes(receipt)
    manifest = json.dumps(
        {
            "native": {
                "測試": {
                    "path": "native.json.gz",
                    "sha256": sha(native),
                    "receipt": {"path": "native.receipt.json", "sha256": sha(receipt)},
                }
            },
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    path = root / "manifest.json"
    path.write_bytes(manifest)
    cut = len(manifest) // 2
    parts = []
    for index, (offset, decoded) in enumerate(((0, manifest[:cut]), (cut, manifest[cut:]))):
        compressed = gzip.compress(decoded, mtime=0)
        name = f"manifest.part-{index:05}.json.gz"
        (root / name).write_bytes(compressed)
        parts.append({
            "path": name,
            "raw_offset": offset,
            "raw_length": len(decoded),
            "sha256": sha(compressed),
            "decoded_sha256": sha(decoded),
            "size_bytes": len(compressed),
        })
    bundle = {
        "primary_manifest": {
            "parts": parts,
            "original_size_bytes": len(manifest),
            "original_sha256": sha(manifest),
            "decoded_sha256": sha(manifest),
        }
    }
    (root / "bundle-index.json").write_text(json.dumps(bundle), encoding="utf-8")
    return path, sha(manifest)


def test_exact_byte_publication_with_external_prior_pin(tmp_path: Path) -> None:
    path, prior_pin = fixture_publication(tmp_path / "publication 中文")
    receipt = audit_publication(path, expected_manifest_sha256=prior_pin)
    assert receipt["status"] == "verified"
    assert receipt["schema_version"] == "opportunity-native-publication-anchor-audit.v3"
    assert receipt["trusted_manifest_sha256"] == prior_pin
    assert receipt["manifest_trust_policy"] == "caller_pinned"
    assert receipt["manifest_parts_verified"] == 2
    assert "git_preserved_manifest_parts_verified" not in receipt
    assert receipt["native_security_count"] == receipt["native_receipt_count"] == 1
    assert receipt["native_size_bytes"] == (path.parent / "native.json.gz").stat().st_size
    assert receipt["curve_fit_recomputed"] is receipt["pure_wave_launch_phase_recomputed"] is receipt["source_cache_written"] is False
    with pytest.raises(ValueError, match="Manifest trust mismatch"):
        audit_publication(path)


def test_program_identity_tracks_actual_trust_source_and_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, prior_pin = fixture_publication(tmp_path / "publication")
    initial = audit_publication(path, expected_manifest_sha256=prior_pin)
    identity = initial["audit_program_identity"]
    assert identity["entrypoint_sha256"] == initial["audit_script_sha256"] == sha(Path(audit_module.__file__).read_bytes())
    assert identity["trust_module_sha256"] == sha(Path(audit_module.trust_module.__file__).read_bytes())
    assert identity["registered_manifest_sha256"] == audit_module.trust_module.REGISTERED_MANIFEST_SHA256
    mock_source = tmp_path / "trust implementation.py"
    mock_source.write_bytes(b"first trust implementation")
    monkeypatch.setattr(audit_module.trust_module, "__file__", str(mock_source))
    monkeypatch.setattr(audit_module.trust_module, "REGISTERED_MANIFEST_SHA256", "1" * 64)
    changed = audit_publication(path, expected_manifest_sha256=prior_pin)
    assert changed["trusted_manifest_sha256"] == prior_pin
    assert changed["audit_program_identity"]["registered_manifest_sha256"] == "1" * 64
    assert changed["audit_program_identity"]["trust_module_sha256"] == sha(mock_source.read_bytes())
    mock_source.write_bytes(b"second trust implementation")
    revised = audit_publication(path, expected_manifest_sha256=prior_pin)
    assert revised["audit_program_identity"]["trust_module_sha256"] != changed["audit_program_identity"]["trust_module_sha256"]
    assert revised["audit_program_identity"]["entrypoint_sha256"] == identity["entrypoint_sha256"]


def test_alternate_non_git_bundle_records_exact_input_identity(tmp_path: Path) -> None:
    path, prior_pin = fixture_publication(tmp_path / "publication")
    initial = audit_publication(path, expected_manifest_sha256=prior_pin)
    alternate = tmp_path / "alternate non git bundle"
    alternate.mkdir()
    bundle = json.loads(path.with_name("bundle-index.json").read_bytes())
    for index, part in enumerate(bundle["primary_manifest"]["parts"]):
        decoded = gzip.decompress((path.parent / part["path"]).read_bytes())
        compressed = gzip.compress(decoded, mtime=123)
        part["path"] = f"alternate-{index}.gz"
        part["sha256"] = sha(compressed)
        part["size_bytes"] = len(compressed)
        (alternate / part["path"]).write_bytes(compressed)
    index_path = alternate / "different-index.json"
    index_path.write_text(json.dumps(bundle, indent=3), encoding="utf-8")
    changed = audit_publication(path, index_path, expected_manifest_sha256=prior_pin)
    assert changed["status"] == "verified" and changed["trusted_manifest_sha256"] == initial["trusted_manifest_sha256"]
    assert "git_preserved_manifest_parts_verified" not in changed
    assert changed["manifest_parts_verified"] == 2
    assert changed["bundle_identity"]["index_sha256"] == sha(index_path.read_bytes())
    assert changed["bundle_identity"]["index_sha256"] != initial["bundle_identity"]["index_sha256"]
    for actual, original, declared in zip(
        changed["bundle_identity"]["parts"], initial["bundle_identity"]["parts"], bundle["primary_manifest"]["parts"], strict=True
    ):
        assert actual["path"] == declared["path"]
        assert actual["sha256"] == sha((alternate / actual["path"]).read_bytes()) != original["sha256"]
        assert actual["decoded_sha256"] == original["decoded_sha256"]
        assert (actual["raw_offset"], actual["raw_length"]) == (original["raw_offset"], original["raw_length"])


@pytest.mark.parametrize("name", ["native.json.gz", "native.receipt.json", "manifest.part-00000.json.gz"])
def test_tampered_artifact_is_rejected(tmp_path: Path, name: str) -> None:
    path, prior_pin = fixture_publication(tmp_path / "publication")
    (path.parent / name).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Publication hash mismatch"):
        audit_publication(path, expected_manifest_sha256=prior_pin)


def test_receipt_payload_hash_must_bind_native_bytes(tmp_path: Path) -> None:
    path, prior_pin = fixture_publication(tmp_path / "publication", receipt_payload_sha="0" * 64)
    with pytest.raises(ValueError, match="receipt payload hash mismatch"):
        audit_publication(path, expected_manifest_sha256=prior_pin)


@pytest.mark.parametrize("mutation", ["offset", "raw_length", "decoded_sha", "size", "full_sha", "reorder"])
def test_bundle_metadata_cannot_override_exact_reconstruction(tmp_path: Path, mutation: str) -> None:
    path, prior_pin = fixture_publication(tmp_path / "publication")
    index_path = path.with_name("bundle-index.json")
    index: dict[str, Any] = json.loads(index_path.read_bytes())
    primary = index["primary_manifest"]
    if mutation == "offset":
        primary["parts"][0]["raw_offset"] = 1
    elif mutation == "raw_length":
        primary["parts"][0]["raw_length"] += 1
    elif mutation == "decoded_sha":
        primary["parts"][0]["decoded_sha256"] = "0" * 64
    elif mutation == "size":
        primary["original_size_bytes"] += 1
    elif mutation == "full_sha":
        primary["original_sha256"] = "0" * 64
    else:
        primary["parts"].reverse()
    index_path.write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(ValueError, match="Publication"):
        audit_publication(path, expected_manifest_sha256=prior_pin)


def test_cli_arbitrary_cwd_read_only_and_exclusive_receipt(tmp_path: Path) -> None:
    path, prior_pin = fixture_publication(tmp_path / "publication 中文")
    inputs = {file: file.read_bytes() for file in path.parent.iterdir()}
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    script = Path(__file__).resolve().parents[1] / "audit_opportunity_publication.py"
    command = [sys.executable, "-Xutf8", str(script), "--manifest", str(path), "--expected-manifest-sha256", prior_pin]
    output = subprocess.run(command, cwd=elsewhere, capture_output=True, text=True, encoding="utf-8", check=True)
    assert json.loads(output.stdout)["status"] == "verified"
    assert {file: file.read_bytes() for file in path.parent.iterdir()} == inputs
    receipt_path = tmp_path / "new audit receipt.json"
    written = subprocess.run(command + ["--receipt", str(receipt_path)], cwd=elsewhere, capture_output=True, text=True, encoding="utf-8", check=True)
    saved = receipt_path.read_bytes()
    assert json.loads(saved) == json.loads(written.stdout)
    refused = subprocess.run(command + ["--receipt", str(receipt_path)], cwd=elsewhere, capture_output=True, text=True, encoding="utf-8", check=False)
    assert refused.returncode != 0
    assert "opportunity publication audit failed" in refused.stderr
    assert receipt_path.read_bytes() == saved
    assert {file: file.read_bytes() for file in path.parent.iterdir()} == inputs
