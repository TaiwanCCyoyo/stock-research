"""Execution and corporate-action evidence providers, built from dated facts rather than a script.

Codex's 002 review, item 4: the old runner took a pre-written list of ledger events and stamped
them all at 13:30 after the fills, then called that a corporate-action integration. That ordering
is wrong in both directions -- an entitlement recorded after the opening auction gives the shares
to whoever bought that morning and takes it from whoever sold -- and it was not evidence at all,
because it could not express "we do not know".

`run_chronology` already provides the correct seam: it calls the corporate provider for the
half-open interval `(cursor, until]` immediately before each auction and again before each
decision, and it refuses events outside that interval. So placement is not something to implement
here -- it falls out of **when a fact is dated**:

- an entitlement dated before the auction's submission attaches to the holder of record, and
  survives that holder selling into the same auction;
- a buyer whose fill is at 09:00 is not entitled to something dated 08:55;
- a split dated before submission changes the share count the auction then works with.

Completeness is declared per interval and is not the same thing as an empty event list. An
interval with no declared coverage returns `complete=False`, which stops the run with
`corporate_evidence_incomplete` rather than reporting "no corporate actions".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from fractions import Fraction
from typing import Any

from prototype.execution_policy import CapacityPolicy, PolicyError, PriceBandPolicy
from research_core.auction import AuctionQuote, RoutedOrder
from research_core.chronology import TIME_BASES, CorporateEvidence, ExecutionEvidence, ExecutionWindow
from research_core.decision import ExecutionAccountSnapshot
from research_core.ledger import replay_ledger
from research_core.order_lifecycle import FillReport, LifecycleError, TerminalReport, reconcile_cohort_lifecycle


class ProviderError(ValueError):
    """The injected evidence cannot answer what the runner asked for."""


# The one status that means "we did not observe this", as opposed to observing that nothing traded.
UNOBSERVED = "UNKNOWN"


# --------------------------------------------------------------------------------------------
# Execution evidence
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionQuote:
    """One code's observed opening auction, with its band and capacity as stated policies.

    `status` is the observation, not an outcome. `UNKNOWN` is a real answer and produces an
    incomplete window rather than a no-trade, because this evidence cannot tell a halt, a
    delisting and a source omission apart -- see `build_execution_provider` for why that
    distinction changes which stop reason the run gives.
    """

    status: str
    price_cents: int | None
    band: PriceBandPolicy | None
    capacity: CapacityPolicy | None
    source_id: str

    def __post_init__(self) -> None:
        if self.status not in {"TRADED", "HALT", "NO_TRADE", "UNKNOWN"}:
            raise ProviderError("unsupported quote status")
        if self.status == "TRADED" and (self.price_cents is None or self.band is None or self.capacity is None):
            raise ProviderError("a traded quote needs a price, a band policy and a capacity policy")

    def to_auction_quote(self) -> AuctionQuote:
        if self.status != "TRADED":
            return AuctionQuote(
                status=self.status, price_cents=None, limits=None, allocated_shares=None, source_id=self.source_id if self.status != "UNKNOWN" else ""
            )
        assert self.band is not None and self.capacity is not None
        return AuctionQuote(
            status="TRADED",
            price_cents=self.price_cents,
            limits=self.band.resolve(),
            allocated_shares=self.capacity.shares,
            capacity_basis=self.capacity.basis,
            source_id=self.source_id,
        )


@dataclass(frozen=True)
class SessionExecutionEvidence:
    """Everything observed about one session's execution, including what was not observed."""

    evidence_id: str
    quotes: Mapping[str, SessionQuote]
    reports: tuple[FillReport | TerminalReport, ...] = ()
    exclusive: bool = True

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ProviderError("execution evidence must state an id")


