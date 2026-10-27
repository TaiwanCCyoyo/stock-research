"""Bounded synthetic contracts only: no producer/shared paths or file loaders."""

from __future__ import annotations

from dataclasses import replace
from itertools import chain

import numpy as np
import pandas as pd
import pytest

from research_core import entry_window_v1 as entry
from research_core import momentum_only_v1 as canonical
from research_core.multiple_outcomes_v1 import outcomes_for_targets


def _stock(close: list[float] | np.ndarray, code: str = "synthetic-A") -> canonical.StockDaily:
    prices = np.asarray(close, dtype=np.float64)
    n = len(prices)
    labels, main, full = {}, {}, {}
    for horizon in canonical.HORIZONS:
        for target, frame in outcomes_for_targets(prices, horizon, canonical.TARGETS).items():
            labels[horizon, target] = np.asarray([canonical.LABEL_CODES[v] for v in frame["label"]], dtype=np.int8)
            main[horizon, target] = frame["main_eligible"].to_numpy(dtype=bool)
            full[horizon] = frame["calendar_full"].to_numpy(dtype=bool)
    return canonical.StockDaily(
        code,
        "synthetic",
        np.ones(n, dtype=bool),
        np.zeros(n, dtype=bool),
        np.zeros(n, dtype=bool),
        {a: np.ones(n, dtype=np.int8) for a in ("A1", "A2", "A3")},
        np.full(n, np.nan),
        labels,
        main,
        full,
    )


def _quotes(calendar: pd.DatetimeIndex, code: str = "synthetic-A") -> entry.Quotes:
    n = len(calendar)
    return entry.Quotes(
        code,
        calendar,
        np.full(n, 100.0),
        np.full(n, 110.0),
        np.full(n, 90.0),
        np.full(n, 100.0),
        np.zeros(n, dtype=np.int8),
        np.ones(n, dtype=np.int8),
        np.ones(n, dtype=np.int8),
    )


def _row(
    rows: tuple[entry.CountRow, ...], arm: str, band: str | None = None, *, cadence: str = "daily", label: tuple[int, float] = (126, 2.0)
) -> dict[str, int]:
    selected = [r for r in rows if r.set_id == "CORE" and r.cadence == cadence and r.band_id == band and r.label == label and r.arm == arm]
    return dict(zip(entry.METRICS, (sum(r.counts[i] for r in selected) for i in range(len(entry.METRICS))), strict=True))


def test_grid_is_exact_and_contains_no_extra_outcomes() -> None:
    assert [(b.band_id, b.lower, b.upper) for b in entry.BANDS] == [
        ("B01", 0.97, 1.0),
        ("B02", 0.97, 1.02),
        ("B03", 0.97, 1.05),
        ("B04", 1.0, 1.0),
        ("B05", 1.0, 1.02),
        ("B06", 1.0, 1.05),
    ]
    assert [c.cell_id for c in entry.COMPARISONS if c.primary] == [f"M{i:02}" for i in range(1, 25)]
    assert [c.cell_id for c in entry.COMPARISONS if not c.primary] == [f"S{i:02}" for i in range(1, 13)]
    assert {(c.set_id, c.band_id, c.label) for c in entry.COMPARISONS} == {
        (s, b.band_id, label) for s in entry.SET_KEYS for b in entry.BANDS for label in entry.LABELS
    }


def test_next_session_never_skips_missing_quote_and_retains_saturday() -> None:
    calendar = pd.DatetimeIndex(["2018-12-28", "2018-12-29", "2019-01-02", "2019-01-03"])
    q = _quotes(calendar)
    q.raw_open[1] = np.nan
    q.raw_close[-1] = np.nan
    masks = entry.classify_quotes(calendar, q)
    assert masks.primary_reason == ("no_open", None, None, "no_next_session")
    assert masks.quote_known.tolist() == [False, True, True, False]
    assert masks.reasons["invalid_raw_close"][-1]
    q.raw_close[0] = 0
    assert entry.classify_quotes(calendar, q).primary_reason[0] == "invalid_raw_close"


