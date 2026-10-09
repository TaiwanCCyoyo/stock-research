from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from research_core.opportunity_history_catalog import RULE, SELECTOR, adapt_security, source_run_indices
from scripts.build_opportunity_history import PAIRS, code_identity
from scripts.query_opportunity_history import (
    GAIN_POLICY,
    V1_ADAPTER,
    V2_ADAPTERS,
    calendar_content_id,
    main,
    read_reference,
    series_content_id,
    validate_calendar_identity,
    validate_manifest_identity,
    validate_query_tables,
    validate_series_identity,
)
from scripts.tests.opportunity_trusted_fixture_calls import fixture_manifest_sha256, query_manifest


def catalog(root: Path) -> tuple[Path, dict[str, Any]]:
    root.mkdir()

    def write(name: str, payload: Any) -> dict[str, str]:
        raw = json.dumps(payload).encode()
        (root / name).write_bytes(raw)
        return {"path": name, "sha256": hashlib.sha256(raw).hexdigest()}

    calendar: dict[str, Any] = {
        "schema_version": "opportunity-calendar.v1",
        "name": "source-date-union",
        "timezone": "Asia/Taipei",
        "start": "2020-01-01",
        "end": "2020-01-02",
        "dates": ["2020-01-01", "2020-01-02"],
    }
    calendar_id = calendar_content_id(calendar)
    calendar["calendar_id"] = calendar_id
    series = {
        "schema_version": "opportunity-series.v1",
        "code": "A",
        "security_id": "sec",
        "instrument_role": "stock",
        "cohort": "metadata_stock",
        "calendar_id": calendar_id,
        "raw": [100, 110],
        "adjusted": [100, 110],
        "numeric_flags": {},
    }
    series["series_id"] = series_content_id(series)
    manifest = {
        "schema_version": "opportunity-local-history-preview.v1",
        "task": "synthetic",
        "catalog_revision": "gain-continuity-v2",
        "gain_policy": GAIN_POLICY,
        "adapter_revision": sorted(V2_ADAPTERS)[0],
        "rule": RULE,
        "selector": SELECTOR,
        "calendar_id": calendar_id,
        "code_identity": code_identity(),
        "native": {},
        "producer_identity": {"fixture_only": True, "code_identity": code_identity(), "calendar_sha256": "fixture"},
        "calendar": write("calendar.json", calendar) | {"count": 2},
        "series": {"A": write("A.json", series) | {"series_id": series["series_id"], "security_id": "sec"}},
        "tables": {
            "securities": [
                write(
                    "securities.json",
                    {
                        "rows": [
                            {
                                "security_id": "sec",
                                "series_id": series["series_id"],
                                "calendar_id": calendar_id,
                                "stock_opportunity_eligible": True,
                                "continuity_runs": [{"run_id": 0, "start": 0, "end": 1}],
                            }
                        ],
                    },
                )
            ],
            "representative_intervals": [write("intervals.json", {"rows": []})],
        },
    }
    sync_query_table_identity(root, manifest, series)
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def sync_query_table_identity(root: Path, manifest: dict[str, Any], series: dict[str, Any]) -> None:
    eligible = series["instrument_role"] == "stock" and series["cohort"] in ("metadata_stock", "innovation_board")
    calendar = read_reference(root, manifest["calendar"])
    native: dict[str, Any] = {
        **{key: series[key] for key in ("security_id", "series_id", "calendar_id")},
        "input_identity": {"series_sha256": manifest["series"][series["code"]]["sha256"], "calendar_sha256": manifest["calendar"]["sha256"]},
        "native": [],
        "support_records": [],
    }
    if eligible:
        old_reference = manifest["native"].get(series["code"])
        if old_reference:
            previous = read_reference(root, old_reference)
            native["native"] = previous["native"]
        else:
            native["native"] = [
                {
                    "method": method,
                    "scale": scale,
                    "status": "ok",
                    "error": None,
                    "result": {"waves": [], "segments": [], "launches": [], "diagnostics": {"converged": True}},
                }
                for method, scale in sorted(PAIRS)
            ]
        native.update(schema="opportunity-native-results.v1", code_identity=manifest["code_identity"], source_run_indices=source_run_indices(series))
        refresh_fixture_results(native, series)
        manifest["producer_identity"]["calendar_sha256"] = manifest["calendar"]["sha256"]
        publish_native_fixture(root, manifest, series, native)
    publish_query_tables(root, manifest, series, calendar, native)


def publish_native_fixture(root: Path, manifest: dict[str, Any], series: dict[str, Any], native: dict[str, Any]) -> None:
    def write(name: str, payload: Any) -> dict[str, Any]:
        raw = json.dumps(payload).encode()
        (root / name).write_bytes(raw)
        return {"path": name, "sha256": hashlib.sha256(raw).hexdigest()}

    native_ref = write("native-A.json", native) | {"count": 6}
    receipt = {
        "schema_version": "opportunity-native-receipt.v1",
        "context": manifest["producer_identity"],
        "sha256": native_ref["sha256"],
        "security_id": series["security_id"],
        "series_id": series["series_id"],
    }
    native_ref["receipt"] = write("native-A.receipt.json", receipt)
    manifest["native"][series["code"]] = native_ref


def publish_query_tables(root: Path, manifest: dict[str, Any], series: dict[str, Any], calendar: dict[str, Any], native: dict[str, Any]) -> None:
    tables = adapt_security(series, calendar, native)
    eligible = series["instrument_role"] == "stock" and series["cohort"] in ("metadata_stock", "innovation_board")
    tables["securities"][0].update({
        "stock_opportunity_eligible": eligible,
        "method_eligibility_reason": "stock_cohort" if eligible else "excluded_role_or_identity",
        "coverage": series.get("coverage", {}),
    })
    for name in ("securities", "representative_intervals"):
        reference = manifest["tables"][name][0]
        raw = json.dumps({"rows": tables[name]}).encode()
        (root / reference["path"]).write_bytes(raw)
        reference["sha256"] = hashlib.sha256(raw).hexdigest()


