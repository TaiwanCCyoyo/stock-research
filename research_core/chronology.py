"""Pure chronological execution over explicitly supplied calendars and evidence.

Callbacks are trusted, audited code, not a sandbox or PIT certification. No
market lookup, seed selection, best-attempt selection or acceptance gate.

Corporate evidence is asked for over intervals that partition the run's clock with no gap:
`(previous, submitted_at]` before each auction, `(submitted_at, as_of]` for the part of the session
the auction and its receipts occupy, and `(as_of, decision_at]` before each decision. Through 005
the middle interval was never asked for -- the cursor jumped from `submitted_at` to `as_of` -- so a
fact dated inside a trading session was silently skipped. Inside that interval only facts that
can be placed without inventing an order of events are merged; everything else stops the run
with a named reason and a locator (see `corporate_during` inside `run_chronology`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from research_core.auction import AuctionBatch, AuctionQuote, CostSchedule, OrderIntent, RoutedOrder
from research_core.decision import CloseObservation, DecisionSnapshot, ExecutionAccountSnapshot, build_decision_snapshot, build_execution_account_snapshot
from research_core.execution_prices import PriceError, round_stock_price
from research_core.order_actions import CancelRequest, OrderLineage, OrderTermination, PendingResolution
from research_core.order_lifecycle import FillReport, LifecycleResult, TerminalReport, reconcile_cohort_lifecycle
from research_core.signals import SignalDraw, SignalIdentity, SignalOmission


class ChronologyError(ValueError):
    """Invalid run topology, callback contract or event sequence; not a strategy loss."""


def _text(value: Any) -> None:
    if not isinstance(value, str) or not value:
        raise ChronologyError("identity must be a nonempty string")


def _time(value: Any) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(hours=8):
        raise ChronologyError("timestamps must be aware +08:00 datetimes")


def _integer(value: Any, *, minimum: int = 1) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ChronologyError(f"integer must be at least {minimum}")


def _sequence(value: Any) -> None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ChronologyError("expected a sequence")


# How a corporate record's timestamp was established. `exact` is a published instant, `assumed`
# is a modelling choice (the prototype's 08:50), `date_only` is a date with no instant, which
# cannot be ordered against anything else that happened on that date. A record that states
# nothing is `unstated` and is treated like `assumed`: placed at its timestamp, never reordered.
TIME_BASES = ("exact", "assumed", "date_only")

# Outcomes for a record inside `(submitted_at, as_of]`. Anything but the first two stops the run.
INTRADAY_MERGED = "merged"
INTRADAY_NOTICE = "recorded_notice"
INTRADAY_UNSUPPORTED = (
    "unsupported_share_count_change_with_live_orders",
    "unsupported_same_timestamp_sequence",
    "unsupported_date_only_sequence",
)


def _moment_of(record: Mapping[str, Any], name: str) -> datetime:
    when = datetime.fromisoformat(str(record.get(name)))
    _time(when)
    return when


def _events(value: Any) -> tuple[Mapping[str, Any], ...]:
    _sequence(value)
    if any(not isinstance(event, Mapping) for event in value):
        raise ChronologyError("events must contain mappings")
    return tuple(MappingProxyType(dict(event)) for event in value)


@dataclass(frozen=True)
class SessionRoute:
    batch: AuctionBatch
    costs: CostSchedule

    def __post_init__(self) -> None:
        if not isinstance(self.batch, AuctionBatch) or not isinstance(self.costs, CostSchedule):
            raise ChronologyError("session route requires batch and costs")


@dataclass(frozen=True)
class ExecutionWindow:
    window_id: str
    sessions: tuple[SessionRoute, ...]
    expires_at: datetime
    as_of: datetime

    def __post_init__(self) -> None:
        _text(self.window_id)
        _sequence(self.sessions)
        if not self.sessions or any(not isinstance(route, SessionRoute) for route in self.sessions):
            raise ChronologyError("window requires nonempty session routes")
        object.__setattr__(self, "sessions", tuple(self.sessions))
        _time(self.expires_at)
        _time(self.as_of)
        first = self.sessions[0].batch
        keys: set[tuple[str, str]] = set()
        ids: set[str] = set()
        for route in self.sessions:
            batch = route.batch
            if (batch.submitted_at, batch.auction_at, batch.venue) != (first.submitted_at, first.auction_at, first.venue):
                raise ChronologyError("window sessions must be simultaneous and share a venue")
            key = (batch.exchange, batch.venue)
            if key in keys or batch.session_id in ids:
                raise ChronologyError("duplicate session route")
            keys.add(key)
            ids.add(batch.session_id)
        if self.expires_at < first.auction_at or self.as_of < first.auction_at:
            raise ChronologyError("expiry and cutoff must not precede auction")


@dataclass(frozen=True)
class DayFrame:
    trade_date: date
    close_at: datetime
    decision_at: datetime
    prices: Mapping[str, CloseObservation]
    windows: tuple[ExecutionWindow, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.trade_date, date) or isinstance(self.trade_date, datetime):
            raise ChronologyError("trade_date must be date-only")
        _time(self.close_at)
        _time(self.decision_at)
        if self.close_at.date() != self.trade_date or self.decision_at.date() != self.trade_date or self.close_at > self.decision_at:
            raise ChronologyError("close and decision must be ordered on frame date")
        if not isinstance(self.prices, Mapping):
            raise ChronologyError("prices must be a mapping")
        for code, observation in self.prices.items():
            _text(code)
            if not isinstance(observation, CloseObservation) or observation.observed_at != self.close_at or observation.available_at > self.decision_at:
                raise ChronologyError("close observations must match this frame and be available by decision")
        object.__setattr__(self, "prices", MappingProxyType(dict(self.prices)))
        _sequence(self.windows)
        if any(not isinstance(window, ExecutionWindow) for window in self.windows):
            raise ChronologyError("windows must contain ExecutionWindow")
        object.__setattr__(self, "windows", tuple(self.windows))


@dataclass(frozen=True)
class PriorCloseRequest:
    intent: OrderIntent
    exchange: str
    venue: str
    signal: SignalIdentity | None = None
    # Present only on a replacement: the order this one stands in for, and why. A request with no
    # lineage is an original, which is what every request was before replacements existed.
    lineage: OrderLineage | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.intent, OrderIntent) or self.exchange not in {"TWSE", "TPEX"}:
            raise ChronologyError("request requires an intent and supported exchange")
        if self.venue not in {"regular_open", "intraday_odd", "afterhours_odd"}:
            raise ChronologyError("unsupported request venue")
        if self.signal is not None:
            if not isinstance(self.signal, SignalIdentity):
                raise ChronologyError("request signal must be SignalIdentity")
            if (self.signal.code, self.signal.side) != (self.intent.code, self.intent.side) or self.signal.origin_at > self.intent.decision_at:
                raise ChronologyError("signal must match request code/side and precede its decision")
        if self.lineage is not None and not isinstance(self.lineage, OrderLineage):
            raise ChronologyError("request lineage must be OrderLineage")


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    omitted_order_ids: frozenset[str]
    extra_delay: int
    required_omission_ids: frozenset[str] | None = None
    signal_omission: SignalOmission | None = None

    def __post_init__(self) -> None:
        _text(self.scenario_id)
        if not isinstance(self.omitted_order_ids, frozenset):
            raise ChronologyError("omitted_order_ids must be a frozenset")
        for identity in self.omitted_order_ids:
            _text(identity)
        required = self.omitted_order_ids if self.required_omission_ids is None else self.required_omission_ids
        if not isinstance(required, frozenset) or not required <= self.omitted_order_ids:
            raise ChronologyError("required omissions must be a frozenset subset of omitted IDs")
        object.__setattr__(self, "required_omission_ids", required)
        if self.signal_omission is not None and not isinstance(self.signal_omission, SignalOmission):
            raise ChronologyError("signal omission must be an explicit SignalOmission")
        _integer(self.extra_delay, minimum=0)


@dataclass(frozen=True)
class PendingRequest:
    request: PriorCloseRequest
    due_index: int


@dataclass(frozen=True)
class DecisionContext:
    snapshot: DecisionSnapshot
    pending: tuple[PendingRequest, ...]
    # Every order that has already ended, in the order it ended. A rule that ignores this field
    # behaves exactly as it did before the field existed.
    terminations: tuple[OrderTermination, ...] = ()


@dataclass(frozen=True)
class ExecutionEvidence:
    evidence_id: str
    quotes: Mapping[tuple[str, str], AuctionQuote]
    reports: tuple[FillReport | TerminalReport, ...]
    complete: bool
    exclusive: bool

    def __post_init__(self) -> None:
        _text(self.evidence_id)
        if type(self.complete) is not bool or type(self.exclusive) is not bool or not isinstance(self.quotes, Mapping):
            raise ChronologyError("execution evidence requires explicit boolean status and quote mapping")
        _sequence(self.reports)
        if any(not isinstance(report, (FillReport, TerminalReport)) for report in self.reports):
            raise ChronologyError("invalid execution report")
        object.__setattr__(self, "quotes", MappingProxyType(dict(self.quotes)))
        object.__setattr__(self, "reports", tuple(self.reports))


@dataclass(frozen=True)
class CorporateEvidence:
    """Corporate facts for one interval: what happened to this account, and what happened at all.

    `events` are the ledger events this account experiences -- a split of a code it does not hold
    produces none, correctly, because nothing of its changed. But an order already queued to buy
    that code was sized and priced against the old share count, and without some record of the
    action the runner has no way to know that. `share_count_notices` is that record: facts that
    change a code's share count, reported whether or not they moved this account's position. They
    are notices only; they never become ledger events and never change cash or holdings.
    """

    evidence_id: str
    events: tuple[Mapping[str, Any], ...]
    complete: bool
    share_count_notices: tuple[Mapping[str, Any], ...] = ()
    # Facts that first became available inside this interval although they took effect at or
    # before its start. Placing one would mean rewriting a prefix a decision has already read, so
    # the runner stops on any of them instead of inserting it into the past.
    backdated: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        _text(self.evidence_id)
        if type(self.complete) is not bool:
            raise ChronologyError("corporate evidence requires explicit boolean completeness")
        object.__setattr__(self, "events", _events(self.events))
        object.__setattr__(self, "share_count_notices", _events(self.share_count_notices))
        object.__setattr__(self, "backdated", _events(self.backdated))
        for notice in self.share_count_notices:
            _text(notice.get("code"))
            if notice.get("action") != "SPLIT":
                raise ChronologyError("a share-count notice must name a share-count action")
        for record in (*self.events, *self.share_count_notices, *self.backdated):
            basis = record.get("time_basis")
            if basis is not None and basis not in TIME_BASES:
                raise ChronologyError("corporate time_basis must be exact, assumed or date_only")


@dataclass(frozen=True)
class CorporateRecord:
    since: datetime
    until: datetime
    evidence: CorporateEvidence


@dataclass(frozen=True)
class CorporateOutcome:
    """What happened to one corporate record found inside a session's `(submitted_at, as_of]`."""

    window_id: str
    since: datetime
    until: datetime
    kind: str  # "event" or "notice"
    action: str
    code: str
    at: datetime
    time_basis: str
    outcome: str
    live_order_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AmendmentRecord:
    """A replacement the corporate policy created. It never appears in `decisions`, so it is kept here."""

    window_id: str
    at: datetime
    parent_order_id: str
    request: PriorCloseRequest


