"""Structural checks and exact original-source bridges for saved native results."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import sys
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from typing import Any

from scripts.opportunity_native_receipt_cache import load_receipt, save_receipt

PAIRS = {(method, scale) for method in ("segments", "filter") for scale in ("fine", "balanced", "coarse")}

NODE = Path(shutil.which("node") or "node")
SOURCE_GATE = Path(__file__).with_name("verify_opportunity_native_semantics.mjs")
_VERIFIED: OrderedDict[str, None] = OrderedDict()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _usable(series: dict[str, Any], index: int) -> bool:
    value = series["adjusted"][index]
    flags = series.get("numeric_flags", {}).get(str(index))
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0 and not flags


def _near(actual: Any, expected: float, label: str) -> None:
    valid = isinstance(actual, (int, float)) and not isinstance(actual, bool) and math.isfinite(actual)
    _require(valid and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-8), f"Numeric mismatch: {label}")


def _calendar_index(value: Any, date_count: int, field: str) -> None:
    _require(type(value) is int and 0 <= value < date_count, f"Invalid calendar index: {field}")


def validate_candidate_bounds(candidate: dict[str, Any], date_count: int) -> None:
    """Validate pinned Launch coordinates; ensuing and forward endpoints are inclusive."""
    for field in ("index", "rangeStart", "rangeEnd", "forwardEnd"):
        _calendar_index(candidate.get(field), date_count, f"candidate.{field}")
    _require(candidate["index"] == candidate["rangeStart"] <= candidate["rangeEnd"], "Candidate ensuing range order mismatch")
    _require(candidate["forwardEnd"] == candidate["rangeEnd"], "Candidate forward endpoint mismatch")


def validate_phase_bounds(row: dict[str, Any], date_count: int) -> None:
    """Pinned Segment endpoints are non-null inclusive calendar indices."""
    for field in ("start", "end"):
        _calendar_index(row.get(field), date_count, f"phase.{field}")
    _require(row["start"] <= row["end"], "Phase inclusive range order mismatch")


def expected_support_records(native: dict[str, Any]) -> list[dict[str, Any]]:
    """Rebuild pinned support fields in saved native launch order, including ties."""
    launches_by_scope: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in native["native"]:
        if record["status"] != "ok":
            continue
        launches = record["result"]["launches"]
        launches_by_scope[(record["method"], record["scale"])] = launches
    expected_records = []
    for record in native["native"]:
        if record["status"] != "ok":
            continue
        for target in record["result"]["launches"]:
            matches = []
            for scale in ("fine", "balanced", "coarse"):
                available = [
                    launch
                    for launch in launches_by_scope.get((record["method"], scale), [])
                    if launch["kind"] == target["kind"] and abs(launch["index"] - target["index"]) <= 20
                ]
                if available:
                    # min preserves input order for ties, matching the wrapper's strict '<'.
                    nearest = min(available, key=lambda launch: abs(launch["index"] - target["index"]))
                    matches.append({"method": record["method"], "scale": scale, "candidate_id": nearest["id"], "index": nearest["index"]})
            _require(bool(matches), "Native support lacks self match")
            expected_records.append({
                "method": record["method"],
                "scale": record["scale"],
                "candidate_id": target["id"],
                "index": target["index"],
                "kind": target["kind"],
                "matched_ids": matches,
                "support": len(matches),
                "rangeStart": min(match["index"] for match in matches),
                "rangeEnd": max(match["index"] for match in matches),
            })
    return expected_records


def validate_native_support_order(native: dict[str, Any]) -> None:
    _require(native["support_records"] == expected_support_records(native), "Native support nearest/original-order mismatch")


def validate_support_bounds(row: dict[str, Any], date_count: int) -> None:
    """Support ranges enclose matched event points, with inclusive endpoints."""
    for field in ("index", "rangeStart", "rangeEnd"):
        _calendar_index(row.get(field), date_count, f"support.{field}")
    _require(row["rangeStart"] <= row["index"] <= row["rangeEnd"], "Support range order mismatch")
    for match in row["matched_ids"]:
        _calendar_index(match.get("index"), date_count, "support.matched_ids.index")


def validate_wave_semantics(wave: dict[str, Any], series: dict[str, Any], date_count: int, source_runs: list[int | None]) -> None:
    """Bind pinned wave coordinates and percent gain to usable adjusted prices."""
    for field in ("start", "peak", "observedThrough"):
        _calendar_index(wave.get(field), date_count, f"wave.{field}")
    start, peak, through = wave["start"], wave["peak"], wave["observedThrough"]
    _require("end" in wave, "Missing native wave endpoint")
    if wave["end"] is not None:
        _calendar_index(wave["end"], date_count, "wave.end")
        _require(wave["end"] == through, "Closed wave endpoint/observedThrough mismatch")
    _require(0 <= start <= peak <= through < date_count, "Wave range outside calendar")
    _require(isinstance(source_runs, list) and len(source_runs) == date_count, "Wave semantics requires exact source runs")
    run_id = source_runs[start]
    same_run = (
        run_id is not None and type(run_id) is int and run_id >= 0 and all(type(value) is int and value == run_id for value in source_runs[start : through + 1])
    )
    _require(same_run, "Wave crosses exact source run boundary or unusable point")
    _require(_usable(series, start) and _usable(series, peak), "Invalid quote claimed as wave start/peak")
    usable = [index for index in range(start, through + 1) if _usable(series, index)]
    maximum = max(series["adjusted"][index] for index in usable)
    _near(series["adjusted"][peak], maximum, "wave peak")
    _near(wave.get("gain"), (maximum / series["adjusted"][start] - 1) * 100, "wave gain percent")


def _result_rows(result: dict[str, Any], field: str, required: bool) -> list[dict[str, Any]]:
    rows = result.get(field) if required else result.get(field, [])
    _require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), f"Invalid native result list: {field}")
    assert isinstance(rows, list)
    return rows


def _unique_native_ids(rows: list[dict[str, Any]], field: str) -> None:
    identities = [row.get("id") for row in rows]
    _require(all(isinstance(identity, str) and bool(identity) for identity in identities), f"Invalid native {field} ID")
    _require(len(set(identities)) == len(identities), f"Duplicate native {field} ID within method/scale")


def _source_fingerprint() -> str:
    root = SOURCE_GATE.parent.parent
    snapshot = root / "tasks/20261004-sector-wave-full-history-preview/method-snapshot"
    digest = hashlib.sha256()
    for path in (SOURCE_GATE, SOURCE_GATE.with_name("opportunity_history_methods.mjs"), snapshot / "analysis.ts", snapshot / "types.ts"):
        digest.update(path.read_bytes())
    return digest.hexdigest()


@lru_cache(maxsize=1)
def _runtime_fingerprint() -> str:
    """Bind reusable receipts to the actual Node executable and Python runtime."""
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node unavailable for exact original source semantic validation")
    digest = hashlib.sha256(sys.version.encode())
    with Path(node).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verification_fingerprint() -> str:
    digest = hashlib.sha256((_source_fingerprint() + _runtime_fingerprint()).encode())
    digest.update(Path(__file__).read_bytes())
    digest.update(Path(__file__).with_name("opportunity_native_receipt_cache.py").read_bytes())
    return digest.hexdigest()


def _call_source(encoded: str, mode: str) -> str:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node unavailable for exact original source semantic validation: cannot locate node on PATH")
    try:
        completed = subprocess.run([node, str(SOURCE_GATE), mode], input=encoded, check=True, capture_output=True, text=True, encoding="utf-8")
    except subprocess.CalledProcessError as error:
        raise ValueError(f"Exact original source semantic validation failed: {error.stderr or error}") from error
    except OSError as error:
        raise RuntimeError(f"Node unavailable for exact original source semantic validation ({node}): {error}") from error
    return completed.stdout


@lru_cache(maxsize=128)
def _derived_json(encoded: str, _fingerprint: str) -> str:
    return _call_source(encoded, "--derive")


def _derive_source(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))
    # Parsing cached text yields fresh containers; fixture mutation cannot contaminate proofs.
    result = json.loads(_derived_json(encoded, _source_fingerprint()))
    _require(isinstance(result, dict) and result.get("schema") == "opportunity-native-source-expectations.v1", "Invalid original source derivation receipt")
    return result


def expected_noise(series: dict[str, Any], exact_runs: list[int | None]) -> float:
    """Derive fixture noise from preserved JavaScript floating-point operations."""
    return _derive_source({"series": series, "exact_runs": exact_runs})["noise"]


def expected_baseline_waves(series: dict[str, Any], exact_runs: list[int | None], method_scale: str) -> list[dict[str, Any]]:
    """Derive fixture waves directly from the hash-guarded original source."""
    _require(method_scale in ("fine", "balanced", "coarse"), "Unknown native wave method scale")
    return _derive_source({"series": series, "exact_runs": exact_runs})["baselines"][method_scale]


def expected_launches(series: dict[str, Any], segments: list[dict[str, Any]], noise: float) -> list[dict[str, Any]]:
    """Derive fixture launches from saved segments without any method fitting."""
    return _derive_source({"series": series, "segments": segments, "launch_noise": noise})["launches"]


def _validate_pinned_js(native: dict[str, Any], series: dict[str, Any], calendar: dict[str, Any]) -> None:
    encoded = json.dumps({"native": native, "series": series, "calendar": calendar}, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    key = hashlib.sha256((encoded + _verification_fingerprint()).encode("utf-8")).hexdigest()
    if key in _VERIFIED:
        _VERIFIED.move_to_end(key)
        return
    success_count = sum(record["status"] == "ok" for record in native["native"])
    wave_count = sum(len(record["result"]["waves"]) for record in native["native"] if record["status"] == "ok")
    launch_count = sum(len(record["result"]["launches"]) for record in native["native"] if record["status"] == "ok")

    def counts_match(receipt: Any) -> bool:
        return (
            isinstance(receipt, dict)
            and receipt.get("schema") == "opportunity-native-source-semantics.v1"
            and receipt.get("status") == "verified"
            and type(receipt.get("method_count")) is int
            and receipt["method_count"] == success_count
            and type(receipt.get("wave_count")) is int
            and receipt["wave_count"] == wave_count
            and type(receipt.get("launch_count")) is int
            and receipt["launch_count"] == launch_count
        )

    receipt = load_receipt(key)
    if not counts_match(receipt):
        try:
            receipt = json.loads(_call_source(encoded, "--verify"))
        except (json.JSONDecodeError, TypeError) as error:
            raise ValueError("Invalid exact original source semantic validation response") from error
        if isinstance(receipt, dict) and receipt.get("status") == "partial":
            raise ValueError(
                f"Partial native source semantics: {receipt.get('failed_method_count')} failed method scopes; cannot verify complete native evidence"
            )
        _require(counts_match(receipt), "Invalid exact original source semantic validation receipt")
        save_receipt(key, receipt)
    _VERIFIED[key] = None
    if len(_VERIFIED) > 4096:
        _VERIFIED.popitem(last=False)


def validate_native_semantics(native: dict[str, Any], series: dict[str, Any], calendar: dict[str, Any]) -> None:
    """Check structure then original pinned JS pure semantics; never fit or mutate sources."""
    dates = calendar.get("dates")
    _require(isinstance(dates, list), "Invalid native semantic calendar")
    assert isinstance(dates, list)
    date_count = len(dates)
    _require(isinstance(series.get("adjusted"), list) and len(series["adjusted"]) == date_count, "Native semantic series/calendar length mismatch")
    runs = native.get("source_run_indices")
    valid_runs = isinstance(runs, list) and len(runs) == date_count and all(value is None or (type(value) is int and value >= 0) for value in runs)
    _require(valid_runs, "Native semantics requires valid exact source_run_indices")
    assert isinstance(runs, list)
    records = native.get("native")
    _require(isinstance(records, list) and len(records) == 6 and all(isinstance(record, dict) for record in records), "Invalid native six method records")
    assert isinstance(records, list)
    scopes = [(record.get("method"), record.get("scale")) for record in records]
    _require(all(isinstance(method, str) and isinstance(scale, str) for method, scale in scopes), "Invalid native method/scale shape")
    _require(all(scope in PAIRS for scope in scopes) and len(set(scopes)) == 6, "Native must contain six unique known method/scale records")
    for record in records:
        status = record.get("status")
        _require(status in ("ok", "error"), "Invalid native method status")
        result = record.get("result")
        _require(result is None or isinstance(result, dict), "Invalid native method result shape")
        if status == "error":
            _require(bool(record.get("error")), "Native method error lacks error evidence")
            if result is not None:
                _require(all(not _result_rows(result, field, False) for field in ("waves", "segments", "launches")), "Error native method carries success rows")
            continue
        _require(isinstance(result, dict), "Successful native method requires result object")
        assert isinstance(result, dict)
        waves = _result_rows(result, "waves", True)
        phases = _result_rows(result, "segments", True)
        candidates = _result_rows(result, "launches", True)
        _unique_native_ids(waves, "wave")
        _unique_native_ids(candidates, "candidate")
        for wave in waves:
            validate_wave_semantics(wave, series, date_count, runs)
        for phase in phases:
            validate_phase_bounds(phase, date_count)
            slope = phase.get("slope")
            _require(isinstance(slope, (int, float)) and not isinstance(slope, bool) and math.isfinite(slope), "Invalid native phase slope")
        for candidate in candidates:
            validate_candidate_bounds(candidate, date_count)
            _require(candidate.get("kind") in ("reversal", "breakout", "acceleration"), "Invalid native candidate kind")
        diagnostics = result.get("diagnostics")
        _require(isinstance(diagnostics, dict), "Native source diagnostics required")
    support = native.get("support_records")
    _require(isinstance(support, list) and all(isinstance(row, dict) for row in support), "Invalid native support records")
    assert isinstance(support, list)
    for row in support:
        matches = row.get("matched_ids")
        _require(isinstance(matches, list) and all(isinstance(match, dict) for match in matches), "Invalid native support matched IDs")
        validate_support_bounds(row, date_count)
    validate_native_support_order(native)
    _validate_pinned_js(native, series, calendar)