def refresh_fixture_results(native: dict[str, Any], series: dict[str, Any]) -> None:
    from scripts.opportunity_history_native_validation import expected_baseline_waves, expected_launches, expected_noise, expected_support_records

    noise = expected_noise(series, native["source_run_indices"])
    for record in native["native"]:
        if record["status"] == "ok":
            result = record["result"]
            result["waves"] = expected_baseline_waves(series, native["source_run_indices"], record["scale"])
            result["diagnostics"]["noise"] = noise
            result["launches"] = expected_launches(series, result["segments"], noise)
    native["support_records"] = expected_support_records(native)


def member_catalog(root: Path, *, prices: list[float] | None = None, with_candidates: bool = False) -> tuple[Path, dict[str, Any]]:
    path, manifest = catalog(root)
    series = read_reference(root, manifest["series"]["A"])
    prices = prices if prices is not None else [100, 120, 150, 180, 134, 100]
    calendar = read_reference(root, manifest["calendar"])
    dates = [(date(2020, 1, 1) + timedelta(days=index)).isoformat() for index in range(len(prices))]
    calendar.update(dates=dates, start=dates[0], end=dates[-1])
    calendar["calendar_id"] = calendar_content_id(calendar)
    calendar_ref = manifest["calendar"]
    raw_calendar = json.dumps(calendar).encode()
    (root / calendar_ref["path"]).write_bytes(raw_calendar)
    calendar_ref.update(sha256=hashlib.sha256(raw_calendar).hexdigest(), count=len(prices))
    manifest["calendar_id"] = calendar["calendar_id"]
    series.update(raw=prices, adjusted=prices, calendar_id=calendar["calendar_id"])
    series["series_id"] = series_content_id(series)
    series_ref = manifest["series"]["A"]
    raw_series = json.dumps(series).encode()
    (root / series_ref["path"]).write_bytes(raw_series)
    series_ref.update(series_id=series["series_id"], sha256=hashlib.sha256(raw_series).hexdigest())
    sync_query_table_identity(root, manifest, series)
    if with_candidates:
        native = read_reference(root, manifest["native"]["A"])
        for record in native["native"]:
            record["result"]["segments"] = [
                {"start": 0, "end": 1, "slope": -0.01, "phase": "falling"},
                {"start": 1, "end": 3, "slope": 0.04, "phase": "fast"},
                {"start": 3, "end": 5, "slope": -0.02, "phase": "falling"},
            ]
        refresh_fixture_results(native, series)
        publish_native_fixture(root, manifest, series, native)
        publish_query_tables(root, manifest, series, calendar, native)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


@pytest.mark.parametrize("adapter", sorted(V2_ADAPTERS))
def test_explicit_v2_and_complete_no_wave_envelope(tmp_path: Path, adapter: str) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    manifest["adapter_revision"] = adapter
    manifest["compact_export_identity"] = {"adapter_sha256": adapter}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = query_manifest(path, "A", "2020-01-01")
    assert result["member"] is False and result["gain_reason"] == "no_active_wave"
    evidence = result["evidence"]
    assert evidence == {
        "schema": manifest["schema_version"],
        "task": "synthetic",
        "catalog_revision": "gain-continuity-v2",
        "declared_gain_policy": GAIN_POLICY,
        "effective_gain_policy": GAIN_POLICY,
        "policy_source": "manifest",
        "adapter_revision": adapter,
        "rule": manifest["rule"],
        "selector": manifest["selector"],
        "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "trusted_manifest_sha256": fixture_manifest_sha256(path),
        "manifest_trust_policy": "caller_pinned",
        "series_id": manifest["series"]["A"]["series_id"],
        "series_sha256": manifest["series"]["A"]["sha256"],
        "calendar_sha256": manifest["calendar"]["sha256"],
        "native_sha256": manifest["native"]["A"]["sha256"],
        "native_receipt_sha256": manifest["native"]["A"]["receipt"]["sha256"],
        "reconstruction_policy": "selected_native_full_rows.preview.v1",
    }
    outside = query_manifest(path, "A", "1999-01-01")
    assert outside["reason"] == "outside_source_calendar" and outside["evidence"] == evidence


def test_known_top_level_adapter_policy_inference(tmp_path: Path) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    manifest.pop("gain_policy")
    adapter = manifest["adapter_revision"]
    manifest["producer_identity"]["adapter_sha256"] = V1_ADAPTER
    publish_native_fixture(path.parent, manifest, read_reference(path.parent, manifest["series"]["A"]), read_reference(path.parent, manifest["native"]["A"]))
    path.write_text(json.dumps(manifest), encoding="utf-8")
    evidence = query_manifest(path, "A", "2020-01-02")["evidence"]
    assert evidence["declared_gain_policy"] is None
    assert evidence["effective_gain_policy"] == GAIN_POLICY
    assert evidence["policy_source"] == "adapter_registry"
    assert validate_manifest_identity(manifest)["adapter_revision"] == adapter


@pytest.mark.parametrize("producer_identity", [None, {"adapter_sha256": V1_ADAPTER}])
def test_current_top_level_adapter_ignores_source_producer_identity(
    tmp_path: Path,
    producer_identity: dict[str, str] | None,
) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    manifest["producer_identity"] = producer_identity
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert validate_manifest_identity(manifest)["adapter_revision"] == manifest["adapter_revision"]


@pytest.mark.parametrize(
    "malformed",
    [
        [],
        {
            "schema_version": "opportunity-local-history-preview.v1",
            "gain_policy": GAIN_POLICY,
            "producer_identity": {"adapter_sha256": sorted(V2_ADAPTERS)[0]},
        },
    ],
)
def test_non_object_or_source_only_adapter_refused_before_dependencies(tmp_path: Path, malformed: object) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(ValueError):
        query_manifest(path, "A", "2020-01-01")
    with pytest.raises(ValueError):
        validate_manifest_identity(malformed)


def test_original_archived_v1_shape_gets_preserved_producer_refusal(tmp_path: Path) -> None:
    manifest = {
        "schema_version": "opportunity-local-history-preview.v1",
        "producer_identity": {"adapter_sha256": V1_ADAPTER},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="preserved producer at 37cb418"):
        query_manifest(path, "A", "2020-01-01")
    with pytest.raises(ValueError, match="preserved producer at 37cb418"):
        validate_manifest_identity(manifest)


