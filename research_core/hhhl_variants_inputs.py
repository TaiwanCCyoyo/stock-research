"""Verified, read-only inputs and frozen price/pivot adapter for HHHL variants."""

from __future__ import annotations

import hashlib
import io
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.artifact_store import file_digest, object_digest, read_json, safe_path, verify_files
from research_core.feature_atlas_dataset import load_analysis
from research_core.hhhl_v4_source import OHLC_COLUMNS, RAW_COLUMNS, load_v4_components
from research_core.patterns.hhhl.source import verify_sources

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ("base_eligible", "eligibility_reason", "regime", "industry_ref")


def require_hash(path: Path, expected: str) -> None:
    if file_digest(path) != expected:
        raise ValueError(f"fixed input hash mismatch: {path}")


def calendar_identity(dates: pd.Series | pd.DatetimeIndex) -> dict[str, Any]:
    index = pd.DatetimeIndex(pd.to_datetime(dates))
    if index.hasnans or not index.is_unique or not index.is_monotonic_increasing or index.tz is not None or not index.equals(cast(Any, index).normalize()):
        raise ValueError("invalid common-calendar date vector")
    tokens = index.strftime("%Y-%m-%d").tolist()
    return {"sha256": object_digest(tokens), "rows": len(tokens), "first": tokens[0] if tokens else None, "last": tokens[-1] if tokens else None}


