"""Recalculate every published cache output from its retained inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core import cache_execution, derived_cache, derived_features, price_basis
from research_core.artifact_store import file_digest, safe_path, write_json


def _require_current_implementation(manifest: dict[str, Any]) -> None:
    current = {name: file_digest(path) for name, path in derived_cache._implementation_paths().items()}
    if current != manifest["identity"]["implementation"]:
        raise ValueError("current implementation differs from pinned cache")
    cache_execution.require_loaded(derived_cache._implementation_paths())
    cache_execution.require_loaded({"verify_research_cache.py": Path(__file__)})


def recompute(version: Path) -> dict[str, Any]:
    """Compute in a fresh source-bound worker, independent of stale caller imports."""
    return cache_execution.execute("recompute", {"version": str(version.absolute())})


def _recompute_in_process(version: Path) -> dict[str, Any]:
    manifest = derived_cache.verify_cache(version)
    _require_current_implementation(manifest)
    raw = pd.read_parquet(version / "inputs/prices.parquet")
    events = pd.read_parquet(version / "inputs/actions.parquet")
    calendar = derived_cache._calendar(version / "inputs/calendar.json")
    checked = []
    for code in manifest["codes"]:
        for basis in derived_cache.BASES:
            prepared = price_basis.prepare_prices(
                raw.loc[raw["Code"].astype(str).eq(code)],
                events,
                calendar,
                basis=cast(price_basis.PriceBasis, basis),
                cutoff=manifest["identity"]["parameters"]["cutoff"],
            )
            daily, pivots = derived_features.compute_features(prepared)
            daily = daily.rename_axis("Date").reset_index()
            daily.insert(0, "Code", code)
            pivots.insert(0, "Code", code)
            for part, direct in (("daily", daily), ("pivots", pivots)):
                cached = pd.read_parquet(version / basis / code / f"{part}.parquet")
                pd.testing.assert_frame_equal(cached, direct, check_exact=True)
            checked.append({"code": code, "basis": basis, "daily_rows": len(daily), "pivots": len(pivots)})
    derived_cache.verify_cache(version)
    _require_current_implementation(manifest)
    return {
        "schema": "stock-cache-direct-parity.v1",
        "complete": True,
        "version_id": manifest["version_id"],
        "manifest_sha256": file_digest(version / "manifest.json"),
        "verifier_sha256": file_digest(Path(__file__)),
        "checked": checked,
        "comparison": "all columns, dtypes, row order and exact values; NaN masks included",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    version, output = safe_path(args.version), safe_path(args.output)
    receipt = recompute(version)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, receipt)
    print(json.dumps({"output": str(output), "complete": receipt["complete"], "symbol_basis_pairs": len(receipt["checked"])}))  # noqa: T201 - CLI receipt
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
