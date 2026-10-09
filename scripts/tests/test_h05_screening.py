"""Synthetic H05 stopping/paired-assumption rules, without market inputs."""

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

TASK = Path(__file__).resolve().parents[2] / "tasks/20261005-relative-strength-holding"
SPEC = importlib.util.spec_from_file_location("h05_screening_test", TASK / "screening.py")
assert SPEC and SPEC.loader
screen = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = screen
SPEC.loader.exec_module(screen)


def report(net: float = 0.2, dd: float = 0.1, erosion: float | None = 0.05, hits: int = 2) -> dict[str, Any]:
    attempts = [{"disposition": "hit", "closed": True, "unpaid_cash_cents": 0, "net_paid_cash_cents": 100} for _ in range(hits)]
    attempts += [{"disposition": "non_hit", "closed": True, "unpaid_cash_cents": 0, "net_paid_cash_cents": -50}]
    return {
        "schema": "h05-close-measurement.v1",
        "initial_cash_cents": 200_000_000,
        "hit_threshold": "1/2",
        "attempt_order": "first_buy_event_index",
        "attempts": attempts,
        "disposition_counts": {"hit": hits, "non_hit": 1, "unknown": 0},
        "account": {"net_return": net, "close_max_drawdown": dd},
        "non_hit_attribution": {"whole_study": {"status": "unavailable" if erosion is None else "ok", "peak_to_trough_fraction_initial": erosion}},
    }


def paths() -> dict[str, Any]:
    return {arm.identity: {profile: report() for profile in screen.PROFILES} for arm in screen.ARMS}


def test_two_baselines_stop_without_a_lead_and_keep_shared_limitations():
    result = screen.assess({"baseline": {profile: report(net=-0.1, hits=1) for profile in screen.PROFILES}})
    assert result["scheduled_path_count"] == 2 and result["next_stage"] is None
    assert result["baseline"]["shared_absolute_limitations_not_candidate_rejections"] == ["positive_account_return", "multiple_captured_hits"]
    assert result["status"] == "no_baseline_account_lead_established"
    assert not result["strategy_accepted"]


def test_missing_path_is_not_zero_or_candidate_failure():
    result = screen.assess({"baseline": {profile: None for profile in screen.PROFILES}})
    assert result["evaluated_path_count"] == 0
    assert result["baseline"]["profiles"]["rs-ma20"]["metrics"] is None
    assert not result["baseline"]["shared_absolute_limitations_not_candidate_rejections"]


def test_shared_absolute_failures_do_not_erase_a_relative_lead():
    pair = {"rs-ma20": report(net=-0.01, hits=1), "rs-ma60": report(net=-0.1, hits=1)}
    result = screen.baseline_leads(pair)
    assert result["run_remaining_arms"]
    assert result["paired_relative_leads"] == ["rs-ma20"]
    assert not any(row["lead"] for row in result["profiles"].values())


def test_a_single_lead_requires_both_profiles_in_all_arms():
    one = {"baseline": {"rs-ma20": report(), "rs-ma60": report(net=-0.1)}}
    assert screen.baseline_leads(one["baseline"])["run_remaining_arms"]
    with pytest.raises(ValueError, match="stopping rule"):
        screen.assess(one)
    all_paths = paths()
    all_paths["late-cash"].pop("rs-ma60")
    with pytest.raises(ValueError, match="both profiles"):
        screen.assess(all_paths)


def test_strict_pareto_dominance_across_every_arm_only():
    values = paths()
    values["joint"]["rs-ma60"] = report(net=0.3)
    result = screen.assess(values)
    assert result["profiles"]["rs-ma20"]["dominated_on_known_non_hit_metrics"]
    assert result["profiles"]["rs-ma60"]["eligible_for_next_investigation"]
    values["baseline"]["rs-ma20"] = report(erosion=0.01)
    result = screen.assess(values)
    assert all(row["eligible_for_next_investigation"] for row in result["profiles"].values())


def test_shared_negative_sensitivity_remains_shared_not_a_candidate_only_rejection():
    values = paths()
    for profile in screen.PROFILES:
        values["joint"][profile] = report(net=-0.01)
    result = screen.assess(values)
    assert result["shared_negative_return_arms_not_candidate_rejections"] == ["joint"]
    assert not any(row["eligible_for_next_investigation"] for row in result["profiles"].values())


def test_unknown_erosion_and_incomplete_path_prevent_dominance_claim():
    values = paths()
    values["late-cash"]["rs-ma60"] = None
    values["joint"]["rs-ma20"] = report(erosion=None)
    result = screen.assess(values)
    for row in result["profiles"].values():
        assert row["dominated_on_known_non_hit_metrics"] is None
        assert row["dominance_unavailable_arms"] == ["late-cash", "joint"]
        assert not row["eligible_for_next_investigation"]


@pytest.mark.parametrize("mutation", ["nan", "count", "unpaid", "definition", "unregistered"])
def test_incompatible_or_nonfinite_measurements_fail(mutation: str):
    values = deepcopy(paths())
    row = values["baseline"]["rs-ma20"]
    if mutation == "nan":
        row["account"]["net_return"] = float("nan")
    elif mutation == "count":
        row["disposition_counts"]["hit"] = 999
    elif mutation == "unpaid":
        row["attempts"][0]["unpaid_cash_cents"] = 1
    elif mutation == "definition":
        row["hit_threshold"] = "1/10"
    else:
        values["optimized-after-results"] = values["joint"]
    with pytest.raises(ValueError):
        screen.assess(values)


def test_real_empty_nonhit_shape_is_unavailable_not_zero_or_a_crash():
    values = paths()
    row = values["joint"]["rs-ma20"]
    row["attempts"] = [item for item in row["attempts"] if item["disposition"] == "hit"]
    row["disposition_counts"]["non_hit"] = 0
    row["non_hit_attribution"]["whole_study"] = {
        "status": "unavailable",
        "attempt_ids": [],
        "reason": "no attempts in this classification",
        "net_cents": None,
        "worst_loss_cents": None,
        "peak_to_trough_cents": None,
    }
    result = screen.assess(values)
    assert result["profiles"]["rs-ma20"]["dominance_unavailable_arms"] == ["joint"]
    assert result["profiles"]["rs-ma20"]["dominated_on_known_non_hit_metrics"] is None
    metrics = screen._metrics(row)
    assert metrics["known_non_hit_erosion"] is None
    assert metrics["non_hit_attribution_reason"] == "no attempts in this classification"


def test_partial_known_subset_cannot_supply_relative_lead_or_dominance():
    values = paths()
    for pair in values.values():
        row = pair["rs-ma20"]
        row["account"]["net_return"] = 0.3
        row["attempts"].append({"disposition": "unknown", "closed": False, "unpaid_cash_cents": 0, "net_paid_cash_cents": -10})
        row["disposition_counts"]["unknown"] = 1
        row["non_hit_attribution"]["whole_study"].update(status="partial", reason="known settled non-hit subset only")
    result = screen.assess(values)
    assert result["baseline"]["paired_relative_leads"] == []
    metrics = result["baseline"]["profiles"]["rs-ma20"]["metrics"]
    assert metrics["known_non_hit_erosion"] == 0.05  # Descriptive evidence is retained.
    assert metrics["non_hit_attribution_status"] == "partial"
    for profile in result["profiles"].values():
        assert profile["dominated_on_known_non_hit_metrics"] is None
        assert not profile["eligible_for_next_investigation"]
        assert profile["dominance_unavailable_arms"] == [arm.identity for arm in screen.ARMS]
