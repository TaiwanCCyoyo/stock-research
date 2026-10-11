"""The selected non-hit measurement, computed by the shared layer rather than beside it.

The 2026-09-13 prototype carried its own `Attempt` state machine: it re-paired buys with sells,
re-attributed dividends, re-summed costs, and then windowed. Codex's 002 review found the failure
that shape makes almost inevitable -- the non-hits were selected first and only then cut into
20-attempt windows, so `10 non-hit + hit + 10 non-hit` spliced into a run of twenty that never
happened. A second model of the same account will drift from the first, and the drift looks like a
result.

So nothing here re-derives an attempt. `research_core.ledger.replay_ledger` owns the flat-to-flat
inventory, `research_core.attribution_inputs.build_attribution_inputs` turns a recorded prefix into
valuation checkpoints, and `research_core.attribution.non_hit_attribution` does the windowing. This
module supplies only the two things the shared layer deliberately refuses to decide:

1. **the classification** -- which closed attempts are captured hits under the selected provisional
   policy, which are non-hits, and which are unresolved; and
2. **the recorded-prefix framing** -- which events are visible at a stated endpoint, which session
   closes the valuation path is required to contain, and what the marks are at each checkpoint.

The captured-return decomposition is checked against the ledger rather than trusted. Per the
development-measurement policy:

    G = sum(buy_quantity * modeled_execution_price)      excluding commissions and taxes
    S = gross sale consideration
    D = attributed cash distributions actually paid by the endpoint
    C = all charged fees, taxes and other separately charged trading costs
    captured net return = (S + D - G - C) / G,  with G > 0 required

and the shared ledger's own `net_cash_flow` for a closed attempt is `buy_total + sell_total +
dividend_total`, which is `S + D - G - C` written differently. `_reconcile` asserts that identity
per attempt, so a decomposition error cannot pass silently as a plausible captured return.

Three defects Codex's 003 review found, and what changed:

- **Evidence gaps were not bounded by the endpoint**, so a gap discovered later corrupted an
  earlier report. `measure` now slices gaps by the same endpoint as the events, and counts what it
  set aside.
- **Attempt closure was "any SELL"**, which ended an attempt at its first partial exit. Closure now
  comes from the running share count inside the attempt's own ledger-assigned events, so a partial
  sale does not close anything -- and a gap that refers to a known entitlement is attributed by the
  ledger itself rather than by any interval rule of ours.
- **A missing session close still reported a complete account path.** A valuation calendar is now
  supplied explicitly, its required closes are checked as a set against the checkpoints actually
  built, and a shortfall downgrades the path to a labelled diagnostic instead of `ok`. The number of
  closes a caller happened to pass is not evidence of completeness, and neither is a caller's own
  `complete=True`.

One more, found by the 006 batch rather than a review:

- **A held code with no mark crashed the whole measurement**, because the shared ledger refuses to
  value a holding without one -- correctly. `measure` now finds those checkpoints first and reports
  the path as `incomplete_missing_marks`, naming each checkpoint and code, with the cash-only
  decomposition still reported and the marked series withheld. A mark policy that has no evidence
  now says so by leaving the code out, instead of being forced to invent a price to avoid the crash.

Slippage is not subtracted: the contract states it is already inside the modelled execution price.
The 50% threshold is the selected provisional definition for this diagnostic, not owner approval,
and no other threshold is searched here.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from research_core.attribution import non_hit_attribution
from research_core.attribution_inputs import build_attribution_inputs
from research_core.ledger import max_drawdown, replay_ledger

# Fixed initial capital for the development report, not current equity: an account that has grown
# must not be allowed to make an absolute loss look smaller. The owner's production account is
# NT$2,000,000; a smaller synthetic fixture does not change that requirement, so this denominator
# is reported alongside -- never instead of -- the TWD amounts.
PRIMARY_DENOMINATOR_TWD = 2_000_000.0
PROVISIONAL_HIT_THRESHOLD = 0.50
NON_HIT_WINDOW = 20

# Absolute TWD tolerance for reconciling a decomposition against the ledger's own totals. Prices
# and costs here are exact cents, so anything larger than binary-float noise is a real error.
RECONCILE_TOLERANCE_TWD = 1e-6

CLOSED_DISPOSITIONS = ("hit", "non_hit", "unresolved_missing_evidence", "unresolved_no_gross_purchase")


class MeasurementError(ValueError):
    """The recorded evidence cannot be measured as the contract requires."""


@dataclass(frozen=True)
class EvidenceGap:
    """A material cash or entitlement fact that is known to be missing, named at its moment.

    This exists because the shared ledger correctly REFUSES to represent some of them: a
    `DIVIDEND_ENTITLEMENT` must carry a positive amount, so "the stock went ex-dividend and we do
    not know the amount" cannot be written as an event at all. Recording the gap here marks the
    affected attempt unresolved; it never invents a number, and it never lets the attempt be
    counted as a small loss.

    `entitlement_id` is the unambiguous form and should be preferred whenever the gap concerns a
    recorded entitlement: the ledger already knows which attempt owns that entitlement, including
    after the attempt closed and the same code was re-entered. Without it the gap is placed by the
    attempt's own open interval, which cannot resolve a close-and-re-enter at one timestamp -- and
    that case is refused rather than guessed. That interval ends where the attempt goes flat, so an
    unscoped gap dated after the exit -- the window a dividend is usually paid in -- matches no span
    and is refused too. It is the same refusal for the same reason, and `entitlement_id` is the
    answer to both.
    """

    code: str
    at: str
    reason: str
    entitlement_id: str | None = None

    def __post_init__(self) -> None:
        if not self.code or not self.reason:
            raise MeasurementError("an evidence gap must name a code and a reason")
        _aware(self.at, "evidence gap timestamp")
        if self.entitlement_id is not None and not self.entitlement_id:
            raise MeasurementError("entitlement_id, when supplied, must be nonempty")

    def describe(self) -> str:
        scope = f" entitlement={self.entitlement_id}" if self.entitlement_id else ""
        return f"{self.code} {self.at}{scope}: {self.reason}"


@dataclass(frozen=True)
class SessionClose:
    """One valuation point that is not an event, with its order against same-stamp events stated.

    A close that shares a timestamp with a fill is a real situation, and inventing a minute of
    offset to sort it would be fabricating evidence. `position` says which side of that timestamp's
    events the valuation belongs on, so the prefix count is derived rather than guessed.
    """

    at: datetime
    position: Literal["before_events", "after_events"] = "after_events"
    label: str = "session_close"

    def __post_init__(self) -> None:
        if self.at.tzinfo is None or self.at.utcoffset() is None:
            raise MeasurementError("a session close must be timezone-aware")
        if self.position not in {"before_events", "after_events"}:
            raise MeasurementError("session close position must be before_events or after_events")


@dataclass(frozen=True)
class ValuationCalendar:
    """The session closes the valuation path is REQUIRED to contain, as a set to check against.

    Codex's review: a caller passing some closes, or asserting `complete=True`, proves nothing. The
    measurement therefore states which closes it needs, and `measure` verifies that each one is
    actually present among the checkpoints it built. A shortfall is named and downgrades the path.

    `declared_complete` is the caller's assertion that `required_closes` is the whole session list
    for the interval. It is recorded and reported; it is never accepted in place of the set check,
    and it cannot upgrade a path whose closes are missing.

    This is the requirement, never the supply. `measure` builds its valuation points from the
    closes the caller actually has, then checks them against this set -- so a calendar cannot
    satisfy itself.
    """

    calendar_id: str
    required_closes: tuple[SessionClose, ...]
    declared_complete: bool
    basis: str

    def __post_init__(self) -> None:
        if not self.calendar_id or not self.basis:
            raise MeasurementError("a valuation calendar must state an id and a basis")
        if any(not isinstance(item, SessionClose) for item in self.required_closes):
            raise MeasurementError("required_closes must contain SessionClose")
        moments = [item.at for item in self.required_closes]
        if any(left > right for left, right in zip(moments, moments[1:], strict=False)):
            raise MeasurementError("required closes must be nondecreasing")


@dataclass(frozen=True)
class MarkPolicy:
    """As-of marks for a recorded prefix, with a stated basis.

    `resolve(prefix_count, at)` returns the raw marks in force once `prefix_count` events have been
    replayed. Keying on the prefix count rather than the wall clock is what makes a split work: the
    checkpoint before the SPLIT event and the checkpoint after it share a timestamp but differ by
    one event, and the price per share differs accordingly.

    A basis is required for the same reason the execution policies require one. Index and date
    validation in the shared bridge cannot establish that a mark was executable or point-in-time;
    only the stated basis says where it came from.
    """

    resolve: Callable[[int, datetime], Mapping[str, float]]
    basis: str

    def __post_init__(self) -> None:
        if not self.basis:
            raise MeasurementError("a mark policy must state its basis")


def _aware(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise MeasurementError(f"{name} must be an ISO timezone-aware string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise MeasurementError(f"{name} must be an ISO timezone-aware string") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MeasurementError(f"{name} must be an ISO timezone-aware string")
    return parsed


def recorded_prefix(events: Sequence[Mapping[str, Any]], endpoint: datetime) -> list[Mapping[str, Any]]:
    """The events visible at `endpoint`, in recorded order.

    A payment that settles after the endpoint is not evidence at the endpoint. Slicing here rather
    than filtering later is what makes the two-endpoint fixture honest: the same recorded stream,
    read twice, classifies the same attempt differently because different cash is known.
    """
    if endpoint.tzinfo is None or endpoint.utcoffset() is None:
        raise MeasurementError("endpoint must be timezone-aware")
    prefix: list[Mapping[str, Any]] = []
    previous: datetime | None = None
    for event in events:
        moment = _aware(event.get("date"), "event date")
        if previous is not None and moment < previous:
            raise MeasurementError("recorded events must be nondecreasing in time")
        previous = moment
        if moment <= endpoint:
            prefix.append(event)
    return prefix


def visible_gaps(gaps: Sequence[EvidenceGap], endpoint: datetime) -> tuple[list[EvidenceGap], list[EvidenceGap]]:
    """Split evidence gaps into those known by `endpoint` and those discovered after it.

    A gap discovered next month is not a defect in last month's report. Before this split, a future
    gap either corrupted an earlier endpoint's classification or failed association outright.
    """
    known: list[EvidenceGap] = []
    later: list[EvidenceGap] = []
    for gap in gaps:
        (known if _aware(gap.at, "evidence gap timestamp") <= endpoint else later).append(gap)
    return known, later


def build_checkpoints(
    events: Sequence[Mapping[str, Any]],
    *,
    marks: MarkPolicy,
    endpoint: datetime,
    session_closes: Sequence[SessionClose] = (),
) -> list[dict[str, Any]]:
    """Valuation checkpoints for the shared bridge: one before and one after every event.

    The pre/post pair per event is not decoration. The bridge detects an exit only as a change
    between consecutive checkpoints, requires each attempt's entry checkpoint index to be strictly
    increasing, and uses `entry_index - 1` as the window's pre-entry equity denominator. Collapse
    the pair and all three break at once -- a closed attempt starts looking open. They are
    therefore never dropped, including when a session close lands on the same timestamp.

    A close at an event's timestamp is placed by its own stated `position`, so its prefix count is
    derived from the ordering the caller declared rather than from a fabricated offset.
    """
    points: list[dict[str, Any]] = []
    moments = [_aware(event["date"], "event date") for event in events]
    for index, event in enumerate(events):
        stamp = str(event["date"])
        moment = moments[index]
        points.append({"date": stamp, "event_count": index, "raw_marks": dict(marks.resolve(index, moment)), "kind": "pre_event"})
        points.append({"date": stamp, "event_count": index + 1, "raw_marks": dict(marks.resolve(index + 1, moment)), "kind": "post_event"})
    for close in session_closes:
        if close.at > endpoint:
            continue
        if close.position == "after_events":
            count = sum(1 for moment in moments if moment <= close.at)
            order = 1
        else:
            count = sum(1 for moment in moments if moment < close.at)
            order = -1
        points.append({
            "date": close.at.isoformat(),
            "event_count": count,
            "raw_marks": dict(marks.resolve(count, close.at)),
            "kind": close.label,
            "_order": order,
        })
    points.sort(key=lambda item: (_aware(item["date"], "checkpoint date"), item.get("_order", 0), item["event_count"]))
    if moments and endpoint < moments[-1]:
        raise MeasurementError("endpoint precedes the last recorded event in the prefix")
    last = points[-1] if points else None
    if last is None or _aware(last["date"], "checkpoint date") < endpoint:
        points.append({
            "date": endpoint.isoformat(),
            "event_count": len(events),
            "raw_marks": dict(marks.resolve(len(events), endpoint)),
            "kind": "endpoint",
        })
    for point in points:
        point.pop("_order", None)
    return points


@dataclass
class CapturedCash:
    """One attempt's captured-cash decomposition, taken apart only as far as the policy names.

    The attempt itself, its event membership and its totals all come from the shared replay. What
    this adds is the split of `buy_total` into `G` and its costs, and of `sell_total` into `S` and
    its costs, because the policy's denominator is gross purchase consideration and the ledger has
    no reason to keep that apart.
    """

    attempt_id: str
    code: str
    closed: bool
    gross_purchase: float = 0.0
    gross_sale: float = 0.0
    distributions: float = 0.0
    costs: float = 0.0
    unpaid_entitlements: float = 0.0
    net_cash_flow: float = 0.0
    evidence_missing: tuple[str, ...] = ()

    @property
    def captured_return(self) -> float | None:
        """(S + D - G - C) / G, or None when the policy cannot form it."""
        if not self.closed or self.gross_purchase <= 0 or self.evidence_missing:
            return None
        return self.net_cash_flow / self.gross_purchase

    @property
    def disposition(self) -> str:
        if not self.closed:
            return "open"
        if self.evidence_missing:
            return "unresolved_missing_evidence"
        if self.gross_purchase <= 0:
            # "empty attempts are not zero-return trades"
            return "unresolved_no_gross_purchase"
        captured = self.captured_return
        assert captured is not None
        return "hit" if captured >= PROVISIONAL_HIT_THRESHOLD else "non_hit"


def _event_costs(event: Mapping[str, Any]) -> float:
    cents = 0
    for name in ("commission_cents", "tax_cents", "penalty_cents"):
        value = event.get(name, 0) or 0
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MeasurementError(f"{name} must be a nonnegative integer number of cents")
        cents += value
    return cents / 100.0


def _event_price(event: Mapping[str, Any]) -> float:
    """The modelled execution price the fill carried, required rather than reconstructed.

    The 2026-09-13 version fell back to deriving a price from the cash total when `price` was
    absent. That is a reconstruction presented next to observations. A fill without a price is now
    an error, because the shared auction and lifecycle layers always emit one and a hand-written
    event that omits it is missing evidence, not an invitation to solve for it.
    """
    price = event.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise MeasurementError(f"{event.get('action')} {event.get('code')} has no positive modelled execution price")
    return float(price)


@dataclass(frozen=True)
class AttemptSpan:
    """When an attempt opened and when it actually went flat, from the ledger's own membership."""

    opened_at: datetime
    closed_at: datetime | None


