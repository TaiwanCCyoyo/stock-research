"""Query producer intervals with the exact aligned series referenced by manifest."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date as calendar_date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research_core.opportunity_history_catalog import RULE, SELECTOR, _run_spans, project_query_tables, query_security, source_run_indices
from scripts.opportunity_history_source_runs import expected_source_runs

GAIN_POLICY = "exact_pinned_js_run.preview.v2"
V2_ADAPTERS = {
    "aff9b1c452509c662a9738f9209d94133c7a2d7b38d9d479861746166872c5ab",
    "8f5d66b616c323416156ccd8003c51ebdeb8a02af5c27fba149e98b7b46abcbd",
    # Shared full/compact reconstruction; existing frozen V2 receipts stay supported.
    "9404d299d52f403e15eba2824e3cdd1e9e6213589d1231629c29363bf933ad66",
}
V1_ADAPTER = "ac3876886714c3b38fba8cd97106ef4300c41c98d1b20861b17c769358de0756"
REGISTERED_MANIFEST_SHA256 = "c7848ae7ad177770babfda774e07923f995ba2cb3fa4a83d77d02f77a0dfe140"


def validate_manifest_trust(manifest_bytes: bytes, expected_manifest_sha256: str | None = None) -> dict[str, str]:
    """Bind raw bytes to a publication or caller-supplied external trust anchor."""
    expected = REGISTERED_MANIFEST_SHA256
    policy = "registered_publication"
    if expected_manifest_sha256 is not None:
        if not isinstance(expected_manifest_sha256, str) or re.fullmatch(r"[0-9a-fA-F]{64}", expected_manifest_sha256) is None:
            raise ValueError("Invalid expected_manifest_sha256: require 64 hexadecimal characters")
        expected = expected_manifest_sha256.lower()
        policy = "caller_pinned"
    actual = hashlib.sha256(manifest_bytes).hexdigest()
    if actual != expected:
        raise ValueError("Manifest trust mismatch: require the registered publication or an explicit external expected_manifest_sha256")
    return {"trusted_manifest_sha256": actual, "manifest_trust_policy": policy}


def read_reference(root: Path, reference: dict[str, Any] | str) -> Any:
    return _read_reference_with_sha(root, reference)[0]


def _read_reference_with_sha(root: Path, reference: dict[str, Any] | str) -> tuple[Any, str]:
    path = root / (reference if isinstance(reference, str) else reference["path"])
    payload = path.read_bytes()
    actual_sha = hashlib.sha256(payload).hexdigest()
    if isinstance(reference, dict) and reference.get("sha256") and actual_sha != reference["sha256"]:
        raise ValueError(f"artifact hash mismatch: {path}")
    return json.loads(gzip.decompress(payload) if path.suffix == ".gz" else payload), actual_sha


def validate_manifest_identity(manifest: object) -> dict[str, Any]:
    """Validate the fixed CLI adapter registry before loading dependencies."""
    if not isinstance(manifest, dict):
        raise ValueError("Opportunity catalog manifest must be a JSON object")
    if manifest.get("schema_version") != "opportunity-local-history-preview.v1":
        raise ValueError("Unsupported or missing opportunity catalog schema_version")
    adapter = manifest.get("adapter_revision")
    producer = manifest.get("producer_identity")
    archived_source = adapter is None and isinstance(producer, dict) and producer.get("adapter_sha256") == V1_ADAPTER
    compact = manifest.get("compact_export_identity", {})
    if not isinstance(compact, dict):
        raise ValueError("Invalid compact_export_identity")
    if "adapter_sha256" in compact and compact["adapter_sha256"] != manifest.get("adapter_revision"):
        raise ValueError("compact_export_identity adapter disagrees with top-level adapter_revision")
    if adapter == V1_ADAPTER or archived_source:
        raise ValueError("Current CLI supports V2; archived V1 requires the preserved producer at 37cb418 for exact queries")
    if not isinstance(adapter, str) or adapter not in V2_ADAPTERS:
        raise ValueError("Unsupported, unknown or missing adapter revision for current V2 CLI")
    declared = manifest.get("gain_policy")
    if "gain_policy" in manifest and declared != GAIN_POLICY:
        raise ValueError("Unsupported or conflicting gain policy for current V2 CLI")
    for name, expected in (("rule", RULE), ("selector", SELECTOR)):
        if manifest.get(name) != expected:
            raise ValueError(f"Unsupported, conflicting or missing {name} for current V2 CLI")
    return {
        "schema": manifest["schema_version"],
        "task": manifest.get("task"),
        "catalog_revision": manifest.get("catalog_revision"),
        "declared_gain_policy": declared,
        "effective_gain_policy": GAIN_POLICY,
        "policy_source": "manifest" if declared is not None else "adapter_registry",
        "adapter_revision": adapter,
        "rule": manifest.get("rule"),
        "selector": manifest.get("selector"),
    }


def _v2_dependency(reference: object, name: str) -> dict[str, Any]:
    """Require an expected byte identity before opening any V2 dependency."""
    if not isinstance(reference, dict):
        raise ValueError(f"V2 dependency {name} requires a descriptor with path and sha256")
    path = reference.get("path")
    expected_sha = reference.get("sha256")
    if not isinstance(path, str) or not path.strip():
        raise ValueError(f"V2 dependency {name} requires a nonempty path")
    if not isinstance(expected_sha, str) or re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha) is None:
        raise ValueError(f"V2 dependency {name} requires a valid 64-hex sha256")
    return reference | {"sha256": expected_sha.lower()}


def calendar_content_id(calendar: dict[str, Any]) -> str:
    """Compute the exporter's identity over all calendar fields except its ID."""
    content = {key: value for key, value in calendar.items() if key != "calendar_id"}
    raw = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def validate_calendar_identity(calendar: dict[str, Any]) -> None:
    """Verify content identity and the ordered, unique quote-date axis."""
    if calendar.get("calendar_id") != calendar_content_id(calendar):
        raise ValueError("Query calendar content identity does not match calendar_id")
    dates = calendar.get("dates")
    if not isinstance(dates, list) or any(not isinstance(day, str) for day in dates):
        raise ValueError("Query calendar dates must be an array of strings")
    for day in dates:
        try:
            parsed = calendar_date.fromisoformat(day)
        except ValueError as error:
            raise ValueError("Query calendar dates must be real Gregorian YYYY-MM-DD dates") from error
        if parsed.isoformat() != day:
            raise ValueError("Query calendar dates must be real Gregorian YYYY-MM-DD dates")
    if dates != sorted(set(dates)):
        raise ValueError("Query calendar dates must be sorted and unique")


