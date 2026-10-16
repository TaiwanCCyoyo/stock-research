"""Dense integer summaries against a synthetic SQLite event-feed oracle."""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_core.pattern_scan_dense_counts_v1 import INT64_MAX, MAX_CELLS, DenseCounts
from research_core.pattern_scan_rates_v1 import REQUIRED_COLUMNS
from research_core.pattern_scan_summary_store_v1 import COUNT_FIELDS, YEARS, SummaryStore


def matrix(cell: str, stock: str = "0050", year: int = 2010, **counts: int) -> pd.DataFrame:
    return pd.DataFrame([{"cell_id": cell, "security_id": stock, "year": year, "horizon": 126, **dict.fromkeys(COUNT_FIELDS, 0), **counts}])


def test_synthetic_event_oracle_parity_and_year_stock_sets(tmp_path: Path) -> None:
    scratch = tmp_path / ".tmp"
    scratch.mkdir()
    rows = pd.DataFrame(
        [
            ("0050", "a", "2010-01-04", 126, "hit", True, True),
            ("0050", "b", "2011-01-04", 126, "loss", True, True),
            ("0050", "c", "2012-01-04", 126, "unknown", True, False),
            ("2330", "d", "2010-01-04", 126, "hit", True, True),
            ("2330", "e", "2011-01-04", 126, "hit", False, False),
            ("2330", "f", "2012-01-04", 126, "unknown", False, False),
        ],
        columns=pd.Index(REQUIRED_COLUMNS),
    )
    rows["event_eligibility_excluded"] = [False, False, True, False, True, False]
    with SummaryStore(scratch / "oracle.sqlite", scratch_root=scratch) as oracle:
        cell, empty = oracle.register_cells(({"pattern": "P1"}, {"pattern": "empty"}))
        for _, stock_rows in rows.groupby("security_id"):
            oracle.add_stock(cell, stock_rows)
        fields = ",".join(f"counts.{field}" for field in COUNT_FIELDS)
        with sqlite3.connect(oracle.path) as connection:
            supplied = pd.read_sql_query(
                f"SELECT counts.cell_id,security_id,year,cells.horizon,{fields} FROM counts JOIN cells ON counts.cell_id=cells.cell_id", connection
            )
        dense = DenseCounts((cell, empty), 126)
        for _, stock_matrix in supplied.groupby("security_id"):
            dense.add_stock(stock_matrix)
        for target in (cell, empty):
            assert dense.summarize(target) == oracle.summary(target)
            assert dense.annual_summary(target) == oracle.annual_summary(target)
            assert dense.drop_best_year(target) == oracle.drop_best_year(target)
            for year in YEARS:
                assert dense.summarize(target, exclude_year=year) == oracle.summary(target, exclude_year=year)
        assert dense.summarize(cell)["distinct_stock_n"] == 2
        assert dense.summarize(cell, exclude_year=2010)["distinct_stock_n"] == 2
        assert dense.summarize(cell)["per_stock_event_count_median"] == 3


def test_random_count_matrix_matches_public_store(tmp_path: Path) -> None:
    scratch = tmp_path / ".tmp"
    scratch.mkdir()
    rng = np.random.default_rng(20)
    with SummaryStore(scratch / "oracle.sqlite", scratch_root=scratch) as oracle:
        cells = oracle.register_cells(({"pattern": "P1"}, {"pattern": "L1"}))
        dense = DenseCounts(cells, 126)
        for stock in ("0050", "50", "2330"):
            records = []
            for cell in cells:
                for year in (2010, 2011, 2026):
                    counts = {field: int(rng.integers(0, 5)) for field in COUNT_FIELDS}
                    records.append(matrix(cell, stock, year, **counts))
            supplied = pd.concat(records, ignore_index=True)
            oracle.add_count_matrix(supplied)
            dense.add_stock(supplied)
        for cell in cells:
            assert dense.summarize(cell) == oracle.summary(cell)
            assert dense.annual_summary(cell) == oracle.annual_summary(cell)
            assert dense.drop_best_year(cell) == oracle.drop_best_year(cell)


def test_empty_and_zero_known_unknown_bounds_and_zero_hit_ties() -> None:
    dense = DenseCounts(("a", "b"), 126)
    assert dense.summarize("a")["hit_rate"] is None
    assert dense.drop_best_year("a")[0] is None
    dense.add_stock(matrix("a", event_n=1, unknown_n=1, full_calendar_n=1, full_calendar_unknown_n=1, full_main_potential_n=1, full_potential_unknown_n=1))
    result = dense.summarize("a")
    assert result["full_calendar_hit_lower_bound"] == 0
    assert result["full_calendar_hit_upper_bound"] == 1
    assert dense.drop_best_year("a")[0] == 2010
    assert len(dense.annual_summary("b")) == 17


