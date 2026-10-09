"""Synthetic fixed-grid checks; these tests never read market or study results."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from research_core.hhhl_v4_summary import OUTCOME_FIELDS, first_noise_per_security, landmark_census, summarize_v4


def _row(
    security_id: str,
    anchor_date: str,
    *,
    year: int = 2020,
    base_eligible: bool = True,
    adjusted_label: int | None = 0,
    atlas_label: int | None = 0,
    adjusted_reason: str | None = None,
    atlas_reason: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "security_id": security_id,
        "base_eligible": base_eligible,
        "anchor_date": anchor_date,
        "breakout_date": anchor_date,
        "year": year,
    }
    for basis, label, reason in (
        ("adjusted", adjusted_label, adjusted_reason),
        ("atlas", atlas_label, atlas_reason),
    ):
        for horizon in (63, 126):
            values = {
                "label": label,
                "complete": label is not None,
                "unknown_reason": reason,
                "max_return": 0.4,
                "min_return": -0.2,
                "max_drawdown": 0.25,
                "forward_return": 0.1,
                "wait_to_threshold": 12 if label == 1 else None,
            }
            for field, value in values.items():
                row[f"{basis}_{field}_{horizon}"] = value
    row.update(extra)
    return row


def _events() -> pd.DataFrame:
    return pd.DataFrame([
        _row(
            "A",
            "2020-01-01",
            adjusted_label=None,
            atlas_label=0,
            adjusted_reason="window_end",
            pattern=True,
            scale="normal",
            cat="hhhl",
            limit_up=False,
            has_old=True,
            has_recent_far=False,
        ),
        _row(
            "A",
            "2020-01-02",
            adjusted_label=1,
            atlas_label=1,
            pattern=True,
            scale="normal",
            cat="range",
            limit_up=True,
            has_old=False,
            has_recent_far=False,
        ),
        _row(
            "B",
            "2021-02-01",
            year=2021,
            adjusted_label=1,
            atlas_label=0,
            pattern=True,
            scale="normal",
            cat="bottom",
            limit_up=True,
            has_old=True,
            has_recent_far=True,
        ),
        _row(
            "C",
            "2022-03-01",
            year=2022,
            adjusted_label=1,
            atlas_label=0,
            pattern=False,
            scale="inside_big_range",
            cat="range",
            limit_up=False,
            has_old=False,
            has_recent_far=False,
        ),
        _row(
            "D",
            "2022-03-02",
            year=2022,
            pattern=False,
            scale="outside_big_range",
            cat="hhhl",
            limit_up=True,
            has_old=False,
            has_recent_far=False,
        ),
    ])


def _baseline() -> pd.DataFrame:
    rows = []
    for index in range(30):
        rows.append(
            _row(
                f"BASE-{index:02d}",
                f"2020-01-{index + 1:02d}",
                adjusted_label=index % 2,
                atlas_label=(index + 1) % 2,
            )
        )
    return pd.DataFrame(rows)


def _controls() -> pd.DataFrame:
    return pd.DataFrame([
        _row("V1", "2020-01-01", adjusted_label=1, atlas_label=0, control_no_event=True, control_no_pattern=True),
        _row("V2", "2020-01-02", adjusted_label=0, atlas_label=1, control_no_event=False, control_no_pattern=True),
        _row("V3", "2020-01-03", adjusted_label=None, atlas_label=None, control_no_event=False, control_no_pattern=False),
    ])


def _noise() -> pd.DataFrame:
    return pd.DataFrame([_row("N1", "2020-02-01", adjusted_label=0, atlas_label=1)])


def _noise_reversal() -> pd.DataFrame:
    return pd.DataFrame([
        _row(
            "N1",
            "2020-03-01",
            adjusted_label=1,
            atlas_label=0,
            breakout_date="2020-02-01",
            event_id="z-original",
            calendar_offset=20,
        ),
        _row(
            "N1",
            "2020-01-01",
            adjusted_label=0,
            atlas_label=1,
            breakout_date="2020-02-02",
            event_id="a-next",
            calendar_offset=-20,
        ),
        _row(
            "N2",
            "2020-01-01",
            base_eligible=False,
            adjusted_label=1,
            atlas_label=0,
            breakout_date="2020-01-01",
            event_id="n2-ineligible",
        ),
        _row(
            "N2",
            "2020-01-02",
            adjusted_label=0,
            atlas_label=1,
            breakout_date="2020-01-02",
            event_id="n2-eligible",
        ),
        _row(
            "N3",
            "2020-01-01",
            adjusted_label=None,
            atlas_label=0,
            adjusted_reason="no_shift_candidate",
            breakout_date="2020-01-01",
            event_id="n3-unknown-original",
            calendar_offset=None,
        ),
        _row(
            "N3",
            "2020-01-02",
            adjusted_label=1,
            atlas_label=1,
            breakout_date="2020-01-02",
            event_id="n3-known-next",
            calendar_offset=1,
        ),
    ])


def _landmark_row(
    security_id: str,
    anchor_date: str,
    landmark: int,
    group: str,
    rise_bin: str,
    *,
    eligible: bool = True,
    label: int | None = 0,
    status: str = "active",
    reason: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "security_id": security_id,
        "base_eligible": eligible,
        "anchor_date": anchor_date,
        "breakout_date": anchor_date,
        "year": 2020,
        "landmark": landmark,
        "group": group,
        "rise_bin": rise_bin,
        "status": status,
        "reason": reason,
    }
    for field in OUTCOME_FIELDS:
        defaults = {
            "label": label,
            "complete": label is not None,
            "unknown_reason": reason,
            "max_return": 0.4,
            "min_return": -0.2,
            "max_drawdown": 0.25,
            "forward_return": 0.1,
            "wait_to_threshold": 12 if label == 1 else None,
        }
        row[f"{field}_126"] = defaults[field]
    return row


def _landmarks() -> pd.DataFrame:
    return pd.DataFrame([
        _landmark_row("L1", "2020-01-01", 10, "cross_old_only", "lt1", label=1),
        _landmark_row("L2", "2020-01-02", 10, "uncrossed_overhead", "b1_1p10", eligible=False, status="ineligible", reason="base_filter"),
        _landmark_row("L3", "2020-01-03", 20, "cross_recent_far_only", "b1_1p10", label=0),
        _landmark_row("L4", "2020-01-04", 20, "cross_both", "b1p10_1p25", label=1, status="resolved"),
        _landmark_row("L5", "2020-01-05", 40, "clean_reference", "ge1p25", label=0),
        _landmark_row("L6", "2020-01-06", 20, "cross_old_only", "lt1", label=1, status="inactive"),
    ])


def _summaries() -> list[dict[str, Any]]:
    return summarize_v4(_events(), _baseline(), _controls(), _noise(), _landmarks())


def _key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["family"],
        row["slice"],
        row["value"],
        row["sampling"],
        row["horizon"],
        row["basis"],
        row.get("landmark"),
    )


def _one(
    rows: list[dict[str, Any]],
    *,
    family: str,
    slice_name: str,
    value: str,
    sampling: str,
    horizon: int,
    basis: str,
    landmark: int | None = None,
) -> dict[str, Any]:
    return next(row for row in rows if _key(row) == (family, slice_name, value, sampling, horizon, basis, landmark))


def test_summary_grid_has_1080_unique_rows_including_empty_cells() -> None:
    rows = _summaries()

    assert len(rows) == 1080
    assert len({_key(row) for row in rows}) == 1080
    counts = Counter(row["family"] for row in rows)
    assert counts["E-all"] == 112
    assert counts["E-overhead-recent-far-only"] == 112
    assert counts["all_stock_days"] == 36
    assert counts["high_volume_no_event"] == 36
    assert counts["high_volume_no_pattern"] == 36
    assert counts["noise"] == 8
    assert counts["cross_any"] == 30

    empty = _one(
        rows,
        family="E-overhead-recent-far-only",
        slice_name="cat",
        value="hhhl",
        sampling="all_events",
        horizon=63,
        basis="adjusted_reference_factor",
    )
    assert (empty["rows"], empty["eligible"], empty["known"]) == (0, 0, 0)
    assert empty["rate"] is None
    assert empty["small_sample"] is True


def test_first_per_security_keeps_unknown_first_and_basis_denominators_distinct() -> None:
    rows = _summaries()
    adjusted = _one(
        rows,
        family="E-all",
        slice_name="pooled",
        value="all",
        sampling="first_per_security",
        horizon=126,
        basis="adjusted_reference_factor",
    )
    atlas = _one(
        rows,
        family="E-all",
        slice_name="pooled",
        value="all",
        sampling="first_per_security",
        horizon=126,
        basis="atlas_original",
    )

    assert (adjusted["eligible"], adjusted["known"], adjusted["hits"], adjusted["unknown"]) == (2, 1, 1, 1)
    assert adjusted["unknown_reasons"] == {"window_end": 1}
    assert adjusted["hit_wait_p10"]["value"] == 12
    assert adjusted["hit_wait_p90"]["value"] == 12
    assert (atlas["eligible"], atlas["known"], atlas["hits"], atlas["unknown"]) == (2, 2, 0, 0)
    assert adjusted["rate"] == 1
    assert atlas["rate"] == 0


def test_noise_first_per_security_uses_original_eligible_event_order() -> None:
    noise = _noise_reversal()
    selected = first_noise_per_security(noise)
    by_security = selected.set_index("security_id")

    original = by_security.loc["N1"]
    assert original["event_id"] == "z-original"
    assert original["breakout_date"] == "2020-02-01"
    assert original["anchor_date"] == "2020-03-01"
    for horizon in (63, 126):
        assert original[f"adjusted_label_{horizon}"] == 1
        assert original[f"atlas_label_{horizon}"] == 0

    assert by_security.loc["N2", "event_id"] == "n2-eligible"
    assert bool(by_security.loc["N2", "base_eligible"])
    unknown = by_security.loc["N3"]
    assert unknown["event_id"] == "n3-unknown-original"
    assert pd.isna(unknown["calendar_offset"])
    assert unknown["adjusted_unknown_reason_63"] == "no_shift_candidate"
    assert unknown["adjusted_unknown_reason_126"] == "no_shift_candidate"

    rows = summarize_v4(_events(), _baseline(), _controls(), noise, _landmarks())
    for horizon in (63, 126):
        adjusted = _one(
            rows,
            family="noise",
            slice_name="pooled",
            value="all",
            sampling="first_per_security",
            horizon=horizon,
            basis="adjusted_reference_factor",
        )
        atlas = _one(
            rows,
            family="noise",
            slice_name="pooled",
            value="all",
            sampling="first_per_security",
            horizon=horizon,
            basis="atlas_original",
        )
        assert (adjusted["eligible"], adjusted["known"], adjusted["hits"], adjusted["unknown"]) == (3, 2, 1, 1)
        assert adjusted["unknown_reasons"] == {"no_shift_candidate": 1}
        assert (atlas["eligible"], atlas["known"], atlas["hits"], atlas["unknown"]) == (3, 3, 1, 0)


def test_event_and_control_membership_and_matched_basis_rates() -> None:
    rows = _summaries()
    inside = _one(
        rows,
        family="X-inside",
        slice_name="pooled",
        value="all",
        sampling="all_events",
        horizon=126,
        basis="adjusted_reference_factor",
    )
    assert (inside["eligible"], inside["hits"]) == (1, 1)

    no_event = _one(
        rows,
        family="high_volume_no_event",
        slice_name="pooled",
        value="all",
        sampling="all_observations",
        horizon=126,
        basis="adjusted_reference_factor",
    )
    no_pattern = _one(
        rows,
        family="high_volume_no_pattern",
        slice_name="pooled",
        value="all",
        sampling="all_observations",
        horizon=126,
        basis="adjusted_reference_factor",
    )
    assert (no_event["eligible"], no_event["known"], no_event["hits"]) == (1, 1, 1)
    assert (no_pattern["eligible"], no_pattern["known"], no_pattern["hits"]) == (2, 2, 1)
    assert inside["all_day_base_rate"] == 0.5
    assert inside["no_event_control_rate"] == 1
    assert inside["lift_all_days"] == 2
    assert inside["lift_no_event_control"] == 1

    atlas_inside = _one(
        rows,
        family="X-inside",
        slice_name="pooled",
        value="all",
        sampling="all_events",
        horizon=126,
        basis="atlas_original",
    )
    assert atlas_inside["all_day_base_rate"] == 0.5
    assert atlas_inside["no_event_control_rate"] == 0
    assert atlas_inside["lift_no_event_control"] is None


def test_small_sample_flag_and_landmark_union_and_census() -> None:
    rows = _summaries()
    base = _one(
        rows,
        family="all_stock_days",
        slice_name="pooled",
        value="all",
        sampling="all_observations",
        horizon=126,
        basis="adjusted_reference_factor",
    )
    assert (base["known"], base["known_securities"], base["small_sample"]) == (30, 30, False)

    cross_any = _one(
        rows,
        family="cross_any",
        slice_name="pooled",
        value="all",
        sampling="all_events",
        horizon=126,
        basis="adjusted_reference_factor",
        landmark=20,
    )
    assert (cross_any["eligible"], cross_any["known"], cross_any["hits"]) == (1, 1, 0)
    assert cross_any["basis"] == "adjusted_reference_factor"
    assert cross_any["all_day_base_rate"] is None
    assert cross_any["no_event_control_rate"] is None
    assert cross_any["lift_all_days"] is None
    assert cross_any["lift_no_event_control"] is None

    census = landmark_census(_landmarks())
    census_map = {(row["landmark"], row["eligibility"], row["status"], row["reason"]): row["rows"] for row in census}
    assert census_map[(10, "eligible", "active", "(missing)")] == 1
    assert census_map[(10, "ineligible", "ineligible", "base_filter")] == 1
    assert census_map[(20, "eligible", "active", "(missing)")] == 1
    assert census_map[(20, "eligible", "resolved", "(missing)")] == 1
    assert census_map[(20, "eligible", "inactive", "(missing)")] == 1
