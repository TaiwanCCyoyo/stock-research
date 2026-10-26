from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from research_core import momentum_only_v1 as momentum
from research_core import tenbagger_drivers_v1 as drivers


def _stock(code: str, n: int, *, eligible: np.ndarray | None = None) -> drivers.DriverStock:
    eligible = np.ones(n, dtype=bool) if eligible is None else eligible
    daily = momentum.StockDaily(
        code=code,
        split="development",
        eligible=eligible,
        jump=np.zeros(n, dtype=bool),
        c52w=np.zeros(n, dtype=bool),
        atoms={"A1": np.ones(n, dtype=np.int8), "A2": np.ones(n, dtype=np.int8)},
        ret120=np.zeros(n),
        labels={label: np.zeros(n, dtype=np.int8) for label in momentum.LABELS},
        main_eligible={label: np.ones(n, dtype=bool) for label in momentum.LABELS},
        calendar_full={horizon: np.ones(n, dtype=bool) for horizon in momentum.HORIZONS},
    )
    features = pd.DataFrame({"HOT": np.ones(n, dtype=np.int8), "SMALL": np.ones(n, dtype=np.int8), "INST": np.ones(n, dtype=np.int8)})
    return drivers.DriverStock(daily=daily, close=np.full(n, 100.0), industry="synthetic", features=features)


def test_formal_members_has_eight_fixed_groups_and_inst_baselines_mask_unknown_only() -> None:
    stock = _stock("A", 4)
    stock.daily.atoms["A1"][:] = [1, 1, 0, 1]
    stock.daily.atoms["A2"][:] = 1
    stock.features.loc[:, "HOT"] = np.asarray([1, 0, -1, 1], dtype=np.int8)
    stock.features.loc[:, "SMALL"] = np.asarray([1, 1, 1, 0], dtype=np.int8)
    stock.features.loc[:, "INST"] = np.asarray([-1, 0, 1, 1], dtype=np.int8)

    members = drivers.formal_members(stock)

    assert set(drivers.CONDITIONS).issubset(members)
    assert len(drivers.CONDITIONS) == 8
    assert members["C-base-daily|INST-known"].tolist() == [False, True, True, True]
    assert members["CORE|INST-known"].tolist() == [False, True, False, True]
    # Unknown HOT is not silently false in a HOT condition, while known false is false.
    assert members["HOT"].tolist() == [True, False, False, True]
    assert members["HOT&SMALL&INST"].tolist() == [False, False, False, False]
    assert drivers.comparison_bases("INST") == ("C-base-daily|INST-known",)
    assert drivers.comparison_bases("CORE&INST") == ("C-base-daily|INST-known", "CORE|INST-known")


def test_formal_counts_uses_group_counts_for_daily_and_cooled_masks(monkeypatch: pytest.MonkeyPatch) -> None:
    stock = _stock("A", 3)
    stock.features["HOT"] = [1, 1, 0]
    calendar = pd.date_range("2010-01-04", periods=3)
    calls: list[np.ndarray] = []

    def counted(
        daily: momentum.StockDaily,
        members: NDArray[np.bool_],
        *,
        lookback: int,
        year_index: NDArray[np.intp],
        n_years: int,
    ) -> NDArray[np.int32]:
        calls.append(members.copy())
        output = np.zeros((len(momentum.LABELS), n_years, len(momentum.METRICS)), dtype=np.int32)
        output[:, :, 0] = int(members.sum())
        return output

    monkeypatch.setattr(momentum, "group_counts", counted)
    daily, cooled = drivers.formal_counts([stock], calendar)

    assert len(calls) == 2 * len(drivers.GROUPS)
    assert daily.shape == cooled.shape
    hot_index = drivers.GROUPS.index("HOT")
    assert np.all(daily[hot_index, :, 0, 0, 0] == 2)
    assert np.all(cooled[hot_index, :, 0, 0, 0] == int(calls[2 * hot_index + 1].sum()))


def test_retro_observations_reuses_two_x_episodes_and_records_first_crossings() -> None:
    n = 580
    calendar = pd.date_range("2020-01-02", periods=n)
    stock = _stock("A", n)
    stock.daily.labels[504, 2.0][:] = 0
    stock.daily.labels[504, 2.0][[10, 40, 70]] = 1
    stock.close[12] = 200
    stock.close[15] = 300
    stock.close[20] = 1100
    stock.close[42] = 200
    stock.close[50] = 600
    stock.close[72] = 200
    stock.close[80] = 400
    stock.features.loc[:, "HOT"] = 1
    stock.features.loc[:, "SMALL"] = 1
    stock.features.loc[:, "INST"] = 1

    observations, alignment = drivers.retro_observations([stock], calendar, set())

    anchor = observations.loc[observations.point.eq("anchor")].sort_values("calendar_index")
    assert anchor.group_id.tolist() == ["ge10", "ge5_lt10", "ge2_lt5"]
    first_two = observations.loc[(observations.group_id.eq("ge10")) & observations.point.eq("first_2x")].iloc[0]
    first_three = observations.loc[(observations.group_id.eq("ge10")) & observations.point.eq("first_3x")].iloc[0]
    assert first_two.calendar_index == 12
    assert first_three.calendar_index == 15
    assert set(alignment.target_multiple) == {5.0, 10.0}