def _attempt_spans(events: Sequence[Mapping[str, Any]], membership: Mapping[int, str]) -> dict[str, AttemptSpan]:
    """Flat-to-flat spans derived from the running share count inside each attempt.

    Codex's review: treating any SELL as the close ends an attempt at its first partial exit, and
    then a gap between that partial and the final disposal has nowhere to attach. Shares are
    tracked per attempt instead, and closure is the moment the count first reaches zero -- which is
    the same definition `replay_ledger` uses to move an attempt out of `open_attempts`.
    """
    opened: dict[str, datetime] = {}
    closed: dict[str, datetime] = {}
    shares: dict[str, int] = {}
    for index, event in enumerate(events):
        identity = membership[index]
        moment = _aware(event["date"], "event date")
        opened.setdefault(identity, moment)
        action = str(event["action"]).upper()
        if action == "BUY":
            shares[identity] = shares.get(identity, 0) + int(event["qty"])
        elif action == "SELL":
            shares[identity] = shares.get(identity, 0) - int(event["qty"])
            if shares[identity] <= 0 and identity not in closed:
                closed[identity] = moment
        elif action == "SPLIT":
            shares[identity] = int(event["new_qty"])
    return {identity: AttemptSpan(moment, closed.get(identity)) for identity, moment in opened.items()}


