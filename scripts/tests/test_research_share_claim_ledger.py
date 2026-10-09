from __future__ import annotations

import math

import pytest

from research_core.ledger import LedgerError, mark_share_claims_cents, replay_ledger


def event(action: str, code: str, day: str, total: float = 0, **extra: object) -> dict[str, object]:
    return {"action": action, "code": code, "date": day, "total": total, **extra}


def claim(identity: str = "claim", numerator: int = 201, denominator: int = 2) -> dict[str, object]:
    return event(
        "SHARE_ENTITLEMENT",
        "A",
        "2026-01-02",
        entitlement_id=identity,
        share_numerator=numerator,
        share_denominator=denominator,
        valuation_policy="same-class-raw-close-cent-half-up",
    )


def test_claim_keeps_original_attempt_and_capacity_until_fraction_settles() -> None:
    events = [
        event("BUY", "A", "2026-01-01", -1000, qty=1000),
        claim(),
        event("SELL", "A", "2026-01-03", 1000, qty=1000),
        event("BUY", "A", "2026-01-04", -100, qty=100),
    ]
    ledger = replay_ledger(1100, events, max_positions=1)
    assert ledger["open_attempts"][0]["id"] == 0 and ledger["outstanding_share_codes"] == ["A"]
    assert ledger["share_claims"][0]["remaining_numerator"] == 201
    with pytest.raises(LedgerError, match="max_positions"):
        replay_ledger(1100, events + [event("BUY", "B", "2026-01-05", -1, qty=1)], max_positions=1)
    settled = replay_ledger(
        1100,
        events
        + [
            event("SELL", "A", "2026-01-05", 100, qty=100),
            event("SHARE_DELIVERY", "A", "2026-01-06", qty=100, entitlement_id="claim"),
            event("SELL", "A", "2026-01-07", 100, qty=100),
            event("SHARE_CASH_SETTLEMENT", "A", "2026-01-08", 5, entitlement_id="claim"),
        ],
        max_positions=1,
    )
    assert settled["positions"] == {} and settled["share_claims"] == []
    assert settled["attempts"][0]["share_settlement_total"] == 5
    history = settled["share_claim_history"][0]
    assert history["attempt_id"] == 0 and history["original_numerator"] == 201 and history["original_denominator"] == 2
    assert history["delivered_qty"] == 100 and history["settled_numerator"] == 1 and history["settled_denominator"] == 2
    assert history["remaining_numerator"] == 0 and history["settlement_total"] == 5
    released = replay_ledger(
        1100,
        events
        + [
            event("SELL", "A", "2026-01-05", 100, qty=100),
            event("SHARE_DELIVERY", "A", "2026-01-06", qty=100, entitlement_id="claim"),
            event("SELL", "A", "2026-01-07", 100, qty=100),
            event("SHARE_CASH_SETTLEMENT", "A", "2026-01-08", 5, entitlement_id="claim"),
            event("BUY", "B", "2026-01-09", -1, qty=1),
        ],
        max_positions=1,
    )
    assert released["positions"] == {"B": 1}


def test_claim_marking_rounds_each_claim_half_up_and_equity_includes_it() -> None:
    ledger = replay_ledger(100, [event("BUY", "A", "2026-01-01", -10, qty=1), claim("one", 1, 2), claim("two", 1, 2)])
    assert mark_share_claims_cents(ledger, {"A": 0.01}) == 2
    assert mark_share_claims_cents(ledger, {"A": 0.01}, attempt_id=0) == 2
    marked = replay_ledger(100, [event("BUY", "A", "2026-01-01", -10, qty=1), claim("one", 1, 2)], marks={"A": 10})
    assert marked["marked_equity"] == pytest.approx(100 + 5)


def test_rejects_settlement_before_whole_delivery_split_and_wrong_kind() -> None:
    base = [event("BUY", "A", "2026-01-01", -100, qty=1), claim()]
    with pytest.raises(LedgerError, match="fractional"):
        replay_ledger(100, base + [event("SHARE_CASH_SETTLEMENT", "A", "2026-01-03", 0, entitlement_id="claim")])
    with pytest.raises(LedgerError, match="SPLIT"):
        replay_ledger(100, base + [event("SPLIT", "A", "2026-01-03", old_qty=1, new_qty=2)])
    with pytest.raises(LedgerError, match="share claim"):
        replay_ledger(100, base + [event("SHARE_DELIVERY", "A", "2026-01-03", qty=1, entitlement_id="missing")])


