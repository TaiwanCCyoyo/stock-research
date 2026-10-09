"""Lossless compact native-event adapter and fixed retrospective selector."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import Counter
from typing import Any

LOGGER = logging.getLogger(__name__)
RULE = "wave-lab-exploratory.v1"
SELECTOR = "wave-start-representative.preview.v1"
UNKNOWN = {"first_knowable_at": None, "first_knowable_reason": "not_recorded", "detected_at": None, "detected_reason": "not_recorded"}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _id(*parts: Any) -> str:
    encoded = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()[:32]


def _dates(calendar: list[str] | dict[str, Any]) -> list[str]:
    return calendar if isinstance(calendar, list) else calendar["dates"]


def _flags(series: dict[str, Any], index: int) -> Any:
    flags = series.get("numeric_flags", {})
    return flags.get(str(index), flags.get(index)) if isinstance(flags, dict) else flags[index]


def _barrier_indices(series: dict[str, Any], dates: list[str]) -> set[int]:
    barriers = set()
    for barrier in series.get("action_barriers", []):
        index = barrier.get("index", barrier.get("calendar_index"))
        if index is None and barrier.get("date", barrier.get("ex_date")):
            day = barrier.get("date", barrier.get("ex_date"))
            index = next((i for i, date in enumerate(dates) if date >= day and _finite(series["raw"][i])), None)
        if index is not None:
            barriers.add(index)
    return barriers


def source_run_indices(series: dict[str, Any]) -> list[int | None]:
    """Mirror source run breaks: drop null/flagged points, retain jump sides."""
    runs: list[int | None] = []
    previous: float | None = None
    run = -1
    for index, value in enumerate(series["adjusted"]):
        if not _finite(value) or value <= 0 or _flags(series, index):
            runs.append(None)
            previous = None
            continue
        if previous is None or abs(math.log(value) - math.log(previous)) > math.log(1.35):
            run += 1
        runs.append(run)
        previous = value
    return runs


def _native_runs(native: dict[str, Any], series: dict[str, Any]) -> list[int | None]:
    runs = native.get("source_run_indices")
    if runs is None:
        return source_run_indices(series)
    if len(runs) != len(series["adjusted"]) or any(
        value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0) for value in runs
    ):
        raise ValueError("Invalid native source run indices")
    return runs


def _run_spans(runs: list[int | None]) -> list[dict[str, int]]:
    spans: list[dict[str, int]] = []
    for index, run in enumerate(runs):
        if run is None:
            continue
        if spans and spans[-1]["run_id"] == run and spans[-1]["end"] == index - 1:
            spans[-1]["end"] = index
        else:
            spans.append({"run_id": run, "start": index, "end": index})
    return spans


def gain_at(series: dict[str, Any], calendar: list[str] | dict[str, Any], base: int, index: int) -> tuple[float | None, str | None]:
    """Return a fraction only across usable, unbroken source continuity."""
    dates = _dates(calendar)
    prices = series["adjusted"]
    if base < 0 or index < base or index >= len(prices):
        return None, "outside_series"
    if not _finite(prices[base]) or not _finite(prices[index]) or prices[base] <= 0 or prices[index] <= 0:
        return None, "missing_or_invalid_endpoint"
    barriers = _barrier_indices(series, dates)
    runs = series.get("source_run_indices")
    for i in range(base, index + 1):
        if _flags(series, i):
            return None, "numeric_blocker"
        if not _finite(prices[i]) or prices[i] <= 0:
            return None, "missing_continuity"
        if i > base and i in barriers:
            return None, "action_barrier"
        if runs is None and i > base and abs(math.log(prices[i]) - math.log(prices[i - 1])) > math.log(1.35):
            return None, "continuity_jump"
    if runs is not None and runs[base] != runs[index]:
        return None, "continuity_jump"
    return prices[index] / prices[base] - 1, None


def build_representative_intervals(
    waves: list[dict[str, Any]], calendar: list[str] | dict[str, Any], candidates: list[dict[str, Any]] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select balanced segments aliases; confirmed ends are exclusive."""
    dates = _dates(calendar)
    eligible = [w for w in waves if w["method_scale"] == "balanced" and any(a["method"] == "segments" for a in w["aliases"])]
    eligible.sort(key=lambda w: (w["scale"] != "large", w["start"], w["id"]))
    references: dict[str, str | None] = {}
    for eligible_wave in eligible:
        linked = [c for c in candidates or [] if c["method"] == "segments" and c["method_scale"] == "balanced" and eligible_wave["id"] in c.get("wave_ids", [])]
        references[eligible_wave["id"]] = min(linked, key=lambda c: (c["index"], c["id"]))["id"] if linked else None
    selected: list[dict[str, Any] | None] = []
    for i in range(len(dates)):
        selected.append(next((w for w in eligible if w["start"] <= i and (i < w["end"] if w["end"] is not None else i <= w["observedThrough"])), None))
    intervals: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for i, wave in enumerate(selected):
        if (wave["id"] if wave else None) != (previous["id"] if previous else None):
            reason = "first_active" if previous is None else "no_active_wave" if wave is None else "representative_switch"
            transitions.append({
                "index": i,
                "date": dates[i],
                "old_wave_id": previous["id"] if previous else None,
                "new_wave_id": wave["id"] if wave else None,
                "old_gain_base_index": previous["start"] if previous else None,
                "new_gain_base_index": wave["start"] if wave else None,
                "reason": reason,
            })
        if wave:
            if intervals and intervals[-1]["wave_id"] == wave["id"] and intervals[-1]["end_exclusive_index"] == i:
                intervals[-1]["end_exclusive_index"] = i + 1
            else:
                intervals.append({
                    "wave_id": wave["id"],
                    "start_index": i,
                    "end_exclusive_index": i + 1,
                    "gain_base_index": wave["start"],
                    "earliest_candidate_id": references[wave["id"]],
                    "manual_selection": None,
                    "manual_selection_status": "not_selected",
                    "selector": SELECTOR,
                })
        previous = wave
    for row in intervals:
        row["start_date"] = dates[row["start_index"]]
        end = row["end_exclusive_index"]
        row["end_exclusive_date"] = dates[end] if end < len(dates) else None
        row["cutoff_date"] = dates[-1] if end == len(dates) else None
    return intervals, transitions


