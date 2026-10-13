"""Annual ranking and raw-price reinvestment scenarios, with explicit unknowns.

Cash amounts are supplied estimates. This model neither infers missing economic
rights from price factors nor certifies historical universe or queue availability.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.price_basis import prepare_prices

LOGGER = logging.getLogger(__name__)
VERSION = "annual-rotation.v1"


def economic_path(
    raw: pd.DataFrame,
    actions: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    start_field: str = "Open",
    end_field: str = "Open",
    commission: float = 0.0,
    sell_tax: float = 0.0,
    slippage: float = 0.0,
    split_ratios: dict[str, float] | None = None,
    known_halts: set[str] | None = None,
    entry_cost: bool = True,
    exit_cost: bool = True,
) -> dict[str, Any]:
    """Return wealth per initial unit; unusable paths return a named unknown.

    An ex-date at the initial purchase is not an entitlement. On an open-price
    exit, that day's dividend stays cash, since the stock is sold before the
    assumed close reinvestment. An exact split on exit applies before sale.
    Known halts carry the previous mark, never invent a quote or a fill.
    """
    if start_field not in {"Open", "Close"} or end_field not in {"Open", "Close"}:
        raise ValueError("endpoint field must be Open or Close")
    if start >= end or start not in calendar or end not in calendar:
        raise ValueError("ordered calendar endpoints required")
    if any(not np.isfinite(value) or value < 0 or value >= 1 for value in (commission, sell_tax, slippage)):
        raise ValueError("cost fractions must be finite in [0,1)")
    if commission + sell_tax >= 1:
        raise ValueError("combined exit costs must be below proceeds")
    days = calendar[(calendar >= start) & (calendar <= end)]
    code = str(raw.Code.iloc[0])
    events = actions.loc[actions.code.astype(str).eq(code) & pd.to_datetime(actions.ex_date).between(start, end)].copy()
    quotes = raw.loc[raw.Date.between(start, end)]
    frame = prepare_prices(quotes, events, days, basis="raw", cutoff=end)
    ratios, halts = split_ratios or {}, known_halts or set()
    unknowns: list[str] = []
    for raw_day, row in frame.iterrows():
        day = cast(pd.Timestamp, raw_day)
        permitted_missing_halt = str(day.date()) in halts and row.quality_reason == "missing_official_quote"
        if not bool(row.Quality) and not permitted_missing_halt:
            unknowns.append(f"{day.date()}:{row.quality_reason}")
    if unknowns:
        return {"status": "unknown", "reasons": unknowns, "gross_multiplier": None, "net_multiplier": None}
    entry = float(frame.loc[start, f"Raw{start_field}"])
    exit_price = float(frame.loc[end, f"Raw{end_field}"])
    if not np.isfinite(entry) or not np.isfinite(exit_price) or min(entry, exit_price) <= 0:
        return {"status": "unknown", "reasons": ["missing_endpoint_price"], "gross_multiplier": None, "net_multiplier": None}
    by_day: dict[pd.Timestamp, pd.DataFrame] = dict(tuple(events.groupby(pd.to_datetime(events.ex_date))))
    gross_units = 1 / entry
    net_units = 1 / (entry * (1 + slippage) * (1 + commission)) if entry_cost else 1 / entry
    marks: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    last_mark = entry
    for raw_day, row in frame.iterrows():
        day = cast(pd.Timestamp, raw_day)
        cash_gross = cash_net = 0.0
        day_events = by_day.get(day)
        if day > start and day_events is not None:
            if len(day_events) != 1:
                unknowns.append(f"{day.date()}:ambiguous_same_day_actions")
                break
            event = day_events.iloc[0]
            kind = str(event.event_type)
            if kind == "CASH_DIVIDEND":
                dividend = float(event.cash_dividend_estimate)
                if not np.isfinite(dividend) or dividend < 0:
                    unknowns.append(f"{day.date()}:missing_or_negative_cash_estimate")
                    break
                if day == end and end_field == "Open":
                    cash_gross, cash_net = gross_units * dividend, net_units * dividend
                else:
                    close = float(row.RawClose)
                    if not np.isfinite(close) or close <= 0:
                        unknowns.append(f"{day.date()}:missing_dividend_reinvestment_close")
                        break
                    gross_units *= 1 + dividend / close
                    net_units *= 1 + dividend / (close * (1 + commission))
                applied.append({"date": str(day.date()), "type": kind, "cash_per_unit_estimate": dividend})
            elif kind in {"ETF_SPLIT", "ETF_REVERSE_SPLIT"}:
                ratio = ratios.get(str(day.date()))
                if ratio is None or not np.isfinite(ratio) or ratio <= 0:
                    unknowns.append(f"{day.date()}:missing_exact_share_ratio")
                    break
                gross_units *= ratio
                net_units *= ratio
                applied.append({"date": str(day.date()), "type": kind, "exact_share_ratio": ratio})
            else:
                unknowns.append(f"{day.date()}:unsupported_economic_action:{kind}")
                break
        mark = float(row.RawClose)
        if str(day.date()) in halts and not np.isfinite(mark):
            mark = last_mark
        last_mark = mark
        if day == end:
            gross_value = gross_units * exit_price + cash_gross
            net_value = net_units * exit_price * ((1 - slippage) * (1 - commission - sell_tax) if exit_cost else 1) + cash_net
        elif day == start and start_field == "Close":
            gross_value, net_value = 1.0, net_units * entry
        else:
            gross_value, net_value = gross_units * mark, net_units * mark
        marks.append({"date": str(day.date()), "gross": gross_value, "net": net_value, "mark_observed": bool(row.Quality)})
    # A non-calendar event inside the holding cannot silently disappear.
    noncalendar = [str(day.date()) for day in by_day if day not in days and day > start]
    unknowns.extend(f"{day}:noncalendar_action" for day in noncalendar)
    if unknowns:
        LOGGER.debug("Unresolved economic path start=%s end=%s reasons=%s", start, end, unknowns)
        return {"status": "unknown", "reasons": unknowns, "gross_multiplier": None, "net_multiplier": None}
    return {
        "status": "modeled",
        "reasons": [],
        "raw_entry": entry,
        "raw_exit": exit_price,
        "gross_multiplier": marks[-1]["gross"],
        "net_multiplier": marks[-1]["net"],
        "marks": marks,
        "events": applied,
    }


def annual_candidates(raw: pd.DataFrame, actions: pd.DataFrame, calendar: pd.DatetimeIndex, *, year: int) -> dict[str, Any]:
    """Calculate one symbol/year from its historical prefix only."""
    years = pd.Series(calendar).dt.year.to_numpy()
    year_days = calendar[years == year]
    if not len(year_days):
        raise ValueError("ranking year missing from calendar")
    prior = calendar[years < year]
    start = cast(pd.Timestamp, prior[-1] if len(prior) else year_days[0])
    end = cast(pd.Timestamp, year_days[-1])
    window = calendar[(calendar >= start) & (calendar <= end)]
    selected_actions = actions.loc[pd.to_datetime(actions.ex_date).between(start, end)]
    economic = economic_path(raw, selected_actions, calendar, start=start, end=end, start_field="Close", end_field="Close")
    reference = prepare_prices(raw.loc[raw.Date.between(start, end)], selected_actions, window, basis="reference_factor_adjusted", cutoff=end)
    usable = bool(reference.Quality.all())
    factor_return = float(reference.Close.iloc[-1] / reference.Close.iloc[0] - 1) if usable else None
    if not bool(raw.Date.eq(start).any()):
        economic["status"] = "ineligible"
        economic["reasons"] = ["missing_initial_anchor_new_listing_or_coverage_gap"]
    return {
        "year": year,
        "code": str(raw.Code.iloc[0]),
        "anchor_date": str(start.date()),
        "decision_date": str(end.date()),
        "ranking_gross_return": None if economic["gross_multiplier"] is None else economic["gross_multiplier"] - 1,
        "ranking_status": economic["status"],
        "ranking_reasons": economic["reasons"][:10],
        "ranking_reason_count": len(economic["reasons"]),
        "reference_factor_return_diagnostic": factor_return,
        "raw_anchor_close": None if not np.isfinite(reference.RawClose.iloc[0]) else float(reference.RawClose.iloc[0]),
        "raw_end_close": None if not np.isfinite(reference.RawClose.iloc[-1]) else float(reference.RawClose.iloc[-1]),
        "observed_calendar_quotes": int(reference.RawClose.notna().sum()),
        "required_calendar_quotes": len(window),
    }


def select_leaders(candidates: list[dict[str, Any]], *, count: int = 1) -> list[dict[str, Any]]:
    """Select calculable leaders; unknown candidates remain in the caller's audit."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("positive leader count required")
    usable = [row for row in candidates if row["ranking_gross_return"] is not None]
    if any(not np.isfinite(row["ranking_gross_return"]) for row in usable):
        raise ValueError("nonfinite rank return")
    return sorted(usable, key=lambda row: (-row["ranking_gross_return"], row["code"]))[:count]


