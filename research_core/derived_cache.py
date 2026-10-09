"""On-demand immutable Stock price/feature versions; no live producer writes."""

from __future__ import annotations

import logging
import platform
import re
import time
import uuid
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow

from research_core import artifact_store, cache_execution, derived_features, price_basis
from research_core.artifact_store import (
    copy_verified,
    describe_file,
    file_digest,
    object_digest,
    publish_noreplace,
    read_json,
    relative_name,
    safe_path,
    verify_files,
    write_json,
)
from StockProject.engine import data_loader

LOGGER = logging.getLogger(__name__)
SCHEMA = "stock-derived-cache.v1"
BASES = ("raw", "permanent_adjusted", "reference_factor_adjusted")
DIGEST = re.compile(r"[0-9a-f]{64}")
CODE = re.compile(r"[A-Za-z0-9_-]+")


def _implementation_paths() -> dict[str, Path]:
    return {
        "derived_cache.py": Path(__file__),
        "price_basis.py": Path(price_basis.__file__),
        "derived_features.py": Path(derived_features.__file__),
        "action_types.py": Path(data_loader.__file__),
        "cache_execution.py": Path(cache_execution.__file__),
        "artifact_store.py": Path(artifact_store.__file__),
    }


def _identity(sources: dict[str, Path], cutoff: str, codes: list[str] | None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "inputs": {name: file_digest(path) for name, path in sources.items()},
        "implementation": {name: file_digest(path) for name, path in _implementation_paths().items()},
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "pyarrow": pyarrow.__version__},
        "parameters": {"cutoff": cutoff, "codes": codes, "bases": list(BASES)},
        "definitions": {"prices": price_basis.DEFINITION_VERSION, "features": derived_features.definition_metadata()},
        "availability": "ex_date cutoff is not PIT publication certification; confirmed pivots available at confirmed_at",
    }


def _identity_hashes(identity: dict[str, Any], field: str) -> dict[str, str]:
    """Validate a version's sealed inventory independently of installed code."""
    hashes = identity.get(field)
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError(f"nonempty retained {field} identity required")
    for name, digest in hashes.items():
        if not isinstance(name, str) or not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ValueError(f"invalid retained {field} descriptor")
        relative_name(name)
    return cast(dict[str, str], hashes)


def _sealed_bases(identity: dict[str, Any]) -> list[str]:
    """Use only this version's portable, unique basis directory names."""
    parameters = identity.get("parameters")
    bases = parameters.get("bases") if isinstance(parameters, dict) else None
    if not isinstance(bases, list) or not bases or any(not isinstance(basis, str) for basis in bases) or len(set(bases)) != len(bases):
        raise ValueError("retained cache basis inventory invalid")
    for basis in bases:
        if "/" in basis:
            raise ValueError("retained cache basis name invalid")
        try:
            relative_name(basis)
        except ValueError as error:
            raise ValueError("retained cache basis name invalid") from error
    return cast(list[str], bases)


def verify_cache(version: Path, *, _building: bool = False) -> dict[str, Any]:
    """Read-only verification, including all retained inputs and output bytes."""
    version = safe_path(version)
    manifest = read_json(version / "manifest.json")
    identity = manifest.get("identity")
    if manifest.get("schema") != SCHEMA or manifest.get("complete") is not True or not isinstance(identity, dict):
        raise ValueError("incomplete or unsupported cache")
    version_id = object_digest(identity)
    if not DIGEST.fullmatch(version_id) or manifest.get("version_id") != version_id:
        raise ValueError("cache identity mismatch")
    if identity.get("schema") != SCHEMA:
        raise ValueError("unsupported retained cache schema")
    inputs = _identity_hashes(identity, "inputs")
    implementation = _identity_hashes(identity, "implementation")
    bases = _sealed_bases(identity)
    if set(inputs) != {"prices.parquet", "actions.parquet", "calendar.json"}:
        raise ValueError("retained input inventory does not match cache schema")
    # Staging is used only by the builder; public readers require a named version.
    if version.name != version_id and not (_building and version.name.startswith(f".staging-{version_id}-")):
        raise ValueError("cache directory/version mismatch")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("cache artifact inventory required")
    verify_files(version, artifacts)
    by_name = {entry["path"]: entry for entry in artifacts}
    for name, digest in inputs.items():
        if by_name.get(f"inputs/{name}", {}).get("sha256") != digest:
            raise ValueError("retained input identity mismatch")
    for name, digest in implementation.items():
        if by_name.get(f"implementation/{name}", {}).get("sha256") != digest:
            raise ValueError("retained formula identity mismatch")
    codes = manifest.get("codes")
    if (
        not isinstance(codes, list)
        or not codes
        or len(set(codes)) != len(codes)
        or any(not isinstance(code, str) or not CODE.fullmatch(code) for code in codes)
    ):
        raise ValueError("cache symbol inventory invalid")
    required = {f"{basis}/{code}/{part}.parquet" for basis in bases for code in codes for part in ("daily", "pivots")}
    required |= {f"inputs/{name}" for name in inputs}
    required |= {f"implementation/{name}" for name in implementation}
    if set(by_name) != required:
        raise ValueError("cache inventory does not cover all bases/symbols/inputs")
    LOGGER.debug("Verified cache %s sealed bases=%s", version_id, bases)
    return manifest