def captured_cash(
    initial_cash: float,
    events: Sequence[Mapping[str, Any]],
    *,
    max_positions: int,
    evidence_gaps: Sequence[EvidenceGap] = (),
) -> tuple[dict[str, CapturedCash], dict[str, Any]]:
    """Decompose each shared-replay attempt into G, S, D and C, and reconcile it.

    Event-to-attempt membership is read from the replay's own `cash_rows`, which is how a dividend
    paid after a re-entry stays with the attempt that earned it. No trade pairing happens here.
    """
    ledger = replay_ledger(initial_cash, events, max_positions=max_positions)
    rows: dict[str, CapturedCash] = {}
    for items, closed in ((ledger["attempts"], True), (ledger["open_attempts"], False)):
        for item in items:
            identity = str(item["id"])
            rows[identity] = CapturedCash(
                attempt_id=identity,
                code=str(item["code"]),
                closed=closed,
                distributions=float(item["dividend_total"]),
                unpaid_entitlements=float(item["dividend_receivable"]),
                net_cash_flow=float(item["buy_total"] + item["sell_total"] + item["dividend_total"]),
            )
    membership = {int(row["event_index"]): str(row["attempt_id"]) for row in ledger["cash_rows"]}

    buy_costs: dict[str, float] = dict.fromkeys(rows, 0.0)
    sell_costs: dict[str, float] = dict.fromkeys(rows, 0.0)
    for index, event in enumerate(events):
        identity = membership[index]
        action = str(event["action"]).upper()
        if action not in {"BUY", "SELL"}:
            continue
        row = rows[identity]
        price = _event_price(event)
        quantity = int(event["qty"])
        costs = _event_costs(event)
        row.costs += costs
        if action == "BUY":
            row.gross_purchase += quantity * price
            buy_costs[identity] += costs
        else:
            row.gross_sale += quantity * price
            sell_costs[identity] += costs

    ledger_by_id = {str(item["id"]): item for item in (*ledger["attempts"], *ledger["open_attempts"])}
    for identity, row in rows.items():
        _reconcile(row, ledger_by_id[identity], buy_costs[identity], sell_costs[identity])

    spans = _attempt_spans(events, membership)
    owners = {str(item["id"]): str(item["attempt_id"]) for item in ledger["dividend_entitlements"]}
    for gap in evidence_gaps:
        identity = _gap_attempt(gap, spans, rows, owners)
        rows[identity].evidence_missing = (*rows[identity].evidence_missing, gap.describe())
    return rows, ledger


