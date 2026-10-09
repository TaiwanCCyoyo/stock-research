"""Small, policy-free replay helpers for executed shared-capital events.

Event dictionaries are replayed in supplied order.  ``BUY`` totals are negative
(including all costs); ``SELL`` totals are net proceeds and paid ``DIVIDEND``
totals are positive. A nonpositive ``SELL`` requires explicit reconciled gross
proceeds and costs, with enough cash to pay any shortfall. A ``SPLIT`` has a zero
total. ``DIVIDEND_ENTITLEMENT`` records an explicit, non-spendable receivable
with a zero total. ``CAPITAL_RETURN_ENTITLEMENT`` and linked ``CAPITAL_RETURN``
do the same for returned principal, in separate fields from dividends. A cash deficit greater than the
documented floating-point tolerance is invalid.  The tolerance is
``1e-9 * max(1, abs(initial_cash))`` and a residual within it is normalized to
zero.

This module reconstructs accounting facts only.  It does not select trades,
infer hits, impose position limits by default, or evaluate research gates.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from fractions import Fraction
from typing import Any


class LedgerError(ValueError):
    """Raised when an event stream cannot be reconciled as a cash ledger."""


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise LedgerError(f"{name} must be finite")
    return float(value)


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LedgerError(f"{name} must be a positive integer")
    return value


def _event_text(event: Mapping[str, Any], name: str) -> str:
    value = event.get(name)
    if not isinstance(value, str) or not value:
        raise LedgerError(f"event {name} must be a non-empty string")
    return value


def _attempt(attempt_id: int, code: str) -> dict[str, Any]:
    return {
        "id": attempt_id,
        "code": code,
        "buy_total": 0.0,
        "sell_total": 0.0,
        "dividend_total": 0.0,
        "dividend_receivable": 0.0,
        "capital_return_total": 0.0,
        "capital_return_receivable": 0.0,
        "share_settlement_total": 0.0,
        "share_claim_ids": [],
        "entry_event_index": attempt_id,
    }


def _finish_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    net_cash_flow = (
        attempt["buy_total"] + attempt["sell_total"] + attempt["dividend_total"] + attempt["capital_return_total"] + attempt["share_settlement_total"]
    )
    net_pnl = net_cash_flow + attempt["dividend_receivable"] + attempt["capital_return_receivable"]
    invested = -attempt["buy_total"]
    return {
        **attempt,
        "pnl_ex_dividend": attempt["buy_total"] + attempt["sell_total"] + attempt["capital_return_total"] + attempt["share_settlement_total"],
        "net_cash_flow": net_cash_flow,
        "net_pnl": net_pnl,
        "net_return_on_gross_buys": net_pnl / invested,
    }


def _unpaid_receivable(entitlements: Mapping[str, Mapping[str, Any]], attempt_id: int | None = None, kind: str | None = None) -> float:
    """Sum authoritative unpaid amounts instead of subtracting rounded aggregates."""
    try:
        return math.fsum(
            item["amount"]
            for item in entitlements.values()
            if item["kind"] in ("DIVIDEND", "CAPITAL_RETURN")
            and not item["paid"]
            and (attempt_id is None or item["attempt"]["id"] == attempt_id)
            and (kind is None or item["kind"] == kind)
        )
    except OverflowError as exc:
        raise LedgerError("cash receivable overflow") from exc


def replay_ledger(
    initial_cash: float,
    events: Iterable[Mapping[str, Any]],
    marks: Mapping[str, float] | None = None,
    *,
    max_positions: int | None = None,
) -> dict[str, Any]:
    """Replay strict execution events and return cash, positions, and attempts.

    ``attempts`` contains only flat-to-flat attempts.  ``open_attempts`` remains
    separate so an unrealized position cannot be mislabeled as a loss or miss.
    When supplied, ``marks`` are applied only to the final returned state.
    """
    cash = _finite(initial_cash, "initial_cash")
    if cash <= 0:
        raise LedgerError("initial_cash must be positive")
    if max_positions is not None:
        max_positions = _positive_int(max_positions, "max_positions")

    tolerance = 1e-9 * max(1.0, abs(cash))
    positions: dict[str, int] = {}
    active: dict[str, dict[str, Any]] = {}
    attempts: list[dict[str, Any]] = []
    cash_rows: list[dict[str, Any]] = []
    entitlements: dict[str, dict[str, Any]] = {}
    entitled_codes: set[str] = set()
    legacy_dividend_codes: set[str] = set()
    dividend_receivable = 0.0
    capital_return_receivable = 0.0
    capital_return_total = 0.0
    share_settlement_total = 0.0
    previous_date: Any = None
    claim: dict[str, Any] | None

    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            raise LedgerError("each event must be a mapping")
        action = _event_text(event, "action").upper()
        code = _event_text(event, "code")
        date = event.get("date")
        try:
            event_time = datetime.fromisoformat(str(date))
        except ValueError as error:
            raise LedgerError("event date must be an ISO date or datetime") from error
        if previous_date is not None:
            try:
                out_of_order = event_time < previous_date
            except TypeError as exc:
                raise LedgerError("event dates must be mutually comparable") from exc
            if out_of_order:
                raise LedgerError("event dates must be nondecreasing")
        previous_date = event_time
        total = _finite(event.get("total"), "event total")

        if action == "BUY":
            qty = _positive_int(event.get("qty"), "BUY qty")
            if total >= 0:
                raise LedgerError("BUY total must be negative")
            if code not in active and max_positions is not None and len(active) >= max_positions:
                raise LedgerError("max_positions would be exceeded")
            if cash + total < -tolerance:
                raise LedgerError("insufficient cash for BUY")
            cash += total
            if abs(cash) <= tolerance:
                cash = 0.0
            positions[code] = positions.get(code, 0) + qty
            attempt = active.setdefault(code, _attempt(index, code))
            attempt["buy_total"] += total
        elif action == "SELL":
            qty = _positive_int(event.get("qty"), "SELL qty")
            has_components = "gross_proceeds" in event or "cost_total" in event
            if has_components:
                gross = _finite(event.get("gross_proceeds"), "SELL gross_proceeds")
                costs = _finite(event.get("cost_total"), "SELL cost_total")
                if gross <= 0 or costs < 0:
                    raise LedgerError("SELL requires positive gross proceeds and nonnegative costs")
                # Reconcile original decimal/int values before binary-float
                # subtraction can swallow a cent or a large-integer difference.
                difference = Fraction(str(event["total"])) - Fraction(str(event["gross_proceeds"])) + Fraction(str(event["cost_total"]))
                if abs(difference) > Fraction(1, 1_000_000_000):
                    raise LedgerError("SELL total does not reconcile with gross proceeds minus costs")
            elif total <= 0:
                raise LedgerError("nonpositive SELL total requires gross_proceeds and cost_total")
            held = positions.get(code, 0)
            if held < qty:
                raise LedgerError("SELL exceeds current holding")
            if cash + total < -tolerance:
                raise LedgerError("insufficient cash for SELL costs")
            cash += total
            if abs(cash) <= tolerance:
                cash = 0.0
            attempt = active[code]
            attempt["sell_total"] += total
            if held == qty:
                del positions[code]
                if not _has_share_claim(entitlements, code):
                    attempts.append(active.pop(code))
            else:
                positions[code] = held - qty
        elif action == "DIVIDEND":
            if total <= 0:
                raise LedgerError("DIVIDEND total must be positive")
            entitlement_id = event.get("entitlement_id")
            if "entitlement_id" not in event:
                if code in entitled_codes:
                    raise LedgerError("DIVIDEND requires entitlement_id for a code with explicit entitlements")
                if code not in positions:
                    raise LedgerError("DIVIDEND requires a current holding")
                attempt = active[code]
                legacy_dividend_codes.add(code)
            else:
                if not isinstance(entitlement_id, str) or not entitlement_id:
                    raise LedgerError("DIVIDEND entitlement_id must be a non-empty string")
                entitlement = entitlements.get(entitlement_id)
                if entitlement is None:
                    raise LedgerError("DIVIDEND entitlement_id must reference a prior entitlement")
                if entitlement["kind"] != "DIVIDEND":
                    raise LedgerError("DIVIDEND entitlement_id has the wrong kind")
                if entitlement["paid"]:
                    raise LedgerError("DIVIDEND entitlement_id has already been paid")
                if entitlement["code"] != code:
                    raise LedgerError("DIVIDEND entitlement code does not match")
                if not math.isclose(total, entitlement["amount"], rel_tol=0.0, abs_tol=1e-9):
                    raise LedgerError("DIVIDEND total does not match entitlement amount")
                entitlement["paid"] = True
                attempt = entitlement["attempt"]
                attempt["dividend_receivable"] = _unpaid_receivable(entitlements, attempt["id"], "DIVIDEND")
                dividend_receivable = _unpaid_receivable(entitlements, kind="DIVIDEND")
            cash += total
            attempt["dividend_total"] += total
        elif action == "DIVIDEND_ENTITLEMENT":
            if total != 0:
                raise LedgerError("DIVIDEND_ENTITLEMENT total must be zero")
            if code not in positions:
                raise LedgerError("DIVIDEND_ENTITLEMENT requires a current holding")
            if code in legacy_dividend_codes:
                raise LedgerError("cannot mix legacy dividends and explicit entitlements for a code")
            entitlement_id = _event_text(event, "entitlement_id")
            if entitlement_id in entitlements:
                raise LedgerError("DIVIDEND_ENTITLEMENT entitlement_id must be globally unique")
            amount = _finite(event.get("amount"), "DIVIDEND_ENTITLEMENT amount")
            if amount <= 0:
                raise LedgerError("DIVIDEND_ENTITLEMENT amount must be positive")
            attempt = active[code]
            entitled_codes.add(code)
            entitlements[entitlement_id] = {
                "id": entitlement_id,
                "code": code,
                "attempt": attempt,
                "amount": amount,
                "kind": "DIVIDEND",
                "paid": False,
            }
            attempt["dividend_receivable"] = _unpaid_receivable(entitlements, attempt["id"], "DIVIDEND")
            dividend_receivable = _unpaid_receivable(entitlements, kind="DIVIDEND")
        elif action == "CAPITAL_RETURN_ENTITLEMENT":
            if total != 0:
                raise LedgerError("CAPITAL_RETURN_ENTITLEMENT total must be zero")
            if code not in positions:
                raise LedgerError("CAPITAL_RETURN_ENTITLEMENT requires a current holding")
            entitlement_id = _event_text(event, "entitlement_id")
            if entitlement_id in entitlements:
                raise LedgerError("CAPITAL_RETURN_ENTITLEMENT entitlement_id must be globally unique")
            amount = _finite(event.get("amount"), "CAPITAL_RETURN_ENTITLEMENT amount")
            if amount <= 0:
                raise LedgerError("CAPITAL_RETURN_ENTITLEMENT amount must be positive")
            attempt = active[code]
            entitlements[entitlement_id] = {
                "id": entitlement_id,
                "code": code,
                "attempt": attempt,
                "amount": amount,
                "kind": "CAPITAL_RETURN",
                "paid": False,
            }
            attempt["capital_return_receivable"] = _unpaid_receivable(entitlements, attempt["id"], "CAPITAL_RETURN")
            capital_return_receivable = _unpaid_receivable(entitlements, kind="CAPITAL_RETURN")
        elif action == "CAPITAL_RETURN":
            if total <= 0:
                raise LedgerError("CAPITAL_RETURN total must be positive")
            entitlement_id = _event_text(event, "entitlement_id")
            entitlement = entitlements.get(entitlement_id)
            if entitlement is None:
                raise LedgerError("CAPITAL_RETURN entitlement_id must reference a prior entitlement")
            if entitlement["kind"] != "CAPITAL_RETURN":
                raise LedgerError("CAPITAL_RETURN entitlement_id has the wrong kind")
            if entitlement["paid"]:
                raise LedgerError("CAPITAL_RETURN entitlement_id has already been paid")
            if entitlement["code"] != code:
                raise LedgerError("CAPITAL_RETURN entitlement code does not match")
            if not math.isclose(total, entitlement["amount"], rel_tol=0.0, abs_tol=1e-9):
                raise LedgerError("CAPITAL_RETURN total does not match entitlement amount")
            entitlement["paid"] = True
            attempt = entitlement["attempt"]
            attempt["capital_return_receivable"] = _unpaid_receivable(entitlements, attempt["id"], "CAPITAL_RETURN")
            capital_return_receivable = _unpaid_receivable(entitlements, kind="CAPITAL_RETURN")
            cash += total
            attempt["capital_return_total"] += total
            capital_return_total += total
        elif action == "SHARE_ENTITLEMENT":
            if total != 0:
                raise LedgerError("SHARE_ENTITLEMENT total must be zero")
            if code not in positions:
                raise LedgerError("SHARE_ENTITLEMENT requires a current holding")
            entitlement_id = _event_text(event, "entitlement_id")
            if entitlement_id in entitlements:
                raise LedgerError("SHARE_ENTITLEMENT entitlement_id must be globally unique")
            numerator = _positive_int(event.get("share_numerator"), "SHARE_ENTITLEMENT share_numerator")
            denominator = _positive_int(event.get("share_denominator"), "SHARE_ENTITLEMENT share_denominator")
            if event.get("valuation_policy") != "same-class-raw-close-cent-half-up":
                raise LedgerError("SHARE_ENTITLEMENT valuation_policy is unsupported")
            attempt = active[code]
            entitlements[entitlement_id] = {
                "id": entitlement_id,
                "code": code,
                "attempt": attempt,
                "kind": "SHARE",
                "remaining": Fraction(numerator, denominator),
                "original": Fraction(numerator, denominator),
                "delivered_qty": 0,
                "settled_fraction": Fraction(0, 1),
                "settlement_total": 0.0,
                "valuation_policy": event["valuation_policy"],
            }
            attempt["share_claim_ids"].append(entitlement_id)
        elif action == "SHARE_DELIVERY":
            if total != 0:
                raise LedgerError("SHARE_DELIVERY total must be zero")
            entitlement_id = _event_text(event, "entitlement_id")
            claim = entitlements.get(entitlement_id)
            if claim is None or claim["kind"] != "SHARE":
                raise LedgerError("SHARE_DELIVERY entitlement_id must reference a share claim")
            if claim["code"] != code or active.get(code) is not claim["attempt"]:
                raise LedgerError("SHARE_DELIVERY claim code or attempt does not match")
            qty = _positive_int(event.get("qty"), "SHARE_DELIVERY qty")
            delivered = Fraction(qty, 1)
            if delivered > claim["remaining"]:
                raise LedgerError("SHARE_DELIVERY exceeds remaining claim")
            claim["remaining"] -= delivered
            claim["delivered_qty"] += qty
            attempt = active[code]
            positions[code] = positions.get(code, 0) + qty
        elif action == "SHARE_CASH_SETTLEMENT":
            if total < 0:
                raise LedgerError("SHARE_CASH_SETTLEMENT total must be nonnegative")
            entitlement_id = _event_text(event, "entitlement_id")
            claim = entitlements.get(entitlement_id)
            if claim is None or claim["kind"] != "SHARE":
                raise LedgerError("SHARE_CASH_SETTLEMENT entitlement_id must reference a share claim")
            if claim["code"] != code or active.get(code) is not claim["attempt"]:
                raise LedgerError("SHARE_CASH_SETTLEMENT claim code or attempt does not match")
            if not 0 < claim["remaining"] < 1:
                raise LedgerError("SHARE_CASH_SETTLEMENT requires a fractional remaining claim")
            attempt = active[code]
            claim["settled_fraction"] = claim["remaining"]
            claim["settlement_total"] = total
            claim["remaining"] = Fraction(0, 1)
            cash += total
            attempt["share_settlement_total"] += total
            share_settlement_total += total
            if code not in positions and not _has_share_claim(entitlements, code):
                attempts.append(active.pop(code))
        elif action == "SPLIT":
            qty = _positive_int(event.get("new_qty"), "SPLIT new_qty")
            old_qty = _positive_int(event.get("old_qty"), "SPLIT old_qty")
            if total != 0:
                raise LedgerError("SPLIT total must be zero")
            if _has_share_claim(entitlements, code):
                raise LedgerError("SPLIT with outstanding share claims is unsupported")
            if positions.get(code) != old_qty:
                raise LedgerError("SPLIT old_qty does not match current holding")
            if "qty" in event and event["qty"] != qty - old_qty:
                raise LedgerError("SPLIT qty must be the share-count delta, not new_qty")
            attempt = active[code]
            positions[code] = qty
        else:
            raise LedgerError(f"unknown action: {action}")
        cash_rows.append({
            "event_index": index,
            "attempt_id": attempt["id"],
            "date": date,
            "cash": cash,
            "dividend_receivable": dividend_receivable,
            "capital_return_receivable": capital_return_receivable,
        })

    result: dict[str, Any] = {
        "cash": cash,
        "positions": dict(positions),
        "cash_rows": cash_rows,
        "attempts": [_finish_attempt(attempt) for attempt in attempts],
        "open_attempts": list(active.values()),
        "dividend_receivable": dividend_receivable,
        "capital_return_total": capital_return_total,
        "capital_return_receivable": capital_return_receivable,
        "share_settlement_total": share_settlement_total,
        "dividend_entitlements": [
            {"id": item["id"], "code": item["code"], "attempt_id": item["attempt"]["id"], "amount": item["amount"], "paid": item["paid"]}
            for item in entitlements.values()
            if item["kind"] == "DIVIDEND"
        ],
        "capital_return_entitlements": [
            {"id": item["id"], "code": item["code"], "attempt_id": item["attempt"]["id"], "amount": item["amount"], "paid": item["paid"]}
            for item in entitlements.values()
            if item["kind"] == "CAPITAL_RETURN"
        ],
        "share_claims": [_share_claim_record(item) for item in entitlements.values() if item["kind"] == "SHARE" and item["remaining"] > 0],
        "share_claim_history": [_share_claim_record(item) for item in entitlements.values() if item["kind"] == "SHARE"],
        "outstanding_share_codes": sorted({item["code"] for item in entitlements.values() if item["kind"] == "SHARE" and item["remaining"] > 0}),
    }
    if marks is not None:
        result["marked_equity"] = mark_equity(result, marks)
    return result


def _has_share_claim(entitlements: Mapping[str, Mapping[str, Any]], code: str) -> bool:
    return any(item["kind"] == "SHARE" and item["code"] == code and item["remaining"] > 0 for item in entitlements.values())


def _share_claim_record(claim: Mapping[str, Any]) -> dict[str, Any]:
    remaining = claim["remaining"]
    return {
        "id": claim["id"],
        "code": claim["code"],
        "attempt_id": claim["attempt"]["id"],
        "remaining_numerator": remaining.numerator,
        "remaining_denominator": remaining.denominator,
        "original_numerator": claim["original"].numerator,
        "original_denominator": claim["original"].denominator,
        "delivered_qty": claim["delivered_qty"],
        "settled_numerator": claim["settled_fraction"].numerator,
        "settled_denominator": claim["settled_fraction"].denominator,
        "settlement_total": claim["settlement_total"],
        "valuation_policy": claim["valuation_policy"],
    }


def mark_share_claims_cents(ledger: Mapping[str, Any], marks: Mapping[str, float], *, attempt_id: int | None = None) -> int:
    """Mark every outstanding same-class claim independently, rounded half-up to cents."""
    claims = ledger.get("share_claims", [])
    if not isinstance(claims, Sequence):
        raise LedgerError("ledger share_claims must be a sequence")
    total = 0
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise LedgerError("share claim must be a mapping")
        if attempt_id is not None and claim.get("attempt_id") != attempt_id:
            continue
        code = _event_text(claim, "code")
        if code not in marks:
            raise LedgerError(f"missing mark for share claim code: {code}")
        mark = _finite(marks[code], f"mark for share claim {code}")
        if mark < 0:
            raise LedgerError("marks must be nonnegative")
        numerator = _positive_int(claim.get("remaining_numerator"), "share claim remaining_numerator")
        denominator = _positive_int(claim.get("remaining_denominator"), "share claim remaining_denominator")
        cents = Fraction(str(mark)) * 100 * Fraction(numerator, denominator)
        whole, remainder = divmod(cents.numerator, cents.denominator)
        total += whole + (1 if remainder * 2 >= cents.denominator else 0)
    return total


def mark_equity(ledger: Mapping[str, Any], marks: Mapping[str, float]) -> float:
    """Return cash, marked holdings, and unpaid dividend/principal receivables."""
    cash = _finite(ledger.get("cash"), "ledger cash")
    positions = ledger.get("positions")
    if not isinstance(positions, Mapping):
        raise LedgerError("ledger positions must be a mapping")
    dividend_receivable = _finite(ledger.get("dividend_receivable", 0.0), "ledger dividend_receivable")
    if dividend_receivable < 0:
        raise LedgerError("ledger dividend_receivable must be nonnegative")
    capital_return_receivable = _finite(ledger.get("capital_return_receivable", 0.0), "ledger capital_return_receivable")
    if capital_return_receivable < 0:
        raise LedgerError("ledger capital_return_receivable must be nonnegative")
    equity = cash + dividend_receivable + capital_return_receivable + mark_share_claims_cents(ledger, marks) / 100.0
    for code, qty in positions.items():
        qty = _positive_int(qty, f"position qty for {code}")
        if code not in marks:
            raise LedgerError(f"missing mark for held code: {code}")
        mark = _finite(marks[code], f"mark for {code}")
        if mark < 0:
            raise LedgerError("marks must be nonnegative")
        equity += qty * mark
    if not math.isfinite(equity):
        raise LedgerError("marked equity overflow")
    return equity


def consecutive_non_hit_effects(attempts: Sequence[Mapping[str, Any]], span: int) -> dict[str, Any]:
    """Find the worst contiguous all-known-non-hit compounded effect window."""
    span = _positive_int(span, "span")
    identities = [item.get("id") for item in attempts]
    if any(isinstance(identity, bool) or not isinstance(identity, (str, int)) or identity == "" for identity in identities):
        raise LedgerError("attempt IDs must be nonempty strings or integers")
    if len(set(identities)) != len(identities):
        raise LedgerError("attempt IDs must be present and unique")
    if any(item.get("hit") is not None and not isinstance(item["hit"], bool) for item in attempts):
        raise LedgerError("attempt hit must be bool or None")
    if len(attempts) < span:
        return {"status": "insufficient_windows"}
    best: tuple[float, list[Any]] | None = None
    saw_unknown = False
    for start in range(len(attempts) - span + 1):
        window = attempts[start : start + span]
        hits = [item.get("hit") for item in window]
        if any(hit is True for hit in hits):
            continue
        if any(hit is None for hit in hits):
            saw_unknown = True
            continue
        compounded = 1.0
        for item in window:
            effect = _finite(item.get("effect"), "attempt effect")
            if effect <= -1:
                raise LedgerError("attempt effect must be greater than -1")
            compounded *= 1.0 + effect
            if not math.isfinite(compounded):
                raise LedgerError("compounded effect overflow")
        candidate = (compounded - 1.0, [item.get("id") for item in window])
        if best is None or candidate[0] < best[0]:
            best = candidate
    if saw_unknown:
        return {"status": "unavailable", "reason": "unknown classification may hide the worst window"}
    if best is not None:
        return {"status": "ok", "worst_compounded_net_effect": best[0], "ids": best[1], "unit": "fraction", "metric": "synthetic_non_hit_effect.v1"}
    return {"status": "no_eligible_windows"}


def max_drawdown(equity: Sequence[float]) -> float:
    """Compute positive peak-to-trough drawdown from an explicit equity sequence."""
    if not equity:
        raise LedgerError("equity sequence must not be empty")
    values = [_finite(value, "equity value") for value in equity]
    if values[0] <= 0:
        raise LedgerError("initial equity must be positive")
    if any(value < 0 for value in values):
        raise LedgerError("equity values must be nonnegative")
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = max(worst, (peak - value) / peak)
    return worst
