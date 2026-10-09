from __future__ import annotations

from typing import Any

import pytest

from research_core.ledger import LedgerError, mark_equity, replay_ledger


def event(action: str, code: str, day: str, total: float = 0, **extra: object) -> dict[str, object]:
    return {"action": action, "code": code, "date": day, "total": total, **extra}


def test_receivable_cannot_buy_but_paid_return_can_and_recovers_principal() -> None:
    prefix = [
        event("BUY", "A", "2026-01-01", -100, qty=1),
        event("CAPITAL_RETURN_ENTITLEMENT", "A", "2026-01-02", entitlement_id="refund", amount=100),
    ]
    with pytest.raises(LedgerError, match="insufficient cash"):
        replay_ledger(100, prefix + [event("BUY", "B", "2026-01-03", -100, qty=1)])
    paid = replay_ledger(100, prefix + [event("CAPITAL_RETURN", "A", "2026-01-03", 100, entitlement_id="refund"), event("BUY", "B", "2026-01-04", -100, qty=1)])
    assert paid["cash"] == 0 and paid["positions"] == {"A": 1, "B": 1}
    ledger = replay_ledger(
        100,
        prefix
        + [
            event("CAPITAL_RETURN", "A", "2026-01-03", 100, entitlement_id="refund"),
            event("SELL", "A", "2026-01-04", 0, qty=1, gross_proceeds=100, cost_total=100),
        ],
    )
    attempt = ledger["attempts"][0]
    assert ledger["cash"] == 100 and attempt["capital_return_total"] == 100
    assert attempt["pnl_ex_dividend"] == attempt["net_pnl"] == 0


def test_return_stays_with_original_attempt_after_exit_and_rebuy_and_marks_equity() -> None:
    ledger = replay_ledger(
        100,
        [
            event("BUY", "A", "2026-01-01", -100, qty=1),
            event("CAPITAL_RETURN_ENTITLEMENT", "A", "2026-01-02", entitlement_id="old", amount=10),
            event("SELL", "A", "2026-01-03", 90, qty=1),
            event("BUY", "A", "2026-01-04", -90, qty=1),
            event("CAPITAL_RETURN", "A", "2026-01-05", 10, entitlement_id="old"),
        ],
        marks={"A": 90},
    )
    assert ledger["cash_rows"][-1]["attempt_id"] == 0
    assert ledger["attempts"][0]["capital_return_total"] == 10
    assert ledger["open_attempts"][0]["id"] == 3
    assert mark_equity(ledger, {"A": 90}) == 100


def test_dividend_and_return_coexist_and_wrong_kind_or_link_reject() -> None:
    good = [
        event("BUY", "A", "2026-01-01", -100, qty=1),
        event("DIVIDEND_ENTITLEMENT", "A", "2026-01-02", entitlement_id="div", amount=2),
        event("CAPITAL_RETURN_ENTITLEMENT", "A", "2026-01-03", entitlement_id="refund", amount=10),
        event("DIVIDEND", "A", "2026-01-04", 2, entitlement_id="div"),
        event("CAPITAL_RETURN", "A", "2026-01-05", 10, entitlement_id="refund"),
    ]
    ledger = replay_ledger(100, good)
    assert ledger["dividend_receivable"] == ledger["capital_return_receivable"] == 0
    assert ledger["open_attempts"][0]["dividend_total"] == 2
    with pytest.raises(LedgerError, match="wrong kind"):
        replay_ledger(100, good[:3] + [event("CAPITAL_RETURN", "A", "2026-01-04", 2, entitlement_id="div")])
    with pytest.raises(LedgerError, match="globally unique"):
        replay_ledger(100, good[:3] + [event("CAPITAL_RETURN_ENTITLEMENT", "A", "2026-01-04", entitlement_id="div", amount=1)])
    with pytest.raises(LedgerError, match="reference"):
        replay_ledger(100, [event("CAPITAL_RETURN", "A", "2026-01-01", 1, entitlement_id="none")])


@pytest.mark.parametrize("amount", [0, -1, None, True, float("nan"), float("inf")])
def test_invalid_or_unknown_principal_entitlement_rejects(amount: Any) -> None:
    with pytest.raises(LedgerError):
        replay_ledger(
            100, [event("BUY", "A", "2026-01-01", -100, qty=1), event("CAPITAL_RETURN_ENTITLEMENT", "A", "2026-01-02", entitlement_id="refund", amount=amount)]
        )


@pytest.mark.parametrize("extra", [{"code": "B"}, {"total": 9}, {"total": 0}, {"entitlement_id": None}])
def test_wrong_principal_payment_rejects(extra: dict[str, Any]) -> None:
    prefix = [event("BUY", "A", "2026-01-01", -100, qty=1), event("CAPITAL_RETURN_ENTITLEMENT", "A", "2026-01-02", entitlement_id="refund", amount=10)]
    with pytest.raises(LedgerError):
        replay_ledger(100, [*prefix, {**event("CAPITAL_RETURN", "A", "2026-01-03", 10, entitlement_id="refund"), **extra}])


def test_principal_cannot_be_paid_twice_or_reused_as_dividend_id() -> None:
    prefix = [event("BUY", "A", "2026-01-01", -100, qty=1), event("CAPITAL_RETURN_ENTITLEMENT", "A", "2026-01-02", entitlement_id="refund", amount=10)]
    pay = event("CAPITAL_RETURN", "A", "2026-01-03", 10, entitlement_id="refund")
    with pytest.raises(LedgerError, match="already been paid"):
        replay_ledger(100, [*prefix, pay, pay])
    with pytest.raises(LedgerError, match="globally unique"):
        replay_ledger(100, [*prefix, event("DIVIDEND_ENTITLEMENT", "A", "2026-01-03", entitlement_id="refund", amount=10)])
