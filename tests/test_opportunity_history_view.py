from __future__ import annotations

from copy import deepcopy
from itertools import product
from typing import Any

import pytest

from research_core.opportunity_history_catalog import gain_at
from research_core.opportunity_history_view import GainIndex, build_frame

DATES = [f"2020-01-{day:02d}" for day in range(1, 6)]


@pytest.mark.parametrize("runs", [None, [0, 0, 1, 1, 1]])
def test_gain_index_matches_shared_priority_for_all_endpoints(runs: list[int] | None) -> None:
    for middle, flags, barrier in product(
        [11.0, None, 0.0, -1.0, float("nan"), float("inf"), 1000.0],
        [{}, {"0": ["base"]}, {"1": ["early"]}, {"2": ["middle"]}, {"4": ["late"]}],
        [[], [{"index": 0}], [{"calendar_index": 1}], [{"ex_date": DATES[2]}]],
    ):
        series = {"raw": [10.0, 10.5, middle, 11.5, 12.0], "adjusted": [10.0, 10.5, middle, 11.5, 12.0], "numeric_flags": flags, "action_barriers": barrier}
        if runs is not None:
            series["source_run_indices"] = runs
        cache = GainIndex(series, DATES)
        for base in range(-1, 7):
            for index in range(-1, 7):
                assert cache.at(base, index) == gain_at(series, DATES, base, index)


def test_endpoint_and_chronological_priority() -> None:
    series = {"raw": [10, 11, 12, None, 14], "adjusted": [10, 11, 12, None, 14], "numeric_flags": {"1": ["invalid"]}, "action_barriers": [{"index": 2}]}
    cache = GainIndex(series, DATES)
    assert cache.at(0, 3) == (None, "missing_or_invalid_endpoint")
    assert cache.at(0, 4) == (None, "numeric_blocker")
    assert cache.at(1, 4) == (None, "numeric_blocker")
    assert cache.at(2, 4) == (None, "missing_continuity")


def test_native_runs_skip_python_log_and_keep_final_jump_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    series = {
        "raw": [1, 1, 10000, 10000, 10000],
        "adjusted": [1, 1, 10000, 10000, 10000],
        "source_run_indices": [0, 0, 1, 1, 1],
        "numeric_flags": {"4": ["late"]},
    }

    def unexpected_log(value: float) -> float:
        raise AssertionError("Native run indices must not be rederived")

    monkeypatch.setattr("research_core.opportunity_history_view.math.log", unexpected_log)
    cache = GainIndex(series, DATES)
    assert cache.at(0, 3) == (None, "continuity_jump")
    assert cache.at(0, 4) == (None, "numeric_blocker")
    assert cache.at(2, 3) == (0.0, None)
    saved = cache._cache[0]
    assert cache.at(0, 1) == (0.0, None)
    assert cache._cache[0] is saved


def _catalog() -> dict[str, Any]:
    series = {
        "security_id": "stock:1234",
        "series_id": "prices:1234",
        "raw": [10, 11, 12, 13, 14],
        "adjusted": [10, 11, 12, 13, 14],
        "source_run_indices": [0] * 5,
    }
    wave = {
        "id": "wave:a",
        "security_id": "stock:1234",
        "start": 0,
        "peak": 4,
        "end": None,
        "observedThrough": 4,
        "scale": "large",
        "gain": 40.0,
        "leftCensored": True,
        "rightCensored": True,
    }
    interval = {
        "wave_id": wave["id"],
        "series_id": series["series_id"],
        "start_index": 2,
        "end_exclusive_index": 4,
        "gain_base_index": 0,
        "earliest_candidate_id": "candidate:reference",
    }
    return {
        "id": "catalog:test",
        "dates": DATES,
        "securities": {"1234": {"security_id": series["security_id"], "name": None, "stock_opportunity_eligible": True}},
        "series": {"1234": series},
        "intervals": {series["security_id"]: [interval]},
        "waves": {wave["id"]: wave},
        "classifications": {},
        "gains": {"1234": GainIndex(series, DATES)},
        "native_display": {
            "1234": {
                ("segments", "balanced"): {
                    "segments": [
                        {"start": 0, "end": 1, "phase": "fast"},
                        {"start": 2, "end": 3, "phase": "rising"},
                    ],
                    "launches": [{"catalogId": "candidate:reference", "index": 1, "rangeStart": 1, "rangeEnd": 2, "kind": "breakout", "outcome": "confirmed"}],
                    "waves": [],
                }
            }
        },
    }


