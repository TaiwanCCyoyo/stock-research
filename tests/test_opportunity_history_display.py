from __future__ import annotations

from typing import Any, cast

import pytest

from research_core.opportunity_history_display import _sparkline, augment_frame_row, build_directory, build_options
from research_core.opportunity_history_view import GainIndex
from research_core.wave_growth import GrowthMetric

DATES = [f"2020-01-0{i}" for i in range(1, 6)]


def _growth(row: dict[str, object], field: str = "growth") -> GrowthMetric:
    value = row[field]
    assert isinstance(value, dict)
    return cast(GrowthMetric, value)


def _catalog():
    series = {
        "security_id": "stock:1234",
        "series_id": "prices:1234",
        "raw": [10, 11, 12, 13, 14],
        "adjusted": [10, 11, 12, 13, 14],
        "source_run_indices": [0, 0, 0, 0, 0],
    }
    wave = {
        "id": "wave:a",
        "security_id": "stock:1234",
        "start": 0,
        "peak": 4,
        "end": None,
        "observedThrough": 4,
        "scale": "large",
        "leftCensored": False,
        "rightCensored": True,
    }
    candidate = {"catalogId": "candidate:a", "id": "native:a", "index": 1, "rangeStart": 1, "rangeEnd": 2, "kind": "breakout", "outcome": "confirmed"}
    native_wave = {"id": "native:wave", "start": 0, "peak": 4, "end": None, "observedThrough": 4, "scale": "large"}
    return {
        "id": "catalog:test",
        "dates": DATES,
        "securities": {"1234": {"security_id": "stock:1234", "name": "Example issuer", "stock_opportunity_eligible": True}},
        "series": {"1234": series},
        "intervals": {
            "stock:1234": [{"wave_id": "wave:a", "start_index": 1, "end_exclusive_index": 4, "gain_base_index": 0, "earliest_candidate_id": "candidate:a"}]
        },
        "waves": {"wave:a": wave},
        "classifications": {},
        "gains": {"1234": GainIndex(series, DATES)},
        "native_display": {
            "1234": {
                ("segments", "balanced"): {
                    "waves": [native_wave],
                    "segments": [{"start": 0, "end": 4, "phase": "fast"}],
                    "launches": [candidate],
                    "launchIndices": [1],
                },
                ("segments", "coarse"): {"waves": [native_wave], "segments": [], "launches": [candidate], "launchIndices": [1]},
            }
        },
    }


def _confirm_wave_end(catalog: dict[str, Any]) -> None:
    wave = catalog["waves"]["wave:a"]
    wave.update({"peak": 3, "end": 4, "rightCensored": False})
    native_wave = catalog["native_display"]["1234"][("segments", "balanced")]["waves"][0]
    native_wave.update({"peak": 3, "end": 4})


def test_directory_projects_every_saved_interval_and_keeps_gain_continuity():
    catalog = _catalog()
    _confirm_wave_end(catalog)
    result = build_directory(catalog)
    assert result["method"] == "segments"
    assert result["methodScale"] == "balanced"
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["representativeFrom"] == DATES[1]
    assert row["representativeUntilExclusive"] == DATES[4]
    assert row["endConfirmedAt"] == DATES[4]
    assert row["gainAtEnd"] == pytest.approx(30.0)
    assert row["gainAtEndDate"] == DATES[3]
    growth = _growth(row, "growthAtEnd")
    assert growth["observationDate"] == DATES[3]
    assert growth["sizingGainPct"] == pytest.approx(30.0)
    assert growth["basis"] == "actual"
    assert row["peakGain"] == pytest.approx(30.0)
    assert row["launchCandidate"]["date"] == DATES[1]


def test_directory_exclusive_endpoint_after_calendar_uses_next_calendar_day():
    catalog = _catalog()
    catalog["intervals"]["stock:1234"][0]["end_exclusive_index"] = len(DATES)
    row = build_directory(catalog)["rows"][0]
    assert row["representativeUntilExclusive"] == "2020-01-06"
    assert row["gainAtEnd"] is None
    assert row["gainAtEndDate"] is None
    assert _growth(row, "growthAtEnd")["basis"] == "unknown"


