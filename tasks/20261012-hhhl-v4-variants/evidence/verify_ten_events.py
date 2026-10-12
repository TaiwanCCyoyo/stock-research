"""Retained one-off checks of the fixed ten-event audit; never import this file."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from research_core.artifact_store import file_digest, read_json, safe_path, verify_files  # noqa: E402
from research_core.derived_features import compute_features  # noqa: E402
from research_core.hhhl_variants_features import classify_feature  # noqa: E402
from research_core.hhhl_variants_observations import classify_window, flag_history, landmark_riskset, previous_completed_week_signal  # noqa: E402

LOCAL_FEATURES = ("A", "B", "B2", "C", "C2", "C3", "C4", "D", "D2", "E", "E2", "E3", "E4_cat", "E4_big", "F", "G", "G2_limit", "G2_position", "I", "K", "K2")
FLAG_IDS = ("X1", "X2", "X3", "X4", "X5_MA20", "X5_MA60", "X6_10", "X6_15")


def positive(value: Any) -> bool:
    return value is not None and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def audit_date(value: Any) -> date:
    timestamp = pd.Timestamp(value)
    if not isinstance(timestamp, pd.Timestamp):
        raise ValueError("audit dates must be nonmissing")
    return cast(date, timestamp.date())


class Checks:
    def __init__(self) -> None:
        self.count = 0

    def equal(self, actual: Any, expected: Any, label: str) -> None:
        self.count += 1
        if expected is None:
            okay = actual is None or (isinstance(actual, float) and not math.isfinite(actual))
        elif isinstance(expected, bool):
            okay = isinstance(actual, (bool, np.bool_)) and bool(actual) == expected
        elif isinstance(expected, (int, float)):
            okay = actual is not None and math.isclose(float(actual), float(expected), rel_tol=1e-10, abs_tol=1e-10)
        else:
            okay = actual == expected
        if not okay:
            # Never include supplied quote vectors or numeric market values.
            raise AssertionError(f"ten-event verification mismatch: {label}")


def quote_valid(bar: dict[str, Any]) -> bool:
    values = [bar[name] for name in ("Open", "High", "Low", "Close")]
    if not all(positive(value) for value in values):
        return False
    opening, high, low, close = values
    return high >= low and low <= opening <= high and low <= close <= high


def mean_window(closes: list[Any], length: int, stop: int) -> float | None:
    start = stop - length
    if start < 0:
        return None
    window = closes[start:stop]
    return math.fsum(window) / length if len(window) == length and all(positive(value) for value in window) else None


def ratio(numerator: Any, denominator: Any, *, minus_one: bool = False) -> float | None:
    if not positive(numerator) or not positive(denominator):
        return None
    return numerator / denominator - int(minus_one)


def verify_features(case: dict[str, Any], checks: Checks) -> None:
    event = case["original_source_event"]
    inputs = case["feature_inputs_asof_t0"]
    prefix = inputs["common_calendar_prefix"]
    t0 = int(event["calendar_index"])
    checks.equal(len(prefix), t0 + 1, "prefix length")
    checks.equal([row["calendar_index"] for row in prefix], list(range(t0 + 1)), "prefix calendar positions")
    dates = [audit_date(row["Date"]) for row in prefix]
    checks.equal(dates[-1].isoformat(), audit_date(case["asof_date"]).isoformat(), "event date")
    raw = [row["raw"] for row in prefix]
    adjusted = [row["adjusted"] for row in prefix]
    valid = [quote_valid(bar) for bar in adjusted]
    closes = [bar["Close"] if usable else None for bar, usable in zip(adjusted, valid)]
    frame = pd.DataFrame([{name: bar[name] for name in ("Open", "High", "Low", "Close")} for bar in adjusted], index=pd.DatetimeIndex(dates))
    frame["Quality"] = True
    recomputed, _ = compute_features(frame)
    for index, row in enumerate(prefix):
        for stored, shared in (("atr_pct", "atr14_pct"), ("ma20", "SMA20"), ("ma60", "SMA60")):
            value = recomputed[shared].iloc[index]
            expected = float(value) if pd.notna(value) and math.isfinite(float(value)) else None
            checks.equal(row["daily"][stored], expected, f"{case['event_id']} prefix {stored}/{index}")
    anchor = adjusted[-1]["Close"]
    z2, hz = event["Z2"], event["hz_top"]
    restart_day = audit_date(event["restart_date"])
    if restart_day not in dates or restart_day > dates[-1]:
        raise AssertionError("restart date outside causal prefix")
    restart_index = dates.index(restart_day)
    restart_low = adjusted[restart_index]["Low"]
    levels = json.loads(event["bonus_levels"])
    sequence = json.loads(event["pivot_sequence"])
    for point in sequence:
        if audit_date(point["date"]) > dates[-1]:
            raise AssertionError("stored pivot extreme is after t0")
    upper = [line["level"] for line in levels]
    if any(not positive(level) or (positive(anchor) and level <= anchor) for level in upper):
        raise AssertionError("original bonus level violates upper-line contract")
    m20, m60, m120, m240 = [mean_window(closes, n, t0 + 1) for n in (20, 60, 120, 240)]
    m240_prior = mean_window(closes, 240, t0 - 19)
    hierarchy = [closes[-1], m20, m60, m120, m240]
    c: int | None
    if all(positive(value) for value in hierarchy):
        observed_hierarchy = [float(cast(float, value)) for value in hierarchy]
        c = sum(left > right for left, right in zip(observed_hierarchy, observed_hierarchy[1:]))
    else:
        c = None
    prior250 = closes[max(0, t0 - 250) : t0]
    extrema_known = len(prior250) == 250 and all(positive(value) for value in prior250)
    observed_prior250 = [float(cast(float, value)) for value in prior250] if extrema_known else []
    previous_atr = [row["daily"]["atr_pct"] for row in prefix[max(0, t0 - 120) : t0]]
    atr_known = len(previous_atr) == 120 and all(value is not None and math.isfinite(value) for value in previous_atr)
    median = statistics.median(previous_atr) if atr_known else None
    # Frozen G compresses only rows retained by source price restoration. Its
    # min_periods=1 mean ignores missing volumes within the last 20 such rows.
    source_positions = [
        index for index, bar in enumerate(adjusted) if all(bar[name] is not None and math.isfinite(bar[name]) for name in ("Open", "High", "Low", "Close"))
    ]
    previous_source = [index for index in source_positions if index < t0][-20:]
    volumes = [raw[index]["VolumeLots"] for index in previous_source if raw[index]["VolumeLots"] is not None and math.isfinite(raw[index]["VolumeLots"])]
    mean_volume = math.fsum(volumes) / len(volumes) if volumes else None
    numerator_volume = raw[-1]["VolumeLots"]
    legacy_vx = numerator_volume / mean_volume if positive(mean_volume) and numerator_volume is not None and math.isfinite(numerator_volume) else None
    checks.equal(event["vx"], legacy_vx, f"{case['event_id']} frozen source vx")
    raw_current = raw[-1]["Close"]
    raw_previous = raw[-2]["Close"] if len(raw) >= 2 else None
    raw_return = ratio(raw_current, raw_previous, minus_one=True)
    high, low = adjusted[-1]["High"], adjusted[-1]["Low"]
    position = bool((anchor - low) / (high - low) >= 0.75) if valid[-1] and high > low else None
    values = {
        "A": ratio(min(upper), anchor, minus_one=True) if upper else None,
        "B": ratio(anchor, z2, minus_one=True),
        "B2": ratio(anchor, hz, minus_one=True),
        "C": c,
        "C2": ratio(m240, m240_prior, minus_one=True),
        "C3": ratio(closes[-1], m240, minus_one=True),
        "C4": previous_completed_week_signal(dates, closes, t0),
        "D": ratio(closes[-1], max(observed_prior250)) if extrema_known else None,
        "D2": ratio(closes[-1], min(observed_prior250)) if extrema_known else None,
        "E": t0 - restart_index,
        "E2": (hz - restart_low) / hz if positive(hz) and positive(restart_low) else None,
        "E3": sum(point["k"] in {"H", "L"} and point["rel"] == "higher" for point in sequence),
        "E4_cat": event["cat"],
        "E4_big": bool(event["big_hhhl"]),
        "F": ratio(previous_atr[-1], median) if atr_known else None,
        "G": legacy_vx,
        "G2_limit": bool(raw_return >= 0.095) if raw_return is not None else None,
        "G2_position": position,
        "I": inputs["context_asof_t0"]["regime"],
        "K": prefix[-1]["daily"]["atr_pct"],
        "K2": raw_current if positive(raw_current) else None,
    }
    # Zero ATR is an observed value, not missing. F also allows zero numerator
    # whenever its full median is strictly positive.
    if atr_known and positive(median):
        values["F"] = previous_atr[-1] / median
    computed = inputs["computed_features_asof_t0"]
    for feature_id in LOCAL_FEATURES:
        expected = values[feature_id]
        checks.equal(computed[feature_id], expected, f"{case['event_id']} value {feature_id}")
        if feature_id in {"C", "E", "E3"} and expected is not None:
            expected = int(expected)
        classified = classify_feature(feature_id, expected, applicable=feature_id != "A" or bool(upper))
        checks.equal(computed[f"{feature_id}_status"], classified.status, f"{case['event_id']} status {feature_id}")
        checks.equal(computed[f"{feature_id}_bin"], classified.bin_id, f"{case['event_id']} bin {feature_id}")


def support_flag(close: Any, support: Any, *, inclusive: bool = False) -> bool | None:
    if not positive(close) or not positive(support):
        return None
    return bool(close <= support if inclusive else close < support)


def verify_flags(case: dict[str, Any], checks: Checks) -> int:
    event = case["original_source_event"]
    evidence = case["outcome_flag_path_t0_to_H"]
    points = evidence["closing_path"]
    t0 = int(event["calendar_index"])
    checks.equal([point["offset"] for point in points], list(range(len(points))), "flag path offsets")
    checks.equal([point["calendar_index"] for point in points], list(range(t0, t0 + len(points))), "flag path indices")
    prefix = case["feature_inputs_asof_t0"]["common_calendar_prefix"]
    dates = {row["calendar_index"]: audit_date(row["Date"]) for row in [*prefix, *points]}
    z2, hz = event["Z2"], event["hz_top"]
    restart = audit_date(event["restart_date"])
    restart_low = next(row["adjusted"]["Low"] for row in prefix if audit_date(row["Date"]) == restart)
    crossing = set()
    for pivot in evidence["frozen_low_pivots"]:
        extreme, confirmed = pivot["extreme_index"], pivot["confirmed_index"]
        if not 0 <= extreme <= confirmed < t0 + len(points):
            raise AssertionError("audit pivot indices violate confirmation order")
        checks.equal(audit_date(pivot["extreme_date"]), dates[extreme], "pivot extreme date")
        checks.equal(audit_date(pivot["confirmed_date"]), dates[confirmed], "pivot confirmation date")
        if confirmed > t0 and positive(z2) and pivot["price"] < z2:
            crossing.add(confirmed)
    path = [point["adjusted_close"] for point in points]
    anchor = path[0]
    vectors: dict[str, list[bool | None]] = {name: [] for name in FLAG_IDS}
    for point in points:
        close = point["adjusted_close"]
        for name, support in (("X1", hz), ("X2", z2), ("X3", restart_low), ("X5_MA20", point["ma20"]), ("X5_MA60", point["ma60"])):
            vectors[name].append(support_flag(close, support))
        vectors["X4"].append(point["calendar_index"] in crossing if positive(z2) else None)
        vectors["X6_10"].append(support_flag(close, anchor * 0.9 if positive(anchor) else None, inclusive=True))
        vectors["X6_15"].append(support_flag(close, anchor * 0.85 if positive(anchor) else None, inclusive=True))
    seen = set()
    for row in evidence["flags"]:
        horizon, landmark, flag_id = int(row["horizon"]), int(row["landmark"]), row["flag_id"]
        identity = horizon, landmark, flag_id
        if identity in seen or flag_id not in FLAG_IDS:
            raise AssertionError("duplicate or unrecognized audit flag row")
        seen.add(identity)
        outcome = classify_window(path, horizon)
        new = landmark_riskset(path, landmark, z2 if positive(z2) else 1.0)
        old = landmark_riskset(path, landmark, z2, legacy_active=True) if positive(z2) else None
        raw = flag_history(vectors[flag_id], landmark)
        before = flag_history(vectors[flag_id], landmark, outcome.first_hit_offset)
        trigger = before.first_trigger_offset
        checks.equal(row["flag_state"], before.state, "pre-hit flag state")
        checks.equal(row["first_trigger_offset"], trigger, "pre-hit first trigger")
        checks.equal(row["through_offset"], before.through_offset, "pre-hit through offset")
        checks.equal(row["unknown_reason"], before.reason, "pre-hit reason")
        checks.equal(row["raw_flag_state"], raw.state, "raw flag state")
        checks.equal(row["raw_first_trigger_offset"], raw.first_trigger_offset, "raw first trigger")
        checks.equal(row["raw_unknown_reason"], raw.reason, "raw reason")
        checks.equal(row["label"], outcome.outcome, "path label")
        checks.equal(row["first_hit_offset"], outcome.first_hit_offset, "first hit")
        checks.equal(row["calendar_full"], outcome.calendar_full, "calendar full")
        checks.equal(row["full_path"], outcome.full_path, "price path full")
        checks.equal(row["outcome_unknown_reason"], outcome.reason, "outcome reason")
        checks.equal(row["riskset_state"], new.state, "new riskset state")
        checks.equal(row["riskset_eligible"], new.eligible, "new riskset eligible")
        checks.equal(row["riskset_reason"], new.reason, "new riskset reason")
        checks.equal(row["riskset_decision_offset"], new.decision_offset, "new riskset decision")
        checks.equal(row["legacy_state"], old.state if old else "early_unknown", "legacy riskset state")
        checks.equal(row["legacy_reason"], old.reason if old else "invalid_support", "legacy reason")
        checks.equal(row["legacy_decision_offset"], old.decision_offset if old else None, "legacy decision")
        trigger_return = path[trigger] / anchor - 1 if trigger is not None and positive(path[trigger]) and positive(anchor) else None
        checks.equal(row["trigger_return"], trigger_return, "trigger return")
        if trigger is not None and outcome.first_hit_offset is not None:
            checks.equal(trigger < outcome.first_hit_offset, True, "strictly before first hit")
    expected_rows = {(horizon, landmark, flag_id) for horizon in (126, 252) for landmark in (5, 10, 20, 40, horizon) for flag_id in FLAG_IDS}
    checks.equal(seen, expected_rows, "all fixed flag scopes present")
    return len(seen)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    args = parser.parse_args()
    if not args.dataset.is_absolute():
        parser.error("--dataset must be an absolute path")
    dataset = safe_path(args.dataset)
    manifest = read_json(dataset / "manifest.json")
    names = ("audit/ten-events.json", "audit-digest.json")
    descriptors = [entry for entry in manifest["artifacts"] if entry["path"] in names]
    if len(descriptors) != len(names):
        raise ValueError("manifest must declare both fixed audit artifacts")
    verify_files(dataset, descriptors)
    audit = read_json(dataset / names[0], max_bytes=64_000_000)
    digest = read_json(dataset / names[1])
    cases = audit["cases"]
    identifiers = [case["event_id"] for case in cases]
    checks = Checks()
    checks.equal(audit["schema_version"], "hhhl-variants-audit.v1", "audit schema")
    checks.equal(audit["rows"], 10, "fixed audit rows")
    checks.equal(len(cases), 10, "ten cases")
    checks.equal(len(set(identifiers)), 10, "distinct event identities")
    checks.equal(identifiers, digest["selected_event_ids"], "fixed selected identities")
    checks.equal(file_digest(dataset / names[0]), digest["sha256"], "audit digest pin")
    flag_rows = 0
    for case in cases:
        verify_features(case, checks)
        flag_rows += verify_flags(case, checks)
    print(
        json.dumps(
            {  # noqa: T201 - CLI verification summary is the requested output
                "schema_version": "hhhl-ten-events-verification.v1",
                "assertions": checks.count,
                "case_ids": identifiers,
                "checked_local_features": list(LOCAL_FEATURES),
                "flag_rows_checked": flag_rows,
                "flag_ids": list(FLAG_IDS),
                "peer_features_not_checked": ["H", "J", "K3"],
                "hash_evidence": {
                    "manifest_sha256": file_digest(dataset / "manifest.json"),
                    "audit_sha256": file_digest(dataset / names[0]),
                    "audit_digest_sha256": file_digest(dataset / names[1]),
                    "verification_code_sha256": file_digest(Path(__file__)),
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
