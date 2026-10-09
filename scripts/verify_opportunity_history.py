"""Read-only verification of compact history catalogs and pinned series."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research_core.opportunity_history_catalog import adapt_security, build_representative_intervals, gain_at, query_security
from scripts.build_opportunity_history import resolve_params_artifact, validate_native
from scripts.opportunity_history_native_validation import (
    _calendar_index as _calendar_index,
)
from scripts.opportunity_history_native_validation import (
    validate_candidate_bounds as validate_candidate_bounds,
)
from scripts.opportunity_history_native_validation import (
    validate_native_semantics,
    validate_wave_semantics,
)
from scripts.opportunity_history_native_validation import (
    validate_native_support_order as validate_native_support_order,
)
from scripts.opportunity_history_native_validation import (
    validate_phase_bounds as validate_phase_bounds,
)
from scripts.opportunity_history_native_validation import (
    validate_support_bounds as validate_support_bounds,
)
from scripts.query_opportunity_history import validate_calendar_identity, validate_manifest_identity, validate_manifest_trust, validate_series_identity

PAIRS = {(method, scale) for method in ("segments", "filter") for scale in ("fine", "balanced", "coarse")}
GAIN_POLICY_CONTEXT = "current V2 gain policy; archived V1 requires preserved f6135c6/legacy gain verifier; do not rewrite V1"
COMPACT_TABLES = frozenset({
    "securities",
    "methods",
    "baseline_waves",
    "source_phases",
    "candidates",
    "support_records",
    "relations",
    "representative_intervals",
    "transitions",
})


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _read(path: Path) -> Any:
    data = path.read_bytes()
    if path.suffix == ".gz":
        data = gzip.decompress(data)

    def reject_constant(value: str) -> None:
        raise ValueError(f"Nonfinite JSON constant: {value}")

    return json.loads(data, parse_constant=reject_constant)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checked(root: Path, reference: dict[str, Any]) -> Path:
    path = root / reference["path"]
    _require(_hash(path) == reference["sha256"], f"Hash mismatch: {path}")
    return path


def _unique(rows: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result = {row[key]: row for row in rows}
    _require(len(result) == len(rows), f"Duplicate {label} {key}")
    return result


def _near(actual: Any, expected: float, label: str) -> None:
    _require(isinstance(actual, (int, float)) and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-8), f"Numeric mismatch: {label}")


def _method_match(row: dict[str, Any], method: dict[str, Any]) -> bool:
    return row["method"] == method["method"] and row["method_scale"] == method["scale"]


def _expected_source_runs(manifest_path: Path) -> dict[str, list[int | None]]:
    # Batch the pinned pure source transform; no method analysis is executed.
    from scripts.opportunity_history_source_runs import expected_source_runs

    return expected_source_runs(manifest_path)


def _row_hash(row: dict[str, Any]) -> str:
    encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_producer_context(
    manifest_path: Path, manifest: dict[str, Any], series_manifest: dict[str, Any], params_path: Path | None = None
) -> dict[str, Any]:
    """Bind source context to preserved inputs without substituting current code."""
    explicit_params = params_path is not None
    context = manifest.get("producer_identity")
    _require(isinstance(context, dict), "Missing or invalid producer context")
    assert isinstance(context, dict)
    fields = ("calendar_sha256", "series_manifest_sha256", "input_receipt_sha256", "config_sha256", "producer_sha256", "adapter_sha256")
    for field in fields:
        value = context.get(field)
        _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None, f"Invalid producer context hash: {field}")
    valid_code_identity = isinstance(context.get("code_identity"), dict) and context["code_identity"] == manifest.get("code_identity")
    _require(valid_code_identity, "Producer context code identity mismatch")
    _require(isinstance(manifest.get("input_receipt"), dict), "Missing or invalid manifest input receipt")
    _require(series_manifest.get("input_receipt") == manifest["input_receipt"], "Series manifest/input receipt mismatch")
    _require(series_manifest.get("calendar") == manifest["calendar"], "Series manifest/calendar descriptor mismatch")
    root = manifest_path.parent
    bound_hashes = {}
    for field, descriptor in (("calendar_sha256", manifest["calendar"]), ("series_manifest_sha256", manifest["series_manifest"])):
        _checked(root, descriptor)
        actual = descriptor["sha256"]
        _require(context[field] == actual, f"Producer context hash mismatch: {field}")
        bound_hashes[field] = actual
    receipt_sha = _row_hash(manifest["input_receipt"])
    _require(context["input_receipt_sha256"] == receipt_sha, "Producer context hash mismatch: input_receipt_sha256")
    bound_hashes["input_receipt_sha256"] = receipt_sha
    # The original producer hashes params.json bytes; canonical config JSON is not interchangeable.
    params_path = resolve_params_artifact(manifest_path, manifest, params_path)
    config_sha = _hash(params_path)
    _require(context["config_sha256"] == config_sha, "Producer context hash mismatch: config_sha256")
    _require(_read(params_path) == manifest.get("config"), "Pinned params/manifest config mismatch")
    bound_hashes["config_sha256"] = config_sha
    if "params_artifact" in manifest:
        config_path = manifest["params_artifact"]["path"]
    elif not explicit_params:
        config_path = "../params.json"
    else:
        config_path = "external:params-by-sha256"
    return {
        "schema_version": "opportunity-producer-context-verification.v1",
        "producer_identity": context,
        "bound_input_hashes": bound_hashes,
        "config_path": config_path,
        "config_hash_basis": "original_params_file_bytes_and_parsed_object_equality",
        "producer_adapter_code_policy": "original code bytes not read; source SHA shape and per-native receipt context consistency only",
    }


def validate_native_context(receipt: dict[str, Any], context: dict[str, Any], code: str) -> None:
    """Reject re-signed receipts whose source run context differs from manifest."""
    _require(receipt.get("context") == context, f"Native receipt producer context mismatch: {code}")


def _verify_reconstruction(series: dict[str, Any], calendar: dict[str, Any], native: dict[str, Any], owned: dict[str, list[dict[str, Any]]]) -> Counter[str]:
    """Compare one security only; retain multiplicity and all native fields."""
    rebuilt = adapt_security(series, calendar, native)
    eligible = series["instrument_role"] == "stock" and series["cohort"] in {"metadata_stock", "innovation_board"}
    rebuilt["securities"][0].update({
        "stock_opportunity_eligible": eligible,
        "method_eligibility_reason": "stock_cohort" if eligible else "excluded_role_or_identity",
        "coverage": series.get("coverage", {}),
    })
    for name, expected_rows in rebuilt.items():
        actual_rows = owned.get(name, [])
        context = (
            f"{series['code']} {name}; current V2 adapter reconstruction. "
            "Archived V1 gain-policy differences require preserved f6135c6/legacy gain verifier; do not rewrite V1"
        )
        _require(len(actual_rows) == len(expected_rows), f"Native reconstruction count mismatch: {context}")
        expected_hashes = Counter(_row_hash(row) for row in expected_rows)
        actual_hashes = Counter(_row_hash(row) for row in actual_rows)
        _require(actual_hashes == expected_hashes, f"Native reconstruction mismatch: {context}")
    return Counter({name: len(owned.get(name, [])) for name in rebuilt})


def _verify_support(rows: list[dict[str, Any]], candidates: dict[str, dict[str, Any]]) -> None:
    indexed: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates.values():
        indexed[(candidate["security_id"], candidate["method"], candidate["kind"], candidate["method_scale"])].append(candidate)
    for row in rows:
        target_id = row["target_catalog_id"]
        _require(target_id in candidates, "Unresolved support target")
        target = candidates[target_id]
        _require(row["security_id"] == target["security_id"], "Support target security mismatch")
        _require(row["method"] == target["method"] and row["scale"] == target["method_scale"], "Support target method/scale mismatch")
        _require(row["index"] == target["index"] and row["kind"] == target["kind"], "Support target kind/index mismatch")
        matched = row["matched_catalog_ids"]
        native_matches = row["matched_ids"]
        _require(row["support"] == len(matched) == len(native_matches) <= 3, "Support count mismatch")
        _require(len(set(matched)) == len(matched), "Duplicate support match")
        scales = set()
        indices = []
        for candidate_id, native_match in zip(matched, native_matches, strict=True):
            _require(candidate_id in candidates, "Unresolved support match")
            candidate = candidates[candidate_id]
            _require(candidate["security_id"] == target["security_id"], "Support match security mismatch")
            _require(candidate["method"] == target["method"] and candidate["kind"] == target["kind"], "Support match method/kind mismatch")
            _require(abs(candidate["index"] - target["index"]) <= 20, "Support exceeds calendar radius")
            _require(candidate["method_scale"] not in scales, "Duplicate support scale")
            scales.add(candidate["method_scale"])
            _require(
                native_match
                == {"method": candidate["method"], "scale": candidate["method_scale"], "candidate_id": candidate["native_id"], "index": candidate["index"]},
                "Support native reference mismatch",
            )
            indices.append(candidate["index"])
        expected_scales = set()
        for scale in ("fine", "balanced", "coarse"):
            available = [
                candidate
                for candidate in indexed[(target["security_id"], target["method"], target["kind"], scale)]
                if abs(candidate["index"] - target["index"]) <= 20
            ]
            if available:
                expected_scales.add(scale)
                selected = next((candidates[candidate_id] for candidate_id in matched if candidates[candidate_id]["method_scale"] == scale), None)
                _require(selected is not None, "Missing support scale")
                assert selected is not None
                minimum_distance = min(abs(candidate["index"] - target["index"]) for candidate in available)
                _require(abs(selected["index"] - target["index"]) == minimum_distance, "Support match is not nearest")
        _require(scales == expected_scales, "Support scale coverage mismatch")
        _require(bool(indices) and row["rangeStart"] == min(indices) and row["rangeEnd"] == max(indices), "Support range mismatch")


def verify_catalog(manifest_path: Path, params_path: Path | None = None, *, expected_manifest_sha256: str | None = None) -> dict[str, Any]:
    """Verify saved native provenance plus independent compact semantics."""
    root = manifest_path.parent
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    validate_manifest_identity(manifest)
    manifest_trust = validate_manifest_trust(manifest_bytes, expected_manifest_sha256)
    calendar = _read(_checked(root, manifest["calendar"]))
    validate_calendar_identity(calendar)
    dates = calendar["dates"]
    _require(dates == sorted(set(dates)), "Calendar is not sorted unique")
    _require(manifest["calendar_id"] == calendar["calendar_id"], "Calendar identity mismatch")
    _require(manifest["calendar"]["count"] == len(dates), "Calendar count mismatch")
    series_manifest = _read(_checked(root, manifest["series_manifest"]))
    producer_context_evidence = validate_producer_context(manifest_path, manifest, series_manifest, params_path)
    _require(series_manifest["count"] == len(series_manifest["rows"]) == manifest["security_count"], "Series/security count mismatch")
    _require(manifest["series_manifest"]["count"] == series_manifest["count"], "Series descriptor count mismatch")
    tables: dict[str, list[dict[str, Any]]] = {}
    _require(set(manifest["tables"]) == COMPACT_TABLES, "Unknown or missing compact table keys")
    for name, references in manifest["tables"].items():
        rows = []
        for reference in references:
            part = _read(_checked(root, reference))["rows"]
            _require(isinstance(part, list), f"Invalid table rows: {name}")
            for row in part:
                _require(isinstance(row, dict), f"Invalid table row: {name}")
                if name != "relations":
                    valid_owner = isinstance(row.get("security_id"), str) and bool(row["security_id"])
                    _require(valid_owner, f"Missing or invalid security owner: {name}")
            _require(len(part) == reference["count"], f"Table count mismatch: {name}")
            rows.extend(part)
        tables[name] = rows
    for name, reference in manifest.get("extras", {}).items():
        extra = _read(_checked(root, reference))
        if "count" in reference:
            _require(len(extra["rows"]) == reference["count"], f"Extra count mismatch: {name}")
    securities = _unique(tables["securities"], "security_id", "security")
    _require(len(securities) == manifest["security_count"], "Security table count mismatch")
    methods = _unique(tables["methods"], "id", "method")
    waves = _unique(tables["baseline_waves"], "id", "wave")
    candidates = _unique(tables["candidates"], "id", "candidate")
    phases = _unique(tables["source_phases"], "id", "phase")
    _unique(tables["support_records"], "id", "support")
    by_security: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    grouped_counts: Counter[str] = Counter()
    for name, rows in tables.items():
        if name == "relations":
            continue
        for row in rows:
            _require(row["security_id"] in securities, f"Unresolved security reference: {name}")
            by_security[row["security_id"]][name].append(row)
            grouped_counts[name] += 1
    analyzed = {row["security_id"] for row in securities.values() if row["stock_opportunity_eligible"]}
    _require(len(analyzed) == manifest["analyzed_security_count"], "Analyzed security count mismatch")
    alias_map: dict[str, dict[str, Any]] = {}
    native_aliases: dict[tuple[str, str, str, str], str] = {}
    for wave in waves.values():
        _require(wave["gain_unit"] == wave["maxDrawdown_unit"] == "percent", "Wave unit mismatch")
        for alias in wave["aliases"]:
            _require(alias["method_scale"] == wave["method_scale"], "Alias scale mismatch")
            _require(alias["source_id"] not in alias_map, "Duplicate source alias ID")
            alias_map[alias["source_id"]] = wave
            key = (wave["security_id"], alias["method"], alias["method_scale"], alias["native_id"])
            _require(key not in native_aliases, "Duplicate native wave identity")
            native_aliases[key] = wave["id"]
    alias_relations = set()
    parent_relations = set()
    all_ids = set(waves) | set(candidates) | set(phases) | set(alias_map)
    for relation in tables["relations"]:
        _require(relation["left_id"] in all_ids, "Unresolved relation left ID")
        left_row = alias_map.get(relation["left_id"]) or waves.get(relation["left_id"]) or candidates.get(relation["left_id"]) or phases[relation["left_id"]]
        owner = left_row["security_id"]
        _require(relation.get("security_id", owner) == owner, "Relation owner disagrees with left ID")
        by_security[owner]["relations"].append(relation)
        grouped_counts["relations"] += 1
        right = relation["right_id"]
        _require(right in all_ids or (right is None and relation["kind"] == "native_parent"), "Unresolved relation right ID")
        if right is not None:
            left_row = (
                alias_map.get(relation["left_id"]) or waves.get(relation["left_id"]) or candidates.get(relation["left_id"]) or phases[relation["left_id"]]
            )
            left_security = left_row["security_id"]
            right_security = (alias_map.get(right) or waves.get(right) or candidates.get(right) or phases[right])["security_id"]
            _require(left_security == right_security, "Relation crosses securities")
        if relation["kind"] == "equality_alias":
            _require(relation["left_id"] in alias_map and alias_map[relation["left_id"]]["id"] == right, "Invalid equality alias")
            alias_relations.add((relation["left_id"], right))
        elif relation["kind"] == "native_parent":
            parent_relations.add((relation["left_id"], relation["method"], relation["native_parent_id"], right))
        elif relation["kind"] == "candidate_index_in_wave":
            assert right is not None
            wave, candidate = waves[relation["left_id"]], candidates[right]
            limit = wave["end"] if wave["end"] is not None else wave["observedThrough"] + 1
            _require(wave["start"] <= candidate["index"] < limit and relation["index"] == candidate["index"], "Candidate membership violates exclusive end")
    for source_id, wave in alias_map.items():
        _require((source_id, wave["id"]) in alias_relations, "Missing equality alias relation")
    for wave in waves.values():
        for alias in wave["aliases"]:
            if alias["native_parent_id"] is not None:
                key = (wave["security_id"], alias["method"], alias["method_scale"], alias["native_parent_id"])
                expected_parent = native_aliases.get(key)
                _require((wave["id"], alias["method"], alias["native_parent_id"], expected_parent) in parent_relations, "Native parent relation mismatch")
    for candidate in candidates.values():
        validate_candidate_bounds(candidate, len(dates))
        _require(all(candidate[field] == "percent" for field in ("gain_unit", "forwardGain_unit", "drawdown_unit")), "Candidate unit mismatch")
        for wave_id in candidate["wave_ids"]:
            _require(wave_id in waves, "Unresolved candidate wave")
            wave = waves[wave_id]
            limit = wave["end"] if wave["end"] is not None else wave["observedThrough"] + 1
            valid_membership = wave["security_id"] == candidate["security_id"] and wave["start"] <= candidate["index"] < limit
            _require(valid_membership, "Candidate wave violates membership boundary")
    for phase in phases.values():
        validate_phase_bounds(phase, len(dates))
    for support in tables["support_records"]:
        validate_support_bounds(support, len(dates))
    _verify_support(tables["support_records"], candidates)
    _require({row["target_catalog_id"] for row in tables["support_records"]} == set(candidates), "Support does not cover every candidate")
    _require(len(tables["support_records"]) == len(candidates), "Support target count mismatch")
    series_rows = _unique(series_manifest["rows"], "code", "series code")
    _require(set(series_rows) == set(manifest["series"]), "Series map coverage mismatch")
    _require(set(manifest["native"]) == {row["code"] for row in securities.values() if row["security_id"] in analyzed}, "Native file coverage mismatch")
    totals: Counter[str] = Counter()
    _require(all(grouped_counts[name] == len(rows) for name, rows in tables.items()), "Compact rows were not grouped exactly once")
    consumed_counts: Counter[str] = Counter()
    expected_runs: dict[str, list[int | None]] | None = None
    for code, reference in manifest["series"].items():
        _require(all(reference[key] == series_rows[code][key] for key in ("path", "sha256", "series_id", "security_id")), "Series reference mismatch")
        series = _read(_checked(root, reference))
        validate_series_identity(series)
        security_id = series["security_id"]
        _require(security_id in securities, "Series security missing")
        security = securities[security_id]
        _require(
            all(security[field] == series[field] for field in ("code", "series_id", "calendar_id", "cohort", "instrument_role")),
            "Compact security/series metadata mismatch",
        )
        _require(security["coverage"] == series.get("coverage", {}), "Compact coverage/series mismatch")
        expected_eligibility = series["instrument_role"] == "stock" and series["cohort"] in {"metadata_stock", "innovation_board"}
        _require(security["stock_opportunity_eligible"] == expected_eligibility, "Compact eligibility/series mismatch")
        valid_identity = series["code"] == code and series["series_id"] == reference["series_id"] and series["calendar_id"] == manifest["calendar_id"]
        _require(valid_identity, "Series identity mismatch")
        _require(len(series["raw"]) == len(series["adjusted"]) == len(dates), "Series alignment mismatch")
        owned = by_security[security_id]
        security_methods = owned["methods"]
        if security_id in analyzed:
            _require(series["instrument_role"] == "stock", "Analyzed non-stock role")
            _require(len(security_methods) == 6 and {(row["method"], row["scale"]) for row in security_methods} == PAIRS, "Analyzed stock needs six methods")
            native_reference = manifest["native"][code]
            native_path = _checked(root, native_reference)
            native_receipt = _read(_checked(root, native_reference["receipt"]))
            validate_native_context(native_receipt, manifest["producer_identity"], code)
            _require(native_reference["count"] == 6 and native_receipt["sha256"] == native_reference["sha256"], "Native receipt/count mismatch")
            _require(native_receipt["security_id"] == security_id and native_receipt["series_id"] == series["series_id"], "Native receipt identity mismatch")
            native = _read(native_path)
            expected_input = {"series_sha256": reference["sha256"], "calendar_sha256": manifest["calendar"]["sha256"]}
            validate_native(native, series, expected_input, manifest["code_identity"])
            _require("source_run_indices" in native, f"V2 eligible native requires exact source_run_indices: {code}")
            validate_native_semantics(native, series, calendar)
            if expected_runs is None:
                expected_runs = _expected_source_runs(manifest_path)
                _require(set(expected_runs) == set(manifest["native"]), "Exact source run code coverage mismatch")
            _require(code in expected_runs, f"Missing exact source run expectation: {code}")
            _require(native["source_run_indices"] == expected_runs[code], f"Exact pinned JS source run mismatch: {code}")
            totals["exact_source_runs_verified_count"] += 1
            totals["parsed_native_count"] += 1
        else:
            _require(not security_methods and not owned["baseline_waves"] and not owned["candidates"], "Excluded role has method results")
            no_native = {
                **{field: series[field] for field in ("security_id", "series_id", "calendar_id")},
                "input_identity": {"series_sha256": reference["sha256"], "calendar_sha256": manifest["calendar"]["sha256"]},
                "native": [],
                "support_records": [],
            }
            native = no_native
            totals["reconstructed_without_native_count"] += 1
        for method in security_methods:
            _require(method["status"] in {"ok", "error"}, "Unknown method status")
            _require(method["status"] != "error" or bool(method["error"]), "Failure lacks error evidence")
            if method["status"] == "error":
                _require(method["wave_count"] == method["phase_count"] == method["candidate_count"] == 0, "Failed method has successful rows")
            alias_count = sum(_method_match(alias, method) for wave in owned["baseline_waves"] for alias in wave["aliases"])
            _require(alias_count == method["wave_count"], "Native wave count conservation failed")
            _require(sum(_method_match(row, method) for row in owned["source_phases"]) == method["phase_count"], "Phase count conservation failed")
            _require(sum(_method_match(row, method) for row in owned["candidates"]) == method["candidate_count"], "Candidate count conservation failed")
            totals["native_wave_count"] += alias_count
            totals["method_failures"] += method["status"] == "error"
            totals["nonconverged_methods"] += isinstance(method.get("diagnostics"), dict) and method["diagnostics"].get("converged") is False
        for wave in owned["baseline_waves"]:
            validate_wave_semantics(wave, series, len(dates), native["source_run_indices"])
        expected_intervals, expected_transitions = build_representative_intervals(owned["baseline_waves"], dates, owned["candidates"])
        actual_intervals = sorted(owned["representative_intervals"], key=lambda row: row["start_index"])
        actual_transitions = sorted(owned["transitions"], key=lambda row: row["index"])
        _require(len(actual_intervals) == len(expected_intervals), "Representative interval count mismatch")
        _require(len(actual_transitions) == len(expected_transitions), "Representative transition count mismatch")
        for actual, expected in zip(actual_intervals, expected_intervals, strict=True):
            _require(all(actual[key] == value for key, value in expected.items()), "Representative interval rebuild mismatch")
            _require(actual["series_id"] == series["series_id"], "Interval series identity mismatch")
        for actual, expected in zip(actual_transitions, expected_transitions, strict=True):
            _require(all(actual[key] == value for key, value in expected.items()), "Representative transition rebuild mismatch")
            _require(actual["gain_unit"] == actual["gain_jump_unit"] == "fraction", "Transition unit mismatch")
        run_indices: list[int | None] = [None] * len(dates)
        for span in security.get("continuity_runs", []):
            run_indices[span["start"] : span["end"] + 1] = [span["run_id"]] * (span["end"] - span["start"] + 1)
        gain_series = series | {"source_run_indices": run_indices}
        for transition in actual_transitions:
            gains = {}
            for side in ("old", "new"):
                base = transition[f"{side}_gain_base_index"]
                gain, reason = gain_at(gain_series, dates, base, transition["index"]) if base is not None else (None, "no_wave")
                gains[side] = gain
                if gain is None:
                    _require(transition[f"{side}_gain"] is None, f"Unavailable transition gain claimed; {GAIN_POLICY_CONTEXT}")
                else:
                    _near(transition[f"{side}_gain"], gain, f"transition gain fraction; {GAIN_POLICY_CONTEXT}")
                _require(transition[f"{side}_gain_reason"] == reason, f"Transition gain reason mismatch; {GAIN_POLICY_CONTEXT}")
            expected_jump = gains["new"] - gains["old"] if gains["new"] is not None and gains["old"] is not None else None
            if expected_jump is None:
                _require(transition["gain_jump"] is None, f"Unavailable transition jump claimed; {GAIN_POLICY_CONTEXT}")
            else:
                _near(transition["gain_jump"], expected_jump, f"transition jump fraction; {GAIN_POLICY_CONTEXT}")
        for previous, following in zip(actual_intervals, actual_intervals[1:]):
            _require(previous["end_exclusive_index"] <= following["start_index"], "Representative intervals overlap")
        for interval in actual_intervals:
            for i in {interval["start_index"], interval["end_exclusive_index"] - 1}:
                query = query_security(owned, series, dates, dates[i])
                _require(query["member"] and query["wave_id"] == interval["wave_id"] and query["gain_unit"] == "fraction", "Query membership/unit mismatch")
        totals["coverage_caveats"] += len(security.get("coverage_caveats", []))
        consumed_counts.update(_verify_reconstruction(series, calendar, native, owned))
        del native
    _require(totals["native_wave_count"] == len(alias_map) == sum(method["wave_count"] for method in methods.values()), "Total native wave conservation failed")
    _require(len(phases) == sum(method["phase_count"] for method in methods.values()), "Total phase conservation failed")
    _require(len(candidates) == sum(method["candidate_count"] for method in methods.values()), "Total candidate conservation failed")
    _require(all(consumed_counts[name] == len(rows) for name, rows in tables.items()), "Compact rows were not reconstructed exactly once")
    return {
        "schema_version": "opportunity-verification-receipt.v1",
        "status": "verified",
        "manifest_sha256": manifest_trust["trusted_manifest_sha256"],
        "security_count": len(securities),
        "analyzed_security_count": len(analyzed),
        "calendar_count": len(dates),
        "table_counts": {name: len(rows) for name, rows in tables.items()},
        "native_wave_count": totals["native_wave_count"],
        "shared_wave_count": len(waves),
        "method_failures": totals["method_failures"],
        "nonconverged_methods": totals["nonconverged_methods"],
        "phase_cross_run_count": sum(bool(row.get("run_boundary_crossing")) for row in phases.values()),
        "coverage_caveat_count": totals["coverage_caveats"],
        "cohorts": dict(sorted(Counter(row["cohort"] for row in securities.values()).items())),
        "unresolved_parent_relations": sum(row["kind"] == "native_parent" and row["right_id"] is None for row in tables["relations"]),
        "native_dense_policy": "parsed_one_security_at_a_time_for_deterministic_compact_reconstruction_no_analysis_rerun",
        "native_semantic_reconstruction": "current V2 adapter; exact_pinned_js_run.preview.v2",
        "native_reconstruction_adapter_sha256": _hash(Path(__file__).resolve().parents[1] / "research_core/opportunity_history_catalog.py"),
        "parsed_native_count": totals["parsed_native_count"],
        "reconstructed_without_native_count": totals["reconstructed_without_native_count"],
        "reconstructed_table_counts": {name: consumed_counts[name] for name in tables},
        "exact_source_runs_verified_count": totals["exact_source_runs_verified_count"],
        "native_without_exact_run_claim_count": totals["native_without_exact_run_claim_count"],
        "source_run_policy": "exact_pinned_js_transform_required_for_all_eligible_native; excluded_no_native_uses_frozen_fallback",
        "native_source_semantics_policy": "deep_exact_original_pinned_typescript_waves_noise_and_launches_with_saved_segments; no_fitting",
        "producer_context_evidence": producer_context_evidence,
        **manifest_trust,
    }


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--params", type=Path)
    parser.add_argument("--expected-manifest-sha256")
    args = parser.parse_args()
    receipt = verify_catalog(args.manifest, params_path=args.params, expected_manifest_sha256=args.expected_manifest_sha256)
    encoded = json.dumps(receipt, ensure_ascii=True, sort_keys=True, allow_nan=False)
    if args.receipt:
        with args.receipt.open("x", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
    sys.stdout.write(encoded + "\n")


if __name__ == "__main__":
    main()