def test_random_observations_is_seeded_per_stock_and_year_and_reports_shortfall() -> None:
    calendar = pd.date_range("2019-12-29", periods=6)
    eligible_a = np.array([True, False, True, False, False, False])
    a = _stock("A", 6, eligible=eligible_a)
    b = _stock("B", 6)
    observations = pd.DataFrame({
        "code": ["A"] * 5 + ["B"],
        "point": ["anchor"] * 6,
        "year": [2019] * 4 + [2020, 2020],
        "group_id": ["ge10"] * 4 + ["ge5_lt10", "ge10"],
    })

    drawn, quotas = drivers.random_observations(observations, [a, b], calendar)
    repeated, repeated_quotas = drivers.random_observations(observations, [a, b], calendar)

    pd.testing.assert_frame_equal(drawn, repeated)
    pd.testing.assert_frame_equal(quotas, repeated_quotas)
    quota_a = quotas.loc[quotas.code.eq("A") & quotas.matched_group.eq("ge10")].iloc[0]
    quota_b = quotas.loc[quotas.code.eq("B") & quotas.matched_group.eq("ge10")].iloc[0]
    assert (quota_a.quota_n, quota_a.available_n, quota_a.drawn_n, quota_a.shortfall_n) == (4, 2, 2, 2)
    assert (quota_b.quota_n, quota_b.available_n, quota_b.drawn_n, quota_b.shortfall_n) == (1, 3, 1, 0)
    assert drawn.loc[drawn.code.eq("A"), "calendar_index"].isin([0, 2]).all()
    missing = quotas.loc[quotas.code.eq("A") & quotas.matched_group.eq("ge5_lt10")].iloc[0]
    assert (missing.year, missing.drawn_n, missing.shortfall_n) == (2020, 0, 1)


def test_exact_a4_reports_cell_differences_and_rejects_missing_universe() -> None:
    differences = drivers.exact_a4([np.array([0, 1], dtype=np.int8)], [np.array([0, 0], dtype=np.int8)], ["A"])
    assert differences == [{"code": "A", "different_cells": 1, "first_index": 1}]
    with pytest.raises(drivers.AlignmentError, match="complete fixed universe"):
        drivers.exact_a4([], [np.array([0], dtype=np.int8)], ["A"])


def test_exact_episode_counts_reports_fixed_target_mismatches() -> None:
    actual = pd.DataFrame({"target_multiple": [10.0, 5.0], "episode_n": [1, 2]})
    reference = pd.DataFrame({"target_multiple": [10.0, 5.0], "horizon": [504, 504], "episode_n": [139, 900]})

    result = drivers.exact_episode_counts(actual, reference)

    assert result == [
        {"target_multiple": 10.0, "actual": 1, "reference": [139], "fixed": 139},
        {"target_multiple": 5.0, "actual": 2, "reference": [900], "fixed": 900},
    ]


def test_exact_formal_counts_names_group_label_and_metric_mismatches() -> None:
    counts = np.zeros((len(drivers.GROUPS), len(drivers.LABELS), 1, 1, len(momentum.METRICS)), dtype=np.int32)
    reference = pd.DataFrame([
        {"group_id": group, "horizon": horizon, "target_multiple": target, **{metric: 1 for metric in momentum.METRICS}}
        for group in ("C-base-daily", "A1&A2:daily")
        for horizon, target in drivers.LABELS
        if target != 2
    ])

    differences = drivers.exact_formal_counts(counts, reference)

    assert differences
    assert differences[0]["group_id"] in {"C-base-daily", "CORE"}
    assert differences[0]["metric"] in momentum.METRICS
    assert "horizon" in differences[0] and "target_multiple" in differences[0]


def test_retro_tables_reports_medians_and_r6_requires_both_bootstrap_intervals() -> None:
    def row(group: str, value: int) -> dict[str, object]:
        record: dict[str, object] = {
            "code": "A",
            "point": "first_2x",
            "year": 2020,
            "group_id": group,
            **{variable: np.nan for variable in drivers.RETRO_VARIABLES},
        }
        record.update({
            "HOT": value,
            "SMALL": value,
            "HOT&SMALL": value,
            "INST": value,
            "three_institutions_net_buy_fraction": float(value),
            "three_institutions_net_volume_ratio": float(value),
        })
        return record

    observations = pd.DataFrame([row("ge10", 1), row("ge5_lt10", 1), row("ge2_lt5", 0)])
    random = pd.DataFrame([{**row("random", 0), "matched_group": group} for group in (*drivers.RETRO_GROUPS, "ge5")])
    summaries, intervals, recommendation = drivers.retro_tables(observations, random, ["A"], reps=20)

    inst = summaries.loc[summaries.point.eq("first_2x") & summaries.variable.eq("INST")]
    assert "median" in summaries.columns
    assert inst.loc[inst.group_id.eq("ge10"), "median"].eq(1.0).all()
    assert set(intervals.bootstrap) == {"stock", "two_way"}
    random_intervals = intervals.loc[intervals.baseline.str.startswith("random:")]
    assert (random_intervals.baseline == "random:" + random_intervals.group_id).all()
    evidence = {item["variable"]: item for item in recommendation["evidence"]}
    # In this perfectly separated synthetic sample both cluster methods must agree.
    assert evidence["INST"]["supports_continuation"] is True
    assert recommendation["recommend_continue"] is True
    assert recommendation["owner_decision_required"] is True