def series_content_id(series: dict[str, Any]) -> str:
    """Compute the exporter's identity over all series fields except its ID."""
    content = {key: value for key, value in series.items() if key != "series_id"}
    raw = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def validate_series_identity(series: dict[str, Any]) -> None:
    """Require the series identity to describe its complete recorded content."""
    if series.get("series_id") != series_content_id(series):
        raise ValueError("Query series content identity does not match series_id")


def _validate_query_inputs(manifest: dict[str, Any], code: str, series_ref: dict[str, Any], series: object, calendar: object) -> None:
    """Bind checked bytes to the requested security and shared quote calendar."""
    if not isinstance(series, dict) or not isinstance(calendar, dict):
        raise ValueError("Query series and calendar must be JSON objects")
    validate_calendar_identity(calendar)
    validate_series_identity(series)
    if series.get("code") != code:
        raise ValueError("Query series code does not match requested code")
    for name in ("series_id", "security_id"):
        expected = series_ref.get(name)
        if not isinstance(expected, str) or not expected.strip() or series.get(name) != expected:
            raise ValueError(f"Query series {name} does not match its nonempty descriptor identity")
    calendar_id = manifest.get("calendar_id")
    if not isinstance(calendar_id, str) or not calendar_id.strip():
        raise ValueError("Query manifest requires a nonempty calendar_id")
    if calendar.get("calendar_id") != calendar_id or series.get("calendar_id") != calendar_id:
        raise ValueError("Query calendar identity does not match manifest and series")
    dates = calendar.get("dates")
    if not isinstance(dates, list):
        raise ValueError("Query calendar dates must be an array")
    calendar_ref = manifest["calendar"]
    if "count" in calendar_ref and (type(calendar_ref["count"]) is not int or calendar_ref["count"] != len(dates)):
        raise ValueError("Query calendar descriptor count does not match dates")
    for name in ("raw", "adjusted"):
        values = series.get(name)
        if not isinstance(values, list) or len(values) != len(dates):
            raise ValueError(f"Query series {name} length does not match calendar dates")