@dataclass(frozen=True)
class WindowRecord:
    window_id: str
    evidence_id: str
    routes: tuple[RoutedOrder, ...]
    result: LifecycleResult | None
    evidence: ExecutionEvidence


@dataclass(frozen=True)
class DecisionRecord:
    at: datetime
    requests: tuple[PriorCloseRequest, ...]
    omitted_order_ids: tuple[str, ...]


@dataclass(frozen=True)
class ChronologyResult:
    status: str
    stop_reason: str | None
    scenario: Scenario
    calendar_id: str
    initial_checkpoint_id: str
    events: tuple[Mapping[str, Any], ...]
    snapshots: tuple[DecisionSnapshot, ...]
    windows: tuple[WindowRecord, ...]
    pending: tuple[PendingRequest, ...]
    decisions: tuple[DecisionRecord, ...]
    corporate_records: tuple[CorporateRecord, ...]
    matched_omission_ids: frozenset[str]
    unmatched_omission_ids: frozenset[str]
    evidence_basis: str = "caller_supplied_calendar_and_providers"
    signals: tuple[SignalIdentity, ...] = ()
    signal_draws: tuple[SignalDraw, ...] = ()
    sampled_omission_ids: frozenset[str] = frozenset()
    terminations: tuple[OrderTermination, ...] = ()
    # 006 additions, all defaulted so a result built by older code reads the same.
    amendments: tuple[AmendmentRecord, ...] = ()
    corporate_outcomes: tuple[CorporateOutcome, ...] = ()
    stop_locator: Mapping[str, Any] | None = None

    def requests(self) -> tuple[PriorCloseRequest, ...]:
        """Every request the run created: decision output in order, then policy amendments."""
        return tuple(request for record in self.decisions for request in record.requests) + tuple(item.request for item in self.amendments)


