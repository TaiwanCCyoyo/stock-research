"""Cash-only per-share adapter; source timing and credit policy are caller inputs."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from research_core.chronology import CorporateEvidence
from research_core.ledger import replay_ledger


class CashDividendError(ValueError):
    """Inconsistent adapter inputs, not a failed investment strategy."""


def timestamp(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(hours=8):
        raise CashDividendError("timestamps must be aware +08:00")


def nonempty(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CashDividendError("identity and policy must be nonempty")


@dataclass(frozen=True)
class CashDividend:
    event_id: str
    code: str
    credited_per_share: Decimal | None
    entitlement_at: datetime
    payment_at: datetime
    source_available_at: datetime | None
    source_id: str
    policy_id: str
    time_basis: str

    def __post_init__(self) -> None:
        for value in (self.event_id, self.code, self.source_id, self.policy_id):
            nonempty(value)
        for instant in (self.entitlement_at, self.payment_at):
            timestamp(instant)
        if self.source_available_at is not None:
            timestamp(self.source_available_at)
        if self.payment_at <= self.entitlement_at:
            raise CashDividendError("payment must follow entitlement")
        if self.time_basis not in {"exact", "assumed"}:
            raise CashDividendError("cash timing requires an exact or explicit assumed order")
        amount = self.credited_per_share
        if amount is not None and (not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0):
            raise CashDividendError("credited per-share amount must be finite nonnegative Decimal or unknown")


@dataclass(frozen=True)
class CashCoverage:
    since: datetime
    until: datetime
    complete: bool
    evidence_id: str

    def __post_init__(self) -> None:
        timestamp(self.since)
        timestamp(self.until)
        nonempty(self.evidence_id)
        if self.until <= self.since or type(self.complete) is not bool:
            raise CashDividendError("coverage requires an ordered interval and explicit completeness")


def amount_cents(per_share: Decimal, quantity: int) -> int:
    """Round the account amount once; never round the per-share value first."""
    if not isinstance(per_share, Decimal) or not per_share.is_finite() or per_share < 0:
        raise CashDividendError("invalid per-share amount")
    if type(quantity) is not int or quantity < 0:
        raise CashDividendError("quantity must be a nonnegative integer")
    return int((per_share * quantity * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def build_cash_provider(
    terms: Sequence[CashDividend],
    coverage: Sequence[CashCoverage],
    *,
    initial_cash_cents: int,
    max_positions: int,
    rounding_policy: str,
):
    """Pure callback for cash-only intervals; not whole-market corporate coverage.

    Query intervals are (since, until]. The prefix must contain the full actual
    account history, including prior calls' emitted events. No state survives a
    call, so separate stress paths cannot leak holdings or entitlements.
    """
    if rounding_policy != "account-cent-half-up":
        raise CashDividendError("unsupported or unstated rounding policy")
    if type(initial_cash_cents) is not int or initial_cash_cents <= 0 or type(max_positions) is not int or max_positions <= 0:
        raise CashDividendError("positive integer account limits required")
    frozen_terms, frozen_coverage = tuple(terms), tuple(coverage)
    if len({term.event_id for term in frozen_terms}) != len(frozen_terms):
        raise CashDividendError("duplicate dividend event identity")

    def moment(record: Mapping[str, Any]) -> datetime:
        value = datetime.fromisoformat(str(record["date"]))
        timestamp(value)
        return value

    def stamped(term: CashDividend, at: datetime, **values: Any) -> dict[str, Any]:
        return {
            "code": term.code,
            "date": at.isoformat(),
            "entitlement_id": term.event_id,
            "time_basis": term.time_basis,
            "available_at": at.isoformat(),
            "source_available_at": term.source_available_at.isoformat() if term.source_available_at else None,
            "evidence_basis": term.source_id,
            "cash_policy_id": term.policy_id,
            "rounding_policy": rounding_policy,
            **values,
        }

    def provide(since: datetime, until: datetime, prefix: Sequence[Mapping[str, Any]]) -> CorporateEvidence:
        timestamp(since)
        timestamp(until)
        if until <= since:
            raise CashDividendError("query interval must be ordered")
        covering = [item for item in frozen_coverage if item.since <= since and item.until >= until]
        if not covering or any(not item.complete for item in covering):
            return CorporateEvidence("cash-dividends:coverage-incomplete", (), False)
        evidence_id = f"cash-dividends:{covering[0].evidence_id}"
        original = list(prefix)
        # Stable sort preserves authoritative equal-time prefix ordering.
        original.sort(key=moment)
        emitted: list[dict[str, Any]] = []

        def ledger_before(at: datetime) -> dict[str, Any]:
            records = sorted([record for record in [*original, *emitted] if moment(record) < at], key=moment)
            return replay_ledger(initial_cash_cents / 100, records, max_positions=max_positions)

        def check_claim_times(term: CashDividend, cutoff: datetime, *, paid: bool) -> None:
            for action, expected in (("DIVIDEND_ENTITLEMENT", term.entitlement_at), ("DIVIDEND", term.payment_at)):
                if action == "DIVIDEND" and not paid:
                    continue
                matching = [
                    record
                    for record in [*original, *emitted]
                    if str(record["action"]).upper() == action and record.get("entitlement_id") == term.event_id and moment(record) <= cutoff
                ]
                if len(matching) != 1 or moment(matching[0]) != expected:
                    raise CashDividendError("prefix claim or payment timestamp differs from declared schedule")

        # A caller cannot start after qualification and silently omit an owed
        # claim, even when no payment falls in this query interval.
        past_terms = [term for term in frozen_terms if term.entitlement_at <= since]
        if past_terms:
            boundary_records = [record for record in original if moment(record) <= since]
            boundary = replay_ledger(
                initial_cash_cents / 100,
                boundary_records,
                max_positions=max_positions,
            )
            boundary_claims = {claim["id"]: claim for claim in boundary["dividend_entitlements"]}
            # The boundary replay validates this prefix once. Index its share
            # quantities instead of replaying the whole ledger for every past
            # dividend on every subsequent query day.
            quantities: dict[str, int] = {}
            clocks: dict[str, list[datetime]] = {}
            values: dict[str, list[int]] = {}
            for record in boundary_records:
                action, code = str(record["action"]).upper(), str(record["code"])
                if action in {"BUY", "SHARE_DELIVERY"}:
                    quantities[code] = quantities.get(code, 0) + int(record["qty"])
                elif action == "SELL":
                    quantities[code] -= int(record["qty"])
                elif action == "SPLIT":
                    quantities[code] = int(record["new_qty"])
                else:
                    continue
                clocks.setdefault(code, []).append(moment(record))
                values.setdefault(code, []).append(quantities[code])
            for term in past_terms:
                times = clocks.get(term.code, [])
                position = bisect_left(times, term.entitlement_at)
                if position < len(times) and times[position] == term.entitlement_at:
                    raise CashDividendError("unsupported same-timestamp record and cash event")
                qualified = values[term.code][position - 1] if position else 0
                if not qualified:
                    if term.event_id in boundary_claims:
                        raise CashDividendError("prefix claim exists without qualifying shares")
                    continue
                if term.source_available_at is None or term.source_available_at > term.entitlement_at or term.credited_per_share is None:
                    return CorporateEvidence(f"{evidence_id}:unknown-or-late:{term.event_id}", (), False)
                cents = amount_cents(term.credited_per_share, qualified)
                if not cents:
                    if term.event_id in boundary_claims:
                        raise CashDividendError("prefix claim exists for zero credited amount")
                    continue
                claim = boundary_claims.get(term.event_id)
                if claim is None:
                    return CorporateEvidence(f"{evidence_id}:missing-entitlement:{term.event_id}", (), False)
                if claim["code"] != term.code or Decimal(str(claim["amount"])) != Decimal(cents) / 100:
                    raise CashDividendError("prefix claim differs from qualified per-share amount")
                check_claim_times(term, since, paid=bool(claim["paid"]))
                if bool(claim["paid"]) != (term.payment_at <= since):
                    return CorporateEvidence(f"{evidence_id}:payment-boundary-mismatch:{term.event_id}", (), False)

        schedule = sorted(
            (at, kind, term.event_id, term)
            for term in frozen_terms
            for kind, at in (("entitlement", term.entitlement_at), ("payment", term.payment_at))
            if since < at <= until
        )
        for at, kind, _, term in schedule:
            if any(moment(record) == at and record.get("code") == term.code for record in original):
                raise CashDividendError("unsupported same-timestamp record and cash event")
            ledger = ledger_before(at)
            claims = {claim["id"]: claim for claim in ledger["dividend_entitlements"]}
            if kind == "entitlement":
                if term.event_id in claims:
                    raise CashDividendError("entitlement already present in prefix")
                held = ledger["positions"].get(term.code, 0)
                if not held:
                    continue
                if term.source_available_at is None or term.source_available_at > term.entitlement_at or term.credited_per_share is None:
                    return CorporateEvidence(f"{evidence_id}:unknown-or-late:{term.event_id}", (), False)
                cents = amount_cents(term.credited_per_share, held)
                if cents == 0:
                    continue
                emitted.append(stamped(term, at, action="DIVIDEND_ENTITLEMENT", total=0, amount=cents / 100, qualified_qty=held))
            else:
                claim = claims.get(term.event_id)
                if claim is None:
                    # Independently establish that no payment claim was omitted at the
                    # boundary. Current holdings cannot establish past qualification.
                    qualification = ledger_before(term.entitlement_at)
                    held = qualification["positions"].get(term.code, 0)
                    if held and (term.credited_per_share is None or amount_cents(term.credited_per_share, held) > 0):
                        return CorporateEvidence(f"{evidence_id}:missing-entitlement:{term.event_id}", (), False)
                    continue
                if claim["code"] != term.code or claim["paid"]:
                    raise CashDividendError("payment claim code mismatch or already paid")
                qualified = ledger_before(term.entitlement_at)["positions"].get(term.code, 0)
                if not qualified:
                    raise CashDividendError("prefix claim exists without qualifying shares")
                if term.source_available_at is None or term.source_available_at > term.entitlement_at or term.credited_per_share is None:
                    return CorporateEvidence(f"{evidence_id}:unknown-or-late:{term.event_id}", (), False)
                expected = Decimal(amount_cents(term.credited_per_share, qualified)) / 100
                if Decimal(str(claim["amount"])) != expected:
                    raise CashDividendError("prefix claim differs from qualified per-share amount")
                check_claim_times(term, at, paid=False)
                emitted.append(stamped(term, at, action="DIVIDEND", total=claim["amount"]))
        return CorporateEvidence(evidence_id, tuple(emitted), True)

    return provide
