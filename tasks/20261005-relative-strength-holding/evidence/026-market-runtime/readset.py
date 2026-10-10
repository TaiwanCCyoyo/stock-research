"""Bind existing price, membership and factor artifacts; never run a strategy."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
TASKS = Path(__file__).resolve().parents[1]
FACTOR_ROOT = TASKS / "025-signal-factor-inputs"
if str(FACTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(FACTOR_ROOT))

from model import POLICY_ID as TIMING_POLICY_ID  # noqa: E402
from model import ModeledAdjustment, model_adjustments  # noqa: E402

PRICE_HASHES = {
    "twse-official": "a494202f244986070b128396108afe830f4307d6779aca10ff33bbe9dc57196a",  # pragma: allowlist secret - artifact checksum
    "tpex-official": "2a4d3c5e8d17f3daf8538556a25c27c581da2389a53ae3dee8e953b94eb875a8",  # pragma: allowlist secret - artifact checksum
    "twse-recovered": "4c2d7844546bf70aa15f76932b8d8d859814d00af1ad71fae9cd627f43730f4d",  # pragma: allowlist secret - artifact checksum
}
MEMBERSHIP_HASH = "9356d2148252d92918cc0967e06aa97ffe2f251a6f098bb7279d9d9666d09062"  # pragma: allowlist secret - artifact checksum
FACTOR_HASH = "aa1dfabe51795ad5264e2839b725a56e3c681f106c5ab06b8e5333b2f44b8dab"  # pragma: allowlist secret - artifact checksum
FACTOR_MODEL_HASH = "f2ebe2d2d9bb079c03846fbadba1e7307bff62bd9b53b6b5542bd3f20bfafa66"  # pragma: allowlist secret - artifact checksum
BAR_TIME_POLICY = "development-raw-close-effective-evening-v1"
KEYS = ["market", "code", "date"]
PRICES = ["open", "high", "low", "close", "volume"]


class ReadsetError(ValueError):
    """Fixed evidence identity or binding changed."""


@dataclass(frozen=True)
class MarketReadset:
    raw: pd.DataFrame
    universe: dict[date, frozenset[str]]
    market_by_day: dict[date, dict[str, str]]
    modeled_adjustments: tuple[ModeledAdjustment, ...]
    input_identities: dict[str, str]
    timing_basis: str = BAR_TIME_POLICY


def checked(path: Path, expected: str) -> bytes:
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != expected:
        raise ReadsetError(f"input identity drift: {path}")
    return body


def bind_observations(parts: list[tuple[pd.DataFrame, str]], membership: pd.DataFrame, *, bar_time_policy: str) -> tuple[pd.DataFrame, dict, dict]:
    """Exact source keys; modeled availability is separate from observed unknowns."""
    if bar_time_policy != BAR_TIME_POLICY or not parts:
        raise ReadsetError("explicit daily-data availability policy required")
    frames = []
    for frame, source_id in parts:
        if not source_id or not set(KEYS + PRICES).issubset(frame):
            raise ReadsetError("missing raw identity or fields")
        copied = frame[KEYS + PRICES].copy()
        copied["price_source_id"] = source_id
        frames.append(copied)
    raw = pd.concat(frames, ignore_index=True)
    if raw.empty or raw[KEYS].isna().any().any() or raw.duplicated(KEYS).any() or raw.duplicated(["code", "date"]).any():
        raise ReadsetError("empty, missing or overlapping source keys")
    required = {*KEYS, "include_for_scoring", "historical_available_at", "source_id"}
    if not required.issubset(membership) or membership[KEYS].isna().any().any() or membership.duplicated(KEYS).any():
        raise ReadsetError("missing or duplicate membership binding")
    identity = membership[list(required)].rename(columns={"source_id": "membership_source_id", "historical_available_at": "membership_historical_available_at"})
    joined = raw.merge(identity, on=KEYS, how="outer", validate="one_to_one", indicator=True)
    if not joined["_merge"].eq("both").all() or not joined["include_for_scoring"].map(lambda value: type(value) is bool).all():
        raise ReadsetError("price and membership keys or inclusion flags disagree")
    if not joined["market"].isin(["TWSE", "TPEx"]).all():
        raise ReadsetError("unexpected source market")
    dates = pd.to_datetime(joined["date"], format="%Y-%m-%d", errors="raise")
    if (dates < "2018-01-01").any() or (dates > "2023-12-31").any():
        raise ReadsetError("outside development/warm-up period")
    joined["Date"] = dates
    joined["Market"] = joined["market"].replace({"TPEx": "TPEX"})
    joined["Code"] = joined["code"]
    for source, target in zip(PRICES, ("Open", "High", "Low", "Close", "Volume"), strict=True):
        joined[target] = joined[source]
    joined["available_at"] = dates.dt.tz_localize("Asia/Taipei") + pd.Timedelta(hours=18)
    joined["historical_available_at"] = None
    joined["source_id"] = joined["price_source_id"] + "|" + bar_time_policy + ":assumed"
    universe = {}
    routes = {}
    for day, group in joined.groupby("Date", sort=True):
        local_day = day.date()
        universe[local_day] = frozenset(group.loc[group["include_for_scoring"], "Code"])
        routes[local_day] = dict(zip(group["Code"], group["Market"], strict=True))
    columns = ["Market", "Code", "Date", "Open", "High", "Low", "Close", "Volume", "available_at", "historical_available_at", "source_id"]
    return joined[columns].sort_values(["Code", "Date"]).reset_index(drop=True), universe, routes


def load_market_readset(*, bar_time_policy: str, factor_time_policy: str) -> MarketReadset:
    """Read fixed byte identities only. Factor coverage is intentionally not created."""
    from io import BytesIO

    identities = {}
    parts = []
    for name, digest in PRICE_HASHES.items():
        path = TASKS / "009-source-assembly" / "price-readset" / name / "prices.parquet"
        parts.append((pd.read_parquet(BytesIO(checked(path, digest)), columns=KEYS + PRICES), f"{name}:{digest}"))
        identities[str(path)] = digest
    membership_path = TASKS / "022-daily-membership" / "projected-v2" / "observed-identities.parquet"
    membership = pd.read_parquet(BytesIO(checked(membership_path, MEMBERSHIP_HASH)))
    identities[str(membership_path)] = MEMBERSHIP_HASH
    factor_path = FACTOR_ROOT / "signal-factor-readset-v1.json"
    factor_payload = json.loads(checked(factor_path, FACTOR_HASH))
    identities[str(factor_path)] = FACTOR_HASH
    checked(FACTOR_ROOT / "model.py", FACTOR_MODEL_HASH)
    identities[str(FACTOR_ROOT / "model.py")] = FACTOR_MODEL_HASH
    modeled = model_adjustments(factor_payload["records"], policy_id=factor_time_policy)
    raw, universe, routes = bind_observations(parts, membership, bar_time_policy=bar_time_policy)
    return MarketReadset(raw, universe, routes, modeled, identities)


def summary(readset: MarketReadset) -> dict[str, Any]:
    return {
        "status": "source_binding_complete_not_strategy_execution",
        "rows": len(readset.raw),
        "dates": len(readset.universe),
        "codes": readset.raw["Code"].nunique(),
        "missing_ohlc_rows": int(readset.raw[["Open", "High", "Low", "Close"]].isna().any(axis=1).sum()),
        "included_identity_keys": sum(len(values) for values in readset.universe.values()),
        "factor_records": len(readset.modeled_adjustments),
        "coverage_created": False,
        "bar_time_policy": BAR_TIME_POLICY,
        "factor_time_policy": TIMING_POLICY_ID,
        "input_identities": readset.input_identities,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.parent != Path(__file__).resolve().parent or output.exists():
        raise ReadsetError("fresh output must be inside this batch folder")
    bound = load_market_readset(bar_time_policy=BAR_TIME_POLICY, factor_time_policy=TIMING_POLICY_ID)
    report = summary(bound)
    report["reader_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["python_version"] = sys.version
    report["python_executable"] = sys.executable
    report["root_uv_lock_sha256"] = hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
