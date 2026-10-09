"""Shared-reservation residual reports through a later venue and close valuation.

All dates, prints, fills, capacities and costs are synthetic fixture inputs.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from research_core.auction import AccountState, AuctionBatch, AuctionQuote, CostSchedule, OrderIntent, RoutedOrder, resolve_auction_batch
from research_core.decision import CloseObservation, build_decision_snapshot, build_execution_account_snapshot
from research_core.execution_prices import PriceLimits
from research_core.ledger import replay_ledger
from research_core.order_lifecycle import FillReport, LifecycleError, LifecycleResult, TerminalReport, reconcile_cohort_lifecycle, reconcile_order_lifecycle


def t(clock: str, day: int = 5) -> datetime:
    return datetime.fromisoformat(f"2026-01-{day:02d}T{clock}:00+08:00")


TWSE = AuctionBatch("TWSE", "regular_open", t("08:55"), t("09:00"), "synthetic-twse")
TPEX = AuctionBatch("TPEX", "regular_open", t("08:55"), t("09:00"), "synthetic-tpex")
COSTS = CostSchedule(Fraction(0), 2000, 1, "ceil", Fraction(0), 1, "ceil", Fraction(0), 1, "ceil")
OTHER_COSTS = replace(COSTS, min_commission_cents=3000)
LIMIT_A = PriceLimits(Decimal("90"), Decimal("110"))
LIMIT_B = PriceLimits(Decimal("180"), Decimal("220"))
STATE = AccountState(200_000_000, {}, t("08:55"), "trade_date_cash")
ROUTES = (
    RoutedOrder(OrderIntent("a", "A", "BUY", 2000, 11000, t("16:00", 2)), TWSE, COSTS),
    RoutedOrder(OrderIntent("b", "B", "BUY", 2000, 22000, t("16:00", 2)), TPEX, OTHER_COSTS),
)
QUOTES = {
    (TWSE.session_id, "A"): AuctionQuote("TRADED", 10000, LIMIT_A, 1000, "synthetic-a-print", "fixed-allocation"),
    (TPEX.session_id, "B"): AuctionQuote("TRADED", 20000, LIMIT_B, 1000, "synthetic-b-print", "fixed-allocation"),
}


def reports() -> list[FillReport | TerminalReport]:
    return [
        FillReport("a-later", "a", t("09:02"), t("09:02"), 1, 1000, 10100, LIMIT_A, "synthetic-a-later", "fixed-allocation"),
        TerminalReport("b-cancel", "b", t("09:03"), t("09:03"), 2, "CANCELLED", 1000, "synthetic-b-terminal"),
        TerminalReport("a-full", "a", t("09:04"), t("09:04"), 3, "FILLED", 2000, "synthetic-a-terminal"),
    ]


def reconcile(**overrides: Any) -> LifecycleResult:
    args: dict[str, Any] = {
        "state": STATE,
        "routed_orders": ROUTES,
        "quotes": QUOTES,
        "max_positions": 5,
        "expires_at": t("13:30"),
        "as_of": t("09:04"),
        "reports": reports(),
    }
    args.update(overrides)
    return reconcile_cohort_lifecycle(**args)


def test_interleaved_two_market_reports_then_odd_lot_and_close_reconcile() -> None:
    result = reconcile()
    assert result.continuation_allowed and result.next_state is not None
    assert result.next_state.cash_cents == 159_895_000
    assert result.next_state.positions == {"A": 2000, "B": 1000}
    assert [item.commission_cents for item in result.initial_result.outcomes] == [2000, 3000]
    assert len(result.additional_events) == 1
    assert result.additional_events[0]["commission_cents"] == 0
    assert result.additional_events[0]["session_id"] == TWSE.session_id
    events = [*result.initial_result.ledger_events, *result.additional_events]
    assert [event["date"] for event in events] == [t("09:00").isoformat(), t("09:00").isoformat(), t("09:02").isoformat()]

    before_odd = build_execution_account_snapshot(
        initial_cash_cents=200_000_000,
        history_start=t("00:00", 2),
        as_of=t("09:05"),
        events=events,
        trading_dates=[date(2026, 1, 2), date(2026, 1, 5)],
        calendar_id="synthetic-calendar",
        execution_complete=result.continuation_allowed,
        execution_checkpoint_id="synthetic-all-terminals-visible",
        cash_basis="trade_date_cash",
        unresolved_order_ids=result.unresolved_order_ids,
        max_positions=5,
    )
    odd_batch = AuctionBatch("TWSE", "intraday_odd", t("09:05"), t("09:10"), "synthetic-odd")
    # An independent prior-close child, not a fabricated same-day signal.
    child = OrderIntent("a-odd", "A", "BUY", 250, 11000, t("16:00", 2))
    odd = resolve_auction_batch(
        before_odd.account,
        [child],
        {"A": AuctionQuote("TRADED", 10200, LIMIT_A, 250, "synthetic-odd-print", "fixed-odd-allocation")},
        batch=odd_batch,
        costs=COSTS,
        max_positions=5,
    )
    assert odd.continuation_allowed and odd.next_state is not None
    assert odd.next_state.cash_cents == 157_343_000
    assert odd.next_state.positions == {"A": 2250, "B": 1000}
    events.extend(odd.ledger_events)
    close = build_decision_snapshot(
        initial_cash_cents=200_000_000,
        history_start=t("00:00", 2),
        as_of=t("16:00"),
        events=events,
        session_closes=[t("13:30", 2), t("13:30")],
        calendar_id="synthetic-calendar",
        prices={
            code: CloseObservation(price, Decimal(price) / 200, t("13:30"), t("15:00"), "synthetic-close") for code, price in {"A": 10300, "B": 20200}.items()
        },
        execution_complete=odd.continuation_allowed,
        execution_checkpoint_id="synthetic-odd-complete",
        cash_basis="trade_date_cash",
        unresolved_order_ids=(),
        max_positions=5,
    )
    assert close.cash_cents == 157_343_000
    assert close.equity_cents == 200_718_000
    assert close.holdings["A"].qty == 2250 and close.holdings["A"].completed_closes == 1
    replayed = replay_ledger(2_000_000, events, marks={"A": 103, "B": 202}, max_positions=5)
    assert replayed["cash"] == close.cash_cents / 100
    assert replayed["marked_equity"] == close.equity_cents / 100


def test_one_markets_unresolved_or_unavailable_terminal_blocks_later_session() -> None:
    early = reconcile(as_of=t("09:03"))
    assert early.unresolved_order_ids == ("a",)
    assert early.next_state is None and not early.continuation_allowed
    delayed = reports()
    delayed[1] = replace(delayed[1], available_at=t("09:06"))
    invisible = reconcile(reports=delayed)
    assert invisible.next_state is None and not invisible.continuation_allowed
    assert set(invisible.unresolved_order_ids) == {"a", "b"}
    assert len(invisible.additional_events) == 1  # Known A fill remains diagnostic, not a complete book.


def test_each_markets_later_fill_uses_its_own_cumulative_fee_and_metadata() -> None:
    later = [
        FillReport("b-later", "b", t("09:01"), t("09:01"), 1, 1000, 20100, LIMIT_B, "b-source", "b-capacity"),
        TerminalReport("b-full", "b", t("09:02"), t("09:02"), 2, "FILLED", 2000, "b-terminal"),
        TerminalReport("a-cancel", "a", t("09:03"), t("09:03"), 3, "CANCELLED", 1000, "a-terminal"),
    ]
    result = reconcile(reports=later)
    assert result.continuation_allowed and result.next_state is not None
    assert result.next_state.cash_cents == 149_895_000
    event = result.additional_events[0]
    assert event["session_id"] == TPEX.session_id and event["source_id"] == "b-source"
    assert event["capacity_basis"] == "b-capacity" and event["commission_cents"] == 0
    # Nonzero proportional rate makes using the other route's zero rate observable.
    proportional = replace(OTHER_COSTS, commission_rate=Fraction(1, 100))
    changed = reconcile(routed_orders=(ROUTES[0], replace(ROUTES[1], costs=proportional)), reports=later)
    assert changed.initial_result.outcomes[1].commission_cents == 200_000
    assert changed.additional_events[0]["commission_cents"] == 201_000


def test_initial_missing_market_cannot_be_made_complete_by_later_reports() -> None:
    result = reconcile(quotes={(TWSE.session_id, "A"): QUOTES[(TWSE.session_id, "A")]})
    assert not result.initial_result.state_complete and result.next_state is None
    assert result.additional_events == ()


def test_initially_unaffordable_other_market_is_not_readmitted_by_terminal_replay() -> None:
    # Combined limit reservations exceed 650,000 TWD. After A completes more
    # cheaply, B would fit, but its original rejected admission must stay fixed.
    state = replace(STATE, cash_cents=65_000_000)
    result = reconcile(state=state, reports=[reports()[0], reports()[2]])
    assert result.initial_result.outcomes[1].reason == "insufficient_reserved_cash"
    assert result.next_state is not None and result.next_state.positions == {"A": 2000}
    assert result.next_state.cash_cents == 44_898_000
    with pytest.raises(LifecycleError):
        reconcile(state=state)  # The rejected B request cannot receive a residual cancellation report.


def test_single_market_wrapper_and_cohort_use_identical_lifecycle_arithmetic() -> None:
    own_reports = [reports()[0], reports()[2]]
    legacy = reconcile_order_lifecycle(
        STATE,
        [ROUTES[0].order],
        {"A": QUOTES[(TWSE.session_id, "A")]},
        batch=TWSE,
        costs=COSTS,
        max_positions=5,
        expires_at=t("13:30"),
        as_of=t("09:04"),
        reports=own_reports,
    )
    cohort = reconcile(routed_orders=(ROUTES[0],), quotes={(TWSE.session_id, "A"): QUOTES[(TWSE.session_id, "A")]}, reports=own_reports)
    assert cohort == legacy


@pytest.mark.parametrize(
    "overrides",
    [
        {"routed_orders": ()},
        {"max_positions": None},
        {"as_of": t("08:59")},
        {"expires_at": t("08:59")},
        {"expires_at": t("13:30", 6)},
        {"as_of": datetime(2026, 1, 5, 9, 4)},
        {"reports": "invalid"},
    ],
)
def test_invalid_cohort_lifecycle_metadata_fails(overrides: dict[str, Any]) -> None:
    with pytest.raises(LifecycleError):
        reconcile(**overrides)


def test_global_report_order_and_original_route_limits_remain_enforced() -> None:
    with pytest.raises(LifecycleError):
        reconcile(reports=[reports()[1], reports()[0], reports()[2]])
    bad = reports()
    first_fill = bad[0]
    assert isinstance(first_fill, FillReport)
    bad[0] = replace(first_fill, limits=PriceLimits(Decimal("90"), Decimal("120")))
    with pytest.raises(LifecycleError):
        reconcile(reports=bad)