def read_cached(version: Path, basis: str, code: str, *, part: str = "daily") -> pd.DataFrame:
    """Use an explicit pinned version; there is no mutable latest alias."""
    if part not in {"daily", "pivots"} or not CODE.fullmatch(code):
        raise ValueError("unsupported cache selection")
    version = safe_path(version)
    if not DIGEST.fullmatch(version.name):
        raise ValueError("only published versions are readable")
    manifest = verify_cache(version)
    if basis not in _sealed_bases(manifest["identity"]):
        raise ValueError("unsupported cache selection")
    if code not in manifest["codes"]:
        raise ValueError("symbol is outside this cache version")
    return pd.read_parquet(safe_path(version / basis / code / f"{part}.parquet"))


def _calendar(path: Path) -> pd.DatetimeIndex:
    document = read_json(path)
    dates = document.get("dates")
    if not isinstance(dates, list) or not dates or not isinstance(document.get("basis"), str) or not document["basis"]:
        raise ValueError("explicit nonempty calendar dates and basis required")
    calendar = pd.DatetimeIndex(pd.to_datetime(dates))
    if (
        calendar.tz is not None
        or calendar.hasnans
        or not calendar.is_unique
        or not calendar.is_monotonic_increasing
        or any(day != day.normalize() for day in calendar)
    ):
        raise ValueError("calendar must be sorted unique naive daily dates")
    return calendar


def build_cache(*, prices: Path, actions: Path, calendar: Path, root: Path, cutoff: str, codes: list[str] | None = None) -> dict[str, Any]:
    """Build/reuse in a fresh source-bound interpreter, never caller's stale code."""
    return cache_execution.execute(
        "build",
        {
            "prices": str(prices.absolute()),
            "actions": str(actions.absolute()),
            "calendar": str(calendar.absolute()),
            "root": str(root.absolute()),
            "cutoff": cutoff,
            "codes": codes,
        },
    )


