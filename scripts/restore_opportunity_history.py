"""Copy the frozen opportunity-history web bundle into the shared research_data root.

Hashes the producer bundle first, copies it to a staging directory, re-reads every copied
byte, runs the full `HistoryStore` gate on the copy, publishes it without replacing anything
and registers it in the shared catalog. It never downloads, runs analysis or modifies the
source. A failed run leaves its `.staging-*` directory for inspection.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research_core.opportunity_history_bundle import ORIGINAL_MANIFEST_SHA256, history_data_roots, restore_bundle
from research_core.opportunity_history_store import HistoryStore

LOGGER = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="producer directory containing catalog-v2 and runs/native")
    args = parser.parse_args()
    result = restore_bundle(
        args.source, history_data_roots(), gate=lambda bundle, sha: HistoryStore(bundle, sha), expected_manifest_sha256=ORIGINAL_MANIFEST_SHA256
    )
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