@pytest.mark.parametrize("band", entry.BANDS, ids=lambda b: b.band_id)
@pytest.mark.parametrize("close", [10.0, 99.9, 100.0])
def test_every_exact_endpoint_and_immediate_neighbor(band: entry.Band, close: float) -> None:
    calendar = pd.date_range("2019-01-01", periods=2)
    a, b = close * band.lower, close * band.upper
    for opening, expected in ((np.nextafter(a, -np.inf), "below"), (a, "accepted"), (b, "accepted"), (np.nextafter(b, np.inf), "above")):
        q = _quotes(calendar)
        q.raw_close[:] = close
        q.raw_open[1] = opening
        masks = entry.classify_quotes(calendar, q).bands[band.band_id]
        assert [name for name in ("accepted", "above", "below") if getattr(masks, name)[0]] == [expected]
    if a < b:
        q = _quotes(calendar)
        q.raw_close[:] = close
        q.raw_open[1] = np.nextafter(a, np.inf)
        assert entry.classify_quotes(calendar, q).bands[band.band_id].accepted[0]
        q.raw_open[1] = np.nextafter(b, -np.inf)
        assert entry.classify_quotes(calendar, q).bands[band.band_id].accepted[0]


@pytest.mark.parametrize("dtype", [np.float16, np.float32])
@pytest.mark.parametrize("band", entry.BANDS, ids=lambda b: b.band_id)
def test_mixed_precision_close_and_float64_endpoints_are_explicitly_rejected(dtype: type[np.float16] | type[np.float32], band: entry.Band) -> None:
    calendar = pd.date_range("2019-01-01", periods=2)
    for opening in (10.0 * band.lower, 10.0 * band.upper):
        q = _quotes(calendar)
        q.raw_close[:] = 10.0
        q.raw_open[1] = opening
        mixed = replace(q, raw_close=q.raw_close.astype(dtype))
        with pytest.raises(ValueError, match="raw_close.*float64"):
            entry.classify_quotes(calendar, mixed)


@pytest.mark.parametrize("dtype", [np.float16, np.float32])
@pytest.mark.parametrize("name", ["raw_open", "raw_high", "raw_low", "raw_close"])
def test_every_raw_price_vector_requires_float64(name: str, dtype: type[np.float16] | type[np.float32]) -> None:
    calendar = pd.date_range("2019-01-01", periods=2)
    q = _quotes(calendar)
    mixed = replace(q, **{name: getattr(q, name).astype(dtype)})
    with pytest.raises(ValueError, match=f"{name}.*float64"):
        entry.classify_quotes(calendar, mixed)


@pytest.mark.parametrize("dtype", [np.float16, np.float32])
@pytest.mark.parametrize("name", ["lower", "upper"])
def test_official_limit_bounds_require_float64(name: str, dtype: type[np.float16] | type[np.float32]) -> None:
    calendar = pd.date_range("2019-01-01", periods=2)
    q = _quotes(calendar)
    limits = entry.OfficialLimits("synthetic official fixture", np.full(2, 90.0), np.full(2, 110.0), np.ones(2, dtype=np.int8))
    mixed_limits = replace(limits, **{name: getattr(limits, name).astype(dtype)})
    with pytest.raises(ValueError, match=f"official {name}.*float64"):
        entry.classify_quotes(calendar, replace(q, official_limits=mixed_limits))


def test_range_touch_does_not_change_open_and_unknown_diagnostics_stay_unknown() -> None:
    calendar = pd.date_range("2019-01-01", periods=3)
    q = _quotes(calendar)
    q.raw_open[1] = 109
    masks = entry.classify_quotes(calendar, q)
    assert all(m.above[0] and m.range_touch[0] == entry.TRUE for m in masks.bands.values())
    assert masks.limit_status == ("unknown",) * 3
    q.raw_high[1] = np.nan
    q.raw_close[1] = np.nan
    masks = entry.classify_quotes(calendar, q)
    assert masks.one_price[0] == entry.UNKNOWN
    assert all(m.above[0] and m.range_touch[0] == entry.UNKNOWN for m in masks.bands.values())
    assert all(not m.above[1] and not m.below[1] for m in masks.bands.values())
    q.raw_high[1], q.raw_low[1] = 90, 110
    assert all(m.range_touch[0] == entry.UNKNOWN for m in entry.classify_quotes(calendar, q).bands.values())


