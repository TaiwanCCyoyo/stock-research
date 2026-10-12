"""Exact logical parity on invented bundles and fail-closed daily caches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core.artifact_store import describe_file, file_digest
from research_core.hhhl_variants_continue_pipeline_v1 import run_cached_study
from research_core.hhhl_variants_daily import calculate_daily_features
from research_core.hhhl_variants_run import compact, run_study
from scripts.tests.test_hhhl_variants_run import InventedBundle


def build_cache(inputs: InventedBundle, root: Path) -> list[dict[str, Any]]:
    (root / "daily").mkdir(parents=True)
    descriptors = []
    for ordinal in range(1, len(inputs.tables) + 1):
        stock = inputs.stock(ordinal)
        daily = calculate_daily_features(stock.raw, stock.adjusted, stock.legacy_vx, stock.legacy_liquid)
        path = root / f"daily/{ordinal:04}.parquet"
        compact(daily).to_parquet(path, index=False)
        descriptor = describe_file(root, path)
        descriptor.update(rows=len(daily), code=stock.code)
        descriptors.append(descriptor)
    return descriptors


def test_cached_continuation_matches_entire_original_pipeline(tmp_path: Path) -> None:
    inputs = InventedBundle()
    original, continued, cache = (tmp_path / name for name in ("original", "continued", "cache"))
    original.mkdir()
    continued.mkdir()
    descriptors = build_cache(inputs, cache)
    expected, expected_selection = run_study(inputs, original)
    actual, actual_selection = run_cached_study(inputs, continued, cache, descriptors)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert actual_selection == expected_selection
    original_files = {path.relative_to(original).as_posix() for path in original.rglob("*") if path.is_file()}
    continued_files = {path.relative_to(continued).as_posix() for path in continued.rglob("*") if path.is_file()}
    assert original_files == continued_files
    for name in sorted(original_files):
        if name.endswith(".parquet"):
            pd.testing.assert_frame_equal(pd.read_parquet(continued / name), pd.read_parquet(original / name), check_exact=True)
        else:
            assert json.loads((continued / name).read_text(encoding="utf-8")) == json.loads((original / name).read_text(encoding="utf-8"))
    for descriptor in descriptors:
        assert file_digest(continued / descriptor["path"]) == descriptor["sha256"]
        assert file_digest(cache / descriptor["path"]) == descriptor["sha256"]


@pytest.mark.parametrize("defect", ["missing", "duplicate", "extra", "hash", "bytes", "code", "rows", "invalid_rows"])
def test_cached_continuation_rejects_incomplete_or_changed_cache(tmp_path: Path, defect: str) -> None:
    inputs = InventedBundle()
    cache = tmp_path / "cache"
    descriptors = build_cache(inputs, cache)
    original_hashes = {descriptor["path"]: descriptor["sha256"] for descriptor in descriptors}
    destination = tmp_path / "continued"
    destination.mkdir()
    if defect == "missing":
        descriptors.pop()
    elif defect == "duplicate":
        descriptors[1] = descriptors[0].copy()
    elif defect == "extra":
        descriptors.append(dict(descriptors[0], path="daily/0003.parquet"))
    elif defect == "hash":
        descriptors[0]["sha256"] = "0" * 64
    elif defect == "bytes":
        descriptors[0]["bytes"] += 1
    elif defect == "code":
        descriptors[0]["code"] = "unrelated-code"
    elif defect == "rows":
        descriptors[0]["rows"] += 1
    elif defect == "invalid_rows":
        descriptors[0]["rows"] = True
    with pytest.raises(ValueError, match="cache|artifact"):
        run_cached_study(inputs, destination, cache, descriptors)
    # No pre-existing daily cache bytes are ever replaced by continuation.
    for relative, expected in original_hashes.items():
        assert file_digest(cache / relative) == expected
