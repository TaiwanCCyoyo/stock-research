"""Build replay-derived evidence inputs for :func:`non_hit_attribution`.

This module only translates a caller-supplied, complete sequence of recorded
events and as-of marks into the input shape consumed by attribution.  It does
not choose a hit threshold, fetch market data, establish point-in-time source
provenance, or certify captured-value criteria.  Attempt IDs are properties of
this particular prefix replay and are not stable across counterfactual event
streams; this is not an optimized full-history runner.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from research_core.attribution import AttributionError, mark_attempt_pnl
from research_core.ledger import mark_equity, replay_ledger


def _aware_iso(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise AttributionError(f"{name} must be an ISO timezone-aware string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AttributionError(f"{name} must be an ISO timezone-aware string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AttributionError(f"{name} must be an ISO timezone-aware string")
    return parsed


def _checkpoint(value: Any) -> tuple[datetime, int, dict[str, float], str]:
    if not isinstance(value, Mapping):
        raise AttributionError("checkpoint must be a mapping")
    date = _aware_iso(value.get("date"), "checkpoint date")
    count = value.get("event_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise AttributionError("checkpoint event_count must be a nonnegative integer")
    marks = value.get("raw_marks")
    if not isinstance(marks, Mapping):
        raise AttributionError("checkpoint raw_marks must be a mapping")
    # Keep only our own container: callers can mutate their mapping after return.
    return date, count, dict(marks), value["date"]


def _attempt_records(ledger: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for items, closed in ((ledger["attempts"], True), (ledger["open_attempts"], False)):
        for item in items:
            identity = item.get("id")
            if isinstance(identity, bool) or not isinstance(identity, (int, str)) or identity == "":
                raise AttributionError("replay produced an invalid attempt id")
            entry_event_index = item.get("entry_event_index")
            code = item.get("code")
            if isinstance(entry_event_index, bool) or not isinstance(entry_event_index, int) or not isinstance(code, str):
                raise AttributionError("replay produced an invalid attempt")
            records.append({"id": str(identity), "code": code, "entry_event_index": entry_event_index, "closed": closed, "item": item})
    if len({item["id"] for item in records}) != len(records):
        raise AttributionError("replay produced duplicate normalized attempt IDs")
    return sorted(records, key=lambda item: item["entry_event_index"])


def build_attribution_inputs(
    *,
    initial_cash: float,
    events: Sequence[Mapping[str, Any]],
    checkpoints: Sequence[Mapping[str, Any]],
    classifications: Mapping[str, bool | None],
    max_positions: int = 5,
) -> dict[str, Any]:
    """Build complete replay-backed attribution inputs without strategy policy.

    The caller supplies the entire recorded study stream and all checkpoint
    marks.  Dates constrain each checkpoint to its event prefix.  This helper
    intentionally cannot prove hidden calendar, PIT, source, mark-provenance,
    or captured-threshold claims.
    """
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        raise AttributionError("events must be a sequence")
    if not isinstance(checkpoints, Sequence) or isinstance(checkpoints, (str, bytes)) or not checkpoints:
        raise AttributionError("at least one checkpoint is required")
    if not isinstance(classifications, Mapping):
        raise AttributionError("classifications must be a mapping")
    if isinstance(max_positions, bool) or not isinstance(max_positions, int) or max_positions <= 0:
        raise AttributionError("max_positions must be a positive integer")

    copied_events = list(events)
    event_dates: list[datetime] = []
    for index, event in enumerate(copied_events):
        if not isinstance(event, Mapping):
            raise AttributionError("each event must be a mapping")
        event_date = _aware_iso(event.get("date"), "event date")
        if event_dates and event_date < event_dates[-1]:
            raise AttributionError("event dates must be nondecreasing")
        event_dates.append(event_date)
        if isinstance(event.get("action"), str) and event["action"].upper() == "DIVIDEND":
            entitlement_id = event.get("entitlement_id")
            if not isinstance(entitlement_id, str) or not entitlement_id:
                raise AttributionError("DIVIDEND requires a nonempty entitlement_id")

    parsed = [_checkpoint(item) for item in checkpoints]
    if parsed[0][1] != 0 or parsed[-1][1] != len(copied_events):
        raise AttributionError("checkpoint counts must start at zero and end at all events")
    previous_date: datetime | None = None
    previous_count: int | None = None
    for date, count, _marks, _date_text in parsed:
        if count > len(copied_events):
            raise AttributionError("checkpoint event_count exceeds events")
        if previous_date is not None and date < previous_date:
            raise AttributionError("checkpoint dates must be nondecreasing")
        if previous_count is not None and count - previous_count not in (0, 1):
            raise AttributionError("checkpoint event_count must increase by zero or one")
        if previous_count is not None and count == previous_count + 1 and date != event_dates[count - 1]:
            raise AttributionError("an event-increment checkpoint must match its event date")
        if count and date < event_dates[count - 1]:
            raise AttributionError("checkpoint predates its last included event")
        if count < len(event_dates) and date > event_dates[count]:
            raise AttributionError("checkpoint postdates its next event")
        previous_date, previous_count = date, count

    replay_cache: dict[int, dict[str, Any]] = {}

    def replay(count: int) -> dict[str, Any]:
        if count not in replay_cache:
            # Reuse repeated marks of one prefix without retaining every full
            # historical ledger in addition to the required output PnL paths.
            replay_cache.clear()
            replay_cache[count] = replay_ledger(initial_cash, copied_events[:count], max_positions=max_positions)
        return replay_cache[count]

    # Replay before validating the fixed E0 pre-event checkpoints, so "new" is
    # ledger-defined rather than inferred from action intent.
    final_ledger = replay(len(copied_events))
    for index, (_date, count, _marks, _date_text) in enumerate(parsed):
        if index == 0 or count == parsed[index - 1][1]:
            continue
        event_index = count - 1
        event = copied_events[event_index]
        if (
            isinstance(event.get("action"), str)
            and event["action"].upper() == "BUY"
            and isinstance(event.get("code"), str)
            and event["code"] not in {item["code"] for item in replay(event_index)["open_attempts"]}
            and parsed[index - 1][0] != event_dates[event_index]
        ):
            raise AttributionError("a new BUY requires a same-timestamp pre-event checkpoint")

    records = _attempt_records(final_ledger)
    identities = {item["id"] for item in records}
    if any(not isinstance(identity, str) for identity in classifications) or set(classifications) != identities:
        raise AttributionError("classifications must contain exactly the normalized attempt IDs")
    for identity, hit in classifications.items():
        if hit is not None and not isinstance(hit, bool):
            raise AttributionError("attempt classification must be bool or None")

    final_open = {item["id"] for item in records if not item["closed"]}
    if any(classifications[identity] is not None for identity in final_open):
        raise AttributionError("only unknown classifications are allowed for open attempts")

    entry_indices: dict[str, int] = {}
    exit_indices: dict[str, int | None] = {item["id"]: None for item in records}
    output_points: list[dict[str, Any]] = []
    was_open: set[str] = set()
    for index, (date, count, marks, date_text) in enumerate(parsed):
        ledger = replay(count)
        observed = mark_attempt_pnl(ledger, marks)
        equity = mark_equity(ledger, marks)
        open_now = {str(item["id"]) for item in ledger["open_attempts"]}
        for record in records:
            identity = record["id"]
            if identity not in entry_indices and count >= record["entry_event_index"] + 1:
                entry_indices[identity] = index
            if identity in was_open and identity not in open_now and exit_indices[identity] is None:
                exit_indices[identity] = index
        was_open = open_now
        pnl = {record["id"]: observed.get(record["id"], 0.0 if record["id"] not in entry_indices else None) for record in records}
        if any(value is None for value in pnl.values()):
            raise AttributionError("replay omitted PnL for an entered attempt")
        output_points.append({"date": date_text, "equity": float(equity), "attempt_pnl": pnl})

    attempts: list[dict[str, Any]] = []
    for record in records:
        identity = record["id"]
        if identity not in entry_indices:
            raise AttributionError("replay attempt has no entry checkpoint")
        item = record["item"]
        captured = float(item["net_cash_flow"]) if record["closed"] else None
        attempts.append({
            "id": identity,
            "code": record["code"],
            "entry_index": entry_indices[identity],
            "exit_index": exit_indices[identity],
            "hit": classifications[identity],
            "captured_pnl_twd": captured,
        })
    return {
        "schema_version": "attribution-inputs.v1",
        "evidence_basis": "caller_supplied_complete_recorded_events_and_marks",
        "attribution_only": True,
        "attempts": attempts,
        "checkpoints": output_points,
        "initial_equity": float(initial_cash),
    }