@dataclass(frozen=True)
class SyntheticReceiptRule:
    """A stated synthetic broker that closes whatever an opening auction left outstanding.

    Session-dated fixture receipts only fit the arm they were written for: a delay or omission arm
    sends different orders on different sessions, and an order left outstanding without a receipt
    stops the run as `execution_unresolved` -- correctly. A stress matrix needs every arm to be able
    to execute, so this rule issues the receipt a broker would send at the session cutoff.

    It does not model the market to decide which orders those are: it asks the same shared
    lifecycle the runner is about to use, with no reports supplied, and takes its
    `unresolved_order_ids`. An order the board refused outright -- a limit outside the band, cash or
    slots already committed -- is terminal there and gets no receipt, which is what a broker would
    also not send. What remains is written as `CANCELLED` at whatever actually filled, or `EXPIRED`
    when nothing did.

    A modelling choice with a required basis, never an observation, and it never overrides an
    explicit receipt for the same order.

    **Fixture worlds only.** `input-contract.md` is explicit that a known no-fill without a terminal
    receipt must stop the run, and that a receipt must never be invented to cover missing evidence.
    That rule is about real evidence: there, silence means "we do not know". Here the world is
    invented and its broker's behaviour is part of it, stated in `basis`. A real market adapter must
    leave this `None` and supply the venue's own receipts; with it set, an unresolved order can no
    longer tell you that your evidence has a hole.
    """

    basis: str
    max_positions: int
    event_time: time | None = None  # the session cutoff; the offline session clock supplies it

    def __post_init__(self) -> None:
        if not self.basis or self.event_time is None or self.max_positions <= 0:
            raise ProviderError("a synthetic receipt rule must state its basis, cutoff time and position ceiling")

    def receipts(
        self,
        window: ExecutionWindow,
        snapshot: ExecutionAccountSnapshot,
        routes: Sequence[RoutedOrder],
        quotes: Mapping[tuple[str, str], AuctionQuote],
    ) -> tuple[TerminalReport, ...]:
        if not routes or self.event_time is None:
            return ()
        try:
            resolved = reconcile_cohort_lifecycle(
                snapshot.account,
                tuple(routes),
                quotes,
                max_positions=self.max_positions,
                expires_at=window.expires_at,
                as_of=window.as_of,
                reports=(),
            )
        except LifecycleError:
            # The runner will raise on the same evidence and say why; inventing a receipt here
            # would only bury it.
            return ()
        initial = resolved.initial_result
        outstanding = set(resolved.unresolved_order_ids) | set(initial.next_state.pending_order_ids if initial.next_state is not None else ())
        if not outstanding:
            return ()
        filled = {outcome.order_id: outcome.filled_qty for outcome in initial.outcomes}
        day = window.sessions[0].batch.auction_at.date()
        moment = datetime.combine(day, self.event_time, tzinfo=window.sessions[0].batch.auction_at.tzinfo)
        issued: list[TerminalReport] = []
        for route in routes:
            order_id = route.order.order_id
            if order_id not in outstanding:
                continue
            quantity = filled.get(order_id, 0)
            status = "CANCELLED" if quantity else "EXPIRED"
            issued.append(
                TerminalReport(
                    report_id=f"synthetic-{status.lower()}-{order_id}-{day.isoformat()}",
                    order_id=order_id,
                    event_at=moment,
                    available_at=moment,
                    sequence=1,
                    status=status,
                    cumulative_filled_qty=quantity,
                    source_id="synthetic-broker-rule",
                )
            )
        return tuple(issued)


