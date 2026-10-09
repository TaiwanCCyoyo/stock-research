from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from research_core.opportunity_history_catalog import RULE, SELECTOR, adapt_security
from scripts import verify_opportunity_history as verifier
from scripts.build_opportunity_history import (
    PAIRS,
    ROOT,
    TASK,
    build_catalog,
    canonical,
    code_identity,
    descriptor,
    read_json,
    resolve_params_artifact,
    sha,
    write_json,
)
from scripts.opportunity_history_native_validation import (
    NODE,
    SOURCE_GATE,
    expected_baseline_waves,
    expected_launches,
    expected_noise,
    expected_support_records,
    validate_native_semantics,
)
from scripts.query_opportunity_history import GAIN_POLICY, V2_ADAPTERS, calendar_content_id, series_content_id, validate_manifest_identity
from scripts.tests.opportunity_trusted_fixture_calls import fixture_manifest_sha256, verify_catalog
from scripts.tests.test_build_opportunity_history import fixture_params, inputs


@pytest.fixture(autouse=True)
def fixture_exact_source_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Known pinned transform for the dense six-point synthetic series."""

    def expected(path: Path) -> dict[str, list[int | None]]:
        return {code: [0] * 6 for code in read_json(path)["native"]}

    monkeypatch.setattr(verifier, "_expected_source_runs", expected)


def semantic_inputs(root: Path) -> Path:
    path = inputs(root)
    source = read_json(path)
    calendar_path = root / source["calendar"]["path"]
    calendar: dict[str, Any] = {"dates": [f"2020-01-{day:02}" for day in range(1, 7)]}
    calendar["calendar_id"] = calendar_content_id(calendar)
    calendar_path.unlink()
    write_json(calendar_path, calendar)
    source["calendar"] = descriptor(calendar_path, root, 6)
    source["calendar_id"] = calendar["calendar_id"]
    for row in source["rows"]:
        series_path = root / row["path"]
        series = read_json(series_path)
        series.update({
            "calendar_id": calendar["calendar_id"],
            "raw": [100, 120, 150, 180, 134, 100],
            "adjusted": [100, 120, 150, 180, 134, 100],
            "sources": ["official"] * 6,
            "coverage": {"date_count": 6, "missing_count": 0, "usable_adjusted_count": 6},
        })
        series["series_id"] = series_content_id(series)
        series_path.unlink()
        write_json(series_path, series)
        row.update({"series_id": series["series_id"], "coverage": series["coverage"]} | descriptor(series_path, root))
    path.unlink()
    write_json(path, source)
    return path


def rich_runner(series_path: Path, calendar_path: Path, output_path: Path) -> None:
    series = read_json(series_path)
    runs: list[int | None] = [0] * 6
    noise = expected_noise(series, runs)
    phases = [{"start": 0, "end": 1, "phase": "falling", "slope": -0.01}, {"start": 1, "end": 5, "phase": "fast", "slope": 0.1}]
    candidates = expected_launches(series, phases, noise)
    records = [
        {
            "method": method,
            "scale": scale,
            "status": "ok",
            "error": None,
            "result": {
                "waves": expected_baseline_waves(series, runs, scale),
                "segments": phases,
                "launches": candidates,
                "diagnostics": {"converged": False, "noise": noise},
            },
        }
        for method, scale in sorted(PAIRS)
    ]
    support = expected_support_records({"native": records})
    write_json(
        output_path,
        {
            "schema": "opportunity-native-results.v1",
            **{key: series[key] for key in ("security_id", "series_id", "calendar_id")},
            "input_identity": {"series_sha256": sha(series_path), "calendar_sha256": sha(calendar_path)},
            "code_identity": code_identity(),
            "source_run_indices": runs,
            "native": records,
            "support_records": support,
        },
    )


def catalog_fixture(tmp_path: Path) -> Path:
    source = semantic_inputs(tmp_path / "目錄 catalog")
    build_catalog(source, tmp_path / "native", params_path=fixture_params(source.parent), runner=rich_runner, progress=lambda _: None)
    return source.parent / "manifest.json"


def test_custom_params_are_declared_and_verified_without_sibling_copy(tmp_path: Path) -> None:
    source = semantic_inputs(tmp_path / "custom catalog")
    params = tmp_path / "external numerical settings.json"
    # Different formatting proves that the recorded hash binds raw file bytes.
    params.write_text(json.dumps(read_json(ROOT / "tasks" / TASK / "params.json"), indent=3), encoding="utf-8")
    manifest = build_catalog(source, tmp_path / "native", params_path=params, runner=rich_runner, progress=lambda _: None)
    path = source.parent / "manifest.json"
    assert resolve_params_artifact(path, manifest) == params.resolve()
    assert manifest["params_artifact"]["sha256"] == sha(params) == manifest["producer_identity"]["config_sha256"]
    assert not (source.parent.parent / "params.json").exists()
    assert verify_catalog(path)["status"] == "verified"


def test_legacy_explicit_params_path_and_cli(tmp_path: Path) -> None:
    path = catalog_fixture(tmp_path)
    manifest = read_json(path)
    params = resolve_params_artifact(path, manifest)
    manifest.pop("params_artifact")
    path.unlink()
    write_json(path, manifest)
    assert not (path.parent.parent / "params.json").exists()
    assert verify_catalog(path, params_path=params)["status"] == "verified"
    command = [
        sys.executable,
        str(ROOT / "scripts/verify_opportunity_history.py"),
        "--manifest",
        str(path),
        "--params",
        str(params),
        "--expected-manifest-sha256",
        fixture_manifest_sha256(path),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    assert json.loads(completed.stdout)["status"] == "verified"


@pytest.mark.parametrize(
    "reference",
    [None, {}, {"path": "", "sha256": "0" * 64}, {"path": "params.json", "sha256": 123}, {"path": "params.json", "sha256": "xyz"}],
)
def test_invalid_declared_params_descriptor_rejected(tmp_path: Path, reference: Any) -> None:
    with pytest.raises(ValueError, match="params_artifact"):
        resolve_params_artifact(tmp_path / "manifest.json", {"params_artifact": reference})


@pytest.mark.parametrize("mutation", ["bad_sha", "explicit_conflict"])
def test_declared_params_conflicts_rejected(tmp_path: Path, mutation: str) -> None:
    path = catalog_fixture(tmp_path)
    manifest = read_json(path)
    explicit = None
    if mutation == "bad_sha":
        manifest["params_artifact"]["sha256"] = "0" * 64
        message = "params_artifact hash mismatch"
    else:
        explicit = tmp_path / "different params.json"
        explicit.write_bytes(resolve_params_artifact(path, manifest).read_bytes())
        message = "Explicit params path conflicts"
    path.unlink()
    write_json(path, manifest)
    with pytest.raises(ValueError, match=message):
        verify_catalog(path, params_path=explicit)


@pytest.mark.parametrize("artifact", ["calendar", "series"])
def test_resigned_bytes_require_content_identity(tmp_path: Path, artifact: str) -> None:
    path = catalog_fixture(tmp_path)
    manifest = read_json(path)
    reference = manifest["calendar"] if artifact == "calendar" else manifest["series"]["A"]
    artifact_path = path.parent / reference["path"]
    content = read_json(artifact_path)
    if artifact == "calendar":
        content["dates"][0] = "2019-12-31"
    else:
        content["adjusted"][0] = 99
    artifact_path.unlink()
    write_json(artifact_path, content)
    reference["sha256"] = sha(artifact_path)
    if artifact == "series":
        source_path = path.parent / manifest["series_manifest"]["path"]
        source = read_json(source_path)
        next(row for row in source["rows"] if row["code"] == "A")["sha256"] = reference["sha256"]
        source_path.unlink()
        write_json(source_path, source)
        manifest["series_manifest"]["sha256"] = sha(source_path)
        manifest["producer_identity"]["series_manifest_sha256"] = sha(source_path)
    path.unlink()
    write_json(path, manifest)
    with pytest.raises(ValueError, match="content identity"):
        verify_catalog(path)


@pytest.mark.parametrize("conflict", ["unknown_adapter", "gain_policy", "compact_adapter"])
def test_manifest_identity_conflicts_rejected_before_dependencies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conflict: str) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest: dict[str, Any] = {
        "schema_version": "opportunity-local-history-preview.v1",
        "adapter_revision": min(V2_ADAPTERS),
        "gain_policy": GAIN_POLICY,
        "rule": RULE,
        "selector": SELECTOR,
    }
    if conflict == "unknown_adapter":
        manifest["adapter_revision"] = "unknown-adapter"
    elif conflict == "gain_policy":
        manifest["gain_policy"] = "conflicting-policy"
    else:
        manifest["compact_export_identity"] = {"adapter_sha256": "conflicting-adapter"}
    write_json(manifest_path, manifest)
    reads: list[Path] = []
    checked: list[dict[str, Any]] = []
    original_read = verifier._read

    def read_manifest_only(path: Path) -> Any:
        reads.append(path)
        assert path == manifest_path, "Dependencies must not be read for an invalid identity"
        return original_read(path)

    def dependency_forbidden(_root: Path, reference: dict[str, Any]) -> Path:
        checked.append(reference)
        raise AssertionError("Dependency checks must not run for an invalid identity")

    monkeypatch.setattr(verifier, "_read", read_manifest_only)
    monkeypatch.setattr(verifier, "_checked", dependency_forbidden)
    error_pattern = {"unknown_adapter": "adapter revision", "gain_policy": "gain policy", "compact_adapter": "compact_export_identity"}[conflict]
    with pytest.raises(ValueError, match=error_pattern):
        verify_catalog(manifest_path)
    # The manifest is parsed directly from the raw bytes bound by its trust pin.
    assert reads == []
    assert checked == []


@pytest.mark.parametrize("field", ["rule", "selector"])
@pytest.mark.parametrize("mutation", ["missing", "null", "wrong", "type"])
def test_rule_selector_identity_rejected_before_dependencies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, mutation: str) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest: dict[str, Any] = {
        "schema_version": "opportunity-local-history-preview.v1",
        "adapter_revision": min(V2_ADAPTERS),
        "gain_policy": GAIN_POLICY,
        "rule": RULE,
        "selector": SELECTOR,
    }
    if mutation == "missing":
        manifest.pop(field)
    elif mutation == "null":
        manifest[field] = None
    elif mutation == "wrong":
        manifest[field] = "unsupported-identity"
    else:
        manifest[field] = {"value": RULE if field == "rule" else SELECTOR}
    write_json(manifest_path, manifest)
    reads: list[Path] = []
    checked: list[dict[str, Any]] = []
    original_read = verifier._read

    def read_manifest_only(path: Path) -> Any:
        reads.append(path)
        assert path == manifest_path, "Invalid rule/selector must not read dependencies"
        return original_read(path)

    def dependency_forbidden(_root: Path, reference: dict[str, Any]) -> Path:
        checked.append(reference)
        raise AssertionError("Invalid rule/selector must fail before dependency checks")

    monkeypatch.setattr(verifier, "_read", read_manifest_only)
    monkeypatch.setattr(verifier, "_checked", dependency_forbidden)
    with pytest.raises(ValueError, match=field):
        verify_catalog(manifest_path)
    # _read now serves dependencies; invalid identity must not invoke it.
    assert reads == []
    assert checked == []


def test_known_v2_adapter_infers_missing_gain_policy(tmp_path: Path) -> None:
    manifest_path = catalog_fixture(tmp_path)
    manifest = read_json(manifest_path)
    manifest.pop("gain_policy")
    manifest_path.unlink()
    write_json(manifest_path, manifest)
    evidence = validate_manifest_identity(manifest)
    assert evidence["effective_gain_policy"] == GAIN_POLICY
    assert evidence["policy_source"] == "adapter_registry"
    assert verify_catalog(manifest_path)["status"] == "verified"


@pytest.mark.parametrize(
    "field",
    [
        "calendar_sha256",
        "series_manifest_sha256",
        "input_receipt_sha256",
        "config_sha256",
        "producer_sha256",
        "adapter_sha256",
    ],
)
def test_manifest_producer_context_hash_tampering_rejected(tmp_path: Path, field: str) -> None:
    manifest_path = catalog_fixture(tmp_path)
    manifest = read_json(manifest_path)
    manifest["producer_identity"][field] = "0" * 64
    manifest_path.unlink()
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="context.*mismatch"):
        verify_catalog(manifest_path)


def test_resigned_native_receipt_context_mismatch_rejected(tmp_path: Path) -> None:
    manifest_path = catalog_fixture(tmp_path)
    manifest = read_json(manifest_path)
    reference = manifest["native"]["A"]["receipt"]
    receipt_path = manifest_path.parent / reference["path"]
    receipt = read_json(receipt_path)
    receipt["context"]["producer_sha256"] = "0" * 64
    receipt_path.unlink()
    write_json(receipt_path, receipt)
    reference["sha256"] = sha(receipt_path)
    manifest_path.unlink()
    write_json(manifest_path, manifest)
    assert reference["sha256"] == sha(receipt_path)
    with pytest.raises(ValueError, match="Native receipt producer context mismatch: A"):
        verify_catalog(manifest_path)


def test_resigned_manifest_input_receipt_must_match_series_manifest(tmp_path: Path) -> None:
    manifest_path = catalog_fixture(tmp_path)
    manifest = read_json(manifest_path)
    manifest["input_receipt"]["files"][0]["snapshot_sha256"] = "changed-input-claim"
    manifest["producer_identity"]["input_receipt_sha256"] = hashlib.sha256(canonical(manifest["input_receipt"])).hexdigest()
    manifest_path.unlink()
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="Series manifest/input receipt mismatch"):
        verify_catalog(manifest_path)


def test_config_claim_must_equal_pinned_params_object(tmp_path: Path) -> None:
    manifest_path = catalog_fixture(tmp_path)
    manifest = read_json(manifest_path)
    manifest["config"]["run_jump_ratio"] = 1.5
    manifest_path.unlink()
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="Pinned params/manifest config mismatch"):
        verify_catalog(manifest_path)


def test_producer_context_helpers_do_not_parse_tables_or_native_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = catalog_fixture(tmp_path)
    manifest = read_json(manifest_path)
    series_manifest = read_json(manifest_path.parent / manifest["series_manifest"]["path"])
    reads: list[Path] = []
    original_read = verifier._read
    params_path = resolve_params_artifact(manifest_path, manifest)

    def read_params_only(path: Path) -> Any:
        reads.append(path)
        assert path == params_path
        return original_read(path)

    monkeypatch.setattr(verifier, "_read", read_params_only)
    evidence = verifier.validate_producer_context(manifest_path, manifest, series_manifest)
    assert reads == [params_path]
    assert evidence["bound_input_hashes"]["config_sha256"] == manifest["producer_identity"]["config_sha256"]
    assert "original code bytes not read" in evidence["producer_adapter_code_policy"]
    for code, native_reference in manifest["native"].items():
        receipt = read_json(manifest_path.parent / native_reference["receipt"]["path"])
        verifier.validate_native_context(receipt, manifest["producer_identity"], code)


def test_relocated_producer_evidence_has_no_absolute_params_path(tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.mkdir()
    manifest_path = catalog_fixture(original)
    relocated = tmp_path / "relocated"
    shutil.copytree(original, relocated)
    relocated_path = relocated / manifest_path.relative_to(original)
    assert verify_catalog(manifest_path) == verify_catalog(relocated_path)
    manifest = read_json(manifest_path)
    evidence = verify_catalog(manifest_path)["producer_context_evidence"]
    assert evidence["config_path"] == manifest["params_artifact"]["path"] == "fixture-params.json"
    assert str(tmp_path) not in json.dumps(evidence)


def test_explicit_legacy_producer_evidence_uses_hash_marker(tmp_path: Path) -> None:
    path = catalog_fixture(tmp_path)
    manifest = read_json(path)
    params = resolve_params_artifact(path, manifest)
    manifest.pop("params_artifact")
    source = read_json(path.parent / manifest["series_manifest"]["path"])
    evidence = verifier.validate_producer_context(path, manifest, source, params_path=params)
    assert evidence["config_path"] == "external:params-by-sha256"
    assert evidence["bound_input_hashes"]["config_sha256"] == sha(params)
    assert str(tmp_path) not in json.dumps(evidence)


@pytest.mark.parametrize("outcome", ["failed", "unresolved", "continued"])
def test_candidate_bounds_preserve_inclusive_final_date_and_null_gains(outcome: str) -> None:
    verifier.validate_candidate_bounds(
        {"index": 1, "rangeStart": 1, "rangeEnd": 2, "forwardEnd": 2, "outcome": outcome, "forwardGain": None, "drawdown": None},
        3,
    )


def _resign_native_and_rebuild_fixture_tables(path: Path, native: dict[str, Any]) -> None:
    """Make tampered native and all compact tables internally consistent, without fitting."""
    manifest = read_json(path)
    root = path.parent
    reference = manifest["native"]["A"]
    native_path = root / reference["path"]
    native_path.unlink()
    write_json(native_path, native)
    reference["sha256"] = sha(native_path)
    receipt_path = root / reference["receipt"]["path"]
    receipt = read_json(receipt_path)
    receipt["sha256"] = reference["sha256"]
    receipt_path.unlink()
    write_json(receipt_path, receipt)
    reference["receipt"]["sha256"] = sha(receipt_path)
    calendar = read_json(root / manifest["calendar"]["path"])
    tables: dict[str, list[dict[str, Any]]] = {name: [] for name in manifest["tables"]}
    for code, series_ref in manifest["series"].items():
        series = read_json(root / series_ref["path"])
        saved = (
            read_json(root / manifest["native"][code]["path"])
            if code in manifest["native"]
            else {
                **{field: series[field] for field in ("security_id", "series_id", "calendar_id")},
                "input_identity": {"series_sha256": series_ref["sha256"], "calendar_sha256": manifest["calendar"]["sha256"]},
                "native": [],
                "support_records": [],
            }
        )
        rebuilt = adapt_security(series, calendar, saved)
        eligible = series["instrument_role"] == "stock" and series["cohort"] in {"metadata_stock", "innovation_board"}
        rebuilt["securities"][0].update({
            "stock_opportunity_eligible": eligible,
            "method_eligibility_reason": "stock_cohort" if eligible else "excluded_role_or_identity",
            "coverage": series.get("coverage", {}),
        })
        for name, rows in rebuilt.items():
            tables[name].extend(rows)
    for name, references in manifest["tables"].items():
        assert len(references) == 1
        rows = sorted(tables[name], key=canonical)
        table_path = root / references[0]["path"]
        table_path.unlink()
        write_json(table_path, {"rows": rows})
        references[0].update({"sha256": sha(table_path), "count": len(rows)})
    path.unlink()
    write_json(path, manifest)


@pytest.mark.parametrize("mutation", ["outside_calendar", "negative", "boolean", "ensuing_order", "forward_end", "support_index"])
def test_resigned_native_and_rebuilt_compact_bounds_rejected(tmp_path: Path, mutation: str) -> None:
    path = catalog_fixture(tmp_path)
    manifest = read_json(path)
    native = read_json(path.parent / manifest["native"]["A"]["path"])
    for record in native["native"]:
        candidate = record["result"]["launches"][0]
        if mutation in {"outside_calendar", "negative", "boolean"}:
            index = {"outside_calendar": 99, "negative": -1, "boolean": False}[mutation]
            candidate.update(dict.fromkeys(("index", "rangeStart", "rangeEnd", "forwardEnd"), index))
        elif mutation == "ensuing_order":
            candidate.update({"index": 2, "rangeStart": 2, "rangeEnd": 0, "forwardEnd": 0})
        elif mutation == "forward_end":
            candidate["forwardEnd"] = 3
    if mutation in {"outside_calendar", "negative", "boolean"}:
        index = {"outside_calendar": 99, "negative": -1, "boolean": False}[mutation]
        for support in native["support_records"]:
            support.update(dict.fromkeys(("index", "rangeStart", "rangeEnd"), index))
            for match in support["matched_ids"]:
                match["index"] = index
    elif mutation == "support_index":
        native["support_records"][0]["index"] = 99
    _resign_native_and_rebuild_fixture_tables(path, native)
    with pytest.raises(ValueError, match="calendar index|Candidate ensuing range|Candidate forward endpoint"):
        verify_catalog(path)


@pytest.mark.parametrize("start,end", [(0, 99), (-1, 2), (False, 2), (2, 0)])
def test_resigned_phase_and_rebuilt_compact_bounds_rejected(tmp_path: Path, start: Any, end: Any) -> None:
    path = catalog_fixture(tmp_path)
    manifest = read_json(path)
    native = read_json(path.parent / manifest["native"]["A"]["path"])
    for record in native["native"]:
        record["result"]["segments"][0].update({"start": start, "end": end})
    _resign_native_and_rebuild_fixture_tables(path, native)
    with pytest.raises(ValueError, match="calendar index|Phase inclusive range"):
        verify_catalog(path)


def test_phase_bounds_reject_null_and_allow_inclusive_final_date() -> None:
    verifier.validate_phase_bounds({"start": 0, "end": 2}, 3)
    with pytest.raises(ValueError, match="phase.end"):
        verifier.validate_phase_bounds({"start": 0, "end": None}, 3)


def _tied_native(native: dict[str, Any]) -> dict[str, Any]:
    """Put the larger index and lexically later ID first in saved launch order."""
    for record in native["native"]:
        original = record["result"]["launches"][0]
        points = [("z-first", 2), ("a-second", 0)] if record["scale"] == "fine" else [("launch", 1)]
        record["result"]["launches"] = [
            original | {"id": identity, "index": index, "rangeStart": index, "rangeEnd": index, "forwardEnd": index} for identity, index in points
        ]
    support_records = []
    for record in native["native"]:
        for target in record["result"]["launches"]:
            matches = []
            for scale in ("fine", "balanced", "coarse"):
                launches = next(item["result"]["launches"] for item in native["native"] if item["method"] == record["method"] and item["scale"] == scale)
                nearest = min(launches, key=lambda launch: abs(launch["index"] - target["index"]))
                matches.append({"method": record["method"], "scale": scale, "candidate_id": nearest["id"], "index": nearest["index"]})
            support_records.append({
                "method": record["method"],
                "scale": record["scale"],
                "candidate_id": target["id"],
                "index": target["index"],
                "kind": target["kind"],
                "support": len(matches),
                "rangeStart": min(match["index"] for match in matches),
                "rangeEnd": max(match["index"] for match in matches),
                "matched_ids": matches,
            })
    native["support_records"] = support_records
    return native


def test_native_support_tie_uses_original_order_independent_of_compact_sort(tmp_path: Path) -> None:
    path = catalog_fixture(tmp_path)
    manifest = read_json(path)
    native = _tied_native(read_json(path.parent / manifest["native"]["A"]["path"]))
    verifier.validate_native_support_order(native)
    _resign_native_and_rebuild_fixture_tables(path, native)
    target = next(row for row in native["support_records"] if row["method"] == "segments" and row["scale"] == "balanced")
    assert target["matched_ids"][0] == {"method": "segments", "scale": "fine", "candidate_id": "z-first", "index": 2}
    target["matched_ids"][0].update({"candidate_id": "a-second", "index": 0})
    target.update({"rangeStart": 0, "rangeEnd": 1})
    _resign_native_and_rebuild_fixture_tables(path, native)
    with pytest.raises(ValueError, match="Native support nearest/original-order mismatch"):
        verifier.validate_native_support_order(native)


def mutate_table(manifest_path: Path, table: str, changes: dict[str, Any]) -> None:
    manifest = read_json(manifest_path)
    reference = manifest["tables"][table][0]
    path = manifest_path.parent / reference["path"]
    part = read_json(path)
    part["rows"][0].update(changes)
    path.unlink()
    write_json(path, part)
    reference["sha256"] = sha(path)
    manifest_path.unlink()
    write_json(manifest_path, manifest)


def test_tiny_catalog_counts_nonconvergence_units_and_exclusive_end(tmp_path: Path) -> None:
    path = catalog_fixture(tmp_path)
    receipt = verify_catalog(path)
    assert receipt["status"] == "verified"
    assert receipt["security_count"] == 4
    assert receipt["analyzed_security_count"] == 2
    assert receipt["native_wave_count"] == 24
    assert receipt["shared_wave_count"] == 12
    assert receipt["nonconverged_methods"] == 12
    assert receipt["phase_cross_run_count"] == 0
    assert receipt["cohorts"]["unresolved_identity"] == 1
    assert receipt["parsed_native_count"] == 2
    assert receipt["reconstructed_without_native_count"] == 2
    assert receipt["native_semantic_reconstruction"] == "current V2 adapter; exact_pinned_js_run.preview.v2"
    assert receipt["reconstructed_table_counts"] == receipt["table_counts"]
    assert receipt["exact_source_runs_verified_count"] == 2


def append_unowned_row(manifest_path: Path, table: str, changes: dict[str, Any]) -> None:
    manifest = read_json(manifest_path)
    reference = manifest["tables"][table][0]
    path = manifest_path.parent / reference["path"]
    part = read_json(path)
    injected = part["rows"][0].copy()
    injected.pop("security_id")
    injected.update(changes)
    part["rows"].append(injected)
    path.unlink()
    write_json(path, part)
    reference["count"] = len(part["rows"])
    reference["sha256"] = sha(path)
    manifest_path.unlink()
    write_json(manifest_path, manifest)


@pytest.mark.parametrize("coupled_phase", [False, True])
def test_resigned_unowned_method_and_coupled_phase_rejected(tmp_path: Path, coupled_phase: bool) -> None:
    manifest_path = catalog_fixture(tmp_path)
    append_unowned_row(
        manifest_path,
        "methods",
        {
            "id": "injected-unowned-method",
            "wave_count": 0,
            "candidate_count": 0,
            "phase_count": int(coupled_phase),
        },
    )
    if coupled_phase:
        append_unowned_row(manifest_path, "source_phases", {"id": "injected-unowned-phase"})
    manifest = read_json(manifest_path)
    for table in ("methods", "source_phases"):
        reference = manifest["tables"][table][0]
        path = manifest_path.parent / reference["path"]
        assert reference["sha256"] == sha(path)
        assert reference["count"] == len(read_json(path)["rows"])
    with pytest.raises(ValueError, match="Missing or invalid security owner: methods"):
        verify_catalog(manifest_path)


def test_arbitrary_table_key_rejected(tmp_path: Path) -> None:
    manifest_path = catalog_fixture(tmp_path)
    manifest = read_json(manifest_path)
    manifest["tables"]["unconsumed_rows"] = manifest["tables"]["methods"]
    manifest_path.unlink()
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="Unknown or missing compact table keys"):
        verify_catalog(manifest_path)


def exact_runner(series_path: Path, calendar_path: Path, output_path: Path) -> None:
    rich_runner(series_path, calendar_path, output_path)
    native = read_json(output_path)
    native["source_run_indices"] = [0] * 6
    output_path.unlink()
    write_json(output_path, native)


def test_exact_source_runs_provider_called_once_and_excluded_no_native_retained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = semantic_inputs(tmp_path / "exact catalog")
    build_catalog(source, tmp_path / "native", params_path=fixture_params(source.parent), runner=exact_runner, progress=lambda _: None)
    calls: list[Path] = []

    def expected(manifest_path: Path) -> dict[str, list[int | None]]:
        calls.append(manifest_path)
        return {"A": [0] * 6, "B": [0] * 6}

    monkeypatch.setattr(verifier, "_expected_source_runs", expected)
    manifest_path = source.parent / "manifest.json"
    receipt = verify_catalog(manifest_path)
    assert calls == [manifest_path]
    assert receipt["exact_source_runs_verified_count"] == 2
    assert receipt["native_without_exact_run_claim_count"] == 0

    fallback_root = tmp_path / "fallback"
    fallback_root.mkdir()
    fallback_path = catalog_fixture(fallback_root)
    receipt = verify_catalog(fallback_path)
    assert calls == [manifest_path, fallback_path]
    assert receipt["native_without_exact_run_claim_count"] == 0
    assert receipt["reconstructed_without_native_count"] == 2


def test_exact_source_run_mismatch_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = semantic_inputs(tmp_path / "exact catalog")
    build_catalog(source, tmp_path / "native", params_path=fixture_params(source.parent), runner=exact_runner, progress=lambda _: None)
    monkeypatch.setattr(verifier, "_expected_source_runs", lambda _: {"A": [0, None, 1, 1, 1, 1], "B": [0] * 6})
    with pytest.raises(ValueError, match="Exact pinned JS source run mismatch: A"):
        verify_catalog(source.parent / "manifest.json")


def test_deleted_exact_runs_with_resigned_native_and_rebuilt_compact_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = catalog_fixture(tmp_path)
    assert verify_catalog(path)["exact_source_runs_verified_count"] == 2
    manifest = read_json(path)
    native = read_json(path.parent / manifest["native"]["A"]["path"])
    del native["source_run_indices"]
    _resign_native_and_rebuild_fixture_tables(path, native)
    resigned = read_json(path)
    reference = resigned["native"]["A"]
    assert "source_run_indices" not in read_json(path.parent / reference["path"])
    assert reference["sha256"] == sha(path.parent / reference["path"])
    assert reference["receipt"]["sha256"] == sha(path.parent / reference["receipt"]["path"])
    securities = [row for part in resigned["tables"]["securities"] for row in read_json(path.parent / part["path"])["rows"]]
    assert next(row for row in securities if row["code"] == "A")["run_boundary_precision"] == "python_fallback"

    def expected_forbidden(_path: Path) -> dict[str, list[int | None]]:
        raise AssertionError("Missing required runs must fail before exact comparison or reconstruction")

    monkeypatch.setattr(verifier, "_expected_source_runs", expected_forbidden)
    with pytest.raises(ValueError, match="V2 eligible native requires exact source_run_indices: A"):
        verify_catalog(path)


@pytest.mark.parametrize("mutation", ["waves", "candidates", "support"])
def test_resigned_native_divergence_rejected(tmp_path: Path, mutation: str) -> None:
    manifest_path = catalog_fixture(tmp_path)
    manifest = read_json(manifest_path)
    reference = manifest["native"]["A"]
    native_path = manifest_path.parent / reference["path"]
    native = read_json(native_path)
    if mutation == "waves":
        # Change both method aliases consistently: baseline consistency alone cannot catch this.
        for record in native["native"]:
            if record["scale"] == "fine":
                record["result"]["waves"][0]["gain"] = 123
    elif mutation == "candidates":
        native["native"][0]["result"]["launches"][0]["forwardGain"] = 999
    else:
        native["support_records"][0]["rangeEnd"] = 3
    native_path.unlink()
    write_json(native_path, native)
    reference["sha256"] = sha(native_path)
    receipt_path = manifest_path.parent / reference["receipt"]["path"]
    receipt = read_json(receipt_path)
    receipt["sha256"] = reference["sha256"]
    receipt_path.unlink()
    write_json(receipt_path, receipt)
    reference["receipt"]["sha256"] = sha(receipt_path)
    manifest_path.unlink()
    write_json(manifest_path, manifest)
    assert sha(native_path) == reference["sha256"]
    assert sha(receipt_path) == reference["receipt"]["sha256"]
    message = {
        "support": "Native support nearest/original-order mismatch",
        "waves": "Numeric mismatch: wave gain percent",
        "candidates": "Original source launch mismatch",
    }[mutation]
    with pytest.raises(ValueError, match=message):
        verify_catalog(manifest_path)


def test_builder_process_failure_preserves_diagnostics_and_original_native_bytes(tmp_path: Path) -> None:
    source = semantic_inputs(tmp_path / "failed catalog")
    native_dir = tmp_path / "native"
    original_bytes = b"unverified original runner output\n"

    def failed_runner(_series_path: Path, _calendar_path: Path, output_path: Path) -> None:
        output_path.write_bytes(original_bytes)
        raise subprocess.CalledProcessError(1, "synthetic-node", stderr="retained process failure")

    with pytest.raises(subprocess.CalledProcessError) as failure:
        build_catalog(source, native_dir, params_path=fixture_params(source.parent), runner=failed_runner, progress=lambda _: None)
    assert failure.value.stderr == "retained process failure"
    assert (native_dir / "A.json.gz").read_bytes() == original_bytes
    diagnostic = read_json(native_dir / "A.failure.json")
    assert diagnostic["schema_version"] == "opportunity-native-process-failure.v1"
    assert diagnostic["code"] == "A"
    assert diagnostic["process"] == {"command": "synthetic-node", "returncode": 1, "stdout": None, "stderr": "retained process failure"}
    assert diagnostic["retained_output"] == {"path": "A.json.gz", "sha256": hashlib.sha256(original_bytes).hexdigest(), "size_bytes": len(original_bytes)}
    assert not (native_dir / "A.receipt.json").exists()
    assert not (source.parent / "chunks").exists()
    assert not (source.parent / "manifest.json").exists()


def test_exact_runs_preserve_method_failure_diagnostics_but_refuse_partial_verification(tmp_path: Path) -> None:
    source = semantic_inputs(tmp_path / "method failures")
    build_catalog(source, tmp_path / "native", params_path=fixture_params(source.parent), runner=rich_runner, progress=lambda _: None)
    path = source.parent / "manifest.json"
    assert verify_catalog(path)["status"] == "verified"
    manifest = read_json(path)
    for reference in manifest["native"].values():
        native_path = path.parent / reference["path"]
        native = read_json(native_path)
        for record in native["native"]:
            record.update({"status": "error", "result": None, "error": {"name": "SyntheticMethodFailure", "message": "retained"}})
        native["support_records"] = []
        native_path.unlink()
        write_json(native_path, native)
        reference["sha256"] = sha(native_path)
        receipt_path = path.parent / reference["receipt"]["path"]
        receipt = read_json(receipt_path)
        receipt["sha256"] = reference["sha256"]
        receipt_path.unlink()
        write_json(receipt_path, receipt)
        reference["receipt"]["sha256"] = sha(receipt_path)
    path.unlink()
    write_json(path, manifest)
    _resign_native_and_rebuild_fixture_tables(path, read_json(path.parent / manifest["native"]["A"]["path"]))
    manifest = read_json(path)
    methods = [row for reference in manifest["tables"]["methods"] for row in read_json(path.parent / reference["path"])["rows"]]
    assert len(methods) == 12 and all(row["status"] == "error" for row in methods)
    for reference in manifest["native"].values():
        native = read_json(path.parent / reference["path"])
        assert len(native["native"]) == 6
        assert all(record["status"] == "error" and record["error"]["message"] == "retained" for record in native["native"])
    with pytest.raises(ValueError, match="Native publication requires all six successful scopes"):
        verify_catalog(path)


@pytest.mark.parametrize("mutation", ["error_rows", "outside_peak", "false_peak", "false_gain"])
def test_native_semantic_tampering_with_resigned_compact_rejected(tmp_path: Path, mutation: str) -> None:
    path = catalog_fixture(tmp_path)
    assert verify_catalog(path)["status"] == "verified"
    manifest = read_json(path)
    native = read_json(path.parent / manifest["native"]["A"]["path"])
    for record in native["native"]:
        wave = record["result"]["waves"][0]
        if mutation == "error_rows":
            record.update({"status": "error", "error": {"name": "SyntheticFailure", "message": "populated results retained"}})
        elif mutation == "outside_peak":
            wave["peak"] = 99
        elif mutation == "false_peak":
            wave.update({"peak": 0, "gain": 0})
        else:
            wave["gain"] = 123
    _resign_native_and_rebuild_fixture_tables(path, native)
    message = {
        "error_rows": "Native publication requires all six successful scopes",
        "outside_peak": "calendar index: wave.peak",
        "false_peak": "Numeric mismatch: wave peak",
        "false_gain": "Numeric mismatch: wave gain percent",
    }[mutation]
    with pytest.raises(ValueError, match=message):
        verify_catalog(path)


@pytest.mark.parametrize(
    "mutation",
    ["bad_result", "bad_waves", "duplicate_scope", "unknown_scope", "duplicate_wave", "duplicate_candidate", "bool_run", "short_runs"],
)
def test_shared_native_semantics_rejects_invalid_shape_and_identity(tmp_path: Path, mutation: str) -> None:
    path = catalog_fixture(tmp_path)
    manifest = read_json(path)
    native = read_json(path.parent / manifest["native"]["A"]["path"])
    series = read_json(path.parent / manifest["series"]["A"]["path"])
    calendar = read_json(path.parent / manifest["calendar"]["path"])
    validate_native_semantics(native, series, calendar)
    record = native["native"][0]
    if mutation == "bad_result":
        record["result"] = []
    elif mutation == "bad_waves":
        record["result"]["waves"] = None
    elif mutation == "duplicate_scope":
        record.update({key: native["native"][1][key] for key in ("method", "scale")})
    elif mutation == "unknown_scope":
        record["method"] = ["segments"]
    elif mutation == "duplicate_wave":
        record["result"]["waves"].append(record["result"]["waves"][0].copy())
    elif mutation == "duplicate_candidate":
        record["result"]["launches"].append(record["result"]["launches"][0].copy())
    elif mutation == "bool_run":
        native["source_run_indices"][0] = True
    else:
        native["source_run_indices"].pop()
    with pytest.raises(ValueError, match="shape|list|unique|Duplicate|source_run_indices"):
        validate_native_semantics(native, series, calendar)


def test_shared_native_semantics_refuses_partial_with_empty_failure_results(tmp_path: Path) -> None:
    path = catalog_fixture(tmp_path)
    manifest = read_json(path)
    native = read_json(path.parent / manifest["native"]["A"]["path"])
    series = read_json(path.parent / manifest["series"]["A"]["path"])
    calendar = read_json(path.parent / manifest["calendar"]["path"])
    for record in native["native"]:
        record.update({
            "status": "error",
            "error": {"name": "SyntheticMethodFailure", "message": "retained"},
            "result": {"waves": [], "segments": [], "launches": [], "diagnostics": {"converged": False}, "warnings": ["retained"]},
        })
    native["support_records"] = []
    with pytest.raises(ValueError, match="Partial native source semantics.*cannot verify"):
        validate_native_semantics(native, series, calendar)
    assert all(record["error"]["message"] == "retained" and record["result"]["warnings"] == ["retained"] for record in native["native"])


@pytest.mark.parametrize("gain", [True, float("inf"), float("nan")])
def test_shared_wave_semantics_rejects_nonfinite_and_boolean_gain(gain: Any) -> None:
    with pytest.raises(ValueError, match="Numeric mismatch: wave gain percent"):
        verifier.validate_wave_semantics({"start": 0, "peak": 1, "observedThrough": 1, "end": None, "gain": gain}, {"adjusted": [100, 101]}, 2, [0, 0])


@pytest.mark.parametrize("runs", [[0, None, 1], [0, 1, 1], [None, None, None], [0, False, 0]])
def test_wave_requires_one_nonnull_exact_run(runs: list[int | None]) -> None:
    with pytest.raises(ValueError, match="Wave crosses exact source run"):
        verifier.validate_wave_semantics(
            {"start": 0, "peak": 2, "observedThrough": 2, "end": None, "gain": 69},
            {"adjusted": [100, 130, 169]},
            3,
            runs,
        )


@pytest.mark.parametrize(
    "method_scale,small_end,large_end,parent",
    [("fine", 4, 5, "wave-large-1"), ("balanced", 4, 5, "wave-large-1"), ("coarse", 5, None, None)],
)
def test_pinned_directional_baseline_has_scale_specific_cuts(method_scale: str, small_end: int, large_end: int | None, parent: str | None) -> None:
    waves = expected_baseline_waves({"adjusted": [100, 120, 150, 180, 134, 100]}, [0] * 6, method_scale)
    assert len(waves) == 2
    assert [wave["id"] for wave in waves] == ["wave-small-0", "wave-large-1"]
    assert [(wave["start"], wave["peak"], wave["end"], wave["observedThrough"]) for wave in waves] == [(0, 3, small_end, small_end), (0, 3, large_end, 5)]
    assert waves[0].get("parentId") == parent
    assert waves[0]["leftCensored"] is True and waves[0]["rightCensored"] is False
    assert waves[1]["rightCensored"] is (large_end is None)
    assert all(wave["gain"] == pytest.approx(80) for wave in waves)
    assert waves[0]["maxDrawdown"] == pytest.approx((([100, 120, 150, 180, 134, 100][small_end] / 180) - 1) * 100)


def test_baseline_floor_reset_and_run_local_serials() -> None:
    assert expected_baseline_waves({"adjusted": [100, 110, 120]}, [0, 0, 0], "fine") == []
    waves = expected_baseline_waves({"adjusted": [100, 130, 170, None, 100, 130, 170]}, [0, 0, 0, None, 1, 1, 1], "fine")
    assert [wave["id"] for wave in waves] == ["wave-small-0", "wave-small-1", "wave-large-2", "wave-large-3"]
    assert [(wave["start"], wave["observedThrough"]) for wave in waves] == [(0, 2), (4, 6), (0, 2), (4, 6)]
    assert all(wave["end"] is None and wave["rightCensored"] and "parentId" not in wave for wave in waves)


@pytest.mark.parametrize("mutation", ["run_gap", "scale_swap", "launch_gain", "launch_drawdown", "launch_outcome", "noise", "phase_label"])
def test_resigned_source_semantic_fields_are_recomputed(tmp_path: Path, mutation: str) -> None:
    path = catalog_fixture(tmp_path)
    assert verify_catalog(path)["status"] == "verified"
    manifest = read_json(path)
    native = read_json(path.parent / manifest["native"]["A"]["path"])
    if mutation == "run_gap":
        native["source_run_indices"] = [0, 0, None, 1, 1, 1]
    for record in native["native"]:
        result = record["result"]
        if mutation == "scale_swap":
            for wave in result["waves"]:
                wave["scale"] = "large" if wave["scale"] == "small" else "small"
        elif mutation == "launch_gain":
            result["launches"][0]["forwardGain"] = 999
        elif mutation == "launch_drawdown":
            result["launches"][0]["drawdown"] = 999
        elif mutation == "launch_outcome":
            result["launches"][0]["outcome"] = "continued"
        elif mutation == "noise":
            result["diagnostics"]["noise"] = 0
        elif mutation == "phase_label":
            result["segments"][0]["phase"] = "FABRICATED"
    _resign_native_and_rebuild_fixture_tables(path, native)
    messages = {
        "run_gap": "Wave crosses exact source run",
        "scale_swap": "Original source wave mismatch",
        "noise": "Original source noise mismatch",
        "phase_label": "Original source phase mismatch",
    }
    with pytest.raises(ValueError, match=messages.get(mutation, "Original source launch mismatch")):
        verify_catalog(path)


def test_original_source_phase_threshold_labels() -> None:
    slopes = [0, -0.0003, 0.0003, 0.005, 0.005000000000000001]
    segments = [{"start": index, "end": index, "slope": slope} for index, slope in enumerate(slopes)]
    payload = {"series": {"adjusted": [100] * len(slopes)}, "segments": segments}
    completed = subprocess.run(
        [str(NODE), str(SOURCE_GATE), "--derive"],
        input=json.dumps(payload),
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    expected = json.loads(completed.stdout)
    assert expected["schema"] == "opportunity-native-source-expectations.v1"
    assert [segment["phase"] for segment in expected["phases"]] == ["flat", "falling", "rising", "rising", "fast"]


def test_launch_gain_drawdown_outcome_and_noise_are_independent_source_values() -> None:
    series = {"adjusted": [100, 120, 150, 180, 134, 100]}
    noise = expected_noise(series, [0] * 6)
    phases = [{"start": 0, "end": 1, "slope": -0.01}, {"start": 1, "end": 5, "slope": 0.1}]
    launch = expected_launches(series, phases, noise)[0]
    assert launch["id"] == "launch-1-reversal" and launch["support"] == 1
    assert launch["forwardGain"] == pytest.approx((100 / 120 - 1) * 100)
    assert launch["drawdown"] == pytest.approx((100 / 180 - 1) * 100)
    assert launch["relativeStrength"] == pytest.approx(0.11 / noise)
    assert launch["outcome"] == "unresolved" and launch["sustainSessions"] == 4


@pytest.mark.parametrize("mutation", ["hash", "ref", "exclusive_end", "unit", "peak_gain", "count", "support"])
def test_corruption_rejected(tmp_path: Path, mutation: str) -> None:
    path = catalog_fixture(tmp_path)
    if mutation == "hash":
        manifest = read_json(path)
        reference = manifest["tables"]["baseline_waves"][0]
        (path.parent / reference["path"]).write_bytes(b"corrupt")
    elif mutation == "ref":
        mutate_table(path, "candidates", {"wave_ids": ["missing-wave"]})
    elif mutation == "exclusive_end":
        mutate_table(path, "representative_intervals", {"end_exclusive_index": 99})
    elif mutation == "unit":
        mutate_table(path, "baseline_waves", {"gain_unit": "fraction"})
    elif mutation == "peak_gain":
        mutate_table(path, "baseline_waves", {"gain": 0.02})
    elif mutation == "count":
        mutate_table(path, "methods", {"phase_count": 999})
    else:
        mutate_table(path, "support_records", {"matched_catalog_ids": ["missing-candidate"]})
    with pytest.raises(ValueError):
        verify_catalog(path)


def test_invalid_quote_cannot_be_claimed_peak(tmp_path: Path) -> None:
    path = catalog_fixture(tmp_path)
    mutate_table(path, "baseline_waves", {"peak": 1})
    with pytest.raises(ValueError, match="Numeric mismatch: wave peak"):
        verify_catalog(path)


def test_cli_utf8_exclusive_receipt_write(tmp_path: Path) -> None:
    manifest = catalog_fixture(tmp_path)
    receipt_path = tmp_path / "驗證 receipt.json"
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "verify_opportunity_history.py"),
        "--manifest",
        str(manifest),
        "--receipt",
        str(receipt_path),
        "--expected-manifest-sha256",
        fixture_manifest_sha256(manifest),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    assert json.loads(completed.stdout) == read_json(receipt_path)
    repeated = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert repeated.returncode != 0 and "FileExistsError" in repeated.stderr
