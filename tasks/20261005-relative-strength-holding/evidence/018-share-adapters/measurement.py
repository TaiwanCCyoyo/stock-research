"""Native share-claim measurement adapter over the immutable 006 bridge helpers."""

from __future__ import annotations

import hashlib
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from research_core.attribution import non_hit_attribution
from research_core.attribution_inputs import build_attribution_inputs
from research_core.ledger import replay_ledger

BASE = Path(__file__).resolve().parents[1] / "006-artifacts-5fe106d423484ccf959cc4e2e5d6f6d3"
SOURCE = BASE / "prototype/measurement_bridge.py"
SOURCE_SHA256 = "be991589b60f90ddca87e381ed6fd1909b53a655c4c5b28f624bdd751eecbb2f"  # pragma: allowlist secret
if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
    raise RuntimeError("006 measurement algorithm identity changed")
sys.path.insert(0, str(BASE))
from prototype import measurement_bridge as original  # noqa: E402
from prototype.measurement_bridge import EvidenceGap, MarkPolicy, MeasurementError, SessionClose, ValuationCalendar  # noqa: E402

if Path(original.__file__).resolve() != SOURCE.resolve():
    raise RuntimeError("006 measurement import resolves to a different packet")

PRIMARY_DENOMINATOR_TWD = original.PRIMARY_DENOMINATOR_TWD
PROVISIONAL_HIT_THRESHOLD = original.PROVISIONAL_HIT_THRESHOLD
NON_HIT_WINDOW = original.NON_HIT_WINDOW


@dataclass(frozen=True)
class AttemptSpan:
    opened_at: datetime
    closed_at: datetime | None


@dataclass
class CapturedCash:
    attempt_id: str
    code: str
    closed: bool
    gross_purchase: float = 0.0
    gross_sale: float = 0.0
    dividends_paid: float = 0.0
    capital_returns_paid: float = 0.0
    share_cash_settlements: float = 0.0
    costs: float = 0.0
    unpaid_dividends: float = 0.0
    unpaid_capital_returns: float = 0.0
    unpaid_entitlement_ids: tuple[str, ...] = ()
    outstanding_share_claim_ids: tuple[str, ...] = ()
    net_cash_flow: float = 0.0
    evidence_missing: tuple[str, ...] = ()

    @property
    def captured_return(self) -> float | None:
        if not self.closed or self.gross_purchase <= 0 or self.evidence_missing or self.outstanding_share_claim_ids:
            return None
        return self.net_cash_flow / self.gross_purchase

    @property
    def disposition(self) -> str:
        if not self.closed or self.outstanding_share_claim_ids:
            return "open"
        if self.evidence_missing:
            return "unresolved_missing_evidence"
        if self.gross_purchase <= 0:
            return "unresolved_no_gross_purchase"
        assert self.captured_return is not None
        return "hit" if self.captured_return >= PROVISIONAL_HIT_THRESHOLD else "non_hit"


