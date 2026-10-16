"""Project completed PR17 values into a local, noncanonical feature preview.

This adapter neither calculates features nor updates any shared family. Original
numerical lineage is retained separately from the projection executor.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_series_equal

from research_core.artifact_store import describe_file, file_digest, object_digest, publish_noreplace, read_json, verify_files, write_json
from research_core.pattern_scan_parquet_v1 import read_frame, write_frame
from research_core.research_data_paths import checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample
from research_core.run_receipt import InputSpec, fingerprint_inputs, write_run_receipt

LOGGER = logging.getLogger(__name__)
DEFINITION = "pattern-scan-local-feature-projection.v1"
PRICE_COLUMNS = (
    "Open",
    "High",
    "Low",
    "Close",
    "RawOpen",
    "RawHigh",
    "RawLow",
    "RawClose",
    "VolumeLots",
    "Turnover",
    "corporate_action_types",
    "restatement_factor",
    "Volume",
    "BBUpper",
    "BBLower",
)
INDICATOR_COLUMNS = (
    "Quality",
    "quality_reason",
    "volume_status",
    "ATR14",
    "atr14_pct",
    "SMA5",
    "SMA10",
    "SMA20",
    "SMA60",
    "SMA120",
    "EMA5",
    "EMA10",
    "EMA20",
    "EMA60",
    "BB20_Middle",
    "BB20_Upper",
    "BB20_Lower",
    "SMA240",
    "RSI14",
    "ADX14",
    "MACDHist",
    "BBWidth",
    "F10",
    "F32",
    "F22",
    "F23",
    "F24",
    "F25",
    "F33",
    "security_id",
    "calendar_index",
    "asof_date",
)
INDICATOR_INPUT_COLUMNS = (*PRICE_COLUMNS, *INDICATOR_COLUMNS)
PIVOT_COLUMNS = (
    "k",
    "kind",
    "extreme_index",
    "confirmation_index",
    "extreme_date",
    "confirmed_at",
    "price",
    "security_id",
    "asof_date",
)
COMMON_COLUMNS = (
    "C",
    "C2",
    "C3",
    "C4",
    "D",
    "D2",
    "F",
    "G",
    "G2_limit",
    "G2_position",
    "K",
    "K2",
    "ret120",
    "prior_volume20",
    "turnover20",
    "ma20",
    "ma60",
    "atr_pct",
    "C_unknown_reason",
    "C2_unknown_reason",
    "C3_unknown_reason",
    "D_unknown_reason",
    "D2_unknown_reason",
    "F_unknown_reason",
    "K_unknown_reason",
    "C4_unknown_reason",
    "G_unknown_reason",
    "K2_unknown_reason",
    "G2_limit_unknown_reason",
    "G2_position_unknown_reason",
    "quality_reason",
    "MA_a",
    "MA_b",
    "BB_a",
    "BB_b",
    "BB_c",
    "SR_a",
    "SR_b",
    "SR_a_unknown_reason",
    "SR_b_unknown_reason",
    "SR_c",
    "KL_a",
    "KL_b",
    "KL_c",
    "RSI",
    "MACD",
    "ADX",
    "VOL_a",
    "security_id",
    "t0",
    "calendar_index",
    "industry_ref",
    "base_eligible",
    "is_cnh",
)
TABLES = {"daily_indicators": "indicators.parquet", "confirmed_pivots": "pivots.parquet", "daily_conditions": "common_values.parquet"}


def _columns(frame: pd.DataFrame, expected: tuple[str, ...]) -> None:
    if not frame.columns.is_unique or set(frame.columns) != set(expected):
        raise ValueError("feature preview requires the exact declared PR17 column set")


def project_frames(indicators: pd.DataFrame, pivots: pd.DataFrame, common: pd.DataFrame, *, code: str) -> dict[str, pd.DataFrame]:
    """Keep existing values exactly, with causal pivot availability and no prices.

    Price columns and verified Bollinger aliases are omitted from daily indicators.
    Pivot prices are essential derived extrema, not a duplicated daily-price table.
    Definition-specific common conditions remain named as such, without promoting
    their historical industry reference or eligibility metadata to PIT observations.
    """
    for frame, columns in ((indicators, INDICATOR_INPUT_COLUMNS), (pivots, PIVOT_COLUMNS), (common, COMMON_COLUMNS)):
        _columns(frame, columns)
        if not cast(pd.Series, frame["security_id"]).eq(f"TW:{code}").all():
            raise ValueError("feature preview security_id differs from its stock")
    calendar = indicators.index
    if (
        not isinstance(calendar, pd.DatetimeIndex)
        or calendar.empty
        or calendar.hasnans
        or not calendar.is_unique
        or not calendar.is_monotonic_increasing
        or not calendar.equals(common.index)
    ):
        raise ValueError("feature preview requires identical nonempty ordered daily calendars")
    for frame in (indicators, common):
        if not np.array_equal(frame["calendar_index"].to_numpy(), np.arange(len(calendar))):
            raise ValueError("feature preview calendar_index differs from daily positions")
    if not pd.DatetimeIndex(common["t0"]).equals(calendar):
        raise ValueError("feature preview t0 differs from daily dates")
    if not pd.DatetimeIndex(indicators["asof_date"]).equals(calendar) or not pd.DatetimeIndex(pivots["asof_date"]).equals(
        pd.DatetimeIndex(pivots["confirmed_at"])
    ):
        raise ValueError("feature preview asof_date differs from its row availability date")
    for alias, canonical in (("BBUpper", "BB20_Upper"), ("BBLower", "BB20_Lower")):
        try:
            assert_series_equal(indicators[alias], indicators[canonical], check_names=False, check_exact=True)
        except AssertionError as error:
            raise ValueError("feature preview Bollinger aliases differ") from error
    for position, date in (("extreme_index", "extreme_date"), ("confirmation_index", "confirmed_at")):
        values = cast(pd.Series, pivots[position])
        if values.isna().any() or not values.between(0, len(calendar) - 1).all() or not values.eq(values.astype(int)).all():
            raise ValueError("feature preview pivot calendar positions are invalid")
        if not pd.DatetimeIndex(pivots[date]).equals(calendar.take(values.astype(int))):
            raise ValueError("feature preview pivot dates differ from calendar positions")
    if (
        not cast(pd.Series, pivots["extreme_index"]).le(pivots["confirmation_index"]).all()
        or not cast(pd.Series, pivots["k"]).isin([1.5, 4.0]).all()
        or not cast(pd.Series, pivots["kind"]).isin(["high", "low"]).all()
    ):
        raise ValueError("feature preview pivot confirmation/definition is invalid")
    if not np.isfinite(pivots["price"]).all() or not cast(pd.Series, pivots["price"]).gt(0).all():
        raise ValueError("feature preview requires finite positive pivot prices")
    return {
        "daily_indicators": indicators.loc[:, list(INDICATOR_COLUMNS)].copy(deep=True),
        "confirmed_pivots": pivots.copy(deep=True),
        "daily_conditions": common.copy(deep=True),
    }


def _stamp(path: Path) -> tuple[int, int]:
    info = checked_path(path).stat()
    return info.st_size, info.st_mtime_ns


def _source_parts(stock_result: Path, preparation: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result = read_json(stock_result, max_bytes=128_000_000)
    prepared = read_json(preparation, max_bytes=128_000_000)
    pool = result["pool"]
    rows = pool["results"]
    codes = [row["code"] for row in rows]
    if result.get("phase") != "full_stock_checkpoints" or pool.get("complete") is not True or not rows or len(set(codes)) != len(codes):
        raise ValueError("feature preview requires unique completed stock checkpoints")
    if len(rows) != prepared["ordinary_reference_n"] or any(
        row.get("complete") is not True
        or row.get("source_id") != prepared["source"]["source_id"]
        or row.get("input_id") != prepared["input_id"]
        or not re.fullmatch(r"[0-9A-Za-z]+", row["code"])
        for row in rows
    ):
        raise ValueError("feature preview stock source/input/coverage differs")
    return prepared, sorted(rows, key=lambda row: row["code"])


def build_preview(stock_result: Path, destination: Path, *, repo_root: Path, codes: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Write a physical local candidate under this worktree's .tmp, never shared.

    Verify only the three artifacts actually consumed, once per stock. Retired
    prices are neither needed nor restored. Original receipts and all other
    study artifacts remain untouched. An interrupted sibling staging is retained.
    """
    before = resource_sample()
    repo_root, stock_result, destination = map(checked_path, (repo_root, stock_result, destination))
    if not destination.is_relative_to(repo_root / ".tmp") or destination == repo_root / ".tmp":
        raise ValueError("feature preview destination must be below this worktree's .tmp")
    if destination.exists():
        raise FileExistsError(destination)
    preparation = checked_path(stock_result.parent / "derived-preparation.json")
    inputs = fingerprint_inputs([InputSpec("stock_result", stock_result, live_producer=False), InputSpec("preparation", preparation, live_producer=False)])
    prepared, rows = _source_parts(stock_result, preparation)
    if codes is not None:
        if not codes or len(set(codes)) != len(codes) or not set(codes).issubset(row["code"] for row in rows):
            raise ValueError("feature preview selection must contain unique existing stock codes")
        rows = [row for row in rows if row["code"] in codes]
    for row in rows:
        source = checked_path(Path(row["output_path"]))
        if destination.is_relative_to(source) or source.is_relative_to(destination):
            raise ValueError("feature preview destination overlaps source artifacts")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = checked_path(destination.with_name(f".staging-{destination.name}-{uuid.uuid4().hex}"))
    staging.mkdir()
    stocks = []
    observed: dict[Path, tuple[int, int]] = {}
    common_calendar: dict[str, Any] | None = None
    for number, row in enumerate(rows, 1):
        started = resource_sample()
        source = checked_path(Path(row["output_path"]))
        receipt = checked_path(source / "receipt.json")
        observed[receipt] = _stamp(receipt)
        if read_json(receipt) != row:
            raise ValueError("feature preview stock receipt differs from completed result")
        descriptors = {record["path"]: record for record in row["artifacts"]}
        if len(descriptors) != len(row["artifacts"]):
            raise ValueError("duplicate source artifact names")
        selected = [descriptors[name] for name in TABLES.values()]
        for record in selected:
            path = checked_path(source / record["path"])
            observed[path] = _stamp(path)
        verify_files(source, selected)
        frames = {name: read_frame(source / filename) for name, filename in TABLES.items()}
        projected = project_frames(frames["daily_indicators"], frames["confirmed_pivots"], frames["daily_conditions"], code=row["code"])
        calendar = cast(pd.DatetimeIndex, frames["daily_indicators"].index)
        calendar_record = {
            "sessions": len(calendar),
            "first": cast(pd.Timestamp, calendar[0]).isoformat(),
            "last": cast(pd.Timestamp, calendar[-1]).isoformat(),
            "sha256": object_digest(calendar.strftime("%Y-%m-%d").tolist()),
        }
        if common_calendar is not None and common_calendar != calendar_record:
            raise ValueError("feature preview stocks have different calendars")
        if len(calendar) != prepared["calendar_n"]:
            raise ValueError("feature preview calendar coverage differs from preparation")
        common_calendar = calendar_record
        output = staging / row["code"]
        output.mkdir()
        artifacts = []
        for name, frame in projected.items():
            path = output / f"{name}.parquet"
            with path.open("xb") as stream:
                write_frame(frame, stream, index=True)
            assert_frame_equal(frame, read_frame(path), check_exact=True)
            artifacts.append({
                **describe_file(staging, path),
                "table": name,
                "rows": len(frame),
                "columns": list(frame.columns),
                "compression": "zstd",
                "exact_projection_verified": True,
            })
        stocks.append({
            "code": row["code"],
            "original_receipt": {"path": str(receipt), "sha256": file_digest(receipt)},
            "source_artifacts": selected,
            "artifacts": artifacts,
        })
        if number == 1 or number % 100 == 0 or number == len(rows):
            LOGGER.info(
                "Feature preview stock=%s progress=%d/%d observation=%s",
                row["code"],
                number,
                len(rows),
                phase_receipt("verify_project_serialize", started, resource_sample()),
            )
    if any(_stamp(path) != stamp for path, stamp in observed.items()):
        raise ValueError("source stock artifacts changed during feature projection")
    manifest = {
        "schema": DEFINITION,
        "status": "local_candidate_pending_owner_claude_sop",
        "complete": True,
        "numerical_source": prepared["source"],
        "input_id": prepared["input_id"],
        "original_producer_fingerprint": prepared["producer_fingerprint"],
        "price_basis": "price-basis.v2/reference_factor_adjusted; original PR17 official-source preparation",
        "calendar": common_calendar,
        "stocks": stocks,
        "stock_count": len(stocks),
        "available_stock_count": prepared["ordinary_reference_n"],
        "verification": "selected original artifact hashes; exact in-memory projection and Parquet roundtrip; unchanged source stat identities",
        "availability": {
            "daily_indicators": "at close, subject to original quality/warmup",
            "confirmed_pivots": "confirmed_at, never extreme_date",
            "daily_conditions": "at close under original versioned PR17/HHHL definitions; industry_ref is current-reference metadata",
        },
        "omitted": {"daily_price_columns": list(PRICE_COLUMNS), "future_outcomes": "base_labels not exported", "events_controls_global_ranks": "not exported"},
        "definition_references": [
            "research_core.derived_features:derived-features.v1",
            "research_core.pattern_scan_indicators_v1",
            "research_core.pattern_scan_daily_values_v1",
            "research_core.hhhl_variants_daily",
        ],
        "policy": "temporary owner-authorized worktree preview; no shared registration/update, automatic deletion, or new retained input snapshot",
        "payload_bytes": sum(artifact["bytes"] for stock in stocks for artifact in stock["artifacts"]),
        "measurement": phase_receipt("local_feature_projection", before, resource_sample()),
    }
    write_json(staging / "manifest.json", manifest)
    # Relative result names survive the sibling rename. Git still resolves the
    # real worktree above staging, preserving the actual projection executor.
    write_run_receipt(
        staging / "run_receipt.json",
        run_id=destination.name,
        definition=DEFINITION,
        parameters={"mode": "verified_projection_no_recalculation", "stock_count": len(stocks)},
        inputs=inputs,
        results={"manifest": staging / "manifest.json"},
        repo_root=staging,
    )
    publish_noreplace(staging, destination)
    LOGGER.info("Local feature candidate complete stocks=%d payload_bytes=%d destination=%s", len(stocks), manifest["payload_bytes"], destination)
    return manifest
