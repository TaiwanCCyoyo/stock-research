"""H05 daily-close measurement, not an intraday or misses-only account engine."""

from __future__ import annotations

import logging
import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import datetime, time, timedelta
from fractions import Fraction
from typing import Any

from research_core.attribution import mark_attempt_pnl
from research_core.chronology import ChronologyResult
from research_core.ledger import mark_share_claims_cents, replay_ledger

LOGGER = logging.getLogger(__name__)
INITIAL_CENTS = 200_000_000
HIT = Fraction(1, 2)
SPAN = 20


class MeasurementError(ValueError):
    """The saved evidence cannot support a complete H05 period."""


def _integer(value: Any, label: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < int(positive):
        raise MeasurementError(f"{label} must be a {'positive' if positive else 'nonnegative'} integer")
    return value


def _stamp(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(hours=8):
        raise MeasurementError("timestamps require +08:00")
    return value


def _cents(value: Any) -> int:
    # Ledger arithmetic is floating point; this tolerance only absorbs its
    # arithmetic residue, never rounds an economically meaningful fractional cent.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MeasurementError("money must be finite")
    rounded = round(value * 100)
    if not math.isclose(value, rounded / 100, rel_tol=0, abs_tol=1e-6):
        raise MeasurementError("ledger money must reconcile to cents")
    return rounded


def _trade(event: Mapping[str, Any]) -> tuple[int, int]:
    qty = _integer(event.get("qty"), "trade quantity", positive=True)
    price = event.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise MeasurementError("trade requires its positive observed/model price")
    gross = Fraction(str(price)) * qty * 100
    if gross.denominator != 1:
        raise MeasurementError("gross trade amount is not exact cents")
    costs = sum(_integer(event.get(field), field) for field in ("commission_cents", "tax_cents", "penalty_cents"))
    net = -(int(gross) + costs) if event["action"] == "BUY" else int(gross) - costs
    if Fraction(str(event.get("total"))) * 100 != net:
        raise MeasurementError("executed trade cash does not reconcile with gross and costs")
    return int(gross), costs


def _attempts(ledger: Mapping[str, Any], events: Sequence[Mapping[str, Any]], endpoint: datetime) -> list[dict[str, Any]]:
    grouped: dict[int, list[int]] = {}
    for row in ledger["cash_rows"]:
        grouped.setdefault(row["attempt_id"], []).append(row["event_index"])
    closed = {item["id"] for item in ledger["attempts"]}
    items = sorted((*ledger["attempts"], *ledger["open_attempts"]), key=lambda item: item["entry_event_index"])
    records = []
    for item in items:
        indices = grouped[item["id"]]
        buys = sells = costs = 0
        for index in indices:
            event = events[index]
            if event["action"] in {"BUY", "SELL"}:
                gross, charge = _trade(event)
                costs += charge
                if event["action"] == "BUY":
                    buys += gross
                else:
                    sells += gross
        paid = sum(_cents(item[field]) for field in ("dividend_total", "capital_return_total", "share_settlement_total"))
        captured = sells + paid - buys - costs
        actual_cash = sum(_cents(item[field]) for field in ("buy_total", "sell_total", "dividend_total", "capital_return_total", "share_settlement_total"))
        if captured != actual_cash or buys <= 0:
            raise MeasurementError("attempt cash components do not reconcile")
        unpaid = _cents(item["dividend_receivable"]) + _cents(item["capital_return_receivable"])
        settled = item["id"] in closed and unpaid == 0
        disposition = ("hit" if Fraction(captured, buys) >= HIT else "non_hit") if settled else "unknown"
        exposure_events = [events[index] for index in indices if events[index]["action"] in {"SELL", "SHARE_CASH_SETTLEMENT"}]
        flat_at = exposure_events[-1]["date"] if item["id"] in closed else None
        entry_at = events[item["entry_event_index"]]["date"]
        resolution_at = events[indices[-1]]["date"] if settled else None
        records.append({
            "id": str(item["id"]),
            "code": item["code"],
            "entry_event_index": item["entry_event_index"],
            "entry_at": entry_at,
            "flat_at": flat_at,
            "cash_resolution_at": resolution_at,
            "exposure_calendar_days": (datetime.fromisoformat(flat_at) - datetime.fromisoformat(entry_at)).days
            if flat_at
            else (endpoint - datetime.fromisoformat(entry_at)).days,
            "closed": item["id"] in closed,
            "disposition": disposition,
            "unknown_reason": None if settled else ("unpaid_cash_rights" if item["id"] in closed else "open_stock_or_share_claim"),
            "gross_buy_cents": buys,
            "gross_sell_cents": sells,
            "cost_cents": costs,
            "paid_dividend_cents": _cents(item["dividend_total"]),
            "paid_principal_cents": _cents(item["capital_return_total"]),
            "paid_fraction_cents": _cents(item["share_settlement_total"]),
            "unpaid_cash_cents": unpaid,
            "net_paid_cash_cents": captured,
            "captured_return": captured / buys if settled else None,
        })
    return records


def _erosion(ids: list[str], points: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not ids:
        return {
            "status": "unavailable",
            "attempt_ids": [],
            "reason": "no attempts in this classification",
            "net_cents": None,
            "worst_loss_cents": None,
            "peak_to_trough_cents": None,
        }
    values = [0] + [sum(point["attempt_pnl_cents"][identity] for identity in ids) for point in points]
    peak = erosion = 0
    for value in values:
        peak = max(peak, value)
        erosion = max(erosion, peak - value)
    loss = -min(values)
    return {
        "status": "ok",
        "attempt_ids": ids,
        "net_cents": values[-1],
        "worst_loss_cents": loss,
        "peak_to_trough_cents": erosion,
        "net_fraction_initial": values[-1] / INITIAL_CENTS,
        "worst_loss_fraction_initial": loss / INITIAL_CENTS,
        "peak_to_trough_fraction_initial": erosion / INITIAL_CENTS,
    }


def _nonhits(attempts: Sequence[Mapping[str, Any]], points: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    known = [item["id"] for item in attempts if item["disposition"] == "non_hit"]
    unknown = [item["id"] for item in attempts if item["disposition"] == "unknown"]
    runs: list[list[str]] = []
    block: list[str] = []
    for item in [*attempts, {"disposition": "hit"}]:
        if item["disposition"] == "non_hit":
            block.append(item["id"])
        else:
            if block:
                runs.append(block)
                block = []
    windows = []
    uncertain = False
    for index in range(max(0, len(attempts) - SPAN + 1)):
        window = attempts[index : index + SPAN]
        states = {item["disposition"] for item in window}
        if states == {"non_hit"}:
            windows.append(_erosion([item["id"] for item in window], points))
        elif "hit" not in states and "unknown" in states:
            uncertain = True
    status = "unavailable" if uncertain else ("ok" if windows else ("insufficient_windows" if len(attempts) < SPAN else "no_eligible_windows"))
    whole = _erosion(known, points)
    if known and unknown:
        whole.update(status="partial", reason="known settled non-hit subset only")
    return {
        "attribution_only": True,
        "sampling": "daily_close_plus_initial_zero",
        "denominator_cents": INITIAL_CENTS,
        "whole_study": whole,
        "unknown_attribution": _erosion(unknown, points),
        "runs": [_erosion(ids, points) for ids in runs],
        "windows": windows,
        "window_summary": {
            "status": status,
            "span": SPAN,
            "worst_peak_to_trough_fraction_initial": max(item["peak_to_trough_fraction_initial"] for item in windows) if status == "ok" else None,
        },
        "max_known_non_hit_run": max(map(len, runs), default=0),
        "classification_complete": not unknown,
    }


def _account(points: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    peak = INITIAL_CENTS
    worst = 0.0
    underwater = longest = 0
    years: dict[int, dict[str, Any]] = {}
    previous = INITIAL_CENTS
    for point in points:
        equity = point["equity_cents"]
        peak = max(peak, equity)
        worst = max(worst, 1 - equity / peak)
        underwater = underwater + 1 if equity < peak else 0
        longest = max(longest, underwater)
        year = datetime.fromisoformat(point["at"]).year
        annual = years.setdefault(year, {"year": year, "start_equity_cents": previous, "gross_buy_cents": 0, "gross_sell_cents": 0, "cost_cents": 0})
        annual["end_equity_cents"] = equity
        previous = equity
    for event in events:
        if event["action"] in {"BUY", "SELL"}:
            gross, cost = _trade(event)
            year = datetime.fromisoformat(event["date"]).year
            if year not in years:
                raise MeasurementError("trade year is outside reviewed period")
            years[year]["gross_buy_cents" if event["action"] == "BUY" else "gross_sell_cents"] += gross
            years[year]["cost_cents"] += cost
    for annual in years.values():
        annual["net_profit_cents"] = annual["end_equity_cents"] - annual["start_equity_cents"]
        annual["net_return"] = annual["net_profit_cents"] / annual["start_equity_cents"] if annual["start_equity_cents"] else None
        annual["gross_buy_turnover_initial"] = annual["gross_buy_cents"] / INITIAL_CENTS
        annual["half_two_sided_turnover_initial"] = (annual["gross_buy_cents"] + annual["gross_sell_cents"]) / (2 * INITIAL_CENTS)
        annual["direct_cost_fraction_initial"] = annual["cost_cents"] / INITIAL_CENTS
    return {
        "net_return": points[-1]["equity_cents"] / INITIAL_CENTS - 1,
        "close_max_drawdown": worst,
        "max_underwater_reviews": longest,
        "annual": list(years.values()),
    }


def measure(result: ChronologyResult, *, expected_reviews: Sequence[datetime]) -> dict[str, Any]:
    """Reconcile a complete five-slot, NT$2m chronology and retain daily evidence.

    Calendar completeness is caller-declared, not inferred from available prices.
    Only this registered H05 capital and the fixed provisional metric are supported.
    """
    if not isinstance(result, ChronologyResult) or result.status != "complete" or result.stop_reason is not None or result.pending:
        raise MeasurementError("complete chronology without pending requests is required")
    reviews = tuple(_stamp(value) for value in expected_reviews)
    if not reviews or any(value.time() != time(20) for value in reviews) or any(a.date() >= b.date() for a, b in zip(reviews, reviews[1:])):
        raise MeasurementError("expected reviews must be unique ordered 20:00 dates")
    if tuple(snapshot.as_of for snapshot in result.snapshots) != reviews:
        raise MeasurementError("snapshots do not cover the entire expected review calendar")
    events = result.events
    dates = tuple(_stamp(datetime.fromisoformat(str(event.get("date")))) for event in events)
    if any(a > b for a, b in zip(dates, dates[1:])) or (dates and (dates[0].date() < reviews[0].date() or dates[-1] > reviews[-1])):
        raise MeasurementError("events are unordered or outside the observation horizon")
    LOGGER.info("Measuring H05 complete prefix: %s events, %s reviews", len(events), len(reviews))
    final = replay_ledger(INITIAL_CENTS / 100, events, max_positions=5)
    attempts = _attempts(final, events, reviews[-1])
    closes = tuple(value.replace(hour=13, minute=30) for value in reviews)
    for attempt in attempts:
        entry = datetime.fromisoformat(attempt["entry_at"])
        flat = datetime.fromisoformat(attempt["flat_at"]) if attempt["flat_at"] else reviews[-1]
        attempt["exposure_closes"] = sum(entry <= close < flat for close in closes)
        resolution = datetime.fromisoformat(attempt["cash_resolution_at"]) if attempt["cash_resolution_at"] else None
        attempt["cash_resolution_calendar_days"] = (resolution - entry).days if resolution else None
    points = []
    cached_count = -1
    ledger: Mapping[str, Any] = final
    for snapshot in result.snapshots:
        count = _integer(snapshot.event_count, "snapshot event count")
        if count != bisect_right(dates, snapshot.as_of) or snapshot.calendar_id != result.calendar_id or snapshot.cash_basis != "trade_date_cash":
            raise MeasurementError("snapshot prefix/calendar/cash basis differs")
        if count != cached_count:
            ledger = replay_ledger(INITIAL_CENTS / 100, events[:count], max_positions=5)
            cached_count = count
        marks = {}
        for code, observation in snapshot.prices.items():
            if observation.observed_at != snapshot.as_of.replace(hour=13, minute=30) or observation.available_at > snapshot.as_of:
                raise MeasurementError("close mark is stale or unavailable at review")
            marks[code] = observation.raw_close_cents / 100
        marked = mark_attempt_pnl(ledger, marks)
        pnl = {}
        for attempt in attempts:
            identity = attempt["id"]
            if identity not in marked and count > attempt["entry_event_index"]:
                raise MeasurementError("entered attempt disappeared from prefix attribution")
            pnl[identity] = _cents(marked[identity]) if identity in marked else 0
        expected = {
            "cash_cents": _cents(ledger["cash"]),
            "receivable_cents": _cents(ledger["dividend_receivable"]) + _cents(ledger["capital_return_receivable"]),
            "capital_return_receivable_cents": _cents(ledger["capital_return_receivable"]),
            "share_claim_value_cents": mark_share_claims_cents(ledger, marks),
            "equity_cents": INITIAL_CENTS + sum(pnl.values()),
        }
        if any(_integer(getattr(snapshot, name), name) != value for name, value in expected.items()):
            raise MeasurementError("saved monetary snapshot differs from replay")
        if {code: holding.qty for code, holding in snapshot.holdings.items()} != ledger["positions"] or set(snapshot.occupied_issuer_codes) != set(
            ledger["positions"]
        ) | set(ledger["outstanding_share_codes"]):
            raise MeasurementError("saved holdings/issuer occupancy differs from replay")
        for opened in ledger["open_attempts"]:
            if opened["code"] in ledger["positions"]:
                holding = snapshot.holdings[opened["code"]]
                entry = dates[opened["entry_event_index"]]
                if (
                    holding.attempt_id != opened["id"]
                    or holding.entry_at != entry
                    or holding.completed_closes != sum(entry <= close <= snapshot.as_of for close in closes)
                ):
                    raise MeasurementError("saved holding attempt identity/age differs from replay")
        points.append({"at": snapshot.as_of.isoformat(), "event_count": count, **expected, "attempt_pnl_cents": pnl})
    nonhits = [item["net_paid_cash_cents"] for item in attempts if item["disposition"] == "non_hit"]
    LOGGER.info("H05 measurement reconciled: %s attempts; %s unknown", len(attempts), sum(item["disposition"] == "unknown" for item in attempts))
    return {
        "schema": "h05-close-measurement.v1",
        "provisional": True,
        "initial_cash_cents": INITIAL_CENTS,
        "hit_threshold": "1/2",
        "horizon": {"start": reviews[0].isoformat(), "end": reviews[-1].isoformat()},
        "attempt_order": "first_buy_event_index",
        "attempts": attempts,
        "daily": points,
        "disposition_counts": {key: sum(item["disposition"] == key for item in attempts) for key in ("hit", "non_hit", "unknown")},
        "non_hit_mean_signed_cash_cents": sum(nonhits) / len(nonhits) if nonhits else None,
        "non_hit_attribution": _nonhits(attempts, points),
        "account": _account(points, events),
    }
