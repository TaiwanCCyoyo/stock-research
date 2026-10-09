"""Descriptive H05 burden and attempt attribution; no performance recalculation."""

import logging
from bisect import bisect_right
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from fractions import Fraction
from typing import Any

from research_core.chronology import ChronologyResult
from research_core.ledger import replay_ledger

LOGGER = logging.getLogger(__name__)
INITIAL_CENTS = 200_000_000
VENUES = ("regular_open", "intraday_odd", "afterhours_odd", "unknown")


class DiagnosticError(ValueError):
    """Chronology and its supplied verified measurement do not match."""


def _validate(result: ChronologyResult, report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if not isinstance(result, ChronologyResult) or result.status != "complete" or result.stop_reason is not None or result.pending:
        raise DiagnosticError("complete chronology without pending requests required")
    if report.get("schema") != "h05-close-measurement.v1" or report.get("initial_cash_cents") != INITIAL_CENTS:
        raise DiagnosticError("verified H05 measurement identity required")
    if report.get("hit_threshold") != "1/2" or report.get("attempt_order") != "first_buy_event_index":
        raise DiagnosticError("measurement threshold/attempt ordering differs")
    if not result.snapshots or report.get("horizon") != {"start": result.snapshots[0].as_of.isoformat(), "end": result.snapshots[-1].as_of.isoformat()}:
        raise DiagnosticError("measurement horizon differs")
    daily = report.get("daily", ())
    dates = [datetime.fromisoformat(event["date"]) for event in result.events]
    if dates != sorted(dates) or (dates and dates[-1] > result.snapshots[-1].as_of):
        raise DiagnosticError("event prefix is unordered or beyond measurement")
    if len(daily) != len(result.snapshots):
        raise DiagnosticError("measurement review count differs")
    for point, snapshot in zip(daily, result.snapshots, strict=True):
        if (
            point["at"] != snapshot.as_of.isoformat()
            or point["event_count"] != snapshot.event_count
            or snapshot.event_count != bisect_right(dates, snapshot.as_of)
            or snapshot.calendar_id != result.calendar_id
        ):
            raise DiagnosticError("measurement event prefix/calendar differs")
        for field in ("cash_cents", "equity_cents", "receivable_cents", "capital_return_receivable_cents", "share_claim_value_cents"):
            if point[field] != getattr(snapshot, field):
                raise DiagnosticError("measurement monetary snapshot differs")
    final = replay_ledger(INITIAL_CENTS / 100, result.events, max_positions=5)
    native = sorted((*final["attempts"], *final["open_attempts"]), key=lambda item: item["entry_event_index"])
    attempts: list[Mapping[str, Any]] = list(report.get("attempts", ()))
    if [item["id"] for item in attempts] != [str(item["id"]) for item in native]:
        raise DiagnosticError("measurement attempt ids/order differ")
    closed = {item["id"] for item in final["attempts"]}
    gross_buys: dict[int, Fraction] = {}
    last_event: dict[int, int] = {}
    for row in final["cash_rows"]:
        identity, index = row["attempt_id"], row["event_index"]
        last_event[identity] = index
        event = result.events[index]
        if event["action"] == "BUY":
            gross_buys[identity] = gross_buys.get(identity, Fraction(0)) + Fraction(str(event["price"])) * event["qty"] * 100
    for item, ledger_attempt in zip(attempts, native, strict=True):
        entry = ledger_attempt["entry_event_index"]
        paid = round(
            sum(ledger_attempt[field] for field in ("buy_total", "sell_total", "dividend_total", "capital_return_total", "share_settlement_total")) * 100
        )
        unpaid = round((ledger_attempt["dividend_receivable"] + ledger_attempt["capital_return_receivable"]) * 100)
        is_closed = ledger_attempt["id"] in closed
        if (
            item["entry_event_index"] != entry
            or item["entry_at"] != result.events[entry]["date"]
            or item["code"] != ledger_attempt["code"]
            or item["closed"] != is_closed
            or item["net_paid_cash_cents"] != paid
            or item["unpaid_cash_cents"] != unpaid
        ):
            raise DiagnosticError("measurement attempt differs from event replay")
        if item["disposition"] not in {"hit", "non_hit", "unknown"} or (item["disposition"] == "unknown") != (not is_closed or unpaid != 0):
            raise DiagnosticError("measurement settled classification differs")
        gross = gross_buys[ledger_attempt["id"]]
        if gross <= 0 or gross.denominator != 1 or item["gross_buy_cents"] != gross:
            raise DiagnosticError("measurement gross purchases differ from actual buys")
        if is_closed and unpaid == 0:
            expected_disposition = "hit" if Fraction(paid, int(gross)) >= Fraction(1, 2) else "non_hit"
            if item["disposition"] != expected_disposition:
                raise DiagnosticError("measurement settled hit threshold classification differs")
            if item["cash_resolution_at"] != result.events[last_event[ledger_attempt["id"]]]["date"]:
                raise DiagnosticError("measurement cash resolution time differs from event replay")
    if any(set(point["attempt_pnl_cents"]) != {item["id"] for item in attempts} for point in daily):
        raise DiagnosticError("measurement daily attempt identities differ")
    return attempts


def _burden(result: ChronologyResult) -> dict[str, Any]:
    annual: dict[int, dict[str, Any]] = {}
    days: Counter[str] = Counter()
    signal_ids: set[str] = set()
    unknown_ids = []
    request_ids = {request.intent.order_id for request in result.requests()}
    unlinked_fill_indices = []

    def year(at: datetime) -> dict[str, Any]:
        return annual.setdefault(
            at.year,
            {
                "year": at.year,
                "advice_signal_ids": [],
                "unknown_signal_order_ids": [],
                "order_legs": 0,
                "route_legs": 0,
                "order_venues": dict.fromkeys(VENUES, 0),
                "route_venues": dict.fromkeys(VENUES, 0),
                "unlinked_fill_event_indices": [],
                "fills": {side: dict.fromkeys(VENUES, 0) for side in ("BUY", "SELL")},
            },
        )

    for snapshot in result.snapshots:
        year(snapshot.as_of)
    for request in result.requests():
        row = year(request.intent.decision_at)
        row["order_legs"] += 1
        row["order_venues"][request.venue] += 1
        days[request.intent.decision_at.date().isoformat()] += 1
        if request.signal is None:
            unknown_ids.append(request.intent.order_id)
            row["unknown_signal_order_ids"].append(request.intent.order_id)
        elif request.signal.signal_id not in signal_ids:
            signal_ids.add(request.signal.signal_id)
            year(request.signal.origin_at)["advice_signal_ids"].append(request.signal.signal_id)
    for window in result.windows:
        for route in window.routes:
            row = year(route.batch.auction_at)
            row["route_legs"] += 1
            row["route_venues"][route.batch.venue] += 1
    for index, event in enumerate(result.events):
        if event["action"] in {"BUY", "SELL"}:
            venue = event.get("venue", "unknown")
            if venue not in VENUES:
                raise DiagnosticError("unsupported executed fill venue")
            row = year(datetime.fromisoformat(event["date"]))
            row["fills"][event["action"]][venue] += 1
            if event.get("order_id") not in request_ids:
                unlinked_fill_indices.append(index)
                row["unlinked_fill_event_indices"].append(index)
    for row in annual.values():
        annual_days = {day: count for day, count in days.items() if int(day[:4]) == row["year"]}
        row.update(
            known_advice_signal_count=len(row["advice_signal_ids"]),
            signal_count_complete=not row["unknown_signal_order_ids"] and not row["unlinked_fill_event_indices"],
            active_order_creation_days=len(annual_days),
            max_order_legs_created_per_day=max(annual_days.values(), default=0),
        )
        row["active_advice_days"] = len({record.at.date() for record in result.decisions if record.requests and record.at.year == row["year"]})
    return {
        "annual": [annual[key] for key in sorted(annual)],
        "known_advice_signal_ids": sorted(signal_ids),
        "unknown_signal_order_ids": unknown_ids,
        "unlinked_fill_event_indices": unlinked_fill_indices,
        "signal_count_complete": not unknown_ids and not unlinked_fill_indices,
        "order_legs": len(result.requests()),
        "route_legs": sum(len(window.routes) for window in result.windows),
        "fills": {side: {venue: sum(row["fills"][side][venue] for row in annual.values()) for venue in VENUES} for side in ("BUY", "SELL")},
        "active_advice_days": len({record.at.date() for record in result.decisions if record.requests}),
        "max_order_legs_created_per_day": max(days.values(), default=0),
        "fill_count_basis": "actual BUY/SELL ledger event legs, not order or signal count",
    }


def _slots(result: ChronologyResult) -> dict[str, Any]:
    labels: dict[int, int] = {}
    occupied: dict[int, int] = {}
    slots: list[dict[str, Any]] = [
        {"slot": number, "attempt_ids": [], "issuer_codes": [], "entries": 0, "successive_attempts": 0, "issuer_changes": 0} for number in range(1, 6)
    ]
    for index, event in enumerate(result.events):
        if event["action"] not in {"BUY", "SELL", "SHARE_CASH_SETTLEMENT"}:
            continue
        ledger = replay_ledger(INITIAL_CENTS / 100, result.events[: index + 1], max_positions=5)
        current = {item["id"] for item in ledger["open_attempts"]}
        occupied = {identity: number for identity, number in occupied.items() if identity in current}
        for item in sorted(ledger["open_attempts"], key=lambda item: item["entry_event_index"]):
            identity = item["id"]
            if identity in labels:
                continue
            number = min(set(range(1, 6)) - set(occupied.values()))
            labels[identity] = occupied[identity] = number
            row = slots[number - 1]
            row["issuer_changes"] += int(bool(row["issuer_codes"]) and row["issuer_codes"][-1] != item["code"])
            row["issuer_codes"].append(item["code"])
            row["attempt_ids"].append(str(identity))
            row["entries"] += 1
            row["successive_attempts"] = row["entries"] - 1
    return {
        "basis": "descriptive lowest-free-slot labels from actual ledger event order; not policy allocation",
        "slots": slots,
        "attempt_slot": {str(key): value for key, value in labels.items()},
    }


def _gaps(attempts: list[Mapping[str, Any]]) -> dict[str, Any]:
    hits = [index for index, item in enumerate(attempts) if item["disposition"] == "hit"]
    segments = []
    bounds = [-1, *hits, len(attempts)]
    for left, right in zip(bounds, bounds[1:]):
        block = attempts[left + 1 : right]
        unknown = [item["id"] for item in block if item["disposition"] == "unknown"]
        segments.append({
            "kind": "whole_observed_prefix" if not hits else ("leading" if left == -1 else "trailing" if right == len(attempts) else "between_hits"),
            "left_hit_id": attempts[left]["id"] if left >= 0 else None,
            "right_hit_id": attempts[right]["id"] if right < len(attempts) else None,
            "attempt_ids": [item["id"] for item in block],
            "known_non_hit_count": sum(item["disposition"] == "non_hit" for item in block),
            "unknown_attempt_ids": unknown,
            "classification_complete": not unknown,
            "left_censored": left == -1,
            "right_censored": right == len(attempts),
            "exact_non_hit_gap": len(block) if left >= 0 and right < len(attempts) and not unknown else None,
        })
    return {
        "basis": "entry order and endpoint settled-hit classification; leading/trailing segments are censored",
        "hit_attempt_ids": [attempts[index]["id"] for index in hits],
        "segments": segments,
    }


def _hit_waits(attempts: list[Mapping[str, Any]], result: ChronologyResult) -> dict[str, Any]:
    start, end = result.snapshots[0].as_of, result.snapshots[-1].as_of
    hits = sorted(
        (item for item in attempts if item["disposition"] == "hit"),
        key=lambda item: (datetime.fromisoformat(item["cash_resolution_at"]), item["entry_event_index"]),
    )
    already = [item["id"] for item in hits if datetime.fromisoformat(item["cash_resolution_at"]) <= start]
    observed = [item for item in hits if datetime.fromisoformat(item["cash_resolution_at"]) > start]
    intervals = []
    previous, previous_id = start, None
    for item in observed:
        resolved = datetime.fromisoformat(item["cash_resolution_at"])
        intervals.append({
            "kind": "first_observed_hit" if previous_id is None else "between_resolved_hits",
            "start_at": previous.isoformat(),
            "end_at": resolved.isoformat(),
            "left_hit_id": previous_id,
            "right_hit_id": item["id"],
            "elapsed_days": (resolved - previous).total_seconds() / 86400,
            "left_observation_boundary": previous_id is None,
            "right_censored": False,
        })
        previous, previous_id = resolved, item["id"]
    intervals.append({
        "kind": "after_last_observed_hit" if observed else "whole_observation_without_new_hit",
        "start_at": previous.isoformat(),
        "end_at": end.isoformat(),
        "left_hit_id": previous_id,
        "right_hit_id": None,
        "elapsed_days": (end - previous).total_seconds() / 86400,
        "left_observation_boundary": previous_id is None,
        "right_censored": True,
    })
    unknown = [item["id"] for item in attempts if item["disposition"] == "unknown"]
    return {
        "basis": "descriptive endpoint hit classification sorted by actual cash resolution; elapsed 24-hour days; never historical decision inputs",
        "resolved_hit_attempt_ids": [item["id"] for item in hits],
        "already_resolved_at_first_review_ids": already,
        "uncompleted_attempt_count": len(unknown),
        "uncompleted_attempt_ids": unknown,
        "intervals": intervals,
    }


def diagnose(result: ChronologyResult, measurement_report: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize already measured attempts without a return engine or gate."""
    attempts = _validate(result, measurement_report)
    settled = [item for item in attempts if item["disposition"] != "unknown"]
    positive = sorted((item for item in settled if item["net_paid_cash_cents"] > 0), key=lambda item: (-item["net_paid_cash_cents"], item["entry_event_index"]))
    denominator = sum(item["net_paid_cash_cents"] for item in positive)
    streak = longest = 0
    loss_runs = []
    run = []
    for item in [*attempts, {"disposition": "unknown"}]:
        if item["disposition"] != "unknown" and item["net_paid_cash_cents"] < 0:
            streak += 1
            longest = max(longest, streak)
            run.append(item["id"])
        else:
            if run:
                loss_runs.append(run)
                run = []
            streak = 0
    unknown = [item["id"] for item in attempts if item["disposition"] == "unknown"]
    LOGGER.info("H05 descriptive diagnostics: %d attempts, %d unknown", len(attempts), len(unknown))
    return {
        "schema": "h05-descriptive-diagnostics.v1",
        "descriptive_only": True,
        "measurement_schema": measurement_report["schema"],
        "horizon": dict(measurement_report["horizon"]),
        "burden": _burden(result),
        "slot_labels": _slots(result),
        "hit_gaps": _gaps(attempts),
        "cash_resolved_hit_waits": _hit_waits(attempts, result),
        "positive_profit_concentration": {
            "basis": "closed settled positive net paid cash profits only; attribution, not best-trade-removal stress",
            "positive_attempt_count": len(positive),
            "excluded_unsettled_count": len(unknown),
            "positive_profit_sum_cents": denominator,
            "top1_fraction": positive[0]["net_paid_cash_cents"] / denominator if denominator else None,
            "top3_fraction": sum(item["net_paid_cash_cents"] for item in positive[:3]) / denominator if denominator else None,
            "ranked_attempt_ids": [item["id"] for item in positive],
        },
        "net_loss_streak": {
            "max_known": longest,
            "known_runs": loss_runs,
            "unknown_attempt_ids": unknown,
            "classification_complete": not unknown,
            "basis": "entry order; nonnegative settled profit and unknown break known loss runs",
        },
        "holding_durations": [
            {
                key: item[key]
                for key in ("id", "entry_at", "flat_at", "cash_resolution_at", "exposure_calendar_days", "exposure_closes", "cash_resolution_calendar_days")
            }
            for item in attempts
        ],
    }
