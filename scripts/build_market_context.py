"""Build the preregistered immutable 0050 context package."""

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_core.market_context_artifact import build_dataset  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    manifest = build_dataset(args.source_manifest, args.expected_source_sha256, args.output)
    sys.stdout.write(json.dumps({"dataset_id": manifest["dataset_id"], "summary": manifest["summary"]}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