def test_one_price_and_explicit_official_limits_are_independent_diagnostics() -> None:
    calendar = pd.date_range("2019-01-01", periods=4)
    q = _quotes(calendar)
    for values in (q.raw_open, q.raw_high, q.raw_low, q.raw_close):
        values[1] = 110
    masks = entry.classify_quotes(calendar, q)
    assert masks.one_price[0] == entry.TRUE and masks.one_price[1] == entry.FALSE
    assert masks.limit_status[0] == "unknown"
    limits = entry.OfficialLimits("synthetic official fixture", np.full(4, 90.0), np.full(4, 110.0), np.ones(4, dtype=np.int8))
    masks = entry.classify_quotes(calendar, replace(q, official_limits=limits))
    assert masks.limit_status[:3] == ("at_upper", "inside", "inside")
    limits.quality[1] = entry.UNKNOWN
    assert entry.classify_quotes(calendar, replace(q, official_limits=limits)).limit_status[0] == "unknown"
    q.raw_low[1] = np.nan
    assert entry.classify_quotes(calendar, q).one_price[0] == entry.UNKNOWN


def test_multiple_quality_exclusions_share_one_m_without_double_counting() -> None:
    calendar = pd.date_range("2019-01-01", periods=4)
    q = _quotes(calendar)
    q.action_to_next[0] = entry.TRUE
    q.event_quality_to_next[0] = entry.UNKNOWN
    q.quote_quality_to_next[0] = entry.FALSE
    q.action_to_next[1] = entry.UNKNOWN
    masks = entry.classify_quotes(calendar, q)
    assert masks.one_price[0] == entry.UNKNOWN
    assert all(b.range_touch[0] == entry.UNKNOWN for b in masks.bands.values())
    stock = _stock([10, 11, 12, 13])
    out = entry.count_stock(calendar, stock, q)
    assert _row(out.rows, "S")["event_n"] == 4
    assert _row(out.rows, "Q")["event_n"] == 3
    assert _row(out.rows, "M")["event_n"] == 1
    assert _row(out.rows, "Q_minus_M")["event_n"] == 2
    diagnostic = out.diagnostics[0].counts
    assert diagnostic["reason:corporate_action"] == diagnostic["reason:event_quality_unknown"] == diagnostic["reason:quote_quality_invalid"] == 1
    for band in entry.BANDS:
        assert _row(out.rows, "accepted", band.band_id)["event_n"] + _row(out.rows, "rejected", band.band_id)["event_n"] == 1


def test_unrepresentable_quote_ratio_is_unknown_without_above_below_or_rounding() -> None:
    calendar = pd.date_range("2019-01-01", periods=2)
    q = _quotes(calendar)
    q.raw_close[0], q.raw_open[1] = 1e-300, 1e300
    masks = entry.classify_quotes(calendar, q)
    assert masks.primary_reason[0] == "invalid_quote_ratio" and not masks.quote_known[0]
    assert all(not b.accepted[0] and not b.above[0] and not b.below[0] for b in masks.bands.values())


def test_cool_before_quotes_bands_or_years_and_never_replace_rejected_signals() -> None:
    calendar = pd.date_range("2018-12-20", periods=50)
    stock = _stock(np.full(50, 10.0))
    stock.eligible[:] = False
    stock.eligible[[0, 20, 21, 40, 42]] = True
    q = _quotes(calendar)
    q.raw_open[1] = np.nan
    q.raw_open[22] = 110
    out = entry.count_stock(calendar, stock, q)
    assert np.flatnonzero(canonical.cooled(np.ones(50, dtype=bool), stock.eligible)).tolist() == [0, 21, 42]
    assert _row(out.rows, "S", cadence="cooled20")["event_n"] == 3
    assert _row(out.rows, "M", cadence="cooled20")["event_n"] == 2
    for band in entry.BANDS:
        assert _row(out.rows, "accepted", band.band_id, cadence="cooled20")["event_n"] == 1
        assert _row(out.rows, "above", band.band_id, cadence="cooled20")["event_n"] == 1
    q.raw_open[1] = 100
    changed = entry.count_stock(calendar, stock, q)
    assert [r for r in out.rows if r.arm == "S"] == [r for r in changed.rows if r.arm == "S"]
    assert [r for r in out.rows if r.arm == "M"] != [r for r in changed.rows if r.arm == "M"]


