"""Bounded per-stock execution for annual ranking candidates.

Each worker evaluates one stock's history independently. All results return to
the parent before any ranking or aggregation, preserving the cross-stock
barrier and deterministic output order.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from typing import Any

import pandas as pd

from research_core.annual_rotation import annual_candidates
from research_core.research_measurement_v1 import phase_receipt, resource_sample

LOGGER = logging.getLogger(__name__)


def _rank_stock(
    code: str,
    stock_prices: pd.DataFrame,
    stock_actions: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    years: list[int],
) -> dict[str, Any]:
    """Worker boundary: calculate one stock and return its local receipt."""
    before = resource_sample()
    observed_years = set(pd.to_datetime(stock_prices["Date"]).dt.year.astype(int))
    # A symbol enters the annual universe only once it has at least one raw
    # quote that year. For partial-year listings, annual_candidates still
    # decides whether its required anchor/end points are usable.
    rows = [annual_candidates(stock_prices, stock_actions, calendar, year=year) for year in years if year in observed_years]
    after = resource_sample()
    receipt = phase_receipt("annual_candidates_one_stock", before, after)
    return {"code": code, "rows": rows, "measurement": receipt}


def _validate_years(years: list[int]) -> list[int]:
    if not years or any(type(year) is not int for year in years):
        raise ValueError("years must be a nonempty list of integer years")
    if len(set(years)) != len(years):
        raise ValueError("years must not contain duplicates")
    return sorted(years)


def rank_panel(
    prices: pd.DataFrame,
    actions: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    years: list[int],
    *,
    workers: int = 1,
    codes: list[str] | None = None,
) -> dict[str, Any]:
    """Calculate annual candidates by stock with a bounded process pool.

    Cross-stock ranking remains a parent-side barrier: workers only run the
    established ``annual_candidates`` definition for one stock at a time.
    The process pool admits no more than ``workers`` in-flight stock frames.
    Native memory and I/O fields are process measurements; I/O counters are not
    physical-disk throughput. Pickle byte counts and isolated process-pool
    startup/window measurements are explicitly unknown.
    """
    if type(workers) is not int or workers not in (1, 2):
        raise ValueError("workers must be 1 or 2")
    ordered_years = _validate_years(years)
    if not isinstance(calendar, pd.DatetimeIndex) or calendar.empty or not calendar.is_monotonic_increasing:
        raise ValueError("calendar must be a nonempty increasing DatetimeIndex")
    if not {"Code", "Date"}.issubset(prices.columns):
        raise ValueError("prices must contain Code and Date columns")
    if not {"code", "ex_date"}.issubset(actions.columns):
        raise ValueError("actions must contain code and ex_date columns")

    parent_before = resource_sample()
    grouping_before = resource_sample()
    normalized_prices = (prices.loc[prices.Code.astype(str).isin(codes)] if codes is not None else prices).copy(deep=False)
    if bool(normalized_prices["Code"].isna().any()) or bool(normalized_prices["Date"].isna().any()):
        raise ValueError("prices must have valid stock codes and dates")
    normalized_prices["Code"] = normalized_prices["Code"].astype(str)
    normalized_prices["Date"] = pd.to_datetime(normalized_prices["Date"])

    normalized_actions = actions.copy()
    if bool(normalized_actions["code"].isna().any()) or bool(normalized_actions["ex_date"].isna().any()):
        raise ValueError("actions must have valid stock codes and ex-dates")
    normalized_actions["code"] = normalized_actions["code"].astype(str)
    normalized_actions["ex_date"] = pd.to_datetime(normalized_actions["ex_date"])
    prices_by_code = {str(code): frame.reset_index(drop=True) for code, frame in normalized_prices.groupby("Code", sort=True)}
    actions_by_code: dict[str, pd.DataFrame] = {
        str(code): frame.drop(columns=["_code"]).reset_index(drop=True)
        for code, frame in normalized_actions.assign(_code=normalized_actions["code"]).groupby("_code", sort=True)
    }
    available_codes = sorted(prices_by_code)
    if codes is None:
        selected_codes = available_codes
    else:
        if any(not isinstance(code, str) or not code for code in codes):
            raise ValueError("codes must contain nonempty stock-code strings")
        selected_set = set(codes)
        selected_codes = [code for code in available_codes if code in selected_set]
    stock_inputs = [
        (
            code,
            prices_by_code[code],
            actions_by_code[code] if code in actions_by_code else normalized_actions.iloc[0:0].copy(),
            calendar,
            ordered_years,
        )
        for code in selected_codes
    ]
    grouping_receipt = phase_receipt("group_stock_inputs", grouping_before, resource_sample())
    LOGGER.debug("Annual ranking inputs grouped: stocks=%d years=%d workers=%d", len(stock_inputs), len(ordered_years), workers)

    processing_before = resource_sample()
    stock_results: list[dict[str, Any]] = []
    peak_inflight = 0
    if workers == 1:
        for stock_input in stock_inputs:
            stock_results.append(_rank_stock(*stock_input))
            peak_inflight = max(peak_inflight, 1)
    elif stock_inputs:
        executor = ProcessPoolExecutor(max_workers=workers)
        pending: dict[Future[dict[str, Any]], str] = {}
        next_index = 0
        try:
            while next_index < len(stock_inputs) or pending:
                while next_index < len(stock_inputs) and len(pending) < workers:
                    stock_input = stock_inputs[next_index]
                    future = executor.submit(_rank_stock, *stock_input)
                    pending[future] = stock_input[0]
                    next_index += 1
                    peak_inflight = max(peak_inflight, len(pending))
                completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed:
                    pending.pop(future)
                    stock_results.append(future.result())
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
    processing_receipt = phase_receipt("bounded_annual_stock_pool", processing_before, resource_sample())

    aggregation_before = resource_sample()
    rows = [row for result in stock_results for row in result["rows"]]
    rows.sort(key=lambda row: (row["year"], row["code"]))
    status_counts = Counter(str(row["ranking_status"]) for row in rows)
    status_counts_int = {status: int(status_counts[status]) for status in sorted(status_counts)}
    aggregation_receipt = phase_receipt("parent_barrier_and_integer_aggregation", aggregation_before, resource_sample())
    performance = {
        "schema": "annual-ranking-pool.v1",
        "workers_requested": workers,
        "stock_count": int(len(stock_inputs)),
        "year_count": int(len(ordered_years)),
        "row_count": int(len(rows)),
        "ranking_status_counts": status_counts_int,
        "peak_inflight_stock_jobs": int(peak_inflight),
        "worker_receipts": [result["measurement"] for result in sorted(stock_results, key=lambda item: item["code"])],
        "parent_phases": {
            "group_stock_inputs": grouping_receipt,
            "bounded_annual_stock_pool": processing_receipt,
            "parent_barrier_and_integer_aggregation": aggregation_receipt,
        },
        "pickle_serialized_input_bytes": None,
        "pickle_serialized_input_bytes_status": "unknown",
        "process_pool_startup_seconds": None if workers == 2 else 0.0,
        "process_pool_startup_status": "unknown" if workers == 2 else "not_applicable",
        "process_pool_window_seconds": None if workers == 2 else 0.0,
        "process_pool_window_status": "unknown" if workers == 2 else "not_applicable",
        "io_scope": "Native process I/O counters are transfer counters, not physical disk throughput.",
        "worker_peak_memory_policy": "Retained as observed evidence; no hard memory limit is asserted.",
        "host_pid": os.getpid(),
        "parent_total": phase_receipt("annual_ranking_total", parent_before, resource_sample()),
    }
    LOGGER.debug("Annual ranking barrier complete: rows=%d peak_inflight=%d", len(rows), peak_inflight)
    return {"rows": rows, "performance": performance}
