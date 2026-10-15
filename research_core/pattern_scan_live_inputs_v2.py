"""Live read-only pattern-scan inputs with the approved fixed study calendar.

Fingerprints describe the full live sources; study rows retain the approved
cutoff. Historical snapshot readers and their physical evidence are untouched.
"""

from __future__ import annotations

import logging
from contextlib import closing
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.artifact_store import object_digest
from research_core.feature_atlas_io import security_inventory
from research_core.live_producer import read_stable, readonly_sqlite
from research_core.pattern_scan_inputs_v1 import PRICE_COLUMNS, read_preparation_pins
from research_core.price_basis import DEFINITION_VERSION, prepare_prices
from research_core.producer_data import producer_data_root
from research_core.research_data_paths import DataRoots
from research_core.research_measurement_v1 import phase_receipt, resource_sample
from research_core.run_receipt import InputSpec, assert_inputs_unchanged, fingerprint_inputs

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveScanInputs:
    roots: DataRoots
    calendar: pd.DatetimeIndex
    prices: pd.DataFrame
    actions: pd.DataFrame
    inventory: pd.DataFrame
    input_id: str
    fingerprint: dict[str, Any]
    consumption_measurements: tuple[dict[str, Any], ...] = ()

    @cached_property
    def price_positions(self) -> dict[str, Any]:
        """Index once without duplicating the quote table per stock."""
        return {str(code): positions for code, positions in self.prices.groupby("Code", sort=False).indices.items()}

    def stock(self, code: str) -> pd.DataFrame:
        """Apply the existing price policy to one official security."""
        if code != "0050" and not ((self.inventory["code"] == code) & self.inventory["included"]).any():
            raise ValueError("security outside fixed ordinary-reference universe")
        raw = self.prices.iloc[self.price_positions.get(code, np.array([], dtype=np.int64))].copy()
        if raw.empty:
            raise ValueError(f"no official prices for fixed security: {code}")
        return prepare_prices(
            raw,
            self.actions.loc[self.actions["code"].eq(code)],
            self.calendar,
            basis="reference_factor_adjusted",
            cutoff=cast(pd.Timestamp, self.calendar[-1]),
        )

    def verify_after(self) -> None:
        """Reject producer changes since the pre-read fingerprint."""
        assert_inputs_unchanged(self.fingerprint)
        LOGGER.info("Verified live scan inputs input_id=%s", self.input_id)


def _calendar(pins_path: Path) -> tuple[pd.DatetimeIndex, list[str]]:
    pins = read_stable(pins_path, read_preparation_pins)
    approved = pins["price_observation"]["calendar"]
    dates = approved["dates"]
    if object_digest(dates) != approved["sha256"]:
        raise ValueError("fixed common calendar identity mismatch")
    calendar = pd.DatetimeIndex(pd.to_datetime(dates))
    if (
        calendar.empty
        or calendar.hasnans
        or calendar.tz is not None
        or not calendar.is_unique
        or not calendar.is_monotonic_increasing
        or any(day != day.normalize() for day in calendar)
        or dates[0] != "2010-01-04"
        or dates[-1] != pins["cutoff"]
    ):
        raise ValueError("fixed calendar requires approved unique sorted naive daily dates")
    return calendar, dates


def _database_frame(path: Path, query: str, *, params: tuple[str, ...] = ()) -> pd.DataFrame:
    with closing(readonly_sqlite(path)) as connection:
        connection.execute("BEGIN")
        frame = pd.read_sql_query(query, connection, params=list(params))
        connection.execute("COMMIT")
    return frame


def load_live_inputs(roots: DataRoots, *, pins_path: Path) -> LiveScanInputs:
    """Fingerprint three live sources before reading; never copy producer inputs."""
    calendar, dates = _calendar(pins_path)
    root = producer_data_root()
    LOGGER.info("Reading live scan inputs root=%s cutoff=%s", root, dates[-1])
    started = resource_sample()
    fingerprint = fingerprint_inputs([
        InputSpec("price_daily", root / "price_daily.parquet", date_column="Date"),
        InputSpec("symbol_meta", root / "symbol_meta.sqlite", tables={"symbol_meta": None}),
        InputSpec("corporate_actions", root / "corporate_actions.sqlite", tables={"corporate_actions": "ex_date"}),
    ])
    measurements = [phase_receipt("live_input_fingerprint", started, resource_sample())]
    before = resource_sample()
    prices = read_stable(
        root / "price_daily.parquet",
        lambda path: pd.read_parquet(path, columns=list(PRICE_COLUMNS), filters=[("Date", ">=", calendar[0]), ("Date", "<=", calendar[-1])]),
    )
    measurements.append({**phase_receipt("parquet_read_and_decode", before, resource_sample()), "role": "price_daily.parquet"})
    if not bool(prices["Code"].map(lambda value: isinstance(value, str) and bool(value.strip())).all()):
        raise ValueError("raw code identity must retain its string bytes")
    observed = pd.DatetimeIndex(prices["Date"])
    if observed.hasnans or observed.tz is not None or any(day != day.normalize() for day in observed) or not observed.isin(calendar).all():
        raise ValueError("raw dates differ from fixed common daily calendar")
    official = prices["Source"].eq("official")
    official_prices = prices.loc[official].copy()
    frames = []
    for role, query, params in (
        ("symbol_meta.sqlite", "SELECT * FROM symbol_meta ORDER BY code", ()),
        ("corporate_actions.sqlite", "SELECT * FROM corporate_actions WHERE ex_date <= ? ORDER BY code, ex_date", (dates[-1],)),
    ):
        before = resource_sample()
        frames.append(_database_frame(root / role, query, params=params))
        measurements.append({**phase_receipt("sqlite_read_and_decode", before, resource_sample()), "role": role})
    meta, actions = frames
    if (
        meta["code"].duplicated().any()
        or not bool(meta["code"].map(lambda value: isinstance(value, str)).all())
        or not bool(actions["code"].map(lambda value: isinstance(value, str)).all())
    ):
        raise ValueError("fixed metadata/action code identities invalid")
    inventory = pd.DataFrame(security_inventory(official_prices, meta))
    identity = object_digest({
        "fingerprint": {key: value for key, value in fingerprint.items() if key != "captured_at_utc"},
        "calendar": dates,
        "cutoff": dates[-1],
        "price_basis": f"{DEFINITION_VERSION}/reference_factor_adjusted",
    })
    inputs = LiveScanInputs(roots, calendar, official_prices, actions, inventory, identity, fingerprint, tuple(measurements))
    inputs.verify_after()
    LOGGER.info(
        "Read live scan input_id=%s official_rows=%d excluded_source_rows=%d ordinary=%d calendar=%d",
        identity,
        len(official_prices),
        int((~official).sum()),
        int(inventory["included"].sum()),
        len(calendar),
    )
    return inputs