@pytest.mark.parametrize(
    ("closes", "expected"),
    [
        ([10.0, 11.0], (0, 0, 0, 0, 1, 1, 0)),
        ([10.0, np.nan, 30.0], (0, 0, 0, 0, 1, 1, 0)),
        ([10.0, 20.0], (0, 0, 0, 0, 0, 1, 0)),
        ([10.0] + [20.0] * 126, (1, 1, 0, 0, 0, 0, 0)),
        ([10.0] + [9.0] * 126, (1, 0, 1, 0, 0, 0, 0)),
        ([10.0] + [11.0] * 126, (1, 0, 0, 1, 0, 0, 0)),
        ([10.0, np.nan] + [30.0] * 125, (0, 0, 0, 0, 1, 0, 1)),
    ],
)
@pytest.mark.parametrize("opening", [100.0, 110.0])
def test_real_canonical_outcomes_keep_censored_unknown_overlap_and_all_arms(closes: list[float], expected: tuple[int, ...], opening: float) -> None:
    calendar = pd.date_range("2019-01-01", periods=len(closes))
    stock = _stock(closes)
    stock.eligible[1:] = False
    q = _quotes(calendar)
    q.raw_open[1] = opening
    rows = entry.count_stock(calendar, stock, q).rows
    m = _row(rows, "M")
    assert tuple(m[name] for name in entry.METRICS[1:]) == expected
    assert m["event_n"] == m["known_n"] + m["full_unknown_n"] + m["censored_n"] == 1
    arm = "accepted" if opening == 100 else "rejected"
    assert _row(rows, arm, "B04") == m
    if closes == [10.0, 20.0]:
        assert stock.labels[126, 2.0][0] == canonical.LABEL_CODES["hit"] and m["hit_n"] == 0


def test_every_count_matches_canonical_membership_and_quality_overlay() -> None:
    n = 530
    calendar = pd.date_range("2018-12-01", periods=n)
    stock = _stock(np.linspace(10, 35, n))
    stock.atoms["A3"][::3] = entry.FALSE
    stock.atoms["A1"][::5] = entry.UNKNOWN
    stock.jump[2] = True
    stock.eligible[::7] = False
    q = _quotes(calendar)
    q.raw_open[1::4] = 110
    q.raw_open[2::4] = 90
    q.raw_open[3::19] = np.nan
    q.event_quality_to_next[::23] = entry.UNKNOWN
    masks = entry.classify_quotes(calendar, q)
    out = entry.count_stock(calendar, stock, q)
    session_years = canonical.calendar_years(calendar)
    years = tuple(sorted(set(session_years)))
    yi = np.searchsorted(years, session_years).astype(np.intp)
    for s, canonical_key in entry.SET_KEYS.items():
        for cadence in entry.CADENCES:
            _, lookback, cool = canonical.groups()[f"{canonical_key}:{'cooled' if cadence == 'cooled20' else 'daily'}"]
            signal = canonical.set_members(stock.atoms, canonical.condition_sets()[canonical_key]) & stock.eligible
            signal = canonical.cooled(signal, stock.eligible) if cool else signal
            for band_id, band in masks.bands.items():
                for arm, mask in (
                    ("M", masks.clean),
                    ("accepted", band.accepted),
                    ("rejected", band.above | band.below),
                    ("above", band.above),
                    ("below", band.below),
                ):
                    expected = canonical.group_counts(stock, signal & mask, lookback=lookback, year_index=yi, n_years=len(years))
                    selected = [
                        r for r in out.rows if r.set_id == s and r.cadence == cadence and r.arm == arm and r.band_id == (None if arm == "M" else band_id)
                    ]
                    for row in selected:
                        assert row.counts == tuple(int(v) for v in expected[canonical.LABELS.index(row.label), years.index(row.t0_year)])
    # One full-calendar hit becomes full_unknown under the canonical result overlay.
    assert _row(out.rows, "S")["full_unknown_n"] > 0