def validate_query_tables(
    tables: dict[str, list[dict[str, Any]]],
    series: dict[str, Any],
    expected_runs: list[int | None] | None = None,
    *,
    native: dict[str, Any] | None = None,
    calendar: dict[str, Any] | None = None,
) -> None:
    """Reconstruct selected rows from caller-verified native/receipt bytes.

    This pure gate checks identities, exact runs and complete row multiplicity.
    Callers must verify native/receipt hashes and receipt context beforehand;
    query_manifest performs those checks for its selected dependencies.
    """
    for table_name in ("securities", "representative_intervals"):
        rows = tables[table_name]
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("security_id"), str) or not row["security_id"].strip():
                raise ValueError("Query compact rows require a nonempty security_id")
    selected = [row for row in tables["securities"] if row.get("security_id") == series["security_id"]]
    if len(selected) != 1:
        raise ValueError("Query requires exactly one selected security row")
    intervals = [row for row in tables["representative_intervals"] if row.get("security_id") == series["security_id"]]
    eligible = series.get("instrument_role") == "stock" and series.get("cohort") in ("metadata_stock", "innovation_board")
    if eligible:
        if expected_runs is None:
            raise ValueError("Query eligible security requires exact JavaScript source runs")
        if native is None:
            raise ValueError("Query eligible security requires verified native evidence")
        if "source_run_indices" not in native or native["source_run_indices"] != expected_runs:
            raise ValueError("Query native exact source runs do not match pinned JavaScript")
        runs = expected_runs
    else:
        runs = source_run_indices(series)
        if intervals:
            raise ValueError("Query excluded security cannot have representative intervals")
    if len(runs) != len(series["adjusted"]) or any(value is not None and (type(value) is not int or value < 0) for value in runs):
        raise ValueError("Query source run indices are invalid")
    security = selected[0]
    if type(security.get("stock_opportunity_eligible")) is not bool or security["stock_opportunity_eligible"] != eligible:
        raise ValueError("Query compact security eligibility does not match checked series role/cohort")
    spans = security.get("continuity_runs")
    if (
        not isinstance(spans, list)
        or any(
            not isinstance(span, dict) or set(span) != {"run_id", "start", "end"} or any(type(value) is not int for value in span.values()) for span in spans
        )
        or spans != _run_spans(runs)
    ):
        raise ValueError("Query compact security continuity_runs do not match verified source runs")
    for row in selected:
        for name in ("security_id", "series_id", "calendar_id"):
            if row.get(name) != series[name]:
                raise ValueError(f"Query compact row {name} does not match checked series identity")
    for row in intervals:
        if row.get("series_id") != series["series_id"]:
            raise ValueError("Query interval series_id does not match checked series identity")
        if "calendar_id" in row and row["calendar_id"] != series["calendar_id"]:
            raise ValueError("Query interval calendar_id does not match checked series identity")
        if any(type(row.get(name)) is not int for name in ("start_index", "end_exclusive_index", "gain_base_index")):
            raise ValueError("Query interval indices must be integers")
        if not 0 <= row["gain_base_index"] <= row["start_index"] < row["end_exclusive_index"] <= len(series["adjusted"]):
            raise ValueError("Query interval bounds do not fit checked series")
        if not isinstance(row.get("wave_id"), str) or not row["wave_id"].strip():
            raise ValueError("Query interval requires a nonempty wave_id")
    ordered = sorted(intervals, key=lambda row: row["start_index"])
    if any(left["end_exclusive_index"] > right["start_index"] for left, right in zip(ordered, ordered[1:])):
        raise ValueError("Query selected security intervals must not overlap")
    if calendar is None:
        raise ValueError("Query row reconstruction requires checked calendar")
    if eligible and native is not None:
        from scripts.opportunity_history_native_validation import validate_native_semantics

        validate_native_semantics(native, series, calendar)
    if native is None:
        native = {**{key: series[key] for key in ("security_id", "series_id", "calendar_id")}, "native": [], "support_records": []}
    rebuilt = project_query_tables(series, calendar, native)
    rebuilt["securities"][0].update({
        "stock_opportunity_eligible": eligible,
        "method_eligibility_reason": "stock_cohort" if eligible else "excluded_role_or_identity",
        "coverage": series.get("coverage", {}),
    })
    for name, actual in (("securities", selected), ("representative_intervals", intervals)):

        def rows_counter(rows: list[dict[str, Any]]) -> Counter[str]:
            return Counter(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) for row in rows)

        if rows_counter(actual) != rows_counter(rebuilt[name]):
            raise ValueError(f"Query native reconstruction mismatch: {name}")