def build_execution_provider(sessions: Mapping[date, SessionExecutionEvidence], receipt_rule: SyntheticReceiptRule | None = None):
    """An `ExecutionProvider` over injected per-session evidence.

    Two different things must not be reported the same way, and the earlier version reported them
    the same way:

    - **No evidence.** A routed order whose code has no quote, or whose quote says `UNKNOWN`,
      leaves this provider unable to say anything about that session. It answers `complete=False`,
      and the run stops with `execution_evidence_incomplete` -- naming the actual problem. The
      previous version declared the window complete and let the auction discover the gap, so the
      run stopped with `execution_unresolved`, which reads as "the lifecycle did not add up" rather
      than "we never observed this".
    - **A known no-trade.** `HALT` and `NO_TRADE` are observations. The evidence is complete, the
      auction records the order as unfilled for that stated reason, and the order stays outstanding
      until a terminal receipt ends it. That receipt is still required: a known no-fill with no
      receipt is `execution_unresolved`, and it must never be turned into an invented `EXPIRED` or
      a silent continuation.
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
        # A receipt belongs to an order that was sent that session. The fixtures key receipts by
        # session because that is where the baseline sent them; a delay or omission arm that sends
        # the order on a different session has no receipt for it here, and handing the lifecycle a
        # receipt for an order it was never given is refused there (`report order_id is
        # unrecognized`). A receipt the baseline needed and a rerun lacks is not hidden by this:
        # an order left outstanding without one still stops as `execution_unresolved`.
        sent = {route.order.order_id for route in routes}
        reports = tuple(report for report in evidence.reports if report.order_id in sent)
        if receipt_rule is not None and complete:
            explicit = {report.order_id for report in reports}
            reports += receipt_rule.receipts(window, snapshot, [route for route in routes if route.order.order_id not in explicit], quotes)
        return ExecutionEvidence(evidence.evidence_id, quotes, reports, complete, evidence.exclusive)

    return provide


# --------------------------------------------------------------------------------------------
# Corporate evidence
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CorporateFact:
    """One dated corporate fact. The date is what decides which interval it lands in.

    `time_basis` says how `at` was established: `exact` (a published instant), `assumed` (a
    modelling choice, which is what every fixture before 006 used), or `date_only` (only the date is
    known, so it cannot be ordered against anything else that happened that day).

    `available_at` is when the fact could first be known, if later than `at`. Such a fact is not
    reported for the interval it took effect in -- that would let a decision read it early -- and is
    reported as `backdated` for the interval it becomes available in, which the runner refuses to
    place into the past.
    """

    action: str
    code: str
    at: datetime
    basis: str
    amount: float | None = None
    entitlement_id: str | None = None
    ratio: Fraction | None = None
    time_basis: str = "assumed"
    available_at: datetime | None = None

    @property
    def visible_at(self) -> datetime:
        return self.at if self.available_at is None else self.available_at

    def __post_init__(self) -> None:
        if self.time_basis not in TIME_BASES:
            raise ProviderError("time_basis must be exact, assumed or date_only")
        if self.available_at is not None and (self.available_at.tzinfo is None or self.available_at < self.at):
            raise ProviderError("available_at must be timezone-aware and not before the fact itself")
        if self.action not in {"DIVIDEND_ENTITLEMENT", "DIVIDEND", "SPLIT"}:
            raise ProviderError("unsupported corporate action")
        if self.at.tzinfo is None or self.at.utcoffset() is None:
            raise ProviderError("a corporate fact must be timezone-aware")
        if not self.basis:
            raise ProviderError("a corporate fact must state its basis")
        if self.action in {"DIVIDEND_ENTITLEMENT", "DIVIDEND"} and not self.entitlement_id:
            raise ProviderError("entitlements and payments must carry an entitlement_id")
        if self.action == "SPLIT" and (self.ratio is None or self.ratio <= 0):
            raise ProviderError("a split must carry a positive ratio")


@dataclass(frozen=True)
class CorporateCoverage:
    """An interval this evidence actually speaks for, and whether it is complete there."""

    since: datetime
    until: datetime
    complete: bool
    evidence_id: str

    def __post_init__(self) -> None:
        if self.until < self.since:
            raise ProviderError("coverage must not end before it begins")


def build_corporate_provider(
    facts: Sequence[CorporateFact],
    coverage: Sequence[CorporateCoverage],
    *,
    initial_cash_cents: int,
    max_positions: int,
):
    """A `CorporateProvider` that answers only for intervals it is declared to cover.

    A split's share counts are read from the recorded prefix through `replay_ledger`, not tracked
    separately: `old_qty` must equal the holding the ledger will find, or the ledger rejects it.
    A fact about a code we do not hold produces no event, which is how "bought this morning, so
    not entitled" is expressed -- the buyer's fill is simply later than the entitlement.

    An entitlement with no amount makes the interval incomplete rather than producing a zero. The
    shared ledger refuses a non-positive amount, and inventing one would read as "no dividend".

    Splits are additionally reported as share-count notices, holding or not. A split of a code we
    do not hold changes nothing about this account, so it produces no event -- but an order already
    queued to buy that code was sized and priced against the old share count, and the runner cannot
    see that from the events alone.

    Each fact is placed against the records dated strictly BEFORE it, plus what this call has
    already emitted. Before 006 the whole prefix was replayed, which was only right because every
    interval started after the last recorded event. The session interval `(submitted_at, as_of]`
    breaks that: a receipt at 11:00 must not make its buyer the holder of record at 10:00. A record
    at exactly the fact's instant is excluded here, and the runner stops on that case for the same
    code rather than let either order be assumed.
    """

    def moment(record: Mapping[str, Any]) -> datetime:
        return datetime.fromisoformat(str(record["date"]))

    def stamped(fact: CorporateFact, record: dict[str, Any]) -> dict[str, Any]:
        return {**record, "time_basis": fact.time_basis, "available_at": fact.visible_at.isoformat(), "evidence_basis": fact.basis}

    def provide(since: datetime, until: datetime, prefix: Sequence[Mapping[str, Any]]) -> CorporateEvidence:
        covering = [item for item in coverage if item.since <= since and item.until >= until]
        if not covering:
            return CorporateEvidence(f"uncovered-{since.isoformat()}-{until.isoformat()}", (), False)
        if any(not item.complete for item in covering):
            return CorporateEvidence(covering[0].evidence_id, (), False)

        order = lambda fact: (fact.at, fact.code, fact.action)  # noqa: E731
        selected = sorted((fact for fact in facts if since < fact.at <= until and fact.visible_at <= until), key=order)
        backdated = tuple(
            stamped(fact, {"action": fact.action, "code": fact.code, "date": fact.at.isoformat()})
            for fact in sorted((fact for fact in facts if fact.at <= since and since < fact.visible_at <= until), key=order)
        )
        if any(fact.action == "DIVIDEND_ENTITLEMENT" and fact.amount is None for fact in selected):
            return CorporateEvidence(f"{covering[0].evidence_id}-amount-unknown", (), False)

        records = list(prefix)
        entitled: set[str] = set()
        events: list[Mapping[str, Any]] = []
        for fact in selected:
            # Python's sort is stable: at one timestamp the recorded prefix stays ahead of what this
            # call emitted, which matches the order the runner merges them in.
            known = sorted([record for record in records if moment(record) < fact.at] + events, key=moment)
            ledger = replay_ledger(initial_cash_cents / 100.0, known, max_positions=max_positions)
            positions = dict(ledger["positions"])
            unpaid = {str(item["id"]): item for item in ledger["dividend_entitlements"] if not item["paid"]}
            if fact.action == "DIVIDEND_ENTITLEMENT":
                if positions.get(fact.code, 0) <= 0:
                    # Not a holder of record at this instant, so no entitlement arises.
                    continue
                events.append(
                    stamped(
                        fact,
                        {
                            "action": "DIVIDEND_ENTITLEMENT",
                            "code": fact.code,
                            "date": fact.at.isoformat(),
                            "total": 0,
                            "amount": fact.amount,
                            "entitlement_id": fact.entitlement_id,
                        },
                    )
                )
                entitled.add(str(fact.entitlement_id))
            elif fact.action == "DIVIDEND":
                identifier = str(fact.entitlement_id)
                if identifier not in unpaid and identifier not in entitled:
                    # No entitlement of ours to pay. Nothing is created out of nothing.
                    continue
                amount = fact.amount if fact.amount is not None else float(unpaid[identifier]["amount"])
                events.append(
                    stamped(
                        fact,
                        {
                            "action": "DIVIDEND",
                            "code": fact.code,
                            "date": fact.at.isoformat(),
                            "total": amount,
                            "entitlement_id": identifier,
                        },
                    )
                )
            else:
                held = positions.get(fact.code, 0)
                if held <= 0:
                    continue
                assert fact.ratio is not None
                new_qty = Fraction(held) * fact.ratio
                if new_qty.denominator != 1:
                    raise ProviderError(f"{fact.code} split ratio does not produce whole shares from {held}")
                events.append(
                    stamped(
                        fact,
                        {
                            "action": "SPLIT",
                            "code": fact.code,
                            "date": fact.at.isoformat(),
                            "total": 0,
                            "old_qty": held,
                            "new_qty": int(new_qty),
                            "qty": int(new_qty) - held,
                        },
                    )
                )
        notices = tuple(
            stamped(
                fact,
                {
                    "action": "SPLIT",
                    "code": fact.code,
                    "date": fact.at.isoformat(),
                    "ratio_numerator": fact.ratio.numerator if fact.ratio is not None else None,
                    "ratio_denominator": fact.ratio.denominator if fact.ratio is not None else None,
                },
            )
            for fact in selected
            if fact.action == "SPLIT"
        )
        return CorporateEvidence(covering[0].evidence_id, tuple(events), True, notices, backdated)

    return provide


def no_corporate_actions(*, evidence_id: str = "declared-complete-no-corporate-actions"):
    """A provider that declares every interval complete and empty.

    Only for fixtures that are deliberately testing something else. It asserts a fact -- that the
    interval genuinely had no corporate actions -- which is exactly the assertion `unknown` is not
    allowed to make silently.
    """

    def provide(since: datetime, until: datetime, prefix: Sequence[Mapping[str, Any]]) -> CorporateEvidence:
        return CorporateEvidence(f"{evidence_id}-{until.isoformat()}", (), True)

    return provide


def band_or_fail(band: PriceBandPolicy) -> PriceBandPolicy:
    """Surface a band policy's own refusal early rather than at fill time."""
    try:
        band.resolve()
    except PolicyError:
        raise
    return band


__all__ = [
    "UNOBSERVED",
    "CorporateCoverage",
    "CorporateFact",
    "ProviderError",
    "SessionExecutionEvidence",
    "SessionQuote",
    "SyntheticReceiptRule",
    "band_or_fail",
    "build_corporate_provider",
    "build_execution_provider",
    "no_corporate_actions",
]
