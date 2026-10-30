"""Hand-built StockDaily labels only; no price/outcome builder or real inputs."""

import builtins
import inspect
from dataclasses import FrozenInstanceError, replace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core import momentum_only_v1 as canonical
from research_core import multi_timeframe_ma_counts_v1 as counts


def fixture(n: int = 64, start: str = "2015-01-01") -> tuple[canonical.StockDaily, pd.DatetimeIndex, dict[str, np.ndarray], np.ndarray]:
    calendar = pd.bdate_range(start, periods=n)
    stock = canonical.StockDaily(
        code="FAKE_A",
        split="synthetic",
        eligible=np.ones(n, dtype=np.bool_),
        jump=np.zeros(n, dtype=np.bool_),
        c52w=np.zeros(n, dtype=np.bool_),
        atoms={name: np.ones(n, dtype=np.int8) for name in ("A1", "A2")},
        ret120=np.full(n, np.nan, dtype=np.float64),
        labels={label: np.ones(n, dtype=np.int8) for label in canonical.LABELS},
        main_eligible={label: np.ones(n, dtype=np.bool_) for label in canonical.LABELS},
        calendar_full={horizon: np.ones(n, dtype=np.bool_) for horizon in canonical.HORIZONS},
    )
    return stock, calendar, {name: np.zeros(n, dtype=np.int8) for name in counts.CANDIDATES}, np.ones(n, dtype=np.bool_)


def run(inputs: tuple[canonical.StockDaily, pd.DatetimeIndex, dict[str, np.ndarray], np.ndarray]) -> counts.StockCounts:
    stock, calendar, states, mask = inputs
    return counts.count_stock(stock, calendar=calendar, candidate_states=states, common_mask=mask)


def metric(result: counts.StockCounts, name: str, *, group: str = "weekly-turn", cadence: str = "daily", label: int = 0) -> np.ndarray:
    return result.counts[result.groups.index(group), result.cadences.index(cadence), label, :, result.metrics.index(name)]


@pytest.mark.parametrize("mode", ["no_s6", "mask_false", "candidate_unknown", "empty"])
def test_fixed_axes_int64_zero_rows_and_audit_partitions(mode: str) -> None:
    inputs = fixture(0 if mode == "empty" else 25)
    stock, _, states, mask = inputs
    if mode == "no_s6":
        stock.eligible[:] = False
        mask[:] = False
    elif mode == "mask_false":
        mask[:] = False
    elif mode == "candidate_unknown":
        for values in states.values():
            values[:] = -1
    result = run(inputs)
    assert result.security_id == "FAKE_A"
    assert result.groups == ("weekly-turn", "cross50", "cross70", "dense", "C-base", "CORE")
    assert result.cadences == ("daily", "cooled") and result.years == tuple(range(2010, 2027))
    assert result.labels == tuple((h, target) for h in (252, 504) for target in (2.0, 3.0, 5.0, 10.0))
    assert result.metrics == (*canonical.METRICS, "censored_unknown_n", "censored_observed_hit_n", "excluded_known_n", "quality_unknown_n")
    assert result.counts.shape == (6, 2, 8, 17, 12)
    assert result.coverage_counts.shape == (17, 3) and result.state_counts.shape == (6, 17, 3) and result.membership_counts.shape == (6, 2, 17, 3)
    assert all(array.dtype == np.dtype("int64") for array in (result.counts, result.coverage_counts, result.state_counts, result.membership_counts))
    np.testing.assert_array_equal(result.state_counts.sum(axis=2), np.broadcast_to(result.coverage_counts[:, 0], (6, 17)))
    assert np.array_equal(result.coverage_counts[:, 2], result.coverage_counts[:, 0] - result.coverage_counts[:, 1])
    assert not result.counts[:, :, :, :5].any() and not result.counts[:, :, :, 6:].any()
    if mode == "candidate_unknown":
        assert not result.counts[:4].any()
        assert result.state_counts[:4, 5, 2].tolist() == [25] * 4
        assert result.state_counts[:4, 5, 1].tolist() == [0] * 4
        assert metric(result, "event_n", group="C-base").sum() == 25
        assert metric(result, "event_n", group="CORE").sum() == 25
    else:
        assert not result.counts.any()


