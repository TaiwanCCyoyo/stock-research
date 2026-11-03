"""Real synthetic filesystem mutations and operation counts, without market IO."""

import hashlib
import json
import logging
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from research_core import artifact_store
from research_core.pattern_scan_recovery_v1 import _Reads


def _file(tmp_path: Path) -> Path:
    path = tmp_path / "observed" / "nested" / "input.bin"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"synthetic saved bytes")
    return path


@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.parametrize("purpose", ["input", "output"])
def test_same_bytes_and_mtime_file_replacement_is_detected(tmp_path: Path, scoped: bool, purpose: str) -> None:
    path = _file(tmp_path)
    reads = _Reads(purpose=purpose)
    reads.observe(path)
    before = path.stat()
    replacement = path.with_name("replacement.bin")
    replacement.write_bytes(path.read_bytes())
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    replacement.replace(path)
    assert path.stat().st_ino != before.st_ino
    assert (path.stat().st_size, path.stat().st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    with pytest.raises(ValueError, match=f"{purpose} changed"):
        reads.unchanged({path} if scoped else None)


@pytest.mark.parametrize("scoped", [False, True])
def test_plain_ancestor_replacement_detected_even_with_original_leaf_inode(tmp_path: Path, scoped: bool) -> None:
    path = _file(tmp_path)
    reads = _Reads()
    reads.observe(path)
    leaf_identity = (path.stat().st_dev, path.stat().st_ino, path.stat().st_size, path.stat().st_mtime_ns)
    original_parent = path.parent
    parked = original_parent.with_name("parked-original-directory")
    original_parent.rename(parked)
    original_parent.mkdir()
    (parked / path.name).rename(path)
    assert (path.stat().st_dev, path.stat().st_ino, path.stat().st_size, path.stat().st_mtime_ns) == leaf_identity
    with pytest.raises(ValueError, match="ancestor changed"):
        reads.unchanged({path} if scoped else None)


def test_directory_mtime_changes_do_not_invalidate_identity(tmp_path: Path) -> None:
    path = _file(tmp_path)
    reads = _Reads()
    reads.observe(path)
    reads.observe_directory(path.parent)
    info = path.parent.stat()
    (path.parent / "unrelated-new-sibling.bin").write_bytes(b"new output")
    os.utime(path.parent, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    reads.unchanged({path, path.parent})


def test_scoped_check_cannot_silently_accept_an_unobserved_path(tmp_path: Path) -> None:
    path = _file(tmp_path)
    reads = _Reads()
    with pytest.raises(ValueError, match="already observed"):
        reads.unchanged({path})


def test_selected_payload_hash_check_detects_same_size_metadata_preserving_edit(tmp_path: Path) -> None:
    path = _file(tmp_path)
    original = path.read_bytes()
    record = {"path": path.name, "bytes": len(original), "sha256": hashlib.sha256(original).hexdigest()}
    reads = _Reads()
    reads.observe(path)
    info = path.stat()
    path.write_bytes(b"X" * len(original))
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    with pytest.raises(ValueError):
        reads.verify(path.parent, [record])


@pytest.mark.skipif(sys.platform != "win32", reason="actual Windows junction regression")
@pytest.mark.parametrize("scoped", [False, True])
def test_windows_junction_replacing_observed_ancestor_preserves_external_target(tmp_path: Path, scoped: bool) -> None:
    path = _file(tmp_path)
    reads = _Reads()
    reads.observe(path)
    outside = tmp_path / "external-target"
    outside.mkdir()
    sentinel = outside / "sentinel.bin"
    sentinel.write_bytes(b"external target must remain unchanged")
    (outside / path.name).write_bytes(path.read_bytes())
    original_parent = path.parent
    original_parent.rename(original_parent.with_name("parked-original-directory"))
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(original_parent), str(outside)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    try:
        with pytest.raises(ValueError, match="reparse|linked"):
            reads.unchanged({path} if scoped else None)
        assert sentinel.read_bytes() == b"external target must remain unchanged"
    finally:
        # Only unlink this test-created junction; never recurse into its target.
        os.rmdir(original_parent)
    assert sentinel.read_bytes() == b"external target must remain unchanged"


@pytest.mark.parametrize("stock_n", [1, 2, 5])
@pytest.mark.parametrize("background_n", [20, 100])
def test_global_observation_cost_stays_fixed_across_stock_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stock_n: int, background_n: int, record_property: Any
) -> None:
    reads = _Reads()
    background = set()
    local_groups = []
    for index in range(background_n):
        path = tmp_path / "global" / f"{index:03}.bin"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"synthetic global observation")
        background.add(path)
    for stock in range(stock_n):
        group = set()
        for index in range(3):
            path = tmp_path / f"stock-{stock}" / f"{index}.bin"
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"synthetic selected observation")
            group.add(path)
        local_groups.append(group)
    local = set().union(*local_groups)
    for path in background | local:
        reads.observe(path)
    original_lstat, original_stat, original_digest = Path.lstat, Path.stat, artifact_store.file_digest
    calls: Counter[str] = Counter()

    def count_lstat(path: Path, *args: Any, **kwargs: Any) -> os.stat_result:
        if path in background:
            calls["global_leaf_lstat"] += 1
        elif path in local:
            calls["selected_leaf_lstat"] += 1
        elif path == tmp_path or path.is_relative_to(tmp_path):
            calls["ancestor_lstat"] += 1
        return original_lstat(path, *args, **kwargs)

    def count_stat(path: Path, *args: Any, **kwargs: Any) -> os.stat_result:
        if path == tmp_path or path.is_relative_to(tmp_path):
            calls["stat"] += 1
        return original_stat(path, *args, **kwargs)

    def count_digest(path: Path) -> str:
        if path in background | local:
            calls["hash"] += 1
        return original_digest(path)

    monkeypatch.setattr(Path, "lstat", count_lstat)
    monkeypatch.setattr(Path, "stat", count_stat)
    monkeypatch.setattr(artifact_store, "file_digest", count_digest)
    # Calibrate the real path-checking stack once. In particular, safe_path and
    # checked_path both inspect the leaf; do not assume one OS call per observe.
    reads.unchanged({next(iter(background))})
    leaf_lstats_per_observation = calls["global_leaf_lstat"]
    assert leaf_lstats_per_observation > 0
    schedules = {}
    for schedule in ("old_global_schedule", "new_scoped_schedule"):
        calls.clear()
        before = dict(reads.metrics)
        observations: Counter[str] = Counter()
        original_observe = reads.observe

        def observe(path: Path) -> None:
            if path in background:
                observations["global_file_observations"] += 1
            elif path in local:
                observations["selected_file_observations"] += 1
            original_observe(path)

        with monkeypatch.context() as scoped_patch:
            scoped_patch.setattr(reads, "observe", observe)
            reads.unchanged()  # inventory closure
            for group in local_groups:
                reads.unchanged(group if schedule == "new_scoped_schedule" else None)
                reads.unchanged(group if schedule == "new_scoped_schedule" else None)
            reads.unchanged()  # before creating output
            reads.unchanged()  # after writing output
        delta = {key: reads.metrics[key] - before[key] for key in before}
        for key in ("global_leaf_lstat", "selected_leaf_lstat", "ancestor_lstat", "stat", "hash"):
            calls.setdefault(key, 0)
        schedules[schedule] = {"calls": dict(calls), "observations": dict(observations), "metric_delta": delta}
    new, old = schedules["new_scoped_schedule"], schedules["old_global_schedule"]
    assert new["metric_delta"]["full_sweeps"] == 3
    assert new["metric_delta"]["scoped_sweeps"] == 2 * stock_n
    assert new["observations"]["global_file_observations"] == 3 * background_n
    assert new["metric_delta"]["file_observations"] == 3 * background_n + 5 * len(local)
    assert old["observations"]["global_file_observations"] == (3 + 2 * stock_n) * background_n
    assert old["metric_delta"]["file_observations"] == (3 + 2 * stock_n) * (background_n + len(local))
    # Independent actual-call counts must agree with the per-observation probe,
    # so the implementation's metrics cannot conceal a global rescan per stock.
    assert new["calls"]["global_leaf_lstat"] == leaf_lstats_per_observation * 3 * background_n
    assert old["calls"]["global_leaf_lstat"] == leaf_lstats_per_observation * (3 + 2 * stock_n) * background_n
    report = {
        "scope": "synthetic filesystem operations only; no market speed inference",
        "comparison": "old versus new call schedule using the same current _Reads checker",
        "measurement_window": "stability gates only; fixture creation, initial observations and payload ingestion excluded",
        "same_checked_path": True,
        "stocks": stock_n,
        "global_only_files": background_n,
        "selected_files": len(local),
        "leaf_lstats_per_observation": leaf_lstats_per_observation,
        **schedules,
    }
    record_property("synthetic_stability_operation_counts", report)
    logging.getLogger(__name__).info("SYNTHETIC_STABILITY_COUNTS %s", json.dumps(report, sort_keys=True))
