from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.build_opportunity_history import read_json, sha
from scripts.opportunity_history_native_validation import expected_launches, expected_support_records, validate_native_semantics
from scripts.query_opportunity_history import query_manifest
from scripts.tests.test_verify_opportunity_history import _resign_native_and_rebuild_fixture_tables, catalog_fixture
from scripts.verify_opportunity_history import verify_catalog


@pytest.mark.parametrize("mutation", ["slope", "endpoint"])
@pytest.mark.parametrize("entrypoint", ["query", "verifier"])
def test_original_publication_pin_rejects_consistently_resigned_fitting_outputs(tmp_path: Path, mutation: str, entrypoint: str) -> None:
    path = catalog_fixture(tmp_path)
    # The caller chooses this anchor before reading a potentially replaced publication.
    original_pin = sha(path)
    assert verify_catalog(path, expected_manifest_sha256=original_pin)["status"] == "verified"
    assert query_manifest(path, "A", "2020-01-04", expected_manifest_sha256=original_pin)["member"] is True
    manifest = read_json(path)
    native: dict[str, Any] = read_json(path.parent / manifest["native"]["A"]["path"])
    series = read_json(path.parent / manifest["series"]["A"]["path"])
    calendar = read_json(path.parent / manifest["calendar"]["path"])
    for record in native["native"]:
        result = record["result"]
        segment = result["segments"][0]
        if mutation == "slope":
            segment["slope"] = -0.02
        else:
            segment["end"] = 2
        result["launches"] = expected_launches(series, result["segments"], result["diagnostics"]["noise"])
    native["support_records"] = expected_support_records(native)
    # Pure semantic checks cannot authenticate the inputs to a saved numerical fit.
    validate_native_semantics(native, series, calendar)
    _resign_native_and_rebuild_fixture_tables(path, native)
    assert sha(path) != original_pin
    with pytest.raises(ValueError, match="Manifest trust mismatch"):
        if entrypoint == "query":
            query_manifest(path, "A", "2020-01-04", expected_manifest_sha256=original_pin)
        else:
            verify_catalog(path, expected_manifest_sha256=original_pin)
    # Removing the external pin cannot turn an unknown publication into an approved one.
    with pytest.raises(ValueError, match="Manifest trust mismatch"):
        if entrypoint == "query":
            query_manifest(path, "A", "2020-01-04")
        else:
            verify_catalog(path)
