"""Synthetic batch counts only; no market IO."""

import math

import pytest

from research_core.hhhl_variants_rates import RateAccumulator, descriptive_flag_rates, trigger_return_summary


def counts(hit: int = 0, loss: int = 0, flat: int = 0, unknown: int = 0, censored_hit: int = 0, censored_unknown: int = 0, **extra: int) -> dict[str, int]:
    return dict(
        calendar_full_n=hit + loss + flat + unknown,
        hit_n=hit,
        loss_n=loss,
        flat_win_n=flat,
        unknown_n=unknown,
        censored_n=censored_hit + censored_unknown,
        censored_hit_n=censored_hit,
        censored_unknown_n=censored_unknown,
        **extra,
    )


def test_union_codes_unknown_bounds_and_censored_separation() -> None:
    accumulator = RateAccumulator()
    metadata = {"row_kind": "single", "feature_id": "D"}
    accumulator.add(("D",), metadata, 2019, counts(hit=1, loss=1, unknown=2, censored_hit=2), ("0050", "1234"))
    accumulator.add(("D",), metadata, 2020, counts(flat=1, censored_unknown=3), ("0050",))
    pooled = accumulator.finalize()[0]
    assert pooled["known_security_n"] == 2
    assert pooled["known_n"] == 3
    assert pooled["hit_rate"] == pytest.approx(1 / 3)
    assert pooled["loss_rate"] == pytest.approx(1 / 3)
    assert pooled["hit_lower"] == 0.2
    assert pooled["hit_upper"] == 0.6
    assert pooled["censored_n"] == 5
    assert pooled["censored_hit_lower"] == 0.4
    assert pooled["censored_hit_upper"] == 1.0
    assert pooled["small_sample"] is True


def test_drop_best_year_tie_removes_whole_year_and_reunions_codes() -> None:
    accumulator = RateAccumulator()
    metadata = {"row_kind": "candidate", "candidate_id": "a"}
    accumulator.add(("a",), metadata, 2022, counts(hit=2, flat=1, diagnostic_n=7), ("a", "b"))
    accumulator.add(("a",), metadata, 2020, counts(hit=2, loss=6, unknown=5, censored_hit=4, diagnostic_n=9), ("a", "c"))
    dropped = accumulator.finalize()[-1]
    assert dropped["removed_year"] == 2020
    assert dropped["hit_n"] == 2 and dropped["flat_win_n"] == 1
    assert dropped["unknown_n"] == dropped["loss_n"] == dropped["censored_hit_n"] == 0
    assert dropped["diagnostic_n"] == 7
    assert dropped["known_security_n"] == 2
    assert dropped["base_row_kind"] == "candidate"


def test_all_years_zero_rows_and_no_events_removed_year() -> None:
    accumulator = RateAccumulator()
    accumulator.add((), {"row_kind": "baseline"}, 2021, counts())
    rows = accumulator.finalize()
    assert len(rows) == 10
    assert [row["year"] for row in rows[1:9]] == list(range(2019, 2027))
    for row in rows:
        assert row["known_n"] == row["known_security_n"] == 0
        assert row["hit_rate"] is row["loss_rate"] is row["hit_lower"] is None
        assert row["censored_hit_lower"] is None
    assert rows[-1]["removed_year"] is None
    assert accumulator.finalize() == rows


def test_zero_hits_drop_earliest_year_with_any_events() -> None:
    accumulator = RateAccumulator()
    accumulator.add((), {"row_kind": "baseline"}, 2022, counts(unknown=2))
    accumulator.add((), {"row_kind": "baseline"}, 2020, counts(censored_unknown=1))
    assert accumulator.finalize()[-1]["removed_year"] == 2020


@pytest.mark.parametrize(
    "bad",
    [
        {"calendar_full_n": 1},
        {"hit_n": 1},
        {"censored_n": 2, "censored_hit_n": 1},
        {"unknown_n": -1},
        {"calendar_full_n": True},
        {"diagnostic_n": 1.5},
        {"known_n": 1},
        {"hit_rate": 1},
    ],
)
def test_invalid_counts_are_atomic(bad: dict[str, int]) -> None:
    accumulator = RateAccumulator()
    with pytest.raises(ValueError):
        accumulator.add((), {"row_kind": "baseline"}, 2020, bad)
    assert accumulator.finalize() == []


def test_metadata_inconsistent_repeated_key_and_mutation_are_rejected() -> None:
    accumulator = RateAccumulator()
    metadata = {"row_kind": "baseline", "extra": {"cohort": "P-clean"}}
    accumulator.add((), metadata, 2020, counts(hit=1), ("0050",))
    metadata["extra"]["cohort"] = "P-over"  # type: ignore[index]
    with pytest.raises(ValueError, match="inconsistent metadata"):
        accumulator.add((), metadata, 2020, counts(hit=1), ("0050",))
    assert accumulator.finalize()[0]["hit_n"] == 1
    assert accumulator.finalize()[0]["extra"] == {"cohort": "P-clean"}


@pytest.mark.parametrize("year", [2018, 2027, True, 2020.0])
def test_invalid_year(year: int) -> None:
    with pytest.raises(ValueError, match="2019"):
        RateAccumulator().add((), {"row_kind": "baseline"}, year, counts())


def test_known_codes_must_be_valid_and_cannot_include_unknown_only_security() -> None:
    with pytest.raises(ValueError, match="known events"):
        RateAccumulator().add((), {"row_kind": "baseline"}, 2020, counts(unknown=1), ("0050",))
    with pytest.raises(ValueError, match="string codes"):
        RateAccumulator().add((), {"row_kind": "baseline"}, 2020, counts(hit=1), ("",))


def test_flag_known_rate_and_full_bounds_include_unknown() -> None:
    result = descriptive_flag_rates(2, 3, 5)
    assert result["known_n"] == 5 and result["all_n"] == 10
    assert result["known_rate"] == 0.4
    assert result["lower"] == 0.2 and result["upper"] == 0.7
    assert descriptive_flag_rates(0, 0, 2)["known_rate"] is None
    assert descriptive_flag_rates(0, 0, 2)["upper"] == 1
    assert descriptive_flag_rates(0, 0, 0)["lower"] is None
    with pytest.raises(ValueError):
        descriptive_flag_rates(0, -1, 0)


def test_trigger_return_quantiles_linear_and_unknown_counts() -> None:
    summary = trigger_return_summary([0.3, None, -0.1, math.nan, math.inf, 0.1])
    assert summary["trigger_return_n"] == 3
    assert summary["trigger_return_unknown_n"] == 3
    assert summary["trigger_return_p10"] == pytest.approx(-0.06)
    assert summary["trigger_return_median"] == 0.1
    assert summary["trigger_return_p90"] == pytest.approx(0.26)
    assert trigger_return_summary([0.5])["trigger_return_p10"] == 0.5
    assert trigger_return_summary([])["trigger_return_median"] is None
