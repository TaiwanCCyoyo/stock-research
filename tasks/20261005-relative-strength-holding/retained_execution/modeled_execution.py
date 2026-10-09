"""Named modeled terminal reports for a fully observed offline execution window.

This is an adapter for 006's provider seam, not a market-data parser or broker receipt source.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from prototype.providers import UNOBSERVED, SessionExecutionEvidence

from research_core.auction import AuctionQuote, RoutedOrder
from research_core.chronology import ExecutionEvidence, ExecutionWindow
from research_core.decision import ExecutionAccountSnapshot
from research_core.order_lifecycle import FillReport, LifecycleError, TerminalReport, reconcile_cohort_lifecycle


class ModeledExecutionError(ValueError):
    """A modeled termination policy was underspecified."""


@dataclass(frozen=True)
class EndOfWindowTermination:
    """A named non-observed policy; it never supplies market qualifications or fills."""

    model_id: str
    basis: str
    max_positions: int

    def __post_init__(self) -> None:
        if not self.model_id or not self.basis or self.max_positions <= 0:
            raise ModeledExecutionError("model_id, basis, and positive max_positions are required")


def build_modeled_execution_provider(sessions: Mapping[Any, SessionExecutionEvidence], policy: EndOfWindowTermination):
    """Build a fresh provider closure for one arm.

    Explicit reports remain evidence.  The policy only emits a modeled terminal report for an
    unresolved order once the queried window has expired, and only after the normal lifecycle has
    accepted complete quotes, bands, allocation, and cash/slot competition.
    """

    def provide(window: ExecutionWindow, snapshot: ExecutionAccountSnapshot, routes: Sequence[RoutedOrder]) -> ExecutionEvidence:
        day = window.sessions[0].batch.auction_at.date()
        evidence = sessions.get(day)
        if evidence is None:
            return ExecutionEvidence(f"no-execution-evidence-{day.isoformat()}", {}, (), False, True)
        quotes: dict[tuple[str, str], AuctionQuote] = {}
        complete = True
        for route in routes:
            quote = evidence.quotes.get(route.order.code)
            if quote is None or quote.status == UNOBSERVED:
                complete = False
                continue
            quotes[(route.batch.session_id, route.order.code)] = quote.to_auction_quote()
        sent = {route.order.order_id for route in routes}
        explicit = tuple(report for report in evidence.reports if report.order_id in sent)
        if not complete or window.as_of < window.expires_at:
            return ExecutionEvidence(evidence.evidence_id, quotes, explicit, complete, evidence.exclusive)
        try:
            reconciled = reconcile_cohort_lifecycle(
                snapshot.account,
                tuple(routes),
                quotes,
                max_positions=policy.max_positions,
                expires_at=window.expires_at,
                as_of=window.as_of,
                reports=explicit,
            )
        except LifecycleError:
            return ExecutionEvidence(evidence.evidence_id, quotes, explicit, complete, evidence.exclusive)
        model_at = window.expires_at
        # Do not append an expiry before an explicit report the evidence places or makes
        # available later. Returning the untouched evidence lets chronology preserve the
        # unresolved/incomplete condition instead of manufacturing an ordering.
        if any(report.event_at > model_at or report.available_at > model_at for report in explicit):
            return ExecutionEvidence(evidence.evidence_id, quotes, explicit, complete, evidence.exclusive)
        outstanding = set(reconciled.unresolved_order_ids)
        filled = {outcome.order_id: outcome.filled_qty for outcome in reconciled.initial_result.outcomes}
        for report in reconciled.visible_reports:
            if isinstance(report, FillReport):
                filled[report.order_id] = filled.get(report.order_id, 0) + report.qty
        modeled: list[TerminalReport] = []
        terminal_ids = {report.order_id for report in reconciled.visible_reports if isinstance(report, TerminalReport)}
        next_sequence = max((report.sequence for report in explicit), default=0) + 1
        for route in routes:
            order_id = route.order.order_id
            if order_id not in outstanding or order_id in terminal_ids:
                continue
            quantity = filled.get(order_id, 0)
            status = "CANCELLED" if quantity else "EXPIRED"
            modeled.append(
                TerminalReport(
                    report_id=f"modeled-{policy.model_id}-{status.lower()}-{order_id}-{model_at.isoformat()}",
                    order_id=order_id,
                    event_at=model_at,
                    available_at=model_at,
                    sequence=next_sequence,
                    status=status,
                    cumulative_filled_qty=quantity,
                    source_id=f"modeled:{policy.model_id}",
                )
            )
            next_sequence += 1
        return ExecutionEvidence(
            f"{evidence.evidence_id}|modeled:{policy.model_id}",
            quotes,
            explicit + tuple(modeled),
            complete,
            evidence.exclusive,
        )

    return provide


__all__ = ["EndOfWindowTermination", "ModeledExecutionError", "build_modeled_execution_provider"]