def _reconcile(row: CapturedCash, item: Mapping[str, Any], buy_costs: float, sell_costs: float) -> None:
    """Prove the decomposition is the ledger's own totals, taken apart and not recomputed."""
    checks = (
        ("buy_total", float(item["buy_total"]), -(row.gross_purchase + buy_costs)),
        ("sell_total", float(item["sell_total"]), row.gross_sale - sell_costs),
        ("net_cash_flow", row.net_cash_flow, row.gross_sale + row.distributions - row.gross_purchase - row.costs),
    )
    for name, expected, derived in checks:
        if abs(expected - derived) > RECONCILE_TOLERANCE_TWD:
            raise MeasurementError(f"attempt {row.attempt_id} {name} does not reconcile: ledger {expected} vs decomposition {derived}")


def _gap_attempt(
    gap: EvidenceGap,
    spans: Mapping[str, AttemptSpan],
    rows: Mapping[str, CapturedCash],
    entitlement_owners: Mapping[str, str],
) -> str:
    """Which attempt an evidence gap belongs to, refusing to choose when it is genuinely ambiguous.

    An entitlement-scoped gap is placed by the ledger, which already attributes every entitlement
    to the attempt that earned it -- including one paid after that attempt closed and the same code
    was re-entered. Everything else is placed by the attempt's own flat-to-flat span; if a code
    closes and re-enters at one timestamp, two spans contain that instant and the gap is refused.
    """
    moment = _aware(gap.at, "evidence gap timestamp")
    if gap.entitlement_id is not None:
        owner = entitlement_owners.get(gap.entitlement_id)
        if owner is None:
            raise MeasurementError(f"evidence gap names unknown entitlement {gap.entitlement_id}")
        if rows[owner].code != gap.code:
            raise MeasurementError(f"evidence gap code {gap.code} does not match entitlement {gap.entitlement_id}")
        return owner
    matches = [
        identity
        for identity, span in spans.items()
        if rows[identity].code == gap.code and span.opened_at <= moment and (span.closed_at is None or moment <= span.closed_at)
    ]
    if not matches:
        raise MeasurementError(f"evidence gap for {gap.code} at {gap.at} matches no attempt span")
    if len(matches) > 1:
        raise MeasurementError(
            f"evidence gap for {gap.code} at {gap.at} is ambiguous between attempts {sorted(matches)}; supply entitlement_id to name the one it concerns"
        )
    return matches[0]


