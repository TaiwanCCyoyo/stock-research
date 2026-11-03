"""Assess an explicitly supplied JSON packet; emit no card, order or file."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import NoReturn

from research_core.order_card_freshness_json_v1 import read_and_assess_packet

LOGGER = logging.getLogger(__name__)


class _InputParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(1, f"{self.prog}: {message}\n")


def main(argv: list[str] | None = None) -> int:
    parser = _InputParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="explicit order-card-freshness.v1 JSON packet")
    args = parser.parse_args(argv)
    try:
        result = read_and_assess_packet(args.input)
        encoded = json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False)
    except (OSError, ValueError, TypeError, OverflowError) as error:
        LOGGER.error("Invalid freshness input: %s", error)
        return 1
    sys.stdout.write(encoded + "\n")
    return 0 if result["freshness_ready"] else 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    raise SystemExit(main())