def _selected_native(
    manifest: dict[str, Any],
    root: Path,
    code: str,
    series: dict[str, Any],
    series_sha: str,
    calendar_sha: str,
) -> tuple[dict[str, Any], str, str]:
    # build_opportunity_history imports this module for input identities.
    from scripts.build_opportunity_history import validate_native

    reference = _v2_dependency(manifest["native"][code], f"native[{code}]")
    receipt_ref = _v2_dependency(reference.get("receipt"), f"native[{code}].receipt")
    if type(reference.get("count")) is not int or reference["count"] != 6:
        raise ValueError("Query native descriptor requires six method records")
    native, native_sha = _read_reference_with_sha(root, reference)
    receipt, receipt_sha = _read_reference_with_sha(root, receipt_ref)
    context = manifest.get("producer_identity")
    if not isinstance(native, dict) or not isinstance(receipt, dict) or not isinstance(context, dict) or not context:
        raise ValueError("Query native/receipt/producer context must be objects")
    if (
        receipt.get("schema_version") != "opportunity-native-receipt.v1"
        or receipt.get("security_id") != series["security_id"]
        or receipt.get("series_id") != series["series_id"]
        or receipt.get("sha256") != native_sha
        or receipt.get("context") != context
    ):
        raise ValueError("Query native receipt identity/hash/context mismatch")
    validate_native(native, series, {"series_sha256": series_sha, "calendar_sha256": calendar_sha}, manifest["code_identity"])
    return native, native_sha, receipt_sha


def query_manifest(manifest_path: Path, code: str, date: str, *, expected_manifest_sha256: str | None = None) -> dict[str, Any]:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    evidence = validate_manifest_identity(manifest)
    evidence |= validate_manifest_trust(manifest_bytes, expected_manifest_sha256)
    root = manifest_path.parent
    calendar_ref = _v2_dependency(manifest["calendar"], "calendar")
    series_ref = _v2_dependency(manifest["series"][code], f"series[{code}]")
    table_refs = {}
    for name in ("securities", "representative_intervals"):
        references = manifest["tables"][name]
        references = references if isinstance(references, list) else [references]
        table_refs[name] = [_v2_dependency(ref, f"tables[{name}][{index}]") for index, ref in enumerate(references)]
    calendar, calendar_sha = _read_reference_with_sha(root, calendar_ref)
    series, series_sha = _read_reference_with_sha(root, series_ref)
    _validate_query_inputs(manifest, code, series_ref, series, calendar)
    tables = {name: [row for ref in references for row in read_reference(root, ref)["rows"]] for name, references in table_refs.items()}
    eligible = series.get("instrument_role") == "stock" and series.get("cohort") in ("metadata_stock", "innovation_board")
    runs = expected_source_runs(manifest_path, {code})[code] if eligible else None
    native, native_sha, receipt_sha = _selected_native(manifest, root, code, series, series_sha, calendar_sha) if eligible else (None, None, None)
    validate_query_tables(tables, series, runs, native=native, calendar=calendar)
    result = query_security(tables, series, calendar, date)
    result["evidence"] = evidence | {
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "series_id": series["series_id"],
        "series_sha256": series_sha,
        "calendar_sha256": calendar_sha,
        "native_sha256": native_sha,
        "native_receipt_sha256": receipt_sha,
        "reconstruction_policy": "selected_native_full_rows.preview.v1" if eligible else "excluded_no_native_full_rows.preview.v1",
    }
    return result


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--code", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--expected-manifest-sha256")
    args = parser.parse_args(argv)
    try:
        result = query_manifest(args.manifest, args.code, args.date, expected_manifest_sha256=args.expected_manifest_sha256)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        parser.exit(2, f"opportunity query failed: {error}\n")
    sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