def _underwater_spans(dates: Sequence[str], values: Sequence[float]) -> tuple[list[dict[str, Any]], bool]:
    """Every peak-to-recovery span, settled at the recovery point rather than the last low.

    Codex's review: the previous loop cleared its state the moment equity regained the peak, so the
    span was measured to the last checkpoint that was still below it. A high on day 1, water on
    day 2 and recovery on day 5 is five days underwater, not two. A span still open at the end is
    reported as censored: the account has not recovered yet, and calling that a finished duration
    would understate it.
    """
    peak, peak_at = values[0], dates[0]
    since: str | None = None
    spans: list[dict[str, Any]] = []

    def days(start: str, end: str) -> float:
        return (_aware(end, "checkpoint date") - _aware(start, "checkpoint date")).total_seconds() / 86_400.0

    for stamp, value in zip(dates, values, strict=True):
        if value >= peak:
            if since is not None:
                spans.append({"from": since, "to": stamp, "days": days(since, stamp), "status": "recovered"})
                since = None
            peak, peak_at = value, stamp
            continue
        if since is None:
            since = peak_at
    censored = since is not None
    if since is not None:
        spans.append({"from": since, "to": dates[-1], "days": days(since, dates[-1]), "status": "censored"})
    return spans, censored


def _account_path(checkpoints: Sequence[Mapping[str, Any]], valuation: Mapping[str, Any]) -> dict[str, Any]:
    """The full account's own equity series, reported apart from the attribution series.

    These are two different quantities and the contract is explicit that neither replaces the
    other: attribution can show unacceptable erosion while the account is still profitable. They
    are kept under separate keys here so a chart of one cannot be captioned as the other.

    A path whose required session closes are not all present is still computed -- the numbers it
    does have are useful -- but it is labelled `diagnostic_incomplete_valuation`, never `ok`. A
    drawdown measured on a sparse grid is a lower bound on the real one.
    """
    dates = [str(point["date"]) for point in checkpoints]
    equity = [point["equity"] for point in checkpoints]
    if any(value is None for value in equity):
        return {"status": "unavailable", "reason": "account equity missing at one or more checkpoints"}
    values = [float(value) for value in equity]
    spans, censored = _underwater_spans(dates, values)
    longest = max(spans, key=lambda item: item["days"]) if spans else None
    return {
        "status": "ok" if valuation["status"] == "complete" else "diagnostic_incomplete_valuation",
        "valuation_status": valuation["status"],
        "series": "full_account_marked_equity",
        "initial_equity_twd": values[0],
        "final_equity_twd": values[-1],
        "max_drawdown_fraction": max_drawdown(values),
        "max_drawdown_support": "lower bound: measured only at the supplied checkpoints"
        if valuation["status"] != "complete"
        else "measured at every required session close and event",
        "underwater_spans": spans,
        "longest_underwater_days": longest["days"] if longest else 0.0,
        "longest_underwater_span": longest,
        "ends_underwater": censored,
        "underwater_censored": censored,
        "equity_path": list(zip(dates, values, strict=True)),
    }


