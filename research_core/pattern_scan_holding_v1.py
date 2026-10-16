"""Retrospective holding diagnostics over an explicit, fixed ordinary-stock grid."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from numbers import Integral
from typing import Any

import numpy as np
import pandas as pd

from research_core.hhhl_variants_run import UNKNOWN_INDUSTRIES

LOGGER = logging.getLogger(__name__)
STATES = ("up", "down", "consolidation", "mixed", "unknown")
OUTPUT_COLUMNS = (
    "security_id",
    "t0",
    "calendar_index",
    "horizon",
    "calendar_full",
    "censored",
    "endpoint_out_of_range",
    "observed_sessions",
    "industry_ref",
    "own_return",
    "own_return_reason",
    "peer_return",
    "peer_return_reason",
    "potential_peer_n",
    "known_peer_n",
    "unknown_peer_n",
    "benchmark_return",
    "benchmark_return_reason",
    "holding_context_reason",
    "information_scope",
) + tuple(name for state in STATES for name in (f"holding_{state}_n", f"holding_{state}_fraction"))


def _empty_holding() -> pd.DataFrame:
    integers = {"calendar_index", "horizon", "observed_sessions", "potential_peer_n", "known_peer_n", "unknown_peer_n"}
    booleans = {"calendar_full", "censored", "endpoint_out_of_range"}
    floats = {"own_return", "peer_return", "benchmark_return"}
    return pd.DataFrame({
        name: pd.Series(
            dtype="int64"
            if name in integers or name.endswith("_n")
            else "bool"
            if name in booleans
            else "float64"
            if name in floats or name.endswith("_fraction")
            else "object"
        )
        for name in OUTPUT_COLUMNS
    })


def _jumps(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    flat = values.ravel()
    if any(not pd.isna(value) and not isinstance(value, (bool, np.bool_)) for value in flat):
        raise ValueError("jump flags must be booleans or missing")
    known = np.array([not pd.isna(value) for value in flat], dtype=bool).reshape(values.shape)
    jumped = np.array([bool(value) if not pd.isna(value) else False for value in flat], dtype=bool).reshape(values.shape)
    return jumped, ~known


def _returns(prices: np.ndarray, jumps: np.ndarray, missing_quality: np.ndarray, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    n, stocks = prices.shape
    positions = np.arange(n)
    full = positions + horizon < n
    endpoints = np.minimum(positions + horizon, max(n - 1, 0))
    valid_anchor = np.isfinite(prices) & (prices > 0)
    terminal = prices[endpoints]
    valid_endpoint = np.isfinite(terminal) & (terminal > 0)
    jump_prefix = np.vstack((np.zeros((1, stocks), dtype=np.int64), np.cumsum(jumps, axis=0, dtype=np.int64)))
    missing_prefix = np.vstack((np.zeros((1, stocks), dtype=np.int64), np.cumsum(missing_quality, axis=0, dtype=np.int64)))
    has_jump = jump_prefix[endpoints + 1] - jump_prefix[positions] > 0
    quality_unknown = missing_prefix[endpoints + 1] - missing_prefix[positions] > 0
    reasons = np.full(prices.shape, None, dtype=object)
    reasons[~valid_endpoint] = "invalid_endpoint"
    reasons[~valid_anchor] = "invalid_anchor"
    reasons[quality_unknown] = "quality_unknown"
    reasons[has_jump] = "unexplained_jump"
    reasons[~full] = "window_end"
    known = full[:, None] & valid_anchor & valid_endpoint & ~has_jump & ~quality_unknown
    values = np.full(prices.shape, np.nan)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        np.divide(terminal, prices, out=values, where=known)
    values[known] -= 1.0
    nonfinite = known & ~np.isfinite(values)
    reasons[nonfinite] = "nonfinite_return"
    values[nonfinite] = np.nan
    return values, reasons


def holding_values(
    close_matrix: pd.DataFrame,
    industry_ref: Mapping[str, str],
    benchmark_close: pd.Series,
    retrospective_states: pd.Series,
    *,
    horizons: Sequence[int] = (126, 252),
    jump_matrix: pd.DataFrame | None = None,
    benchmark_jump: pd.Series | None = None,
    anchors: Mapping[str, Sequence[int]] | None = None,
) -> pd.DataFrame:
    """Return all stock/anchor/horizon endpoint and future-state diagnostics.

    ``industry_ref`` is the complete fixed ordinary-stock inventory, including
    columns containing entirely missing prices. Blank classifications remain
    unknown. Peers have the same reference industry and exclude the subject;
    no t0 liquidity filter is introduced. Endpoint returns tolerate ordinary
    interior missing prices, but any jump or unknown jump status over the
    inclusive anchor..endpoint window prevents a known return. No missing
    peer becomes zero. Omitted benchmark quality stays unknown.

    Holding state fractions count t0+1..observed end and retain unknown days.
    These use future information and are not t0 conditions or account returns.
    ``anchors`` restricts output materialization to selected stock/calendar
    positions, in calendar order; peer reductions still use the entire grid.
    Omitted stocks have no output rows, not fewer potential peers.
    No reader, publication, price preparation or label mutation runs here.
    """
    calendar = close_matrix.index
    if (
        not isinstance(calendar, pd.DatetimeIndex)
        or calendar.tz is not None
        or calendar.hasnans
        or not calendar.is_unique
        or not calendar.is_monotonic_increasing
    ):
        raise ValueError("prices require a sorted unique naive common DatetimeIndex")
    if any(day != day.normalize() for day in calendar) or len(calendar) == 0:
        raise ValueError("prices require a nonempty midnight common calendar")
    codes = tuple(close_matrix.columns)
    if not codes or not close_matrix.columns.is_unique or any(not isinstance(code, str) or not code.strip() for code in codes):
        raise ValueError("security codes require unique nonblank original strings")
    if set(industry_ref) != set(codes) or any(not isinstance(industry, str) for industry in industry_ref.values()):
        raise ValueError("reference metadata must exactly cover the fixed price-grid codes")
    if jump_matrix is not None and (not jump_matrix.index.equals(calendar) or not jump_matrix.columns.equals(close_matrix.columns)):
        raise ValueError("jump matrix must exactly match the fixed price grid")
    for name, series in (("benchmark", benchmark_close), ("retrospective", retrospective_states), ("benchmark_jump", benchmark_jump)):
        if series is not None and (not series.index.equals(calendar) or not series.index.is_unique):
            raise ValueError(f"{name} must exactly match the common calendar")
    horizon_values: list[int] = []
    for horizon in horizons:
        if isinstance(horizon, (bool, np.bool_)) or not isinstance(horizon, Integral) or horizon <= 0:
            raise ValueError("horizons must be positive integers")
        horizon_values.append(int(horizon))
    if not horizon_values or len(set(horizon_values)) != len(horizon_values):
        raise ValueError("horizons must be nonempty and unique")
    states = ["unknown" if pd.isna(value) else value for value in retrospective_states]
    if any(state not in STATES for state in states):
        raise ValueError("invalid retrospective state")
    prices = close_matrix.to_numpy(dtype=float, na_value=np.nan)
    benchmark = benchmark_close.to_numpy(dtype=float, na_value=np.nan).reshape(-1, 1)
    supplied_jumps = jump_matrix.to_numpy(dtype=object) if jump_matrix is not None else np.full(prices.shape, None)
    jumps, missing_quality = _jumps(supplied_jumps)
    benchmark_quality = benchmark_jump.to_numpy(dtype=object).reshape(-1, 1) if benchmark_jump is not None else np.full(benchmark.shape, None)
    benchmark_jumps, benchmark_missing = _jumps(benchmark_quality)
    requested: dict[str, np.ndarray] = {}
    if anchors is not None and not set(anchors).issubset(codes):
        raise ValueError("anchor codes must belong to the original fixed price grid")
    for code in codes:
        supplied = range(len(calendar)) if anchors is None else anchors.get(code, ())
        indices: list[int] = []
        for position in supplied:
            if isinstance(position, (bool, np.bool_)) or not isinstance(position, Integral) or not 0 <= position < len(calendar):
                raise ValueError("anchor positions require valid integer calendar indices")
            indices.append(int(position))
        if len(set(indices)) != len(indices):
            raise ValueError("anchor positions must be unique per stock")
        requested[code] = np.array(sorted(indices), dtype=np.int64)
    if not any(len(indices) for indices in requested.values()):
        return _empty_holding()
    groups: dict[str, list[int]] = {}
    for col, code in enumerate(codes):
        industry = industry_ref[code]
        if industry.strip() not in UNKNOWN_INDUSTRIES:
            groups.setdefault(industry, []).append(col)
    n = len(calendar)
    positions = np.arange(n, dtype=np.int64)
    dates = np.array([day.date().isoformat() for day in calendar], dtype=object)
    state_prefix = {state: np.concatenate(([0], np.cumsum(np.array([value == state for value in states], dtype=np.int64)))) for state in STATES}
    tables: list[pd.DataFrame] = []
    for horizon in horizon_values:
        own_returns, own_reasons = _returns(prices, jumps, missing_quality, horizon)
        benchmark_returns, benchmark_reasons = _returns(benchmark, benchmark_jumps, benchmark_missing, horizon)
        full = positions + horizon < n
        if jump_matrix is None:
            own_reasons[full] = "quality_layer_not_supplied"
        if benchmark_jump is None:
            benchmark_reasons[full] = "quality_layer_not_supplied"
        observed = np.minimum(horizon, n - positions - 1)
        context_reason = np.full(n, None, dtype=object)
        context_reason[observed == 0] = "no_observed_future"
        end = positions + observed
        context_counts = {state: state_prefix[state][end + 1] - state_prefix[state][positions + 1] for state in STATES}
        reductions = {
            industry: (np.isfinite(own_returns[:, members]).sum(axis=1, dtype=np.int64), np.nansum(own_returns[:, members], axis=1))
            for industry, members in groups.items()
        }
        for col, code in enumerate(codes):
            selected = requested[code]
            if len(selected) == 0:
                continue
            industry = industry_ref[code]
            industry_known = industry.strip() not in UNKNOWN_INDUSTRIES
            potential = len(groups.get(industry, ())) - 1 if industry_known else 0
            potential = max(potential, 0)
            known = np.zeros(n, dtype=np.int64)
            peer_mean = np.full(n, np.nan)
            peer_reason = np.full(n, "unknown_industry" if not industry_known else "no_peers", dtype=object)
            if potential:
                group_known, group_sum = reductions[industry]
                own_known = np.isfinite(own_returns[:, col])
                known = group_known - own_known.astype(np.int64)
                peer_sum = group_sum - np.where(own_known, own_returns[:, col], 0.0)
                np.divide(peer_sum, known, out=peer_mean, where=known > 0)
                peer_reason[:] = "no_known_peers"
                peer_reason[known > 0] = None
                peer_reason[~full] = "window_end"
            data: dict[str, Any] = {
                "security_id": code,
                "t0": dates,
                "calendar_index": positions,
                "horizon": horizon,
                "calendar_full": full,
                "censored": ~full,
                "endpoint_out_of_range": ~full,
                "observed_sessions": observed,
                "industry_ref": industry if industry_known else None,
                "own_return": own_returns[:, col],
                "own_return_reason": own_reasons[:, col],
                "peer_return": peer_mean,
                "peer_return_reason": peer_reason,
                "potential_peer_n": potential,
                "known_peer_n": known,
                "unknown_peer_n": potential - known,
                "benchmark_return": benchmark_returns[:, 0],
                "benchmark_return_reason": benchmark_reasons[:, 0],
                "holding_context_reason": context_reason,
                "information_scope": "retrospective_holding_diagnostic",
            }
            for state in STATES:
                counts = context_counts[state]
                fractions = np.full(n, np.nan)
                np.divide(counts, observed, out=fractions, where=observed > 0)
                data[f"holding_{state}_n"] = counts
                data[f"holding_{state}_fraction"] = fractions
            selected_data = {name: value[selected] if isinstance(value, np.ndarray) else value for name, value in data.items()}
            tables.append(pd.DataFrame(selected_data))
    result = pd.concat(tables, ignore_index=True)
    LOGGER.debug("Holding diagnostics stocks=%d anchors=%d horizons=%s rows=%d", len(codes), n, horizon_values, len(result))
    return result