def first_observed_trade(raw: pd.DataFrame, calendar: pd.DatetimeIndex, *, on_or_after: pd.Timestamp, avoid_one_price: bool = False) -> pd.Timestamp | None:
    """Find an observed positive-volume valid open; this is not a fill guarantee."""
    quotes = raw.loc[raw.Date >= on_or_after].sort_values("Date")
    for row in quotes.itertuples(index=False):
        prices = [row.Open, row.High, row.Low, row.Close]
        if row.Date not in calendar or not all(np.isfinite(value) and value > 0 for value in prices):
            continue
        if row.High < max(prices) or row.Low > min(prices) or not np.isfinite(row.Volume) or row.Volume <= 0:
            continue
        if avoid_one_price and row.High == row.Low:
            continue
        return cast(pd.Timestamp, row.Date)
    return None


def paired_benchmark_path(raw: pd.DataFrame, actions: pd.DataFrame, calendar: pd.DatetimeIndex, strategy: dict[str, Any], **policy: Any) -> dict[str, Any]:
    """Require exact strategy dates; never find different benchmark endpoints."""
    if strategy.get("entry_date") is None or strategy.get("exit_date") is None:
        return {"status": "unknown", "reasons": ["missing_strategy_endpoints"], "gross_multiplier": None, "net_multiplier": None}
    start = cast(pd.Timestamp, pd.Timestamp(strategy["entry_date"]))
    end = cast(pd.Timestamp, pd.Timestamp(strategy["exit_date"]))
    if pd.isna(start) or pd.isna(end) or start >= end:
        return {"status": "unknown", "reasons": ["unordered_strategy_endpoints"], "gross_multiplier": None, "net_multiplier": None}
    return economic_path(
        raw,
        actions,
        calendar,
        start=start,
        end=end,
        end_field="Close" if strategy["is_ytd"] else "Open",
        **policy,
    )