def _valuation_verdict(
    calendar: ValuationCalendar | None,
    checkpoints: Sequence[Mapping[str, Any]],
    endpoint: datetime,
    marks: MarkPolicy,
) -> dict[str, Any]:
    """Check the required closes as a SET against what was actually built.

    A count of supplied closes proves nothing, and neither does a caller asserting completeness:
    both are recorded, and both are checked against the checkpoints that exist. With no calendar at
    all the result is an explicitly named event-only diagnostic -- an honest mode, but never one
    that may be described as a complete path.
    """
    if calendar is None:
        return {
            "status": "event_only_diagnostic",
            "reason": "no valuation calendar supplied; the path is valued only at event boundaries",
            "calendar_id": None,
            "declared_complete": False,
            "required_closes": 0,
            "present_closes": 0,
            "missing_closes": [],
            "marks_basis": marks.basis,
        }
    required = [item for item in calendar.required_closes if item.at <= endpoint]
    present = {str(point["date"]) for point in checkpoints}
    missing = [item.at.isoformat() for item in required if item.at.isoformat() not in present]
    if missing:
        status = "incomplete_missing_required_closes"
    elif not calendar.declared_complete:
        status = "incomplete_calendar_not_declared_complete"
    else:
        status = "complete"
    verdict = {
        "status": status,
        "calendar_id": calendar.calendar_id,
        "calendar_basis": calendar.basis,
        "declared_complete": calendar.declared_complete,
        "required_closes": len(required),
        "present_closes": len(required) - len(missing),
        "missing_closes": missing,
        "marks_basis": marks.basis,
    }
    if status != "complete":
        verdict["reason"] = (
            "required session closes are absent from the valuation path" if missing else "the caller did not declare this calendar the complete session list"
        )
    return verdict