def _build_cache_in_process(*, prices: Path, actions: Path, calendar: Path, root: Path, cutoff: str, codes: list[str] | None = None) -> dict[str, Any]:
    """Create a new version or verify identical reuse; never overwrite a version."""
    started = time.monotonic()
    sources = {"prices.parquet": safe_path(prices), "actions.parquet": safe_path(actions), "calendar.json": safe_path(calendar)}
    selected = sorted(set(codes)) if codes is not None else None
    if selected is not None and (not selected or any(not CODE.fullmatch(code) for code in selected)):
        raise ValueError("invalid requested codes")
    cutoff_day = pd.Timestamp(cutoff)
    if not isinstance(cutoff_day, pd.Timestamp) or cutoff_day.tzinfo is not None or cutoff_day != cutoff_day.normalize():
        raise ValueError("cutoff must be a naive daily date")
    cutoff = cutoff_day.date().isoformat()
    identity = _identity(sources, cutoff, selected)
    cache_execution.require_loaded(_implementation_paths())
    version_id = object_digest(identity)
    family = safe_path(root) / "price-bases"
    version = family / version_id
    if version.exists():
        manifest = verify_cache(version)
        LOGGER.info("Reused cache %s with %d symbols", version_id, len(manifest["codes"]))
        return {
            "version_id": version_id,
            "manifest_path": str(version / "manifest.json"),
            "computed_symbols": 0,
            "reused_symbols": len(manifest["codes"]),
            "elapsed_seconds": time.monotonic() - started,
        }
    family.mkdir(parents=True, exist_ok=True)
    lock = safe_path(family / f".{version_id}.lock")
    with lock.open("x", encoding="utf-8"):
        pass
    staging = safe_path(family / f".staging-{version_id}-{uuid.uuid4().hex}")
    try:
        staging.mkdir()
        for name, source in sources.items():
            copy_verified(source, staging / "inputs" / name, identity["inputs"][name])
        for name, source in _implementation_paths().items():
            copy_verified(source, staging / "implementation" / name, identity["implementation"][name])
        bars = pd.read_parquet(staging / "inputs/prices.parquet")
        events = pd.read_parquet(staging / "inputs/actions.parquet")
        dates = _calendar(staging / "inputs/calendar.json")
        if "Code" not in bars or bars.empty or bool(bars["Code"].isna().any()):
            raise ValueError("nonempty price symbols required")
        bars["Code"] = bars["Code"].astype(str)
        available = sorted(bars["Code"].unique().tolist())
        selected = selected if selected is not None else available
        if set(selected) - set(available) or any(not CODE.fullmatch(code) for code in selected):
            raise ValueError("requested symbols absent or unsafe")
        paths = [staging / "inputs" / name for name in sources]
        paths.extend(staging / "implementation" / name for name in _implementation_paths())
        coverage: list[dict[str, Any]] = []
        for code in selected:
            raw = bars.loc[bars["Code"].eq(code)]
            for basis in BASES:
                prepared = price_basis.prepare_prices(raw, events, dates, basis=cast(price_basis.PriceBasis, basis), cutoff=cutoff)
                daily, pivots = derived_features.compute_features(prepared)
                daily = daily.rename_axis("Date").reset_index()
                daily.insert(0, "Code", code)
                pivots.insert(0, "Code", code)
                directory = safe_path(staging / basis / code)
                directory.mkdir(parents=True)
                daily_path, pivot_path = directory / "daily.parquet", directory / "pivots.parquet"
                daily.to_parquet(daily_path, index=False)
                pivots.to_parquet(pivot_path, index=False)
                paths.extend((daily_path, pivot_path))
                coverage.append({
                    "code": code,
                    "basis": basis,
                    "rows": len(daily),
                    "valid_rows": int(daily["Quality"].sum()),
                    "atr14_missing": int(daily["ATR14"].isna().sum()),
                    "pivots": len(pivots),
                    "quality_reasons": {str(key): int(value) for key, value in daily["quality_reason"].dropna().value_counts().items()},
                })
        if any(file_digest(source) != identity["inputs"][name] for name, source in sources.items()):
            raise ValueError("input changed during build; incomplete staging retained")
        if any(file_digest(source) != identity["implementation"][name] for name, source in _implementation_paths().items()):
            raise ValueError("implementation changed during build; incomplete staging retained")
        cache_execution.require_loaded(_implementation_paths())
        manifest = {
            "schema": SCHEMA,
            "complete": True,
            "version_id": version_id,
            "identity": identity,
            "codes": selected,
            "calendar_basis": read_json(staging / "inputs/calendar.json")["basis"],
            "coverage": coverage,
            "artifacts": [describe_file(staging, path) for path in paths],
            "elapsed_seconds": time.monotonic() - started,
        }
        write_json(staging / "manifest.json", manifest)
        verify_cache(staging, _building=True)
        # All builders for this digest must acquire the exclusive same lock.
        if version.exists():
            raise ValueError("immutable version appeared concurrently")
        publish_noreplace(staging, version)
        LOGGER.info("Published cache %s symbols=%d bytes=%d", version_id, len(selected), sum(entry["bytes"] for entry in manifest["artifacts"]))
        return {
            "version_id": version_id,
            "manifest_path": str(version / "manifest.json"),
            "computed_symbols": len(selected),
            "reused_symbols": 0,
            "bytes": sum(entry["bytes"] for entry in manifest["artifacts"]),
            "elapsed_seconds": time.monotonic() - started,
        }
    finally:
        # Only the lock exclusively created by this invocation is removed.
        lock.unlink()