@pytest.mark.parametrize(
    "column,value",
    [("cell_id", "missing"), ("security_id", 50), ("year", 2009), ("horizon", 252), ("hit_n", True), ("known_n", -1), ("event_n", 1.5), ("loss_n", 2**63)],
)
def test_invalid_feed_rolls_back_and_stock_can_retry(column: str, value: object) -> None:
    dense = DenseCounts(("a",), 126)
    valid = matrix("a", event_n=1)
    bad = valid.astype(object)
    bad.loc[0, column] = value
    with pytest.raises(ValueError):
        dense.add_stock(bad)
    assert dense.summarize("a")["event_n"] == 0
    dense.add_stock(valid)
    assert dense.summarize("a")["event_n"] == 1


def test_complete_stock_duplicate_and_matrix_duplicate_cannot_mutate() -> None:
    dense = DenseCounts(("a", "b"), 126)
    dense.add_stock(matrix("a", event_n=2))
    with pytest.raises(ValueError, match="duplicate complete"):
        dense.add_stock(matrix("b", event_n=1))
    assert dense.summarize("b")["event_n"] == 0
    other = matrix("b", "2330", event_n=1)
    with pytest.raises(ValueError, match="duplicate cell"):
        dense.add_stock(pd.concat([other, other], ignore_index=True))
    dense.add_stock(other)
    assert dense.summarize("b")["event_n"] == 1


def test_int64_overflow_checks_all_cells_before_mutation_including_year_sum() -> None:
    dense = DenseCounts(("a", "b"), 126)
    dense.add_stock(matrix("a", event_n=INT64_MAX))
    bad = pd.concat([matrix("b", "2330", event_n=1), matrix("a", "2330", 2011, event_n=1)], ignore_index=True)
    with pytest.raises(OverflowError, match="overflow"):
        dense.add_stock(bad)
    assert dense.summarize("a")["event_n"] == INT64_MAX
    assert dense.summarize("b")["event_n"] == 0
    dense.add_stock(matrix("b", "2330", event_n=1))


def test_storage_numeric_bytes_and_declared_limits() -> None:
    dense = DenseCounts(("a", "b"), 126)
    baseline = 2 * 17 * len(COUNT_FIELDS) * np.dtype(np.int64).itemsize
    assert dense.memory_nbytes == baseline
    dense.add_stock(pd.concat([matrix("a", event_n=2), matrix("a", year=2011, event_n=3), matrix("b")], ignore_index=True))
    assert dense.memory_nbytes == baseline + 2 * 3 * 8
    assert dense.summarize("a")["per_stock_event_count_max"] == 5
    dense.add_stock(matrix("a", "2330", event_n=7).iloc[:0])
    assert dense.memory_nbytes == baseline + 48 + 2 * 4 * 8 + 3 * 8
    with pytest.raises(ValueError):
        DenseCounts(("a", "a"), 126)
    with pytest.raises(ValueError):
        DenseCounts(tuple(str(index) for index in range(MAX_CELLS + 1)), 126)
    with pytest.raises(ValueError):
        DenseCounts(("a",), True)
    with pytest.raises(ValueError):
        dense.summarize("missing")


def test_lazy_cell_index_reused_and_invalidated_only_after_successful_feed() -> None:
    dense = DenseCounts(("a", "b", "c"), 126)
    dense.add_stock(pd.concat([matrix("a", event_n=2), matrix("a", year=2011, event_n=3), matrix("b", event_n=4)], ignore_index=True))
    assert dense.index_build_count == 0
    assert dense.summarize("a")["per_stock_event_count_max"] == 5
    assert dense.index_build_count == 1
    for _ in range(3):
        assert dense.summarize("b")["distinct_stock_n"] == 1
        assert dense.summarize("c")["distinct_stock_n"] == 0
        assert dense.summarize("a", exclude_year=2010)["per_stock_event_count_max"] == 3
        dense.annual_summary("a")
    assert dense.index_build_count == 1
    with pytest.raises(ValueError, match="duplicate complete"):
        dense.add_stock(matrix("a", event_n=1))
    assert dense.index_build_count == 1
    dense.add_stock(matrix("a", "2330", 2012, event_n=7))
    assert dense.index_build_count == 1
    result = dense.summarize("a")
    assert result["distinct_stock_n"] == 2 and result["per_stock_event_count_median"] == 6
    assert result["per_stock_event_count_max"] == 7
    assert dense.index_build_count == 2
    assert dense.summarize("a", only_year=2012)["distinct_stock_n"] == 1


def test_indexed_stock_sums_preserve_integer_counts_above_float_precision() -> None:
    dense = DenseCounts(("a",), 126)
    large = 2**53 + 1
    dense.add_stock(pd.concat([matrix("a", event_n=large), matrix("a", year=2011, event_n=2)], ignore_index=True))
    dense.add_stock(matrix("a", "2330", event_n=3))
    assert dense.summarize("a")["per_stock_event_count_max"] == large + 2
    assert dense.summarize("a", exclude_year=2011)["per_stock_event_count_max"] == large
    assert dense.index_build_count == 1
