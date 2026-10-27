"""Synthetic complete-universe panels only; no market readers or real calendars."""

import builtins
import inspect
import socket
import sqlite3
from dataclasses import FrozenInstanceError, asdict, replace
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core import multi_timeframe_ma_core_v1 as core
from research_core import multi_timeframe_ma_panel_v1 as panel


def request_of(n: int = 10, days: int = 21, cutoff: str = "2020-06-30") -> panel.PanelRequest:
    return panel.PanelRequest(
        tuple(f"FAKE_{i:02d}" for i in range(n)),
        "synthetic-G",
        cast(pd.Timestamp, pd.Timestamp(cutoff)),
        "synthetic-U",
        "synthetic-C",
        pd.date_range(end=cutoff, periods=days),
    )


def packet_of(request: panel.PanelRequest, i: int = 0, *, weeks: int = 120, slope: float | None = None, **changes: Any) -> panel.StockFeaturePacket:
    dates = pd.date_range(end=request.decision_cutoff, periods=weeks, freq="7D")
    close = 100.0 + (float(i) if slope is None else slope) * np.arange(weeks, dtype=np.float64)
    weekly = core.CutoffSeries(
        request.codes[i],
        request.generation,
        request.decision_cutoff,
        "reference_factor_adjusted",
        "completed_weekly",
        dates,
        close,
        np.ones(weeks, dtype=np.bool_),
    )
    packet = panel.StockFeaturePacket(
        request.codes[i],
        request.generation,
        request.decision_cutoff,
        request.universe_id,
        request.calendar_id,
        True,
        request.common_calendar[-21:],
        np.zeros(min(21, len(request.common_calendar)), dtype=np.int8),
        core.FALSE,
        core.FALSE,
        weekly,
        core.moving_averages(weekly),
    )
    return replace(packet, **changes)


def test_sorted_complete_barrier_and_public_oracle_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    request = request_of()
    packets = [packet_of(request, i) for i in reversed(range(10))]
    before = packets.copy()
    calls = {"density": 0, "ratio": 0}
    density, ratio = core.density_at_cutoff, core.ratio_cross

    def density_spy(*args: Any) -> core.DensityState:
        calls["density"] += 1
        return density(*args)

    def ratio_spy(*args: Any) -> core.RatioCross:
        calls["ratio"] += 1
        return ratio(*args)

    monkeypatch.setattr(core, "density_at_cutoff", density_spy)
    monkeypatch.setattr(core, "ratio_cross", ratio_spy)
    result = panel.evaluate_panel(request, packets)
    assert result.codes == tuple(row.security_id for row in result.stocks) == request.codes
    assert packets == before and calls == {"density": 10, "ratio": 10}
    assert result.m == (True,) * 10  # False D/W and false crosses are known.
    assert all(row.daily_state == row.w_current == row.w_previous == row.cross50 == row.cross70 == core.FALSE for row in result.stocks)
    assert result.coverage == panel.PanelCoverage(10, 10, 0, 0, tuple((reason, 0) for reason in panel.MASK_REASONS), 10)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "extra", "wrong_generation", "wrong_cutoff", "wrong_universe", "wrong_calendar"])