def missing_marks(
    initial_cash: float,
    events: Sequence[Mapping[str, Any]],
    checkpoints: Sequence[Mapping[str, Any]],
    *,
    max_positions: int,
) -> list[dict[str, Any]]:
    """Every checkpoint at which a held code has no mark, with the codes named.

    The holdings come from the shared replay of that checkpoint's own prefix, so "held" means what
    the ledger means by it and nothing is inferred from the marks themselves.
    """
    held: dict[int, tuple[str, ...]] = {}
    found: list[dict[str, Any]] = []
    for point in checkpoints:
        count = int(point["event_count"])
        if count not in held:
            positions = replay_ledger(initial_cash, list(events[:count]), max_positions=max_positions)["positions"]
            held[count] = tuple(sorted(positions))
        absent = [code for code in held[count] if code not in point["raw_marks"]]
        if absent:
            found.append({"date": point["date"], "event_count": count, "kind": point["kind"], "codes": absent})
    return found


def _fixed_fractions(metric: Mapping[str, Any]) -> dict[str, float | None]:
    """TWD attribution restated against the fixed NT$2m denominator the contract names."""

    def fraction(name: str) -> float | None:
        value = metric.get(name)
        return None if value is None else float(value) / PRIMARY_DENOMINATOR_TWD

    return {
        "net_fraction_fixed_2m": fraction("net_pnl_twd"),
        "worst_cumulative_loss_fraction_fixed_2m": fraction("worst_cumulative_loss_twd"),
        "peak_to_trough_fraction_fixed_2m": fraction("peak_to_trough_erosion_twd"),
    }


