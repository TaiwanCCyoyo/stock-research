"""Verify and inspect saved 0050 descriptors; never calculate performance."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_core.market_context_artifact import LAYERS, load_context_rows, read_dataset  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--verify", action="store_true", help="verify all hashes and semantic contracts (also done on every read)")
    parser.add_argument("--recompute", action="store_true", help="require matching producer and compare recomputed rows")
    parser.add_argument("--layer", choices=sorted(LAYERS))
    parser.add_argument("--date")
    args = parser.parse_args()
    if args.date and not args.layer:
        parser.error("--date requires --layer")
    result = read_dataset(args.dataset, recompute=args.recompute)
    if args.layer:
        result["rows"] = load_context_rows(args.dataset, layer=args.layer, date=args.date)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
