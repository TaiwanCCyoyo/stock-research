"""Synthetic immutable cache integration and fail-closed reader checks."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict

import numpy as np
import pandas as pd
import pytest

from research_core import artifact_store, cache_execution, derived_cache
from research_core.derived_features import compute_features
from research_core.price_basis import PriceBasis, prepare_prices
from scripts.verify_research_cache import _recompute_in_process as recompute


class CacheInputs(TypedDict):
    prices: Path
    actions: Path
    calendar: Path
    root: Path
    cutoff: str


@pytest.fixture(autouse=True)
def allow_private_fault_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache_execution, "require_loaded", lambda paths: None)


@pytest.fixture
def inputs(tmp_path: Path) -> CacheInputs:
    dates = pd.date_range("2020-01-01", periods=75)
    close = 100 + 4 * np.sin(np.arange(len(dates)) / 3)
    close[25:] *= 0.5
    close[50:] *= 0.9
    bars = pd.DataFrame({
        "Code": "2330",
        "Date": dates,
        "Open": close,
        "High": close * 1.01,
        "Low": close * 0.99,
        "Close": close,
        "Volume": 10.0,
        "Source": "synthetic",
    })
    # Retain an explicit missing official session in the supplied calendar.
    bars = bars.drop(index=40).reset_index(drop=True)
    events = pd.DataFrame({
        "code": ["2330", "2330"],
        "ex_date": [dates[25], dates[50]],
        "event_type": ["ETF_SPLIT", "CASH_DIVIDEND"],
        "price_factor": [0.5, 0.9],
    })
    prices, actions, calendar = (tmp_path / name for name in ("prices.parquet", "actions.parquet", "calendar.json"))
    bars.to_parquet(prices, index=False)
    events.to_parquet(actions, index=False)
    calendar.write_text(json.dumps({"dates": [day.date().isoformat() for day in dates], "basis": "synthetic explicit sessions"}), encoding="utf-8")
    return {"prices": prices, "actions": actions, "calendar": calendar, "root": tmp_path / "cache", "cutoff": list(dates)[-1].date().isoformat()}


def build(inputs: CacheInputs):
    receipt = derived_cache._build_cache_in_process(**inputs)
    return receipt, Path(receipt["manifest_path"]).parent


def snapshot(directory: Path):
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in directory.rglob("*") if path.is_file()}


@pytest.mark.parametrize("basis", derived_cache.BASES)
def test_outputs_match_direct_price_and_feature_calculation(inputs: CacheInputs, basis: PriceBasis):
    receipt, version = build(inputs)
    calendar = pd.DatetimeIndex(json.loads(inputs["calendar"].read_text(encoding="utf-8"))["dates"])
    prepared = prepare_prices(pd.read_parquet(inputs["prices"]), pd.read_parquet(inputs["actions"]), calendar, basis=basis, cutoff=inputs["cutoff"])
    daily, pivots = compute_features(prepared)
    daily = daily.rename_axis("Date").reset_index()
    daily.insert(0, "Code", "2330")
    pivots.insert(0, "Code", "2330")
    pd.testing.assert_frame_equal(derived_cache.read_cached(version, basis, "2330"), daily)
    pd.testing.assert_frame_equal(derived_cache.read_cached(version, basis, "2330", part="pivots"), pivots)
    assert receipt["computed_symbols"] == 1 and receipt["reused_symbols"] == 0
    assert len(daily) == 75 and not daily.Quality.iloc[40]


def test_full_direct_recalculation_receipt(inputs: CacheInputs):
    first, version = build(inputs)
    receipt = recompute(version)
    assert receipt["complete"] is True
    assert receipt["version_id"] == first["version_id"]
    assert len(receipt["checked"]) == 3
    assert all(row["daily_rows"] == 75 for row in receipt["checked"])


def test_identical_build_reuses_without_changing_source_or_existing_bytes(inputs: CacheInputs):
    sources = {"prices": inputs["prices"], "actions": inputs["actions"], "calendar": inputs["calendar"]}
    source_before = {name: path.read_bytes() for name, path in sources.items()}
    first, version = build(inputs)
    before = snapshot(version)
    second, same_version = build(inputs)
    assert first["version_id"] == second["version_id"] and version == same_version
    assert second["computed_symbols"] == 0 and second["reused_symbols"] == 1
    assert snapshot(version) == before
    assert {name: path.read_bytes() for name, path in sources.items()} == source_before


def test_empty_foreign_version_at_publication_boundary_is_never_replaced(inputs: CacheInputs, monkeypatch: pytest.MonkeyPatch) -> None:
    publisher = derived_cache.publish_noreplace
    competing: list[Path] = []

    def competing_publish(staging: Path, destination: Path) -> None:
        assert not destination.exists()
        assert (staging / "manifest.json").is_file()
        destination.mkdir()
        competing.append(destination)
        publisher(staging, destination)

    monkeypatch.setattr(derived_cache, "publish_noreplace", competing_publish)
    with pytest.raises(FileExistsError):
        build(inputs)
    assert len(competing) == 1
    version = competing[0]
    assert version.is_dir() and list(version.iterdir()) == []
    assert not (version.parent / f".{version.name}.lock").exists()
    stages = list(version.parent.glob(f".staging-{version.name}-*"))
    assert len(stages) == 1
    retained_bytes = snapshot(stages[0])
    assert derived_cache.verify_cache(stages[0], _building=True)["complete"] is True

    monkeypatch.setattr(derived_cache, "publish_noreplace", publisher)
    with pytest.raises(FileNotFoundError):
        build(inputs)
    assert version.is_dir() and list(version.iterdir()) == []
    assert snapshot(stages[0]) == retained_bytes
    assert list(version.parent.glob(f".staging-{version.name}-*")) == stages
    assert not (version.parent / f".{version.name}.lock").exists()


def test_changed_input_creates_version_and_old_reader_stays_pinned(inputs: CacheInputs):
    first, old_version = build(inputs)
    old_bytes = snapshot(old_version)
    old_daily = derived_cache.read_cached(old_version, "raw", "2330")
    bars = pd.read_parquet(inputs["prices"])
    bars.loc[0, "Volume"] = 99.0
    bars.to_parquet(inputs["prices"], index=False)
    second, new_version = build(inputs)
    assert first["version_id"] != second["version_id"]
    assert new_version != old_version and second["computed_symbols"] == 1
    assert snapshot(old_version) == old_bytes
    pd.testing.assert_frame_equal(derived_cache.read_cached(old_version, "raw", "2330"), old_daily)
    assert derived_cache.read_cached(new_version, "raw", "2330").VolumeLots.iloc[0] == 99


@pytest.mark.parametrize("basis,code,part", [("unknown", "2330", "daily"), ("raw", "9999", "daily"), ("raw", "../2330", "daily"), ("raw", "2330", "unknown")])
def test_wrong_selection_rejected(inputs: CacheInputs, basis: str, code: str, part: str):
    _, version = build(inputs)
    with pytest.raises(ValueError):
        derived_cache.read_cached(version, basis, code, part=part)


def test_partial_directory_and_staging_are_never_readable(inputs: CacheInputs):
    _, version = build(inputs)
    partial = version.parent / ("a" * 64)
    partial.mkdir()
    with pytest.raises(FileNotFoundError):
        derived_cache.read_cached(partial, "raw", "2330")
    staging = version.parent / f".staging-{version.name}-synthetic"
    staging.mkdir()
    with pytest.raises(ValueError, match="only published"):
        derived_cache.read_cached(staging, "raw", "2330")


def test_corrupt_artifact_rejects_reader_and_reuse_without_fallback(inputs: CacheInputs):
    _, version = build(inputs)
    artifact = version / "raw/2330/daily.parquet"
    content = artifact.read_bytes()
    artifact.write_bytes(bytes([content[0] ^ 1]) + content[1:])
    corrupted = snapshot(version)
    with pytest.raises(ValueError, match="hash/size mismatch"):
        derived_cache.read_cached(version, "raw", "2330")
    with pytest.raises(ValueError, match="hash/size mismatch"):
        derived_cache._build_cache_in_process(**inputs)
    assert snapshot(version) == corrupted
    assert len(list(version.parent.glob("[0-9a-f]" * 64))) == 1


@pytest.mark.parametrize("tampering", ["missing_output", "duplicate", "traversal", "input_hash", "implementation_hash"])
def test_manifest_inventory_and_identity_reject_tampering(inputs: CacheInputs, tampering: str):
    _, version = build(inputs)
    manifest_path = version / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if tampering == "missing_output":
        manifest["artifacts"] = [entry for entry in manifest["artifacts"] if entry["path"] != "raw/2330/pivots.parquet"]
    elif tampering == "duplicate":
        manifest["artifacts"].append(manifest["artifacts"][0].copy())
    elif tampering == "traversal":
        manifest["artifacts"][0]["path"] = "../prices.parquet"
    else:
        key = "inputs" if tampering == "input_hash" else "implementation"
        name = next(iter(manifest["identity"][key]))
        manifest["identity"][key][name] = "0" * 64
        manifest["version_id"] = artifact_store.object_digest(manifest["identity"])
        renamed = version.parent / manifest["version_id"]
        version.rename(renamed)
        version = renamed
        manifest_path = version / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        derived_cache.read_cached(version, "raw", "2330")


def test_source_and_implementation_hashes_bind_version_and_retained_bytes(inputs: CacheInputs, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    first, original_version = build(inputs)
    manifest = derived_cache.verify_cache(original_version)
    for name, digest in manifest["identity"]["inputs"].items():
        assert artifact_store.file_digest(original_version / "inputs" / name) == digest
    for name, digest in manifest["identity"]["implementation"].items():
        assert artifact_store.file_digest(original_version / "implementation" / name) == digest
    paths = derived_cache._implementation_paths()
    original = paths["derived_features.py"].read_bytes()
    changed = tmp_path / "synthetic-derived-features.py"
    changed.write_bytes(original + b"\n# synthetic formula source version for identity test\n")
    paths["derived_features.py"] = changed
    monkeypatch.setattr(derived_cache, "_implementation_paths", lambda: paths)
    second, new_version = build(inputs)
    assert second["version_id"] != first["version_id"]
    assert (new_version / "implementation/derived_features.py").read_bytes() == changed.read_bytes()
    pd.testing.assert_frame_equal(derived_cache.read_cached(original_version, "raw", "2330"), derived_cache.read_cached(new_version, "raw", "2330"))


@pytest.mark.parametrize("change", ["add", "remove", "rename"])
def test_retained_implementation_inventory_survives_current_source_layout_changes(
    inputs: CacheInputs,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    change: str,
) -> None:
    first, original_version = build(inputs)
    original_bytes = snapshot(original_version)
    original_daily = derived_cache.read_cached(original_version, "raw", "2330")
    paths = derived_cache._implementation_paths().copy()
    if change == "add":
        added = tmp_path / "formula-helper.py"
        added.write_bytes(b"# synthetic added formula source\n")
        paths["formula_helper.py"] = added
    elif change == "remove":
        paths.pop("derived_features.py")
    else:
        paths["renamed_features.py"] = paths.pop("derived_features.py")
    monkeypatch.setattr(derived_cache, "_implementation_paths", lambda: paths)

    assert derived_cache.verify_cache(original_version)["version_id"] == first["version_id"]
    pd.testing.assert_frame_equal(derived_cache.read_cached(original_version, "raw", "2330"), original_daily)
    with pytest.raises(ValueError, match="current implementation differs from pinned cache"):
        recompute(original_version)
    assert snapshot(original_version) == original_bytes

    second, new_version = build(inputs)

    assert second["version_id"] != first["version_id"]
    assert new_version != original_version
    manifest = derived_cache.verify_cache(new_version)
    assert set(manifest["identity"]["implementation"]) == set(paths)
    for name, source in paths.items():
        assert (new_version / "implementation" / name).read_bytes() == source.read_bytes()
    pd.testing.assert_frame_equal(derived_cache.read_cached(new_version, "raw", "2330"), original_daily)
    assert recompute(new_version)["complete"] is True
    assert snapshot(original_version) == original_bytes


@pytest.mark.parametrize("name", ["action_types.py", "derived_cache.py"])
def test_recompute_rejects_changes_to_every_retained_implementation(
    inputs: CacheInputs,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
) -> None:
    first, version = build(inputs)
    original_bytes = snapshot(version)
    original_daily = derived_cache.read_cached(version, "raw", "2330")
    paths = derived_cache._implementation_paths().copy()
    changed = tmp_path / f"changed-{name}"
    changed.write_bytes(paths[name].read_bytes() + b"\n# synthetic changed implementation\n")
    paths[name] = changed
    monkeypatch.setattr(derived_cache, "_implementation_paths", lambda: paths)

    assert derived_cache.verify_cache(version)["version_id"] == first["version_id"]
    pd.testing.assert_frame_equal(derived_cache.read_cached(version, "raw", "2330"), original_daily)
    with pytest.raises(ValueError, match="current implementation differs from pinned cache"):
        recompute(version)
    assert snapshot(version) == original_bytes


@pytest.mark.parametrize("change", ["add", "remove", "rename"])
def test_retained_bases_survive_changes_to_current_formula_bases(
    inputs: CacheInputs,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    first, version = build(inputs)
    original_bytes = snapshot(version)
    sealed_bases = derived_cache.BASES
    frames = {(basis, part): derived_cache.read_cached(version, basis, "2330", part=part) for basis in sealed_bases for part in ("daily", "pivots")}
    current_bases: tuple[str, ...]
    if change == "add":
        current_bases = (*sealed_bases, "future_basis")
    elif change == "remove":
        current_bases = sealed_bases[1:]
    else:
        current_bases = ("future_basis", *sealed_bases[1:])
    monkeypatch.setattr(derived_cache, "BASES", current_bases)

    assert derived_cache.verify_cache(version)["version_id"] == first["version_id"]
    for (basis, part), original in frames.items():
        pd.testing.assert_frame_equal(derived_cache.read_cached(version, basis, "2330", part=part), original)
    with pytest.raises(ValueError, match="unsupported cache selection"):
        derived_cache.read_cached(version, "future_basis", "2330")
    assert snapshot(version) == original_bytes


@pytest.mark.parametrize(
    "bases",
    [
        None,
        [],
        "raw",
        ["raw", "raw"],
        [42],
        [[]],
        [""],
        ["."],
        [".."],
        ["../raw"],
        ["/raw"],
        ["C:/raw"],
        ["raw/nested"],
        ["raw\\nested"],
        ["raw"],
    ],
)
def test_malformed_sealed_bases_rejected_after_identity_rehash(inputs: CacheInputs, bases: Any) -> None:
    _, version = build(inputs)
    manifest = json.loads((version / "manifest.json").read_text(encoding="utf-8"))
    manifest["identity"]["parameters"]["bases"] = bases
    manifest["version_id"] = artifact_store.object_digest(manifest["identity"])
    renamed = version.parent / manifest["version_id"]
    version.rename(renamed)
    (renamed / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="basis|bases"):
        derived_cache.verify_cache(renamed)
    with pytest.raises(ValueError, match="basis|bases"):
        derived_cache.read_cached(renamed, "raw", "2330")


def test_recompute_rechecks_implementation_after_direct_calculation(
    inputs: CacheInputs,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, version = build(inputs)
    original_bytes = snapshot(version)
    paths = derived_cache._implementation_paths().copy()
    changed = tmp_path / "changed-action-types.py"
    changed.write_bytes(paths["action_types.py"].read_bytes() + b"\n# synthetic concurrent implementation change\n")
    monkeypatch.setattr(derived_cache, "_implementation_paths", lambda: paths)
    calls = 0

    def changing_compute_features(prepared: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        nonlocal calls
        frames = compute_features(prepared)
        calls += 1
        if calls == 1:
            paths["action_types.py"] = changed
        return frames

    monkeypatch.setattr(derived_cache.derived_features, "compute_features", changing_compute_features)
    with pytest.raises(ValueError, match="current implementation differs from pinned cache"):
        recompute(version)

    assert calls == len(derived_cache.BASES)
    assert snapshot(version) == original_bytes


@pytest.mark.parametrize(
    "implementation",
    [
        {},
        [],
        {"../outside.py": "0" * 64},
        {"C:/outside.py": "0" * 64},
        {"formula\\outside.py": "0" * 64},
        {"derived_features.py": None},
        {"derived_features.py": 42},
        {"derived_features.py": "not-a-digest"},
    ],
)
def test_invalid_retained_implementation_metadata_rejected_after_identity_rehash(
    inputs: CacheInputs,
    implementation: Any,
) -> None:
    _, version = build(inputs)
    manifest = json.loads((version / "manifest.json").read_text(encoding="utf-8"))
    manifest["identity"]["implementation"] = implementation
    manifest["version_id"] = artifact_store.object_digest(manifest["identity"])
    renamed = version.parent / manifest["version_id"]
    version.rename(renamed)
    (renamed / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError):
        derived_cache.verify_cache(renamed)
    with pytest.raises(ValueError):
        derived_cache.read_cached(renamed, "raw", "2330")


@pytest.mark.parametrize("name", ["../outside", "raw/../outside", "/absolute", "C:/absolute", "raw\\outside", "raw//outside", "raw/./outside"])
def test_portable_artifact_names_reject_traversal(name: str):
    with pytest.raises(ValueError, match="unsafe artifact name"):
        artifact_store.relative_name(name)


def test_mock_windows_reparse_ancestor_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    original_lstat = Path.lstat

    def reparse_lstat(path: Path, *args: Any, **kwargs: Any):
        result = original_lstat(path, *args, **kwargs)
        if path == tmp_path:
            return SimpleNamespace(st_file_attributes=1024, st_mode=result.st_mode)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", reparse_lstat)
        with pytest.raises(ValueError, match="linked/reparse path forbidden"):
            artifact_store.safe_path(tmp_path / "not-created" / "artifact.parquet")
    with pytest.raises(ValueError, match="path traversal forbidden"):
        artifact_store.safe_path(tmp_path / ".." / "outside")
