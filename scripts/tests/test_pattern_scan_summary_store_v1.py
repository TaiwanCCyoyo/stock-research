"""Synthetic transaction, stock-set and integer aggregation contracts."""

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from research_core import pattern_scan_summary_store_v1 as module
from research_core.pattern_scan_rates_v1 import REQUIRED_COLUMNS, drop_best_hit_year, summarize_events
from research_core.pattern_scan_summary_store_v1 import COUNT_FIELDS, SummaryStore


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / ".tmp"
    root.mkdir()
    return root


def events() -> pd.DataFrame:
    data = [
        ("0050", "a", "2010-01-04", 126, "hit", True, True),
        ("0050", "b", "2011-01-04", 126, "loss", True, True),
        ("0050", "c", "2011-02-04", 126, "unknown", True, False),
        ("2330", "d", "2010-01-04", 126, "hit", True, True),
        ("2330", "e", "2012-01-04", 126, "unknown", True, False),
        ("2330", "f", "2012-02-04", 126, "hit", False, False),
        ("2330", "g", "2012-03-04", 126, "unknown", False, False),
    ]
    frame = pd.DataFrame(data, columns=pd.Index(REQUIRED_COLUMNS))
    frame["event_eligibility_excluded"] = [False, False, True, False, False, True, False]
    return frame


def feed(store: SummaryStore, cell: str, data: pd.DataFrame) -> None:
    for _, stock in data.groupby("security_id", sort=False):
        store.add_stock(cell, stock)


def test_stock_sets_cross_years_and_rates_derive_from_integer_sums(scratch: Path) -> None:
    data = events()
    with SummaryStore(scratch / "study.sqlite") as store:
        cell = store.register_cell({"pattern": "P1", "horizon": 126})
        assert cell == store.register_cell({"horizon": 126, "pattern": "P1"})
        feed(store, cell, data)
        assert store.summary(cell) == summarize_events(data)
        result = store.summary(cell)
        assert result["distinct_stock_n"] == 2
        assert result["per_stock_event_count_median"] == 3.5
        assert result["per_stock_event_count_max"] == 4
        assert result["full_main_potential_n"] == 4
        assert result["censored_potential_n"] == 1
        assert store.drop_best_year(cell) == drop_best_hit_year(data)
        annual = store.annual_summary(cell)
        assert len(annual) == 17
        for i, result in enumerate(annual):
            selected = data.loc[data.t0.str.startswith(str(2010 + i))]
            assert result == summarize_events(selected)


def test_duplicate_feed_and_bad_rows_cannot_double_count(scratch: Path) -> None:
    data = events().query("security_id == '0050'")
    with SummaryStore(scratch / "study.sqlite") as store:
        cell = store.register_cell({"pattern": "L1"})
        store.add_stock(cell, data)
        before = store.summary(cell)
        with pytest.raises(ValueError, match="duplicate stock"):
            store.add_stock(cell, data)
        assert store.summary(cell) == before
        bad = pd.concat([data, data.iloc[:1]], ignore_index=True)
        with pytest.raises(ValueError, match="duplicate"):
            store.add_stock(cell, bad)
        assert store.summary(cell) == before


def test_empty_cell_zero_rates_and_zero_hit_tie(scratch: Path) -> None:
    with SummaryStore(scratch / "study.sqlite") as store:
        cell = store.register_cell({"pattern": "empty"})
        zero = summarize_events(events().iloc[:0])
        assert store.summary(cell) == zero
        assert store.drop_best_year(cell) == (None, zero)
        assert store.annual_summary(cell) == (zero,) * 17
        nohit = events().iloc[[1]]
        store.add_stock(cell, nohit)
        assert store.drop_best_year(cell) == (2010, summarize_events(nohit))


