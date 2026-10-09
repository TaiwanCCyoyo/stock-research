"""Publish immutable portable aggregates from an existing frozen atlas dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research_core.feature_atlas_publication import publish_feature_atlas  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bulk-location", action="append", default=[])
    args = parser.parse_args()
    result = publish_feature_atlas(args.dataset, args.output, args.bulk_location)
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
