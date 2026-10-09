"""Baseline-ranked complete-attempt suppression with full chronological reruns.

This fixed diagnostic policy is not an approved research gate or a sampling rule.
All run inputs, callbacks and stable request identities need prospective audit.

Request identity across arms
----------------------------

An order ID means the same piece of advice in every arm that uses it. What "the same" covers is
split in two, and the split is the contract:

- **Identity** (`IDENTITY_FIELDS`): code, side, decision time, exchange, venue, the originating
  signal, and -- for a replacement -- the parent it replaces and why. Two arms that give one ID
  different values here are describing different advice under one name, and are refused.
- **State-dependent** (`STATE_DEPENDENT_FIELDS`): quantity, limit price, and when a replacement's
  parent ending became known. These legitimately differ between arms, because they are computed
  from the arm's own cash, holdings and receipts. Freezing them would reject an honest rerun.

Arms are checked against the frozen baseline while they run, and against each other only after
all of them have run (`check_cross_run_identities`), so the outcome -- including which error is
reported -- does not depend on the order the arms were run in.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from fractions import Fraction
from types import MappingProxyType
from typing import Any

from research_core.chronology import (
    ActionRule,
    ChronologyError,
    ChronologyResult,
    CorporateProvider,
    DayFrame,
    DecisionContext,
    ExecutionProvider,
    PendingCorporatePolicy,
    PendingRequest,
    PriorCloseRequest,
    Scenario,
    run_chronology,
)
from research_core.ledger import replay_ledger
from research_core.order_actions import CancelRequest, PendingResolution
from research_core.signals import SignalIdentity

IDENTITY_FIELDS = ("code", "side", "decision_at", "exchange", "venue", "signal", "parent_order_id", "lineage_reason")
STATE_DEPENDENT_FIELDS = ("qty", "limit_price_cents", "lineage_known_at")

RANKING_BASIS = "closed_economic_net_pnl_cents_desc_then_entry_event_index"
RANKING_NOTE = (
    "synthetic diagnostic: economic net PnL of each closed attempt, INCLUDING dividend and capital-return receivables "
    "recorded but not yet paid by the end of the baseline; not captured cash and not an approved gate"
)


def request_identity(request: PriorCloseRequest) -> tuple[Any, ...]:
    """The fields named in `IDENTITY_FIELDS`, in that order."""
    intent, lineage = request.intent, request.lineage
    return (
        intent.code,
        intent.side,
        intent.decision_at,
        request.exchange,
        request.venue,
        request.signal,
        None if lineage is None else lineage.parent_order_id,
        None if lineage is None else lineage.reason,
    )


def amendment_identity(item: PendingRequest, resolution: PendingResolution) -> tuple[Any, ...]:
    """The identity `run_chronology` will give the replacement `resolution` creates for `item`.

    It mirrors how the runner builds the child: the parent's code, side, decision time, route and
    signal, with the parent's ID and the resolution's reason as its lineage.
    """
    request = item.request
    intent = request.intent
    return (intent.code, intent.side, intent.decision_at, request.exchange, request.venue, request.signal, resolution.order_id, resolution.reason)


def run_identities(result: ChronologyResult) -> dict[str, tuple[Any, ...]]:
    """Every request ID a run created -- decisions and policy amendments -- with its identity."""
    return {request.intent.order_id: request_identity(request) for request in result.requests()}


def check_cross_run_identities(baseline: ChronologyResult, arms: Sequence[ChronologyResult]) -> None:
    """Refuse any request or signal ID that means different things in different runs.

    Deterministic whatever order `arms` is in: every conflict is collected first and the first one
    in sorted ID order is reported.
    """
    requests: dict[str, set[tuple[Any, ...]]] = {}
    signals: dict[str, set[SignalIdentity]] = {}
    for result in (baseline, *arms):
        for identity, value in run_identities(result).items():
            requests.setdefault(identity, set()).add(value)
        for signal in result.signals:
            signals.setdefault(signal.signal_id, set()).add(signal)
    request_conflicts = sorted(identity for identity, values in requests.items() if len(values) > 1)
    if request_conflicts:
        raise ChronologyError(f"cross-run request ID changed its decision identity: {request_conflicts[0]}")
    signal_conflicts = sorted(identity for identity, values in signals.items() if len(values) > 1)
    if signal_conflicts:
        raise ChronologyError(f"cross-run signal ID changed its identity: {signal_conflicts[0]}")


@dataclass(frozen=True)
class StressInputs:
    initial_cash_cents: int
    max_positions: int
    history_start: datetime
    initial_checkpoint_id: str
    frames: tuple[DayFrame, ...]
    calendar_id: str
    calendar_complete: bool
    # A factory of either rule shape: a `DecisionRule` factory is also a valid `ActionRule` factory.
    decision_factory: Callable[[], ActionRule]
    execution_factory: Callable[[], ExecutionProvider]
    corporate_factory: Callable[[], CorporateProvider]
    # Called once per arm, like the other factories, so a stateful policy cannot leak across arms.
    pending_corporate_policy_factory: Callable[[], PendingCorporatePolicy] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.frames, tuple):
            raise ChronologyError("stress frames must be a fixed tuple")
        if not all(callable(factory) for factory in (self.decision_factory, self.execution_factory, self.corporate_factory)):
            raise ChronologyError("stress requires callable factories")
        if self.pending_corporate_policy_factory is not None and not callable(self.pending_corporate_policy_factory):
            raise ChronologyError("pending_corporate_policy_factory must be callable when supplied")

    def run(self, scenario: Scenario) -> ChronologyResult:
        """Create fresh providers for each arm; factories remain trusted code."""
        policy = None if self.pending_corporate_policy_factory is None else self.pending_corporate_policy_factory()
        return run_chronology(
            initial_cash_cents=self.initial_cash_cents,
            max_positions=self.max_positions,
            history_start=self.history_start,
            initial_checkpoint_id=self.initial_checkpoint_id,
            frames=self.frames,
            calendar_id=self.calendar_id,
            calendar_complete=self.calendar_complete,
            scenario=scenario,
            decision_factory=self.decision_factory,
            execution_provider=self.execution_factory(),
            corporate_provider=self.corporate_factory(),
            pending_corporate_policy=policy,
        )

    def for_rerun(self, baseline: ChronologyResult) -> StressInputs:
        """Check each arm's requests and amendments against the baseline's identities as it runs.

        Only IDs the baseline actually produced are checked here, against a frozen copy, so arm
        order cannot matter. An ID new to an arm is checked against other arms afterwards by
        `check_cross_run_identities`, which every runner in this package calls once its arms are
        done. **A caller that drives `for_rerun` itself must call it too**: without that pass, two
        arms can each mint the same new ID meaning different things and nothing will say so.
        """
        identities: Mapping[str, tuple[Any, ...]] = MappingProxyType(run_identities(baseline))
        signals: Mapping[str, SignalIdentity] = MappingProxyType({signal.signal_id: signal for signal in baseline.signals})
        rule_factory = self.decision_factory
        policy_factory = self.pending_corporate_policy_factory

        def check(order_id: str, value: tuple[Any, ...]) -> None:
            known = identities.get(order_id)
            if known is not None and known != value:
                raise ChronologyError("cross-run request ID changed its decision identity")

        def checked_factory() -> ActionRule:
            rule = rule_factory()

            def checked(context: DecisionContext) -> tuple[PriorCloseRequest | CancelRequest, ...]:
                actions = tuple(rule(context))
                for action in actions:
                    if isinstance(action, CancelRequest):
                        # A withdrawal names an order that already passed this check when it was
                        # created; it has no identity of its own to reuse.
                        continue
                    if not isinstance(action, PriorCloseRequest):
                        raise ChronologyError("decision rule must return PriorCloseRequest or CancelRequest")
                    check(action.intent.order_id, request_identity(action))
                    if action.signal is not None:
                        previous = signals.get(action.signal.signal_id)
                        if previous is not None and previous != action.signal:
                            raise ChronologyError("cross-run signal ID changed its identity")
                return actions

            return checked

        checked_policy_factory: Callable[[], PendingCorporatePolicy] | None = None
        if policy_factory is not None:
            make_policy = policy_factory

            def checked_policy() -> PendingCorporatePolicy:
                policy = make_policy()

                def checked(
                    conflicts: tuple[PendingRequest, ...],
                    causes: tuple[Mapping[str, Any], ...],
                    snapshot: Any,
                ) -> Sequence[PendingResolution]:
                    answers = tuple(policy(conflicts, causes, snapshot))
                    by_id = {item.request.intent.order_id: item for item in conflicts}
                    for answer in answers:
                        # Malformed answers are the runner's to refuse, with its own message.
                        if isinstance(answer, PendingResolution) and answer.action == "amend" and answer.order_id in by_id:
                            check(str(answer.replacement_order_id), amendment_identity(by_id[answer.order_id], answer))
                    return answers

                return checked

            checked_policy_factory = checked_policy

        return replace(self, decision_factory=checked_factory, pending_corporate_policy_factory=checked_policy_factory)


@dataclass(frozen=True)
class AttemptTarget:
    attempt_id: int
    code: str
    entry_order_id: str
    # BUY orders that actually filled inside this attempt, as the ledger assigned them.
    buy_order_ids: frozenset[str]
    net_pnl_cents: int
    unpaid_receivable_cents: int
    # The decision requests those fills descend from, and every order in those chains (the roots,
    # their retries and their corporate amendments), whether or not each one filled.
    root_order_ids: frozenset[str] = frozenset()
    chain_order_ids: frozenset[str] = frozenset()
    # Other attempts that share a chain root with this one, e.g. a residual retry that filled after
    # this attempt had already gone flat. Suppressing this attempt removes those too.
    shared_root_attempt_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ChainSuppression:
    """What suppressing one target's chains actually did in one arm.

    The three "not" outcomes are different facts and are never merged:

    - `roots_not_regenerated` -- a later root this arm's rule never produced, because the account
      it saw was different. Nothing was omitted, and nothing needed to be.
    - `descendants_not_regenerated` -- a baseline retry or amendment that could not exist, because
      its root was never queued. Expected, and not an omission anyone asked for by ID.
    - `required_roots_unapplied` -- a required root that was not omitted. The run is then
      `incomplete` (`unapplied_omission_targets`); it is listed here so the report says which.
    """

    attempt_id: int
    root_order_ids: tuple[str, ...]
    required_root_ids: tuple[str, ...]
    applied_root_ids: tuple[str, ...]
    roots_not_regenerated: tuple[str, ...]
    descendants_not_regenerated: tuple[str, ...]
    required_roots_unapplied: tuple[str, ...]


@dataclass(frozen=True)
class StressArm:
    count: int
    targets: tuple[AttemptTarget, ...]
    result: ChronologyResult | None
    unavailable_reason: str | None
    suppression: tuple[ChainSuppression, ...] = ()
    # Which attempts the arm set out to remove, and which ones its omission set actually reaches.
    # They differ only when chains are shared, and then the arm is not run at all.
    selected_attempt_ids: tuple[int, ...] = ()
    directly_suppressed_attempt_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class BestAttemptStress:
    baseline: ChronologyResult
    ranked_closed_attempts: tuple[AttemptTarget, ...]
    open_attempt_ids: tuple[int, ...]
    arms: tuple[StressArm, ...]
    ranking_basis: str = RANKING_BASIS
    ranking_note: str = RANKING_NOTE


def _cents(value: Any) -> int:
    if isinstance(value, bool):
        raise ChronologyError("stress monetary evidence must be exact cents")
    amount = Fraction(str(value)) * 100
    if amount.denominator != 1:
        raise ChronologyError("stress monetary evidence must be exact cents")
    return amount.numerator


def _parents(result: ChronologyResult) -> dict[str, str]:
    """Every child-to-parent link the run recorded, from lineage, amendments and terminations."""
    parents: dict[str, str] = {}
    for request in result.requests():
        if request.lineage is not None:
            parents[request.intent.order_id] = request.lineage.parent_order_id
    for record in result.terminations:
        if record.parent_order_id is not None:
            parents[record.order_id] = record.parent_order_id
    return parents


def chain_roots(result: ChronologyResult) -> dict[str, str]:
    """Map every order the run created to the decision request its chain started from.

    Every order is either rule output or a corporate amendment, and an amendment always has a
    parent, so following parents always ends at a decision request. That is asserted, not assumed:
    a chain ending anywhere else means the run's records are inconsistent.
    """
    parents = _parents(result)
    decided = {request.intent.order_id for record in result.decisions for request in record.requests}
    roots: dict[str, str] = {}
    for order_id in {request.intent.order_id for request in result.requests()} | {record.order_id for record in result.terminations}:
        cursor, seen = order_id, set()
        while cursor in parents:
            if cursor in seen:
                raise ChronologyError("order lineage contains a cycle")
            seen.add(cursor)
            cursor = parents[cursor]
        if cursor not in decided:
            raise ChronologyError("an order chain does not start at a decision request")
        roots[order_id] = cursor
    return roots


def _inventory(baseline: ChronologyResult, inputs: StressInputs) -> tuple[tuple[AttemptTarget, ...], tuple[int, ...], Mapping[int, frozenset[str]]]:
    ledger = replay_ledger(inputs.initial_cash_cents / 100, baseline.events, max_positions=inputs.max_positions)
    all_attempts = ledger["attempts"] + ledger["open_attempts"]
    pnl = {item["id"]: 0 for item in all_attempts}
    unpaid = dict.fromkeys(pnl, 0)
    buys: dict[int, set[str]] = {identity: set() for identity in pnl}
    request_attempt: dict[str, int] = {}
    for event, row in zip(baseline.events, ledger["cash_rows"], strict=True):
        identity = row["attempt_id"]
        pnl[identity] += _cents(event["total"])
        if event["action"] == "DIVIDEND" and not event.get("entitlement_id"):
            raise ChronologyError("stress ranking requires linked dividend evidence")
        if event["action"] == "BUY":
            order_id = event.get("order_id")
            if not isinstance(order_id, str) or not order_id:
                raise ChronologyError("every BUY fill needs its original order ID")
            previous = request_attempt.setdefault(order_id, identity)
            if previous != identity:
                raise ChronologyError("a BUY order ID cannot span multiple attempts")
            buys[identity].add(order_id)
    for entitlement in (*ledger["dividend_entitlements"], *ledger["capital_return_entitlements"]):
        if not entitlement["paid"]:
            amount = _cents(entitlement["amount"])
            unpaid[entitlement["attempt_id"]] += amount
            pnl[entitlement["attempt_id"]] += amount
    roots_of = chain_roots(baseline)
    members: dict[str, set[str]] = {}
    for order_id, root in roots_of.items():
        members.setdefault(root, set()).add(order_id)
    attempt_roots = {identity: frozenset(roots_of[order_id] for order_id in orders) for identity, orders in buys.items()}
    ranked = []
    for attempt in ledger["attempts"]:
        identity = attempt["id"]
        if abs(Fraction(str(attempt["net_pnl"])) * 100 - pnl[identity]) > Fraction(1, 1_000_000):
            raise ChronologyError("exact-cent stress contribution disagrees with shared ledger")
        entry = baseline.events[identity]
        # The ledger numbers an attempt by the index of the event that opened it.
        if entry["action"] != "BUY":
            raise ChronologyError("an attempt must open with a BUY fill")
        roots = attempt_roots[identity]
        ranked.append(
            AttemptTarget(
                identity,
                attempt["code"],
                entry["order_id"],
                frozenset(buys[identity]),
                pnl[identity],
                unpaid[identity],
                roots,
                frozenset(order_id for root in roots for order_id in members[root]),
                tuple(sorted(other for other, others in attempt_roots.items() if other != identity and others & roots)),
            )
        )
    # Every attempt's chains, open ones included: an open attempt cannot be selected, so if a
    # chain reaches it the arm is not isolating one attempt either.
    chains_by_attempt = {identity: frozenset(order_id for root in roots for order_id in members[root]) for identity, roots in attempt_roots.items()}
    return (
        tuple(sorted(ranked, key=lambda item: (-item.net_pnl_cents, item.attempt_id))),
        tuple(item["id"] for item in ledger["open_attempts"]),
        chains_by_attempt,
    )


def required_roots(baseline: ChronologyResult, roots: frozenset[str]) -> frozenset[str]:
    """Every target root the first affected decision advised -- not just the first of them.

    Omission is applied where a request is created, so the rule at that decision has still seen an
    account identical to the baseline's: every request it emits there is deterministic, and all of
    them must therefore actually be omitted. Roots advised at *later* decisions may legitimately
    never be advised again, because by then the account has diverged.

    Requiring only the chronologically first root would let a rule that silently stopped advising
    its sibling at that same instant report a complete, narrower suppression.
    """
    for record in baseline.decisions:
        named = frozenset(request.intent.order_id for request in record.requests if request.intent.order_id in roots)
        if named:
            return named
    raise ChronologyError("a ranked attempt has no decision request at the root of its chains")


def _suppression(targets: Sequence[AttemptTarget], required: frozenset[str], result: ChronologyResult) -> tuple[ChainSuppression, ...]:
    created = {request.intent.order_id for request in result.requests()}
    filled = {str(event.get("order_id")) for event in result.events if event.get("order_id")}
    revived = sorted((created - result.matched_omission_ids) & {order_id for target in targets for order_id in target.chain_order_ids})
    queued_or_filled = revived + sorted(filled & {order_id for target in targets for order_id in target.chain_order_ids})
    if queued_or_filled:
        # Unreachable through `run_chronology`, which refuses a child of a never-queued order.
        raise ChronologyError(f"a suppressed chain was revived: {queued_or_filled[0]}")
    rows = []
    for target in targets:
        roots = tuple(sorted(target.root_order_ids))
        descendants = tuple(sorted(target.chain_order_ids - target.root_order_ids))
        rows.append(
            ChainSuppression(
                attempt_id=target.attempt_id,
                root_order_ids=roots,
                required_root_ids=tuple(root for root in roots if root in required),
                applied_root_ids=tuple(root for root in roots if root in result.matched_omission_ids),
                roots_not_regenerated=tuple(root for root in roots if root not in result.matched_omission_ids and root not in required),
                descendants_not_regenerated=tuple(order_id for order_id in descendants if order_id not in created),
                required_roots_unapplied=tuple(root for root in roots if root in required and root not in result.matched_omission_ids),
            )
        )
    return tuple(rows)


def directly_suppressed(omitted: frozenset[str], chains_by_attempt: Mapping[int, frozenset[str]]) -> tuple[int, ...]:
    """Baseline attempts whose own filled chains this omission set removes.

    This is the suppression rule reaching an attempt, which is a different thing from an attempt
    that simply does not happen in the rerun. An arm may legitimately change everything after the
    first omitted decision -- different cash, different ranks, different trades -- and none of that
    is this. Only an attempt whose own orders are in the omitted set is counted here.
    """
    return tuple(sorted(identity for identity, chain in chains_by_attempt.items() if chain & omitted))


def run_best_attempt_stresses(inputs: StressInputs, *, counts: tuple[int, ...]) -> BestAttemptStress:
    """Run one baseline and each explicit count, without opening stored results.

    Each target is suppressed at the root of every order chain it filled from: the decision
    requests, plus -- by ID, as a second guard -- every retry and corporate amendment the baseline
    derived from them. Suppressing the root is what makes the suppression hold when a child's ID
    changes between arms: a root that was never queued never ends, so nothing can replace it.

    **An arm that cannot remove exactly the attempts it selected is not run.** Two flat-to-flat
    attempts can descend from one root -- a partial entry sold out, then the residual retried into a
    second attempt -- and suppressing that root removes both. Reporting that as "the best one
    removed" would be false: half the effect belongs to an attempt nobody selected. Such an arm
    comes back `unavailable` with `nonisolatable_shared_root` and both ID sets, never `complete`.
    Dropping back to omitting the filled child IDs is not the answer either -- a rerun that renames
    the child revives the attempt, which is the failure the root rule exists to prevent.

    The chronologically first target root must actually be omitted, because until that decision
    the rerun is the baseline. Later roots may legitimately not be regenerated, since the account
    the rule sees has changed. Other entries in the same stock remain eligible. No final PnL is
    subtracted and no SELL is copied from baseline.
    """
    if not isinstance(inputs, StressInputs) or not isinstance(counts, tuple) or not counts:
        raise ChronologyError("stress inputs and nonempty explicit counts tuple required")
    if any(isinstance(count, bool) or not isinstance(count, int) or count < 1 for count in counts) or len(set(counts)) != len(counts):
        raise ChronologyError("stress counts must be distinct positive integers")
    baseline = inputs.run(Scenario("best-attempt-baseline", frozenset(), 0))
    if baseline.status != "complete":
        return BestAttemptStress(baseline, (), (), tuple(StressArm(count, (), None, "baseline_incomplete") for count in counts))
    ranked, open_ids, chains_by_attempt = _inventory(baseline, inputs)

    rerun_inputs = inputs.for_rerun(baseline)
    arms = []
    for count in counts:
        if len(ranked) < count:
            arms.append(StressArm(count, (), None, "insufficient_closed_attempts"))
            continue
        targets = ranked[:count]
        selected = tuple(sorted(target.attempt_id for target in targets))
        roots = frozenset(root for target in targets for root in target.root_order_ids)
        omitted = frozenset(order_id for target in targets for order_id in target.chain_order_ids)
        reached = directly_suppressed(omitted, chains_by_attempt)
        if set(reached) - set(selected):
            arms.append(
                StressArm(
                    count,
                    targets,
                    None,
                    "nonisolatable_shared_root",
                    (),
                    selected,
                    reached,
                )
            )
            continue
        required = required_roots(baseline, roots)
        result = rerun_inputs.run(Scenario(f"suppress-best-{count}", omitted, 0, required))
        arms.append(StressArm(count, targets, result, result.stop_reason, _suppression(targets, required, result), selected, reached))
    check_cross_run_identities(baseline, [arm.result for arm in arms if arm.result is not None])
    return BestAttemptStress(baseline, ranked, open_ids, tuple(arms))


__all__ = [
    "IDENTITY_FIELDS",
    "RANKING_BASIS",
    "RANKING_NOTE",
    "STATE_DEPENDENT_FIELDS",
    "AttemptTarget",
    "BestAttemptStress",
    "required_roots",
    "ChainSuppression",
    "StressArm",
    "StressInputs",
    "amendment_identity",
    "chain_roots",
    "check_cross_run_identities",
    "directly_suppressed",
    "request_identity",
    "run_best_attempt_stresses",
    "run_identities",
]