def test_integer_partition_reassembly_distinct_union_empty_eras_and_null_rates() -> None:
    calendar = pd.date_range("2018-12-20", periods=150)
    a = entry.count_stock(calendar, _stock(np.linspace(10, 35, 150)), _quotes(calendar))
    b = entry.count_stock(calendar, _stock(np.full(150, 10.0), "synthetic-B"), _quotes(calendar, "synthetic-B"))
    whole = entry.aggregate_rows(chain(a.rows, b.rows))
    parts = [[r for r in chain(a.rows, b.rows) if r.t0_year == year] for year in (2018, 2019)]
    assert entry.aggregate_rows(chain.from_iterable(parts)) == whole
    key = entry.SummaryKey("CORE", "daily", None, (126, 2.0), "all", "M")
    assert whole[key].distinct_stock_n == 2
    assert sum(whole[replace(key, era=era)].distinct_stock_n for era in ("2013-2018", "2019+")) == 4
    assert whole[key].counts[0] == 298  # common M stored once, not six times
    empty = entry.comparison_rates(whole, entry.COMPARISONS[0], "daily", "2010-2012")
    assert all(value is None for value in empty.values())
    rates = entry.comparison_rates(whole, entry.COMPARISONS[0], "daily", "all")
    assert rates["quote_accept_rate"] == 1 and rates["accepted_hit_diff"] == 0
    with pytest.raises(ValueError, match="duplicate"):
        entry.aggregate_rows(chain(a.rows, a.rows))
    huge = 2**63
    row = replace(a.rows[0], counts=(huge, huge, huge, 0, 0, 0, 0, 0))
    summed = entry.aggregate_rows([row, replace(row, security_id="synthetic-C")])
    assert summed[entry.SummaryKey(row.set_id, row.cadence, row.band_id, row.label, "all", row.arm)].counts[0] == 2**64
    assert all(value is None for value in entry.comparison_rates(entry.aggregate_rows([]), entry.COMPARISONS[0], "daily", "all").values())


def test_rates_use_known_denominators_and_rejected_hit_share_is_not_arm_hit_rate() -> None:
    def summary(values: tuple[int, ...]) -> entry.Summary:
        return entry.Summary(values, frozenset(), frozenset())

    cell = entry.COMPARISONS[0]
    key = entry.SummaryKey("CORE", "daily", None, cell.label, "all", "M")
    data = {
        key: summary((12, 10, 4, 4, 2, 2, 1, 1)),
        replace(key, band_id="B01", arm="accepted"): summary((7, 6, 3, 2, 1, 1, 1, 0)),
        replace(key, band_id="B01", arm="rejected"): summary((5, 4, 1, 2, 1, 1, 0, 1)),
        replace(key, band_id="B01", arm="above"): summary((5, 4, 1, 2, 1, 1, 0, 1)),
        replace(key, band_id="B01", arm="below"): summary((0,) * 8),
    }
    rates = entry.comparison_rates(data, cell, "daily", "all")
    assert rates["quote_accept_rate"] == 7 / 12
    assert rates["accepted_hit_diff"] == pytest.approx(0.5 - 0.4)
    assert rates["accepted_loss_diff"] == pytest.approx(2 / 6 - 0.4)
    assert rates["rejected_hit_share"] == 0.25
    data[replace(key, band_id="B01", arm="accepted")] = summary((7, 6, 3, 2, 1, 0, 1, 0))
    with pytest.raises(ValueError, match="conserve"):
        entry.comparison_rates(data, cell, "daily", "all")


@pytest.mark.parametrize(
    "defect", ["length", "duplicate", "unordered", "shifted", "enum", "bool_state", "code", "stock_length", "label_enum", "missing_atom", "missing_label"]
)
def test_malformed_or_unaligned_inputs_are_rejected(defect: str) -> None:
    calendar = pd.date_range("2019-01-01", periods=3)
    stock, q = _stock([10, 11, 12]), _quotes(calendar)
    if defect == "length":
        q = replace(q, raw_open=np.array([100.0]))
    elif defect == "duplicate":
        calendar = pd.DatetimeIndex([calendar[0], calendar[0], calendar[2]])
    elif defect == "unordered":
        calendar = calendar[::-1]
    elif defect == "shifted":
        q = replace(q, calendar=calendar + pd.Timedelta(days=1))
    elif defect == "enum":
        q.action_to_next[0] = 2
    elif defect == "bool_state":
        q = replace(q, action_to_next=np.zeros(3, dtype=bool))
    elif defect == "code":
        q = replace(q, code="other-stock")
    elif defect == "stock_length":
        stock = replace(stock, eligible=np.ones(2, dtype=bool))
    elif defect == "label_enum":
        stock.labels[126, 2.0][0] = 4
    elif defect == "missing_atom":
        del stock.atoms["A1"]
    elif defect == "missing_label":
        del stock.labels[126, 2.0]
    with pytest.raises(ValueError):
        entry.count_stock(calendar, stock, q)
