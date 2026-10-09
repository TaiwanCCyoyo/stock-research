"""Immutable single-benchmark evidence packages and strict, read-only access."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import lzma
import math
import platform
import re
from collections import Counter
from datetime import date, datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from research_core.jobs import confined

LOGGER = logging.getLogger(__name__)
SCHEMA = "market-context-manifest.v2"
# Fixed rules identity, not a secret: sorted compact JSON plus newline from _encode.
RULES_V1_SHA256 = "94bf82f761be10915587b49ee9a21430b36c8c6c1d6bf7451c36e82bf9261547"  # pragma: allowlist secret
LAYERS = {"past_only": "past-only.json.gz", "retrospective": "retrospective.json.gz"}
REQUIRED = {
    "inputs/source-manifest.json.xz",
    "inputs/0050.json.gz",
    "inputs/calendar.json.gz",
    "definition.json",
    "summary.json",
    *LAYERS.values(),
    "producer/market_context.py.gz",
    "producer/market_context_artifact.py.gz",
    "producer/build_market_context.py.gz",
    "producer/mission.md.gz",
}


def _encode(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{label} must be a nonempty object")
    return value


def _decompress(raw: bytes, label: str) -> bytes:
    try:
        if label.endswith(".xz"):
            return lzma.decompress(raw, format=lzma.FORMAT_XZ)
        return gzip.decompress(raw) if label.endswith(".gz") else raw
    except (lzma.LZMAError, OSError, EOFError) as exc:
        raise ValueError(f"malformed compressed artifact: {label}") from exc


def _parse(raw: bytes, label: str) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value: str) -> float:
        if label == "0050.json.gz":
            return float(value)
        raise ValueError("nonfinite JSON value outside source series")

    try:
        return json.loads(_decompress(raw, label), object_pairs_hook=unique_object, parse_constant=constant)
    except (ValueError, OSError, EOFError) as exc:
        raise ValueError(f"malformed JSON artifact: {label}") from exc


def _descriptor(value: Any) -> dict[str, Any]:
    ref = _object(value, "descriptor")
    if not isinstance(ref.get("path"), str) or not isinstance(ref.get("sha256"), str) or not re.fullmatch("[0-9a-f]{64}", ref["sha256"]):
        raise ValueError("descriptor requires normalized path and lowercase SHA256")
    return ref


def _checked(root: Path, ref: Any) -> bytes:
    descriptor = _descriptor(ref)
    path = confined(root, descriptor["path"])
    raw = path.read_bytes()
    if not raw or _sha(raw) != descriptor["sha256"]:
        raise ValueError(f"artifact SHA256 mismatch or empty: {descriptor['path']}")
    return raw


def _inputs(source: Any, series: Any, calendar: Any) -> tuple[list[str], list[float | None]]:
    source = _object(source, "source manifest")
    series = _object(series, "series")
    calendar = _object(calendar, "calendar")
    ref = _descriptor(_object(source.get("series"), "series descriptors").get("0050"))
    calendar_ref = _descriptor(source.get("calendar"))
    if series.get("code") != "0050" or series.get("security_id") != "TW:0050" or ref.get("security_id") != "TW:0050":
        raise ValueError("benchmark code/security identity mismatch")
    if not isinstance(ref.get("series_id"), str) or not ref["series_id"] or series.get("series_id") != ref["series_id"]:
        raise ValueError("series identity mismatch")
    calendar_id = source.get("calendar_id")
    if not isinstance(calendar_id, str) or not calendar_id or series.get("calendar_id") != calendar_id or calendar.get("calendar_id") != calendar_id:
        raise ValueError("calendar identity mismatch")
    dates = calendar.get("dates")
    if not isinstance(dates, list) or not dates or any(not isinstance(day, str) for day in dates):
        raise ValueError("nonempty calendar dates required")
    try:
        valid = all(date.fromisoformat(day).isoformat() == day for day in dates)
    except ValueError as exc:
        raise ValueError("invalid calendar date") from exc
    if not valid or dates != sorted(set(dates)) or type(calendar_ref.get("count")) is not int or calendar_ref["count"] != len(dates):
        raise ValueError("calendar count/order/uniqueness mismatch")
    for field in ("raw", "adjusted"):
        if not isinstance(series.get(field), list) or len(series[field]) != len(dates):
            raise ValueError(f"series {field} length mismatch")
    flags = series.get("numeric_flags")
    if isinstance(flags, dict):
        if any(not isinstance(key, str) or not key.isdecimal() or str(int(key)) != key or int(key) >= len(dates) for key in flags):
            raise ValueError("malformed numeric flag index")
        flag_values = [flags.get(str(index), []) for index in range(len(dates))]
    elif isinstance(flags, list) and len(flags) == len(dates):
        flag_values = flags
    else:
        raise ValueError("numeric_flags must be an index dictionary or aligned list")
    if any(not isinstance(value, list) or any(not isinstance(flag, str) or not flag for flag in value) for value in flag_values):
        raise ValueError("malformed numeric flags")
    closes: list[float | None] = []
    for value, flagged in zip(series["adjusted"], flag_values, strict=True):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError("close must be numeric or null")
        closes.append(float(value) if value is not None and math.isfinite(value) and value > 0 and not flagged else None)
    return dates, closes


def _counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "states": dict(sorted(Counter(row["state"] for row in rows).items())),
        "events": dict(sorted(Counter(row["event"] for row in rows if row["event"] is not None).items())),
        "missing_reasons": dict(sorted(Counter(row["missing_reason"] for row in rows if row["missing_reason"] is not None).items())),
    }


def _identity(artifacts: list[dict[str, Any]]) -> str:
    # Outputs are included too: identical inputs/producer must never silently alias changed rows.
    return "sha256:" + _sha(_encode({ref["path"]: ref["sha256"] for ref in artifacts}))


def build_dataset(source_manifest: Path, expected_source_sha256: str, output: Path) -> dict[str, Any]:
    """Build once; never remove incomplete generations or overwrite existing paths."""
    from research_core.market_context import compute_context_rows, definition

    if output.exists():
        raise FileExistsError(f"refusing existing output: {output}")
    LOGGER.info("Checking benchmark source manifest %s", source_manifest)
    source_raw = _checked(source_manifest.parent, {"path": source_manifest.name, "sha256": expected_source_sha256})
    source = _object(_parse(source_raw, "source-manifest.json"), "source manifest")
    series_raw = _checked(source_manifest.parent, source["series"]["0050"])
    calendar_raw = _checked(source_manifest.parent, source["calendar"])
    dates, closes = _inputs(source, _parse(series_raw, "0050.json.gz"), _parse(calendar_raw, "calendar.json"))
    rules = definition()
    if rules.get("version") != "benchmark-context.rules.v1":
        raise ValueError("unsupported benchmark definition")
    rows = {layer: compute_context_rows(dates, closes, layer=layer) for layer in LAYERS}
    summary = {
        "scope": "whole_dataset_retrospective",
        "security_id": "TW:0050",
        "calendar_slots": len(dates),
        "usable_closes": sum(value is not None for value in closes),
        "start": dates[0],
        "end": dates[-1],
        "layers": {layer: _counts(value) for layer, value in rows.items()},
    }
    root = Path(__file__).resolve().parents[1]
    content = {
        "inputs/source-manifest.json.xz": lzma.compress(source_raw, format=lzma.FORMAT_XZ),
        "inputs/0050.json.gz": series_raw,
        "inputs/calendar.json.gz": gzip.compress(calendar_raw, mtime=0),
        "definition.json": _encode(rules),
        "summary.json": _encode(summary),
        **{LAYERS[layer]: gzip.compress(_encode(value), mtime=0) for layer, value in rows.items()},
        "producer/market_context.py.gz": gzip.compress((root / "research_core/market_context.py").read_bytes(), mtime=0),
        "producer/market_context_artifact.py.gz": gzip.compress(Path(__file__).read_bytes(), mtime=0),
        "producer/build_market_context.py.gz": gzip.compress((root / "scripts/build_market_context.py").read_bytes(), mtime=0),
        "producer/mission.md.gz": gzip.compress((root / "tasks/20261005-market-context-handoff/mission.md").read_bytes(), mtime=0),
    }
    output.mkdir(parents=True, exist_ok=False)
    artifacts = []
    for relative, raw in sorted(content.items()):
        path = confined(output, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        artifacts.append({"path": relative, "sha256": _sha(raw)})
    manifest = {
        "schema_version": SCHEMA,
        "dataset_id": _identity(artifacts),
        "artifacts": artifacts,
        "security_id": "TW:0050",
        "calendar_id": source["calendar_id"],
        "series_id": source["series"]["0050"]["series_id"],
        "source_manifest_sha256": expected_source_sha256,
        "definition_version": rules["version"],
        "summary": summary,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "source_price_basis": source.get("price_basis"),
        "historical_availability": "unknown",
        "source_manifest_scope": "provenance_only; referenced stock universe not included",
        "retained_byte_hashes": {
            relative: _sha(_decompress(raw, relative))
            for relative, raw in content.items()
            if relative.startswith("producer/") or relative in {"inputs/source-manifest.json.xz", "inputs/calendar.json.gz"}
        },
    }
    (output / "manifest.json").write_bytes(_encode(manifest))
    LOGGER.info("Saved benchmark context %s with %d calendar slots", manifest["dataset_id"], len(dates))
    return manifest


def _validate_rows(rows: Any, dates: list[str], closes: list[float | None], layer: str) -> None:
    if not isinstance(rows, list) or len(rows) != len(dates):
        raise ValueError("output row count mismatch")
    previous_state = "unknown"
    had_up = False
    had_consolidation_after_up = False
    required_fields = {
        "security_id",
        "asof_date",
        "layer",
        "state",
        "event",
        "information_cutoff",
        "missing_reason",
        "window_return",
        "window_range",
        "window_start",
        "window_end",
    }
    for index, row in enumerate(rows):
        row = _object(row, "context row")
        if set(row) != required_fields:
            raise ValueError("context row fields mismatch")
        if row.get("security_id") != "TW:0050" or row.get("layer") != layer or row.get("asof_date") != dates[index]:
            raise ValueError("row identity/date/layer mismatch")
        start, end = (index - 20, index) if layer == "past_only" else (index - 10, index + 10)
        cutoff = dates[end] if end < len(dates) else None
        if row["information_cutoff"] != cutoff or row["window_end"] != cutoff or row["window_start"] != (dates[start] if start >= 0 else None):
            raise ValueError("row information cutoff/window dates mismatch")
        if row.get("state") not in {"up", "down", "consolidation", "mixed", "unknown"} or row.get("event") not in {None, "launch", "resumption"}:
            raise ValueError("invalid state/event")
        reason = (
            "future_unavailable"
            if end >= len(dates)
            else "warmup"
            if start < 0
            else "unusable_observations"
            if any(value is None for value in closes[start : end + 1])
            else None
        )
        if reason is not None:
            if (
                row["state"] != "unknown"
                or row["missing_reason"] != reason
                or row["event"] is not None
                or row["window_return"] is not None
                or row["window_range"] is not None
            ):
                raise ValueError("invalid missing window semantics")
        else:
            values = [Fraction(str(value)) for value in closes[start : end + 1]]
            change, spread = values[-1] / values[0] - 1, max(values) / min(values) - 1
            state = (
                "up" if change >= Fraction(3, 100) else "down" if change <= Fraction(-3, 100) else "consolidation" if spread <= Fraction(8, 100) else "mixed"
            )
            if (
                row["state"] != state
                or row["missing_reason"] is not None
                or type(row["window_return"]) not in {float, int}
                or type(row["window_range"]) not in {float, int}
                or row["window_return"] != float(change)
                or row["window_range"] != float(spread)
            ):
                raise ValueError("invalid known window semantics")
        event = None
        state = row["state"]
        if state in {"unknown", "down"}:
            had_up = False
            had_consolidation_after_up = False
        elif state == "up":
            if previous_state not in {"unknown", "up"}:
                event = "resumption" if had_up and had_consolidation_after_up else "launch"
            had_up = True
        elif state == "consolidation" and had_up:
            had_consolidation_after_up = True
        if row["event"] != event:
            raise ValueError("invalid transition event semantics")
        previous_state = state


def _load(dataset: Path, *, recompute: bool = False) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    manifest = _object(_parse(confined(dataset, "manifest.json").read_bytes(), "manifest.json"), "manifest")
    if manifest.get("schema_version") != SCHEMA:
        raise ValueError("unsupported context manifest schema")
    refs = manifest.get("artifacts")
    if not isinstance(refs, list) or len(refs) != len(REQUIRED):
        raise ValueError("exact required artifact descriptors missing")
    artifacts = {_descriptor(ref)["path"]: _checked(dataset, ref) for ref in refs}
    if set(artifacts) != REQUIRED or len(artifacts) != len(refs) or manifest.get("dataset_id") != _identity(refs):
        raise ValueError("artifact inventory or dataset identity mismatch")
    retained = manifest.get("retained_byte_hashes")
    retained_paths = {
        relative for relative in artifacts if relative.startswith("producer/") or relative in {"inputs/source-manifest.json.xz", "inputs/calendar.json.gz"}
    }
    if not isinstance(retained, dict) or set(retained) != retained_paths:
        raise ValueError("retained byte identity inventory mismatch")
    for relative in retained_paths:
        original = _decompress(artifacts[relative], relative)
        if not original or _sha(original) != retained[relative]:
            raise ValueError("retained original byte SHA256 mismatch")
    source = _parse(artifacts["inputs/source-manifest.json.xz"], "source-manifest.json.xz")
    if manifest.get("source_manifest_sha256") != retained["inputs/source-manifest.json.xz"]:
        raise ValueError("source manifest identity mismatch")
    for key, relative in (("calendar", "inputs/calendar.json.gz"), ("series", "inputs/0050.json.gz")):
        ref = source[key] if key == "calendar" else source[key]["0050"]
        original = _decompress(artifacts[relative], relative) if key == "calendar" else artifacts[relative]
        if _descriptor(ref)["sha256"] != _sha(original):
            raise ValueError("saved source descriptor SHA256 mismatch")
        confined(dataset, ref["path"])
    dates, closes = _inputs(source, _parse(artifacts["inputs/0050.json.gz"], "0050.json.gz"), _parse(artifacts["inputs/calendar.json.gz"], "calendar.json.gz"))
    if (
        manifest.get("security_id") != "TW:0050"
        or manifest.get("calendar_id") != source["calendar_id"]
        or manifest.get("series_id") != source["series"]["0050"]["series_id"]
    ):
        raise ValueError("manifest input identity mismatch")
    rules = _object(_parse(artifacts["definition.json"], "definition.json"), "definition")
    if rules.get("version") != "benchmark-context.rules.v1" or manifest.get("definition_version") != rules["version"]:
        raise ValueError("definition identity mismatch")
    # Historical reads validate all rules/caveats without consulting mutable code.
    if _sha(_encode(rules)) != RULES_V1_SHA256:
        raise ValueError("unsupported definition content identity")
    rows = {layer: _parse(artifacts[relative], relative) for layer, relative in LAYERS.items()}
    for layer, values in rows.items():
        _validate_rows(values, dates, closes, layer)
    summary = _parse(artifacts["summary.json"], "summary.json")
    expected = {
        "scope": "whole_dataset_retrospective",
        "security_id": "TW:0050",
        "calendar_slots": len(dates),
        "usable_closes": sum(value is not None for value in closes),
        "start": dates[0],
        "end": dates[-1],
        "layers": {layer: _counts(value) for layer, value in rows.items()},
    }
    if summary != expected or manifest.get("summary") != expected:
        raise ValueError("summary counts/coverage mismatch")
    if (
        manifest.get("historical_availability") != "unknown"
        or manifest.get("source_price_basis") != source.get("price_basis")
        or not isinstance(manifest.get("runtime"), dict)
        or not manifest["runtime"]
    ):
        raise ValueError("source availability/basis/runtime metadata mismatch")
    if manifest.get("source_manifest_scope") != "provenance_only; referenced stock universe not included":
        raise ValueError("source manifest inclusion scope mismatch")
    if recompute:
        from research_core.market_context import compute_context_rows, definition

        producer = Path(__file__).with_name("market_context.py").read_bytes()
        retained_producer = _decompress(artifacts["producer/market_context.py.gz"], "producer/market_context.py.gz")
        # Git may convert LF/CRLF in a checkout; original byte proofs above stay exact.
        if producer.replace(b"\r\n", b"\n") != retained_producer.replace(b"\r\n", b"\n") or definition() != rules:
            raise ValueError("active producer drift; use matching retained producer for recomputation")
        for layer, values in rows.items():
            if compute_context_rows(dates, closes, layer=layer) != values:
                raise ValueError("recomputed rows differ")
    LOGGER.info("Verified benchmark context %s", manifest["dataset_id"])
    return manifest, rows


def read_dataset(dataset: Path, *, recompute: bool = False) -> dict[str, Any]:
    manifest, _ = _load(dataset, recompute=recompute)
    return {"dataset_id": manifest["dataset_id"], "verified": True, **manifest["summary"]}


def load_context_rows(dataset: Path, *, layer: str, date: str | None = None) -> list[dict[str, Any]]:
    if layer not in LAYERS:
        raise ValueError("unsupported layer")
    _, rows = _load(dataset)
    selected = rows[layer] if date is None else [row for row in rows[layer] if row["asof_date"] == date]
    if not selected:
        raise ValueError("date not available in context dataset")
    return selected
