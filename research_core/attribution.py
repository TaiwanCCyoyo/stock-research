"""Deterministic, policy-free PnL attribution for replayed attempts."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from research_core.ledger import LedgerError, mark_equity, mark_share_claims_cents


class AttributionError(ValueError):
    """Raised when attribution evidence is malformed or internally inconsistent."""


def _finite(value: Any, name: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise AttributionError(f"{name} must be finite")
    value = float(value)
    if nonnegative and value < 0:
        raise AttributionError(f"{name} must be nonnegative")
    return value


def _id(value: Any, name: str = "attempt id") -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or value == "":
        raise AttributionError(f"{name} must be a nonempty string or integer")
    return str(value)


def _sum(values: Sequence[float], name: str) -> float:
    try:
        result = math.fsum(values)
    except OverflowError as exc:
        raise AttributionError(f"{name} overflow") from exc
    if not math.isfinite(result):
        raise AttributionError(f"{name} overflow")
    return result


def mark_attempt_pnl(ledger: Mapping[str, Any], raw_marks: Mapping[str, float]) -> dict[str, float]:
    """Mark an as-of event-prefix replay, never a final ledger repriced in the past."""
    # Reuse the ledger's mark validation (especially missing marks for open holdings).
    mark_equity(ledger, raw_marks)
    closed = ledger.get("attempts", [])
    opened = ledger.get("open_attempts", [])
    positions = ledger.get("positions", {})
    if (
        not isinstance(closed, Sequence)
        or isinstance(closed, (str, bytes))
        or not isinstance(opened, Sequence)
        or isinstance(opened, (str, bytes))
        or not isinstance(positions, Mapping)
    ):
        raise LedgerError("ledger attempts and positions must have replay shapes")
    result: dict[str, float] = {}
    open_codes: set[str] = set()

    def amount(item: Mapping[str, Any], field: str, default: float | None = None) -> float:
        try:
            return _finite(item.get(field, default), field)
        except AttributionError as exc:
            raise LedgerError(f"invalid attempt {field}") from exc

    for item in closed:
        if not isinstance(item, Mapping):
            raise LedgerError("ledger attempt must be a mapping")
        identity = _id(item.get("id"))
        if identity in result:
            raise LedgerError("normalized ledger attempt IDs must be unique")
        try:
            value = math.fsum((amount(item, "net_cash_flow"), amount(item, "dividend_receivable", 0.0), amount(item, "capital_return_receivable", 0.0)))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise LedgerError("invalid closed attempt totals") from exc
        if not math.isfinite(value):
            raise LedgerError("closed attempt PnL overflow")
        result[identity] = value
    for item in opened:
        if not isinstance(item, Mapping):
            raise LedgerError("ledger open attempt must be a mapping")
        identity = _id(item.get("id"))
        code = item.get("code")
        if identity in result or not isinstance(code, str) or code in open_codes:
            raise LedgerError("invalid open attempt")
        open_codes.add(code)
        try:
            value = math.fsum((
                amount(item, "buy_total"),
                amount(item, "sell_total"),
                amount(item, "dividend_total"),
                amount(item, "dividend_receivable", 0.0),
                amount(item, "capital_return_total", 0.0),
                amount(item, "capital_return_receivable", 0.0),
                amount(item, "share_settlement_total", 0.0),
                (positions.get(code, 0) * raw_marks[code]) if code in positions else 0.0,
                mark_share_claims_cents(ledger, raw_marks, attempt_id=item.get("id")) / 100.0,
            ))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise LedgerError("invalid open attempt totals") from exc
        if not math.isfinite(value):
            raise LedgerError("open attempt PnL overflow")
        result[identity] = value
    claim_codes = ledger.get("outstanding_share_codes", [])
    if not isinstance(claim_codes, Sequence) or isinstance(claim_codes, (str, bytes)) or any(not isinstance(code, str) for code in claim_codes):
        raise LedgerError("ledger outstanding_share_codes must be a sequence of codes")
    if open_codes != set(positions) | set(claim_codes):
        raise LedgerError("every current holding or share claim must have exactly one open attempt")
    return result


def _metric(ids: list[str], start: int, end: int, checkpoints: list[dict[str, Any]], initial: float) -> dict[str, Any]:
    base = {
        "status": "ok",
        "attempt_ids": ids,
        "start_index": start,
        "end_index": end,
        "start_equity": checkpoints[start]["equity"],
        "net_pnl_twd": None,
        "worst_cumulative_loss_twd": None,
        "peak_to_trough_erosion_twd": None,
        "net_fraction_initial": None,
        "net_fraction_start": None,
        "worst_cumulative_loss_fraction_initial": None,
        "worst_cumulative_loss_fraction_start": None,
        "peak_to_trough_fraction_start": None,
        "peak_to_trough_fraction_initial": None,
    }
    values: list[float] = []
    missing_equity = False
    for point in checkpoints[start : end + 1]:
        if not point["complete_pnl"]:
            base.update(status="unavailable", reason="incomplete account-wide attempt PnL evidence")
            return base
        missing_equity = missing_equity or point["equity"] is None
        pnl = point["attempt_pnl"]
        row: list[float] = []
        for identity in ids:
            value = pnl.get(identity)
            if value is None:
                base.update(status="unavailable", reason="missing selected attempt PnL evidence")
                return base
            row.append(value)
        values.append(_sum(row, "attribution PnL"))
    peak = values[0]
    trough = values[0]
    erosion = 0.0
    for value in values:
        peak = max(peak, value)
        trough = min(trough, value)
        erosion = max(erosion, _sum([peak, -value], "attribution erosion"))
    net = values[-1]
    loss = max(0.0, -trough)

    def ratio(value: float, denominator: float) -> float:
        return _finite(value / denominator, "attribution fraction")

    base.update(
        net_pnl_twd=net,
        worst_cumulative_loss_twd=loss,
        peak_to_trough_erosion_twd=erosion,
        net_fraction_initial=ratio(net, initial),
        peak_to_trough_fraction_initial=ratio(erosion, initial),
        worst_cumulative_loss_fraction_initial=ratio(loss, initial),
    )
    if missing_equity:
        base.update(status="partial", reason="account equity is missing at one or more checkpoints")
    equity = base["start_equity"]
    if equity is None or equity == 0:
        base["fraction_start_reason"] = "missing or zero start equity"
    else:
        base["peak_to_trough_fraction_start"] = ratio(erosion, equity)
        base["net_fraction_start"] = ratio(net, equity)
        base["worst_cumulative_loss_fraction_start"] = ratio(loss, equity)
    return base


def non_hit_attribution(
    attempts: Sequence[Mapping[str, Any]], checkpoints: Sequence[Mapping[str, Any]], *, initial_equity: float, span: int = 20
) -> dict[str, Any]:
    """Report observed PnL of known completed non-hit attempts, without a gate."""
    initial = _finite(initial_equity, "initial_equity")
    if initial <= 0 or isinstance(span, bool) or not isinstance(span, int) or span <= 0:
        raise AttributionError("initial_equity and span must be positive")
    parsed: list[dict[str, Any]] = []
    identities: set[str] = set()
    previous_entry = 0
    count = len(checkpoints)
    if count == 0:
        raise AttributionError("at least one valuation checkpoint is required")
    for item in attempts:
        if not isinstance(item, Mapping):
            raise AttributionError("attempt must be a mapping")
        identity = _id(item.get("id"))
        entry = item.get("entry_index")
        exit_index = item.get("exit_index")
        hit = item.get("hit")
        if identity in identities or isinstance(entry, bool) or not isinstance(entry, int) or entry < 1 or entry <= previous_entry or entry >= count:
            raise AttributionError("attempt IDs and entry indices must be unique and strictly ordered in bounds")
        if "hit" not in item or (hit is not None and not isinstance(hit, bool)):
            raise AttributionError("attempt hit must be bool or None")
        if exit_index is None:
            if hit is not None:
                raise AttributionError("only unknown attempts may remain open")
        elif isinstance(exit_index, bool) or not isinstance(exit_index, int) or exit_index < entry or exit_index >= count:
            raise AttributionError("attempt exit index must be in bounds")
        identities.add(identity)
        previous_entry = entry
        captured = item.get("captured_pnl_twd")
        if captured is not None:
            captured = _finite(captured, "captured PnL")
        if hit is True and captured is not None and captured <= 0:
            raise AttributionError("a hit requires positive actually captured PnL")
        parsed.append({"id": identity, "entry": entry, "exit": exit_index, "hit": hit, "captured": captured})
    points: list[dict[str, Any]] = []
    previous_date: datetime | None = None
    for index, item in enumerate(checkpoints):
        if not isinstance(item, Mapping) or not isinstance(item.get("attempt_pnl"), Mapping):
            raise AttributionError("checkpoint must contain an attempt_pnl mapping")
        try:
            observed = datetime.fromisoformat(str(item.get("date")))
        except ValueError as exc:
            raise AttributionError("checkpoint date must be ISO") from exc
        if previous_date is not None:
            try:
                if observed < previous_date:
                    raise AttributionError("checkpoint dates must be nondecreasing")
            except TypeError as exc:
                raise AttributionError("checkpoint dates must be mutually comparable") from exc
        previous_date = observed
        equity_value = item.get("equity")
        equity = None if equity_value is None else _finite(equity_value, "checkpoint equity", nonnegative=True)
        pnl: dict[str, float | None] = {}
        for raw_id, value in item["attempt_pnl"].items():
            identity = _id(raw_id, "checkpoint attempt id")
            if identity not in identities or identity in pnl:
                raise AttributionError("checkpoint PnL IDs must match attempts")
            pnl[identity] = None if value is None else _finite(value, "attempt PnL")
        complete_pnl = set(pnl) == identities and all(value is not None for value in pnl.values())
        if complete_pnl and equity is not None:
            expected = _sum([initial] + [value for value in pnl.values() if value is not None], "account equity reconciliation")
            if not math.isclose(equity, expected, rel_tol=0.0, abs_tol=1e-8):
                raise AttributionError("account equity does not reconcile with initial equity and all attempt PnL")
        points.append({"equity": equity, "attempt_pnl": pnl, "index": index, "complete_pnl": complete_pnl})
    classification_reasons: dict[str, str] = {}
    for item in parsed:
        known_after_exit: float | None = None
        for index, point in enumerate(points):
            value = point["attempt_pnl"].get(item["id"])
            if index < item["entry"] and value not in (None, 0.0):
                raise AttributionError("PnL before entry must be zero")
            if item["exit"] is not None and index >= item["exit"] and value is not None:
                if known_after_exit is None:
                    known_after_exit = value
                elif not math.isclose(value, known_after_exit, rel_tol=0.0, abs_tol=1e-8):
                    raise AttributionError("closed attempt PnL must remain constant after exit")
        if item["hit"] is True:
            settled_path = [point["attempt_pnl"].get(item["id"]) for point in points[item["exit"] :]]
            if known_after_exit is not None and known_after_exit <= 0:
                raise AttributionError("a hit cannot have nonpositive closed economic PnL")
            if item["captured"] is None or any(value is None for value in settled_path):
                item["hit"] = None
                classification_reasons[item["id"]] = "declared hit lacks captured or complete closed PnL evidence"
            elif known_after_exit is not None and item["captured"] > known_after_exit + 1e-8:
                raise AttributionError("captured PnL exceeds closed economic PnL")
    known = [item for item in parsed if item["hit"] is False and item["exit"] is not None]
    unknown = [item["id"] for item in parsed if item["hit"] is None]

    def make(items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            return {
                "status": "unavailable",
                "attempt_ids": [],
                "reason": "no known completed non-hit attempts",
                "net_pnl_twd": None,
                "worst_cumulative_loss_twd": None,
                "peak_to_trough_erosion_twd": None,
                "net_fraction_initial": None,
                "peak_to_trough_fraction_start": None,
                "peak_to_trough_fraction_initial": None,
            }
        return _metric([x["id"] for x in items], items[0]["entry"] - 1, max(x["exit"] for x in items), points, initial)

    whole = _metric([item["id"] for item in known], 0, len(points) - 1, points, initial) if known else make([])
    if whole["status"] == "ok" and unknown:
        whole["status"] = "partial"
        whole["reason"] = "known non-hit subset only; unresolved attempts are reported separately"
    unclassified = _metric(unknown, 0, len(points) - 1, points, initial) if unknown else make([])
    if unclassified["status"] == "ok":
        unclassified.update(status="partial", reason="unclassified PnL, not completed non-hit evidence")
    elif not unknown:
        unclassified["reason"] = "no unclassified attempts"
    runs: list[dict[str, Any]] = []
    block: list[dict[str, Any]] = []
    for item in parsed + [{"hit": True}]:
        if item.get("hit") is False and item.get("exit") is not None:
            block.append(item)
        else:
            if block:
                runs.append(make(block))
                block = []
    windows: list[dict[str, Any]] = []
    potential_unknown = False
    for start in range(max(0, len(parsed) - span + 1)):
        block = parsed[start : start + span]
        if len(block) != span:
            continue
        if any(x["hit"] is None for x in block):
            if not any(x["hit"] is True for x in block):
                potential_unknown = True
            continue
        if all(x["hit"] is False and x["exit"] is not None for x in block):
            windows.append(make(block))
    if len(parsed) < span:
        summary_status = "insufficient_windows"
    elif potential_unknown or any(x["status"] != "ok" for x in windows):
        summary_status = "unavailable"
    elif windows:
        summary_status = "ok"
    else:
        summary_status = "no_eligible_windows"
    summary: dict[str, Any] = {"status": summary_status, "worst_peak_to_trough_fraction_start": None}
    if summary_status != "ok":
        summary["reason"] = {
            "insufficient_windows": "fewer attempts than the requested span",
            "no_eligible_windows": "every full-span window contains a known hit",
            "unavailable": "unresolved classifications or missing PnL can conceal the worst window",
        }[summary_status]
    if summary_status == "ok":
        summary["worst_peak_to_trough_fraction_start"] = (
            max(x["peak_to_trough_fraction_start"] for x in windows if x["peak_to_trough_fraction_start"] is not None)
            if all(x["peak_to_trough_fraction_start"] is not None for x in windows)
            else None
        )
        if summary["worst_peak_to_trough_fraction_start"] is None:
            summary.update(status="unavailable", reason="missing or zero start equity")
    return {
        "metric": "non_hit_attribution.v1",
        "attribution_only": True,
        "span": span,
        "classification_complete": not unknown,
        "classification_reasons": classification_reasons,
        "whole_study": whole,
        "unclassified_attribution": unclassified,
        "runs": runs,
        "windows": windows,
        "window_summary": summary,
        "unknown_attempt_ids": unknown,
    }
