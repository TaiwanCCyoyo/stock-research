from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from research_core.opportunity_history_catalog import RULE, SELECTOR
from scripts import query_opportunity_history as query
from scripts import verify_opportunity_history as verifier


def manifest_sample() -> bytes:
    return json.dumps({
        "schema_version": "opportunity-local-history-preview.v1",
        "adapter_revision": sorted(query.V2_ADAPTERS)[0],
        "gain_policy": query.GAIN_POLICY,
        "rule": RULE,
        "selector": SELECTOR,
    }).encode("utf-8")


def test_registered_publication_and_unknown_default(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = manifest_sample()
    with pytest.raises(ValueError, match="Manifest trust mismatch"):
        query.validate_manifest_trust(raw)
    monkeypatch.setattr(query, "REGISTERED_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())
    assert query.validate_manifest_trust(raw) == {
        "trusted_manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "manifest_trust_policy": "registered_publication",
    }


def test_external_pin_is_normalized_and_not_read_from_manifest() -> None:
    raw = manifest_sample()
    digest = hashlib.sha256(raw).hexdigest()
    assert query.validate_manifest_trust(raw, digest.upper())["manifest_trust_policy"] == "caller_pinned"
    forged = json.loads(raw)
    forged["expected_manifest_sha256"] = digest
    with pytest.raises(ValueError, match="Manifest trust mismatch"):
        query.validate_manifest_trust(json.dumps(forged).encode())


@pytest.mark.parametrize("pin", ["", "x" * 64, "0" * 63, " " + "0" * 64, 17, "0" * 64])
def test_invalid_or_mismatched_external_pin(pin: Any) -> None:
    with pytest.raises(ValueError, match="expected_manifest_sha256|Manifest trust mismatch"):
        query.validate_manifest_trust(manifest_sample(), pin)


@pytest.mark.parametrize("entry", ["query", "verify"])
def test_entrypoint_rejects_unknown_before_dependencies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(manifest_sample())

    def unread(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Manifest trust must be checked before dependency reads")

    monkeypatch.setattr(query, "_v2_dependency", unread)
    monkeypatch.setattr(verifier, "_checked", unread)
    with pytest.raises(ValueError, match="Manifest trust mismatch"):
        if entry == "query":
            query.query_manifest(path, "A", "2020-01-01")
        else:
            verifier.verify_catalog(path)


def test_actual_query_and_verifier_accept_explicit_external_pin(tmp_path: Path) -> None:
    from scripts.tests.test_verify_opportunity_history import catalog_fixture

    path = catalog_fixture(tmp_path)
    external_pin = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = verifier.verify_catalog(path, expected_manifest_sha256=external_pin)
    result = query.query_manifest(path, "A", "2020-01-03", expected_manifest_sha256=external_pin)
    assert receipt["manifest_trust_policy"] == result["evidence"]["manifest_trust_policy"] == "caller_pinned"
    assert receipt["trusted_manifest_sha256"] == result["evidence"]["trusted_manifest_sha256"] == external_pin


def test_resigned_native_and_compact_cannot_replace_original_external_pin(tmp_path: Path) -> None:
    from scripts.tests.test_verify_opportunity_history import _resign_native_and_rebuild_fixture_tables, catalog_fixture

    path = catalog_fixture(tmp_path)
    original_pin = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = json.loads(path.read_bytes())
    from scripts.build_opportunity_history import read_json

    native = read_json(path.parent / manifest["native"]["A"]["path"])
    for record in native["native"]:
        record["result"]["segments"][0]["slope"] = -0.02
    _resign_native_and_rebuild_fixture_tables(path, native)
    assert hashlib.sha256(path.read_bytes()).hexdigest() != original_pin
    with pytest.raises(ValueError, match="Manifest trust mismatch"):
        verifier.verify_catalog(path, expected_manifest_sha256=original_pin)
    with pytest.raises(ValueError, match="Manifest trust mismatch"):
        query.query_manifest(path, "A", "2020-01-03", expected_manifest_sha256=original_pin)
