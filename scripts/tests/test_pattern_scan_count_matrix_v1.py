"""Public-summary parity and integer membership sums over invented events."""

from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core.pattern_scan_count_matrix_v1 import aggregate_memberships, event_count_vectors
from research_core.pattern_scan_rates_v1 import summarize_events
from research_core.pattern_scan_summary_store_v1 import COUNT_FIELDS


def rows(seed: int = 42, size: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    labels = rng.choice(["hit", "loss", "flat-win", "unknown"], size=size)
    full = rng.choice([True, False], size=size)
    excluded = rng.choice([True, False], size=size)
    eligible = full & (labels != "unknown") & ~excluded
    return pd.DataFrame({
        "security_id": "TW:001",
        "event_id": [f"synthetic:{index}" for index in range(size)],
        "t0": [f"{2010 + index % 17}-01-04" for index in range(size)],
        "horizon": 126,
        "base_label": "hit",
        "effective_label": labels,
        "calendar_full": full,
        "event_main_eligible": eligible,
        "event_eligibility_excluded": excluded,
    })


def assert_oracle(frame: pd.DataFrame, counts: pd.Series) -> None:
    summary = summarize_events(frame)
    for field in COUNT_FIELDS[:-3]:
        assert counts[field] == summary[field]
    full = cast(pd.Series, frame["calendar_full"])
    unknown = cast(pd.Series, frame["effective_label"]).eq("unknown")
    eligible = cast(pd.Series, frame["event_main_eligible"])
    excluded = cast(pd.Series, frame["event_eligibility_excluded"]) if "event_eligibility_excluded" in frame else full & ~unknown & ~eligible
    assert counts.full_potential_unknown_n == (full & ~excluded & unknown).sum()
    assert counts.censored_potential_hit_n == (~full & ~excluded & frame.effective_label.eq("hit")).sum()
    assert counts.censored_potential_unknown_n == (~full & ~excluded & unknown).sum()
    if counts.full_main_potential_n:
        assert counts.hit_n / counts.full_main_potential_n == summary["full_calendar_hit_lower_bound"]
        assert (counts.hit_n + counts.full_potential_unknown_n) / counts.full_main_potential_n == summary["full_calendar_hit_upper_bound"]
    if counts.censored_potential_n:
        assert counts.censored_potential_hit_n / counts.censored_potential_n == summary["censored_hit_lower_bound"]
        assert (counts.censored_potential_hit_n + counts.censored_potential_unknown_n) / counts.censored_potential_n == summary["censored_hit_upper_bound"]


@pytest.mark.parametrize("seed", [1, 42, 399])
@pytest.mark.parametrize("explicit", [True, False])
def test_vectors_match_public_counts_and_bounds(seed: int, explicit: bool) -> None:
    frame = rows(seed)
    if not explicit:
        frame = frame.drop(columns="event_eligibility_excluded")
    original = frame.copy(deep=True)
    vectors = event_count_vectors(frame)
    assert tuple(vectors.columns) == COUNT_FIELDS
    assert vectors.index.name == "event_id"
    assert vectors.index.tolist() == frame.event_id.tolist()
    assert all(dtype == np.dtype("int64") for dtype in vectors.dtypes)
    assert np.isin(vectors.to_numpy(), (0, 1)).all()
    assert_oracle(frame, cast(pd.Series, vectors.sum()))
    pd.testing.assert_frame_equal(frame, original)


def test_every_one_event_vector_is_exact_oracle() -> None:
    frame = rows(size=50)
    vectors = event_count_vectors(frame)
    for index in range(len(frame)):
        assert_oracle(frame.iloc[[index]], cast(pd.Series, vectors.iloc[index]))


def test_multifacet_memberships_integer_year_accumulation_and_unmodified_inputs() -> None:
    frame = rows(size=80)
    members = pd.DataFrame([
        {"event_id": event, "cell_id": cell} for index, event in enumerate(frame.event_id) for cell in ("all", "even" if index % 2 == 0 else "odd")
    ])
    originals = frame.copy(deep=True), members.copy(deep=True)
    result = aggregate_memberships(frame, members)
    assert list(result.columns) == ["cell_id", "security_id", "year", "horizon", *COUNT_FIELDS]
    assert result.event_n.sum() == 2 * len(frame)
    for supplied in result.to_dict("records"):
        row = cast(dict[str, Any], supplied)
        subset = frame.loc[frame.t0.str.startswith(str(row["year"]))]
        if row["cell_id"] != "all":
            indices = np.arange(len(frame)) % 2 == (0 if row["cell_id"] == "even" else 1)
            subset = subset.loc[indices[subset.index]]
        assert_oracle(subset, pd.Series(row))
    pd.testing.assert_frame_equal(frame, originals[0])
    pd.testing.assert_frame_equal(members, originals[1])


def test_membership_order_does_not_change_counts() -> None:
    frame = rows(size=20)
    members = pd.DataFrame({"event_id": frame.event_id, "cell_id": "all"})
    expected = aggregate_memberships(frame, members)
    actual = aggregate_memberships(frame.sample(frac=1, random_state=1), members.sample(frac=1, random_state=2))
    pd.testing.assert_frame_equal(actual, expected)


def test_empty_vectors_and_empty_memberships_keep_integer_schemas() -> None:
    frame = rows(size=0)
    vectors = event_count_vectors(frame)
    assert vectors.empty and tuple(vectors.columns) == COUNT_FIELDS
    assert_oracle(frame, cast(pd.Series, vectors.sum()))
    members = pd.DataFrame({"event_id": pd.Series(dtype=object), "cell_id": pd.Series(dtype=object)})
    empty = aggregate_memberships(frame, members)
    assert empty.empty and list(empty.columns) == ["cell_id", "security_id", "year", "horizon", *COUNT_FIELDS]
    assert all(empty[field].dtype == np.dtype("int64") for field in COUNT_FIELDS)
    pd.testing.assert_frame_equal(aggregate_memberships(rows(size=20), members), empty)


@pytest.mark.parametrize(
    "invalid", ["duplicate_membership", "unknown_event", "multiple_stock", "multiple_horizon", "year", "duplicate_event", "eligible_unknown"]
)
def test_invalid_batches_fail_without_partial_output(invalid: str) -> None:
    frame = rows(size=20)
    members = pd.DataFrame({"event_id": frame.event_id, "cell_id": "all"})
    if invalid == "duplicate_membership":
        members = pd.concat([members, members.iloc[:1]])
    elif invalid == "unknown_event":
        members.loc[0, "event_id"] = "absent"
    elif invalid == "multiple_stock":
        frame.loc[0, "security_id"] = "TW:002"
    elif invalid == "multiple_horizon":
        frame.loc[0, "horizon"] = 252
    elif invalid == "year":
        frame.loc[0, "t0"] = "2009-01-04"
    elif invalid == "duplicate_event":
        frame.loc[0, "event_id"] = frame.event_id.iloc[1]
    else:
        frame.loc[0, ["effective_label", "calendar_full", "event_main_eligible", "event_eligibility_excluded"]] = ["unknown", True, True, False]
    with pytest.raises(ValueError):
        aggregate_memberships(frame, members)
