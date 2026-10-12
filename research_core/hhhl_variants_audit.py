"""Deterministic local event evidence for reviewing fixed HHHL calculations."""

from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from numbers import Integral, Real
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from research_core.artifact_store import file_digest, safe_path, write_json

if TYPE_CHECKING:
    from research_core.hhhl_variants_inputs import StockInput

SAMPLING = "first 5 by (code, asof_date, event_id), then first 5 remaining by (SHA256(event_id), event_id); no outcome selection"
LOGGER = logging.getLogger(__name__)


def _nullable(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, Mapping):
        return {str(key): _nullable(item) for key, item in value.items()}
    if isinstance(value, np.ndarray):
        return _nullable(value.tolist())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_nullable(item) for item in value]
    if isinstance(value, np.datetime64):
        timestamp = pd.Timestamp(value)
        return timestamp.isoformat() if isinstance(timestamp, pd.Timestamp) else None
    if isinstance(value, np.generic):
        return _nullable(value.item())
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        return value
    raise TypeError(f"unsupported audit scalar: {type(value).__name__}")


def write_audit_samples(stocks: list[StockInput], staging: Path) -> dict[str, Any]:
    """Write at most ten predetermined P events locally; return only public identities."""
    events = []
    seen: set[str] = set()
    for stock in stocks:
        for event in stock.events.to_dict(orient="records"):
            event_id = event["event_id"]
            if not isinstance(event_id, str) or event_id in seen:
                raise ValueError("audit requires distinct original event IDs")
            seen.add(event_id)
            t0 = int(event["calendar_index"])
            if not 0 <= t0 < len(stock.raw):
                raise ValueError("audit event outside common calendar")
            events.append((stock.code, pd.Timestamp(stock.raw["Date"].iloc[t0]), event_id, stock, event))
    events.sort(key=lambda entry: entry[:3])
    selected = events[:5]
    remaining = sorted(events[5:], key=lambda entry: (hashlib.sha256(entry[2].encode("utf-8")).hexdigest(), entry[2]))
    selected += remaining[:5]
    cases = []
    cache: dict[int, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]] = {}
    for code, asof, event_id, stock, event in selected:
        if stock.ordinal not in cache:
            daily = pd.read_parquet(safe_path(staging / f"daily/{stock.ordinal:04}.parquet"))
            features = pd.read_parquet(safe_path(staging / f"features/{stock.ordinal:04}.parquet"))
            flag_path = safe_path(staging / f"flags/{stock.ordinal:04}.parquet")
            flags = pd.read_parquet(flag_path) if flag_path.exists() else pd.DataFrame()
            if len(daily) != len(stock.raw):
                raise ValueError("audit daily rows must match common calendar")
            cache[stock.ordinal] = daily, features, flags
        daily, features, flags = cache[stock.ordinal]
        t0 = int(event["calendar_index"])
        end = min(t0 + 252, len(stock.raw) - 1)
        feature = features.loc[features["calendar_index"].eq(t0)]
        if len(feature) != 1 or feature.iloc[0]["event_id"] != event_id:
            raise ValueError("audit feature row identity mismatch")
        cohort = "P-over" if event.get("has_old", False) or event.get("has_recent_far", False) else "P-clean"
        flag_rows = flags.loc[flags["event_id"].eq(event_id) & flags["cohort_id"].eq(cohort)] if len(flags) else flags
        before = []
        path = []
        for position in range(end + 1):
            day = stock.raw["Date"].iloc[position]
            if position <= t0:
                before.append({
                    "calendar_index": position,
                    "Date": day,
                    "raw": stock.raw.iloc[position].to_dict(),
                    "adjusted": stock.adjusted.iloc[position].to_dict(),
                    "daily": {name: daily[name].iloc[position] for name in ("atr_pct", "ma20", "ma60")},
                })
            if position >= t0:
                path.append({
                    "calendar_index": position,
                    "offset": position - t0,
                    "Date": day,
                    "adjusted_close": stock.adjusted["Close"].iloc[position],
                    "ma20": daily["ma20"].iloc[position],
                    "ma60": daily["ma60"].iloc[position],
                })
        pivots = []
        for extreme, confirmed, price in stock.low_pivots:
            if confirmed > end:
                continue
            if not 0 <= extreme <= confirmed < len(stock.raw):
                raise ValueError("audit pivot indices outside common calendar")
            pivots.append({
                "extreme_index": extreme,
                "confirmed_index": confirmed,
                "price": price,
                "extreme_date": stock.raw["Date"].iloc[extreme],
                "confirmed_date": stock.raw["Date"].iloc[confirmed],
            })
        cases.append(
            _nullable({
                "event_id": event_id,
                "code": code,
                "asof_date": asof,
                "cohort_id": cohort,
                "original_source_event": event,
                "feature_inputs_asof_t0": {
                    "common_calendar_prefix": before,
                    "context_asof_t0": stock.context.iloc[t0].to_dict(),
                    "computed_features_asof_t0": feature.iloc[0].to_dict(),
                },
                "outcome_flag_path_t0_to_H": {
                    "max_horizon": 252,
                    "closing_path": path,
                    "flags": flag_rows.to_dict(orient="records"),
                    "frozen_low_pivots": pivots,
                    "pivot_semantics": "frozen-v4 1.5ATR; extreme and confirmation dates kept distinct",
                },
            })
        )
    destination = safe_path(staging / "audit/ten-events.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_json(destination, {"schema_version": "hhhl-variants-audit.v1", "sampling": SAMPLING, "rows": len(cases), "cases": cases})
    LOGGER.info("Wrote deterministic HHHL audit samples: original_events=%d cases=%d", len(events), len(cases))
    return {"selected_event_ids": [entry[2] for entry in selected], "rows": len(cases), "sampling": SAMPLING, "sha256": file_digest(destination)}
