"""Read producer institutional shares without joining gaps or observing t (T6--T8)."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from research_core.live_producer import ProducerBusyError, ProducerChangedError, assert_producer_idle, readonly_sqlite, stat_identity
from research_core.producer_data import producer_data_root

LOGGER = logging.getLogger(__name__)
DEFINITION_ID = "institutional-flow.v1"
NET_COLUMNS = ("three_institutions_net", "foreign_total_net", "trust_net")
MARKETS = ("TWSE", "TPEx")


@dataclass(frozen=True)
class InstitutionalRead:
    rows: pd.DataFrame
    coverage: dict[str, dict[str, object]]
    path: Path


def assert_institutional_idle() -> None:
    """Observe manual backfill writers as well as the scheduled writer guard.

    Failure to observe process state refuses the read. Never kill a process or
    acquire the producer's own writer lock. The end-of-read file check also
    catches a writer that began after this point-in-time observation.
    """
    assert_producer_idle()
    if sys.platform != "win32":
        return
    query = (
        "Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -match '^(python|pythonw|uv)(\\.exe)?$' -and "
        "$_.CommandLine -match '(fetch_institutional|backfill.{0,40}institutional|institutional.{0,40}backfill)' "
        "} | Select-Object ProcessId,Name | ConvertTo-Json -Compress"
    )
    observed = subprocess.run(["powershell.exe", "-NoProfile", "-Command", query], capture_output=True, text=True, check=False, timeout=30)
    if observed.returncode:
        raise ProducerBusyError("cannot observe institutional backfill processes")
    if observed.stdout.strip():
        raise ProducerBusyError(f"institutional backfill is running; wait for its owner: {observed.stdout.strip()}")


def continuous_coverage(logs: pd.DataFrame, rows: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict[str, dict[str, object]]:
    """Each market's final uninterrupted source-consistent session suffix.

    A successful checkpoint must agree with actual rows. A failed/missing
    checkpoint, absent rows or source change resets the start. Earlier islands
    remain excluded even when 60-row rolling windows there would be complete.
    """
    if calendar.empty or not calendar.is_unique or not calendar.is_monotonic_increasing:
        raise ValueError("a nonempty sorted unique session calendar is required")
    if logs.duplicated(["market", "date"]).any() or rows.duplicated(["code", "date"]).any():
        raise ValueError("duplicate institutional checkpoint or stock day")
    result: dict[str, dict[str, object]] = {}
    for market in MARKETS:
        market_rows = rows.loc[rows.market.eq(market)]
        day_sources = market_rows.groupby("date").source.agg(lambda values: tuple(sorted(set(values))))
        actual_n = market_rows.groupby("date").size()
        checkpoints = logs.loc[logs.market.eq(market)].set_index("date")
        complete: list[tuple[int, str]] = []
        for index, day in enumerate(calendar.strftime("%Y-%m-%d")):
            if day not in checkpoints.index or day not in actual_n.index:
                continue
            checkpoint = checkpoints.loc[day]
            sources = day_sources.loc[day]
            if checkpoint["status"] == "ok" and int(checkpoint["row_count"]) == int(actual_n.loc[day]) and len(sources) == 1:
                complete.append((index, str(sources[0])))
        # Coverage ends on the latest genuinely covered session, not a synthetic
        # interpolation across a trailing gap. Later sessions stay unknown.
        suffix: list[tuple[int, str]] = []
        for item in complete:
            if suffix and (item[0] != suffix[-1][0] + 1 or item[1] != suffix[-1][1]):
                suffix = []
            suffix.append(item)
        result[market] = {
            "from": None if not suffix else cast(pd.Timestamp, calendar[suffix[0][0]]).date().isoformat(),
            "to": None if not suffix else cast(pd.Timestamp, calendar[suffix[-1][0]]).date().isoformat(),
            "source": None if not suffix else suffix[0][1],
            "sessions": len(suffix),
            "earlier_complete_sessions_excluded": len(complete) - len(suffix),
        }
    return result


def read_institutional(calendar: pd.DatetimeIndex, *, idle_check: Callable[[], None] = assert_institutional_idle) -> InstitutionalRead:
    """One read-only SQLite transaction at the configured canonical producer root."""
    idle_check()
    path = producer_data_root() / "institutional.sqlite"
    wal = path.with_name(path.name + "-wal")

    def identity() -> tuple[tuple[int, int], tuple[int, int] | None]:
        return stat_identity(path), stat_identity(wal) if wal.exists() else None

    before = identity()
    with closing(readonly_sqlite(path)) as connection:
        connection.execute("BEGIN")
        rows = pd.read_sql_query(
            "SELECT market,date,code,source,three_institutions_net,foreign_total_net,trust_net FROM institutional_daily WHERE date <= ?",
            connection,
            params=[cast(pd.Timestamp, calendar[-1]).date().isoformat()],
        )
        logs = pd.read_sql_query(
            "SELECT market,date,status,row_count FROM institutional_fetch_log WHERE date <= ?",
            connection,
            params=[cast(pd.Timestamp, calendar[-1]).date().isoformat()],
        )
        connection.execute("COMMIT")
    if identity() != before:
        raise ProducerChangedError("institutional database or WAL changed during read; wait for the writer")
    idle_check()
    coverage = continuous_coverage(logs, rows, calendar)
    LOGGER.info("Institutional contiguous coverage %s", json.dumps(coverage, ensure_ascii=False))
    return InstitutionalRead(rows, coverage, path)


def institutional_daily(
    rows: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    code: str,
    market: str,
    volume_shares: pd.Series,
    coverage: dict[str, dict[str, object]],
) -> pd.DataFrame:
    """All rolling quantities use exactly t-60..t-1 and raw share units.

    A missing daily row, missing net or missing/nonpositive total volume yields
    unknown for that flow; the primary INST-known mask uses the three-institution
    series. Missing foreign/trust data does not change the primary mask.
    """
    if not calendar.equals(volume_shares.index) or rows.duplicated(["code", "date"]).any():
        raise ValueError("aligned volume and unique institutional stock days required")
    found = rows.loc[rows.code.eq(code) & rows.market.eq(market)].copy()
    found["date"] = pd.to_datetime(found.date)
    found = found.set_index("date").reindex(calendar)
    segment = coverage.get(market, {})
    start, end = segment.get("from"), segment.get("to")
    within = (
        np.zeros(len(calendar), dtype=bool)
        if not isinstance(start, str) or not isinstance(end, str)
        else (calendar >= pd.Timestamp(start)) & (calendar <= pd.Timestamp(end))
    )
    source = segment.get("source")
    within = within & found.source.eq(source).to_numpy()
    volume = cast(pd.Series, volume_shares.where(np.isfinite(volume_shares) & volume_shares.ge(0)))
    volume_sum = cast(pd.Series, volume.rolling(60, min_periods=60).sum()).shift(1)
    result = pd.DataFrame(index=calendar)
    for column in NET_COLUMNS:
        net = cast(pd.Series, pd.to_numeric(found[column], errors="coerce"))
        net = cast(pd.Series, net.where(within))
        net = cast(pd.Series, net.where(np.isfinite(net)))
        known_n = cast(pd.Series, net.notna().rolling(60, min_periods=60).sum()).shift(1)
        positive = cast(pd.Series, net.gt(0).where(net.notna()))
        buy_fraction = cast(pd.Series, positive.rolling(60, min_periods=60).mean()).shift(1)
        net_sum = cast(pd.Series, net.rolling(60, min_periods=60).sum()).shift(1)
        ratio = net_sum / volume_sum.where(volume_sum.gt(0))
        known = known_n.eq(60) & buy_fraction.notna() & ratio.notna()
        result[f"{column}_buy_fraction"] = buy_fraction.where(known)
        result[f"{column}_volume_ratio"] = ratio.where(known)
        result[f"{column}_state"] = np.where(known, (buy_fraction.ge(0.6) & ratio.ge(0.05)).astype(np.int8), np.int8(-1)).astype(np.int8)
    result["INST"] = result["three_institutions_net_state"]
    return result