def annual_holding(
    raw: pd.DataFrame, actions: pd.DataFrame, calendar: pd.DatetimeIndex, *, year: int, full_year_through: int, avoid_one_price: bool = False, **policy: Any
) -> dict[str, Any]:
    """Keep a chosen issuer and unresolved endpoints even when a mark is absent."""
    year_days = calendar[pd.Series(calendar).dt.year.to_numpy() == year]
    if not len(year_days) or raw.empty:
        raise ValueError("nonempty issuer history and trading-year calendar required")
    scheduled = cast(pd.Timestamp, year_days[0])
    entry = first_observed_trade(raw, calendar, on_or_after=scheduled, avoid_one_price=avoid_one_price)
    is_ytd = year > full_year_through
    future = calendar[calendar >= pd.Timestamp(f"{year + 1}-01-01")]
    end = (
        cast(pd.Timestamp, calendar[-1])
        if is_ytd
        else first_observed_trade(raw, calendar, on_or_after=cast(pd.Timestamp, future[0]), avoid_one_price=avoid_one_price)
        if len(future)
        else None
    )
    info = {
        "code": str(raw.Code.iloc[0]),
        "year": year,
        "scheduled_entry": str(scheduled.date()),
        "entry_date": None if entry is None else str(entry.date()),
        "exit_date": None if end is None else str(end.date()),
        "is_ytd": is_ytd,
        "exit_kind": "mark_close_liquidation_scenario" if is_ytd else "observed_open_scenario",
    }
    if entry is None or end is None or entry >= end or entry.year != year:
        return {
            **info,
            "status": "unknown",
            "position_status": "unresolved",
            "reasons": ["missing_or_unordered_execution_endpoints"],
            "raw_entry": None,
            "raw_exit": None,
            "gross_multiplier": None,
            "net_multiplier": None,
        }
    result = economic_path(raw, actions, calendar, start=entry, end=end, end_field="Close" if is_ytd else "Open", **policy)
    for key, date, field in (("raw_entry", entry, "Open"), ("raw_exit", end, "Close" if is_ytd else "Open")):
        observations = raw.loc[raw.Date.eq(date), field]
        value = float(observations.iloc[0]) if len(observations) == 1 else np.nan
        result[key] = value if np.isfinite(value) and value > 0 else None
        if result[key] is None:
            result["reasons"].append(f"{date.date()}:ambiguous_or_missing_{key}")
    return {**info, **result, "position_status": "unresolved" if result["status"] == "unknown" else "modeled_exit_or_mark"}
