"""Explicit vocabulary for ending an order and for the order that replaces it.

`order_lifecycle` reconciles one auction date's residual reports; `chronology` owns the queue of
requests that are fixed at one decision and wait for a later session. Between those two there was
no way to say three things that a run genuinely needs to say:

- **A queued request can be taken back before it is ever submitted.** That is not a broker cancel
  and must not borrow the receipt vocabulary: nothing reached a venue, so there is no `report_id`
  and nothing was filled. `WITHDRAWN` says exactly that.
- **An order that ended tells the next decision how it ended and what was left.** Without it a
  retry is a brand new order with no link to what it retries, and nothing stops it re-requesting
  the whole original size after a partial fill.
- **A replacement is a child, not an edit.** The original order keeps its recorded identity and
  quantity; the order that actually goes to market is a new identity naming its parent. History is
  never silently rewritten, and a reader can always see both.

Every type here is inert data with its own validation. None of it decides anything: the run's rule
supplies the actions, the run's policy supplies the corporate resolutions, and `chronology`
enforces that what they supply is consistent with what actually happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from research_core.signals import SignalIdentity


class OrderActionError(ValueError):
    """A supplied action, lineage or resolution is not internally consistent."""


# How an order came to be terminal. The distinction is the point: a reader must never have to
# guess whether `CANCELLED` came from a broker or from us.
#   auction   -- the auction itself settled it (filled, rejected, or refused by the board)
#   report    -- a caller-supplied FillReport/TerminalReport closed it
#   decision  -- the rule took the request back before it was ever submitted
#   corporate -- a corporate action invalidated it and an explicit policy withdrew or amended it
PROVENANCE = ("auction", "report", "decision", "corporate")

# Statuses this module owns. The four broker statuses are re-used verbatim from TerminalReport so a
# receipt-backed termination reports exactly what the receipt said; the two below are ours, and are
# deliberately spelled differently so they can never be read as a receipt.
BROKER_STATUSES = ("FILLED", "CANCELLED", "EXPIRED", "REJECTED")
INTERNAL_STATUSES = ("WITHDRAWN", "AMENDED")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise OrderActionError(f"{name} must be a nonempty string")
    return value


def _moment(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(hours=8):
        raise OrderActionError(f"{name} must be an aware +08:00 datetime")
    return value


def _count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OrderActionError(f"{name} must be a nonnegative integer")
    return value


@dataclass(frozen=True)
class CancelRequest:
    """Take back a queued request before the session it was waiting for.

    Only legal against a request that is still pending, because anything further along has already
    reached an auction and can only be ended by evidence from there. `decided_at` must be the
    decision that issued the withdrawal, so a withdrawal cannot be backdated past the information
    that motivated it.
    """

    order_id: str
    reason: str
    decided_at: datetime

    def __post_init__(self) -> None:
        _text(self.order_id, "order_id")
        _text(self.reason, "reason")
        _moment(self.decided_at, "decided_at")


@dataclass(frozen=True)
class OrderLineage:
    """The link from a replacement order back to the order it replaces.

    `known_at` is when the parent's ending became knowable to the decision -- a receipt's
    `available_at`, or the decision timestamp for a withdrawal. It exists so a retry cannot be
    justified by information that had not arrived yet.
    """

    parent_order_id: str
    reason: str
    known_at: datetime

    def __post_init__(self) -> None:
        _text(self.parent_order_id, "parent_order_id")
        _text(self.reason, "reason")
        _moment(self.known_at, "known_at")


@dataclass(frozen=True)
class OrderTermination:
    """One order's ending, as the next decision may read it.

    `residual_qty` is what a replacement may ask for at most. It is `requested_qty - filled_qty`
    and never an estimate: a partial fill closed by a cancel leaves exactly the unfilled part, and
    re-requesting the original size would double the exposure of one piece of advice.
    """

    order_id: str
    code: str
    side: str
    status: str
    provenance: str
    reason: str
    requested_qty: int
    filled_qty: int
    terminated_at: datetime
    available_at: datetime
    signal: SignalIdentity | None = None
    parent_order_id: str | None = None
    replaced_by: str | None = None
    report_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.order_id, "order_id")
        _text(self.code, "code")
        if self.side not in {"BUY", "SELL"}:
            raise OrderActionError("side must be BUY or SELL")
        if self.status not in set(BROKER_STATUSES) | set(INTERNAL_STATUSES):
            raise OrderActionError("unknown termination status")
        if self.provenance not in PROVENANCE:
            raise OrderActionError("unknown termination provenance")
        _text(self.reason, "reason")
        if _count(self.requested_qty, "requested_qty") <= 0:
            raise OrderActionError("requested_qty must be positive")
        if _count(self.filled_qty, "filled_qty") > self.requested_qty:
            raise OrderActionError("filled quantity cannot exceed what was requested")
        if _moment(self.terminated_at, "terminated_at") > _moment(self.available_at, "available_at"):
            raise OrderActionError("a termination cannot be knowable before it happened")
        if self.status in INTERNAL_STATUSES and self.report_id is not None:
            raise OrderActionError("an internal termination has no broker receipt")
        if self.status in INTERNAL_STATUSES and self.filled_qty:
            raise OrderActionError("a request that was never submitted cannot have filled")
        if self.signal is not None and not isinstance(self.signal, SignalIdentity):
            raise OrderActionError("signal must be a SignalIdentity")
        for name in ("parent_order_id", "replaced_by", "report_id"):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)

    @property
    def residual_qty(self) -> int:
        return self.requested_qty - self.filled_qty


@dataclass(frozen=True)
class PendingResolution:
    """What an explicit policy does about one queued order a corporate action invalidated.

    Two answers, and no third: withdraw it and let the next decision look at the world again, or
    amend it -- which terminates the original and submits a **new identity** carrying the restated
    quantity and limit. There is no in-place edit, because an order whose size changed without
    changing identity cannot be audited afterwards.

    `basis` is required and separate from `reason`: the reason is what happened, the basis is the
    policy that chose this answer to it. Neither is defaulted, because no default is right for
    everyone -- brokers differ on whether they adjust a resting order across a split, and this
    runner refuses to assume one.
    """

    order_id: str
    action: Literal["cancel", "amend"]
    reason: str
    basis: str
    replacement_order_id: str | None = None
    new_qty: int | None = None
    new_limit_price_cents: int | None = None

    def __post_init__(self) -> None:
        _text(self.order_id, "order_id")
        if self.action not in {"cancel", "amend"}:
            raise OrderActionError("resolution action must be cancel or amend")
        _text(self.reason, "reason")
        _text(self.basis, "basis")
        if self.action == "cancel":
            if self.replacement_order_id is not None or self.new_qty is not None or self.new_limit_price_cents is not None:
                raise OrderActionError("a cancellation states no replacement")
            return
        _text(self.replacement_order_id, "replacement_order_id")
        if self.new_qty is None and self.new_limit_price_cents is None:
            raise OrderActionError("an amendment must restate a quantity, a limit price, or both")
        if self.new_qty is not None and (isinstance(self.new_qty, bool) or not isinstance(self.new_qty, int) or self.new_qty <= 0):
            raise OrderActionError("an amended quantity must be a positive integer")
        if self.new_limit_price_cents is not None and (
            isinstance(self.new_limit_price_cents, bool) or not isinstance(self.new_limit_price_cents, int) or self.new_limit_price_cents <= 0
        ):
            raise OrderActionError("an amended limit price must be a positive integer number of cents")


__all__ = [
    "BROKER_STATUSES",
    "INTERNAL_STATUSES",
    "PROVENANCE",
    "CancelRequest",
    "OrderActionError",
    "OrderLineage",
    "OrderTermination",
    "PendingResolution",
]