def test_frame_uses_wave_base_and_separates_future_peak() -> None:
    catalog = _catalog()
    # Preserve producer order and select at most one row even for overlapping input.
    catalog["intervals"]["stock:1234"].append(deepcopy(catalog["intervals"]["stock:1234"][0]))
    frame = build_frame(catalog, DATES[2])
    assert frame["schema"] == "opportunity-history-web.v1"
    assert frame["catalogId"] == catalog["id"]
    assert len(frame["rows"]) == 1
    row = frame["rows"][0]
    assert row["gain"] == pytest.approx(20)
    assert row["peakGain"] == pytest.approx(40)
    assert row["peakDate"] == DATES[4]
    assert row["start"] == DATES[0]
    assert row["endConfirmedAt"] is None
    assert row["observedThrough"] == DATES[4]
    assert row["name"] == "1234"
    assert row["raw"] == row["adjusted"] == 12
    assert row["industry"] == {"id": "unknown", "label": "分類待補", "basis": "unknown", "snapshotAt": None}
    assert row["earliestCandidateId"] == "candidate:reference"
    assert row["phase"] == "slow"
    assert row["sourcePhase"] == "rising"
    assert row["launchCandidate"] == {"date": DATES[1], "rangeFrom": DATES[1], "rangeUntil": DATES[2], "kind": "breakout", "outcome": "confirmed"}
    assert row["sparkline"] == [{"date": DATES[0], "adjusted": 10}, {"date": DATES[1], "adjusted": 11}, {"date": DATES[2], "adjusted": 12}]
    assert row["phases"] == [{"from": DATES[0], "until": DATES[1], "phase": "rising"}, {"from": DATES[2], "until": DATES[2], "phase": "slow"}]
    assert build_frame(catalog, DATES[1])["rows"] == []
    assert build_frame(catalog, DATES[4])["rows"] == []


def test_unknown_gain_remains_member_and_classification_is_current_snapshot() -> None:
    catalog = _catalog()
    catalog["series"]["1234"]["numeric_flags"] = {"1": ["blocked"]}
    catalog["gains"]["1234"] = GainIndex(catalog["series"]["1234"], DATES)
    catalog["classifications"]["1234"] = {
        "label": "Ignore informal label",
        "official_industry_snapshot": {"label": "半導體業", "fetched_at": "2026-10-05", "historical_validity": "not_established"},
    }
    row = build_frame(catalog, DATES[2])["rows"][0]
    assert row["gain"] is None
    assert row["reason"] == "numeric_blocker"
    assert row["industry"] == {"id": "半導體業", "label": "半導體業", "basis": "current-snapshot", "snapshotAt": "2026-10-05"}


@pytest.mark.parametrize("barrier_index", [2, 3])
def test_peak_gain_is_unknown_across_action_barrier(barrier_index: int) -> None:
    catalog = _catalog()
    catalog["series"]["1234"]["action_barriers"] = [{"index": barrier_index}]
    catalog["gains"]["1234"] = GainIndex(catalog["series"]["1234"], DATES)
    row = build_frame(catalog, DATES[2])["rows"][0]
    assert row["peakGain"] is None
    assert row["peakDate"] == DATES[4]
    assert catalog["waves"]["wave:a"]["gain"] == 40.0
    if barrier_index <= 2:
        assert row["gain"] is None
        assert row["reason"] == "action_barrier"
    else:
        assert row["gain"] == pytest.approx(20)
        assert row["reason"] is None


def test_nonstock_is_excluded_and_missing_wave_hard_fails() -> None:
    catalog = _catalog()
    catalog["securities"]["1234"]["stock_opportunity_eligible"] = False
    assert build_frame(catalog, DATES[2])["rows"] == []
    catalog["securities"]["1234"]["stock_opportunity_eligible"] = True
    catalog["waves"] = {}
    with pytest.raises(KeyError):
        build_frame(catalog, DATES[2])