# A rule that only ever advises orders. This is what every rule was before withdrawals existed
# and it remains a complete, supported contract.
DecisionRule = Callable[[DecisionContext], Sequence[PriorCloseRequest]]
# A rule that may also take back an order it has not yet had submitted. `run_chronology` accepts
# either; `attempt_stress.StressInputs.for_rerun` currently accepts only `DecisionRule`, because
# its cross-run identity check is written over requests alone.
ActionRule = Callable[[DecisionContext], Sequence[PriorCloseRequest | CancelRequest]]
ExecutionProvider = Callable[[ExecutionWindow, ExecutionAccountSnapshot, tuple[RoutedOrder, ...]], ExecutionEvidence]
CorporateProvider = Callable[[datetime, datetime, tuple[Mapping[str, Any], ...]], CorporateEvidence]
# Asked only when a corporate action has changed a share count since a queued order was fixed.
# It receives the conflicting requests, the corporate events that caused the conflict, and the
# post-action account, and must answer for each one. There is no default: whether a resting order
# survives a split is a broker-by-broker fact this runner will not assume.
PendingCorporatePolicy = Callable[
    [tuple["PendingRequest", ...], tuple[Mapping[str, Any], ...], ExecutionAccountSnapshot],
    Sequence[PendingResolution],
]


def _validate_frames(frames: Sequence[DayFrame], start: datetime) -> None:
    _sequence(frames)
    if not frames or any(not isinstance(frame, DayFrame) for frame in frames):
        raise ChronologyError("frames must be a nonempty sequence of DayFrame")
    previous_date: date | None = None
    cursor = start
    window_ids: set[str] = set()
    session_ids: set[str] = set()
    for frame in frames:
        if previous_date is not None and frame.trade_date <= previous_date:
            raise ChronologyError("frame dates must be strictly increasing and unique")
        if frame.close_at <= start or frame.decision_at <= cursor:
            raise ChronologyError("frames must follow history start and previous decision")
        routes: set[tuple[str, str]] = set()
        for window in frame.windows:
            if window.window_id in window_ids:
                raise ChronologyError("window IDs must be unique in run")
            window_ids.add(window.window_id)
            first = window.sessions[0].batch
            if first.submitted_at < cursor or window.as_of > frame.decision_at:
                raise ChronologyError("execution windows overlap or follow the decision cutoff")
            clocks = (first.submitted_at, first.auction_at, window.expires_at, window.as_of)
            if any(clock.date() != frame.trade_date for clock in clocks):
                raise ChronologyError("window timestamps must match frame date")
            for session in window.sessions:
                batch = session.batch
                key = (batch.exchange, batch.venue)
                if key in routes or batch.session_id in session_ids:
                    raise ChronologyError("duplicate frame route or run session ID")
                routes.add(key)
                session_ids.add(batch.session_id)
            cursor = window.as_of
        cursor = frame.decision_at
        previous_date = frame.trade_date