def test_reject_mixed_stock_horizon_unknown_cell_and_year(scratch: Path) -> None:
    with SummaryStore(scratch / "study.sqlite") as store:
        cell = store.register_cell({})
        for data in (events(), events().iloc[:0]):
            with pytest.raises(ValueError, match="one stock"):
                store.add_stock(cell, data)
        mixed = events().iloc[:2].copy()
        mixed.loc[1, "horizon"] = 252
        with pytest.raises(ValueError, match="one stock"):
            store.add_stock(cell, mixed)
        old = events().iloc[:1].copy()
        old.loc[0, "t0"] = "2009-01-04"
        with pytest.raises(ValueError, match="2010"):
            store.add_stock(cell, old)
        with pytest.raises(ValueError, match="unknown cell"):
            store.summary("missing")
        with pytest.raises(ValueError, match="approved year"):
            store.summary(cell, exclude_year=2009)
        store.add_stock(cell, events().iloc[:1])
        other = events().iloc[[3]].copy()
        other.loc[3, "horizon"] = 252
        with pytest.raises(ValueError, match="horizon"):
            store.add_stock(cell, other)


def test_exclusive_file_and_context_required(scratch: Path) -> None:
    path = scratch / "study.sqlite"
    store = SummaryStore(path)
    with pytest.raises(ValueError, match="context"):
        store.register_cell({})
    with store:
        store.register_cell({})
    with pytest.raises(FileExistsError):
        with SummaryStore(path):
            pass
    with pytest.raises(ValueError, match="context"):
        store.summary("missing")


def test_explicit_primary_style_root_and_path_escape_rejected(scratch: Path, tmp_path: Path) -> None:
    primary = tmp_path / "primary" / ".tmp" / "run"
    primary.mkdir(parents=True)
    with SummaryStore(primary / "summary.sqlite", scratch_root=primary) as store:
        cell = store.register_cell({})
        assert store.summary(cell)["event_n"] == 0
    with pytest.raises(ValueError, match="inside"):
        SummaryStore(tmp_path / "outside.sqlite", scratch_root=primary)
    with pytest.raises(ValueError, match="traversal"):
        SummaryStore(primary / ".." / "outside.sqlite", scratch_root=primary)
    with pytest.raises(ValueError, match="absolute"):
        SummaryStore(scratch / "relative.sqlite", scratch_root=Path(".tmp"))
    with pytest.raises(ValueError, match="existing"):
        SummaryStore(scratch / "none.sqlite", scratch_root=scratch / "missing")


