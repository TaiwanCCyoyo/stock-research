"""Synthetic ZIP publication checks; no market tables or study results are read."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
import zlib
from pathlib import Path
from typing import Any

import pytest

from scripts.publish_hhhl_v4_probability import (
    BUNDLE_NAME,
    MAX_BUNDLE_BYTES,
    MAX_TRANSPORT_METADATA_BYTES,
    MAX_TRANSPORT_PART_BYTES,
    PUBLICATION_ARCHIVE_NAME,
    PUBLICATION_NAME,
    _validate_summaries,
    convert_publication,
    main,
    publish,
    verify_publication,
)
from scripts.validate_hhhl_v4_source import write_json


@pytest.mark.parametrize("boundary", ["member-descriptor", "total-descriptor", "member-header", "total-header"])
def test_expansion_limits_reject_before_any_member_is_opened(
    synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    import scripts.publish_hhhl_v4_probability as producer

    run, _ = synthetic_run
    output = tmp_path / "bounded-publication"
    metadata = publish(run, output)
    bundle = (output / BUNDLE_NAME).read_bytes()
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        sizes = [info.file_size for info in archive.infolist()]
    if boundary == "member-descriptor":
        metadata["members"]["outputs/summaries.json"]["bytes"] = producer.MAX_MEMBER_EXPANDED_BYTES + 1
    elif boundary == "total-descriptor":
        monkeypatch.setattr(producer, "MAX_BUNDLE_EXPANDED_BYTES", sum(sizes) - 1)
    else:
        # Deliberately understated descriptors must not bypass independent ZIP-header limits.
        for descriptor in metadata["members"].values():
            descriptor["bytes"] = 0
        if boundary == "member-header":
            monkeypatch.setattr(producer, "MAX_MEMBER_EXPANDED_BYTES", max(sizes) - 1)
        else:
            monkeypatch.setattr(producer, "MAX_BUNDLE_EXPANDED_BYTES", sum(sizes) - 1)

    def forbidden_open(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("expansion limit must reject before decompression")

    monkeypatch.setattr(zipfile.ZipFile, "open", forbidden_open)
    with pytest.raises(ValueError, match="expanded size limit"):
        producer._verify_bundle(metadata, bundle, output)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def _empty_payload() -> dict[str, Any]:
    return {
        "rows": 0,
        "eligible": 0,
        "ineligible": 0,
        "securities": 0,
        "known_securities": 0,
        "known": 0,
        "hits": 0,
        "nonhits": 0,
        "unknown": 0,
        "rate": None,
        "unknown_lower": None,
        "unknown_upper": None,
        "unknown_reasons": {},
        "small_sample": True,
        "all_day_base_rate": None,
        "no_event_control_rate": None,
        "lift_all_days": None,
        "lift_no_event_control": None,
        **{
            field: {"value": None, "known": 0, "unknown": 0}
            for field in (
                "nonhit_min_return_median",
                "nonhit_min_return_p10",
                "nonhit_max_drawdown_median",
                "hit_wait_median",
                "hit_wait_p10",
                "hit_wait_p90",
            )
        },
    }


def _nonempty_payload(*, wait: float = 5.0) -> dict[str, Any]:
    payload = _empty_payload()
    payload.update(
        rows=5,
        eligible=4,
        ineligible=1,
        securities=3,
        known_securities=2,
        known=3,
        hits=1,
        nonhits=2,
        unknown=1,
        rate=1 / 3,
        unknown_lower=1 / 4,
        unknown_upper=1 / 2,
        unknown_reasons={"window_end": 1},
        all_day_base_rate=1 / 4,
        no_event_control_rate=0,
        lift_all_days=4 / 3,
        lift_no_event_control=None,
    )
    for field in ("hit_wait_median", "hit_wait_p10", "hit_wait_p90"):
        payload[field] = {"value": wait, "known": 1, "unknown": 0}
    for field in ("nonhit_min_return_median", "nonhit_min_return_p10", "nonhit_max_drawdown_median"):
        payload[field] = {"value": -0.1 if "min_return" in field else 0.2, "known": 2, "unknown": 0}
    return payload


def _align_synthetic_comparisons(rows: list[dict[str, Any]]) -> None:
    """Populate fixture references after changing synthetic counts and rates."""
    bases = {
        (row["family"], row["slice"], row["value"], row["horizon"], row["basis"]): row["rate"]
        for row in rows
        if row["family"] in ("all_stock_days", "high_volume_no_event")
    }
    for row in rows:
        for field, lift, family in (
            ("all_day_base_rate", "lift_all_days", "all_stock_days"),
            ("no_event_control_rate", "lift_no_event_control", "high_volume_no_event"),
        ):
            scope_slice, scope_value = ("year", row["value"]) if row["slice"] == "year" else ("pooled", "all")
            base = None if "landmark" in row else bases[(family, scope_slice, scope_value, row["horizon"], row["basis"])]
            row[field] = base
            row[lift] = None if row["rate"] is None or base is None or base == 0 else row["rate"] / base


def _summary_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def append(family: str, slice_name: str, value: str, sampling: str, horizon: int, basis: str, landmark: int | None = None) -> None:
        row: dict[str, Any] = {
            "family": family,
            "slice": slice_name,
            "value": value,
            "sampling": sampling,
            "horizon": horizon,
            "basis": basis,
            **_empty_payload(),
        }
        if landmark is not None:
            row["landmark"] = landmark
        rows.append(row)

    scopes = [("pooled", "all"), *[("year", str(year)) for year in range(2019, 2027)]]
    for family in ("all_stock_days", "high_volume_no_event", "high_volume_no_pattern"):
        for slice_name, value in scopes:
            for horizon in (63, 126):
                for basis in ("adjusted_reference_factor", "atlas_original"):
                    append(family, slice_name, value, "all_observations", horizon, basis)
    event_slices = [*scopes, *[("cat", cat) for cat in ("hhhl", "bottom", "range")], ("limit_up", "false"), ("limit_up", "true")]
    for family in ("E-all", "E-clean", "E-overhead", "E-overhead-old-only", "E-overhead-recent-far-only", "E-overhead-both", "X-inside", "noise"):
        for slice_name, value in [("pooled", "all")] if family == "noise" else event_slices:
            for sampling in ("all_events", "first_per_security"):
                for horizon in (63, 126):
                    for basis in ("adjusted_reference_factor", "atlas_original"):
                        append(family, slice_name, value, sampling, horizon, basis)
    for family in ("cross_any", "cross_old_only", "cross_recent_far_only", "cross_both", "uncrossed_overhead", "clean_reference"):
        for slice_name, value in [("pooled", "all"), *[("rise_bin", name) for name in ("lt1", "b1_1p10", "b1p10_1p25", "ge1p25")]]:
            for landmark in (10, 20, 40):
                for sampling in ("all_events", "first_per_security"):
                    append(family, slice_name, value, sampling, 126, "adjusted_reference_factor", landmark)
    return rows


def test_complete_fixed_grid_accepts_empty_synthetic_results() -> None:
    rows = _summary_rows()
    assert len(rows) == 1080
    assert _validate_summaries(rows) == rows
    assert sum("landmark" in row for row in rows) == 180


def test_payload_accepts_complete_nonempty_metrics_and_unknown_only_nulls() -> None:
    rows = _summary_rows()
    rows[0].update(_nonempty_payload())
    rows[1].update(rows=1, eligible=1, securities=1, unknown=1, unknown_reasons={"window_end": 1}, unknown_lower=0, unknown_upper=1)
    _align_synthetic_comparisons(rows)
    assert _validate_summaries(rows) == rows


def test_payload_accepts_existing_producer_synthetic_statistics() -> None:
    from scripts.tests.test_hhhl_v4_summary import _summaries

    rows = _summaries()
    assert _validate_summaries(rows) == rows


@pytest.mark.parametrize(
    ("family", "slice_name", "value"),
    [
        ("E-all", "pooled", "all"),
        ("E-clean", "cat", "hhhl"),
        ("X-inside", "limit_up", "true"),
        ("E-overhead", "year", "2020"),
        ("noise", "pooled", "all"),
        ("high_volume_no_pattern", "year", "2021"),
    ],
)
@pytest.mark.parametrize(
    ("base_field", "lift_field"),
    [
        ("all_day_base_rate", "lift_all_days"),
        ("no_event_control_rate", "lift_no_event_control"),
    ],
)
def test_comparison_rejects_wrong_scope_reference_despite_consistent_lift(family: str, slice_name: str, value: str, base_field: str, lift_field: str) -> None:
    rows = _summary_rows()
    target = next(row for row in rows if row["family"] == family and row["slice"] == slice_name and row["value"] == value)
    target.update(_nonempty_payload())
    _align_synthetic_comparisons(rows)
    assert _validate_summaries(rows) == rows
    target[base_field] = 0.5
    target[lift_field] = target["rate"] / 0.5
    with pytest.raises(ValueError, match=f"{base_field} reference"):
        _validate_summaries(rows)


def test_comparison_keeps_year_horizon_and_basis_references_separate_and_accepts_zero() -> None:
    rows = _summary_rows()
    baseline = next(
        row
        for row in rows
        if row["family"] == "all_stock_days"
        and row["slice"] == "year"
        and row["value"] == "2020"
        and row["horizon"] == 126
        and row["basis"] == "atlas_original"
    )
    baseline.update(rows=1, eligible=1, known=1, nonhits=1, securities=1, known_securities=1, rate=0, unknown_lower=0, unknown_upper=0)
    for field in ("nonhit_min_return_median", "nonhit_min_return_p10", "nonhit_max_drawdown_median"):
        baseline[field] = {"value": -0.1 if "min_return" in field else 0.2, "known": 1, "unknown": 0}
    _align_synthetic_comparisons(rows)
    assert _validate_summaries(rows) == rows
    matched = next(
        row
        for row in rows
        if row["family"] == "E-all" and row["slice"] == "year" and row["value"] == "2020" and row["horizon"] == 126 and row["basis"] == "atlas_original"
    )
    assert matched["all_day_base_rate"] == 0 and matched["lift_all_days"] is None
    unrelated = next(
        row
        for row in rows
        if row["family"] == "E-all" and row["slice"] == "year" and row["value"] == "2020" and row["horizon"] == 63 and row["basis"] == "atlas_original"
    )
    assert unrelated["all_day_base_rate"] is None
    matched["all_day_base_rate"] = None
    with pytest.raises(ValueError, match="all_day_base_rate reference"):
        _validate_summaries(rows)


@pytest.mark.parametrize(
    ("base_field", "lift_field"),
    [
        ("all_day_base_rate", "lift_all_days"),
        ("no_event_control_rate", "lift_no_event_control"),
    ],
)
def test_landmark_comparisons_remain_null_even_with_consistent_lift(base_field: str, lift_field: str) -> None:
    rows = _summary_rows()
    target = rows[-1]
    target.update(_nonempty_payload(wait=target["landmark"] + 1))
    _align_synthetic_comparisons(rows)
    assert _validate_summaries(rows) == rows
    target[base_field] = 0.5
    target[lift_field] = target["rate"] / 0.5
    with pytest.raises(ValueError, match="must be null for landmark"):
        _validate_summaries(rows)


@pytest.mark.parametrize("field", list(_empty_payload()))
def test_payload_requires_every_descriptive_field(field: str) -> None:
    rows = _summary_rows()
    del rows[0][field]
    with pytest.raises(ValueError, match="missing payload fields"):
        _validate_summaries(rows)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("rows", True),
        ("eligible", "4"),
        ("unknown", -1),
        ("known", 3.0),
        ("rows", 6),
        ("eligible", 5),
        ("known", 4),
        ("hits", 2),
        ("known_securities", 4),
        ("securities", 5),
        ("securities", 1),
        ("rate", 0.5),
        ("unknown_lower", 0.5),
        ("unknown_upper", 1),
        ("rate", None),
        ("rate", True),
        ("rate", "0.333"),
        ("rate", float("nan")),
        ("unknown_upper", float("inf")),
        ("all_day_base_rate", -0.1),
        ("no_event_control_rate", 1.1),
        ("all_day_base_rate", True),
        ("all_day_base_rate", "0.25"),
        ("all_day_base_rate", float("inf")),
        ("no_event_control_rate", float("nan")),
        ("lift_all_days", -1),
        ("lift_all_days", float("inf")),
        ("lift_all_days", float("nan")),
        ("lift_all_days", True),
        ("lift_all_days", "1.333"),
        ("lift_all_days", 1),
        ("lift_all_days", None),
        ("lift_no_event_control", 0),
        ("unknown_reasons", []),
        ("unknown_reasons", {1: 1}),
        ("unknown_reasons", {"window_end": True}),
        ("unknown_reasons", {"window_end": "1"}),
        ("unknown_reasons", {"window_end": -1}),
        ("unknown_reasons", {}),
        ("small_sample", 1),
        ("small_sample", False),
    ],
)
def test_payload_rejects_invalid_and_contradictory_statistics(field: str, bad: Any) -> None:
    rows = _summary_rows()
    rows[0].update(_nonempty_payload())
    rows[0][field] = bad
    with pytest.raises(ValueError):
        _validate_summaries(rows)


@pytest.mark.parametrize(
    "field",
    [
        "nonhit_min_return_median",
        "nonhit_min_return_p10",
        "nonhit_max_drawdown_median",
        "hit_wait_median",
        "hit_wait_p10",
        "hit_wait_p90",
    ],
)
@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"value": None, "known": 0},
        {"value": True, "known": 0, "unknown": 0},
        {"value": "5", "known": 0, "unknown": 0},
        {"value": float("nan"), "known": 0, "unknown": 0},
        {"value": float("inf"), "known": 0, "unknown": 0},
        {"value": None, "known": True, "unknown": 0},
        {"value": None, "known": -1, "unknown": 1},
        {"value": None, "known": 0, "unknown": "0"},
        {"value": None, "known": 1, "unknown": 0},
        {"value": 5, "known": 0, "unknown": 0},
    ],
)
def test_payload_rejects_malformed_quantiles(field: str, bad: Any) -> None:
    rows = _summary_rows()
    rows[0][field] = bad
    with pytest.raises(ValueError):
        _validate_summaries(rows)


@pytest.mark.parametrize(
    "field",
    [
        "nonhit_min_return_median",
        "nonhit_min_return_p10",
        "nonhit_max_drawdown_median",
        "hit_wait_median",
        "hit_wait_p10",
        "hit_wait_p90",
    ],
)
def test_payload_quantile_counts_must_match_their_hit_or_nonhit_population(field: str) -> None:
    rows = _summary_rows()
    rows[0].update(_nonempty_payload())
    rows[0][field]["unknown"] += 1
    with pytest.raises(ValueError, match="inconsistent quantile"):
        _validate_summaries(rows)


def _complete_nonempty_grid(
    *, horizon: int = 63, landmark: int | None = None, family: str | None = None, basis: str = "adjusted_reference_factor"
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = _summary_rows()
    target = next(
        row
        for row in rows
        if row["family"] == (family or ("noise" if landmark is None else "cross_any"))
        and row["slice"] == "pooled"
        and row["sampling"] == "all_events"
        and row["horizon"] == horizon
        and row["basis"] == basis
        and row.get("landmark") == landmark
    )
    target.update(_nonempty_payload(wait=1 if landmark is None else landmark + 1))
    _align_synthetic_comparisons(rows)
    return rows, target


@pytest.mark.parametrize(
    ("family", "basis", "landmark", "reason"),
    [
        ("E-all", "adjusted_reference_factor", None, "invalid_anchor"),
        ("E-all", "adjusted_reference_factor", None, "missing_before_hit"),
        ("E-all", "adjusted_reference_factor", None, "window_end"),
        ("E-all", "atlas_original", None, "missing_or_invalid_path"),
        ("E-all", "atlas_original", None, "window_end"),
        ("noise", "adjusted_reference_factor", None, "no_shift_candidate"),
        ("noise", "atlas_original", None, "no_shift_candidate"),
        ("noise", "adjusted_reference_factor", None, "invalid_anchor"),
        ("noise", "atlas_original", None, "missing_or_invalid_path"),
        ("cross_any", "adjusted_reference_factor", 10, "missing_before_hit"),
        ("cross_any", "adjusted_reference_factor", 20, "window_end"),
        ("cross_any", "adjusted_reference_factor", 40, "window_end"),
    ],
)
def test_unknown_reasons_accept_only_original_scoped_producer_reasons(family: str, basis: str, landmark: int | None, reason: str) -> None:
    rows, target = _complete_nonempty_grid(horizon=126, landmark=landmark, family=family, basis=basis)
    target["unknown_reasons"] = {reason: 1}
    assert _validate_summaries(rows) == rows


@pytest.mark.parametrize(
    ("family", "basis", "landmark", "reason"),
    [
        ("E-all", "adjusted_reference_factor", None, "(missing)"),
        ("E-all", "adjusted_reference_factor", None, ""),
        ("E-all", "atlas_original", None, "window_edn"),
        ("noise", "adjusted_reference_factor", None, "invented"),
        ("E-all", "adjusted_reference_factor", None, "missing_or_invalid_path"),
        ("E-all", "atlas_original", None, "invalid_anchor"),
        ("E-all", "atlas_original", None, "missing_before_hit"),
        ("E-all", "adjusted_reference_factor", None, "no_shift_candidate"),
        ("E-all", "atlas_original", None, "no_shift_candidate"),
        ("noise", "adjusted_reference_factor", None, "missing_or_invalid_path"),
        ("noise", "atlas_original", None, "invalid_anchor"),
        ("cross_any", "adjusted_reference_factor", 10, "invalid_anchor"),
        ("cross_any", "adjusted_reference_factor", 20, "no_shift_candidate"),
        ("cross_any", "adjusted_reference_factor", 40, "missing_or_invalid_path"),
    ],
)
def test_unknown_reasons_reject_undefined_or_cross_scope_reasons(family: str, basis: str, landmark: int | None, reason: str) -> None:
    rows, target = _complete_nonempty_grid(horizon=126, landmark=landmark, family=family, basis=basis)
    target["unknown_reasons"] = {reason: 1}
    with pytest.raises(ValueError, match="undefined unknown reason"):
        _validate_summaries(rows)


def test_unknown_reason_buckets_cannot_have_zero_counts_even_when_total_matches() -> None:
    rows, target = _complete_nonempty_grid()
    target["unknown_reasons"] = {"window_end": 1, "missing_before_hit": 0}
    with pytest.raises(ValueError):
        _validate_summaries(rows)
    rows = _summary_rows()
    rows[0]["unknown_reasons"] = {"window_end": 0}
    with pytest.raises(ValueError):
        _validate_summaries(rows)


@pytest.mark.parametrize(
    "fields",
    [
        ("hit_wait_median",),
        ("hit_wait_p10",),
        ("hit_wait_p90",),
        ("nonhit_min_return_median",),
        ("nonhit_min_return_p10",),
        ("nonhit_max_drawdown_median",),
        ("hit_wait_median", "hit_wait_p10", "hit_wait_p90"),
        ("nonhit_min_return_median", "nonhit_min_return_p10", "nonhit_max_drawdown_median"),
    ],
)
@pytest.mark.parametrize("defect", ["null-value", "missing-value", "missing-known", "lost-population"])
def test_nonempty_quantiles_cannot_lose_known_members_or_values(fields: tuple[str, ...], defect: str) -> None:
    rows, target = _complete_nonempty_grid()
    for field in fields:
        metric = target[field]
        if defect == "null-value":
            metric["value"] = None
        elif defect == "missing-value":
            del metric["value"]
        elif defect == "missing-known":
            del metric["known"]
        else:
            # Keeping known + unknown equal to the population cannot hide missing metrics.
            metric["known"] -= 1
            metric["unknown"] = 1
            if metric["known"] == 0:
                metric["value"] = None
    with pytest.raises(ValueError, match=fields[0]):
        _validate_summaries(rows)


@pytest.mark.parametrize(
    ("horizon", "landmark", "wait"),
    [
        (63, None, 0),
        (63, None, -1),
        (63, None, 64),
        (126, None, 127),
        (126, 10, 10),
        (126, 20, 20),
        (126, 40, 40),
        (126, 10, 0),
        (126, 20, -1),
        (126, 40, 127),
    ],
)
@pytest.mark.parametrize("field", ["hit_wait_median", "hit_wait_p10", "hit_wait_p90"])
def test_hit_wait_quantiles_reject_outside_original_clock(horizon: int, landmark: int | None, wait: float, field: str) -> None:
    rows, target = _complete_nonempty_grid(horizon=horizon, landmark=landmark)
    target[field]["value"] = wait
    with pytest.raises(ValueError, match="waiting range"):
        _validate_summaries(rows)


@pytest.mark.parametrize(
    ("horizon", "landmark", "wait"),
    [
        (63, None, 1),
        (63, None, 63),
        (126, None, 1),
        (126, None, 126),
        (126, 10, 11),
        (126, 20, 21),
        (126, 40, 41),
        (126, 10, 126),
        (126, 20, 126),
        (126, 40, 126),
    ],
)
def test_hit_wait_quantiles_accept_original_clock_boundaries(horizon: int, landmark: int | None, wait: float) -> None:
    rows, target = _complete_nonempty_grid(horizon=horizon, landmark=landmark)
    for field in ("hit_wait_median", "hit_wait_p10", "hit_wait_p90"):
        target[field]["value"] = wait
    assert _validate_summaries(rows) == rows


@pytest.mark.parametrize("landmark", [None, 10, 20, 40])
def test_hit_wait_quantiles_accept_fractional_interpolation(landmark: int | None) -> None:
    rows, target = _complete_nonempty_grid(horizon=126, landmark=landmark)
    target.update(hits=2, nonhits=1, rate=2 / 3, unknown_lower=1 / 2, unknown_upper=3 / 4)
    start = 1 if landmark is None else landmark + 1
    # Quantiles for two integer waits start and start + 1 use linear interpolation.
    for field, offset in (("hit_wait_p10", 0.1), ("hit_wait_median", 0.5), ("hit_wait_p90", 0.9)):
        target[field] = {"value": start + offset, "known": 2, "unknown": 0}
    for field in ("nonhit_min_return_median", "nonhit_min_return_p10", "nonhit_max_drawdown_median"):
        target[field]["known"] = 1
    _align_synthetic_comparisons(rows)
    assert _validate_summaries(rows) == rows


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("hit_wait_p10", 6),
        ("hit_wait_p90", 4),
        ("nonhit_min_return_p10", 0),
    ],
)
def test_quantile_order_cannot_reverse(field: str, bad: float) -> None:
    rows, target = _complete_nonempty_grid()
    for wait_field in ("hit_wait_median", "hit_wait_p10", "hit_wait_p90"):
        target[wait_field]["value"] = 5
    target[field]["value"] = bad
    with pytest.raises(ValueError, match="reversed quantile order"):
        _validate_summaries(rows)


@pytest.mark.parametrize(("horizon", "landmark"), [(63, None), (126, None), (126, 10), (126, 20), (126, 40)])
@pytest.mark.parametrize(
    ("field", "bad", "message"),
    [
        ("nonhit_min_return_median", -1.01, "return range"),
        ("nonhit_min_return_p10", -1.01, "return range"),
        ("nonhit_max_drawdown_median", -0.01, "drawdown range"),
        ("nonhit_max_drawdown_median", 1.01, "drawdown range"),
    ],
)
def test_nonhit_quantiles_reject_impossible_positive_price_ranges(horizon: int, landmark: int | None, field: str, bad: float, message: str) -> None:
    rows, target = _complete_nonempty_grid(horizon=horizon, landmark=landmark)
    target[field]["value"] = bad
    if field == "nonhit_min_return_median":
        # Keep p10 <= median so the range defect cannot be hidden by an order failure.
        target["nonhit_min_return_p10"]["value"] = bad
    with pytest.raises(ValueError, match=message):
        _validate_summaries(rows)


@pytest.mark.parametrize(("horizon", "landmark"), [(63, None), (126, None), (126, 10), (126, 20), (126, 40)])
@pytest.mark.parametrize("minimum_return", [-1, -0.999999999, 0, 0.25])
def test_nonhit_min_return_accepts_boundary_and_positive_values_below_fixed_target(horizon: int, landmark: int | None, minimum_return: float) -> None:
    rows, target = _complete_nonempty_grid(horizon=horizon, landmark=landmark)
    for field in ("nonhit_min_return_median", "nonhit_min_return_p10"):
        target[field]["value"] = minimum_return
    assert _validate_summaries(rows) == rows


@pytest.mark.parametrize(("horizon", "landmark"), [(63, None), (126, None), (126, 10), (126, 20), (126, 40)])
@pytest.mark.parametrize("field", ["nonhit_min_return_median", "nonhit_min_return_p10"])
@pytest.mark.parametrize("excess", [0, 0.01])
def test_nonhit_min_return_rejects_reaching_or_exceeding_fixed_hit_target(horizon: int, landmark: int | None, field: str, excess: float) -> None:
    rows, target = _complete_nonempty_grid(horizon=horizon, landmark=landmark)
    hit_return = 0.5 if horizon == 63 else 1.0
    target[field]["value"] = hit_return + excess
    if field == "nonhit_min_return_p10":
        target["nonhit_min_return_median"]["value"] = hit_return + excess
    with pytest.raises(ValueError, match="return range"):
        _validate_summaries(rows)


@pytest.mark.parametrize(("horizon", "landmark"), [(63, None), (126, None), (126, 10), (126, 20), (126, 40)])
@pytest.mark.parametrize("drawdown", [0, 1])
def test_nonhit_drawdown_accepts_closed_interval_boundaries(horizon: int, landmark: int | None, drawdown: float) -> None:
    rows, target = _complete_nonempty_grid(horizon=horizon, landmark=landmark)
    target["nonhit_max_drawdown_median"]["value"] = drawdown
    assert _validate_summaries(rows) == rows


def test_payload_zero_denominator_requires_null_rates_and_lifts() -> None:
    for field in ("rate", "unknown_lower", "unknown_upper", "lift_all_days", "lift_no_event_control"):
        rows = _summary_rows()
        rows[0][field] = 0
        with pytest.raises(ValueError, match="descriptive formula"):
            _validate_summaries(rows)


def test_payload_small_sample_boundary_uses_existing_formula() -> None:
    rows = _summary_rows()
    rows[0].update(rows=30, eligible=30, known=30, securities=10, known_securities=10, nonhits=30, rate=0, unknown_lower=0, unknown_upper=0, small_sample=False)
    for field in ("nonhit_min_return_median", "nonhit_min_return_p10", "nonhit_max_drawdown_median"):
        rows[0][field] = {"value": -0.1 if "min_return" in field else 0.2, "known": 30, "unknown": 0}
    _align_synthetic_comparisons(rows)
    assert _validate_summaries(rows) == rows


def test_fixed_grid_rejects_missing_cell() -> None:
    with pytest.raises(ValueError, match="exactly 1080 cells"):
        _validate_summaries(_summary_rows()[:-1])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("family", "illegal-family", "fixed v4 grid"),
        ("slice", "rise_bin", "fixed v4 grid"),
        ("value", "2027", "fixed v4 grid"),
        ("sampling", "all_events", "fixed v4 grid"),
        ("basis", "illegal-basis", "fixed v4 grid"),
        ("horizon", 127, "fixed v4 grid"),
        ("value", 2019, "invalid key field type"),
        ("value", ["all"], "invalid key field type"),
        ("horizon", 63.0, "invalid key field type"),
        ("horizon", True, "invalid key field type"),
        ("landmark", 10, "fixed v4 grid"),
        ("landmark", "10", "invalid landmark type"),
        ("landmark", 10.0, "invalid landmark type"),
        ("landmark", True, "invalid landmark type"),
    ],
)
def test_fixed_grid_rejects_unique_replacement_and_invalid_types(field: str, value: Any, message: str) -> None:
    rows = _summary_rows()
    rows[0][field] = value
    with pytest.raises(ValueError, match=message):
        _validate_summaries(rows)


@pytest.mark.parametrize("landmark", [None, 11, 63])
def test_landmark_cell_requires_fixed_landmark(landmark: int | None) -> None:
    rows = _summary_rows()
    rows[-1]["landmark"] = landmark
    with pytest.raises(ValueError, match="fixed v4 grid"):
        _validate_summaries(rows)


def _manifest(run: Path) -> dict[str, Any]:
    return json.loads((run / "manifest.json").read_text(encoding="utf-8"))


def _rewrite_manifest(run: Path, manifest: dict[str, Any]) -> None:
    (run / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rewrite_publication(root: Path, publication: dict[str, Any]) -> None:
    (root / PUBLICATION_NAME).write_text(json.dumps(publication, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_portable_reader_accepts_foreign_windows_bulk_locator(synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path) -> None:
    run, _ = synthetic_run
    output = tmp_path / "foreign-location-publication"
    publish(run, output)
    metadata = json.loads((output / PUBLICATION_NAME).read_bytes())
    metadata["bulk_location"] = "D:/Project/Stock/tasks/saved-only-run"
    _rewrite_publication(output, metadata)
    result = verify_publication(output)
    assert result["metadata"]["bulk_location"] == metadata["bulk_location"]
    assert result["metadata"]["bulk_location_verified"] is False


def test_v1_metadata_rejects_oversize_before_opening(synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, _ = synthetic_run
    output = tmp_path / "oversize-metadata"
    publish(run, output)
    (output / PUBLICATION_NAME).write_bytes(b" " * (MAX_TRANSPORT_METADATA_BYTES + 1))

    def forbidden_open(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("oversize metadata must reject before opening any file")

    monkeypatch.setattr(Path, "open", forbidden_open)
    with pytest.raises(ValueError, match="publication metadata exceeds"):
        verify_publication(output)


def test_v1_metadata_read_remains_bounded_if_file_grows_after_stat(
    synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _ = synthetic_run
    output = tmp_path / "growing-metadata"
    publish(run, output)
    metadata_path = (output / PUBLICATION_NAME).resolve()
    original_open = Path.open
    requests: list[int] = []

    class GrowingStream(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            assert size == MAX_TRANSPORT_METADATA_BYTES + 1
            requests.append(size)
            return super().read(size)

    def growing_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path == metadata_path:
            return GrowingStream(b" " * (MAX_TRANSPORT_METADATA_BYTES + 1))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", growing_open)
    with pytest.raises(ValueError, match="publication metadata exceeds"):
        verify_publication(output)
    assert requests == [MAX_TRANSPORT_METADATA_BYTES + 1]


def _rewrite_transport_archive(root: Path, publication: dict[str, Any]) -> None:
    with zipfile.ZipFile(root / PUBLICATION_ARCHIVE_NAME, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PUBLICATION_NAME, json.dumps(publication, ensure_ascii=False, indent=2) + "\n")


def _checkout_for_identity(identity: dict[str, str]) -> Path:
    builder = next(path for path in identity if path.replace("\\", "/").endswith("scripts/build_hhhl_v4_probability.py"))
    return Path(builder).parents[1]


def _identity_local_path(identity: dict[str, str], original: str) -> Path:
    path = Path(original)
    if path.is_absolute():
        return path
    return _checkout_for_identity(identity).joinpath(*original.replace("\\", "/").split("/"))


@pytest.fixture
def synthetic_run(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    """Create fake byte artifacts, including a final-index baseline shard."""
    run = tmp_path / "run"
    run.mkdir()
    checkout = tmp_path / "synthetic-checkout"
    identity_contents = {
        "scripts/build_hhhl_v4_probability.py": b"# synthetic builder identity\n",
        "tasks/20261010-hhhl-v4-probability/mission.md": b"synthetic relative mission\n",
        "tasks/20261010-hhhl-v4-probability/data-contract.md": b"synthetic relative contract\n",
        "tasks/20261010-hhhl-v4-probability/sources/hhhl_rule_v4.zip": b"synthetic frozen source bytes",
    }
    identity = {}
    for relative, data in identity_contents.items():
        path = checkout.joinpath(*relative.split("/"))
        _write_bytes(path, data)
        original = str(path.resolve()) if relative.endswith("build_hhhl_v4_probability.py") else relative.replace("/", "\\")
        identity[original] = _sha(data)

    artifact_contents = {
        "summaries.json": json.dumps(_summary_rows(), separators=(",", ":")).encode("utf-8"),
        "diagnostics.json": b'{"synthetic":true}\n',
        "coverage.json": b'[{"security_id":"synthetic"}]\n',
        "audit-sample.parquet": b"synthetic audit parquet placeholder",
        "label-discordance-63.parquet": b"synthetic 63-day parquet placeholder",
        "label-discordance-126.parquet": b"synthetic 126-day parquet placeholder",
        "baseline/0001.parquet": b"synthetic first baseline shard",
        "baseline/1941.parquet": b"synthetic last baseline shard",
    }
    artifacts = {}
    for relative, data in artifact_contents.items():
        _write_bytes(run / relative, data)
        artifacts[relative] = {"sha256": _sha(data), "bytes": len(data)}

    write_json(
        run / "manifest.json",
        {
            "schema_version": "hhhl-probability.v4",
            "complete": True,
            "code_commit": "synthetic-commit",
            "identity": identity,
            "artifacts": artifacts,
        },
    )
    return run, artifact_contents


def test_publish_and_reader_verify_exact_members_and_filter_cli(
    synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run, artifact_contents = synthetic_run
    output = tmp_path / "publication"

    metadata = publish(run, output)
    verified = verify_publication(output)

    assert metadata["schema_version"] == "hhhl-v4-probability-publication.v1"
    assert metadata["bulk_location"] == str(run.resolve())
    assert metadata["bulk_location_availability"] == "local_only"
    assert metadata["bulk_location_verified"] is False
    assert metadata["scientific_cells"] == 1080
    assert metadata["bundle_bytes"] <= MAX_BUNDLE_BYTES
    assert len(verified["summaries"]) == 1080
    assert verified["summaries"] == _summary_rows()
    assert verified["metadata"] == metadata

    with zipfile.ZipFile(output / BUNDLE_NAME) as archive:
        names = set(archive.namelist())
        assert "outputs/manifest.json" in names
        assert "outputs/summaries.json" in names
        for original, data in artifact_contents.items():
            if original.startswith("baseline/"):
                continue  # Bulk shards are verified before publication, not bundled.
            assert archive.read(f"outputs/{original}") == data
        input_members = [name for name in names if name.startswith("inputs/")]
        identity = _manifest(run)["identity"]
        assert len(input_members) == len(identity)
        for name in input_members:
            original = metadata["members"][name]["original_path"]
            assert original in identity
            assert metadata["members"][name]["sha256"] == identity[original]
            assert archive.read(name) == _identity_local_path(identity, original).read_bytes()

    assert set(metadata["members"]) == names
    assert main(["--publication", str(output), "--family", "noise", "--horizon", "126"]) == 0
    query = json.loads(capsys.readouterr().out)
    assert len(query) == 4
    assert all(row["family"] == "noise" for row in query)
    assert query[0]["horizon"] == 126


def test_publish_checks_every_declared_artifact_including_final_baseline_shard(synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path) -> None:
    run, _ = synthetic_run
    (run / "baseline" / "1941.parquet").write_bytes(b"changed synthetic shard")
    output = tmp_path / "publication"

    with pytest.raises(ValueError, match="source artifact hash/byte mismatch: baseline/1941.parquet"):
        publish(run, output)
    assert not output.exists()


def test_changed_identity_input_is_rejected_before_archiving(synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path) -> None:
    run, _ = synthetic_run
    identity = _manifest(run)["identity"]
    original = next(path for path in identity if not Path(path).is_absolute())
    _identity_local_path(identity, original).write_bytes(b"changed identity bytes")
    output = tmp_path / "publication"

    with pytest.raises(ValueError, match="source identity hash mismatch"):
        publish(run, output)
    assert not output.exists()


def test_never_overwrites_existing_publication(synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path) -> None:
    run, _ = synthetic_run
    output = tmp_path / "publication"
    publish(run, output)
    before = {path.name: path.read_bytes() for path in output.iterdir()}

    with pytest.raises(FileExistsError):
        publish(run, output)
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before


def test_duplicate_summary_keys_are_rejected_even_when_artifact_hash_is_updated(synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path) -> None:
    run, _ = synthetic_run
    summary_path = run / "summaries.json"
    rows = json.loads(summary_path.read_bytes())
    rows[-1] = rows[0].copy()
    summary_path.write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")
    manifest = _manifest(run)
    raw = summary_path.read_bytes()
    manifest["artifacts"]["summaries.json"] = {"sha256": _sha(raw), "bytes": len(raw)}
    _rewrite_manifest(run, manifest)

    with pytest.raises(ValueError, match="duplicate summary key"):
        publish(run, tmp_path / "publication")


@pytest.mark.parametrize("entrypoint", ["publisher", "reader"])
@pytest.mark.parametrize("defect", ["family", "payload", "missing-wait", "nonhit-return-range", "nonhit-drawdown-range", "unknown-reason"])
def test_publication_rejects_invalid_summaries_even_with_consistent_hashes(
    synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path, entrypoint: str, defect: str
) -> None:
    run, _ = synthetic_run
    output = tmp_path / "publication"
    publication: dict[str, Any] = {}
    if entrypoint == "reader":
        publication = publish(run, output)
    rows = _summary_rows()
    if defect == "family":
        rows[0]["family"] = "illegal-family"
        message = "fixed v4 grid: missing=1, unexpected=1"
    elif defect == "payload":
        rows[0].update(_nonempty_payload())
        rows[0]["rate"] = 0.9
        message = "rate does not match its descriptive formula"
    elif defect == "missing-wait":
        rows, target = _complete_nonempty_grid()
        target["hit_wait_median"] = {"value": None, "known": 0, "unknown": target["hits"]}
        message = "hit_wait_median"
    elif defect == "unknown-reason":
        rows, target = _complete_nonempty_grid()
        target["unknown_reasons"] = {"invented": target["unknown"]}
        message = "undefined unknown reason"
    else:
        rows, target = _complete_nonempty_grid()
        if defect == "nonhit-return-range":
            target["nonhit_min_return_p10"]["value"] = -1.01
            message = "return range"
        else:
            target["nonhit_max_drawdown_median"]["value"] = 1.01
            message = "drawdown range"
    raw = json.dumps(rows, separators=(",", ":")).encode("utf-8")
    manifest = _manifest(run)
    manifest["artifacts"]["summaries.json"] = {"sha256": _sha(raw), "bytes": len(raw)}
    if entrypoint == "publisher":
        (run / "summaries.json").write_bytes(raw)
        _rewrite_manifest(run, manifest)
        with pytest.raises(ValueError, match=message):
            publish(run, output)
        assert not output.exists()
        return

    with zipfile.ZipFile(output / BUNDLE_NAME) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}
    payloads["outputs/summaries.json"] = raw
    payloads["outputs/manifest.json"] = json.dumps(manifest).encode("utf-8")
    for name, data in payloads.items():
        publication["members"][name].update(sha256=_sha(data), bytes=len(data))
    publication["run_manifest_sha256"] = _sha(payloads["outputs/manifest.json"])
    with zipfile.ZipFile(output / BUNDLE_NAME, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)
    bundle = (output / BUNDLE_NAME).read_bytes()
    publication.update(bundle_sha256=_sha(bundle), bundle_bytes=len(bundle))
    _rewrite_publication(output, publication)
    with pytest.raises(ValueError, match=message):
        verify_publication(output)


def test_malformed_publication_member_map_is_rejected(synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path) -> None:
    run, _ = synthetic_run
    output = tmp_path / "publication"
    publish(run, output)
    publication = json.loads((output / PUBLICATION_NAME).read_text(encoding="utf-8"))
    publication["members"].pop("outputs/coverage.json")
    _rewrite_publication(output, publication)

    with pytest.raises(ValueError, match="ZIP membership does not match publication manifest"):
        verify_publication(output)


def test_zip_traversal_is_rejected_without_extraction(synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path) -> None:
    run, _ = synthetic_run
    output = tmp_path / "publication"
    publish(run, output)
    bundle = output / BUNDLE_NAME
    with zipfile.ZipFile(bundle, mode="w") as archive:
        archive.writestr("../escape.txt", b"must not be extracted")
    publication = json.loads((output / PUBLICATION_NAME).read_text(encoding="utf-8"))
    raw_bundle = bundle.read_bytes()
    publication["bundle_bytes"] = len(raw_bundle)
    publication["bundle_sha256"] = _sha(raw_bundle)
    publication["members"] = {
        "../escape.txt": {
            "sha256": _sha(b"must not be extracted"),
            "bytes": len(b"must not be extracted"),
            "original_path": "escape.txt",
        }
    }
    _rewrite_publication(output, publication)

    with pytest.raises(ValueError, match="unsafe ZIP member name"):
        verify_publication(output)
    assert not (tmp_path / "escape.txt").exists()


def test_publication_bundle_path_cannot_escape_root(synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path) -> None:
    run, _ = synthetic_run
    output = tmp_path / "publication"
    publish(run, output)
    publication = json.loads((output / PUBLICATION_NAME).read_text(encoding="utf-8"))
    publication["bundle_path"] = "../bundle.zip"
    _rewrite_publication(output, publication)

    with pytest.raises(ValueError, match="unsupported publication bundle path"):
        verify_publication(output)


def test_transport_v2_splits_identical_bundle_and_reads_without_v1_root(
    synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run, _ = synthetic_run
    v1_root = tmp_path / "publication-v1"
    v2_root = tmp_path / "publication-v2"
    manifest = _manifest(run)
    identity = manifest["identity"]
    filler_name = "tasks/20261010-hhhl-v4-probability/sources/transport-filler.bin"
    filler = b"".join(hashlib.sha256(index.to_bytes(8, "big")).digest() for index in range(27_000))
    _write_bytes(_checkout_for_identity(identity).joinpath(*filler_name.split("/")), filler)
    identity[filler_name.replace("/", "\\")] = _sha(filler)
    _rewrite_manifest(run, manifest)
    v1_metadata = publish(run, v1_root)
    v1_manifest_bytes = (v1_root / PUBLICATION_NAME).read_bytes()
    original_bundle = (v1_root / BUNDLE_NAME).read_bytes()

    assert main(["--split-publication", str(v1_root), "--output", str(v2_root)]) == 0
    metadata = json.loads(capsys.readouterr().out)

    assert (v1_root / PUBLICATION_NAME).read_bytes() == v1_manifest_bytes
    assert (v1_root / BUNDLE_NAME).read_bytes() == original_bundle
    assert not (v2_root / PUBLICATION_NAME).exists()
    assert not (v2_root / BUNDLE_NAME).exists()
    expected_files = {PUBLICATION_ARCHIVE_NAME}
    expected_files.update(part["path"] for part in metadata["bundle_parts"])
    assert {path.name for path in v2_root.iterdir()} == expected_files
    assert {key: metadata[key] for key in v1_metadata} == v1_metadata
    assert metadata["transport_schema"] == "hhhl-v4-probability-transport.v2"
    assert metadata["bundle_bytes"] == len(original_bundle)
    assert len(metadata["bundle_parts"]) == 3
    assert all(part["bytes"] <= MAX_TRANSPORT_PART_BYTES for part in metadata["bundle_parts"])
    with zipfile.ZipFile(v2_root / PUBLICATION_ARCHIVE_NAME) as archive:
        assert archive.namelist() == [PUBLICATION_NAME]
        assert json.loads(archive.read(PUBLICATION_NAME)) == metadata
    rebuilt = b"".join((v2_root / part["path"]).read_bytes() for part in metadata["bundle_parts"])
    assert rebuilt == original_bundle

    # Move only this test's temporary v1 fixture out of the way to prove v2 is standalone.
    v1_root.rename(tmp_path / "v1-source-preserved-elsewhere")
    verified = verify_publication(v2_root)
    assert verified["metadata"] == metadata
    assert verified["summaries"] == _summary_rows()
    assert main(["--publication", str(v2_root), "--family", "noise", "--horizon", "126"]) == 0
    query = json.loads(capsys.readouterr().out)
    assert len(query) == 4
    assert all(row["family"] == "noise" for row in query)
    assert query[0]["horizon"] == 126


def test_transport_v2_detects_tampered_part(synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path) -> None:
    run, _ = synthetic_run
    v1_root = tmp_path / "publication-v1"
    v2_root = tmp_path / "publication-v2"
    publish(run, v1_root)
    metadata = convert_publication(v1_root, v2_root)
    part_path = v2_root / metadata["bundle_parts"][0]["path"]
    data = bytearray(part_path.read_bytes())
    data[0] ^= 1
    part_path.write_bytes(data)

    with pytest.raises(ValueError, match="transport part hash/byte mismatch"):
        verify_publication(v2_root)


def test_transport_v2_rejects_duplicate_part_names(synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path) -> None:
    run, _ = synthetic_run
    v1_root = tmp_path / "publication-v1"
    v2_root = tmp_path / "publication-v2"
    publish(run, v1_root)
    metadata = convert_publication(v1_root, v2_root)
    metadata["bundle_parts"].append(metadata["bundle_parts"][0].copy())
    _rewrite_transport_archive(v2_root, metadata)

    with pytest.raises(ValueError, match="duplicate transport part path"):
        verify_publication(v2_root)


def test_transport_v2_rejects_traversal_part_path(synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path) -> None:
    run, _ = synthetic_run
    v1_root = tmp_path / "publication-v1"
    v2_root = tmp_path / "publication-v2"
    publish(run, v1_root)
    metadata = convert_publication(v1_root, v2_root)
    metadata["bundle_parts"][0]["path"] = "../outside.bin"
    _rewrite_transport_archive(v2_root, metadata)

    with pytest.raises(ValueError, match="unsafe ZIP member name"):
        verify_publication(v2_root)
    assert not (tmp_path / "outside.bin").exists()


def test_transport_v2_rejects_oversized_part(synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path) -> None:
    run, _ = synthetic_run
    v1_root = tmp_path / "publication-v1"
    v2_root = tmp_path / "publication-v2"
    publish(run, v1_root)
    metadata = convert_publication(v1_root, v2_root)
    part = metadata["bundle_parts"][0]
    oversized = b"x" * (MAX_TRANSPORT_PART_BYTES + 1)
    (v2_root / part["path"]).write_bytes(oversized)
    part["bytes"] = len(oversized)
    part["sha256"] = _sha(oversized)
    _rewrite_transport_archive(v2_root, metadata)

    with pytest.raises(ValueError, match="transport part exceeds 400000 bytes"):
        verify_publication(v2_root)


@pytest.mark.parametrize("transport", [False, True])
def test_publication_normalizes_deflate_failure(
    synthetic_run: tuple[Path, dict[str, bytes]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transport: bool
) -> None:
    run, _ = synthetic_run
    original = tmp_path / "publication-v1"
    publish(run, original)
    target = original
    if transport:
        target = tmp_path / "publication-v2"
        convert_publication(original, target)

    def broken_read(*_args: Any, **_kwargs: Any) -> bytes:
        raise zlib.error("synthetic invalid distance")

    monkeypatch.setattr(zipfile.ZipExtFile, "read", broken_read)
    message = "invalid transport publication archive" if transport else "cannot read ZIP member"
    with pytest.raises(ValueError, match=message) as failure:
        verify_publication(target)
    assert isinstance(failure.value.__cause__, zlib.error)
