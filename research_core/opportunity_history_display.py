"""Presentation projections over already-saved opportunity history results."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from research_core.wave_growth import wave_gain

SCHEMA = "opportunity-history-web.v1"
DISPLAY_PHASES = {"fast": "rising", "rising": "slow", "flat": "resting", "falling": "retreat"}
PHASE_LABELS = {"all": "代表波段", "peak_gain_100": "最高漲幅至少 100%", "candidate_started": "發動候選已開始"}
SCALE_LABELS = {"balanced": "平衡尺度", "coarse": "較粗尺度"}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _date(dates: list[str], index: int | None) -> str | None:
    return dates[index] if isinstance(index, int) and 0 <= index < len(dates) else None


def _exclusive_date(dates: list[str], index: int) -> str:
    if index < len(dates):
        return dates[index]
    return (date.fromisoformat(dates[-1]) + timedelta(days=1)).isoformat()


def _phase_segments(catalog: dict[str, Any], code: str, start: int, end: int) -> list[dict[str, Any]]:
    records = catalog.get("native_display", {}).get(code, {})
    segments = records.get(("segments", "balanced"), {}).get("segments", [])
    dates = catalog["dates"]
    result = []
    for segment in segments:
        left, right = max(start, segment["start"]), min(end, segment["end"])
        if left > right:
            continue
        phase = DISPLAY_PHASES.get(segment.get("phase"))
        if phase is None:
            continue
        result.append({"from": dates[left], "until": dates[right], "phase": phase})
    return result


def _launch(catalog: dict[str, Any], code: str, candidate_id: str | None) -> dict[str, Any] | None:
    if candidate_id is None:
        return None
    dates = catalog["dates"]
    candidates = catalog.get("native_display", {}).get(code, {}).get(("segments", "balanced"), {}).get("launches", [])
    row = next((candidate for candidate in candidates if candidate["catalogId"] == candidate_id), None)
    if row is None:
        return None
    return {
        "date": _date(dates, row.get("index")),
        "rangeFrom": _date(dates, row.get("rangeStart")),
        "rangeUntil": _date(dates, row.get("rangeEnd")),
        "kind": row.get("kind"),
        "outcome": row.get("outcome"),
    }


def _sparkline(catalog: dict[str, Any], code: str, start: int, end: int, limit: int = 24) -> list[dict[str, Any]]:
    dates = catalog["dates"]
    series = catalog["series"][code]
    gain_index = catalog["gains"][code]
    prices = series["adjusted"]
    indices = list(range(max(0, start), min(end, len(prices) - 1) + 1))
    if len(indices) > limit:
        # Evenly retain endpoints so the displayed interval remains explicit.
        indices = sorted({round(position * (len(indices) - 1) / (limit - 1)) for position in range(limit)})
        indices = [range(max(0, start), min(end, len(prices) - 1) + 1)[position] for position in indices]
    result = []
    previous_index = None
    for index in indices:
        price = prices[index]
        point_gain, _ = gain_index.at(index, index)
        continuous = previous_index is None or gain_index.at(previous_index, index)[0] is not None
        valid = _finite(price) and price > 0 and point_gain is not None and continuous
        result.append({"date": dates[index], "adjusted": price if valid else None})
        previous_index = index
    return result


def augment_frame_row(catalog: dict[str, Any], row: dict[str, Any], index: int) -> None:
    code = row["code"]
    wave = catalog["waves"][row["waveId"]]
    dates = catalog["dates"]
    stop = wave["end"] - 1 if wave.get("end") is not None else wave["observedThrough"]
    phases = _phase_segments(catalog, code, wave["start"], min(index, stop))
    current_source_phase = None
    current_phase = None
    for segment in catalog.get("native_display", {}).get(code, {}).get(("segments", "balanced"), {}).get("segments", []):
        if segment["start"] <= index <= segment["end"]:
            current_source_phase = segment.get("phase")
            current_phase = DISPLAY_PHASES.get(current_source_phase)
            break
    row.update({
        "launchCandidate": _launch(catalog, code, row.get("earliestCandidateId")),
        "phase": current_phase,
        "sourcePhase": current_source_phase,
        "sparkline": _sparkline(catalog, code, wave["start"], index),
        "phases": phases,
        "growth": wave_gain(row.get("start"), dates[index], row.get("gain"), row.get("leftCensored") is True),
    })
    # Keep the wave-low and candidate launch as independent dated anchors.
    launch = row["launchCandidate"]
    launch_index = dates.index(launch["date"]) if launch is not None else None
    launch_gain = catalog["gains"][code].at(launch_index, index)[0] if launch_index is not None else None
    prices = catalog["series"][code]["adjusted"]
    row["startAdjusted"] = prices[wave["start"]] if catalog["gains"][code].at(wave["start"], wave["start"])[0] is not None else None
    row["launchAdjusted"] = prices[launch_index] if launch_index is not None and catalog["gains"][code].at(launch_index, launch_index)[0] is not None else None
    row["launchGain"] = launch_gain * 100 if launch_gain is not None else None


def build_directory(catalog: dict[str, Any]) -> dict[str, Any]:
    """Return one row per saved representative interval, including closed intervals."""
    dates = catalog["dates"]
    rows = []
    codes_by_security = {security["security_id"]: code for code, security in catalog["securities"].items()}
    for security_id, intervals in catalog["intervals"].items():
        code = codes_by_security.get(security_id)
        if code is None or code not in catalog["series"]:
            continue
        security = catalog["securities"][code]
        classification = catalog["classifications"].get(code) or {}
        snapshot = classification.get("official_industry_snapshot") or {}
        label = snapshot.get("label")
        for interval in intervals:
            wave = catalog["waves"][interval["wave_id"]]
            start, end_exclusive = interval["start_index"], interval["end_exclusive_index"]
            final_index = end_exclusive - 1
            if not 0 <= final_index < len(dates):
                continue
            confirmed_end = wave.get("end")
            end_gain_index = confirmed_end - 1 if confirmed_end is not None else None
            gain = catalog["gains"][code].at(wave["start"], end_gain_index)[0] if end_gain_index is not None else None
            gain_at_end_date = _date(dates, end_gain_index)
            peak, _ = catalog["gains"][code].at(wave["start"], wave["peak"])
            stop = wave["end"] - 1 if wave.get("end") is not None else wave["observedThrough"]
            rows.append({
                "securityId": security_id,
                "code": code,
                "name": security.get("name") or code,
                "industry": {
                    "id": label or "unknown",
                    "label": label or "分類待補",
                    "basis": "current-snapshot" if label else "unknown",
                    "snapshotAt": snapshot.get("fetched_at") if label else None,
                },
                "waveId": wave["id"],
                "start": _date(dates, wave["start"]),
                "peakDate": _date(dates, wave["peak"]),
                "endConfirmedAt": _date(dates, wave.get("end")),
                "observedThrough": _date(dates, wave.get("observedThrough")),
                "representativeFrom": _date(dates, start),
                "representativeUntilExclusive": _exclusive_date(dates, end_exclusive),
                "launchCandidate": _launch(catalog, code, interval.get("earliest_candidate_id")),
                "phases": _phase_segments(catalog, code, wave["start"], stop),
                "scale": wave["scale"],
                "leftCensored": wave["leftCensored"],
                "rightCensored": wave["rightCensored"],
                "peakGain": peak * 100 if peak is not None else None,
                "gainAtEnd": gain * 100 if gain is not None else None,
                "gainAtEndDate": gain_at_end_date,
                "growthAtEnd": wave_gain(
                    _date(dates, wave["start"]),
                    gain_at_end_date,
                    gain * 100 if gain is not None else None,
                    wave.get("leftCensored") is True,
                ),
            })
    rows.sort(key=lambda row: (row["representativeFrom"], row["code"], row["waveId"]))
    return {"schema": SCHEMA, "catalogId": catalog["id"], "method": "segments", "methodScale": "balanced", "rows": rows}


def build_options(catalog: dict[str, Any], date: str) -> dict[str, Any]:
    dates = catalog["dates"]
    if date not in dates:
        raise ValueError("Date is outside the saved quote calendar")
    index = dates.index(date)
    rows = []
    for scale in ("balanced", "coarse"):
        counts = {condition: 0 for condition in PHASE_LABELS}
        for code, security in catalog["securities"].items():
            if security.get("stock_opportunity_eligible") is not True or code not in catalog["series"]:
                continue
            native = catalog.get("native_display", {}).get(code, {}).get(("segments", scale))
            if native is None:
                continue
            active = [
                wave
                for wave in native["waves"]
                if wave["start"] <= index and (index < wave["end"] if wave.get("end") is not None else index <= wave["observedThrough"])
            ]
            if not active:
                continue
            wave = min(active, key=lambda item: (item["scale"] != "large", item["start"], item["id"]))
            counts["all"] += 1
            gain, _ = catalog["gains"][code].at(wave["start"], wave["peak"])
            if gain is not None and gain * 100 >= 100:
                counts["peak_gain_100"] += 1
            if any(
                wave["start"] <= launch_index <= index and (wave.get("end") is None or launch_index < wave["end"]) for launch_index in native["launchIndices"]
            ):
                counts["candidate_started"] += 1
        for condition, label in PHASE_LABELS.items():
            rows.append({
                "id": f"segments:{scale}:{condition}",
                "label": f"{label}（{SCALE_LABELS[scale]}）",
                "method": "segments",
                "methodScale": scale,
                "condition": condition,
                "count": counts[condition],
            })
    return {"schema": SCHEMA, "catalogId": catalog["id"], "date": date, "rows": rows}