def run_chronology(
    *,
    initial_cash_cents: int,
    max_positions: int,
    history_start: datetime,
    initial_checkpoint_id: str,
    frames: Sequence[DayFrame],
    calendar_id: str,
    calendar_complete: bool,
    scenario: Scenario,
    decision_factory: Callable[[], DecisionRule] | Callable[[], ActionRule],
    execution_provider: ExecutionProvider,
    corporate_provider: CorporateProvider,
    pending_corporate_policy: PendingCorporatePolicy | None = None,
) -> ChronologyResult:
    """Rerun decisions and fixed prior-close requests over a declared calendar.

    Missing execution/marks/corporate coverage returns incomplete. Invalid input
    raises ChronologyError. No callback receives a baseline trade list. Replay
    checkpoint IDs are internal labels, not authenticated source evidence.

    A queued request may be withdrawn by its own rule before the session it waits for, and an
    order that has ended is visible to later decisions so a replacement can name what it replaces
    and ask for no more than was left. Without `pending_corporate_policy`, a corporate action that
    changes a share count a queued order depends on stops the run rather than submitting an order
    that no longer describes the world.
    """
    try:
        _integer(initial_cash_cents)
        _integer(max_positions)
        _time(history_start)
        _text(initial_checkpoint_id)
        _text(calendar_id)
        if calendar_complete is not True or not isinstance(scenario, Scenario):
            raise ChronologyError("a declared complete calendar and Scenario are required")
        if not all(callable(callback) for callback in (decision_factory, execution_provider, corporate_provider)):
            raise ChronologyError("providers and decision_factory must be callable")
        if pending_corporate_policy is not None and not callable(pending_corporate_policy):
            raise ChronologyError("pending_corporate_policy must be callable when supplied")
        _validate_frames(frames, history_start)
        frames = tuple(frames)
        rule = decision_factory()
        if not callable(rule):
            raise ChronologyError("decision_factory must create a callable rule")
        events: tuple[Mapping[str, Any], ...] = ()
        snapshots: list[DecisionSnapshot] = []
        windows: list[WindowRecord] = []
        pending: list[PendingRequest] = []
        decisions: list[DecisionRecord] = []
        corporate_records: list[CorporateRecord] = []
        order_ids: set[str] = set()
        report_ids: set[str] = set()
        terminations: list[OrderTermination] = []
        ended: dict[str, OrderTermination] = {}
        position_of: dict[str, int] = {}
        signal_of: dict[str, SignalIdentity | None] = {}
        parent_of: dict[str, str] = {}
        # Every split already applied, kept for the whole run rather than per interval: a split can
        # be consumed by the corporate call before a decision and only invalidate an order at the
        # session two calls later, so the conflict has to be dated against the order it stales.
        # A notice and a real event both land here: an order queued against a code that splits is
        # stale whether or not this account held any of it when the split happened.
        applied_splits: list[tuple[datetime, str, Mapping[str, Any]]] = []
        signals: dict[str, SignalIdentity] = {}
        signal_draws: dict[str, SignalDraw] = {}
        sampled_omission_ids: set[str] = set()
        amendments: list[AmendmentRecord] = []
        corporate_outcomes: list[CorporateOutcome] = []
        # Requests that were generated but never queued. Only used to say why a replacement naming
        # one is refused: such an order never terminated, so nothing can replace it.
        never_queued: set[str] = set()
        cursor = history_start
        checkpoint = 0
        frame_index = 0

        def label() -> str:
            nonlocal checkpoint
            checkpoint += 1
            return f"{initial_checkpoint_id}:replay-{checkpoint}"

        def finish(reason: str | None, locator: Mapping[str, Any] | None = None) -> ChronologyResult:
            matched = frozenset(identity for record in decisions for identity in record.omitted_order_ids if identity in scenario.omitted_order_ids)
            unmatched = scenario.omitted_order_ids - matched
            if reason is None and unmatched & (scenario.required_omission_ids or frozenset()):
                reason = "unapplied_omission_targets"
            return ChronologyResult(
                "complete" if reason is None else "incomplete",
                reason,
                scenario,
                calendar_id,
                initial_checkpoint_id,
                events,
                tuple(snapshots),
                tuple(windows),
                tuple(pending),
                tuple(decisions),
                tuple(corporate_records),
                matched,
                unmatched,
                signals=tuple(signals.values()),
                signal_draws=tuple(signal_draws.values()),
                sampled_omission_ids=frozenset(sampled_omission_ids),
                terminations=tuple(terminations),
                amendments=tuple(amendments),
                corporate_outcomes=tuple(corporate_outcomes),
                stop_locator=None if locator is None else MappingProxyType(dict(locator)),
            )

        def book(at: datetime, prefix: tuple[Mapping[str, Any], ...]) -> ExecutionAccountSnapshot:
            return build_execution_account_snapshot(
                initial_cash_cents=initial_cash_cents,
                history_start=history_start,
                as_of=at,
                events=prefix,
                trading_dates=[frame.trade_date for frame in frames[: frame_index + 1]],
                calendar_id=calendar_id,
                execution_complete=True,
                execution_checkpoint_id=label(),
                cash_basis="trade_date_cash",
                unresolved_order_ids=(),
                max_positions=max_positions,
            )

        def record_end(termination: OrderTermination) -> None:
            if termination.order_id in ended:
                raise ChronologyError("an order cannot terminate twice")
            position_of[termination.order_id] = len(terminations)
            terminations.append(termination)
            ended[termination.order_id] = termination

        def claim_replacement(parent_order_id: str, child_order_id: str) -> None:
            """Mark a terminated order as replaced, so its residual cannot be claimed again.

            The guard is repeated here rather than left to the caller's validation: this is the
            point where the residual actually changes hands, so it is the point that has to be
            impossible to get past twice.
            """
            previous = ended[parent_order_id]
            if previous.replaced_by is not None:
                raise ChronologyError("parent order has already been replaced")
            replaced = replace(previous, replaced_by=child_order_id)
            terminations[position_of[parent_order_id]] = replaced
            ended[parent_order_id] = replaced

        def ask(since: datetime, until: datetime, prefix: tuple[Mapping[str, Any], ...]) -> CorporateEvidence:
            """One provider call, validated the same way for every interval."""
            evidence = corporate_provider(since, until, prefix)
            if not isinstance(evidence, CorporateEvidence):
                raise ChronologyError("corporate_provider must return CorporateEvidence")
            corporate_records.append(CorporateRecord(since, until, evidence))
            if not evidence.complete:
                return evidence
            previous = since
            for event in evidence.events:
                if event.get("action") not in {
                    "DIVIDEND_ENTITLEMENT",
                    "DIVIDEND",
                    "CAPITAL_RETURN_ENTITLEMENT",
                    "CAPITAL_RETURN",
                    "SPLIT",
                    "SHARE_ENTITLEMENT",
                    "SHARE_DELIVERY",
                    "SHARE_CASH_SETTLEMENT",
                }:
                    raise ChronologyError("corporate provider cannot supply trade executions")
                when = _moment_of(event, "date")
                if when <= since or when < previous or when > until:
                    raise ChronologyError("corporate events must be ordered within (since, until]")
                previous = when
            for notice in evidence.share_count_notices:
                when = _moment_of(notice, "date")
                if when <= since or when > until:
                    raise ChronologyError("share-count notices must fall within (since, until]")
            for record in (*evidence.events, *evidence.share_count_notices):
                # Late-available data must never be placed where a decision could already read it.
                if record.get("available_at") is not None and _moment_of(record, "available_at") > until:
                    raise ChronologyError("corporate provider returned a fact before it was available")
            for record in evidence.backdated:
                if _moment_of(record, "date") > since or not since < _moment_of(record, "available_at") <= until:
                    raise ChronologyError("a backdated fact must take effect by `since` and become available inside the interval")
            return evidence

        def check_notices(evidence: CorporateEvidence, positions: Mapping[str, int]) -> None:
            """A share-count notice about a code we hold must also arrive as a ledger event.

            Notices exist for codes this account does not hold, where a split changes nothing of
            ours but stales an order we have already queued. If one names a code we DO hold and no
            event came with it, the provider has contradicted itself: our share count would change
            and the ledger would never hear about it. That is refused rather than recorded.
            """
            dated = {(_moment_of(event, "date"), str(event.get("code"))) for event in evidence.events if event.get("action") == "SPLIT"}
            for notice in evidence.share_count_notices:
                code = str(notice.get("code"))
                if positions.get(code, 0) > 0 and (_moment_of(notice, "date"), code) not in dated:
                    raise ChronologyError("a share-count notice names a held code but no event changed the holding")

        def note_splits(records: Sequence[Mapping[str, Any]]) -> None:
            for record in records:
                if record.get("action") not in {"SPLIT", "SHARE_DELIVERY"}:
                    continue
                when, code = _moment_of(record, "date"), str(record.get("code"))
                # Only SPLIT has a duplicate public notice. Separate share deliveries,
                # even at one timestamp, are distinct causes the order policy must see.
                if record.get("action") == "SHARE_DELIVERY" or not any(
                    left == when and middle == code and prior.get("action") == "SPLIT" for left, middle, prior in applied_splits
                ):
                    applied_splits.append((when, code, record))

        def backdated_locator(evidence: CorporateEvidence, since: datetime, until: datetime) -> dict[str, Any]:
            first = evidence.backdated[0]
            return {
                "since": since.isoformat(),
                "until": until.isoformat(),
                "action": str(first.get("action")),
                "code": str(first.get("code")),
                "date": str(first.get("date")),
                "available_at": str(first.get("available_at")),
                "count": len(evidence.backdated),
            }

        def corporate_before(until: datetime) -> ExecutionAccountSnapshot | tuple[str, dict[str, Any]]:
            nonlocal cursor, events
            if until < cursor:
                raise ChronologyError("corporate interval would cross a consumed lifecycle")
            if until > cursor:
                evidence = ask(cursor, until, events)
                if not evidence.complete:
                    return "corporate_evidence_incomplete", {"since": cursor.isoformat(), "until": until.isoformat(), "evidence_id": evidence.evidence_id}
                if evidence.backdated:
                    return "corporate_fact_available_after_its_effective_boundary", backdated_locator(evidence, cursor, until)
                proposed = events + evidence.events
                current = book(until, proposed)
                check_notices(evidence, current.account.positions)
                note_splits((*evidence.events, *evidence.share_count_notices))
                events, cursor = proposed, until
                return current
            return book(until, events)

        def corporate_during(
            window: ExecutionWindow,
            since: datetime,
            lifecycle: tuple[Mapping[str, Any], ...],
            routed: tuple[RoutedOrder, ...],
        ) -> tuple[str, dict[str, Any]] | None:
            """Ask for `(submitted_at, as_of]`, which the lifecycle occupies, and place what can be placed.

            `events` still ends at `since` here and `lifecycle` is what the auction and its receipts
            recorded after it. The provider sees both, because an entitlement at 10:00 belongs to
            whoever held the code after the 09:00 fills; a provider must place each fact against
            the records dated before it, not against the whole prefix.

            A record is merged at its own timestamp when nothing about it depends on an order of
            events this runner does not know. Three things do, and each stops the run with a
            locator instead of being guessed:

            - a share-count change -- event or notice -- on a code with an order still live at that
              instant, because the order was sized, priced and partly filled on the old count;
            - any record on a code that also has a lifecycle record at exactly the same instant;
            - a `date_only` record on a code with any lifecycle record that session.

            A cash event on a code with a live order is placed normally: who held the code at that
            instant is fixed by the fill timestamps the lifecycle already recorded.
            """
            nonlocal cursor, events
            until = window.as_of
            evidence = ask(since, until, events + lifecycle)
            locator: dict[str, Any] = {"window_id": window.window_id, "since": since.isoformat(), "until": until.isoformat()}
            if not evidence.complete:
                events, cursor = events + lifecycle, until
                return "corporate_evidence_incomplete", {**locator, "evidence_id": evidence.evidence_id}
            if evidence.backdated:
                events, cursor = events + lifecycle, until
                return "corporate_fact_available_after_its_effective_boundary", {**locator, **backdated_locator(evidence, since, until)}
            ended_at = {item.order.order_id: ended[item.order.order_id].terminated_at for item in routed}
            stop: tuple[str, dict[str, Any]] | None = None
            placed: list[Mapping[str, Any]] = []
            for kind, records in (("event", evidence.events), ("notice", evidence.share_count_notices)):
                for record in records:
                    when, code, action = _moment_of(record, "date"), str(record.get("code")), str(record.get("action"))
                    basis = str(record.get("time_basis", "unstated"))
                    live = tuple(sorted(item.order.order_id for item in routed if item.order.code == code and ended_at[item.order.order_id] >= when))
                    same_code = [entry for entry in lifecycle if entry.get("code") == code]
                    if basis == "date_only" and same_code:
                        outcome = "unsupported_date_only_sequence"
                    elif any(_moment_of(entry, "date") == when for entry in same_code):
                        outcome = "unsupported_same_timestamp_sequence"
                    elif action in {"SPLIT", "SHARE_DELIVERY"} and live:
                        outcome = "unsupported_share_count_change_with_live_orders"
                    else:
                        outcome = INTRADAY_MERGED if kind == "event" else INTRADAY_NOTICE
                    corporate_outcomes.append(CorporateOutcome(window.window_id, since, until, kind, action, code, when, basis, outcome, live))
                    if outcome in INTRADAY_UNSUPPORTED:
                        if stop is None:
                            stop = (
                                outcome,
                                {
                                    **locator,
                                    "kind": kind,
                                    "action": action,
                                    "code": code,
                                    "date": when.isoformat(),
                                    "time_basis": basis,
                                    "live_order_ids": list(live),
                                },
                            )
                    elif kind == "event":
                        placed.append(record)
            if stop is not None:
                # What the auction did stands; nothing corporate from this interval is applied.
                events, cursor = events + lifecycle, until
                return stop
            ordered = sorted(
                [(_moment_of(entry, "date"), 0, index, entry) for index, entry in enumerate(lifecycle)]
                + [(_moment_of(entry, "date"), 1, index, entry) for index, entry in enumerate(placed)],
                key=lambda item: item[:3],
            )
            proposed = events + tuple(item[3] for item in ordered)
            check_notices(evidence, book(until, proposed).account.positions)
            note_splits((*evidence.events, *evidence.share_count_notices))
            events, cursor = proposed, until
            return None

        for frame_index, frame in enumerate(frames):
            day_routes = {(session.batch.exchange, session.batch.venue) for window in frame.windows for session in window.sessions}
            due = [item for item in pending if item.due_index == frame_index]
            if any((item.request.exchange, item.request.venue) not in day_routes for item in due):
                raise ChronologyError("missing_due_session")
            for window in frame.windows:
                route_map = {(session.batch.exchange, session.batch.venue): session for session in window.sessions}
                selected = [item for item in pending if item.due_index == frame_index and (item.request.exchange, item.request.venue) in route_map]
                if not selected:
                    continue
                submitted_at = window.sessions[0].batch.submitted_at
                current = corporate_before(submitted_at)
                if isinstance(current, tuple):
                    return finish(*current)
                conflicts = [
                    item
                    for item in selected
                    if any(code == item.request.intent.code and when > item.request.intent.decision_at for when, code, _event in applied_splits)
                ]
                if conflicts:
                    if pending_corporate_policy is None:
                        return finish("pending_conflicts_corporate_action")
                    stale_ids = {item.request.intent.order_id for item in conflicts}
                    causes = tuple(
                        event
                        for when, code, event in applied_splits
                        if any(code == item.request.intent.code and when > item.request.intent.decision_at for item in conflicts)
                    )
                    resolutions = pending_corporate_policy(tuple(conflicts), causes, current)
                    _sequence(resolutions)
                    resolved: dict[str, PendingResolution] = {}
                    for resolution in resolutions:
                        if not isinstance(resolution, PendingResolution):
                            raise ChronologyError("pending_corporate_policy must return PendingResolution")
                        if resolution.order_id not in stale_ids:
                            raise ChronologyError("policy resolved an order that was not in conflict")
                        if resolution.order_id in resolved:
                            raise ChronologyError("policy resolved one order twice")
                        resolved[resolution.order_id] = resolution
                    if set(resolved) != stale_ids:
                        raise ChronologyError("policy did not resolve every conflicting order")
                    kept: list[PendingRequest] = []
                    for item in selected:
                        answer = resolved.get(item.request.intent.order_id)
                        if answer is None:
                            kept.append(item)
                            continue
                        parent = item.request.intent
                        record_end(
                            OrderTermination(
                                order_id=parent.order_id,
                                code=parent.code,
                                side=parent.side,
                                status="WITHDRAWN" if answer.action == "cancel" else "AMENDED",
                                provenance="corporate",
                                reason=answer.reason,
                                requested_qty=parent.qty,
                                filled_qty=0,
                                terminated_at=submitted_at,
                                available_at=submitted_at,
                                signal=signal_of.get(parent.order_id),
                                parent_order_id=parent_of.get(parent.order_id),
                                replaced_by=answer.replacement_order_id,
                            )
                        )
                        if answer.action == "cancel":
                            continue
                        child_id = str(answer.replacement_order_id)
                        if child_id in order_ids:
                            raise ChronologyError("an amendment must use an unused order ID")
                        quantity = parent.qty if answer.new_qty is None else answer.new_qty
                        limit = parent.limit_price_cents if answer.new_limit_price_cents is None else answer.new_limit_price_cents
                        whole_lots = quantity % 1000 == 0 if item.request.venue == "regular_open" else 1 <= quantity <= 999
                        if not whole_lots:
                            raise ChronologyError("amended quantity is not valid for its venue")
                        # `OrderIntent` would also reject an off-grid price, but only as a generic
                        # price error from deep inside the auction. Checking here names the actual
                        # problem -- the policy handed us a price no board would accept -- which is
                        # what a reader of the failure needs.
                        try:
                            on_grid = round_stock_price(Decimal(limit) / 100, "down") == Decimal(limit) / 100
                        except PriceError as error:
                            raise ChronologyError("amended limit price is outside the supported domain") from error
                        if not on_grid:
                            raise ChronologyError("amended limit price is not on the price grid")
                        if parent.side == "SELL" and quantity > current.account.positions.get(parent.code, 0):
                            raise ChronologyError("amended quantity exceeds the post-action holding")
                        if parent.side == "BUY" and quantity * limit > parent.qty * parent.limit_price_cents:
                            # A corporate action is not a reason to commit more money than the
                            # decision chose to commit. The share count may legitimately change --
                            # that is the whole point of amending -- but the notional at the limit
                            # cannot grow, because no decision ever approved the larger number.
                            raise ChronologyError("amended entry commits more cash than the order it replaces")
                        child = PriorCloseRequest(
                            OrderIntent(child_id, parent.code, parent.side, quantity, limit, parent.decision_at),
                            item.request.exchange,
                            item.request.venue,
                            item.request.signal,
                            OrderLineage(parent.order_id, answer.reason, submitted_at),
                        )
                        order_ids.add(child_id)
                        signal_of[child_id] = item.request.signal
                        parent_of[child_id] = parent.order_id
                        amendments.append(AmendmentRecord(window.window_id, submitted_at, parent.order_id, child))
                        kept.append(PendingRequest(child, item.due_index))
                    # Every conflicting parent leaves the queue here, whether it was withdrawn or
                    # replaced; the replacement is routed in its place and was never queued.
                    pending = [item for item in pending if item.request.intent.order_id not in stale_ids]
                    selected = kept
                    if not selected:
                        continue
                routed = tuple(
                    RoutedOrder(
                        item.request.intent,
                        route_map[(item.request.exchange, item.request.venue)].batch,
                        route_map[(item.request.exchange, item.request.venue)].costs,
                    )
                    for item in selected
                )
                evidence = execution_provider(window, current, routed)
                if not isinstance(evidence, ExecutionEvidence):
                    raise ChronologyError("execution_provider must return ExecutionEvidence")
                selected_ids = {item.request.intent.order_id for item in selected}
                pending = [item for item in pending if item.request.intent.order_id not in selected_ids]
                if not evidence.complete or not evidence.exclusive:
                    windows.append(WindowRecord(window.window_id, evidence.evidence_id, routed, None, evidence))
                    return finish("execution_evidence_incomplete" if not evidence.complete else "nonexclusive_execution")
                for report in evidence.reports:
                    if report.report_id in report_ids:
                        raise ChronologyError("report IDs must be unique across the run")
                    report_ids.add(report.report_id)
                result = reconcile_cohort_lifecycle(
                    current.account,
                    routed,
                    evidence.quotes,
                    max_positions=max_positions,
                    expires_at=window.expires_at,
                    as_of=window.as_of,
                    reports=evidence.reports,
                )
                windows.append(WindowRecord(window.window_id, evidence.evidence_id, routed, result, evidence))
                if not result.continuation_allowed or result.next_state is None:
                    return finish("execution_unresolved")
                # Continuation is only allowed when nothing is left outstanding, so every routed
                # order ended here -- settled by the auction itself, or closed by a receipt.
                # The lifecycle's own validated prefix, never `evidence.reports`: a report dated
                # after the cutoff is dropped by `_visible_prefix` without blocking continuation and
                # is therefore checked against nothing -- not against the pending set, not for
                # cumulative consistency. Reading it here would let an unchecked receipt invent a
                # residual that a replacement could then claim.
                receipts = {report.order_id: report for report in result.visible_reports if isinstance(report, TerminalReport)}
                outcome_of = {outcome.order_id: outcome for outcome in result.initial_result.outcomes}
                for routed_order in routed:
                    order = routed_order.order
                    outcome = outcome_of[order.order_id]
                    receipt = receipts.get(order.order_id)
                    if receipt is not None:
                        # `reason` stays the auction's, because `TerminalReport` carries no reason
                        # field: the honest answer to "why did this end" is the last thing actually
                        # observed about it (`limit_not_reached`, `residual_pending`), not a motive
                        # invented for the broker.
                        status, provenance = receipt.status, "report"
                        filled, moment, knowable = receipt.cumulative_filled_qty, receipt.event_at, receipt.available_at
                        report_id: str | None = receipt.report_id
                    else:
                        # `filled` and `rejected` are self-explanatory; an `unfilled` order that
                        # needed no receipt is one the board refused outright, which its own reason
                        # names (`order_limit_outside_bounds`).
                        status = "FILLED" if outcome.disposition == "filled" else "REJECTED"
                        provenance, filled = "auction", outcome.filled_qty
                        moment, knowable, report_id = routed_order.batch.auction_at, window.as_of, None
                    record_end(
                        OrderTermination(
                            order_id=order.order_id,
                            code=order.code,
                            side=order.side,
                            status=status,
                            provenance=provenance,
                            reason=outcome.reason,
                            requested_qty=order.qty,
                            filled_qty=filled,
                            terminated_at=moment,
                            available_at=knowable,
                            signal=signal_of.get(order.order_id),
                            parent_order_id=parent_of.get(order.order_id),
                            report_id=report_id,
                        )
                    )
                lifecycle = _events(result.initial_result.ledger_events) + _events(result.additional_events)
                replayed = book(window.as_of, events + lifecycle)
                if (
                    replayed.account.cash_cents != result.next_state.cash_cents
                    or replayed.account.positions != result.next_state.positions
                    or replayed.account.reserved_position_codes != result.next_state.reserved_position_codes
                ):
                    raise ChronologyError("lifecycle does not reconcile with recorded prefix")
                stopped = corporate_during(window, submitted_at, lifecycle, routed)
                if stopped is not None:
                    return finish(*stopped)
            current = corporate_before(frame.decision_at)
            if isinstance(current, tuple):
                return finish(*current)
            if (set(current.account.positions) | current.account.reserved_position_codes) - set(frame.prices):
                return finish("missing_close_marks")
            snapshot = build_decision_snapshot(
                initial_cash_cents=initial_cash_cents,
                history_start=history_start,
                as_of=frame.decision_at,
                events=events,
                session_closes=[item.close_at for item in frames[: frame_index + 1]],
                calendar_id=calendar_id,
                prices=frame.prices,
                execution_complete=True,
                execution_checkpoint_id=label(),
                cash_basis="trade_date_cash",
                unresolved_order_ids=(),
                max_positions=max_positions,
            )
            snapshots.append(snapshot)
            generated = rule(DecisionContext(snapshot, tuple(pending), tuple(terminations)))
            _sequence(generated)
            for action in generated:
                if not isinstance(action, (PriorCloseRequest, CancelRequest)):
                    raise ChronologyError("decision rule must return PriorCloseRequest or CancelRequest")
            # Withdrawals are applied first, so a replacement issued by the same decision may name
            # the order it replaces. Nothing was ever submitted, so there is no receipt to quote.
            for action in generated:
                if not isinstance(action, CancelRequest):
                    continue
                if action.decided_at != frame.decision_at:
                    raise ChronologyError("withdrawal must carry the current decision timestamp")
                queued = [item for item in pending if item.request.intent.order_id == action.order_id]
                if not queued:
                    raise ChronologyError("withdrawal target is not pending")
                withdrawn = queued[0].request.intent
                pending = [item for item in pending if item.request.intent.order_id != action.order_id]
                record_end(
                    OrderTermination(
                        order_id=withdrawn.order_id,
                        code=withdrawn.code,
                        side=withdrawn.side,
                        status="WITHDRAWN",
                        provenance="decision",
                        reason=action.reason,
                        requested_qty=withdrawn.qty,
                        filled_qty=0,
                        terminated_at=frame.decision_at,
                        available_at=frame.decision_at,
                        signal=signal_of.get(withdrawn.order_id),
                        parent_order_id=parent_of.get(withdrawn.order_id),
                    )
                )
            requests = tuple(action for action in generated if isinstance(action, PriorCloseRequest))
            omitted: list[str] = []
            for request in requests:
                identity = request.intent.order_id
                if request.intent.decision_at != frame.decision_at or identity in order_ids:
                    raise ChronologyError("intent needs current decision timestamp and unique run order ID")
                if request.lineage is not None:
                    lineage = request.lineage
                    if any(item.request.intent.order_id == lineage.parent_order_id for item in pending):
                        raise ChronologyError("parent order has not terminated, so its reservation is still held")
                    origin = ended.get(lineage.parent_order_id)
                    if origin is None:
                        # An omitted order lands here too, whatever ID its would-be child carries:
                        # it was never queued, so it never ended, so a chain whose root was omitted
                        # cannot be revived by renaming a child.
                        detail = " (it was omitted in this arm and never queued)" if lineage.parent_order_id in never_queued else ""
                        raise ChronologyError(f"parent order is unknown{detail}")
                    if (origin.code, origin.side) != (request.intent.code, request.intent.side):
                        raise ChronologyError("child must keep its parent's code and side")
                    if origin.replaced_by is not None:
                        raise ChronologyError("parent order has already been replaced")
                    if request.intent.qty > origin.residual_qty:
                        raise ChronologyError("child quantity exceeds the parent residual")
                    if request.signal != origin.signal:
                        raise ChronologyError("child must carry its parent's signal identity, not a newly minted one")
                    if not origin.available_at <= lineage.known_at <= frame.decision_at:
                        raise ChronologyError("a replacement cannot be justified before its parent ended or after it was decided")
                    parent_of[identity] = lineage.parent_order_id
                order_ids.add(identity)
                signal_of[identity] = request.signal
                if scenario.signal_omission is not None and request.signal is None:
                    raise ChronologyError("signal omission requires metadata on every generated request")
                sampled = False
                if request.signal is not None:
                    signal = request.signal
                    previous_signal = signals.get(signal.signal_id)
                    if previous_signal is None:
                        if signal.origin_at != frame.decision_at:
                            raise ChronologyError("a new signal must originate at its first generated decision")
                        signals[signal.signal_id] = signal
                        if scenario.signal_omission is not None:
                            signal_draws[signal.signal_id] = scenario.signal_omission.draw(signal)
                    elif previous_signal != signal:
                        raise ChronologyError("a reused signal ID changed its identity")
                    if scenario.signal_omission is not None:
                        sampled = signal_draws[signal.signal_id].omitted
                        if sampled:
                            sampled_omission_ids.add(identity)
                if identity in scenario.omitted_order_ids or sampled:
                    omitted.append(identity)
                    never_queued.add(identity)
                else:
                    if request.lineage is not None:
                        # Consume the residual only once the replacement is really queued. Bounding
                        # each child against `residual_qty` alone is not enough -- nothing stopped
                        # two children, at one decision or across many, from each claiming the same
                        # 2,000 shares, so 3,000 shares of advice could buy 5,000. But an omitted
                        # child is an order that never existed, and recording the parent as
                        # "replaced by" it would be both a false record and a residual quietly lost
                        # to an arm that never traded.
                        claim_replacement(request.lineage.parent_order_id, identity)
                    pending.append(PendingRequest(request, frame_index + 1 + scenario.extra_delay))
            decisions.append(DecisionRecord(frame.decision_at, requests, tuple(omitted)))
        return finish("outstanding_requests" if pending else None)
    except (ValueError, TypeError) as error:
        if isinstance(error, ChronologyError):
            raise
        raise ChronologyError(str(error)) from error