@pytest.mark.parametrize("change", ["legacy", "unknown", "missing_adapter", "policy", "schema", "missing_schema", "compact_mismatch"])
def test_version_refusal_precedes_dependency_reads(tmp_path: Path, change: str) -> None:
    manifest: dict[str, Any] = {
        "schema_version": "opportunity-local-history-preview.v1",
        "adapter_revision": sorted(V2_ADAPTERS)[0],
        "gain_policy": GAIN_POLICY,
        "rule": RULE,
        "selector": SELECTOR,
    }
    if change == "legacy":
        manifest["adapter_revision"] = V1_ADAPTER
    elif change == "unknown":
        manifest["adapter_revision"] = "unknown"
    elif change == "missing_adapter":
        manifest.pop("adapter_revision")
    elif change == "policy":
        manifest["gain_policy"] = "old-policy"
    elif change == "schema":
        manifest["schema_version"] = "unversioned"
    elif change == "missing_schema":
        manifest.pop("schema_version")
    else:
        manifest["compact_export_identity"] = {"adapter_sha256": "different"}
    # No dependency descriptors or files: version validation must reject first.
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    match = "37cb418" if change == "legacy" else None
    with pytest.raises(ValueError, match=match):
        query_manifest(path, "A", "2020-01-01")
    with pytest.raises(ValueError):
        validate_manifest_identity(manifest)


def test_artifact_hash_mismatch_remains_rejected(tmp_path: Path) -> None:
    path, _ = catalog(tmp_path / "catalog")
    (path.parent / "A.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        query_manifest(path, "A", "2020-01-01")


@pytest.mark.parametrize("field", ["rule", "selector"])
@pytest.mark.parametrize("change", ["missing", "null", "wrong", "type"])
def test_method_identity_refusal_precedes_dependency_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    change: str,
) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    if change == "missing":
        manifest.pop(field)
    else:
        manifest[field] = {"null": None, "wrong": "another-method.v1", "type": [manifest[field]]}[change]
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def refuse_dependency_read(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Invalid method identity must be refused before opening any dependency")

    monkeypatch.setattr("scripts.query_opportunity_history._read_reference_with_sha", refuse_dependency_read)
    with pytest.raises(ValueError, match=field):
        query_manifest(path, "A", "2020-01-01")
    with pytest.raises(ValueError, match=field):
        validate_manifest_identity(manifest)


def test_valid_method_identity_matches_core_constants(tmp_path: Path) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    identity = validate_manifest_identity(manifest)
    evidence = query_manifest(path, "A", "2020-01-01")["evidence"]
    assert identity["rule"] == evidence["rule"] == RULE
    assert identity["selector"] == evidence["selector"] == SELECTOR


@pytest.mark.parametrize("position", ["calendar", "series", "securities", "representative_intervals", "securities_second", "representative_intervals_second"])
@pytest.mark.parametrize("change", ["bare_string", "missing", "empty", "null", "short", "nonhex"])
def test_v2_dependency_identity_required_before_any_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, position: str, change: str) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    container: Any
    key: str | int
    if position == "calendar":
        container, key = manifest, "calendar"
    elif position == "series":
        container, key = manifest["series"], "A"
    else:
        table_name = position.removesuffix("_second")
        container, key = manifest["tables"][table_name], 0
        if position.endswith("_second"):
            container.append(dict(container[0]))
            key = 1
    reference = container[key]
    if change == "bare_string":
        container[key] = reference["path"]
    elif change == "missing":
        reference.pop("sha256")
    else:
        reference["sha256"] = {"empty": "", "null": None, "short": "a" * 63, "nonhex": "g" * 64}[change]
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def refuse_dependency_read(*args: Any, **kwargs: Any) -> None:
        pytest.fail("V2 malformed dependency must be refused before opening any dependency")

    monkeypatch.setattr("scripts.query_opportunity_history._read_reference_with_sha", refuse_dependency_read)
    with pytest.raises(ValueError, match="V2 dependency.*sha256"):
        query_manifest(path, "A", "2020-01-01")


def test_tampered_series_cannot_remove_expected_hash(tmp_path: Path) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    series_path = path.parent / manifest["series"]["A"]["path"]
    series = json.loads(series_path.read_bytes())
    series["adjusted"][1] = 999
    series_path.write_text(json.dumps(series), encoding="utf-8")
    manifest["series"]["A"].pop("sha256")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match=r"series\[A\].*sha256"):
        query_manifest(path, "A", "2020-01-02")


def test_standalone_legacy_reader_and_uppercase_v2_hash(tmp_path: Path) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    assert read_reference(path.parent, "A.json")["series_id"] == manifest["series"]["A"]["series_id"]
    manifest["series"]["A"]["sha256"] = manifest["series"]["A"]["sha256"].upper()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = query_manifest(path, "A", "2020-01-01")
    assert result["evidence"]["series_sha256"] == manifest["series"]["A"]["sha256"].lower()


