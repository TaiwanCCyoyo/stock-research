"""Corporate facts dated inside a trading session: asked for, placed, or refused with a locator.

Through 005 the runner asked the corporate provider for `(previous, submitted_at]` before an
auction and `(as_of, decision_at]` before a decision, and moved its cursor straight from
`submitted_at` to `as_of` in between. A fact dated at 10:00 on a trading day was therefore never
asked for at all. Every fixture here is synthetic; none of it is a market record.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import pytest

from research_core.chronology import (
    ChronologyError,
    ChronologyResult,
    CorporateEvidence,
    CorporateProvider,
    Scenario,
)
from research_core.ledger import replay_ledger
from scripts.tests import test_research_causal_scenarios as fixture
from scripts.tests import test_research_order_actions as actions

Prefix = tuple[Mapping[str, Any], ...]
BUY_A = actions.BUY_A
SELL_A = actions.SELL_A


def at(day: int, clock: str) -> datetime:
    return fixture.stamp(day, clock)


def holding(prefix: Prefix, code: str, before: datetime) -> int:
    """Shares of `code` held just before `before`, from records dated strictly earlier."""
    held = 0
    for event in prefix:
        if event.get("code") != code or datetime.fromisoformat(str(event["date"])) >= before:
            continue
        if event.get("action") == "BUY":
            held += int(event["qty"])
        elif event.get("action") == "SELL":
            held -= int(event["qty"])
        elif event.get("action") == "SPLIT":
            held = int(event["new_qty"])
    return held


def split(code: str, when: datetime, **extra: Any) -> dict[str, Any]:
    return {"action": "SPLIT", "code": code, "date": when.isoformat(), "total": 0, **extra}


def entitlement(code: str, when: datetime, entitlement_id: str = "ent-A", amount: int = 500, **extra: Any) -> dict[str, Any]:
    return {
        "action": "DIVIDEND_ENTITLEMENT",
        "code": code,
        "date": when.isoformat(),
        "total": 0,
        "amount": amount,
        "entitlement_id": entitlement_id,
        **extra,
    }


def payment(code: str, when: datetime, entitlement_id: str = "ent-A", amount: int = 500) -> dict[str, Any]:
    return {"action": "DIVIDEND", "code": code, "date": when.isoformat(), "total": amount, "entitlement_id": entitlement_id}


def provider(
    records: Sequence[dict[str, Any]] = (),
    *,
    notices: Sequence[dict[str, Any]] = (),
    backdated: Sequence[dict[str, Any]] = (),
    gap: tuple[datetime, datetime] | None = None,
    calls: list[tuple[datetime, datetime]] | None = None,
):
    """A provider over dated records that places each one against the records dated before it.

    A SPLIT doubles whatever is held just before it, and an entitlement or a split of a code not
    held produces no event -- the same holder-of-record rule the prototype provider uses.
    """

    def provide(since: datetime, until: datetime, prefix: Prefix) -> CorporateEvidence:
        if calls is not None:
            calls.append((since, until))
        if gap is not None and since < gap[1] and gap[0] < until:
            return CorporateEvidence(f"coverage-gap-{since.isoformat()}", (), False)
        chosen: list[dict[str, Any]] = []
        for record in records:
            when = datetime.fromisoformat(record["date"])
            if not since < when <= until:
                continue
            known = prefix + tuple(chosen)
            if record["action"] == "SPLIT":
                held = holding(known, record["code"], when)
                if held <= 0:
                    continue
                record = {**record, "old_qty": held, "new_qty": held * 2, "qty": held}
            elif record["action"] == "DIVIDEND_ENTITLEMENT" and holding(known, record["code"], when) <= 0:
                continue
            chosen.append(record)
        return CorporateEvidence(
            f"fixture-corporate-{until.isoformat()}",
            tuple(chosen),
            True,
            tuple(item for item in notices if since < datetime.fromisoformat(item["date"]) <= until),
            tuple(item for item in backdated if since < datetime.fromisoformat(item["available_at"]) <= until),
        )

    return provide


def run(corporate: CorporateProvider, **overrides: Any) -> ChronologyResult:
    return actions.run(corporate_provider=corporate, frames=actions.frames_with_an_afternoon(), **overrides)


def actions_of(result: ChronologyResult) -> list[tuple[str, str, str]]:
    return [(str(event["action"]), str(event["code"]), str(event["date"])[5:16]) for event in result.events]


# --------------------------------------------------------------------------------------------
# The intervals now partition the clock.
# --------------------------------------------------------------------------------------------


def test_the_queried_intervals_chain_with_no_gap_and_include_each_session() -> None:
    calls: list[tuple[datetime, datetime]] = []
    result = run(provider(calls=calls), decision_factory=actions.buy_and_exit_factory)
    assert result.status == "complete", result.stop_reason
    assert calls[0][0] == fixture.stamp(2, "00:00")
    assert all(left[1] == right[0] for left, right in zip(calls, calls[1:], strict=False)), "no instant is skipped"
    assert calls[-1][1] == fixture.stamp(fixture.DAYS[-1])
    # The two sessions with an order in them: the buy on the 5th, the sell on the 6th.
    assert (at(5, "08:55"), at(5, "13:30")) in calls
    assert (at(6, "08:55"), at(6, "13:30")) in calls


def test_a_fact_at_each_boundary_is_found_exactly_once_in_the_interval_that_owns_it() -> None:
    """Half-open `(since, until]`: an instant belongs to the interval it ends."""
    moments = {
        "submission": at(5, "08:55"),
        "in_session": at(5, "10:00"),
        "as_of": at(5, "13:30"),
        "decision": at(5, "16:00"),
    }
    notices = [split("Z", moment, ratio_numerator=2, ratio_denominator=1) for moment in moments.values()]
    result = run(provider(notices=notices), decision_factory=actions.buy_and_exit_factory)
    assert result.status == "complete", result.stop_reason
    found: dict[str, list[tuple[datetime, datetime]]] = {}
    for record in result.corporate_records:
        for notice in record.evidence.share_count_notices:
            found.setdefault(str(notice["date"]), []).append((record.since, record.until))
    assert found == {
        moments["submission"].isoformat(): [(at(2, "16:00"), at(5, "08:55"))],
        moments["in_session"].isoformat(): [(at(5, "08:55"), at(5, "13:30"))],
        moments["as_of"].isoformat(): [(at(5, "08:55"), at(5, "13:30"))],
        moments["decision"].isoformat(): [(at(5, "13:30"), at(5, "16:00"))],
    }
    intraday = [(outcome.at, outcome.outcome) for outcome in result.corporate_outcomes]
    assert intraday == [(moments["in_session"], "recorded_notice"), (moments["as_of"], "recorded_notice")]


# --------------------------------------------------------------------------------------------
# What can be placed is placed at its own instant.
# --------------------------------------------------------------------------------------------


def test_an_entitlement_after_the_morning_fill_belongs_to_the_buyer() -> None:
    """Before 006 this fact was never asked for, so the buyer silently lost it."""
    result = run(provider([entitlement("A", at(5, "10:00"))]), decision_factory=actions.buy_and_exit_factory)
    assert result.status == "complete", result.stop_reason
    assert actions_of(result)[:2] == [("BUY", "A", "01-05T09:00"), ("DIVIDEND_ENTITLEMENT", "A", "01-05T10:00")]
    (outcome,) = result.corporate_outcomes
    assert (outcome.kind, outcome.action, outcome.outcome, outcome.time_basis) == ("event", "DIVIDEND_ENTITLEMENT", "merged", "unstated")


def test_a_payment_after_the_sale_in_the_same_session_is_still_paid_to_that_attempt() -> None:
    """Entitled before the auction, sold at 09:00, paid at 11:00 the same day."""
    records = [entitlement("A", at(6, "08:50")), payment("A", at(6, "11:00"))]
    result = run(provider(records), decision_factory=actions.buy_and_exit_factory)
    assert result.status == "complete", result.stop_reason
    assert [row[:2] for row in actions_of(result)] == [
        ("BUY", "A"),
        ("DIVIDEND_ENTITLEMENT", "A"),
        ("SELL", "A"),
        ("DIVIDEND", "A"),
    ]
    ledger = replay_ledger(fixture.INITIAL_CENTS / 100, list(result.events), max_positions=5)
    (closed,) = ledger["attempts"]
    assert closed["dividend_total"] == 500
    assert ledger["dividend_receivable"] == 0


def test_an_intraday_split_with_no_live_order_on_its_code_is_applied_at_its_instant() -> None:
    """The buy filled completely at 09:00, so at 10:00 nothing live depends on the old count."""
    result = run(
        provider([split("A", at(5, "10:00"))]),
        decision_factory=actions.buy_and_exit_factory,
        execution_provider=actions.execution_with(allocation={6: 2000}),
    )
    assert result.status == "complete", result.stop_reason
    assert actions_of(result) == [
        ("BUY", "A", "01-05T09:00"),
        ("SPLIT", "A", "01-05T10:00"),
        ("SELL", "A", "01-06T09:00"),
    ]
    assert result.events[2]["qty"] == 2000, "the exit decided at 16:00 saw the post-split holding"


def test_a_date_only_fact_on_a_code_with_no_activity_that_session_is_placed() -> None:
    result = run(provider([entitlement("A", at(7, "12:00"), time_basis="date_only")]), decision_factory=actions.buy_and_exit_factory)
    assert result.status == "complete", result.stop_reason
    assert "DIVIDEND_ENTITLEMENT" not in [row[0] for row in actions_of(result)], "sold on the 6th: not a holder on the 7th"


# --------------------------------------------------------------------------------------------
# What cannot be placed stops the run and says exactly where.
# --------------------------------------------------------------------------------------------


def test_a_share_count_notice_while_a_buy_is_still_live_stops_with_its_locator() -> None:
    """The buy was sized on the old share count and is still working when the count changes."""
    reports = {5: (actions.terminal(BUY_A, 5, status="EXPIRED", filled=0),)}
    result = run(
        provider(notices=[split("A", at(5, "10:00"), ratio_numerator=2, ratio_denominator=1)]),
        decision_factory=actions.buy_and_exit_factory,
        execution_provider=actions.execution_with(allocation={5: 0}, reports=reports),
    )
    assert result.status == "incomplete"
    assert result.stop_reason == "unsupported_share_count_change_with_live_orders"
    assert dict(result.stop_locator or {}) == {
        "window_id": "window-5",
        "since": at(5, "08:55").isoformat(),
        "until": at(5, "13:30").isoformat(),
        "kind": "notice",
        "action": "SPLIT",
        "code": "A",
        "date": at(5, "10:00").isoformat(),
        "time_basis": "unstated",
        "live_order_ids": [BUY_A],
    }
    assert [record.order_id for record in result.terminations] == [BUY_A], "what the session did is kept"
    assert not any(event["action"] == "SPLIT" for event in result.events), "and nothing from the interval is applied"


def test_a_split_while_a_partly_filled_sell_is_still_live_stops() -> None:
    reports = {6: (actions.terminal(SELL_A, 6, status="CANCELLED", filled=1000),)}
    result = run(
        provider([split("A", at(6, "10:00"))]),
        decision_factory=lambda: actions.buy_and_exit_factory(buy_qty=3000),
        execution_provider=actions.execution_with(allocation={5: 3000, 6: 1000}, reports=reports),
        initial_cash_cents=600_000_000,
    )
    assert result.stop_reason == "unsupported_share_count_change_with_live_orders"
    assert result.stop_locator is not None and result.stop_locator["live_order_ids"] == [SELL_A]
    assert result.stop_locator["kind"] == "event"
    assert [(event["action"], event["qty"]) for event in result.events] == [("BUY", 3000), ("SELL", 1000)]


def test_a_fact_at_the_same_instant_as_a_fill_on_its_code_stops() -> None:
    """Entitled at 09:00 while the same shares are sold at 09:00: neither order may be assumed."""
    result = run(provider([entitlement("A", at(6, "09:00"))]), decision_factory=actions.buy_and_exit_factory)
    assert result.stop_reason == "unsupported_same_timestamp_sequence"
    assert result.stop_locator is not None and result.stop_locator["date"] == at(6, "09:00").isoformat()


def test_a_date_only_fact_on_a_code_traded_that_session_stops() -> None:
    result = run(provider([entitlement("A", at(5, "12:00"), time_basis="date_only")]), decision_factory=actions.buy_and_exit_factory)
    assert result.stop_reason == "unsupported_date_only_sequence"
    assert result.stop_locator is not None and result.stop_locator["time_basis"] == "date_only"


def test_missing_coverage_inside_a_session_is_incomplete_not_empty() -> None:
    result = run(provider(gap=(at(5, "09:30"), at(5, "09:31"))), decision_factory=actions.buy_and_exit_factory)
    assert result.stop_reason == "corporate_evidence_incomplete"
    assert result.stop_locator is not None and result.stop_locator["window_id"] == "window-5"
    assert [event["action"] for event in result.events] == ["BUY"], "the fill happened; only the corporate side is unknown"
    empty = run(provider(), decision_factory=actions.buy_and_exit_factory)
    assert empty.status == "complete" and empty.corporate_outcomes == ()


def test_a_fact_published_after_its_effective_instant_is_never_placed_into_the_past() -> None:
    """Effective 10:00, first available 18:00: a 16:00 decision must not see it, and it cannot be backfilled."""
    late = split("A", at(5, "10:00"), available_at=at(5, "18:00").isoformat(), ratio_numerator=2, ratio_denominator=1)
    result = run(provider(backdated=[late]), decision_factory=actions.buy_and_exit_factory)
    assert result.stop_reason == "corporate_fact_available_after_its_effective_boundary"
    assert result.stop_locator is not None
    assert (result.stop_locator["date"], result.stop_locator["available_at"]) == (at(5, "10:00").isoformat(), at(5, "18:00").isoformat())
    assert result.snapshots[-1].as_of == at(5, "16:00"), "the decision before publication ran on what was known"


def test_a_provider_that_returns_a_fact_before_it_is_available_is_refused() -> None:
    early = entitlement("A", at(5, "10:00"), available_at=at(5, "18:00").isoformat())
    with pytest.raises(ChronologyError, match="before it was available"):
        run(provider([early]), decision_factory=actions.buy_and_exit_factory)


def test_a_notice_about_a_held_code_without_its_event_is_refused() -> None:
    """Notices exist for codes we do not hold. One about a code we DO hold, with no ledger event,
    would change our share count where the ledger never hears about it."""
    notice = split("A", at(5, "10:00"), ratio_numerator=2, ratio_denominator=1)
    with pytest.raises(ChronologyError, match="names a held code but no event"):
        run(provider(notices=[notice]), decision_factory=actions.buy_and_exit_factory)
    # The same notice for a code this account does not hold is fine, which is what notices are for.
    fine = run(provider(notices=[split("Z", at(5, "10:00"), ratio_numerator=2, ratio_denominator=1)]), decision_factory=actions.buy_and_exit_factory)
    assert fine.status == "complete", fine.stop_reason


def test_an_unknown_time_basis_is_refused() -> None:
    with pytest.raises(ChronologyError, match="time_basis"):
        CorporateEvidence("bad", (entitlement("A", at(5, "10:00"), time_basis="roughly"),), True)


def test_delay_moves_the_session_the_fact_is_found_in_but_never_duplicates_it() -> None:
    """Each fact once per arm, whichever interval the arm's own sessions put it in."""
    records = [entitlement("A", at(6, "10:00"))]
    for scenario in (Scenario("baseline", frozenset(), 0), Scenario("delay-one", frozenset(), 1)):
        result = run(provider(records), decision_factory=actions.buy_and_exit_factory, scenario=scenario)
        seen = [event for record in result.corporate_records for event in record.evidence.events]
        assert len(seen) <= 1
        assert len([event for event in result.events if event["action"] == "DIVIDEND_ENTITLEMENT"]) == len(seen)


def test_frames_with_the_cutoff_at_the_decision_still_query_the_session() -> None:
    """The base harness closes each window at the decision instant; the session is still asked for."""
    calls: list[tuple[datetime, datetime]] = []
    result = actions.run(corporate_provider=provider(calls=calls), decision_factory=actions.buy_and_exit_factory)
    assert result.status == "complete", result.stop_reason
    assert (at(5, "08:55"), at(5, "16:00")) in calls
