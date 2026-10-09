"""Validate frozen HH/HL example parity without reading forward outcomes."""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core.hhhl_rule_source import FrozenRule, load_rule
from research_core.jobs import confined, file_digest

LOGGER = logging.getLogger(__name__)
COLUMNS = ["asof_date", "Open", "High", "Low", "Close", "VolumeLots", "atr14_pct", "base_eligible"]
OHLC = ["Open", "High", "Low", "Close"]


def dated_events(frame: pd.DataFrame, rule: FrozenRule) -> list[dict[str, Any]]:
    """Apply original OHLC drop/reset semantics and map to the full calendar."""
    dates = pd.to_datetime(frame["asof_date"])
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("asof_date must be unique, present and ascending")
    valid = cast(pd.Series, frame[OHLC].notna().all(axis=1))
    positions = [i for i, keep in enumerate(valid) if keep]
    detector_frame = frame.loc[valid, COLUMNS].reset_index(drop=True)
    return [
        {**event, "date": dates.iloc[positions[event["t"]]].strftime("%Y-%m-%d"), "calendar_index": positions[event["t"]]}
        for event in rule.detect(detector_frame)
    ]


def validate(dataset: Path, sources: Path, cases_path: Path, rule_id: str = "hhhl_rule_v1") -> dict[str, Any]:
    rule = load_rule(sources, rule_id)
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    entries = {entry["security_id"].split(":")[-1]: entry for entry in manifest["tables"]}
    required = {case["code"] for group in ("rule_events", "review_events") for case in cases[group]}
    events: dict[str, dict[str, dict[str, Any]]] = {}
    consumed = []
    for code in sorted(required):
        if code not in entries:
            raise ValueError(f"case security absent from manifest: {code}")
        entry = entries[code]
        path = confined(dataset, entry["path"])
        digest = file_digest(path)
        if digest != entry["sha256"]:
            raise ValueError(f"SHA256 mismatch: {entry['path']}")
        frame = pd.read_parquet(path, columns=COLUMNS)
        if len(frame) != entry["rows"]:
            raise ValueError(f"row count mismatch: {entry['path']}")
        detected = dated_events(frame, rule)
        events[code] = {event["date"]: event for event in detected}
        consumed.append({"code": code, "path": entry["path"], "sha256": digest})
        LOGGER.info("Verified security=%s rows=%d events=%d", code, len(frame), len(detected))
    rule_results = []
    for case in cases["rule_events"]:
        event = events[case["code"]].get(case["date"])
        rule_results.append({**case, "found": event is not None, "pattern": bool(event["pattern"]) if event else None})
    review_results = []
    split: Counter[str] = Counter()
    for case in cases["review_events"]:
        event = events[case["code"]].get(case["date"])
        kind = ("pattern" if event["pattern"] else "inside") if event else "missing"
        if event and not event["pattern"] and event["context"] != "inside_big_range":
            raise ValueError("non-pattern event lacks inside_big_range context")
        split[f"{kind}_{case['owner_verdict']}"] += 1
        review_results.append({**case, "kind": kind})
    pattern = sum(row["kind"] == "pattern" for row in review_results)
    inside = sum(row["kind"] == "inside" for row in review_results)
    expected_split = cases["expected_owner_split"]
    checks = {
        "rule_events_exact24": len(rule_results) == 24 and all(row["found"] and row["pattern"] for row in rule_results),
        "review_events_exact30": len(review_results) == 30 and all(row["kind"] != "missing" for row in review_results),
        "review_pattern": pattern == cases["expected_pattern"] == 20,
        "review_inside": inside == cases["expected_inside"] == 10,
        "owner_split": dict(split) == expected_split == {"pattern_yes": 14, "pattern_no": 6, "inside_yes": 2, "inside_no": 8},
    }
    return {
        "passed": all(checks.values()),
        "rule_id": rule_id,
        "dataset_id": manifest["dataset_id"],
        "source_hashes": rule.source_hashes,
        "consumed_tables": consumed,
        "checks": checks,
        "rule_events": rule_results,
        "review_events": review_results,
        "review_counts": {"pattern": pattern, "inside": inside},
        "owner_split": dict(split),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--rule-id", default="hhhl_rule_v1")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    try:
        report = validate(args.dataset, args.sources, args.cases, args.rule_id)
    except (OSError, ValueError, KeyError) as exc:
        LOGGER.error("Source parity validation failed: %s", exc)
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False))  # noqa: T201 - CLI JSON
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))  # noqa: T201 - CLI JSON
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