def _relation(left: dict[str, Any], right: dict[str, Any], left_span: tuple[int, int], right_span: tuple[int, int], domain: str) -> dict[str, Any] | None:
    a, b = left_span
    c, d = right_span
    if max(a, c) > min(b, d):
        return None
    kind = "equal" if (a, b) == (c, d) else "contains" if a <= c and d <= b else "contained_by" if c <= a and b <= d else "crossing"
    return {
        "left_id": left["id"],
        "right_id": right["id"],
        "kind": kind,
        "span_domain": domain,
        "intersection": [max(a, c), min(b, d)],
        "shared_endpoints": sorted(set((a, b)) & set((c, d))),
    }


def _assert_shared_baseline(records: list[dict[str, Any]]) -> None:
    """Successful methods share a directional baseline; failure is not empty."""
    geometry_fields = ("start", "peak", "end", "observedThrough", "scale", "leftCensored", "rightCensored")

    def geometry(wave: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(wave[field] for field in geometry_fields)

    by_scale: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    for record in records:
        if record.get("result") is None or record["status"] in ("error", "failed"):
            continue
        waves = record["result"].get("waves", [])
        scale, method = record["scale"], record["method"]
        if scale not in by_scale:
            by_scale[scale] = method, waves
            continue
        previous_method, previous = by_scale[scale]
        if method == previous_method:
            continue
        old = {geometry(wave): wave for wave in previous}
        new = {geometry(wave): wave for wave in waves}
        if len(previous) != len(waves) or set(old) != set(new):
            raise ValueError(f"inconsistent shared wave geometry: {scale}")
        old_ids = {wave["id"]: geometry(wave) for wave in previous}
        new_ids = {wave["id"]: geometry(wave) for wave in waves}
        for key, wave in old.items():
            other = new[key]
            for field in ("gain", "maxDrawdown"):
                if _finite(wave.get(field)) and _finite(other.get(field)) and wave[field] != other[field]:
                    raise ValueError(f"inconsistent shared wave {field}: {scale}")
            old_parent = wave.get("parentId")
            new_parent = other.get("parentId")
            old_parent_geometry = old_ids.get(old_parent, ("unresolved", old_parent)) if old_parent is not None else None
            new_parent_geometry = new_ids.get(new_parent, ("unresolved", new_parent)) if new_parent is not None else None
            if old_parent_geometry != new_parent_geometry:
                raise ValueError(f"inconsistent shared wave parent: {scale}")


def _adapter_context(series: dict[str, Any], calendar: list[str] | dict[str, Any], native: dict[str, Any]) -> tuple[list[str], tuple[Any, ...]]:
    """Bind both projections to the same aligned source identities."""
    dates = _dates(calendar)
    if len(series["raw"]) != len(dates) or len(series["adjusted"]) != len(dates):
        raise ValueError("series/calendar length mismatch")
    for field in ("security_id", "series_id", "calendar_id"):
        if native.get(field) != series.get(field):
            raise ValueError(f"native/series identity mismatch: {field}")
    scope = (native.get("input_identity"), series["series_id"], RULE, series["security_id"])
    return dates, scope


def _security_row(series: dict[str, Any], dates: list[str], native: dict[str, Any]) -> dict[str, Any]:
    observed = [i for i, value in enumerate(series["raw"]) if _finite(value)]
    role = series.get("instrument_role", series.get("role"))
    return {
        **{k: series.get(k) for k in ("security_id", "series_id", "calendar_id", "code", "name", "cohort")},
        "instrument_role": role,
        "stock_opportunity_eligible": role == "stock" and series.get("cohort") != "unresolved",
        "first_date": dates[observed[0]] if observed else None,
        "last_date": dates[observed[-1]] if observed else None,
        "observed_count": len(observed),
        "source_counts": dict(Counter(s for s in series.get("sources", []) if s)),
        "coverage_caveats": series.get("coverage_caveats", []),
        "status": "observed" if observed else "no_usable_quotes",
        "continuity_runs": _run_spans(_native_runs(native, series)),
        "run_boundary_precision": "exact_pinned_js" if "source_run_indices" in native else "python_fallback",
        **UNKNOWN,
    }


def _add_wave_alias(
    groups: dict[Any, dict[str, Any]], alias_ids: dict[Any, str], scope: tuple[Any, ...], security_id: str, method: str, scale: str, wave: dict[str, Any]
) -> None:
    # Only exact source copies at the SAME scale are aliases.
    key = (scale, wave["start"], wave["peak"], wave["end"], wave["observedThrough"], wave["scale"], wave["leftCensored"], wave["rightCensored"])
    alias = {
        "method": method,
        "method_scale": scale,
        "native_id": wave["id"],
        "source_id": _id(*scope, method, scale, "wave", wave["id"]),
        "native_parent_id": wave.get("parentId"),
    }
    if key not in groups:
        groups[key] = {
            **wave,
            "id": _id(*scope, "baseline", key),
            "security_id": security_id,
            "method_scale": scale,
            "aliases": [],
            "gain_unit": "percent",
            "maxDrawdown_unit": "percent",
            **UNKNOWN,
        }
    shared = groups[key]
    for field in ("gain", "maxDrawdown"):
        if _finite(shared.get(field)) and _finite(wave.get(field)) and shared[field] != wave[field]:
            raise ValueError(f"inconsistent shared wave {field}")
    shared["aliases"].append(alias)
    alias_ids[(method, scale, wave["id"])] = shared["id"]


def _candidate_in_wave(wave: dict[str, Any], index: int) -> bool:
    return wave["start"] <= index and (index < wave["end"] if wave["end"] is not None else index <= wave["observedThrough"])


def project_query_tables(series: dict[str, Any], calendar: list[str] | dict[str, Any], native: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Reconstruct only query rows, without phases, relations or gain work.

    This projection is not a native semantic gate; callers still validate the
    native artifact and its receipt before accepting the reconstructed rows.
    """
    dates, scope = _adapter_context(series, calendar, native)
    security = _security_row(series, dates, native)
    records = native.get("native", [])
    _assert_shared_baseline(records)
    groups: dict[Any, dict[str, Any]] = {}
    alias_ids: dict[Any, str] = {}
    candidates = []
    for record in records:
        method, scale = record["method"], record["scale"]
        result = record.get("result") or {}
        for wave in result.get("waves", []):
            _add_wave_alias(groups, alias_ids, scope, series["security_id"], method, scale, wave)
        if method == "segments" and scale == "balanced":
            for candidate in result.get("launches", []):
                candidates.append({
                    "id": _id(*scope, method, scale, "candidate", candidate["id"]),
                    "index": candidate["index"],
                    "method": method,
                    "method_scale": scale,
                    "wave_ids": [],
                })
    waves = list(groups.values())
    for candidate in candidates:
        candidate["wave_ids"] = [
            wave["id"]
            for wave in waves
            if wave["method_scale"] == candidate["method_scale"]
            and any(alias["method"] == candidate["method"] for alias in wave["aliases"])
            and _candidate_in_wave(wave, candidate["index"])
        ]
    intervals, _ = build_representative_intervals(waves, dates, candidates)
    for row in intervals:
        row.update(security_id=series["security_id"], series_id=series["series_id"])
    LOGGER.debug("Projected query rows for %s: %d intervals", series["security_id"], len(intervals))
    return {"securities": [security], "representative_intervals": intervals}


def adapt_security(series: dict[str, Any], calendar: list[str] | dict[str, Any], native: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Adapt one aligned security; dense fits stay in the native artifact."""
    dates, scope = _adapter_context(series, calendar, native)
    tables: dict[str, list[dict[str, Any]]] = {
        name: []
        for name in (
            "securities",
            "methods",
            "baseline_waves",
            "source_phases",
            "candidates",
            "support_records",
            "relations",
            "representative_intervals",
            "transitions",
        )
    }
    tables["securities"].append(_security_row(series, dates, native))
    alias_ids: dict[Any, str] = {}
    groups: dict[Any, dict[str, Any]] = {}
    runs = _native_runs(native, series)
    gain_series = {**series, "source_run_indices": runs}
    records = native.get("native", [])
    _assert_shared_baseline(records)
    for record in records:
        method, scale = record["method"], record["scale"]
        result = record.get("result") or {}
        method_id = _id(*scope, method, scale)
        tables["methods"].append({
            "id": method_id,
            "security_id": series["security_id"],
            "method": method,
            "scale": scale,
            "status": record["status"],
            "error": record.get("error"),
            "warnings": result.get("warnings", []),
            "diagnostics": result.get("diagnostics"),
            "wave_count": len(result.get("waves", [])),
            "phase_count": len(result.get("segments", [])),
            "candidate_count": len(result.get("launches", [])),
        })
        for wave in result.get("waves", []):
            _add_wave_alias(groups, alias_ids, scope, series["security_id"], method, scale, wave)
        for index, phase in enumerate(result.get("segments", [])):
            phase_runs = sorted({run for run in runs[phase["start"] : phase["end"] + 1] if run is not None})
            tables["source_phases"].append({
                **phase,
                "id": _id(*scope, method, scale, "phase", index),
                "security_id": series["security_id"],
                "method": method,
                "method_scale": scale,
                "span_domain": "native_phase_inclusive",
                "source_run_ids": phase_runs,
                "run_boundary_crossing": len(phase_runs) > 1,
                "run_boundary_reason": "crosses_source_usable_runs"
                if len(phase_runs) > 1
                else "single_source_run"
                if phase_runs
                else "no_usable_source_points",
                **UNKNOWN,
            })
        for candidate in result.get("launches", []):
            tables["candidates"].append({
                **candidate,
                "id": _id(*scope, method, scale, "candidate", candidate["id"]),
                "native_id": candidate["id"],
                "security_id": series["security_id"],
                "method": method,
                "method_scale": scale,
                "wave_ids": [],
                "manual_selection": None,
                "manual_selection_status": "not_selected",
                "gain_unit": "percent",
                "forwardGain_unit": "percent",
                "drawdown_unit": "percent",
                **UNKNOWN,
            })
    tables["baseline_waves"] = list(groups.values())
    for wave in tables["baseline_waves"]:
        for alias in wave["aliases"]:
            parent = alias_ids.get((alias["method"], alias["method_scale"], alias["native_parent_id"]))
            if alias["native_parent_id"] is not None:
                tables["relations"].append({
                    "left_id": wave["id"],
                    "right_id": parent,
                    "native_parent_id": alias["native_parent_id"],
                    "method": alias["method"],
                    "kind": "native_parent",
                    "span_domain": "native_wave",
                })
            tables["relations"].append({"left_id": alias["source_id"], "right_id": wave["id"], "kind": "equality_alias", "span_domain": "native_wave"})
    for index, wave in enumerate(tables["baseline_waves"]):
        span = (wave["start"], wave["end"] if wave["end"] is not None else wave["observedThrough"])
        for other in tables["baseline_waves"][index + 1 :]:
            relation = _relation(
                wave, other, span, (other["start"], other["end"] if other["end"] is not None else other["observedThrough"]), "native_wave_inclusive"
            )
            if relation:
                tables["relations"].append(relation)
        for row, domain in [(p, "native_phase_inclusive") for p in tables["source_phases"]] + [
            (c, "native_candidate_ensuing_inclusive") for c in tables["candidates"]
        ]:
            if row["method_scale"] != wave["method_scale"] or not any(a["method"] == row["method"] for a in wave["aliases"]):
                continue
            row_span = (row["start"], row["end"]) if "start" in row else (row["rangeStart"], row["rangeEnd"])
            relation = _relation(wave, row, span, row_span, domain)
            if relation:
                tables["relations"].append(relation)
            if "wave_ids" in row and _candidate_in_wave(wave, row["index"]):
                row["wave_ids"].append(wave["id"])
                tables["relations"].append({
                    "left_id": wave["id"],
                    "right_id": row["id"],
                    "kind": "candidate_index_in_wave",
                    "span_domain": "wave_membership_start_inclusive_end_exclusive",
                    "index": row["index"],
                })
    candidate_ids = {(c["method"], c["method_scale"], c["native_id"]): c["id"] for c in tables["candidates"]}
    for index, support in enumerate(native.get("support_records", [])):
        matched_catalog_ids = [candidate_ids.get((match["method"], match["scale"], match["candidate_id"])) for match in support.get("matched_ids", [])]
        tables["support_records"].append({
            **support,
            "id": _id(*scope, "support", index),
            "security_id": series["security_id"],
            "target_catalog_id": candidate_ids.get((
                support.get("method"),
                support.get("scale", support.get("target_scale")),
                support.get("candidate_id", support.get("target_id", support.get("targetId"))),
            )),
            "matched_catalog_ids": matched_catalog_ids,
            "span_domain": "comparison_support_calendar_indices",
        })
    intervals, transitions = build_representative_intervals(tables["baseline_waves"], dates, tables["candidates"])
    for row in intervals + transitions:
        row["security_id"] = series["security_id"]
        row["series_id"] = series["series_id"]
    for row in transitions:
        for side in ("old", "new"):
            base = row[f"{side}_gain_base_index"]
            gain, reason = gain_at(gain_series, dates, base, row["index"]) if base is not None else (None, "no_wave")
            row[f"{side}_gain"] = gain
            row[f"{side}_gain_reason"] = reason
        row["gain_jump"] = row["new_gain"] - row["old_gain"] if row["new_gain"] is not None and row["old_gain"] is not None else None
        row["gain_unit"] = "fraction"
        row["gain_jump_unit"] = "fraction"
    tables["representative_intervals"], tables["transitions"] = intervals, transitions
    LOGGER.info("Adapted %s: %d waves, %d candidates", series["security_id"], len(groups), len(tables["candidates"]))
    return tables


def query_security(tables: dict[str, list[dict[str, Any]]], series: dict[str, Any], calendar: list[str] | dict[str, Any], date: str) -> dict[str, Any]:
    """Use the producer's intervals and series; never infer a launch or exit."""
    dates = _dates(calendar)
    if date not in dates:
        return {"date": date, "code": series["code"], "member": False, "reason": "outside_source_calendar"}
    index = dates.index(date)
    interval = next(
        (r for r in tables["representative_intervals"] if r["security_id"] == series["security_id"] and r["start_index"] <= index < r["end_exclusive_index"]),
        None,
    )
    if interval and interval["series_id"] != series["series_id"]:
        raise ValueError("interval/series identity mismatch")
    security = next(r for r in tables["securities"] if r["security_id"] == series["security_id"])
    gain_series = series
    if "continuity_runs" in security:
        runs: list[int | None] = [None] * len(dates)
        for span in security["continuity_runs"]:
            runs[span["start"] : span["end"] + 1] = [span["run_id"]] * (span["end"] - span["start"] + 1)
        gain_series = {**series, "source_run_indices": runs}
    gain, reason = gain_at(gain_series, dates, interval["gain_base_index"], index) if interval else (None, "no_active_wave")
    return {
        "code": series["code"],
        "date": date,
        "series_id": series["series_id"],
        "member": interval is not None,
        "stock_opportunity_count": int(interval is not None and security["stock_opportunity_eligible"]),
        "wave_id": interval["wave_id"] if interval else None,
        "gain_base_index": interval["gain_base_index"] if interval else None,
        "raw_quote": series["raw"][index],
        "adjusted_quote": series["adjusted"][index],
        "gain": gain,
        "gain_unit": "fraction",
        "gain_reason": reason,
        "earliest_candidate_id": interval["earliest_candidate_id"] if interval else None,
        "manual_selection": None,
    }