def test_core_canonical_false_precedence_and_six_independent_groups() -> None:
    inputs = fixture(6)
    stock, _, states, _ = inputs
    stock.atoms["A1"][:] = [1, 0, 1, 1, 0, 1]
    stock.atoms["A2"][:] = [1, -1, -1, 0, 1, -1]
    for i, values in enumerate(states.values()):
        values[:] = np.roll(np.array([1, 0, -1, 1, 0, -1], dtype=np.int8), i)
    result = run(inputs)
    assert result.state_counts[5, 5].tolist() == [1, 3, 2]
    assert metric(result, "event_n", group="CORE").sum() == 1
    assert metric(result, "event_n", group="C-base").sum() == 6
    for group in counts.CANDIDATES:
        assert metric(result, "event_n", group=group).sum() == 2
        assert metric(result, "event_n", group=group, cadence="cooled").sum() == 1
        assert result.state_counts[result.groups.index(group), 5].tolist() == [2, 2, 2]


@pytest.mark.parametrize("quality_instead_of_mask", [False, True])
def test_cooldown_precedes_m_and_quality_never_refills(quality_instead_of_mask: bool) -> None:
    inputs = fixture(43)
    stock, _, states, mask = inputs
    states["weekly-turn"][[0, 20, 21, 42]] = 1
    if quality_instead_of_mask:
        stock.jump[0] = True
    else:
        mask[0] = False
    result = run(inputs)
    assert result.membership_counts[0, 1, 5].tolist() == [4, 3, 3 if quality_instead_of_mask else 2]
    assert metric(result, "event_n", cadence="cooled").sum() == (3 if quality_instead_of_mask else 2)
    assert metric(result, "hit_n", cadence="cooled").sum() == 2
    assert metric(result, "quality_unknown_n", cadence="cooled").sum() == int(quality_instead_of_mask)
    assert metric(result, "full_unknown_n", cadence="cooled").sum() == int(quality_instead_of_mask)
    assert np.flatnonzero(canonical.cooled(states["weekly-turn"] == 1, stock.eligible)).tolist() == [0, 21, 42]


@pytest.mark.parametrize("start", ["2012-12-17", "2018-12-17", "2020-12-17"])
def test_cross_year_and_era_boundaries_do_not_restart_cooldown(start: str) -> None:
    inputs = fixture(22, start)
    _, calendar, states, mask = inputs
    states["weekly-turn"][[0, 20, 21]] = 1
    mask[0] = False
    result = run(inputs)
    year = int(canonical.calendar_years(calendar)[21])
    assert result.membership_counts[0, 1, result.years.index(year)].tolist() == [2, 1, 1]
    assert metric(result, "event_n", cadence="cooled")[result.years.index(year)] == 1
    assert metric(result, "event_n", cadence="cooled").sum() == 1
    assert metric(result, "event_n").sum() == 2


def test_original_t_year_is_not_iso_week_or_outcome_year() -> None:
    inputs = fixture(1, "2010-01-01")
    inputs[2]["weekly-turn"][0] = 1
    result = run(inputs)
    assert metric(result, "event_n")[0] == 1 and metric(result, "event_n")[1:].sum() == 0
    assert inputs[1][0].isocalendar().year == 2009


