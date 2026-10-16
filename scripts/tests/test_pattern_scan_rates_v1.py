"""Explicit denominator, overlapping counts and fixed-year removal checks."""

import pandas as pd
import pytest

from research_core.pattern_scan_rates_v1 import REQUIRED_COLUMNS, drop_best_hit_year, summarize_events


def rows() -> pd.DataFrame:
    values = [
        ("0050", "a", "2010-01-04", 126, "hit", True, True),
        ("0050", "b", "2011-01-04", 126, "loss", True, True),
        ("50", "c", "2012-01-04", 126, "flat-win", True, True),
        ("50", "d", "2013-01-04", 126, "unknown", True, False),
        ("2330", "e", "2014-01-04", 126, "hit", False, False),
        ("2330", "f", "2015-01-04", 126, "unknown", False, False),
        ("2330", "g", "2016-01-04", 126, "hit", True, False),
    ]
    return pd.DataFrame(values, columns=pd.Index(REQUIRED_COLUMNS))


def test_denominators_overlap_and_stock_identity() -> None:
    data = rows()
    before = data.copy(deep=True)
    result = summarize_events(data)
    assert result["event_n"] == 7 and result["distinct_stock_n"] == 3
    assert result["per_stock_event_count_median"] == 2
    assert result["per_stock_event_count_max"] == 3
    assert result["known_n"] == 3 and result["unknown_n"] == 2 and result["censored_n"] == 2
    assert result["excluded_known_n"] == 1
    assert (result["hit_n"], result["loss_n"], result["flat_win_n"]) == (1, 1, 1)
    assert result["hit_rate"] == pytest.approx(1 / 3)
    assert result["loss_rate"] == pytest.approx(1 / 3)
    assert result["observed_hit_n"] == 3
    assert result["full_calendar_n"] == 5
    assert result["full_calendar_observed_hit_n"] == 2
    assert result["full_calendar_unknown_n"] == 1
    assert result["full_main_potential_n"] == 4
    assert result["full_calendar_hit_lower_bound"] == 0.25
    assert result["full_calendar_hit_upper_bound"] == 0.5
    assert result["censored_unknown_n"] == 1 and result["censored_observed_hit_n"] == 1
    assert result["censored_potential_n"] == 2
    assert result["censored_hit_lower_bound"] == 0.5
    assert result["censored_hit_upper_bound"] == 1
    pd.testing.assert_frame_equal(data, before)


def test_empty_has_zero_counts_and_null_rates() -> None:
    result = summarize_events(rows().iloc[:0])
    assert result["event_n"] == result["known_n"] == result["distinct_stock_n"] == 0
    assert result["hit_rate"] is None and result["loss_rate"] is None
    assert result["full_calendar_hit_lower_bound"] is None
    assert result["censored_hit_lower_bound"] is None
    assert result["censored_hit_upper_bound"] is None
    assert result["per_stock_event_count_median"] is None
    assert drop_best_hit_year(rows().iloc[:0])[0] is None


def test_only_full_unknown_has_bounds_zero_one() -> None:
    result = summarize_events(rows().iloc[[3, 5]])
    assert result["known_n"] == 0 and result["hit_rate"] is None
    assert result["full_main_potential_n"] == 1
    assert result["full_calendar_hit_lower_bound"] == 0
    assert result["full_calendar_hit_upper_bound"] == 1


def test_explicit_unknown_and_censored_known_exclusions_preserve_counts_not_bounds() -> None:
    data = rows()
    data["event_eligibility_excluded"] = [False, False, False, True, True, False, True]
    result = summarize_events(data)
    assert result["unknown_n"] == 2 and result["censored_n"] == 2
    assert result["full_calendar_unknown_n"] == 1
    assert result["full_eligibility_excluded_n"] == 2
    assert result["censored_eligibility_excluded_n"] == 1
    assert result["full_main_potential_n"] == 3
    assert result["full_calendar_hit_lower_bound"] == pytest.approx(1 / 3)
    assert result["full_calendar_hit_upper_bound"] == pytest.approx(1 / 3)
    assert result["censored_potential_n"] == 1
    assert result["censored_hit_lower_bound"] == 0
    assert result["censored_hit_upper_bound"] == 1
    data.loc[5, "event_eligibility_excluded"] = True
    result = summarize_events(data.iloc[[3, 4, 5, 6]])
    assert result["full_main_potential_n"] == result["censored_potential_n"] == 0
    assert result["full_calendar_hit_lower_bound"] is None
    assert result["full_calendar_hit_upper_bound"] is None
    assert result["censored_hit_lower_bound"] is None
    assert result["censored_hit_upper_bound"] is None


@pytest.mark.parametrize("value", [1, "false", None])
def test_exclusion_column_requires_boolean(value: object) -> None:
    data = rows()
    data["event_eligibility_excluded"] = pd.Series([value] * len(data), dtype=object)
    with pytest.raises(ValueError, match="boolean"):
        summarize_events(data)


def test_main_eligible_and_explicit_excluded_is_invalid() -> None:
    data = rows()
    data["event_eligibility_excluded"] = True
    with pytest.raises(ValueError, match="exclusion"):
        summarize_events(data)


def test_best_year_uses_only_eligible_hits_and_removes_whole_same_year() -> None:
    data = rows()
    data.loc[1, "effective_label"] = "hit"
    data.loc[3, "t0"] = "2010-12-31"
    removed, result = drop_best_hit_year(data)
    assert removed == 2010
    assert result["event_n"] == 5 and result["unknown_n"] == 1
    assert result["known_n"] == 2 and result["hit_rate"] == 0.5


def test_best_year_zero_remainder_and_zero_hit_tie() -> None:
    removed, result = drop_best_hit_year(rows().iloc[:1])
    assert removed == 2010 and result["event_n"] == 0 and result["hit_rate"] is None
    removed, result = drop_best_hit_year(rows().iloc[[1]])
    assert removed == 2010 and result["event_n"] == 1


@pytest.mark.parametrize(
    "column,value",
    [
        ("security_id", 50),
        ("event_id", " "),
        ("t0", "20100104"),
        ("t0", "2010-02-30"),
        ("horizon", True),
        ("horizon", 0),
        ("horizon", 126.5),
        ("effective_label", "win"),
        ("calendar_full", 1),
        ("event_main_eligible", "true"),
    ],
)
def test_invalid_rows_fail(column: str, value: object) -> None:
    data = rows().astype(object)
    data.loc[0, column] = value
    with pytest.raises(ValueError):
        summarize_events(data)


@pytest.mark.parametrize("index", [3, 4])
def test_eligible_requires_known_full(index: int) -> None:
    data = rows()
    data.loc[index, "event_main_eligible"] = True
    with pytest.raises(ValueError, match="eligible"):
        summarize_events(data)


def test_duplicate_event_horizon_rejected_but_other_horizon_distinct() -> None:
    data = rows().iloc[:1]
    with pytest.raises(ValueError, match="duplicate"):
        summarize_events(pd.concat([data, data], ignore_index=True))
    other = data.copy()
    other.loc[0, "horizon"] = 252
    assert summarize_events(pd.concat([data, other], ignore_index=True))["event_n"] == 2


def test_missing_columns_and_invalid_years_fail() -> None:
    with pytest.raises(ValueError, match="columns"):
        summarize_events(rows().drop(columns="event_id"))
    for years in ((), (2010, 2010), (True,), (0,)):
        with pytest.raises(ValueError, match="years"):
            drop_best_hit_year(rows(), years=years)
