"""Read and verify portable saved comparisons; bulk samples are not supplied."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research_core.feature_atlas_publication import query_comparisons, verify_publication  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--feature")
    parser.add_argument("--panel", choices=["daily", "grid126"], default="daily")
    parser.add_argument("--context", choices=["pooled", "year", "regime", "industry_ref"], default="pooled")
    args = parser.parse_args()
    result = verify_publication(args.publication) if args.verify else query_comparisons(args.publication, args.feature, args.panel, args.context)
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