def test_bad_barrier_fails_before_any_numeric_reduction(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    request = request_of(2)
    packets = [packet_of(request, i) for i in range(2)]
    if kind == "missing":
        packets.pop()
    elif kind == "duplicate":
        packets.append(packets[0])
    elif kind == "extra":
        larger = request_of(3)
        packets.append(packet_of(larger, 2))
    else:
        field = {"wrong_generation": "generation", "wrong_cutoff": "decision_cutoff", "wrong_universe": "universe_id", "wrong_calendar": "calendar_id"}[kind]
        value = request.decision_cutoff + pd.Timedelta(days=1) if field == "decision_cutoff" else "different-ID"
        corruption: dict[str, Any] = {field: value}
        packets[1] = replace(packets[1], **corruption)

    def forbidden(*args: Any) -> Any:
        raise AssertionError("partial barrier must not reach numeric oracles")

    monkeypatch.setattr(core, "density_at_cutoff", forbidden)
    monkeypatch.setattr(core, "ratio_cross", forbidden)
    with pytest.raises(ValueError):
        panel.evaluate_panel(request, packets)


@pytest.mark.parametrize("kind", ["equivalent_ma", "wrong_stock", "wrong_generation", "wrong_cutoff", "daily", "raw_basis"])
def test_weekly_identity_and_exact_ma_lineage(kind: str) -> None:
    request = request_of(1)
    packet = packet_of(request)
    if kind == "equivalent_ma":
        packet = replace(packet, weekly_ma=core.moving_averages(replace(packet.weekly_series)))
    else:
        changes: dict[str, Any] = {
            "wrong_stock": {"security_id": "FAKE_OTHER"},
            "wrong_generation": {"generation": "other-G"},
            "wrong_cutoff": {"decision_cutoff": request.decision_cutoff + pd.Timedelta(days=1)},
            "daily": {"bar_kind": "daily"},
        }
        if kind == "raw_basis":
            # Deliberately corrupt a local fixture to test the panel's basis guard.
            object.__setattr__(packet.weekly_series, "price_basis", "raw")
        else:
            weekly = replace(packet.weekly_series, **changes[kind])
            packet = replace(packet, weekly_series=weekly, weekly_ma=core.moving_averages(weekly))
    with pytest.raises(ValueError):
        panel.evaluate_panel(request, [packet])


@pytest.mark.parametrize(("n", "tied", "expected_dense"), [(1, 1, 0), (10, 10, 0), (10, 1, 1), (20, 3, 3), (20, 4, 0)])
def test_average_tie_percentiles_and_no_forced_top_k(n: int, tied: int, expected_dense: int) -> None:
    request = request_of(n)
    packets = [packet_of(request, i, slope=0.0 if i < tied else float(i)) for i in range(n)]
    result = panel.evaluate_panel(request, packets)
    values = [cast(float, core.density_at_cutoff(packet.weekly_series, packet.weekly_ma).density) for packet in packets]
    oracle = pd.Series(values).rank(method="average", pct=True)
    assert [row.rank_percentile for row in result.stocks] == oracle.tolist()
    assert result.stocks[0].rank_percentile == (tied + 1) / (2 * n)
    assert sum(row.dense == core.TRUE for row in result.stocks) == expected_dense
    assert result.pool_n == n and result.pool_status == "ranked"
    assert result.m == (True,) * n


def test_p_precedes_m_and_unrelated_states_cannot_change_rank() -> None:
    request = request_of()
    packets = [packet_of(request, i) for i in range(10)]
    original = panel.evaluate_panel(request, packets)
    for i in range(1, 10):
        packets[i] = replace(packets[i], **({"daily_states": np.full(21, core.UNKNOWN, dtype=np.int8)} if i % 2 else {"w_previous": core.UNKNOWN}))
    changed = panel.evaluate_panel(request, packets)
    assert changed.pool_n == 10 and sum(changed.m) == 1
    assert changed.stocks[0].rank_percentile == 0.10 and changed.stocks[0].dense == core.TRUE
    assert [(row.p_member, row.rank_percentile, row.dense) for row in changed.stocks] == [
        (row.p_member, row.rank_percentile, row.dense) for row in original.stocks
    ]
    # CORE, candidates, outcomes and confirmation are intentionally absent inputs.
    assert tuple(inspect.signature(panel.evaluate_panel).parameters) == ("request", "packets")
    external_labels, external_core = [0] * 10, [core.UNKNOWN] * 10
    external_labels[:] = [1] * 10
    external_core[:] = [core.TRUE] * 10
    assert panel.evaluate_panel(request, packets) == changed


@pytest.mark.parametrize("reason", ["not_s6", "weekly_previous_unknown", "weekly_current_unknown", "weekly_density_unknown"])
def test_individual_eligibility_reasons_and_legal_pool_changes(reason: str) -> None:
    request = request_of(2)
    packets = [packet_of(request, i) for i in range(2)]
    if reason == "not_s6":
        packets[0] = replace(packets[0], s6=False)
    elif reason == "weekly_density_unknown":
        packets[0] = packet_of(request, weeks=119)
    elif reason == "weekly_previous_unknown":
        packets[0] = replace(packets[0], w_previous=core.UNKNOWN)
    else:
        packets[0] = replace(packets[0], w_current=core.UNKNOWN)
    result = panel.evaluate_panel(request, packets)
    assert result.m == (False, True) and reason in result.stocks[0].mask_reasons
    assert result.pool_n == (1 if reason in ("not_s6", "weekly_density_unknown") else 2)
    if reason == "weekly_density_unknown":
        assert "ema120:ema_warmup_120" in result.stocks[0].density_reasons
        assert result.stocks[0].density is result.stocks[0].rank_percentile is None
        assert result.stocks[0].dense == core.UNKNOWN


@pytest.mark.parametrize(("last", "valid"), [(0.0, True), (-1.0, True), (np.nan, True), (np.inf, True), (100.0, False)])
def test_invalid_weekly_close_or_upstream_quality_excludes_density(last: float, valid: bool) -> None:
    request = request_of(2)
    bad = packet_of(request)
    close, quality = bad.weekly_series.close.copy(), bad.weekly_series.valid.copy()
    close[-1], quality[-1] = last, valid
    weekly = replace(bad.weekly_series, close=close, valid=quality)
    bad = replace(bad, weekly_series=weekly, weekly_ma=core.moving_averages(weekly))
    result = panel.evaluate_panel(request, [bad, packet_of(request, 1)])
    assert result.pool_n == 1 and result.m == (False, True)
    assert result.stocks[0].density is None
    cause = "invalid_close" if valid else "invalid_upstream"
    assert f"denominator:{cause}" in result.stocks[0].density_reasons


def test_numpy_known_boolean_and_integer_states_are_accepted() -> None:
    request = request_of(1)
    result = panel.evaluate_panel(request, [packet_of(request, s6=np.bool_(True), w_current=np.int8(0), w_previous=np.int64(0))])
    assert result.m == (True,) and type(result.stocks[0].w_current) is int


@pytest.mark.parametrize("days", [1, 19, 20, 21, 22, 41])
@pytest.mark.parametrize("unknown_position", [None, 0, -1, 1])
def test_exact_recent_dates_and_public_ratio_warmup(days: int, unknown_position: int | None) -> None:
    request = request_of(1, days=days)
    states = np.zeros(min(21, days), dtype=np.int8)
    states[-min(10, len(states)) :] = core.TRUE
    if unknown_position is not None and unknown_position < len(states):
        states[unknown_position] = core.UNKNOWN
    packet = packet_of(request, daily_states=states)
    expected = core.ratio_cross(states)
    result = panel.evaluate_panel(request, [packet])
    row = result.stocks[0]
    assert row.ratio == (float(expected.ratio[-1]) if np.isfinite(expected.ratio[-1]) else None)
    assert row.previous_ratio == (float(expected.previous_ratio[-1]) if np.isfinite(expected.previous_ratio[-1]) else None)
    assert (row.cross50, row.cross70) == (expected.cross50[-1], expected.cross70[-1])
    assert result.m == (row.daily_state != core.UNKNOWN and row.ratio is not None and row.previous_ratio is not None,)


@pytest.mark.parametrize(("zeros", "cross50", "cross70"), [(11, 1, 0), (10, 0, 0), (7, 0, 1)])
def test_cross_thresholds_and_known_false_d_do_not_add_mask_gates(zeros: int, cross50: int, cross70: int) -> None:
    request = request_of(1)
    states = np.array([0] * zeros + [1] * (21 - zeros), dtype=np.int8)
    result = panel.evaluate_panel(request, [packet_of(request, daily_states=states)])
    assert (result.stocks[0].cross50, result.stocks[0].cross70) == (cross50, cross70)
    assert result.m == (True,)


@pytest.mark.parametrize("outside_s6", [False, True])
def test_empty_pool_preserves_unknowns_and_all_codes(outside_s6: bool) -> None:
    request = request_of(3)
    packets = [packet_of(request, i, weeks=120 if outside_s6 else 119, s6=not outside_s6) for i in range(3)]
    result = panel.evaluate_panel(request, packets)
    assert result.pool_status == "empty" and result.pool_n == 0
    assert result.codes == tuple(row.security_id for row in result.stocks) and result.m == (False,) * 3
    assert all(row.rank_percentile is None and row.dense == core.UNKNOWN and not row.p_member for row in result.stocks)
    assert all("rank_pool_unavailable" in row.mask_reasons for row in result.stocks)
    assert result.coverage.excluded_s6_n == (0 if outside_s6 else 3)


def test_overlapping_coverage_is_within_s6_and_uses_original_cutoff_year() -> None:
    panels = []
    for cutoff in ("2015-12-31", "2016-01-01"):
        request = request_of(3, cutoff=cutoff)
        bad = packet_of(request, weeks=119, daily_states=np.full(21, -1, dtype=np.int8), w_current=-1, w_previous=-1)
        outside = replace(packet_of(request, 2), s6=False, daily_states=np.full(21, -1, dtype=np.int8))
        result = panel.evaluate_panel(request, [bad, packet_of(request, 1), outside])
        counts = dict(result.coverage.reason_counts_within_s6)
        assert result.coverage.s6_n == 2 and result.coverage.m_n == 1 and result.coverage.excluded_s6_n == 1
        assert result.coverage.outside_s6_n == 1 and counts["not_s6"] == 0
        assert sum(counts.values()) == 6 > result.coverage.excluded_s6_n
        assert set(bad.weekly_ma.reasons)  # The caller's core object is retained, not rewritten.
        panels.append(result)
    assert [result.decision_cutoff.year for result in panels] == [2015, 2016]
    assert panels[0].decision_cutoff.isocalendar().year == panels[1].decision_cutoff.isocalendar().year == 2015
    assert sum(result.coverage.excluded_s6_n for result in panels) == 2


@pytest.mark.parametrize("factor", [0.25, 0.97, 2.0])
def test_same_cutoff_positive_scale_and_future_append_do_not_rewrite_old_panel(factor: float) -> None:
    request = request_of()
    packets = [packet_of(request, i) for i in range(10)]
    original = panel.evaluate_panel(request, packets)
    scaled = []
    for packet in packets:
        weekly = replace(packet.weekly_series, close=packet.weekly_series.close * factor)
        scaled.append(replace(packet, weekly_series=weekly, weekly_ma=core.moving_averages(weekly)))
    result = panel.evaluate_panel(request, scaled)
    assert result.m == original.m and result.pool_n == original.pool_n
    assert [(row.rank_percentile, row.dense) for row in result.stocks] == [(row.rank_percentile, row.dense) for row in original.stocks]
    np.testing.assert_allclose(
        np.asarray([row.density for row in result.stocks], dtype=np.float64),
        np.asarray([row.density for row in original.stocks], dtype=np.float64),
        rtol=2e-14,
        atol=1e-15,
    )
    future = request_of(cutoff="2020-07-01")
    panel.evaluate_panel(future, [packet_of(future, i, w_current=core.UNKNOWN) for i in range(10)])
    assert panel.evaluate_panel(request, packets) == original


@pytest.mark.parametrize(
    "change",
    [
        {"codes": ()},
        {"codes": ["FAKE_00"]},
        {"codes": ("FAKE_01", "FAKE_00")},
        {"codes": ("FAKE_00", "FAKE_00")},
        {"codes": (" ",)},
        {"codes": (" FAKE_00",)},
        {"generation": ""},
        {"universe_id": ""},
        {"calendar_id": " "},
        {"decision_cutoff": pd.NaT},
        {"decision_cutoff": pd.Timestamp("2020-06-30 12:00")},
        {"decision_cutoff": pd.Timestamp("2020-06-30", tz="Asia/Taipei")},
        {"common_calendar": pd.DatetimeIndex([])},
        {"common_calendar": pd.date_range(end="2020-06-29", periods=21)},
        {"common_calendar": pd.date_range(end="2020-06-30", periods=21)[::-1]},
        {"common_calendar": pd.DatetimeIndex([pd.Timestamp("2020-06-30")] * 21)},
        {"common_calendar": pd.DatetimeIndex([pd.NaT])},
    ],
)
def test_invalid_requests_are_rejected(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        replace(request_of(1), **change)


@pytest.mark.parametrize(
    "bad",
    [
        np.ones(21, dtype=np.float64),
        np.ones(21, dtype=np.int64),
        np.ones(21, dtype=np.bool_),
        np.ones((21, 1), dtype=np.int8),
        np.zeros(20, dtype=np.int8),
        np.full(21, 2, dtype=np.int8),
        [0] * 21,
    ],
)
def test_daily_states_require_exact_int8_and_exact_length(bad: Any) -> None:
    with pytest.raises(ValueError):
        packet_of(request_of(1), daily_states=bad)


@pytest.mark.parametrize("bad", [True, np.bool_(False), 0.0, np.nan, 2, -2, None, "0"])
@pytest.mark.parametrize("name", ["w_current", "w_previous"])
def test_weekly_states_are_strict_tri_state(name: str, bad: Any) -> None:
    with pytest.raises(ValueError):
        packet_of(request_of(1), **{name: bad})


@pytest.mark.parametrize("bad", [-1, 0, 1, 0.0, None])
def test_s6_requires_known_boolean(bad: Any) -> None:
    with pytest.raises(ValueError):
        packet_of(request_of(1), s6=bad)


@pytest.mark.parametrize("kind", ["shift", "reverse", "duplicate", "aware", "intraday", "missing", "extra"])
def test_saved_d_dates_must_match_exact_common_positions(kind: str) -> None:
    request = request_of(1, days=22)
    dates = request.common_calendar[-21:]
    changes = {
        "shift": dates + pd.Timedelta(days=1),
        "reverse": dates[::-1],
        "duplicate": pd.DatetimeIndex([dates[-1]] * 21),
        "aware": dates.tz_localize("Asia/Taipei"),
        "intraday": dates + pd.Timedelta(hours=1),
        "missing": dates[:-1],
        "extra": request.common_calendar,
    }
    with pytest.raises(ValueError):
        packet = packet_of(request, daily_state_dates=changes[kind], daily_states=np.zeros(len(changes[kind]), dtype=np.int8))
        panel.evaluate_panel(request, [packet])


@pytest.mark.parametrize(
    "change",
    [
        {"density": None},
        {"density": np.nan},
        {"density": np.inf},
        {"density": -1.0},
        {"denominator": None},
        {"denominator": 0.0},
        {"denominator": -1.0},
        {"denominator": np.inf},
        {"denominator": np.nan},
        {"values": (1.0,) * 5},
        {"values": (None,) * 6},
        {"values": (np.nan,) * 6},
        {"values": (np.inf,) * 6},
    ],
)
def test_inconsistent_known_core_density_fails_closed(change: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    request = request_of(1)
    packet = packet_of(request)
    known = core.density_at_cutoff(packet.weekly_series, packet.weekly_ma)
    monkeypatch.setattr(core, "density_at_cutoff", lambda *args: replace(known, **change))
    with pytest.raises(ValueError, match="known core density"):
        panel.evaluate_panel(request, [packet])


def test_unknown_density_reasons_are_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    request = request_of(1)
    packet = packet_of(request)
    missing = core.DensityState((None,) * 6, None, None, False, ("synthetic_reason_A", "synthetic_reason_B"))
    monkeypatch.setattr(core, "density_at_cutoff", lambda *args: missing)
    result = panel.evaluate_panel(request, [packet])
    assert result.stocks[0].density_reasons == missing.reasons
    assert result.stocks[0].density is None and result.m == (False,)


def test_input_snapshots_immutable_outputs_and_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    calendar = pd.date_range(end="2020-06-30", periods=21)
    request = replace(request_of(1), common_calendar=calendar)
    states = np.zeros(21, dtype=np.int8)
    packet = packet_of(request, daily_state_dates=calendar, daily_states=states)
    close_before = packet.weekly_series.close.copy()
    ema_before = packet.weekly_ma.ema[120].copy()
    states[:] = core.UNKNOWN
    calendar.asi8[0] -= 86_400_000_000_000
    assert packet.daily_states[0] == 0 and packet.daily_state_dates.equals(request.common_calendar)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("panel must have no filesystem/network/database fallback")

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", forbidden)
        guard.setattr(socket, "create_connection", forbidden)
        guard.setattr(sqlite3, "connect", forbidden)
        result = panel.evaluate_panel(request, [packet])
    assert result.m == (True,) and result.m is result.m
    # All downstream arms can refer to this one M object, rather than copies.
    assert all(arm is result.m for arm in [result.m] * 6)
    assert asdict(result)["stocks"][0]["ratio"] == 0.0
    with pytest.raises(FrozenInstanceError):
        setattr(result, "pool_n", 0)
    with pytest.raises(TypeError):
        cast(Any, result.m)[0] = False
    with pytest.raises(ValueError):
        packet.daily_states.setflags(write=True)
    np.testing.assert_array_equal(packet.weekly_series.close, close_before)
    np.testing.assert_array_equal(packet.weekly_ma.ema[120], ema_before)
    later = panel.evaluate_panel(request, [replace(packet, w_previous=core.UNKNOWN)])
    assert later.m == (False,) and result.m == (True,) and later.stocks is not result.stocks
