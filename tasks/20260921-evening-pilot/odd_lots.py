"""Bounded residual exits for corporate-action odd lots in the evening pilot."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, time
from types import MappingProxyType
from typing import Any

from research_core.auction import AuctionBatch, CostSchedule
from research_core.chronology import DayFrame, DecisionContext, ExecutionWindow, PriorCloseRequest, SessionRoute

_LOT_SHARES = 1_000
_QUEUED_SUBMISSION = time(14, 0)
_AFTERHOURS_AUCTION = time(14, 30)


def residual_exit_factory(factory: Callable[[], Any]) -> Callable[[], Any]:
    """Split only an already-advised residual SELL into board and after-hours legs.

    The preserved whole-lot policy is asked whether an exit is warranted using a
    shadow, tradable holding.  It still sees the real cash, pending requests and
    issuer occupancy; only the residual holding quantity is substituted.
    """

    def make() -> Any:
        rule = factory()

        def decide(context: DecisionContext) -> Sequence[Any]:
            residuals = {code: held.qty % _LOT_SHARES for code, held in context.snapshot.holdings.items() if held.qty > 0 and held.qty % _LOT_SHARES}
            if not residuals:
                return rule(context)
            shadow_holdings = dict(context.snapshot.holdings)
            for code in residuals:
                held = shadow_holdings[code]
                shadow_qty = max(_LOT_SHARES, (held.qty // _LOT_SHARES) * _LOT_SHARES)
                shadow_holdings[code] = replace(held, qty=shadow_qty)
            shadow_snapshot = replace(context.snapshot, holdings=MappingProxyType(shadow_holdings))
            actions = rule(replace(context, snapshot=shadow_snapshot))
            expanded: list[Any] = []
            for action in actions:
                if not isinstance(action, PriorCloseRequest):
                    expanded.append(action)
                    continue
                order = action.intent
                odd_qty = residuals.get(order.code, 0)
                if order.side != "SELL" or not odd_qty:
                    expanded.append(action)
                    continue
                actual_qty = context.snapshot.holdings[order.code].qty
                whole_qty = actual_qty - odd_qty
                if whole_qty:
                    expanded.append(replace(action, intent=replace(order, order_id=f"{order.order_id}-round", qty=whole_qty)))
                expanded.append(
                    replace(
                        action,
                        intent=replace(order, order_id=f"{order.order_id}-odd", qty=odd_qty),
                        venue="afterhours_odd",
                    )
                )
            return tuple(expanded)

        return decide

    return make


def with_afterhours_odd_windows(frames: Sequence[DayFrame], costs: CostSchedule) -> tuple[DayFrame, ...]:
    """Add simultaneous TWSE/TPEx 14:30 residual-exit windows after each initial frame."""
    result: list[DayFrame] = []
    for index, frame in enumerate(frames):
        if not index:
            result.append(frame)
            continue
        tzinfo = frame.close_at.tzinfo
        submitted_at = datetime.combine(frame.trade_date, _QUEUED_SUBMISSION, tzinfo=tzinfo)
        auction_at = datetime.combine(frame.trade_date, _AFTERHOURS_AUCTION, tzinfo=tzinfo)
        routes = tuple(
            SessionRoute(
                AuctionBatch(
                    exchange=exchange,
                    venue="afterhours_odd",
                    submitted_at=submitted_at,
                    auction_at=auction_at,
                    session_id=f"{exchange}-{frame.trade_date.isoformat()}-afterhours-odd",
                ),
                costs,
            )
            for exchange in ("TWSE", "TPEX")
        )
        window = ExecutionWindow(
            window_id=f"two-market-{frame.trade_date.isoformat()}-afterhours-odd",
            sessions=routes,
            expires_at=auction_at,
            as_of=auction_at,
        )
        result.append(replace(frame, windows=(*frame.windows, window)))
    return tuple(result)


__all__ = ["residual_exit_factory", "with_afterhours_odd_windows"]