def test_integer_overflow_rejected_before_transaction(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = module.summarize_events

    def oversized(frame: pd.DataFrame) -> module.Summary:
        result = original(frame)
        result["event_n"] = 2**63
        return result

    with SummaryStore(scratch / "study.sqlite") as store:
        cell = store.register_cell({})
        with monkeypatch.context() as patch:
            patch.setattr(module, "summarize_events", oversized)
            with pytest.raises(ValueError, match="SQLite positive range"):
                store.add_stock(cell, events().iloc[:1])
        assert store.summary(cell)["event_n"] == 0
        store.add_stock(cell, events().iloc[:1])
        assert store.summary(cell)["event_n"] == 1


def count_matrix(path: Path) -> pd.DataFrame:
    """Read the invented oracle DB's committed integer rows, not its rates."""
    columns = ",".join(f"counts.{field}" for field in COUNT_FIELDS)
    with sqlite3.connect(path) as connection:
        return pd.read_sql_query(
            f"SELECT counts.cell_id,security_id,year,cells.horizon,{columns} FROM counts JOIN cells ON counts.cell_id=cells.cell_id", connection
        )


def test_batch_counts_equal_event_feed_oracle(scratch: Path) -> None:
    with SummaryStore(scratch / "oracle.sqlite") as oracle, SummaryStore(scratch / "batch.sqlite") as batch:
        cells = oracle.register_cells(({"pattern": "P1"}, {"pattern": "L1"}, {"pattern": "empty"}))
        assert batch.register_cells(({"pattern": "P1"}, {"pattern": "L1"}, {"pattern": "empty"})) == cells
        feed(oracle, cells[0], events())
        feed(oracle, cells[1], events().iloc[:2])
        matrix = count_matrix(oracle.path)
        batch.add_count_matrix(matrix.iloc[::-1])
        for cell in cells:
            assert batch.summary(cell) == oracle.summary(cell)
            assert batch.annual_summary(cell) == oracle.annual_summary(cell)
            assert batch.drop_best_year(cell) == oracle.drop_best_year(cell)
        batch.add_count_matrix(matrix.iloc[:0])


def test_partially_duplicate_matrix_is_atomic(scratch: Path) -> None:
    with SummaryStore(scratch / "oracle.sqlite") as oracle, SummaryStore(scratch / "batch.sqlite") as batch:
        cell = oracle.register_cell({})
        batch.register_cell({})
        feed(oracle, cell, events())
        matrix = count_matrix(oracle.path)
        first = matrix.loc[matrix.security_id.eq("0050")]
        batch.add_count_matrix(first)
        before = batch.summary(cell)
        with pytest.raises(ValueError, match="duplicate stock"):
            batch.add_count_matrix(matrix)
        assert batch.summary(cell) == before
        batch.add_count_matrix(matrix.loc[matrix.security_id.eq("2330")])
        assert batch.summary(cell) == oracle.summary(cell)


@pytest.mark.parametrize(
    "column,value",
    [
        ("event_n", -1),
        ("event_n", 2**63),
        ("hit_n", 1.5),
        ("known_n", True),
        ("year", 2009),
        ("year", "2010"),
        ("horizon", 0),
        ("security_id", 50),
        ("cell_id", "missing"),
    ],
)
def test_matrix_invalid_fields_fail_without_feeds(scratch: Path, column: str, value: object) -> None:
    with SummaryStore(scratch / "oracle.sqlite") as oracle, SummaryStore(scratch / "batch.sqlite") as batch:
        cell = oracle.register_cell({})
        batch.register_cell({})
        oracle.add_stock(cell, events().iloc[:1])
        matrix = count_matrix(oracle.path)
        bad = matrix.astype(object)
        bad.loc[0, column] = value
        with pytest.raises(ValueError):
            batch.add_count_matrix(bad)
        assert batch.summary(cell)["event_n"] == 0
        batch.add_count_matrix(matrix)
        assert batch.summary(cell)["event_n"] == 1


def test_matrix_rejects_mixed_cell_horizon_and_duplicate_year(scratch: Path) -> None:
    with SummaryStore(scratch / "oracle.sqlite") as oracle, SummaryStore(scratch / "batch.sqlite") as batch:
        cell = oracle.register_cell({})
        batch.register_cell({})
        oracle.add_stock(cell, events().iloc[:2])
        matrix = count_matrix(oracle.path)
        bad = matrix.copy()
        bad.loc[1, "horizon"] = 252
        with pytest.raises(ValueError, match="horizon"):
            batch.add_count_matrix(bad)
        with pytest.raises(ValueError, match="duplicate"):
            batch.add_count_matrix(pd.concat([matrix, matrix.iloc[:1]], ignore_index=True))
        batch.add_count_matrix(matrix)
        other = matrix.iloc[:1].copy()
        other["security_id"] = "2330"
        other["horizon"] = 252
        with pytest.raises(ValueError, match="horizon"):
            batch.add_count_matrix(other)


def test_batch_registration_order_duplicate_and_collision_rollback(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with SummaryStore(scratch / "batch.sqlite") as batch:
        ids = batch.register_cells(({"x": 1}, {"x": 2}, {"x": 1}))
        assert ids[0] == ids[2] and len(batch.cell_ids()) == 2
        assert batch.register_cells(()) == ()
        with monkeypatch.context() as patch:
            patch.setattr(module, "object_digest", lambda value: "collision")
            with pytest.raises(ValueError, match="collision"):
                batch.register_cells(({"new": 1}, {"new": 2}))
        assert len(batch.cell_ids()) == 2
        with monkeypatch.context() as patch:
            patch.setattr(module, "object_digest", lambda value: ids[0])
            with pytest.raises(ValueError, match="collision"):
                batch.register_cells(({"x": 999},))
        assert batch.metadata(ids[0]) == {"x": 1}
