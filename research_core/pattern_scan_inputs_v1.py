"""Fixed physical input handoff and full-calendar pattern-scan reader.

Acquisition belongs to the producer. This reader has no live-data fallback and
preserves reference metadata limitations and excluded securities in inventory.
"""

from __future__ import annotations

import gzip
import json
import logging
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.artifact_store import copy_verified, file_digest, object_digest, publish_noreplace, read_json, relative_name, safe_path, write_json
from research_core.feature_atlas_io import security_inventory
from research_core.price_basis import prepare_prices
from research_core.research_data_paths import DataRoots

LOGGER = logging.getLogger(__name__)
TASK = "20261013-pattern-scan"
ROLES = ("price_daily.parquet", "corporate_actions.sqlite", "symbol_meta.sqlite", "stock_symbol_mapping.json5", "value_chain_classification.json")
PRICE_COLUMNS = ("Code", "Date", "Open", "High", "Low", "Close", "Volume", "Source")


def read_preparation_pins(path: Path) -> dict[str, Any]:
    pins = json.loads(gzip.decompress(safe_path(path).read_bytes()))
    if not isinstance(pins, dict) or pins.get("cutoff") != "2026-10-12":
        raise ValueError("approved preparation pins required")
    return pins


def _descriptors(pins: dict[str, Any]) -> list[dict[str, Any]]:
    records = pins["frozen_inputs"]["records"]
    if not isinstance(records, list) or sorted(record["role"] for record in records) != sorted(ROLES):
        raise ValueError("exactly five fixed snapshot roles required")
    for record in records:
        if relative_name(record["snapshot_path"]) != f"tasks/{TASK}/inputs/observed-v1/{record['role']}":
            raise ValueError("snapshot path differs from approved bundle")
        digest = record["snapshot_sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid snapshot digest")
        size = record["snapshot_bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise ValueError("invalid snapshot size")
    return records


def _verify(path: Path, record: dict[str, Any]) -> None:
    safe_path(path)
    if path.stat().st_nlink != 1:
        raise ValueError(f"physical snapshot must not be hardlinked: {path}")
    if path.stat().st_size != record["snapshot_bytes"] or file_digest(path) != record["snapshot_sha256"]:
        raise ValueError(f"fixed snapshot changed: {record['role']}")
    if path.suffix == ".sqlite" and any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError(f"frozen SQLite sidecar forbidden: {path}")


def handoff_inputs(roots: DataRoots, source_checkout: Path, pins_path: Path) -> Path:
    """Verified physical mutable-input snapshot handoff, never shared-store links.

    Existing canonical bytes may be reused only with the exact same manifest.
    No replacement, cleanup, source mutation or producer reads are performed.
    """
    pins = read_preparation_pins(pins_path)
    records = _descriptors(pins)
    destination = roots.artifact_path("primary", f"tasks/{TASK}/inputs/observed-v1")
    manifest = {
        "schema": "pattern-scan-input-bundle.v1",
        "cutoff": pins["cutoff"],
        "preparation_pins_sha256": file_digest(pins_path),
        "calendar": pins["price_observation"]["calendar"],
        "records": records,
        "source_kind": "previously frozen physical snapshots",
        "historical_PIT_certified": False,
    }
    if destination.exists():
        if read_json(destination / "manifest.json") != manifest:
            raise ValueError("existing canonical snapshot identity mismatch")
        for record in records:
            _verify(roots.artifact_path("primary", f"tasks/{TASK}/inputs/observed-v1/{record['role']}"), record)
        LOGGER.info("Reused fixed canonical input bundle %s", destination)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = roots.artifact_path("primary", f"tasks/{TASK}/inputs/.staging-observed-v1-{uuid.uuid4().hex}")
    staging.mkdir()
    for record in records:
        source = safe_path(source_checkout / record["snapshot_path"])
        _verify(source, record)
        target = staging / record["role"]
        copy_verified(source, target, record["snapshot_sha256"])
        _verify(target, record)
    write_json(staging / "manifest.json", manifest)
    publish_noreplace(staging, destination)
    LOGGER.info("Handed off %d verified physical snapshots to %s", len(records), destination)
    return destination


@dataclass(frozen=True)
class ScanSnapshot:
    roots: DataRoots
    bundle: Path
    manifest_sha256: str
    calendar: pd.DatetimeIndex
    prices: pd.DataFrame
    actions: pd.DataFrame
    inventory: pd.DataFrame
    input_id: str

    @cached_property
    def price_positions(self) -> dict[str, Any]:
        """Index once without duplicating the fixed quote table per stock."""
        return {str(code): positions for code, positions in self.prices.groupby("Code", sort=False).indices.items()}

    def stock(self, code: str) -> pd.DataFrame:
        """Only supplied official quotes, padded gaps and fixed action restatement."""
        if code != "0050" and not ((self.inventory["code"] == code) & self.inventory["included"]).any():
            raise ValueError("security outside fixed ordinary-reference universe")
        raw = self.prices.iloc[self.price_positions.get(code, np.array([], dtype=np.int64))].copy()
        if raw.empty:
            raise ValueError(f"no official prices for fixed security: {code}")
        actions = self.actions.loc[self.actions["code"].eq(code)]
        return prepare_prices(raw, actions, self.calendar, basis="reference_factor_adjusted", cutoff=cast(pd.Timestamp, self.calendar[-1]))

    def verify_after(self) -> None:
        current = read_json(self.bundle / "manifest.json")
        if file_digest(self.bundle / "manifest.json") != self.manifest_sha256:
            raise ValueError("input manifest changed during execution")
        for record in current["records"]:
            _verify(self.roots.artifact_path("primary", f"tasks/{TASK}/inputs/observed-v1/{record['role']}"), record)


def load_snapshot(roots: DataRoots, *, manifest_sha256: str) -> ScanSnapshot:
    """Read one pinned primary bundle; official/source exclusion is explicit."""
    bundle = roots.artifact_path("primary", f"tasks/{TASK}/inputs/observed-v1")
    manifest_path = bundle / "manifest.json"
    if file_digest(manifest_path) != manifest_sha256:
        raise ValueError("fixed input manifest identity mismatch")
    manifest = read_json(manifest_path)
    if manifest.get("schema") != "pattern-scan-input-bundle.v1" or manifest.get("cutoff") != "2026-10-12":
        raise ValueError("approved fixed input bundle required")
    records = _descriptors({"frozen_inputs": {"records": manifest["records"]}})
    paths = {record["role"]: roots.artifact_path("primary", f"tasks/{TASK}/inputs/observed-v1/{record['role']}") for record in records}
    for record in records:
        _verify(paths[record["role"]], record)
    dates = manifest["calendar"]["dates"]
    if object_digest(dates) != manifest["calendar"]["sha256"]:
        raise ValueError("fixed common calendar identity mismatch")
    calendar = pd.DatetimeIndex(pd.to_datetime(dates))
    if (
        calendar.hasnans
        or calendar.tz is not None
        or not calendar.is_unique
        or not calendar.is_monotonic_increasing
        or any(day != day.normalize() for day in calendar)
    ):
        raise ValueError("fixed calendar requires unique sorted naive daily dates")
    prices = pd.read_parquet(paths["price_daily.parquet"], columns=list(PRICE_COLUMNS), filters=[("Date", ">=", calendar[0]), ("Date", "<=", calendar[-1])])
    if not bool(prices["Code"].map(lambda value: isinstance(value, str) and bool(value.strip())).all()):
        raise ValueError("raw code identity must retain its string bytes")
    observed_dates = pd.DatetimeIndex(prices["Date"])
    if (
        observed_dates.hasnans
        or observed_dates.tz is not None
        or any(day != day.normalize() for day in observed_dates)
        or not observed_dates.isin(calendar).all()
    ):
        raise ValueError("raw dates differ from fixed common daily calendar")
    official = prices["Source"].eq("official")
    official_prices = prices.loc[official].copy()
    with closing(sqlite3.connect(paths["symbol_meta.sqlite"].as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("metadata snapshot quick_check failed")
        meta = pd.read_sql_query("SELECT * FROM symbol_meta ORDER BY code", connection)
    with closing(sqlite3.connect(paths["corporate_actions.sqlite"].as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("action snapshot quick_check failed")
        actions = pd.read_sql_query("SELECT * FROM corporate_actions WHERE ex_date <= ? ORDER BY code, ex_date", connection, params=[dates[-1]])
    if (
        meta["code"].duplicated().any()
        or not bool(meta["code"].map(lambda value: isinstance(value, str)).all())
        or not bool(actions["code"].map(lambda value: isinstance(value, str)).all())
    ):
        raise ValueError("fixed metadata/action code identities invalid")
    inventory = pd.DataFrame(security_inventory(official_prices, meta))
    snapshot = ScanSnapshot(
        roots,
        bundle,
        manifest_sha256,
        calendar,
        official_prices,
        actions,
        inventory,
        object_digest({"manifest": manifest_sha256, "price_basis": "price-basis.v2/reference_factor_adjusted"}),
    )
    snapshot.verify_after()
    LOGGER.info(
        "Read fixed scan bundle official_rows=%d excluded_source_rows=%d ordinary=%d calendar=%d",
        len(official_prices),
        int((~official).sum()),
        int(inventory["included"].sum()),
        len(calendar),
    )
    return snapshot


def daily_qualification(prepared: pd.DataFrame, *, ordinary_reference: bool) -> pd.DataFrame:
    """Approved S6 daily universe; current metadata is not historical membership."""
    required = {"Quality", "VolumeLots", "RawClose"}
    if not required.issubset(prepared) or not isinstance(ordinary_reference, bool):
        raise ValueError("prepared fixed prices and explicit ordinary reference required")
    volume = prepared["VolumeLots"].astype(float)
    raw_close = prepared["RawClose"].astype(float)
    quality = prepared["Quality"].eq(True)
    valid60 = cast(pd.Series, quality.rolling(60, min_periods=60).sum()).eq(60)
    turnover = (raw_close * volume).where(np.isfinite(raw_close) & raw_close.gt(0) & np.isfinite(volume) & volume.ge(0))
    prior20 = turnover.rolling(20, min_periods=20).mean().shift(1)
    reasons = pd.Series("", index=prepared.index, dtype=object)
    for mask, reason in (
        (pd.Series(not ordinary_reference, index=prepared.index), "not_ordinary_reference"),
        (~valid60, "insufficient_continuous_valid60"),
        (~(np.isfinite(volume) & volume.gt(0)), "current_volume_not_positive_known"),
        (~np.isfinite(prior20), "prior20_turnover_unknown"),
        (prior20.lt(1000), "prior20_turnover_below_1000_thousand_twd"),
    ):
        reasons.loc[mask] = reasons.loc[mask].map(lambda old: f"{old}|{reason}" if old else reason)
    return pd.DataFrame(
        {"base_eligible": reasons.eq(""), "eligibility_reason": reasons.where(reasons.ne(""), None), "prior20_raw_turnover_thousand_twd": prior20},
        index=prepared.index,
    )