def test_directory_uses_confirmed_wave_end_for_disjoint_representative_intervals():
    catalog = _catalog()
    _confirm_wave_end(catalog)
    catalog["intervals"]["stock:1234"] = [
        {"wave_id": "wave:a", "start_index": 1, "end_exclusive_index": 2, "gain_base_index": 0},
        {"wave_id": "wave:a", "start_index": 3, "end_exclusive_index": 4, "gain_base_index": 0},
    ]

    rows = build_directory(catalog)["rows"]
    assert len(rows) == 2
    assert rows[0]["representativeUntilExclusive"] != rows[1]["representativeUntilExclusive"]
    assert {row["endConfirmedAt"] for row in rows} == {DATES[4]}
    assert [row["gainAtEnd"] for row in rows] == pytest.approx([30.0, 30.0])

    catalog["series"]["1234"]["action_barriers"] = [{"index": 2}]
    catalog["gains"]["1234"] = GainIndex(catalog["series"]["1234"], DATES)
    rows_after_barrier = build_directory(catalog)["rows"]
    assert [row["gainAtEnd"] for row in rows_after_barrier] == [None, None]
    assert [_growth(row, "growthAtEnd")["basis"] for row in rows_after_barrier] == ["unknown", "unknown"]


def test_sparkline_breaks_same_run_numeric_and_action_barriers():
    for blocker, expected in (
        ({"numeric_flags": {"2": ["invalid"]}}, [10, 11, None, None, 14]),
        ({"action_barriers": [{"index": 2}]}, [10, 11, None, 13, 14]),
    ):
        catalog = _catalog()
        catalog["series"]["1234"]["source_run_indices"] = [0] * len(DATES)
        catalog["series"]["1234"].update(blocker)
        catalog["gains"]["1234"] = GainIndex(catalog["series"]["1234"], DATES)
        points = _sparkline(catalog, "1234", 0, 4)
        assert [point["adjusted"] for point in points] == expected


def test_options_compare_only_saved_balanced_and_coarse_representatives():
    result = build_options(_catalog(), DATES[2])
    assert result["date"] == DATES[2]
    assert len(result["rows"]) == 6
    counts = {(row["methodScale"], row["condition"]): row["count"] for row in result["rows"]}
    assert counts[("balanced", "all")] == 1
    assert counts[("balanced", "peak_gain_100")] == 0
    assert counts[("balanced", "candidate_started")] == 1
    assert counts[("coarse", "all")] == 1


def test_options_reject_date_outside_saved_calendar():
    with pytest.raises(ValueError, match="outside"):
        build_options(_catalog(), "2020-02-01")


def test_launch_gain_has_its_own_anchor_and_respects_continuity():
    catalog = _catalog()
    row = {
        "code": "1234",
        "waveId": "wave:a",
        "earliestCandidateId": "candidate:a",
        "start": DATES[0],
        "gain": 30,
        "leftCensored": False,
    }
    augment_frame_row(catalog, row, 3)
    assert row["startAdjusted"] == 10
    assert row["launchAdjusted"] == 11
    assert row["launchGain"] == pytest.approx((13 / 11 - 1) * 100)
    growth = _growth(row)
    assert growth["sizingGainPct"] == pytest.approx(30.0)
    assert growth["basis"] == "actual"
    catalog["series"]["1234"]["action_barriers"] = [{"index": 2}]
    catalog["gains"]["1234"] = GainIndex(catalog["series"]["1234"], DATES)
    row["gain"] = None
    augment_frame_row(catalog, row, 3)
    assert row["launchGain"] is None
    growth = _growth(row)
    assert growth["basis"] == "unknown"
    assert growth["reason"] == "unknown-gain"