def test_all_eight_labels_have_distinct_hand_counted_partitions_and_diagnostics() -> None:
    inputs = fixture(14)
    stock, _, states, _ = inputs
    for values in states.values():
        values[:] = 1
    for horizon in (252, 504):
        stock.calendar_full[horizon][[4, 5]] = False
    for li, label in enumerate(counts.LABELS):
        values = stock.labels[label]
        values[:] = [1, 2, 3, 0, 0, 1, *([1] * li), *([2] * (8 - li))]
        stock.main_eligible[label][:] = stock.calendar_full[label[0]] & (values != 0)
    result = run(inputs)
    for li in range(8):
        expected = [14, 11, 1 + li, 9 - li, 1, 2, 2, 1, 1, 1, 0, 0]
        assert result.counts[0, 0, li, 5].tolist() == expected
        assert result.counts[0, 1, li, 5].tolist() == [1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    assert np.all(result.counts[:, :, :, :, 0] == result.membership_counts[:, :, None, :, 2])


@pytest.mark.parametrize("horizon", [252, 504])
@pytest.mark.parametrize("where", ["at_t", "at_h", "after_h", "earlier_signal_warmup"])
def test_jump_quality_uses_c_base_boundaries_not_signal_warmup(horizon: int, where: str, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = fixture(horizon + 70)
    stock, _, states, mask = inputs
    anchor = 50
    mask[:] = False
    mask[anchor] = True
    states["weekly-turn"][anchor] = 1
    stock.jump[{"at_t": anchor, "at_h": anchor + horizon, "after_h": anchor + horizon + 1, "earlier_signal_warmup": 10}[where]] = True
    seen = []
    original = canonical.quality_unknown

    def spy(jump: np.ndarray, lookback: int, h: int) -> np.ndarray:
        seen.append(lookback)
        return original(jump, lookback, h)

    monkeypatch.setattr(canonical, "quality_unknown", spy)
    result = run(inputs)
    li = result.labels.index((horizon, 2.0))
    unknown = int(where in ("at_t", "at_h"))
    assert metric(result, "event_n", label=li).sum() == 1
    assert metric(result, "quality_unknown_n", label=li).sum() == unknown
    assert metric(result, "full_unknown_n", label=li).sum() == unknown
    assert metric(result, "known_n", label=li).sum() == 1 - unknown
    assert seen and set(seen) == {canonical.groups()["C-base-daily"][1]} == {0}


@pytest.mark.parametrize("seed", [3, 7])
def test_original_metrics_equal_public_canonical_calls(seed: int, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = fixture(64, "2018-12-03")
    stock, calendar, states, mask = inputs
    rng = np.random.Generator(np.random.PCG64(seed))
    stock.eligible[:] = rng.random(64) > 0.2
    mask[:] = stock.eligible & (rng.random(64) > 0.3)
    stock.jump[:] = rng.random(64) > 0.97
    for values in (*states.values(), *stock.atoms.values()):
        values[:] = rng.integers(-1, 2, size=64, dtype=np.int8)
    for h in canonical.HORIZONS:
        stock.calendar_full[h][:] = rng.random(64) > 0.2
    for label in canonical.LABELS:
        values = stock.labels[label]
        values[:] = np.where(stock.calendar_full[label[0]], rng.integers(0, 4, 64), rng.integers(0, 2, 64))
        stock.main_eligible[label][:] = stock.calendar_full[label[0]] & (values != 0)
    calls = []
    original = canonical.group_counts

    def spy(*args: Any, **kwargs: Any) -> np.ndarray:
        result = original(*args, **kwargs)
        calls.append(result.dtype)
        return result

    monkeypatch.setattr(canonical, "group_counts", spy)
    result = run(inputs)
    assert calls == [np.dtype("int32")] * 12
    names = canonical.condition_sets()["A1&A2"]
    members = {
        **{name: values == 1 for name, values in states.items()},
        "C-base": np.ones(64, dtype=np.bool_),
        "CORE": canonical.set_members(stock.atoms, names),
    }
    years = (canonical.calendar_years(calendar) - 2010).astype(np.intp)
    for gi, group in enumerate(result.groups):
        for ci, cadence in enumerate(result.cadences):
            retained = canonical.cooled(members[group], stock.eligible) if cadence == "cooled" else members[group] & stock.eligible
            expected = original(stock, retained & mask, lookback=canonical.groups()["C-base-daily"][1], year_index=years, n_years=17).astype(np.int64)
            np.testing.assert_array_equal(result.counts[gi, ci, :, :, :8], expected[[canonical.LABELS.index(label) for label in result.labels]])


@pytest.mark.parametrize("kind", ["excluded_known", "main_unknown", "main_censored", "censored_loss", "censored_flat"])
def test_inconsistent_admitted_partitions_fail_with_exact_context(kind: str) -> None:
    inputs = fixture(1)
    stock, _, states, _ = inputs
    states["weekly-turn"][0] = 1
    label = (252, 2.0)
    if kind == "excluded_known":
        stock.main_eligible[label][0] = False
    elif kind == "main_unknown":
        stock.labels[label][0] = 0
    else:
        stock.calendar_full[252][0] = False
        if kind != "main_censored":
            for target in canonical.TARGETS:
                stock.main_eligible[252, target][0] = False
            stock.labels[label][0] = 2 if kind == "censored_loss" else 3
    with pytest.raises(ValueError) as error:
        run(inputs)
    message = str(error.value)
    for part in ("code=FAKE_A", "group=weekly-turn", "cadence=daily", "label=(252, 2.0)", "year=2015", f"excluded_known_n={int(kind == 'excluded_known')}"):
        assert part in message


def test_quality_overlay_and_nonadmitted_bad_partitions_are_not_excluded_known() -> None:
    inputs = fixture(1)
    inputs[2]["weekly-turn"][0] = 1
    inputs[0].jump[0] = True
    result = run(inputs)
    assert metric(result, "excluded_known_n").sum() == 0
    assert metric(result, "quality_unknown_n").sum() == metric(result, "full_unknown_n").sum() == 1
    inputs[0].jump[0] = False
    inputs[0].main_eligible[252, 2.0][0] = False
    inputs[3][:] = False
    assert not run(inputs).counts.any()


def test_quality_overlay_precedes_censored_label_consistency() -> None:
    inputs = fixture(1)
    stock, _, states, _ = inputs
    states["weekly-turn"][0] = 1
    stock.jump[0] = True
    stock.calendar_full[252][0] = False
    stock.labels[252, 2.0][0] = 2
    result = run(inputs)
    assert metric(result, "event_n").sum() == metric(result, "censored_n").sum() == 1
    assert metric(result, "unknown_n").sum() == metric(result, "censored_unknown_n").sum() == 1
    assert metric(result, "quality_unknown_n").sum() == 1
    assert metric(result, "known_n").sum() == metric(result, "full_unknown_n").sum() == metric(result, "excluded_known_n").sum() == 0


def test_h126_keys_are_required_but_s7_semantic_partition_is_only_eight_labels() -> None:
    inputs = fixture(1)
    inputs[2]["weekly-turn"][0] = 1
    inputs[0].main_eligible[126, 2.0][0] = False
    assert metric(run(inputs), "event_n").sum() == 1
    del inputs[0].labels[126, 2.0]
    with pytest.raises(ValueError, match="labels.*keys"):
        run(inputs)


@pytest.mark.parametrize(
    "kind", ["missing_candidate", "extra_candidate", "missing_label", "extra_label", "missing_main", "missing_full", "extra_full", "missing_atom"]
)
def test_required_keys_are_explicit_not_fabricated(kind: str) -> None:
    stock, calendar, states, mask = fixture(2)
    if kind == "missing_candidate":
        del states["dense"]
    elif kind == "extra_candidate":
        states["other"] = np.ones(2, dtype=np.int8)
    elif kind == "missing_label":
        del stock.labels[126, 3.0]
    elif kind == "extra_label":
        stock.labels[252, 4.0] = np.ones(2, dtype=np.int8)
    elif kind == "missing_main":
        del stock.main_eligible[126, 2.0]
    elif kind == "missing_full":
        del stock.calendar_full[126]
    elif kind == "extra_full":
        stock.calendar_full[999] = np.ones(2, dtype=np.bool_)
    else:
        del stock.atoms["A2"]
    with pytest.raises(ValueError):
        counts.count_stock(stock, calendar=calendar, candidate_states=states, common_mask=mask)


@pytest.mark.parametrize("target", ["eligible", "jump", "mask", "candidate", "atom", "label", "main", "full"])
@pytest.mark.parametrize("bad_kind", ["dtype", "length", "dimension"])
def test_accessed_vectors_require_exact_types_and_alignment(target: str, bad_kind: str) -> None:
    stock, calendar, states, mask = fixture(3)
    tri = target in ("candidate", "atom", "label")
    dtype = np.int8 if tri else np.bool_
    # Intentionally malformed arrays cross the typed StockDaily boundary here.
    bad: Any = np.ones(3, dtype=np.float64 if tri else np.int8) if bad_kind == "dtype" else np.ones(2 if bad_kind == "length" else (3, 1), dtype=dtype)
    if target in ("eligible", "jump"):
        stock = replace(stock, **{target: bad})
    elif target == "mask":
        mask = bad
    elif target == "candidate":
        states["dense"] = bad
    elif target == "atom":
        stock.atoms["A1"] = bad
    elif target == "label":
        stock.labels[126, 2.0] = bad
    elif target == "main":
        stock.main_eligible[126, 2.0] = bad
    else:
        stock.calendar_full[126] = bad
    with pytest.raises(ValueError):
        counts.count_stock(stock, calendar=calendar, candidate_states=states, common_mask=mask)


@pytest.mark.parametrize("target", ["candidate", "atom", "label"])
@pytest.mark.parametrize("value", [-2, 4])
def test_invalid_state_values_are_rejected(target: str, value: int) -> None:
    inputs = fixture(2)
    if target == "candidate":
        inputs[2]["dense"][0] = value
    elif target == "atom":
        inputs[0].atoms["A1"][0] = value
    else:
        inputs[0].labels[126, 2.0][0] = value
    with pytest.raises(ValueError, match="invalid state"):
        run(inputs)


@pytest.mark.parametrize("kind", ["duplicate", "reverse", "nat", "aware", "intraday", "early", "late", "list"])
def test_invalid_calendar_is_rejected_without_repairs(kind: str) -> None:
    stock, calendar, states, mask = fixture(2)
    invalid: dict[str, Any] = {
        "duplicate": pd.DatetimeIndex([calendar[0]] * 2),
        "reverse": calendar[::-1],
        "nat": pd.DatetimeIndex([pd.NaT, calendar[1]]),
        "aware": calendar.tz_localize("Asia/Taipei"),
        "intraday": calendar + pd.Timedelta(hours=1),
        "early": pd.bdate_range("2009-01-01", periods=2),
        "late": pd.bdate_range("2027-01-01", periods=2),
        "list": list(calendar),
    }
    with pytest.raises(ValueError, match="calendar"):
        counts.count_stock(stock, calendar=invalid[kind], candidate_states=states, common_mask=mask)


def test_mask_outside_s6_and_int32_capacity_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = fixture(3)
    inputs[0].eligible[0] = False
    with pytest.raises(ValueError, match="subset"):
        run(inputs)
    inputs[3][0] = False
    monkeypatch.setattr(counts, "_MAX_ROWS", 2)
    with pytest.raises(ValueError, match="int32"):
        run(inputs)


def test_inputs_unchanged_outputs_immutable_and_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = fixture(24)
    stock, _, states, mask = inputs
    states["weekly-turn"][[0, 21]] = 1
    arrays = [
        stock.eligible,
        stock.jump,
        *stock.atoms.values(),
        *stock.labels.values(),
        *stock.main_eligible.values(),
        *stock.calendar_full.values(),
        *states.values(),
        mask,
    ]
    before = [array.copy() for array in arrays]

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no data roots, labels, calendar reader or outcome construction")

    for name in ("pr17_calendar", "pr17_codes", "stock_daily", "outcomes_for_targets"):
        monkeypatch.setattr(canonical, name, forbidden)
    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", forbidden)
        result = run(inputs)
    assert tuple(inspect.signature(counts.count_stock).parameters) == ("stock", "calendar", "candidate_states", "common_mask")
    for original, snapshot in zip(arrays, before):
        np.testing.assert_array_equal(original, snapshot)
    for output in (result.counts, result.coverage_counts, result.state_counts, result.membership_counts):
        assert not output.flags.writeable
        assert all(not np.shares_memory(output, original) for original in arrays)
        with pytest.raises(ValueError):
            output.setflags(write=True)
    with pytest.raises(FrozenInstanceError):
        setattr(result, "security_id", "CHANGED")
    snapshot = result.counts.copy()
    mask[:] = False
    states["weekly-turn"][:] = -1
    np.testing.assert_array_equal(result.counts, snapshot)
