"""Synthetic consumer checks for same-class share-claim attribution only."""

from __future__ import annotations

import pytest

from research_core.attribution import mark_attempt_pnl
from research_core.attribution_inputs import build_attribution_inputs
from research_core.ledger import mark_equity, replay_ledger


def _event(action: str, **values: object) -> dict[str, object]:
    return {"action": action, "code": "A", "date": "2026-09-18T09:00:00+08:00", **values}


def test_claim_only_attempt_is_marked_and_settlement_closes_it() -> None:
    events = [
        _event("BUY", qty=10, total=-100),
        _event(
            "SHARE_ENTITLEMENT", total=0, entitlement_id="claim", share_numerator=1, share_denominator=2, valuation_policy="same-class-raw-close-cent-half-up"
        ),
        _event("SELL", qty=10, total=100),
    ]
    claim_only = replay_ledger(1_000, events)
    assert claim_only["positions"] == {}
    assert mark_attempt_pnl(claim_only, {"A": 20}) == {"0": 10.0}
    assert mark_equity(claim_only, {"A": 20}) == 1_010
    settled = replay_ledger(1_000, events + [_event("SHARE_CASH_SETTLEMENT", total=7, entitlement_id="claim")])
    assert settled["open_attempts"] == []
    assert mark_attempt_pnl(settled, {}) == {"0": 7.0}


def test_reentry_with_claim_is_one_attempt_and_reconciles_all_account_pnl() -> None:
    events = [
        _event("BUY", qty=10, total=-100),
        _event(
            "SHARE_ENTITLEMENT", total=0, entitlement_id="claim", share_numerator=1, share_denominator=2, valuation_policy="same-class-raw-close-cent-half-up"
        ),
        _event("SELL", qty=10, total=100),
        {**_event("BUY", qty=1, total=-10), "date": "2026-09-18T09:01:00+08:00"},
    ]
    ledger = replay_ledger(1_000, events)
    pnl = mark_attempt_pnl(ledger, {"A": 10})
    assert pnl == {"0": 5.0}
    assert sum(pnl.values()) == pytest.approx(mark_equity(ledger, {"A": 10}) - 1_000)

    checkpoints = [
        {"date": "2026-09-18T09:00:00+08:00", "event_count": 0, "raw_marks": {}},
        {"date": "2026-09-18T09:00:00+08:00", "event_count": 1, "raw_marks": {"A": 10}},
        {"date": "2026-09-18T09:00:00+08:00", "event_count": 2, "raw_marks": {"A": 10}},
        {"date": "2026-09-18T09:00:00+08:00", "event_count": 3, "raw_marks": {"A": 10}},
        {"date": "2026-09-18T09:01:00+08:00", "event_count": 4, "raw_marks": {"A": 10}},
    ]
    inputs = build_attribution_inputs(initial_cash=1_000, events=events, checkpoints=checkpoints, classifications={"0": None})
    assert inputs["attempts"] == [{"id": "0", "code": "A", "entry_index": 1, "exit_index": None, "hit": None, "captured_pnl_twd": None}]
    assert inputs["checkpoints"][-1]["equity"] == 1_005
