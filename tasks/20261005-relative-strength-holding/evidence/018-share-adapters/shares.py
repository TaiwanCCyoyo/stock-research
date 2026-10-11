"""Pure same-class free-share adapter; dates and net settlement policy are inputs.

This neither downloads nor certifies historical availability. Coverage names only
the supplied share-term domain, not every corporate event affecting an issuer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

from research_core.chronology import CorporateEvidence
from research_core.ledger import replay_ledger


class ShareEvidenceError(ValueError):
    """A term or prefix contradicts the declared share-event contract."""


def _time(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(hours=8):
        raise ShareEvidenceError("timestamps must be aware +08:00")


def _text(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ShareEvidenceError("source and policy identities must be nonempty")


def _moment(record: Mapping[str, Any]) -> datetime:
    value = datetime.fromisoformat(str(record["date"]))
    _time(value)
    return value


@dataclass(frozen=True)
class ShareTerm:
    event_id: str
    code: str
    bonus_per_share: Fraction | None
    entitlement_at: datetime
    delivery_at: datetime
    fractional_settlement_at: datetime | None
    fractional_net_per_share: Decimal | None
    source_available_at: datetime | None
    source_id: str
    policy_id: str
    time_basis: str
    valuation_policy: str

    def __post_init__(self) -> None:
        for value in (self.event_id, self.code, self.source_id, self.policy_id):
            _text(value)
        for instant in (self.entitlement_at, self.delivery_at):
            _time(instant)
        if self.delivery_at <= self.entitlement_at:
            raise ShareEvidenceError("delivery must follow entitlement")
        if self.fractional_settlement_at is not None:
            _time(self.fractional_settlement_at)
            if self.fractional_settlement_at <= self.delivery_at:
                raise ShareEvidenceError("fractional settlement must follow delivery")
        if self.source_available_at is not None:
            _time(self.source_available_at)
        if self.bonus_per_share is not None and (type(self.bonus_per_share) is not Fraction or self.bonus_per_share < 0):
            raise ShareEvidenceError("bonus ratio must be nonnegative Fraction or unknown")
        amount = self.fractional_net_per_share
        if amount is not None and (not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0):
            raise ShareEvidenceError("fractional net price must be nonnegative Decimal or unknown")
        if self.time_basis not in {"exact", "assumed"} or self.valuation_policy != "same-class-raw-close-cent-half-up":
            raise ShareEvidenceError("explicit supported timing and valuation policy required")


@dataclass(frozen=True)
class ShareCoverage:
    since: datetime
    until: datetime
    complete: bool
    evidence_id: str

    def __post_init__(self) -> None:
        _time(self.since)
        _time(self.until)
        _text(self.evidence_id)
        if self.since >= self.until or type(self.complete) is not bool:
            raise ShareEvidenceError("coverage must be ordered and explicitly complete or incomplete")


def _fraction_cents(quantity: Fraction, price: Decimal) -> int:
    cents = quantity * Fraction(price) * 100
    whole, remainder = divmod(cents.numerator, cents.denominator)
    return whole + int(2 * remainder >= cents.denominator)


def build_share_provider(terms: Sequence[ShareTerm], coverage: Sequence[ShareCoverage], *, initial_cash_cents: int, max_positions: int):
    if type(initial_cash_cents) is not int or initial_cash_cents <= 0 or type(max_positions) is not int or max_positions <= 0:
        raise ShareEvidenceError("positive integer account limits required")
    frozen, covered = tuple(terms), tuple(coverage)
    if any(not isinstance(term, ShareTerm) for term in frozen) or any(not isinstance(item, ShareCoverage) for item in covered):
        raise ShareEvidenceError("typed share terms and coverage required")
    if len({term.event_id for term in frozen}) != len(frozen):
        raise ShareEvidenceError("duplicate share event identity")

    def provide(since: datetime, until: datetime, prefix: Sequence[Mapping[str, Any]]) -> CorporateEvidence:
        _time(since)
        _time(until)
        if since >= until:
            raise ShareEvidenceError("query interval must be ordered")
        containers = sorted([item for item in covered if item.since < until and since < item.until], key=lambda item: item.since)
        cursor = since
        for item in containers:
            if not item.complete or item.since > cursor:
                return CorporateEvidence("share-terms:coverage-incomplete", (), False)
            cursor = max(cursor, item.until)
        if cursor < until:
            return CorporateEvidence("share-terms:coverage-incomplete", (), False)
        identity = "share-terms:" + ",".join(item.evidence_id for item in containers)
        original = sorted(prefix, key=_moment)
        emitted: list[dict[str, Any]] = []

        def before(at: datetime) -> dict[str, Any]:
            records = sorted([event for event in [*original, *emitted] if _moment(event) < at], key=_moment)
            return replay_ledger(initial_cash_cents / 100, records, max_positions=max_positions)

        def stamped(term: ShareTerm, at: datetime, **values: Any) -> dict[str, Any]:
            return {
                "code": term.code,
                "date": at.isoformat(),
                "entitlement_id": term.event_id,
                "time_basis": term.time_basis,
                "available_at": at.isoformat(),
                "source_available_at": term.source_available_at.isoformat() if term.source_available_at else None,
                "evidence_basis": term.source_id,
                "share_policy_id": term.policy_id,
                **values,
            }

        def known_quantity(term: ShareTerm) -> Fraction | None:
            if any(
                _moment(event) == term.entitlement_at and event.get("code") == term.code and event.get("entitlement_id") != term.event_id for event in original
            ):
                raise ShareEvidenceError("unsupported same-timestamp qualification")
            held = before(term.entitlement_at)["positions"].get(term.code, 0)
            if held == 0:
                return Fraction(0)
            if term.bonus_per_share is None or term.source_available_at is None or term.source_available_at > term.entitlement_at:
                return None
            return held * term.bonus_per_share

        # Past terms must match their original qualifying quantity and complete
        # declared schedule; current holdings cannot establish past entitlement.
        boundary_records = [event for event in original if _moment(event) <= since]
        boundary = replay_ledger(initial_cash_cents / 100, boundary_records, max_positions=max_positions)
        histories = {item["id"]: item for item in boundary["share_claim_history"]}
        for term in frozen:
            if term.entitlement_at > since:
                continue
            quantity = known_quantity(term)
            if quantity is None:
                return CorporateEvidence(f"{identity}:unknown-or-late:{term.event_id}", (), False)
            history = histories.get(term.event_id)
            if not quantity:
                if history is not None:
                    raise ShareEvidenceError("prefix grant exists without qualifying shares")
                continue
            if history is None:
                return CorporateEvidence(f"{identity}:missing-entitlement:{term.event_id}", (), False)
            if history["code"] != term.code or Fraction(history["original_numerator"], history["original_denominator"]) != quantity:
                raise ShareEvidenceError("prefix grant differs from qualified share quantity")
            whole = quantity.numerator // quantity.denominator
            fraction = quantity - whole
            expected: list[tuple[str, datetime, int | Fraction]] = [("SHARE_ENTITLEMENT", term.entitlement_at, quantity)]
            if whole and term.delivery_at <= since:
                expected.append(("SHARE_DELIVERY", term.delivery_at, whole))
            if fraction and term.delivery_at <= since and term.fractional_settlement_at is None:
                return CorporateEvidence(f"{identity}:unknown-fraction-schedule:{term.event_id}", (), False)
            if fraction and term.fractional_settlement_at is not None and term.fractional_settlement_at <= since:
                if term.fractional_net_per_share is None:
                    return CorporateEvidence(f"{identity}:unknown-fraction-cash:{term.event_id}", (), False)
                expected.append(("SHARE_CASH_SETTLEMENT", term.fractional_settlement_at, _fraction_cents(fraction, term.fractional_net_per_share)))
            actual = [event for event in boundary_records if event.get("entitlement_id") == term.event_id]
            if len(actual) != len(expected):
                return CorporateEvidence(f"{identity}:schedule-boundary-mismatch:{term.event_id}", (), False)
            for event, (action, at, amount) in zip(actual, expected, strict=True):
                if event["action"] != action or _moment(event) != at:
                    raise ShareEvidenceError("prefix action or time differs from declared share schedule")
                metadata = stamped(term, at)
                if any(event.get(key) != value for key, value in metadata.items()):
                    raise ShareEvidenceError("prefix availability, source or policy differs from declared share term")
                if action == "SHARE_ENTITLEMENT" and event.get("valuation_policy") != term.valuation_policy:
                    raise ShareEvidenceError("prefix valuation policy differs from declared share term")
                if action == "SHARE_DELIVERY" and event["qty"] != amount:
                    raise ShareEvidenceError("prefix delivery differs from declared whole shares")
                if action == "SHARE_CASH_SETTLEMENT" and Fraction(str(event["total"])) * 100 != amount:
                    raise ShareEvidenceError("prefix fractional payment differs from declared net cash")

        schedule = sorted(
            (at, kind, term.event_id, term)
            for term in frozen
            for kind, at in (("grant", term.entitlement_at), ("delivery", term.delivery_at), ("settlement", term.fractional_settlement_at))
            if at is not None and since < at <= until
        )
        for at, kind, _, term in schedule:
            if any(_moment(event) == at and event.get("code") == term.code for event in [*original, *emitted]):
                raise ShareEvidenceError("unsupported same-timestamp share event")
            quantity = known_quantity(term)
            if quantity is None:
                return CorporateEvidence(f"{identity}:unknown-or-late:{term.event_id}", (), False)
            if not quantity:
                continue
            if kind == "grant":
                emitted.append(
                    stamped(
                        term,
                        at,
                        action="SHARE_ENTITLEMENT",
                        total=0,
                        share_numerator=quantity.numerator,
                        share_denominator=quantity.denominator,
                        valuation_policy=term.valuation_policy,
                    )
                )
                continue
            history = next((item for item in before(at)["share_claim_history"] if item["id"] == term.event_id), None)
            if history is None:
                return CorporateEvidence(f"{identity}:missing-entitlement:{term.event_id}", (), False)
            if history["code"] != term.code or Fraction(history["original_numerator"], history["original_denominator"]) != quantity:
                raise ShareEvidenceError("prefix grant differs from qualified share quantity")
            whole, fraction = quantity.numerator // quantity.denominator, quantity % 1
            if kind == "delivery":
                if fraction and term.fractional_settlement_at is None:
                    return CorporateEvidence(f"{identity}:unknown-fraction-schedule:{term.event_id}", (), False)
                if whole:
                    emitted.append(stamped(term, at, action="SHARE_DELIVERY", total=0, qty=whole))
            elif fraction:
                if term.fractional_net_per_share is None:
                    return CorporateEvidence(f"{identity}:unknown-fraction-cash:{term.event_id}", (), False)
                emitted.append(stamped(term, at, action="SHARE_CASH_SETTLEMENT", total=_fraction_cents(fraction, term.fractional_net_per_share) / 100))
        # Validate the emitted event vocabulary and ownership before returning it.
        combined = sorted([*(event for event in original if _moment(event) <= until), *emitted], key=_moment)
        replay_ledger(initial_cash_cents / 100, combined, max_positions=max_positions)
        return CorporateEvidence(identity, tuple(emitted), True)

    return provide
