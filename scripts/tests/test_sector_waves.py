from __future__ import annotations

from typing import Any

import pytest

from research_core.sector_waves import CatalogBar, SectorWaveError, cluster_waves, compare_peer, detect_episodes, select_wave_winner


def bars(values: list[float], *, flags: dict[int, tuple[str, ...]] | None = None) -> list[CatalogBar]:
    return [CatalogBar(f"2024-01-{index + 1:02d}", value, value * 2, float(index + 1), (flags or {}).get(index, ())) for index, value in enumerate(values)]


def test_detection_exact_multiple_earliest_tied_low_and_peak_before_qualification() -> None:
    result = detect_episodes("1234", bars([10, 10, 15, 25, 20, 20, 18]))
    assert len(result) == 1
    episode = result[0]
    assert episode["security_id"] == "TW:1234"
    assert episode["start_date"] == "2024-01-01"
    assert episode["qualification_date"] == "2024-01-04"
    assert episode["peak_date"] == "2024-01-04"
    assert episode["price_multiple"] == 2.5
    assert episode["confirmation_date"] == "2024-01-07"
    assert episode["end_date"] == episode["peak_date"]


def test_detection_lookback_boundary_reset_and_right_censoring() -> None:
    series = bars([10, 15, 18, 14, 7, 14, 21, 15, 8, 16, 20])
    result = detect_episodes("A", series, lookback_sessions=3)
    assert [(item["start_date"], item["confirmation_date"]) for item in result] == [
        ("2024-01-05", "2024-01-08"),
        ("2024-01-09", None),
    ]
    assert result[-1]["right_censored"] is True
    assert result[-1]["quality_flags"] == ()


def test_default_126_session_boundary_excludes_older_low() -> None:
    from datetime import date, timedelta

    values = [1.0] + [1.5] * 125 + [2.0]
    start = date(2024, 1, 1)
    series = [CatalogBar((start + timedelta(days=i)).isoformat(), p, p, 1.0) for i, p in enumerate(values)]
    assert detect_episodes("A", series) == []


def test_exact_quarter_drawdown_confirms_and_new_search_cannot_use_old_trough() -> None:
    result = detect_episodes("A", bars([10, 20, 15, 25]))
    assert len(result) == 1
    assert result[0]["confirmation_date"] == "2024-01-03"


def test_changed_definition_cannot_reuse_same_event_identity() -> None:
    sample = bars([10, 30, 20])
    baseline = detect_episodes("A", sample)[0]
    changed = detect_episodes("A", sample, qualifying_multiple=2.5)[0]
    assert baseline["episode_id"] != changed["episode_id"]
    assert baseline["definition_id"] != changed["definition_id"]


def test_detection_rejects_invalid_or_duplicate_dates_and_collects_flags() -> None:
    with pytest.raises(SectorWaveError):
        detect_episodes("A", [CatalogBar("2024-01-01", 1, 1, None), CatalogBar("2024-01-01", 2, 2, None)])
    with pytest.raises(SectorWaveError):
        CatalogBar("2024-01-01", 0, 1, None)
    result = detect_episodes("A", bars([1, 2, 3, 1.5], flags={1: ("jump",), 3: ("liquid",)}))
    assert result[0]["quality_flags"] == ("jump", "liquid")


def test_cluster_requires_common_ascent_intersection_and_never_chains_on_onset() -> None:
    episodes: list[dict[str, Any]] = [
        {"episode_id": "a", "security_id": "TW:A", "start_date": "2024-01-01", "peak_date": "2024-04-01", "first_25pct_date": "2024-01-03"},
        {"episode_id": "b", "security_id": "TW:B", "start_date": "2024-03-20", "peak_date": "2024-03-25", "first_25pct_date": "2024-03-21"},
        {"episode_id": "c", "security_id": "TW:C", "start_date": "2024-06-15", "peak_date": "2024-07-01", "first_25pct_date": None},
    ]
    result = cluster_waves("memory", episodes, onset_gap_days=90)
    assert [wave["episode_ids"] for wave in result] == [["a", "b"], ["c"]]
    assert result[0]["earliest_qualifying_25pct"] == {"security_id": "TW:A", "date": "2024-01-03"}


def test_peer_comparison_uses_common_window_and_quarantines_quality() -> None:
    winner = compare_peer("wave", "TW:A", bars([10, 14, 11]), "2024-01-01", "2024-01-03")
    laggard = compare_peer("wave", "TW:B", bars([10, 13, 12]), "2024-01-01", "2024-01-03")
    quarantined = compare_peer("wave", "TW:C", bars([10, 20, 12], flags={1: ("jump",)}), "2024-01-01", "2024-01-03")
    assert winner["common_window_peak_appreciation_fraction"] == pytest.approx(0.4)
    assert winner["comparability_status"] == "comparable"
    assert quarantined["comparability_status"] == "quarantined"
    assert select_wave_winner([laggard, quarantined, winner]) == "TW:A"
    assert select_wave_winner([quarantined]) is None


def test_peer_missing_or_partial_coverage_is_null_and_ids_are_deterministic() -> None:
    no_bars = compare_peer("wave", "TW:A", [], "2024-01-01", "2024-01-03")
    partial = compare_peer("wave", "TW:A", bars([1, 2]), "2024-01-10", "2024-01-12")
    assert no_bars["null_reason"] == "no_bars"
    assert partial["common_window_peak_appreciation_fraction"] is None
    first = detect_episodes("A", bars([1, 2, 1.5]))
    second = detect_episodes("A", bars([1, 2, 1.5]))
    assert first[0]["episode_id"] == second[0]["episode_id"]