def measure(
    *,
    initial_cash: float,
    events: Sequence[Mapping[str, Any]],
    marks: MarkPolicy,
    endpoint: datetime,
    max_positions: int,
    calendar: ValuationCalendar | None = None,
    session_closes: Sequence[SessionClose] = (),
    evidence_gaps: Sequence[EvidenceGap] = (),
    span: int = NON_HIT_WINDOW,
) -> dict[str, Any]:
    """Measure one recorded stream at one endpoint, using the shared reducer for every path.

    `max_positions` is required rather than defaulted. Five is the candidate's holding ceiling, a
    strategy parameter; inheriting it into a measurement fixture would silently reject a perfectly
    legitimate 21-attempt diagnostic stream for a reason that has nothing to do with measurement.

    `calendar` states which session closes the path is REQUIRED to contain; `session_closes` is
    what the caller actually has. They are deliberately separate inputs: if the calendar supplied
    its own valuation points the set check would confirm itself, and a sparse path would keep
    reporting as complete. Supplying no closes against a calendar that requires them is therefore
    an incomplete path, not an empty requirement.
    """
    prefix = recorded_prefix(events, endpoint)
    known_gaps, later_gaps = visible_gaps(evidence_gaps, endpoint)
    rows = captured_cash(initial_cash, prefix, max_positions=max_positions, evidence_gaps=known_gaps)[0]
    classifications: dict[str, bool | None] = {}
    for identity, row in rows.items():
        disposition = row.disposition
        classifications[identity] = True if disposition == "hit" else False if disposition == "non_hit" else None

    closes = tuple(session_closes)
    checkpoints = build_checkpoints(prefix, marks=marks, endpoint=endpoint, session_closes=closes)
    valuation = _valuation_verdict(calendar, checkpoints, endpoint, marks)
    absent = missing_marks(initial_cash, prefix, checkpoints, max_positions=max_positions)
    if absent:
        # The shared ledger would refuse these checkpoints, and it is right to. Nothing is filled:
        # the cash-only decomposition stands, the marked series is withheld, and the report says
        # exactly where the evidence ran out.
        valuation = {
            **valuation,
            "status": "incomplete_missing_marks",
            "reason": "a held code has no mark at one or more checkpoints; no price was substituted",
            "missing_marks": absent,
        }
        unknown = [identity for identity, known in classifications.items() if known is None]
        # Every key a v2 reader expects is present, holding None or an empty list, so a reader
        # written before this branch existed sees a status rather than a KeyError.
        attribution: dict[str, Any] = {
            "status": "unavailable",
            "reason": "missing valuation evidence",
            "metric": "non_hit_attribution.v1",
            "attribution_only": True,
            "span": span,
            "classification_complete": not unknown,
            "classification_reasons": None,
            "whole_study": None,
            "unclassified_attribution": None,
            "runs": [],
            "windows": [],
            "window_summary": {"status": "unavailable", "reason": "missing valuation evidence", "worst_peak_to_trough_fraction_start": None},
            "unknown_attempt_ids": unknown,
        }
        account: dict[str, Any] = {
            "status": "unavailable",
            "reason": "missing valuation evidence",
            "valuation_status": valuation["status"],
            "missing_marks": absent,
        }
        ordered = sorted(rows, key=lambda identity: (rows[identity].code, identity))
        evidence_basis: Any = None
    else:
        inputs = build_attribution_inputs(
            initial_cash=initial_cash,
            events=prefix,
            checkpoints=checkpoints,
            classifications=classifications,
            max_positions=max_positions,
        )
        attribution = non_hit_attribution(inputs["attempts"], inputs["checkpoints"], initial_equity=inputs["initial_equity"], span=span)
        ordered = [item["id"] for item in inputs["attempts"]]
        for metric in (attribution["whole_study"], attribution["unclassified_attribution"], *attribution["runs"], *attribution["windows"]):
            metric.update(_fixed_fractions(metric))
            metric["valuation_status"] = valuation["status"]
        account = _account_path(inputs["checkpoints"], valuation)
        evidence_basis = inputs["evidence_basis"]
    counts: dict[str, int] = {}
    for identity in ordered:
        counts[rows[identity].disposition] = counts.get(rows[identity].disposition, 0) + 1

    return {
        "schema": "prototype-measurement-bridge.v2",
        "endpoint": endpoint.isoformat(),
        "policy": {
            "hit_threshold": PROVISIONAL_HIT_THRESHOLD,
            "hit_threshold_status": "provisional; selected in development-measurement, NOT owner-approved",
            "span": span,
            "primary_denominator_twd": PRIMARY_DENOMINATOR_TWD,
            "secondary_denominator": "each window's full-account equity immediately before its first entry",
            "max_positions": max_positions,
            "marks_basis": marks.basis,
            "slippage": "already embedded in the modelled execution price; not subtracted again",
        },
        "captured_cash": {
            identity: {
                "code": rows[identity].code,
                "gross_purchase_twd": rows[identity].gross_purchase,
                "gross_sale_twd": rows[identity].gross_sale,
                "distributions_twd": rows[identity].distributions,
                "costs_twd": rows[identity].costs,
                "unpaid_entitlements_twd": rows[identity].unpaid_entitlements,
                "captured_cash_twd": rows[identity].net_cash_flow,
                "captured_return": rows[identity].captured_return,
                "disposition": rows[identity].disposition,
                "evidence_missing": list(rows[identity].evidence_missing),
            }
            for identity in ordered
        },
        "attempt_order": ordered,
        "disposition_counts": counts,
        "non_hit_attribution": attribution,
        "account": account,
        "valuation": valuation,
        "completeness": {
            "classification_complete": attribution["classification_complete"],
            "valuation_complete": valuation["status"] == "complete",
            "unresolved_attempt_ids": attribution["unknown_attempt_ids"],
            "evidence_basis": evidence_basis,
            "attribution_only": True,
            "events_recorded": len(prefix),
            "events_after_endpoint": len(events) - len(prefix),
            "checkpoints": len(checkpoints),
            "unpaid_entitlements_twd": sum(row.unpaid_entitlements for row in rows.values()),
            "evidence_gaps": [gap.describe() for gap in known_gaps],
            "evidence_gaps_after_endpoint": [gap.describe() for gap in later_gaps],
        },
    }


__all__ = [
    "CLOSED_DISPOSITIONS",
    "NON_HIT_WINDOW",
    "PRIMARY_DENOMINATOR_TWD",
    "PROVISIONAL_HIT_THRESHOLD",
    "AttemptSpan",
    "CapturedCash",
    "EvidenceGap",
    "MarkPolicy",
    "MeasurementError",
    "SessionClose",
    "ValuationCalendar",
    "build_checkpoints",
    "captured_cash",
    "measure",
    "missing_marks",
    "recorded_prefix",
    "visible_gaps",
]