def _event_costs(event: Mapping[str, Any]) -> float:
    cents = 0
    for name in ("commission_cents", "tax_cents", "penalty_cents"):
        value = event.get(name, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MeasurementError(f"{name} must be a nonnegative integer number of cents")
        cents += value
    return cents / 100.0


def _event_price(event: Mapping[str, Any]) -> float:
    value = event.get("price")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise MeasurementError(f"{event.get('action')} {event.get('code')} has no positive modelled execution price")
    return float(value)


def _spans_from_replay(initial_cash: float, events: Sequence[Mapping[str, Any]], max_positions: int, membership: Mapping[int, str]) -> dict[str, AttemptSpan]:
    """Use ledger state transitions, never a local SELL/quantity closure rule."""
    opened: dict[str, datetime] = {}
    closed: dict[str, datetime] = {}
    for index, event in enumerate(events):
        identity = membership[index]
        opened.setdefault(identity, original._aware(event["date"], "event date"))
        ledger = replay_ledger(initial_cash, events[: index + 1], max_positions=max_positions)
        if identity in {str(item["id"]) for item in ledger["attempts"]}:
            closed.setdefault(identity, original._aware(event["date"], "event date"))
    return {identity: AttemptSpan(moment, closed.get(identity)) for identity, moment in opened.items()}


def captured_cash(
    initial_cash: float, events: Sequence[Mapping[str, Any]], *, max_positions: int, evidence_gaps: Sequence[EvidenceGap] = ()
) -> tuple[dict[str, CapturedCash], dict[str, Any]]:
    """Decompose native ledger attempts without translating share or cash actions."""
    ledger = replay_ledger(initial_cash, events, max_positions=max_positions)
    rows: dict[str, CapturedCash] = {}
    for items, closed in ((ledger["attempts"], True), (ledger["open_attempts"], False)):
        for item in items:
            identity = str(item["id"])
            unpaid_dividend_ids = [str(claim["id"]) for claim in ledger["dividend_entitlements"] if not claim["paid"] and str(claim["attempt_id"]) == identity]
            unpaid_capital_ids = [
                str(claim["id"]) for claim in ledger["capital_return_entitlements"] if not claim["paid"] and str(claim["attempt_id"]) == identity
            ]
            share_ids = [str(claim["id"]) for claim in ledger["share_claims"] if str(claim["attempt_id"]) == identity]
            rows[identity] = CapturedCash(
                attempt_id=identity,
                code=str(item["code"]),
                closed=closed,
                dividends_paid=float(item["dividend_total"]),
                capital_returns_paid=float(item["capital_return_total"]),
                share_cash_settlements=float(item.get("share_settlement_total", 0.0)),
                unpaid_dividends=float(item["dividend_receivable"]),
                unpaid_capital_returns=float(item["capital_return_receivable"]),
                unpaid_entitlement_ids=tuple(unpaid_dividend_ids + unpaid_capital_ids + share_ids),
                outstanding_share_claim_ids=tuple(share_ids),
            )
    membership = {int(row["event_index"]): str(row["attempt_id"]) for row in ledger["cash_rows"]}
    buy_costs = dict.fromkeys(rows, 0.0)
    sell_costs = dict.fromkeys(rows, 0.0)
    for index, event in enumerate(events):
        action, identity = str(event["action"]).upper(), membership[index]
        if action not in {"BUY", "SELL"}:
            continue
        row, price, qty, costs = rows[identity], _event_price(event), int(event["qty"]), _event_costs(event)
        row.costs += costs
        if action == "BUY":
            row.gross_purchase += qty * price
            buy_costs[identity] += costs
        else:
            row.gross_sale += qty * price
            sell_costs[identity] += costs
    items = {str(item["id"]): item for item in (*ledger["attempts"], *ledger["open_attempts"])}
    for identity, row in rows.items():
        item = items[identity]
        expected = row.gross_sale + row.dividends_paid + row.capital_returns_paid + row.share_cash_settlements - row.gross_purchase - row.costs
        row.net_cash_flow = expected
        closed_cash = item.get("net_cash_flow")
        if (
            not math.isclose(float(item["buy_total"]), -(row.gross_purchase + buy_costs[identity]), rel_tol=0, abs_tol=original.RECONCILE_TOLERANCE_TWD)
            or not math.isclose(float(item["sell_total"]), row.gross_sale - sell_costs[identity], rel_tol=0, abs_tol=original.RECONCILE_TOLERANCE_TWD)
            or (closed_cash is not None and not math.isclose(float(closed_cash), expected, rel_tol=0, abs_tol=original.RECONCILE_TOLERANCE_TWD))
        ):
            raise MeasurementError(f"attempt {identity} does not reconcile with native ledger cash")
    spans = _spans_from_replay(initial_cash, events, max_positions, membership)
    owners = {
        str(claim["id"]): str(claim["attempt_id"])
        for claims in (ledger["dividend_entitlements"], ledger["capital_return_entitlements"], ledger["share_claim_history"])
        for claim in claims
    }
    for gap in evidence_gaps:
        identity = _gap_attempt(gap, spans, rows, owners)
        rows[identity].evidence_missing = (*rows[identity].evidence_missing, gap.describe())
    return rows, ledger


def _gap_attempt(gap: EvidenceGap, spans: Mapping[str, AttemptSpan], rows: Mapping[str, CapturedCash], owners: Mapping[str, str]) -> str:
    """Attach a gap to the ledger-owned attempt span or explicit claim owner."""
    moment = original._aware(gap.at, "evidence gap timestamp")
    if gap.entitlement_id is not None:
        identity = owners.get(gap.entitlement_id)
        if identity is None:
            raise MeasurementError(f"evidence gap names unknown entitlement {gap.entitlement_id}")
        if rows[identity].code != gap.code:
            raise MeasurementError(f"evidence gap code {gap.code} does not match entitlement {gap.entitlement_id}")
        return identity
    matches = [
        identity
        for identity, span in spans.items()
        if rows[identity].code == gap.code and span.opened_at <= moment and (span.closed_at is None or moment <= span.closed_at)
    ]
    if len(matches) != 1:
        raise MeasurementError(f"evidence gap for {gap.code} at {gap.at} does not identify exactly one attempt")
    return matches[0]


def missing_marks(
    initial_cash: float, events: Sequence[Mapping[str, Any]], checkpoints: Sequence[Mapping[str, Any]], *, max_positions: int
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for point in checkpoints:
        ledger = replay_ledger(initial_cash, events[: int(point["event_count"])], max_positions=max_positions)
        codes = set(ledger["positions"]) | set(ledger["outstanding_share_codes"])
        absent = sorted(code for code in codes if code not in point["raw_marks"])
        if absent:
            found.append({"date": point["date"], "event_count": point["event_count"], "kind": point.get("kind"), "codes": absent})
    return found


def _row_report(row: CapturedCash) -> dict[str, Any]:
    return {
        "code": row.code,
        "gross_purchase_twd": row.gross_purchase,
        "gross_sale_twd": row.gross_sale,
        "dividends_paid_twd": row.dividends_paid,
        "capital_returns_paid_twd": row.capital_returns_paid,
        "share_cash_settlements_twd": row.share_cash_settlements,
        "costs_twd": row.costs,
        "unpaid_dividends_twd": row.unpaid_dividends,
        "unpaid_capital_returns_twd": row.unpaid_capital_returns,
        "distributions_twd": row.dividends_paid + row.capital_returns_paid + row.share_cash_settlements,
        "unpaid_entitlements_twd": row.unpaid_dividends + row.unpaid_capital_returns,
        "unpaid_entitlement_ids": list(row.unpaid_entitlement_ids),
        "outstanding_share_claim_ids": list(row.outstanding_share_claim_ids),
        "captured_cash_twd": row.net_cash_flow,
        "captured_return": row.captured_return,
        "disposition": row.disposition,
        "evidence_missing": list(row.evidence_missing),
    }


def measure(
    *,
    initial_cash: float,
    events: Sequence[Mapping[str, Any]],
    marks: MarkPolicy,
    endpoint: datetime,
    max_positions: int,
    calendar: ValuationCalendar | None = None,
    session_closes: Sequence[SessionClose] = (),
    evidence_gaps: Sequence[EvidenceGap] = (),
    span: int = NON_HIT_WINDOW,
) -> dict[str, Any]:
    """Measure a native cash/share prefix; unmarked claims return labelled incomplete evidence."""
    prefix = original.recorded_prefix(events, endpoint)
    known_gaps, later_gaps = original.visible_gaps(evidence_gaps, endpoint)
    rows = captured_cash(initial_cash, prefix, max_positions=max_positions, evidence_gaps=known_gaps)[0]
    classifications = {identity: True if row.disposition == "hit" else False if row.disposition == "non_hit" else None for identity, row in rows.items()}
    checkpoints = original.build_checkpoints(prefix, marks=marks, endpoint=endpoint, session_closes=session_closes)
    valuation = original._valuation_verdict(calendar, checkpoints, endpoint, marks)
    absent = missing_marks(initial_cash, prefix, checkpoints, max_positions=max_positions)
    ordered = sorted(rows, key=lambda identity: (rows[identity].code, identity))
    if absent:
        valuation = {**valuation, "status": "incomplete_missing_marks", "reason": "a held code or outstanding share claim has no mark", "missing_marks": absent}
        attribution: dict[str, Any] = {
            "status": "unavailable",
            "reason": "missing valuation evidence",
            "metric": "non_hit_attribution.v1",
            "attribution_only": True,
            "whole_study": None,
            "unclassified_attribution": None,
            "runs": [],
            "windows": [],
            "window_summary": {"status": "unavailable", "worst_peak_to_trough_fraction_start": None},
            "unknown_attempt_ids": [key for key, value in classifications.items() if value is None],
            "classification_complete": False,
        }
        account: dict[str, Any] = {"status": "unavailable", "reason": "missing valuation evidence", "missing_marks": absent}
    else:
        inputs = build_attribution_inputs(
            initial_cash=initial_cash, events=prefix, checkpoints=checkpoints, classifications=classifications, max_positions=max_positions
        )
        attribution = non_hit_attribution(inputs["attempts"], inputs["checkpoints"], initial_equity=inputs["initial_equity"], span=span)
        ordered = [item["id"] for item in inputs["attempts"]]
        for metric in (attribution["whole_study"], attribution["unclassified_attribution"], *attribution["runs"], *attribution["windows"]):
            metric.update(original._fixed_fractions(metric))
            metric["valuation_status"] = valuation["status"]
        account = original._account_path(inputs["checkpoints"], valuation)
    counts: dict[str, int] = {}
    for identity in ordered:
        counts[rows[identity].disposition] = counts.get(rows[identity].disposition, 0) + 1
    return {
        "schema": "prototype-share-measurement.v1",
        "base_measurement_source_sha256": SOURCE_SHA256,
        "endpoint": endpoint.isoformat(),
        "policy": {
            "hit_threshold": PROVISIONAL_HIT_THRESHOLD,
            "hit_threshold_status": "provisional; selected in development-measurement, NOT owner-approved",
            "span": span,
            "primary_denominator_twd": PRIMARY_DENOMINATOR_TWD,
            "max_positions": max_positions,
            "marks_basis": marks.basis,
            "gross_purchase_denominator": "original gross purchases; never reduced by returned principal",
            "slippage": "already embedded in the modelled execution price; not subtracted again",
        },
        "captured_cash": {identity: _row_report(rows[identity]) for identity in ordered},
        "attempt_order": ordered,
        "disposition_counts": counts,
        "non_hit_attribution": attribution,
        "account": account,
        "valuation": valuation,
        "completeness": {
            "classification_complete": attribution.get("classification_complete", False),
            "valuation_complete": valuation["status"] == "complete",
            "unresolved_attempt_ids": attribution["unknown_attempt_ids"],
            "evidence_basis": "caller_supplied_complete_recorded_events_and_marks" if not absent else None,
            "attribution_only": True,
            "events_recorded": len(prefix),
            "events_after_endpoint": len(events) - len(prefix),
            "checkpoints": len(checkpoints),
            "unpaid_entitlements_twd": sum(row.unpaid_dividends + row.unpaid_capital_returns for row in rows.values()),
            "evidence_gaps": [gap.describe() for gap in known_gaps],
            "evidence_gaps_after_endpoint": [gap.describe() for gap in later_gaps],
        },
    }


__all__ = ["CapturedCash", "EvidenceGap", "MarkPolicy", "MeasurementError", "SessionClose", "ValuationCalendar", "captured_cash", "measure", "missing_marks"]