def test_interleaved_delivery_uses_original_claim_attempt_for_cash_row() -> None:
    ledger = replay_ledger(
        300,
        [
            event("BUY", "A", "2026-01-01", -100, qty=1),
            claim("a", 1, 1),
            event("BUY", "B", "2026-01-03", -100, qty=1),
            event("SHARE_DELIVERY", "A", "2026-01-04", qty=1, entitlement_id="a"),
        ],
    )
    assert ledger["cash_rows"][-1]["attempt_id"] == 0


def test_share_and_cash_claims_coexist_without_cash_spending() -> None:
    events = [
        event("BUY", "A", "2026-01-01", -100, qty=1),
        claim(),
        event("DIVIDEND_ENTITLEMENT", "A", "2026-01-03", entitlement_id="cash", amount=10),
    ]
    ledger = replay_ledger(100, events)
    assert ledger["dividend_receivable"] == 10 and ledger["share_claims"]
    with pytest.raises(LedgerError, match="insufficient cash"):
        replay_ledger(100, events + [event("BUY", "B", "2026-01-04", -1, qty=1)])


def test_integer_delivery_then_final_sell_closes_attempt() -> None:
    ledger = replay_ledger(
        100,
        [
            event("BUY", "A", "2026-01-01", -10, qty=1),
            claim("whole", 1, 1),
            event("SELL", "A", "2026-01-03", 10, qty=1),
            event("SHARE_DELIVERY", "A", "2026-01-04", qty=1, entitlement_id="whole"),
            event("SELL", "A", "2026-01-05", 10, qty=1),
        ],
    )
    assert len(ledger["attempts"]) == 1 and not ledger["open_attempts"]


@pytest.mark.parametrize(
    "extra, match",
    [
        ({"share_numerator": 0, "share_denominator": 1}, "share_numerator"),
        ({"share_numerator": 1, "share_denominator": 0}, "share_denominator"),
        ({"share_numerator": 1, "share_denominator": 1, "valuation_policy": "unknown"}, "valuation_policy"),
    ],
)
def test_invalid_share_entitlement_contract_rejects(extra: dict[str, object], match: str) -> None:
    base = event(
        "SHARE_ENTITLEMENT",
        "A",
        "2026-01-02",
        entitlement_id="claim",
        share_numerator=1,
        share_denominator=1,
        valuation_policy="same-class-raw-close-cent-half-up",
    )
    base.update(extra)
    with pytest.raises(LedgerError, match=match):
        replay_ledger(100, [event("BUY", "A", "2026-01-01", -10, qty=1), base])


@pytest.mark.parametrize("total", [-1, math.nan])
def test_invalid_settlement_total_rejects(total: float) -> None:
    with pytest.raises(LedgerError):
        replay_ledger(
            100,
            [event("BUY", "A", "2026-01-01", -10, qty=1), claim("half", 1, 2), event("SHARE_CASH_SETTLEMENT", "A", "2026-01-03", total, entitlement_id="half")],
        )


def test_delivery_cross_code_overdelivery_double_settlement_id_reuse_and_missing_total_reject() -> None:
    base = [event("BUY", "A", "2026-01-01", -10, qty=1), claim("half", 1, 2)]
    with pytest.raises(LedgerError, match="code"):
        replay_ledger(100, base + [event("SHARE_DELIVERY", "B", "2026-01-03", qty=1, entitlement_id="half")])
    with pytest.raises(LedgerError, match="exceeds"):
        replay_ledger(100, base + [event("SHARE_DELIVERY", "A", "2026-01-03", qty=1, entitlement_id="half")])
    settled = base + [event("SHARE_CASH_SETTLEMENT", "A", "2026-01-03", 0, entitlement_id="half")]
    with pytest.raises(LedgerError, match="attempt|fractional"):
        replay_ledger(100, settled + [event("SHARE_CASH_SETTLEMENT", "A", "2026-01-04", 0, entitlement_id="half")])
    with pytest.raises(LedgerError, match="wrong kind"):
        replay_ledger(100, base + [event("DIVIDEND", "A", "2026-01-03", 1, entitlement_id="half")])
    with pytest.raises(LedgerError, match="globally unique"):
        replay_ledger(
            100, settled + [event("BUY", "A", "2026-01-04", -1, qty=1), event("DIVIDEND_ENTITLEMENT", "A", "2026-01-05", entitlement_id="half", amount=1)]
        )
    missing = {"action": "SHARE_CASH_SETTLEMENT", "code": "A", "date": "2026-01-03", "entitlement_id": "half"}
    with pytest.raises(LedgerError, match="total"):
        replay_ledger(100, base + [missing])
