"""Synthetic share rights across exact snapshots, chronology and full stress reruns."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

import pytest

from research_core.attempt_stress import run_best_attempt_stresses
from research_core.chronology import CorporateEvidence, PendingRequest
from research_core.decision import ExecutionAccountSnapshot, build_execution_account_snapshot
from research_core.ledger import LedgerError, replay_ledger
from research_core.order_actions import PendingResolution
from scripts.tests import test_research_attempt_stress as stress
from scripts.tests import test_research_decision as decision
from scripts.tests import test_research_intraday_corporate as intraday
from scripts.tests import test_research_order_actions as actions


def claim(when: datetime, *, numerator: int = 201, denominator: int = 2, identity: str = "shares-A") -> dict[str, Any]:
    return {
        "action": "SHARE_ENTITLEMENT",
        "code": "A",
        "date": when.isoformat(),
        "total": 0,
        "entitlement_id": identity,
        "share_numerator": numerator,
        "share_denominator": denominator,
        "valuation_policy": "same-class-raw-close-cent-half-up",
    }


def linked(action: str, when: datetime, **extra: Any) -> dict[str, Any]:
    return {"action": action, "code": "A", "date": when.isoformat(), "total": 0, "entitlement_id": "shares-A", **extra}


def execution_snapshot(events: list[dict[str, Any]]):
    return build_execution_account_snapshot(
        initial_cash_cents=200_000_000,
        history_start=decision.stamp(2, "00:00"),
        as_of=decision.stamp(6, "16:00"),
        events=events,
        trading_dates=[decision.stamp(day).date() for day in (2, 5, 6)],
        calendar_id="synthetic",
        execution_complete=True,
        execution_checkpoint_id="fixture-complete",
        cash_basis="trade_date_cash",
        unresolved_order_ids=(),
        max_positions=5,
    )


def test_claim_only_snapshot_marks_each_half_cent_and_releases_last_reservation() -> None:
    # Two independent 0.005 TWD rights round separately to 0.01 each.
    events = [
        decision.event("BUY", 2),
        claim(decision.stamp(5, "08:00"), numerator=1, denominator=20000),
        claim(decision.stamp(5, "08:01"), numerator=1, denominator=20000, identity="second"),
        decision.event("SELL", 5),
    ]
    snapshot = decision.snapshot(events)
    assert snapshot.holdings == {}
    assert snapshot.occupied_issuer_codes == frozenset({"A"})
    assert snapshot.share_claim_value_cents == 2
    assert snapshot.equity_cents == snapshot.cash_cents + 2 == 200_000_002
    assert execution_snapshot(events).account.reserved_position_codes == frozenset({"A"})
    with pytest.raises(LedgerError, match="missing mark"):
        decision.snapshot(events, prices={})
    events.extend([
        linked("SHARE_CASH_SETTLEMENT", decision.stamp(6, "10:00"), total=0.01),
        {**linked("SHARE_CASH_SETTLEMENT", decision.stamp(6, "10:01"), total=0.01), "entitlement_id": "second"},
    ])
    settled = decision.snapshot(events, prices={})
    assert settled.equity_cents == snapshot.equity_cents
    assert settled.share_claim_value_cents == 0 and settled.occupied_issuer_codes == frozenset()
    assert execution_snapshot(events).account.reserved_position_codes == frozenset()


def test_delivery_adds_tradable_shares_without_changing_attempt_age_or_equity() -> None:
    events = [decision.event("BUY", 2), claim(decision.stamp(5, "08:00")), decision.event("SELL", 5)]
    before = decision.snapshot(events)
    events.append(linked("SHARE_DELIVERY", decision.stamp(6, "08:00"), qty=100))
    after = decision.snapshot(events)
    assert after.holdings["A"].qty == 100 and after.holdings["A"].attempt_id == 0
    assert after.holdings["A"].completed_closes == 3
    assert before.equity_cents == after.equity_cents
    assert before.share_claim_value_cents == 1_005_000 and after.share_claim_value_cents == 5000
    assert before.cash_cents == after.cash_cents


def test_chronology_accepts_claim_only_exit_and_fractional_cash_closure() -> None:
    records = [claim(intraday.at(5, "10:00"), numerator=1, denominator=2), linked("SHARE_CASH_SETTLEMENT", intraday.at(7, "10:00"), total=500)]
    result = intraday.run(intraday.provider(records), decision_factory=actions.buy_and_exit_factory)
    assert result.status == "complete", result.stop_reason
    at_exit = next(snapshot for snapshot in result.snapshots if snapshot.as_of.day == 6)
    assert not at_exit.holdings and at_exit.occupied_issuer_codes == frozenset({"A"})
    assert not result.snapshots[-1].occupied_issuer_codes
    ledger = replay_ledger(2_000_000, result.events)
    assert len(ledger["attempts"]) == 1 and not ledger["open_attempts"]
    assert ledger["attempts"][0]["share_settlement_total"] == 500


def test_delivery_before_queued_exit_requires_corporate_order_policy() -> None:
    result = intraday.run(
        intraday.provider([claim(intraday.at(5, "10:00")), linked("SHARE_DELIVERY", intraday.at(6, "08:50"), qty=100)]),
        decision_factory=actions.buy_and_exit_factory,
    )
    assert result.stop_reason == "pending_conflicts_corporate_action"
    assert not any(event["action"] == "SELL" for event in result.events)


def test_delivery_during_live_sell_stops_without_fictitious_resize() -> None:
    result = intraday.run(
        intraday.provider([claim(intraday.at(5, "10:00")), linked("SHARE_DELIVERY", intraday.at(6, "10:00"), qty=100)]),
        decision_factory=lambda: actions.buy_and_exit_factory(buy_qty=3000),
        execution_provider=actions.execution_with(
            allocation={5: 3000, 6: 1000}, reports={6: (actions.terminal(actions.SELL_A, 6, status="CANCELLED", filled=1000),)}
        ),
        initial_cash_cents=600_000_000,
    )
    assert result.stop_reason == "unsupported_share_count_change_with_live_orders"
    assert result.stop_locator is not None and result.stop_locator["action"] == "SHARE_DELIVERY"
    assert not any(event["action"] == "SHARE_DELIVERY" for event in result.events)


def test_simultaneous_deliveries_remain_separate_pending_order_causes() -> None:
    seen: list[Mapping[str, Any]] = []

    def policy(pending: tuple[PendingRequest, ...], causes: tuple[Mapping[str, Any], ...], snapshot: ExecutionAccountSnapshot):
        seen.extend(causes)
        assert snapshot.account.positions["A"] == 1300
        return tuple(PendingResolution(item.request.intent.order_id, "cancel", "share_delivery", "synthetic-policy") for item in pending)

    result = intraday.run(
        intraday.provider([
            claim(intraday.at(5, "10:00"), numerator=100, denominator=1),
            claim(intraday.at(5, "10:01"), numerator=200, denominator=1, identity="second"),
            linked("SHARE_DELIVERY", intraday.at(6, "08:50"), qty=100),
            {**linked("SHARE_DELIVERY", intraday.at(6, "08:50"), qty=200), "entitlement_id": "second"},
        ]),
        decision_factory=actions.buy_and_exit_factory,
        pending_corporate_policy=policy,
    )
    assert result.status == "complete", result.stop_reason
    assert [event["entitlement_id"] for event in seen] == ["shares-A", "second"]


@pytest.mark.parametrize("settled", [False, True])
def test_best_attempt_waits_for_final_share_claim_and_counts_fractional_cash(settled: bool) -> None:
    config = stress.inputs()

    def corporate(since: datetime, until: datetime, prefix: Sequence[Mapping[str, Any]]) -> CorporateEvidence:
        events = []
        grant, pay = stress.market.stamp(6, "15:30"), stress.market.stamp(12, "15:30")
        if since < grant <= until and any(event.get("order_id") == "A-2-BUY" for event in prefix):
            events.append(claim(grant, numerator=1, denominator=2))
        if settled and since < pay <= until and any(event.get("entitlement_id") == "shares-A" for event in prefix):
            events.append(linked("SHARE_CASH_SETTLEMENT", pay, total=50))
        return CorporateEvidence("synthetic-share-rights", tuple(events), True)

    result = run_best_attempt_stresses(replace(config, corporate_factory=lambda: corporate), counts=(1,))
    assert result.baseline.status == "complete"
    if not settled:
        assert result.ranked_closed_attempts == ()
        assert result.arms[0].unavailable_reason == "insufficient_closed_attempts"
    else:
        # The later A purchase still belongs to the first economically open attempt.
        assert len(result.ranked_closed_attempts) == 1
        assert result.ranked_closed_attempts[0].net_pnl_cents == 19_992_000 + 996_000 + 5000
        assert result.ranked_closed_attempts[0].buy_order_ids == frozenset({"A-2-BUY", "A-5-BUY", "A-8-BUY"})
        arm = result.arms[0].result
        assert arm is not None and arm.status == "complete" and arm.events == ()
