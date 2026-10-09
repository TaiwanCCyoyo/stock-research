"""Query saved feature comparisons or recompute them from verified sample rows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research_core.evidence import read_json  # noqa: E402
from research_core.feature_atlas_dataset import FEATURE_COLUMNS, load_analysis, verify_dataset  # noqa: E402
from research_core.feature_atlas_outcomes import binary_comparison  # noqa: E402
from research_core.jobs import confined, file_digest  # noqa: E402


def comparison_rows(dataset: Path) -> list[dict[str, Any]]:
    """Check the comparison artifact against its explicit dataset manifest."""
    manifest = read_json(dataset / "manifest.json")
    entry = next(item for item in manifest["artifacts"] if item["path"] == "comparisons.json")
    path = confined(dataset, entry["path"])
    if file_digest(path) != entry["sha256"]:
        raise ValueError("comparison hash mismatch")
    result = read_json(path)
    if result["dataset_id"] != manifest["dataset_id"]:
        raise ValueError("comparison dataset mismatch")
    return result["comparisons"]


def recompute(dataset: Path) -> dict[str, Any]:
    """Validate every file, then independently read stored samples and aggregate."""
    frame = load_analysis(dataset)
    expected = comparison_rows(dataset)
    actual: list[dict[str, Any]] = []
    for panel, selected in (("daily", frame), ("grid126", frame.loc[frame["calendar_index"].mod(126).eq(0)])):
        actual.extend({"panel": panel, **row} for row in binary_comparison(selected, FEATURE_COLUMNS, ["year", "regime", "industry_ref"]))

    def canonical(rows: list[dict[str, Any]]) -> list[str]:
        return sorted(json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False) for row in rows)

    if canonical(actual) != canonical(expected):
        raise ValueError("stored comparisons differ from recomputed sample evidence")
    return {
        "status": "all_hashes_and_comparisons_verified",
        "sample_rows": len(frame),
        "comparisons": len(actual),
        "daily_comparisons": sum(row["panel"] == "daily" for row in actual),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--recompute", action="store_true")
    parser.add_argument("--feature", choices=FEATURE_COLUMNS)
    parser.add_argument("--panel", choices=["daily", "grid126"], default="daily")
    parser.add_argument("--context", choices=["pooled", "year", "regime", "industry_ref"], default="pooled")
    args = parser.parse_args()
    if args.recompute:
        result: Any = recompute(args.dataset)
    elif args.verify:
        result = verify_dataset(args.dataset)
    else:
        result = [
            row
            for row in comparison_rows(args.dataset)
            if row["panel"] == args.panel
            and (args.feature is None or row["feature"] == args.feature)
            and row["context_column"] == (None if args.context == "pooled" else args.context)
        ]
    sys.stdout.write(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