def verify_pins(primary: Path, pins_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Hash verification only; caller has not evaluated new market outcomes."""
    primary = safe_path(primary)
    pins = read_json(pins_path)
    if pins.get("schema_version") != "hhhl-variants-input-pins.v1":
        raise ValueError("unsupported variants input pins")
    bulk = safe_path(Path(pins["v4_bulk"]["path"]))
    atlas = safe_path(Path(pins["atlas"]["path"]))
    factors = safe_path(Path(pins["factor_bundle"]["path"]))
    for path in (bulk, atlas, factors):
        if not path.is_relative_to(primary):
            raise ValueError("input pins must name explicit primary artifacts")
    require_hash(bulk / "manifest.json", pins["v4_bulk"]["manifest_sha256"])
    manifest = read_json(bulk / "manifest.json")
    if not manifest.get("complete") or manifest.get("schema_version") != "hhhl-probability.v4":
        raise ValueError("incomplete or incompatible v4 bulk")
    verify_files(bulk, [dict(entry, path=name) for name, entry in manifest["artifacts"].items()])
    require_hash(atlas / "manifest.json", pins["atlas"]["manifest_sha256"])
    if read_json(atlas / "manifest.json")["dataset_id"] != pins["atlas"]["dataset_id"]:
        raise ValueError("atlas identity mismatch")
    require_hash(factors, pins["factor_bundle"]["sha256"])
    with zipfile.ZipFile(factors) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())) or set(archive.namelist()) != set(pins["factor_bundle"]["members"]):
            raise ValueError("factor bundle member inventory mismatch")
        for name, expected in pins["factor_bundle"]["members"].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError(f"fixed factor member mismatch: {name}")
    require_hash(ROOT / pins["source_registry"]["path"], pins["source_registry"]["sha256"])
    texts = verify_sources("v4")
    if {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in texts.items()} != pins["source_registry"]["verified_members"]:
        raise ValueError("frozen v4 source members differ")
    require_hash(primary / "tasks/20261010-hhhl-v4-probability/sources/hhhl_rule_v4.zip", pins["original_task_source_zip_sha256"])
    for relative, expected in pins["preparation_code_sha256"].items():
        if hashlib.sha256(safe_path(ROOT / relative).read_bytes().replace(b"\r\n", b"\n")).hexdigest() != expected:
            raise ValueError(f"approved preparation code changed: {relative}")
    for relative, key in (("uv.lock", "uv_lock_sha256"), ("pyproject.toml", "pyproject_sha256")):
        require_hash(ROOT / relative, pins["environment"][key])
    LOG.info("Fixed variants input hashes verified: bulk=%d", len(manifest["artifacts"]))
    return pins, manifest


@dataclass
class StockInput:
    ordinal: int
    code: str
    security_id: str
    raw: pd.DataFrame
    adjusted: pd.DataFrame
    context: pd.DataFrame
    events: pd.DataFrame
    control_indices: np.ndarray
    low_pivots: list[tuple[int, int, float]]
    legacy_vx: np.ndarray
    legacy_liquid: np.ndarray


class FrozenInputs:
    """Keep raw prices in memory; never call the source detector or live I/O."""

    def __init__(self, primary: Path, pins_path: Path) -> None:
        self.primary, self.pins_path = safe_path(primary), safe_path(pins_path)
        self.pins, self.manifest = verify_pins(self.primary, self.pins_path)
        self.bulk = Path(self.pins["v4_bulk"]["path"])
        self.atlas = Path(self.pins["atlas"]["path"])
        self.tables = sorted(read_json(self.atlas / "manifest.json")["tables"], key=lambda entry: entry["security_id"])
        if len({entry["security_id"].split(":", 1)[1] for entry in self.tables}) != len(self.tables):
            raise ValueError("original code cannot route multiple securities in this fixed study")
        self.data = load_analysis(self.atlas, columns=[*CONTEXT, *RAW_COLUMNS], verify_hashes=True)
        self.groups = self.data.groupby("security_id", sort=False).indices
        self.events = pd.read_parquet(self.bulk / "events.parquet")
        self.events = self.events.loc[self.events["base_eligible"].eq(True) & self.events["pattern"].eq(True)].copy()
        if self.events["event_id"].duplicated().any():
            raise ValueError("duplicate original P event identities")
        self.controls = pd.read_parquet(self.bulk / "controls.parquet", columns=["security_id", "asof_date", "base_eligible", "control_no_event"])
        self.controls = self.controls.loc[self.controls["base_eligible"].eq(True) & self.controls["control_no_event"].eq(True)].copy()
        self.event_groups = self.events.groupby("security_id", sort=False).indices
        self.control_groups = self.controls.groupby("security_id", sort=False).indices
        with zipfile.ZipFile(Path(self.pins["factor_bundle"]["path"])) as archive:
            self.actions = pd.read_parquet(io.BytesIO(archive.read("corporate_action_factors.parquet")))
        # This public adapter captures the frozen source. The first returned
        # detector callable is intentionally discarded and never invoked.
        _, self.pivots, self.pivot_k, self.prepare = load_v4_components(verify_sources("v4"))
        if self.pivot_k != 1.5:
            raise ValueError("frozen pivot threshold differs from mission")

    def stock(self, ordinal: int) -> StockInput:
        entry = self.tables[ordinal - 1]
        security = entry["security_id"]
        code = security.split(":", 1)[1]
        frame = self.data.iloc[self.groups[security]].sort_values("asof_date").reset_index(drop=True)
        identity = calendar_identity(frame["asof_date"])
        if any(identity[key] != self.pins["calendar"][key] for key in identity):
            raise ValueError(f"common calendar differs: {security}")
        n = len(frame)
        raw = (
            frame
            .loc[:, list(RAW_COLUMNS)]
            .rename(columns={"asof_date": "Date", "RawOpen": "Open", "RawHigh": "High", "RawLow": "Low", "RawClose": "Close"})
            .copy()
        )
        adjusted = pd.DataFrame({"Date": raw["Date"], **{name: np.full(n, np.nan) for name in ("Open", "High", "Low", "Close")}})
        vx, liquid = np.full(n, np.nan), np.zeros(n, dtype=bool)
        low_pivots: list[tuple[int, int, float]] = []
        if frame.loc[:, list(OHLC_COLUMNS)].notna().all(axis=1).any():
            bars = self.prepare(frame, self.actions, code, self.pins["calendar"]["last"])
            positions = pd.DatetimeIndex(raw["Date"]).get_indexer(pd.to_datetime(bars["asof_date"]))
            if (positions < 0).any() or len(np.unique(positions)) != len(positions):
                raise ValueError("frozen valid-row mapping differs")
            adjusted.loc[positions, ["Open", "High", "Low", "Close"]] = bars.loc[:, ["Open", "High", "Low", "Close"]].to_numpy(float)
            volume = bars["VolumeLots"].astype(float)
            mean_volume = volume.shift(1).rolling(20, min_periods=1).mean()
            vx[positions] = np.where(mean_volume > 0, volume / mean_volume, np.nan)
            turnover = bars["RawClose"].astype(float) * volume
            liquid[positions] = turnover.shift(1).rolling(20, min_periods=20).mean().ge(1000).to_numpy()
            highs, lows = self.pivots(
                bars["High"].to_numpy(float),
                bars["Low"].to_numpy(float),
                bars["Close"].to_numpy(float),
                (bars["atr14_pct"] * bars["Close"]).to_numpy(float),
                k=1.5,
            )
            low_pivots = [(int(positions[extreme]), int(positions[confirmed]), float(price)) for extreme, confirmed, price in lows]
        original = pd.read_parquet(self.bulk / f"baseline/{ordinal:04}.parquet", columns=["security_id", "asof_date", "adjusted_close"])
        if (
            not cast(pd.Series, original["security_id"]).eq(security).to_numpy(dtype=bool).all()
            or calendar_identity(cast(pd.Series, original["asof_date"])) != identity
        ):
            raise ValueError("original baseline routing differs")
        if not np.array_equal(original["adjusted_close"].to_numpy(float), adjusted["Close"].to_numpy(float), equal_nan=True):
            raise ValueError(f"restored v4 close differs from original baseline: {code}")
        events = self.events.iloc[self.event_groups.get(security, [])].copy()
        if len(events):
            event_positions = events["calendar_index"].to_numpy(int)
            if not np.allclose(events["vx"].to_numpy(float), vx[event_positions], rtol=1e-12, atol=1e-12, equal_nan=True):
                raise ValueError("legacy volume ratio differs from original events")
        controls = self.controls.iloc[self.control_groups.get(security, [])]
        control_indices = pd.DatetimeIndex(raw["Date"]).get_indexer(controls["asof_date"])
        if (control_indices < 0).any():
            raise ValueError("original C-nh dates outside common calendar")
        return StockInput(ordinal, code, security, raw, adjusted, frame.loc[:, ["asof_date", *CONTEXT]].copy(), events, control_indices, low_pivots, vx, liquid)

    def verify_after(self) -> None:
        verify_pins(self.primary, self.pins_path)
        # Full atlas reader additionally verifies hashes and one-to-one keys.
        from research_core.feature_atlas_dataset import verify_dataset

        verify_dataset(self.atlas)
