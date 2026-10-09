"""Capital refunds remain principal flows throughout exact account consumers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

import pytest

from research_core.attempt_stress import run_best_attempt_stresses
from research_core.attribution import mark_attempt_pnl, non_hit_attribution
from research_core.attribution_inputs import build_attribution_inputs
from research_core.chronology import CorporateEvidence
from research_core.decision import DecisionError, build_execution_account_snapshot
from research_core.ledger import replay_ledger
from scripts.tests import test_research_attempt_stress as stress
from scripts.tests import test_research_attribution_inputs as attribution
from scripts.tests import test_research_decision as decision


def test_refund_snapshot_keeps_unpaid_principal_nonspendable() -> None:
    claim = {
        "action": "CAPITAL_RETURN_ENTITLEMENT",
        "code": "A",
        "date": decision.stamp(5, "08:00").isoformat(),
        "total": 0,
        "amount": 10000,
        "entitlement_id": "A-refund",
    }
    events = [decision.event("BUY", 2), claim]
    before = decision.snapshot(events, prices={"A": decision.observation(raw=9000)})
    assert before.cash_cents == 190_000_000
    assert before.capital_return_receivable_cents == before.receivable_cents == 1_000_000
    assert before.equity_cents == 200_000_000
    execution = build_execution_account_snapshot(
        initial_cash_cents=200_000_000,
        history_start=decision.stamp(2, "00:00"),
        as_of=decision.stamp(6, "08:55"),
        events=events,
        trading_dates=[decision.stamp(day).date() for day in (2, 5, 6)],
        calendar_id="synthetic",
        execution_complete=True,
        execution_checkpoint_id="synthetic-prefix",
        cash_basis="trade_date_cash",
        unresolved_order_ids=(),
        max_positions=5,
    )
    assert execution.account.cash_cents == before.cash_cents
    assert execution.capital_return_receivable_cents == execution.receivable_cents == before.receivable_cents
    paid = decision.snapshot(
        [*events, {"action": "CAPITAL_RETURN", "code": "A", "date": decision.stamp(6, "12:00").isoformat(), "total": 10000, "entitlement_id": "A-refund"}],
        prices={"A": decision.observation(raw=9000)},
    )
    assert paid.equity_cents == before.equity_cents
    assert paid.cash_cents == before.cash_cents + before.receivable_cents
    assert paid.capital_return_receivable_cents == paid.receivable_cents == 0
    claim["amount"] = 0.001
    with pytest.raises(DecisionError, match="integral number of cents"):
        decision.snapshot(events)


def test_refund_attribution_preserves_original_owner_after_reentry() -> None:
    events, checkpoints, labels = attribution.fixture()
    for event in events:
        if event["action"].startswith("DIVIDEND"):
            event["action"] = event["action"].replace("DIVIDEND", "CAPITAL_RETURN")
    result = build_attribution_inputs(initial_cash=1000, events=events, checkpoints=checkpoints, classifications=labels)
    assert result["checkpoints"][14]["attempt_pnl"] == {"0": 0, "1": -4, "6": 0}
    assert result["checkpoints"][15]["attempt_pnl"] == result["checkpoints"][14]["attempt_pnl"]
    reduced = non_hit_attribution(result["attempts"], result["checkpoints"], initial_equity=1000, span=2)
    assert reduced["whole_study"]["net_pnl_twd"] == -14
    ledger = replay_ledger(1000, events)
    assert all(item["dividend_total"] == 0 for item in ledger["attempts"])
    assert ledger["attempts"][0]["capital_return_total"] == 10


def test_returned_principal_is_not_profit_and_does_not_reduce_purchase_denominator() -> None:
    events = [
        {"action": "BUY", "qty": 100, "total": -1000},
        {"action": "CAPITAL_RETURN_ENTITLEMENT", "total": 0, "amount": 300, "entitlement_id": "refund"},
        {"action": "SPLIT", "total": 0, "old_qty": 100, "new_qty": 70},
        {"action": "SELL", "total": 700, "qty": 70},
        {"action": "CAPITAL_RETURN", "total": 300, "entitlement_id": "refund"},
    ]
    for index, event in enumerate(events):
        event.update(code="A", date=f"2026-01-{index + 1:02d}T09:00:00+08:00")
    unpaid = replay_ledger(1000, events[:4])
    paid = replay_ledger(1000, events)
    assert mark_attempt_pnl(unpaid, {}) == mark_attempt_pnl(paid, {}) == {"0": 0}
    assert unpaid["attempts"][0]["net_cash_flow"] == -300
    attempt = paid["attempts"][0]
    assert attempt["buy_total"] == -1000 and attempt["net_cash_flow"] == 0
    assert attempt["net_return_on_gross_buys"] == 0 and attempt["dividend_total"] == 0


@pytest.mark.parametrize("paid", [False, True])
def test_stress_ranks_unpaid_refund_and_full_rerun_removes_only_original_attempt(paid: bool) -> None:
    config = stress.inputs()

    def corporate(since: datetime, until: datetime, prefix: Sequence[Mapping[str, Any]]) -> CorporateEvidence:
        events: list[dict[str, Any]] = []
        ex, pay = stress.market.stamp(6, "15:30"), stress.market.stamp(9, "15:30")
        if since < ex <= until and any(event.get("order_id") == "A-2-BUY" for event in prefix):
            events.append({"action": "CAPITAL_RETURN_ENTITLEMENT", "code": "A", "date": ex.isoformat(), "total": 0, "amount": 20000, "entitlement_id": "old-A"})
        if paid and since < pay <= until and any(event.get("entitlement_id") == "old-A" for event in prefix):
            events.append({"action": "CAPITAL_RETURN", "code": "A", "date": pay.isoformat(), "total": 20000, "entitlement_id": "old-A"})
        return CorporateEvidence("synthetic-refund", tuple(events), True)

    result = run_best_attempt_stresses(replace(config, corporate_factory=lambda: corporate), counts=(1,))
    assert [item.net_pnl_cents for item in result.ranked_closed_attempts] == [21_992_000, 996_000]
    assert result.ranked_closed_attempts[0].unpaid_receivable_cents == (0 if paid else 2_000_000)
    arm = result.arms[0].result
    assert arm is not None and arm.status == "complete"
    assert all(event["action"] in {"BUY", "SELL"} for event in arm.events)
