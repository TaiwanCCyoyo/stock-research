"""Read-only dashboard projections of maintained prices and catalog metadata.

No calculation, publication or acquisition occurs here. One background warmup uses
the existing verified readers; a bounded pool projects three files concurrently.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, cast

import pandas as pd

from research_core import live_producer
from research_core import maintained_adjusted_daily as maintained
from research_core.opportunity_history_bundle import history_data_roots
from research_core.producer_data import producer_data_root
from research_core.research_data_catalog import DataCatalog
from research_core.shared_data import shared_data_root

LOGGER = logging.getLogger(__name__)
REFERENCE = "reference_factor_adjusted"
PRICE_COLUMNS = ["Code", "Date", "Open", "High", "Low", "Close", "VolumeLots", "Quality", "quality_reason"]


class ViewWarming(RuntimeError):
    """The selected generation is being verified in the background."""


class ViewUnavailable(RuntimeError):
    """Missing, pruned or invalid evidence; never substitute another generation."""


def symbol_names() -> dict[str, tuple[str, str]]:
    """Optional live metadata, guarded before and after the stable read."""
    try:
        live_producer.assert_producer_idle()
        path = producer_data_root() / "symbol_meta.sqlite"

        def read(source: Path) -> dict[str, tuple[str, str]]:
            connection = live_producer.readonly_sqlite(source)
            try:
                connection.row_factory = sqlite3.Row
                rows = connection.execute("SELECT * FROM symbol_meta").fetchall()
                return {str(row["code"]): (str(dict(row).get("name") or row["code"]), str(dict(row).get("market") or "")) for row in rows}
            finally:
                connection.close()

        names = live_producer.read_stable(path, read)
        live_producer.assert_producer_idle()
        return names
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        LOGGER.info("Symbol names unavailable; displaying codes: %s", exc)
        return {}


def catalog_summary() -> tuple[dict[str, Any] | None, str | None]:
    """Discover the real catalog; absence is explicit, never a hand-written list."""
    try:
        catalog = DataCatalog(history_data_roots()).read()
        return {key: catalog.get(key, []) for key in ("version_id", "entries", "retired")}, None
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        LOGGER.warning("Shared catalog unavailable: %s", exc)
        return None, "資料目錄無法讀取或驗證；請檢查 STOCK_RESEARCH_DATA_ROOT。"


def family_summary(status: dict[str, Any]) -> dict[str, Any]:
    return {
        key: status.get(key)
        for key in ("family", "generation", "asof", "status_sha256", "codes", "calendar", "definition", "bases", "technical", "built_at_utc")
    }


def column_arrays(frame: pd.DataFrame) -> dict[str, Any]:
    """Preserve booleans and map pandas missing/non-finite values to JSON null."""
    return {str(column): json.loads(cast(str, frame[column].to_json(orient="values"))) for column in frame.columns}


class SharedDataView:
    """One active generation and at most three reader workers; no shared writes."""

    def __init__(self, root: Path | None = None):
        self._root = root
        self._lock = threading.Lock()
        self._read_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="shared-data-read")
        self._future: Future[list[dict[str, Any]]] | None = None
        self._identity: tuple[str, str] | None = None
        self._names: dict[str, tuple[str, str]] = {}
        self.warm_seconds: float | None = None

    @property
    def root(self) -> Path:
        if self._root is None:
            self._root = shared_data_root()
        return self._root

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    def status(self) -> dict[str, Any]:
        try:
            return maintained.current_generation(self.root)
        except (OSError, ValueError, KeyError) as exc:
            raise ViewUnavailable("共用資料世代不存在、已清除或驗證失敗；請重新載入。") from exc

    def _warm(self, status: dict[str, Any]) -> list[dict[str, Any]]:
        started = time.perf_counter()
        generation = status["generation"]
        # An impossible empty-code filter exercises the existing SHA verification
        # with a typed string predicate (Arrow rejects an untyped empty IN list),
        # without retaining entire price or indicator tables in the API process.
        for basis in maintained.BASES:
            maintained.read_adjusted_daily(basis, codes=[""], columns=["Code"], root=self.root, generation=generation)
        for table in ("daily", "pivots"):
            maintained.read_technical(table, codes=[""], columns=["Code"], root=self.root, generation=generation)
        frame, _ = maintained.read_adjusted_daily(REFERENCE, columns=["Code", "Date"], root=self.root, generation=generation)
        periods = frame.groupby("Code", sort=True)["Date"].agg(["min", "max"])
        symbols = [
            {"code": str(code), "first": cast(pd.Timestamp, row["min"]).date().isoformat(), "last": cast(pd.Timestamp, row["max"]).date().isoformat()}
            for code, row in periods.iterrows()
        ]
        self._names = symbol_names()
        self.warm_seconds = time.perf_counter() - started
        LOGGER.info("Verified shared viewer generation=%s symbols=%d seconds=%.3f", generation, len(symbols), self.warm_seconds)
        return symbols

    def prepare(self, *, wait: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Re-resolve current.json on every call and pin all reads to that identity."""
        status = self.status()
        identity = (status["generation"], status["status_sha256"])
        with self._lock:
            if self._identity != identity:
                # Do not build an unbounded queue when current changes repeatedly.
                if self._future is not None and not self._future.done():
                    raise ViewWarming("正在核對共用資料；世代更新後將重新核對。")
                self._identity = identity
                self._future = self._executor.submit(self._warm, status)
            future = self._future
        assert future is not None
        if not wait and not future.done():
            raise ViewWarming("正在核對共用資料，請稍候。")
        try:
            symbols = future.result()
            # A prune or pointer update during warmup must not advertise old data.
            current = self.status()
            if (current["generation"], current["status_sha256"]) != identity:
                raise ViewWarming("共用資料世代已更新，正在重新核對。")
            return status, symbols
        except (OSError, ValueError, KeyError) as exc:
            LOGGER.warning("Shared viewer warmup failed: %s", exc)
            raise ViewUnavailable("共用資料檔案缺失、已清除或驗證失敗。") from exc

    def start(self) -> None:
        try:
            self.prepare()
        except ViewWarming:
            pass
        except ViewUnavailable as exc:
            LOGGER.warning("Shared viewer startup: %s", exc)

    def symbols(self) -> dict[str, Any]:
        status, rows = self.prepare()
        return {
            "generation": status["generation"],
            "status_sha256": status["status_sha256"],
            "namesAvailable": bool(self._names),
            "symbols": [
                {**row, "name": self._names.get(row["code"], (row["code"], ""))[0], "market": self._names.get(row["code"], ("", ""))[1]} for row in rows
            ],
        }

    def series(self, code: str, basis: str, first: str | None, last: str | None) -> dict[str, Any]:
        status, symbols = self.prepare()
        if code not in {row["code"] for row in symbols}:
            raise LookupError("此世代沒有這個股票代號。")
        generation = status["generation"]
        try:
            # Only one symbol's three verified file projections are in flight.
            # The queue and memory stay bounded even with concurrent HTTP callers.
            with self._read_lock:
                price_read = self._executor.submit(
                    maintained.read_adjusted_daily, basis, codes=[code], columns=PRICE_COLUMNS, root=self.root, generation=generation
                )
                technical_read = pivot_read = None
                if basis == REFERENCE:
                    technical_read = self._executor.submit(maintained.read_technical, "daily", codes=[code], root=self.root, generation=generation)
                    pivot_read = self._executor.submit(maintained.read_technical, "pivots", codes=[code], root=self.root, generation=generation)
                reads = [price_read, *([technical_read, pivot_read] if technical_read and pivot_read else [])]
                # Drain every submitted read even when one fails, before admitting
                # another symbol; the failing future is raised below.
                wait(reads)
                prices, _ = price_read.result()
                technical = technical_read.result()[0] if technical_read else pd.DataFrame()
                pivots = pivot_read.result()[0] if pivot_read else pd.DataFrame()
            prices = prices.sort_values("Date").reset_index(drop=True)
            if basis == REFERENCE:
                technical = prices[["Code", "Date"]].merge(technical, on=["Code", "Date"], how="left", validate="one_to_one")
            selected = pd.Series(True, index=prices.index)
            if first:
                selected &= prices["Date"].ge(pd.Timestamp(first))
            if last:
                selected &= prices["Date"].le(pd.Timestamp(last))
            prices = prices.loc[selected].copy()
            # Even a malformed-but-hashed invalid row must render as whitespace.
            prices.loc[~prices["Quality"].fillna(False), ["Open", "High", "Low", "Close", "VolumeLots"]] = float("nan")
            tech: dict[str, Any] = {}
            if not technical.empty:
                technical = technical.loc[selected].drop(columns=["Code", "Date"]).astype(object)
                technical.loc[~prices["Quality"].fillna(False), :] = None
                tech = column_arrays(technical)
            pivot_rows: list[dict[str, Any]] = []
            if not pivots.empty:
                pivots = pivots.loc[pivots["extreme_date"].isin(prices["Date"])]
                for column in ("extreme_date", "confirmed_at"):
                    pivots[column] = pivots[column].dt.strftime("%Y-%m-%d")
                pivot_rows = json.loads(pivots.drop(columns="Code").to_json(orient="records"))
            result = column_arrays(
                prices.rename(
                    columns={
                        "Open": "open",
                        "High": "high",
                        "Low": "low",
                        "Close": "close",
                        "VolumeLots": "volume",
                        "Quality": "quality",
                    }
                ).drop(columns=["Code", "Date"])
            )
            # Check presence/integrity again, including a prune after the last read.
            after = maintained.current_generation(self.root, generation=generation)
            if after["status_sha256"] != status["status_sha256"]:
                raise ValueError("generation status changed during request")
            return {
                **result,
                "dates": prices["Date"].dt.strftime("%Y-%m-%d").tolist(),
                "tech": tech,
                "pivots": pivot_rows,
                "code": code,
                "basis": basis,
                "generation": generation,
                "status_sha256": status["status_sha256"],
                "asof": status["asof"],
            }
        except (OSError, ValueError, KeyError) as exc:
            LOGGER.warning("Shared viewer read failed generation=%s code=%s: %s", generation, code, exc)
            raise ViewUnavailable("共用資料檔案缺失、已清除或驗證失敗；請重新載入。") from exc
