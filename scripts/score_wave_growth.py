"""Score retrospective wave records with the shared growth-duration rule."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research_core.wave_growth import YEAR_DAYS, classify_growth, wave_gain

EVALUATION_SCHEMA = "wave-growth-evaluation.v1"
RULE_ID = "wave-growth-display.v1"


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        records = payload["rows"]
    else:
        raise ValueError("input must be a list of records or an object containing rows")
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("every input row must be a JSON object")
    return records


def evaluate(records: list[dict[str, Any]], threshold_pct: float = 100) -> dict[str, Any]:
    # Validate even when there are no records to pass through the classifier.
    classify_growth({"basis": "unknown", "sizingGainPct": None}, threshold_pct)
    rows = []
    for record in records:
        metric = wave_gain(
            record.get("start"),
            record.get("date"),
            record.get("gain"),
            record.get("leftCensored") is True,
        )
        rows.append({"input": record, "growth": metric, "eligibility": classify_growth(metric, threshold_pct)})
    return {
        "schema": EVALUATION_SCHEMA,
        "rule": {"id": RULE_ID, "yearDays": YEAR_DAYS, "thresholdPct": threshold_pct},
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSON file containing records or a rows wrapper")
    parser.add_argument("--threshold", type=float, default=100, help="inclusive eligibility threshold in percentage points")
    args = parser.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = evaluate(_records(payload), args.threshold)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
