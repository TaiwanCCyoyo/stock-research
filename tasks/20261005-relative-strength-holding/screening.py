"""Fixed H05 model arms and a provisional development screen, never acceptance."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger(__name__)
PROFILES = ("rs-ma20", "rs-ma60")


@dataclass(frozen=True)
class Assumption:
    identity: str
    cost: str
    cash_delay_days: int
    allocation: str


ARMS = (
    Assumption("baseline", "baseline", 45, "native"),
    Assumption("high-friction", "high-friction", 45, "native"),
    Assumption("late-cash", "baseline", 90, "native"),
    Assumption("partial-allocation", "baseline", 45, "half"),
    Assumption("joint", "high-friction", 90, "half"),
)


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite numeric measurement")
    return float(value)


def _metrics(report: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    if report.get("schema") != "h05-close-measurement.v1" or report.get("initial_cash_cents") != 200_000_000:
        raise ValueError("screen requires H05 NT$2m measurement")
    if report.get("hit_threshold") != "1/2" or report.get("attempt_order") != "first_buy_event_index":
        raise ValueError("screen requires the fixed hit and attempt-order definitions")
    attempts = report["attempts"]
    if any(row["disposition"] not in {"hit", "non_hit", "unknown"} for row in attempts):
        raise ValueError("unknown disposition vocabulary")
    counts = {state: sum(row["disposition"] == state for row in attempts) for state in ("hit", "non_hit", "unknown")}
    if counts != report["disposition_counts"]:
        raise ValueError("saved disposition counts disagree with attempts")
    settled = [row for row in attempts if row["disposition"] != "unknown"]
    if any(not row["closed"] or row["unpaid_cash_cents"] != 0 for row in settled):
        raise ValueError("known disposition requires a settled closed attempt")
    if any(type(row["net_paid_cash_cents"]) is not int for row in settled):
        raise ValueError("paid profit must use integer cents")
    attribution = report["non_hit_attribution"]["whole_study"]
    erosion_status = attribution["status"]
    if erosion_status not in {"ok", "partial", "unavailable"}:
        raise ValueError("unknown non-hit attribution status")
    erosion = attribution.get("peak_to_trough_fraction_initial")
    if erosion_status != "unavailable" and erosion is None:
        raise ValueError("available non-hit attribution requires a measurement")
    return {
        "net_return": _number(report["account"]["net_return"], "net return"),
        "drawdown": _number(report["account"]["close_max_drawdown"], "drawdown"),
        "known_non_hit_erosion": None if erosion is None else _number(erosion, "non-hit erosion"),
        "non_hit_attribution_status": erosion_status,
        "non_hit_attribution_reason": attribution.get("reason"),
        "captured_hits": counts["hit"],
        "unknown_attempts": counts["unknown"],
        "settled_net_paid_cents": sum(row["net_paid_cash_cents"] for row in settled),
    }


def baseline_leads(reports: Mapping[str, Mapping[str, Any] | None]) -> dict[str, Any]:
    """A None report means an explicitly incomplete path, not a zero return."""
    if set(reports) != set(PROFILES):
        raise ValueError("both fixed baseline profiles are required")
    rows: dict[str, dict[str, Any]] = {}
    for profile in PROFILES:
        metrics = _metrics(reports[profile])
        gates = (
            None
            if metrics is None
            else {
                "positive_account_return": metrics["net_return"] > 0,
                "multiple_captured_hits": metrics["captured_hits"] >= 2,
                "positive_settled_paid_profit": metrics["settled_net_paid_cents"] > 0,
            }
        )
        rows[profile] = {"metrics": metrics, "requirements": gates, "lead": gates is not None and all(gates.values())}
    control = rows["rs-ma60"]["requirements"]
    candidate = rows["rs-ma20"]["requirements"]
    shared = [] if control is None or candidate is None else [key for key in control if not control[key] and not candidate[key]]
    relative_leads = []
    for profile in PROFILES:
        other = next(item for item in PROFILES if item != profile)
        current, reference = rows[profile]["metrics"], rows[other]["metrics"]
        if current is None or reference is None or current["non_hit_attribution_status"] != "ok" or reference["non_hit_attribution_status"] != "ok":
            continue
        improvements = (
            current["net_return"] - reference["net_return"],
            reference["drawdown"] - current["drawdown"],
            reference["known_non_hit_erosion"] - current["known_non_hit_erosion"],
        )
        if all(value >= 0 for value in improvements) and any(value > 0 for value in improvements):
            relative_leads.append(profile)
    return {
        "profiles": rows,
        "paired_relative_leads": relative_leads,
        "run_remaining_arms": any(row["lead"] for row in rows.values()) or bool(relative_leads),
        "shared_absolute_limitations_not_candidate_rejections": shared,
    }


def assess(paths: Mapping[str, Mapping[str, Mapping[str, Any] | None]]) -> dict[str, Any]:
    """Assess only the registered arms; caller retains each incomplete path reason."""
    if "baseline" not in paths or set(paths) - {arm.identity for arm in ARMS}:
        raise ValueError("unregistered/missing assumption arm")
    baseline = baseline_leads(paths["baseline"])
    expected = {arm.identity for arm in ARMS} if baseline["run_remaining_arms"] else {"baseline"}
    if set(paths) != expected:
        raise ValueError("path set does not match the predeclared baseline stopping rule")
    for pair in paths.values():
        if set(pair) != set(PROFILES):
            raise ValueError("each executed arm requires both profiles")
    result: dict[str, Any] = {
        "schema": "h05-assumption-screen.v1",
        "provisional": True,
        "strategy_accepted": False,
        "baseline": baseline,
        "evaluated_path_count": sum(report is not None for pair in paths.values() for report in pair.values()),
        "scheduled_path_count": len(paths) * 2,
        "profiles": {},
        "next_stage": "net_dividend_and_remaining_materiality_only",
    }
    if not baseline["run_remaining_arms"]:
        result["status"] = "no_baseline_account_lead_established"
        result["next_stage"] = None
        LOGGER.info("H05 baseline stopping rule: no complete lead; preserve paired differences and incomplete reasons")
        return result
    values = {arm: {profile: _metrics(report) for profile, report in pair.items()} for arm, pair in paths.items()}
    for profile in PROFILES:
        other = next(item for item in PROFILES if item != profile)
        missing = [arm for arm, pair in values.items() if pair[profile] is None]
        negative = [arm for arm, pair in values.items() if (metrics := pair[profile]) is not None and metrics["net_return"] < 0]
        comparisons: list[float] = []
        unavailable = []
        for arm, pair in values.items():
            current, reference = pair[profile], pair[other]
            if current is None or reference is None or current["non_hit_attribution_status"] != "ok" or reference["non_hit_attribution_status"] != "ok":
                unavailable.append(arm)
                continue
            differences = (
                reference["net_return"] - current["net_return"],
                current["drawdown"] - reference["drawdown"],
                current["known_non_hit_erosion"] - reference["known_non_hit_erosion"],
            )
            comparisons.extend(differences)
        dominated = None if unavailable else all(value >= 0 for value in comparisons) and any(value > 0 for value in comparisons)
        # None is insufficient comparison evidence, never a favorable zero.
        eligible = baseline["profiles"][profile]["lead"] and not missing and not negative and dominated is False
        result["profiles"][profile] = {
            "incomplete_arms": missing,
            "negative_return_arms": negative,
            "dominance_unavailable_arms": unavailable,
            "dominated_on_known_non_hit_metrics": dominated,
            "eligible_for_next_investigation": eligible,
            "remaining_unknown_attempts": {
                arm: metrics["unknown_attempts"] if (metrics := pair[profile]) is not None else None for arm, pair in values.items()
            },
        }
    result["shared_negative_return_arms_not_candidate_rejections"] = [
        arm for arm, pair in values.items() if all(metrics is not None and metrics["net_return"] < 0 for metrics in pair.values())
    ]
    result["status"] = "bounded_screen_complete_not_strategy_acceptance"
    LOGGER.info("H05 assumption screen completed; no strategy approval")
    return result