@pytest.mark.parametrize(
    "change",
    [
        "other_security_series",
        "wrong_series_id",
        "wrong_security_id",
        "missing_series_id",
        "empty_security_id",
        "null_series_id",
        "missing_calendar_id",
        "empty_calendar_id",
        "null_calendar_id",
        "different_calendar",
        "series_calendar",
        "calendar_count",
        "calendar_count_bool",
        "raw_length",
        "adjusted_length",
    ],
)
def test_query_identity_chain_refused_before_core(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    reference = manifest["series"]["A"]
    series_path = path.parent / reference["path"]
    series = json.loads(series_path.read_bytes())
    calendar_path = path.parent / manifest["calendar"]["path"]
    calendar = json.loads(calendar_path.read_bytes())

    def update_checked_bytes(target: Path, value: Any, descriptor: dict[str, Any]) -> None:
        raw = json.dumps(value).encode()
        target.write_bytes(raw)
        descriptor["sha256"] = hashlib.sha256(raw).hexdigest()

    if change == "other_security_series":
        # Both the B file and its declared hash/IDs are valid. They cannot answer A.
        series.update(code="B", security_id="sec:B")
        series["series_id"] = series_content_id(series)
        reference.update(path="B.json", series_id=series["series_id"], security_id="sec:B")
        update_checked_bytes(path.parent / "B.json", series, reference)
    elif change in ("wrong_series_id", "wrong_security_id"):
        reference[change.removeprefix("wrong_")] = "different"
    elif change == "missing_series_id":
        reference.pop("series_id")
    elif change == "empty_security_id":
        reference["security_id"] = ""
    elif change == "null_series_id":
        reference["series_id"] = None
    elif change == "missing_calendar_id":
        manifest.pop("calendar_id")
    elif change in ("empty_calendar_id", "null_calendar_id"):
        manifest["calendar_id"] = "" if change == "empty_calendar_id" else None
    elif change == "different_calendar":
        calendar["calendar_id"] = "other-calendar"
        update_checked_bytes(calendar_path, calendar, manifest["calendar"])
    elif change == "series_calendar":
        series["calendar_id"] = "other-calendar"
        series["series_id"] = series_content_id(series)
        reference["series_id"] = series["series_id"]
        update_checked_bytes(series_path, series, reference)
    elif change in ("calendar_count", "calendar_count_bool"):
        manifest["calendar"]["count"] = 3 if change == "calendar_count" else True
    else:
        series[change.removesuffix("_length")].pop()
        series["series_id"] = series_content_id(series)
        reference["series_id"] = series["series_id"]
        update_checked_bytes(series_path, series, reference)
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def refuse_query_core(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Invalid checked query identity chain must never reach query core")

    monkeypatch.setattr("scripts.query_opportunity_history.query_security", refuse_query_core)
    with pytest.raises(ValueError, match="Query"):
        query_manifest(path, "A", "2020-01-01")


def test_calendar_count_optional_with_complete_identity_chain(tmp_path: Path) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    manifest["calendar"].pop("count")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = query_manifest(path, "A", "2020-01-01")
    assert result["evidence"]["series_id"] == manifest["series"]["A"]["series_id"]
    assert result["member"] is False


@pytest.mark.parametrize("change", ["reverse_dates", "timezone", "name"])
def test_rehashed_calendar_bytes_cannot_keep_stale_content_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    reference = manifest["calendar"]
    calendar_path = path.parent / reference["path"]
    calendar = json.loads(calendar_path.read_bytes())
    if change == "reverse_dates":
        calendar["dates"].reverse()
    else:
        calendar[change] = "changed metadata"
    raw = json.dumps(calendar).encode()
    calendar_path.write_bytes(raw)
    reference["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def refuse_query_core(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Stale calendar content ID must never reach query core")

    monkeypatch.setattr("scripts.query_opportunity_history.query_security", refuse_query_core)
    with pytest.raises(ValueError, match="calendar content identity"):
        query_manifest(path, "A", "2020-01-01")


@pytest.mark.parametrize("dates", [["2020-01-02", "2020-01-01"], ["2020-01-01", "2020-01-01"], ["2020-01-01", 2]])
def test_even_validly_resigned_calendar_dates_must_be_sorted_unique_strings(dates: list[Any]) -> None:
    calendar: dict[str, Any] = {"dates": dates}
    calendar["calendar_id"] = calendar_content_id(calendar)
    with pytest.raises(ValueError, match="calendar dates"):
        validate_calendar_identity(calendar)


def test_calendar_identity_matches_exporter_full_object_definition() -> None:
    from research_core.opportunity_history_inputs import canonical_bytes

    content = {"schema_version": "opportunity-calendar.v1", "name": "測試 calendar", "timezone": "Asia/Taipei", "dates": ["2020-01-01"]}
    expected = "sha256:" + hashlib.sha256(canonical_bytes(content)).hexdigest()
    assert calendar_content_id(content | {"calendar_id": "stale"}) == expected
    validate_calendar_identity(content | {"calendar_id": expected})


def test_updated_calendar_identity_with_synchronized_series_is_valid(tmp_path: Path) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    calendar_ref = manifest["calendar"]
    calendar_path = path.parent / calendar_ref["path"]
    calendar = json.loads(calendar_path.read_bytes())
    calendar["name"] = "revised calendar metadata"
    new_id = calendar_content_id(calendar)
    calendar["calendar_id"] = new_id
    raw_calendar = json.dumps(calendar).encode()
    calendar_path.write_bytes(raw_calendar)
    calendar_ref["sha256"] = hashlib.sha256(raw_calendar).hexdigest()
    series_ref = manifest["series"]["A"]
    series_path = path.parent / series_ref["path"]
    series = json.loads(series_path.read_bytes())
    series["calendar_id"] = new_id
    series["series_id"] = series_content_id(series)
    series_ref["series_id"] = series["series_id"]
    raw_series = json.dumps(series).encode()
    series_path.write_bytes(raw_series)
    series_ref["sha256"] = hashlib.sha256(raw_series).hexdigest()
    manifest["calendar_id"] = new_id
    sync_query_table_identity(path.parent, manifest, series)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = query_manifest(path, "A", "2020-01-01")
    assert result["evidence"]["series_id"] == series["series_id"]
    assert result["evidence"]["calendar_sha256"] == calendar_ref["sha256"]


@pytest.mark.parametrize("price_field", ["raw", "adjusted"])
def test_rehashed_price_bytes_cannot_keep_stale_series_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, price_field: str) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    reference = manifest["series"]["A"]
    series_path = path.parent / reference["path"]
    series = json.loads(series_path.read_bytes())
    series[price_field][1] = 999
    raw = json.dumps(series).encode()
    series_path.write_bytes(raw)
    reference["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def refuse_query_core(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Stale series content ID must never reach query core")

    monkeypatch.setattr("scripts.query_opportunity_history.query_security", refuse_query_core)
    with pytest.raises(ValueError, match="series content identity"):
        query_manifest(path, "A", "2020-01-01")


def test_updated_price_content_with_synchronized_series_id_is_valid(tmp_path: Path) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    reference = manifest["series"]["A"]
    series_path = path.parent / reference["path"]
    series = json.loads(series_path.read_bytes())
    previous_id = series["series_id"]
    series["raw"][1] = series["adjusted"][1] = 120
    series["series_id"] = series_content_id(series)
    reference["series_id"] = series["series_id"]
    raw = json.dumps(series).encode()
    series_path.write_bytes(raw)
    reference["sha256"] = hashlib.sha256(raw).hexdigest()
    sync_query_table_identity(path.parent, manifest, series)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = query_manifest(path, "A", "2020-01-02")
    assert result["evidence"]["series_id"] == reference["series_id"] != previous_id
    assert result["evidence"]["series_sha256"] == reference["sha256"]


def test_series_identity_matches_exporter_full_object_definition() -> None:
    from research_core.opportunity_history_inputs import canonical_bytes

    content = {"code": "A", "security_id": "sec", "name": "測試 stock", "raw": [100, None], "adjusted": [100, None], "numeric_flags": {}}
    expected = "sha256:" + hashlib.sha256(canonical_bytes(content)).hexdigest()
    assert series_content_id(content | {"series_id": "stale"}) == expected
    validate_series_identity(content | {"series_id": expected})


@pytest.mark.parametrize(
    "change",
    [
        "security_series_id",
        "security_calendar_id",
        "security_missing",
        "security_duplicate",
        "security_missing_id",
        "interval_series_id",
        "interval_calendar_id",
        "interval_missing_series_id",
        "interval_missing_security_id",
    ],
)
def test_resigned_compact_row_identity_refused_before_core(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    series_ref = manifest["series"]["A"]
    name = "securities" if change.startswith("security_") else "representative_intervals"
    reference = manifest["tables"][name][0]
    table_path = path.parent / reference["path"]
    table = json.loads(table_path.read_bytes())
    if name == "representative_intervals":
        # This interval is inactive on query D; its identity must still be checked.
        table["rows"] = [
            {
                "security_id": series_ref["security_id"],
                "series_id": series_ref["series_id"],
                "start_index": 0,
                "end_exclusive_index": 1,
                "gain_base_index": 0,
                "wave_id": "wave",
                "earliest_candidate_id": None,
            }
        ]
    row = table["rows"][0]
    if change == "security_missing":
        table["rows"] = []
    elif change == "security_duplicate":
        table["rows"].append(dict(row))
    elif change in ("security_missing_id", "interval_missing_security_id"):
        row.pop("security_id")
    elif change == "interval_missing_series_id":
        row.pop("series_id")
    else:
        identity = "calendar_id" if change.endswith("calendar_id") else "series_id"
        row[identity] = "stale-other-catalog-identity"
    raw = json.dumps(table).encode()
    table_path.write_bytes(raw)
    reference["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def refuse_query_core(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Mismatched compact row identity must never reach query core")

    monkeypatch.setattr("scripts.query_opportunity_history.query_security", refuse_query_core)
    with pytest.raises(ValueError, match="Query"):
        query_manifest(path, "A", "2020-01-02")


@pytest.mark.parametrize("include_calendar_id", [False, True])
def test_checked_selected_rows_allow_unrelated_security_and_original_interval_shape(tmp_path: Path, include_calendar_id: bool) -> None:
    path, manifest = member_catalog(tmp_path / "catalog")
    securities_ref = manifest["tables"]["securities"][0]
    securities_path = path.parent / securities_ref["path"]
    securities = json.loads(securities_path.read_bytes())
    securities["rows"].append({"security_id": "other", "series_id": "other-series", "calendar_id": "other-calendar", "stock_opportunity_eligible": False})
    raw_securities = json.dumps(securities).encode()
    securities_path.write_bytes(raw_securities)
    securities_ref["sha256"] = hashlib.sha256(raw_securities).hexdigest()
    intervals_ref = manifest["tables"]["representative_intervals"][0]
    interval = read_reference(path.parent, intervals_ref)["rows"][0]
    if include_calendar_id:
        interval["calendar_id"] = manifest["calendar_id"]
    other = dict(interval) | {"security_id": "other", "series_id": "other-series", "calendar_id": "other-calendar"}
    raw_intervals = json.dumps({"rows": [interval, other]}).encode()
    (path.parent / intervals_ref["path"]).write_bytes(raw_intervals)
    intervals_ref["sha256"] = hashlib.sha256(raw_intervals).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    if include_calendar_id:
        with pytest.raises(ValueError, match="native reconstruction mismatch"):
            query_manifest(path, "A", "2020-01-04")
        return
    result = query_manifest(path, "A", "2020-01-04")
    assert result["member"] and result["stock_opportunity_count"] == 1
    assert result["gain"] == pytest.approx(0.8)


@pytest.mark.parametrize("change", ["false_eligibility", "nonboolean_eligibility", "changed_spans", "missing_spans", "boolean_span_index"])
def test_same_identity_resigned_driving_fields_rejected_before_core(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    reference = manifest["tables"]["securities"][0]
    table_path = path.parent / reference["path"]
    table = json.loads(table_path.read_bytes())
    security = table["rows"][0]
    if change == "false_eligibility":
        security["stock_opportunity_eligible"] = False
    elif change == "nonboolean_eligibility":
        security["stock_opportunity_eligible"] = 1
    elif change == "missing_spans":
        security.pop("continuity_runs")
    elif change == "boolean_span_index":
        security["continuity_runs"][0]["start"] = False
    else:
        security["continuity_runs"][0]["end"] = 0
    raw = json.dumps(table).encode()
    table_path.write_bytes(raw)
    reference["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def refuse_query_core(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Invalid compact driving fields must never reach query core")

    monkeypatch.setattr("scripts.query_opportunity_history.query_security", refuse_query_core)
    with pytest.raises(ValueError, match="eligibility|continuity_runs"):
        query_manifest(path, "A", "2020-01-02")


def test_query_uses_exact_js_floating_boundary_in_one_selected_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.opportunity_history_source_runs import expected_source_runs

    path, manifest = member_catalog(tmp_path / "catalog", prices=[6.02, 8.127, 10, 12, 9, 6.7])
    native = read_reference(path.parent, manifest["native"]["A"])
    assert native["source_run_indices"] == [0] * 6
    calls: list[set[str] | None] = []

    def tracked(source: Path, codes: set[str] | None = None) -> dict[str, list[int | None]]:
        calls.append(codes)
        runs = expected_source_runs(source, codes)
        assert runs == {"A": [0] * 6}
        return runs

    monkeypatch.setattr("scripts.query_opportunity_history.expected_source_runs", tracked)
    result = query_manifest(path, "A", "2020-01-02")
    assert result["gain"] == pytest.approx(0.35) and result["gain_reason"] is None
    assert calls == [{"A"}]
    assert not (path.parent / "not-read-native.json.gz").exists()


def test_query_cli_node_unavailable_is_clean_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    path, _ = catalog(tmp_path / "catalog")

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError("synthetic missing Node")

    monkeypatch.setattr("scripts.opportunity_history_source_runs.subprocess.run", unavailable)
    with pytest.raises(SystemExit) as error:
        main(["--manifest", str(path), "--code", "A", "--date", "2020-01-02", "--expected-manifest-sha256", fixture_manifest_sha256(path)])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "Node is unavailable" in captured.err and "Traceback" not in captured.err and not captured.out


@pytest.mark.parametrize("with_interval", [False, True])
def test_excluded_security_uses_frozen_fallback_without_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_interval: bool) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    reference = manifest["series"]["A"]
    series_path = path.parent / reference["path"]
    series = json.loads(series_path.read_bytes())
    series.update(instrument_role="etf", cohort="metadata_etf")
    series["series_id"] = series_content_id(series)
    reference["series_id"] = series["series_id"]
    raw = json.dumps(series).encode()
    series_path.write_bytes(raw)
    reference["sha256"] = hashlib.sha256(raw).hexdigest()
    sync_query_table_identity(path.parent, manifest, series)
    securities_ref = manifest["tables"]["securities"][0]
    securities_path = path.parent / securities_ref["path"]
    securities = json.loads(securities_path.read_bytes())
    securities["rows"][0]["stock_opportunity_eligible"] = False
    raw_securities = json.dumps(securities).encode()
    securities_path.write_bytes(raw_securities)
    securities_ref["sha256"] = hashlib.sha256(raw_securities).hexdigest()
    if with_interval:
        intervals_ref = manifest["tables"]["representative_intervals"][0]
        raw_intervals = json.dumps({"rows": [{"security_id": "sec", "series_id": series["series_id"]}]}).encode()
        (path.parent / intervals_ref["path"]).write_bytes(raw_intervals)
        intervals_ref["sha256"] = hashlib.sha256(raw_intervals).hexdigest()
    manifest["native"] = {}
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def reject_js(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Excluded security must not invoke JavaScript")

    monkeypatch.setattr("scripts.query_opportunity_history.expected_source_runs", reject_js)
    if with_interval:
        with pytest.raises(ValueError, match="excluded security"):
            query_manifest(path, "A", "2020-01-02")
    else:
        assert query_manifest(path, "A", "2020-01-02")["stock_opportunity_count"] == 0


def test_public_table_validator_requires_exact_runs_for_eligible(tmp_path: Path) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    series = read_reference(path.parent, manifest["series"]["A"])
    tables = {name: read_reference(path.parent, manifest["tables"][name][0])["rows"] for name in ("securities", "representative_intervals")}
    with pytest.raises(ValueError, match="requires exact JavaScript"):
        validate_query_tables(tables, series)


@pytest.mark.parametrize("change", ["negative_base", "base_after_start", "end_outside", "empty_interval", "boolean_index", "empty_wave", "overlap"])
def test_resigned_selected_interval_driving_bounds_refused_before_core(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    series_ref = manifest["series"]["A"]
    reference = manifest["tables"]["representative_intervals"][0]
    interval: dict[str, Any] = {
        "security_id": series_ref["security_id"],
        "series_id": series_ref["series_id"],
        "start_index": 0,
        "end_exclusive_index": 2,
        "gain_base_index": 0,
        "wave_id": "wave",
        "earliest_candidate_id": None,
    }
    rows = [interval]
    if change == "negative_base":
        interval["gain_base_index"] = -1
    elif change == "base_after_start":
        interval["gain_base_index"] = 1
    elif change == "end_outside":
        interval["end_exclusive_index"] = 3
    elif change == "empty_interval":
        interval["end_exclusive_index"] = 0
    elif change == "boolean_index":
        interval["start_index"] = False
    elif change == "empty_wave":
        interval["wave_id"] = ""
    else:
        rows.append(dict(interval) | {"start_index": 1, "wave_id": "other-wave"})
    raw = json.dumps({"rows": rows}).encode()
    (path.parent / reference["path"]).write_bytes(raw)
    reference["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def refuse_query_core(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Invalid interval driving semantics must never reach query core")

    monkeypatch.setattr("scripts.query_opportunity_history.query_security", refuse_query_core)
    with pytest.raises(ValueError, match="Query.*interval"):
        query_manifest(path, "A", "2020-01-02")


def test_adjacent_selected_intervals_are_valid_even_when_unsorted(tmp_path: Path) -> None:
    path, manifest = member_catalog(tmp_path / "catalog", prices=[100, 120, 150, 180, 134, 100, 120, 150, 180, 134, 100])
    series = read_reference(path.parent, manifest["series"]["A"])
    native = read_reference(path.parent, manifest["native"]["A"])
    security = read_reference(path.parent, manifest["tables"]["securities"][0])["rows"]
    intervals = read_reference(path.parent, manifest["tables"]["representative_intervals"][0])["rows"]
    assert len(intervals) == 2
    runs: list[int | None] = [0] * 11
    validate_query_tables(
        {"securities": security, "representative_intervals": list(reversed(intervals))},
        series,
        runs,
        native=native,
        calendar=read_reference(path.parent, manifest["calendar"]),
    )


@pytest.mark.parametrize(
    "change",
    ["shifted_start", "shifted_end", "different_base", "false_wave", "false_candidate", "extra_field", "extra_row", "security_extra_field"],
)
def test_resigned_within_bounds_rows_must_match_saved_native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    prices: list[float] | None = [100, 120, 150, 180, 134, 100, 120, 150, 180, 134, 100] if change == "different_base" else None
    path, manifest = member_catalog(tmp_path / "catalog", prices=prices)
    name = "securities" if change == "security_extra_field" else "representative_intervals"
    reference = manifest["tables"][name][0]
    table = read_reference(path.parent, reference)
    row = table["rows"][1 if change == "different_base" else 0]
    if change == "shifted_start":
        row["start_index"] = 1
    elif change == "shifted_end":
        row["end_exclusive_index"] = 1
    elif change == "different_base":
        row["gain_base_index"] = 0
    elif change == "false_wave":
        row["wave_id"] = "nonempty-false-wave"
    elif change == "false_candidate":
        row["earliest_candidate_id"] = "nonempty-false-candidate"
    elif change == "extra_row":
        table["rows"].append(dict(row))
    else:
        row["unexpected_payload"] = {"invented": True}
    raw = json.dumps(table).encode()
    (path.parent / reference["path"]).write_bytes(raw)
    reference["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def refuse_query_core(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Compact rows differing from saved native must never reach query core")

    monkeypatch.setattr("scripts.query_opportunity_history.query_security", refuse_query_core)
    with pytest.raises(ValueError, match="Query.*reconstruction|Query.*overlap"):
        query_manifest(path, "A", "2020-01-02")


@pytest.mark.parametrize("change", ["missing_runs", "wrong_runs", "input_identity", "code_identity", "count"])
def test_resigned_selected_native_still_requires_exact_identities(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    series = read_reference(path.parent, manifest["series"]["A"])
    native = read_reference(path.parent, manifest["native"]["A"])
    if change == "missing_runs":
        native.pop("source_run_indices")
    elif change == "wrong_runs":
        native["source_run_indices"] = [0, 1]
    elif change == "input_identity":
        native["input_identity"]["series_sha256"] = "0" * 64
    elif change == "code_identity":
        native["code_identity"]["wrapper"]["sha256"] = "0" * 64
    publish_native_fixture(path.parent, manifest, series, native)
    if change == "count":
        manifest["native"]["A"]["count"] = 5
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def refuse_query_core(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Invalid selected native must never reach query core")

    monkeypatch.setattr("scripts.query_opportunity_history.query_security", refuse_query_core)
    with pytest.raises(ValueError, match="Native|Query"):
        query_manifest(path, "A", "2020-01-02")


@pytest.mark.parametrize("change", ["security_id", "series_id", "sha256", "context", "missing_context", "empty_context", "both_omitted_context"])
def test_resigned_selected_native_receipt_identity_hash_context_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    reference = manifest["native"]["A"]["receipt"]
    receipt = read_reference(path.parent, reference)
    if change in ("security_id", "series_id", "sha256"):
        receipt[change] = "incorrect"
    elif change == "context":
        receipt["context"]["fixture_only"] = False
    elif change == "empty_context":
        receipt["context"] = {}
    else:
        receipt.pop("context")
        if change == "both_omitted_context":
            manifest.pop("producer_identity")
    raw = json.dumps(receipt).encode()
    (path.parent / reference["path"]).write_bytes(raw)
    reference["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def refuse_query_core(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Invalid native receipt must never reach query core")

    monkeypatch.setattr("scripts.query_opportunity_history.query_security", refuse_query_core)
    with pytest.raises(ValueError, match="Query.*receipt|Query.*context"):
        query_manifest(path, "A", "2020-01-02")


def test_query_reads_only_selected_native_and_returns_saved_byte_evidence(tmp_path: Path) -> None:
    path, manifest = member_catalog(tmp_path / "catalog")
    manifest["native"]["UNSELECTED"] = {"path": "must-not-read-native.json", "sha256": "0" * 64}
    manifest["series"]["UNSELECTED"] = {"path": "must-not-read-series.json", "sha256": "0" * 64}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = query_manifest(path, "A", "2020-01-04")
    assert result["gain"] == pytest.approx(0.8)
    assert result["evidence"]["native_sha256"] == manifest["native"]["A"]["sha256"]
    assert result["evidence"]["native_receipt_sha256"] == manifest["native"]["A"]["receipt"]["sha256"]
    assert result["evidence"]["reconstruction_policy"] == "selected_native_full_rows.preview.v1"


def test_public_eligible_table_gate_requires_verified_native_even_with_exact_runs(tmp_path: Path) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    series = read_reference(path.parent, manifest["series"]["A"])
    tables = {name: read_reference(path.parent, manifest["tables"][name][0])["rows"] for name in ("securities", "representative_intervals")}
    with pytest.raises(ValueError, match="requires verified native"):
        validate_query_tables(tables, series, [0, 0], calendar=read_reference(path.parent, manifest["calendar"]))


@pytest.mark.parametrize("change", ["error_with_retained_result", "wave_outside_calendar", "false_peak", "false_gain"])
def test_resigned_native_receipt_and_compact_rows_still_require_native_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    path, manifest = member_catalog(tmp_path / "catalog")
    series = read_reference(path.parent, manifest["series"]["A"])
    calendar = read_reference(path.parent, manifest["calendar"])
    native = read_reference(path.parent, manifest["native"]["A"])
    path.write_text(json.dumps(manifest), encoding="utf-8")
    original = query_manifest(path, "A", "2020-01-04")
    assert original["member"] and original["gain"] == pytest.approx(0.8)
    for record in native["native"]:
        if change == "error_with_retained_result":
            record.update(status="error", error={"name": "SyntheticFailure", "message": "Failure must not carry successful observations"})
        else:
            wave = record["result"]["waves"][0]
            if change == "wave_outside_calendar":
                wave.update(peak=6, observedThrough=6)
            elif change == "false_peak":
                wave.update(peak=0, gain=0)
            else:
                wave["gain"] = 999
    # Re-sign all the artifacts and rebuild the compact projection from the
    # malformed native. Correct hashes and reconstruction alone are insufficient.
    publish_native_fixture(path.parent, manifest, series, native)
    publish_query_tables(path.parent, manifest, series, calendar, native)
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def refuse_query_core(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Malformed saved native semantics must never reach query core")

    monkeypatch.setattr("scripts.query_opportunity_history.query_security", refuse_query_core)
    with pytest.raises(ValueError):
        query_manifest(path, "A", "2020-01-02")


def test_dense_member_fixture_preserves_original_scale_boundaries(tmp_path: Path) -> None:
    from scripts.opportunity_history_source_runs import expected_source_runs

    path, manifest = member_catalog(tmp_path / "catalog")
    assert expected_source_runs(path, {"A"}) == {"A": [0] * 6}
    native = read_reference(path.parent, manifest["native"]["A"])
    for record in native["native"]:
        small, large = record["result"]["waves"]
        assert (small["scale"], large["scale"]) == ("small", "large")
        for wave in (small, large):
            assert (wave["start"], wave["peak"]) == (0, 3)
            assert wave["gain"] == pytest.approx(80)
        if record["scale"] == "coarse":
            assert small["end"] == 5 and large["end"] is None
            assert large["observedThrough"] == 5 and large["rightCensored"] is True
            assert "parentId" not in small
        else:
            assert (small["end"], large["end"]) == (4, 5)
            assert small["parentId"] == large["id"]
    assert query_manifest(path, "A", "2020-01-04")["gain"] == pytest.approx(0.8)
    assert query_manifest(path, "A", "2020-01-06")["member"] is False


@pytest.mark.parametrize("change", ["swapped_scales", "forwardGain", "drawdown", "outcome"])
def test_resigned_native_and_compact_projection_require_original_wave_and_launch_derivation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    path, manifest = member_catalog(tmp_path / "catalog", with_candidates=True)
    series = read_reference(path.parent, manifest["series"]["A"])
    calendar = read_reference(path.parent, manifest["calendar"])
    native = read_reference(path.parent, manifest["native"]["A"])
    assert query_manifest(path, "A", "2020-01-04")["gain"] == pytest.approx(0.8)
    for record in native["native"]:
        launches = record["result"]["launches"]
        assert len(launches) == 1
        assert launches[0]["index"] == 1
        assert launches[0]["forwardGain"] == pytest.approx(50)
        assert launches[0]["drawdown"] == pytest.approx(0)
        assert launches[0]["outcome"] == "continued"
        if change == "swapped_scales":
            small, large = record["result"]["waves"]
            small["scale"], large["scale"] = large["scale"], small["scale"]
        else:
            launches[0][change] = {"forwardGain": 999, "drawdown": -25, "outcome": "failed"}[change]
    publish_native_fixture(path.parent, manifest, series, native)
    publish_query_tables(path.parent, manifest, series, calendar, native)
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def refuse_query_core(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Re-signed native derivation mismatches must never reach query core")

    monkeypatch.setattr("scripts.query_opportunity_history.query_security", refuse_query_core)
    with pytest.raises(ValueError):
        query_manifest(path, "A", "2020-01-04")


@pytest.mark.parametrize(
    "day",
    [
        "20200104",
        "2019-W01-4",
        "2020-02-30",
        "2019-02-29",
        "1900-02-29",
        "2020-2-01",
        "2020-01-4",
        "0000-01-01",
        "10000-01-01",
        "2020-00-01",
        "2020-01-00",
        "2020-13-01",
        "2020-01-01T00:00:00",
        "",
        " 2020-01-01",
    ],
)
def test_resigned_calendar_requires_real_canonical_gregorian_dates(day: str) -> None:
    calendar: dict[str, Any] = {"schema_version": "opportunity-calendar.v1", "dates": [day]}
    calendar["calendar_id"] = calendar_content_id(calendar)
    with pytest.raises(ValueError, match="real Gregorian YYYY-MM-DD dates"):
        validate_calendar_identity(calendar)


@pytest.mark.parametrize("day", ["0001-01-01", "1900-02-28", "2000-02-29", "2020-02-29", "2020-01-04", "9999-12-31"])
def test_calendar_accepts_real_gregorian_leap_dates_and_nontrading_dates(day: str) -> None:
    calendar: dict[str, Any] = {"schema_version": "opportunity-calendar.v1", "dates": [day]}
    calendar["calendar_id"] = calendar_content_id(calendar)
    validate_calendar_identity(calendar)


def test_consistently_resigned_noncanonical_calendar_rejected_before_query_core(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, manifest = catalog(tmp_path / "catalog")
    calendar_ref = manifest["calendar"]
    calendar_path = path.parent / calendar_ref["path"]
    calendar = read_reference(path.parent, calendar_ref)
    calendar.update(dates=["20200104", "20200105"], start="20200104", end="20200105")
    calendar["calendar_id"] = calendar_content_id(calendar)
    raw_calendar = json.dumps(calendar).encode()
    calendar_path.write_bytes(raw_calendar)
    calendar_ref["sha256"] = hashlib.sha256(raw_calendar).hexdigest()
    manifest["calendar_id"] = calendar["calendar_id"]
    series_ref = manifest["series"]["A"]
    series = read_reference(path.parent, series_ref)
    series["calendar_id"] = calendar["calendar_id"]
    series["series_id"] = series_content_id(series)
    raw_series = json.dumps(series).encode()
    (path.parent / series_ref["path"]).write_bytes(raw_series)
    series_ref.update(series_id=series["series_id"], sha256=hashlib.sha256(raw_series).hexdigest())
    sync_query_table_identity(path.parent, manifest, series)
    path.write_text(json.dumps(manifest), encoding="utf-8")

    def refuse_downstream(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Malformed calendar dates must be rejected before source transforms or query core")

    monkeypatch.setattr("scripts.query_opportunity_history.expected_source_runs", refuse_downstream)
    monkeypatch.setattr("scripts.query_opportunity_history.query_security", refuse_downstream)
    with pytest.raises(ValueError, match="real Gregorian YYYY-MM-DD dates"):
        query_manifest(path, "A", "20200104")
