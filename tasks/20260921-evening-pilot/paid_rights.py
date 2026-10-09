"""One source-bound paid offer under an explicitly modeled refusal policy."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import Any, TypedDict

from research_core.chronology import CorporateEvidence
from research_core.ledger import replay_ledger

EVENT_ID = "annual:exdailyq:3363:2023-10-17:902"
POLICY_ID = "standing-no-paid-subscriptions-irrevocable-on-ex-date-v1"
AT = datetime.fromisoformat("2023-10-17T07:00:00+08:00")


class _OfferSpec(TypedDict):
    event_id: str
    at: datetime
    ratio: Fraction
    price: str
    fields: dict[str, str]


_OFFER_SPECS: dict[str, _OfferSpec] = {
    "3363": {
        "event_id": EVENT_ID,
        "at": AT,
        "ratio": Fraction("84.61137213") / 1000,
        "price": "52.80",
        "fields": {
            "代號": "3363",
            "除權息日期": "112/10/17",
            "權/息": "除權",
            "現金股利": "0.00000000",
            "每仟股無償配股": "0.00000000",
            "現金增資股數": "10000000",
            "現金增資認購價": "52.80",
            "公開承銷股數": "1000000",
            "員工認購股數": "1500000",
            "原股東認購股數": "7500000",
            "按持股比例仟股認購": "84.61137213",
        },
    },
    "4768": {
        "event_id": "annual:exdailyq:4768:2023-10-02:894",
        "at": datetime.fromisoformat("2023-10-02T07:00:00+08:00"),
        "ratio": Fraction("88.72155820") / 1000,
        "price": "130.00",
        "fields": {
            "代號": "4768",
            "除權息日期": "112/10/02",
            "權/息": "除權",
            "現金股利": "0.00000000",
            "每仟股無償配股": "0.00000000",
            "現金增資股數": "4300000",
            "現金增資認購價": "130.00",
            "公開承銷股數": "430000",
            "員工認購股數": "430000",
            "原股東認購股數": "3440000",
            "按持股比例仟股認購": "88.72155820",
        },
    },
}


@dataclass(frozen=True)
class DeclinedOffer:
    event_id: str
    code: str
    at: datetime
    shares_per_old_share: Fraction
    subscription_price_twd: str


def bind_declined_offer(records: Sequence[Mapping[str, Any]], code: str = "3363") -> DeclinedOffer:
    """Validate the stated offer, never infer an absent right from cash zero."""
    spec = _OFFER_SPECS.get(code)
    if spec is None:
        raise ValueError("only explicitly allowlisted paid offers are supported")
    matching = [record for record in records if record.get("code") == code and record.get("effective_date") == spec["at"].date().isoformat()]
    if len(matching) != 1:
        raise ValueError(f"expected one unique {code} paid-subscription record")
    record = matching[0]
    fields = record.get("literal_fields")
    if (
        record.get("event_id") != spec["event_id"]
        or record.get("source") != "annual/exdailyq"
        or record.get("market") != "TPEx"
        or not isinstance(fields, Mapping)
        or any(fields.get(name) != value for name, value in spec["fields"].items())
    ):
        raise ValueError(f"{code} offer does not match the stated pure paid terms")
    return DeclinedOffer(spec["event_id"], code, spec["at"], spec["ratio"], spec["price"])


def build_declining_provider(base: Callable[..., CorporateEvidence], offer: DeclinedOffer, decisions: list[dict[str, Any]]) -> Callable[..., CorporateEvidence]:
    """Preserve the base ledger; record refusal, not a fictitious cash event."""
    spec = _OFFER_SPECS.get(offer.code)
    if spec is None or offer != DeclinedOffer(spec["event_id"], offer.code, spec["at"], spec["ratio"], spec["price"]):
        raise ValueError("only exact bound paid offers are supported")

    def moment(event: Mapping[str, Any]) -> datetime:
        return datetime.fromisoformat(str(event["date"]))

    def provide(since: datetime, until: datetime, prefix: Sequence[Mapping[str, Any]]) -> CorporateEvidence:
        result = base(since, until, prefix)
        if not result.complete:
            return result
        if since < offer.at <= until:
            before = sorted((event for event in (*prefix, *result.events) if moment(event) < offer.at), key=moment)
            ledger = replay_ledger(2_000_000, before, max_positions=5)
            if offer.code in ledger["outstanding_share_codes"]:
                return CorporateEvidence("paid-offer-pending-share-qualification-unknown", (), False)
            quantity = ledger["positions"].get(offer.code, 0)
            if quantity:
                decision = {
                    "reason": "modeled_paid_subscription_declined",
                    "date": offer.at.isoformat(),
                    "code": offer.code,
                    "event_id": offer.event_id,
                    "qualified_old_shares": quantity,
                    "offer_ratio_numerator": offer.shares_per_old_share.numerator,
                    "offer_ratio_denominator": offer.shares_per_old_share.denominator,
                    "subscription_price_twd": offer.subscription_price_twd,
                    "cash_debit_twd": 0,
                    "new_shares": 0,
                    "time_basis": "assumed",
                    "policy_id": POLICY_ID,
                    "note": "opportunity deliberately declined; not a claim of zero right value",
                }
                if decision not in decisions:
                    decisions.append(decision)
        return CorporateEvidence(f"{result.evidence_id}|{POLICY_ID}", result.events, True, result.share_count_notices, result.backdated)

    return provide