def test_frame_rejects_identity_mismatch_and_noncalendar_dates() -> None:
    catalog = _catalog()
    with pytest.raises(ValueError):
        build_frame(catalog, "2020-01-31")
    catalog["waves"]["wave:a"]["security_id"] = "stock:other"
    with pytest.raises(ValueError, match="identity mismatch"):
        build_frame(catalog, DATES[2])


def test_complete_frame_contract_with_confirmed_end_and_native_null_observed_through() -> None:
    catalog = _catalog()
    catalog["securities"]["1234"]["name"] = "Example issuer"
    wave = catalog["waves"]["wave:a"]
    wave.update({"end": 4, "observedThrough": None, "leftCensored": False, "rightCensored": False})
    catalog["classifications"]["1234"] = {
        "official_industry_snapshot": {
            "label": "航運業",
            "fetched_at": "2026-07-14T01:54:57+08:00",
            "historical_validity": "not_established",
        },
    }
    assert build_frame(catalog, DATES[2]) == {
        "schema": "opportunity-history-web.v1",
        "catalogId": "catalog:test",
        "date": "2020-01-03",
        "rows": [
            {
                "securityId": "stock:1234",
                "code": "1234",
                "name": "Example issuer",
                "seriesId": "prices:1234",
                "waveId": "wave:a",
                "start": "2020-01-01",
                "peakDate": "2020-01-05",
                "endConfirmedAt": "2020-01-05",
                "observedThrough": None,
                "leftCensored": False,
                "rightCensored": False,
                "scale": "large",
                "gain": pytest.approx(20),
                "growth": {
                    "schema": "wave-growth.v1",
                    "startDate": "2020-01-01",
                    "observationDate": "2020-01-03",
                    "yearDays": 365.25,
                    "elapsedDays": 2,
                    "elapsedYears": pytest.approx(2 / 365.25),
                    "totalGainPct": pytest.approx(20),
                    "annualizedGainPct": None,
                    "sizingGainPct": pytest.approx(20),
                    "basis": "actual",
                    "reason": None,
                },
                "peakGain": pytest.approx(40.0),
                "raw": 12,
                "adjusted": 12,
                "reason": None,
                "industry": {"id": "航運業", "label": "航運業", "basis": "current-snapshot", "snapshotAt": "2026-07-14T01:54:57+08:00"},
                "earliestCandidateId": "candidate:reference",
                "phase": "slow",
                "sourcePhase": "rising",
                "launchCandidate": {"date": "2020-01-02", "rangeFrom": "2020-01-02", "rangeUntil": "2020-01-03", "kind": "breakout", "outcome": "confirmed"},
                "startAdjusted": 10,
                "launchAdjusted": 11,
                "launchGain": pytest.approx((12 / 11 - 1) * 100),
                "sparkline": [
                    {"date": "2020-01-01", "adjusted": 10},
                    {"date": "2020-01-02", "adjusted": 11},
                    {"date": "2020-01-03", "adjusted": 12},
                ],
                "phases": [
                    {"from": "2020-01-01", "until": "2020-01-02", "phase": "rising"},
                    {"from": "2020-01-03", "until": "2020-01-03", "phase": "slow"},
                ],
            }
        ],
    }


def test_gain_cache_stores_only_first_blocker_and_retains_endpoint_run_comparison() -> None:
    series = {"raw": [1] * 100, "adjusted": [1] * 100, "source_run_indices": [0, 1, 0] + [0] * 97, "numeric_flags": {"99": ["flag"]}}
    cache = GainIndex(series, [str(index) for index in range(100)])
    assert cache.at(0, 1) == (None, "continuity_jump")
    # Run identity is compared at each endpoint, never made a persistent blocker.
    assert cache.at(0, 2) == (0.0, None)
    assert cache._cache == {0: (99, "numeric_blocker")}
    assert cache.at(0, 99) == (None, "numeric_blocker")
