from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core.industry_role_comparison import ARMS, CLASSIFICATION_BASIS, _triage, analyze, build_roles


def frame(size: int = 6) -> pd.DataFrame:
    result = pd.DataFrame({
        "security_id": [f"TW:{i}" for i in range(size)],
        "asof_date": pd.Timestamp("2020-01-02"),
        "calendar_index": 126,
        "year": 2020,
        "base_eligible": True,
        "industry_ref": "electronics",
        "classification_basis": CLASSIFICATION_BASIS,
        "ret20": 0.125,
        "ret60": 0.125,
        "rs60_percentile": 0.9,
        "market_state": "up",
    })
    for horizon in (63, 126):
        result[f"label_{horizon}"] = 1.0
        result[f"complete_{horizon}"] = True
        result[f"forward_return_{horizon}"] = horizon / 100
        result[f"min_return_{horizon}"] = -0.2
        result[f"max_drawdown_{horizon}"] = 0.3
        result[f"wait_to_threshold_{horizon}"] = 10.0
    return result


def pooled(output: dict[str, Any], arm: str = "all", panel: str = "daily", label: str = "label_126") -> dict[str, Any]:
    return next(row for row in output["comparisons"] if row["arm"] == arm and row["panel"] == panel and row["label"] == label and row["context_column"] is None)


def test_leave_one_out_excludes_only_actual_members_and_preserves_input() -> None:
    data = frame(7)
    data["ret20"] = [0.25, 0.125, 0.125, 0.125, 0.125, -0.125, 99.0]
    data["ret60"] = [0.5, 0.25, 0.125, 0.125, -0.125, -0.25, 99.0]
    data.loc[6, "base_eligible"] = False
    original = data.copy(deep=True)
    roles, audit = build_roles(data)
    assert roles.peer_count.tolist() == [5] * 6 + [6]
    assert roles.loc[0, "peer_mean_ret60"] == pytest.approx(0.125 / 5)
    assert roles.loc[0, "peer_mean_ret20"] == pytest.approx(0.375 / 5)
    assert roles.loc[0, "peer_positive60_fraction"] == 3 / 5
    # The ineligible outlier is never subtracted from the eligible pool.
    assert roles.loc[6, "peer_mean_ret60"] == pytest.approx(0.625 / 6)
    assert roles.loc[6, "peer_positive60_fraction"] == 4 / 6
    assert roles.loc[6, "role_missing_reason"] == "ineligible"
    assert roles.loc[0, "role"] == "leader"
    assert roles.loc[4, "role"] == "laggard_turning"
    assert roles.loc[5, "role"] == "laggard_weak"
    assert audit["n_peer_pool"] == audit["n_role_known"] == 6
    assert audit["missing_reason_counts"]["ineligible"] == 1
    pd.testing.assert_frame_equal(data, original)


def test_minimum_five_other_members_ties_zero_and_negative_returns() -> None:
    roles, _ = build_roles(frame(5))
    assert roles.role.eq("unknown").all()
    assert roles.role_missing_reason.eq("insufficient_peers").all()
    assert roles.peer_count.eq(4).all()
    roles, _ = build_roles(frame())
    assert roles.role.eq("leader").all()  # exact ties are leaders
    assert roles.peer_strength.eq("strong").all()
    decimal = frame().assign(ret60=0.1)
    roles, _ = build_roles(decimal)
    assert roles.role.eq("leader").all()  # arithmetic rounding does not break ties
    decimal.loc[0, "ret60"] = 0.1 - 1e-9
    roles, _ = build_roles(decimal)
    assert roles.loc[0, "role"] == "laggard_turning"
    data = frame()
    data.loc[0, ["ret20", "ret60"]] = [0.0, -0.125]
    roles, _ = build_roles(data)
    assert roles.loc[0, "role"] == "laggard_weak"  # zero is not turning
    data["ret60"] = 0.0
    roles, _ = build_roles(data)
    assert roles.role.eq("leader").all()
    assert roles.peer_strength.eq("other").all()  # mean must be strictly positive
    data["ret60"] = -0.125
    roles, _ = build_roles(data)
    assert roles.role.eq("leader").all()
    assert roles.peer_strength.eq("other").all()


def test_missing_industry_returns_and_rank_do_not_pollute_peer_pool() -> None:
    data = frame(10)
    data.loc[6:8, "industry_ref"] = ["unknown", " UNKNOWN ", "  "]
    data.loc[9, "ret20"] = np.nan
    data.loc[9, "ret60"] = 99.0
    data.loc[0, "rs60_percentile"] = np.nan
    roles, audit = build_roles(data)
    assert roles.loc[:5, "peer_count"].eq(5).all()
    assert roles.loc[:5, "role"].eq("leader").all()
    assert roles.loc[6:8, "peer_count"].eq(0).all()
    assert roles.loc[6:8, "role_missing_reason"].eq("missing_industry").all()
    assert roles.loc[9, "peer_count"] == 6
    assert roles.loc[9, "peer_mean_ret60"] == 0.125
    assert roles.loc[9, "role_missing_reason"] == "missing_returns"
    assert audit["n_role_known"] == 6 and audit["n_support"] == 5
    assert audit["n_eligible_support_missing"] == 5
    data.loc[6, "base_eligible"] = False
    roles, _ = build_roles(data)
    assert roles.loc[6, "role_missing_reason"] == "ineligible"


def test_future_outcomes_cannot_affect_roles_and_turning_is_only_short_positive_proxy() -> None:
    data = frame()
    data.loc[0, ["ret20", "ret60"]] = [0.01, 0.1]
    first, first_audit = build_roles(data)
    assert first.loc[0, "role"] == "laggard_turning"
    changed = data.copy()
    for horizon in (63, 126):
        changed[f"label_{horizon}"] = 0.0
        changed[f"complete_{horizon}"] = False
        changed[f"forward_return_{horizon}"] = -99.0
        changed[f"wait_to_threshold_{horizon}"] = np.nan
    second, second_audit = build_roles(changed)
    pd.testing.assert_frame_equal(first.iloc[:, len(data.columns) :], second.iloc[:, len(data.columns) :])
    assert first_audit == second_audit
    assert first_audit["turning_definition"] == "short_positive_proxy_not_proven_acceleration"


def test_common_support_preserves_eligible_missing_unknown_bounds_and_empty_selections() -> None:
    data = frame(8)
    data.loc[0, "rs60_percentile"] = np.nan
    data.loc[1, "ret20"] = np.nan
    data.loc[2, "label_126"] = np.nan
    data.loc[2, "complete_126"] = False
    data.loc[7, "base_eligible"] = False
    output = analyze(data)
    for arm in ARMS:
        row = pooled(output, arm)
        assert row["n_eligible"] == 7
        assert row["n_feature_known"] == 5
        assert row["n_feature_missing"] == 2
        assert row["same_context_base_rate"] == 1.0
    row = pooled(output)
    assert row["tp"] == row["selected_known"] == 4
    assert row["selected_unknown"] == 1
    assert row["precision_lower"] == 4 / 5
    assert row["precision_upper"] == 1.0
    assert row["selected_distinct_issuers"] == 4
    weak = pooled(output, "weak_strong")
    assert weak["selected_known"] == 0 and weak["precision"] is None
    paths = next(
        row
        for row in output["path_summaries"]
        if row["arm"] == "weak_strong"
        and row["panel"] == "daily"
        and row["label"] == "label_126"
        and row["context_column"] is None
        and row["outcome"] == "winner"
    )
    assert paths["metrics"]["forward_return"] == {"count": 0, "missing": 0, "mean": None, "p10": None, "median": None, "p90": None}
    assert "wait_to_threshold" in paths["metrics"]
    json.dumps(output, allow_nan=False)


def test_original_grid_and_independent_context_slices_and_horizon_paths() -> None:
    data = pd.concat(
        [
            frame().assign(asof_date=pd.Timestamp("2020-01-02"), calendar_index=125),
            frame().assign(asof_date=pd.Timestamp("2021-01-04"), year=2021, calendar_index=252, market_state="mixed"),
        ],
        ignore_index=True,
    )
    data.loc[0, "base_eligible"] = False
    data.loc[6, "label_126"] = 0.0
    data.loc[6, "forward_return_126"] = -0.1
    data.loc[6, "min_return_126"] = -0.5
    data.loc[6, "wait_to_threshold_126"] = np.nan
    output = analyze(data)
    assert pooled(output)["n_eligible"] == 11
    assert pooled(output, panel="grid126")["n_eligible"] == 6
    assert pooled(output, panel="grid126")["selected_distinct_dates"] == 1
    assert {row["context_column"] for row in output["comparisons"]} == {None, "year", "market_state", "industry_ref"}
    nonwinner = next(
        row
        for row in output["path_summaries"]
        if row["arm"] == "all" and row["panel"] == "grid126" and row["label"] == "label_126" and row["context_column"] is None and row["outcome"] == "nonwinner"
    )
    assert nonwinner["metrics"]["min_return"]["mean"] == -0.5
    assert "wait_to_threshold" not in nonwinner["metrics"]
    secondary = next(
        row
        for row in output["path_summaries"]
        if row["arm"] == "all" and row["panel"] == "grid126" and row["label"] == "label_63" and row["context_column"] is None and row["outcome"] == "all"
    )
    assert secondary["metrics"]["forward_return"]["mean"] == pytest.approx(0.63)


def test_actual_shared_winner_intersection_for_disjoint_and_zero_controls() -> None:
    data = frame()
    data["ret60"] = [0.5, 0.5, 0.125, 0.125, 0.125, 0.125]
    data["rs60_percentile"] = [0.1, 0.1, 0.9, 0.9, 0.9, 0.9]
    output = analyze(data)
    pair = next(
        row
        for row in output["paired_rows"]
        if row["arm"] == "leader_strong"
        and row["control"] == "relative_strength"
        and row["panel"] == "daily"
        and row["label"] == "label_126"
        and row["context_column"] is None
    )
    assert pair["candidate_tp"] == 2 and pair["control_tp"] == 4
    assert pair["retained_winners"] == 0 and pair["winner_retention"] == 0.0
    assert pair["differences"]["winner_coverage"] == pytest.approx(-1 / 3)
    data["label_126"] = 0.0
    output = analyze(data)
    assert all(row["winner_retention"] is None for row in output["paired_rows"] if row["label"] == "label_126")


def qualifying_comparisons() -> list[dict[str, Any]]:
    rows = []
    for arm in ("leader_strong", "turning_strong", "weak_strong", "peer_strong", "peer_strong_rs"):
        for panel in ("daily", "grid126"):
            for year in [None, 2019, 2020, 2021, 2022]:
                rows.append({
                    "arm": arm,
                    "panel": panel,
                    "label": "label_126",
                    "context_column": "year" if year else None,
                    "context_value": year,
                    "selected_known": 30,
                    "selected_distinct_issuers": 10,
                    "precision": 0.6 if arm.endswith("strong") and arm != "peer_strong" else 0.4,
                    "selected_unknown": 2,
                    "precision_lower": 0.3,
                    "precision_upper": 0.7,
                })
    return rows


def test_triage_exact_support_strict_comparators_ranking_and_insufficient_evidence() -> None:
    rows = qualifying_comparisons()
    output = _triage(rows)
    assert all(row["qualifies"] for row in output["candidates"])
    assert output["nomination"]["arm"] == "leader_strong"
    assert output["nomination"]["purpose"] == "account_design_only"
    for row in rows:
        if row["arm"] == "turning_strong":
            row["precision"] = 0.7
    assert _triage(rows)["nomination"]["arm"] == "turning_strong"
    for row in rows:
        if row["arm"] == "peer_strong_rs" and row["context_column"] is None:
            row["selected_known"] = 29
    output = _triage(rows)
    assert output["nomination"] is None
    assert all(row["status"] == "insufficient_evidence" for row in output["candidates"])
    assert all(not row["failed_precision_reasons"] for row in output["candidates"])
    assert all(any("insufficient_comparator" in reason for reason in row["reasons"]) for row in output["candidates"])
    rows = qualifying_comparisons()
    rows[0]["selected_distinct_issuers"] = 9
    assert not _triage(rows)["candidates"][0]["qualifies"]
    rows[0]["selected_distinct_issuers"] = 10
    rows[0]["precision"] = 0.4
    assert not _triage(rows)["candidates"][0]["qualifies"]


def test_triage_annual_majority_and_2026_secondary_diagnostics_cannot_rescue() -> None:
    rows = qualifying_comparisons()
    for row in rows:
        if row["arm"] in ("leader_strong", "turning_strong", "weak_strong") and row["context_value"] in (2019, 2020):
            row["precision"] = 0.4
    rows.extend({**row, "context_value": 2026} for row in list(rows) if row["context_value"] == 2022)
    rows.extend({**row, "label": "label_63", "precision": 1.0} for row in list(rows))
    assert _triage(rows)["nomination"] is None
    for row in rows:
        if row["arm"] in ("leader_strong", "turning_strong", "weak_strong") and row["context_value"] == 2019:
            row["precision"] = 0.6
    assert _triage(rows)["nomination"]["arm"] == "leader_strong"
    for row in rows:
        if row["context_value"] == 2022:
            row["selected_known"] = 29
    assert _triage(rows)["nomination"] is None


@pytest.mark.parametrize(
    "column,value,match",
    [
        ("ret20", np.inf, "finite"),
        ("ret60", -np.inf, "finite"),
        ("rs60_percentile", 1.1, "ranks"),
        ("rs60_percentile", -0.1, "ranks"),
        ("base_eligible", 1, "booleans"),
        ("classification_basis", "PIT", "classification_basis"),
        ("calendar_index", 126.5, "integers"),
        ("year", 2019, "year"),
        ("asof_date", "01/02/2020", "ISO"),
        ("industry_ref", 42, "strings"),
    ],
)
def test_invalid_role_contract_fails_closed(column: str, value: Any, match: str) -> None:
    data = frame()
    data[column] = value
    with pytest.raises(ValueError, match=match):
        build_roles(data)


def test_duplicate_keys_calendar_mappings_and_outcome_contract_rejected() -> None:
    data = frame()
    data.loc[1, "security_id"] = data.loc[0, "security_id"]
    with pytest.raises(ValueError, match="duplicate"):
        build_roles(data)
    data = frame()
    data.loc[1, "calendar_index"] = 127
    with pytest.raises(ValueError, match="mapping"):
        build_roles(data)
    data.loc[1, "asof_date"] = pd.Timestamp("2020-01-01")
    with pytest.raises(ValueError, match="order"):
        build_roles(data)
    for column, value, match in [
        ("label_126", 2.0, "binary"),
        ("complete_126", False, "complete"),
        ("min_return_126", np.nan, "finite"),
        ("max_drawdown_63", np.inf, "finite"),
        ("wait_to_threshold_126", np.nan, "finite"),
        ("market_state", "invalid", "market_state"),
    ]:
        data = frame()
        data[column] = value
        with pytest.raises(ValueError, match=match):
            analyze(data)


def test_eligible_industry_cap_and_completely_empty_population() -> None:
    data = frame(65)
    data["industry_ref"] = [f"industry{i}" for i in range(65)]
    with pytest.raises(ValueError, match="64"):
        analyze(data)
    data.loc[64, "base_eligible"] = False
    assert len(analyze(data)["comparisons"]) <= 2184
    output = analyze(frame().iloc[:0])
    assert output["role_audit"]["n_input"] == 0
    assert len(output["comparisons"]) == 28
    assert all(row["precision"] is None for row in output["comparisons"])
    assert output["triage"]["nomination"] is None
    json.dumps(output, allow_nan=False)


def test_all_missing_industry_and_zero_eligible_preserve_unknown_support() -> None:
    data = frame().assign(industry_ref=None)
    output = analyze(data)
    assert output["role_audit"]["missing_reason_counts"]["missing_industry"] == 6
    assert pooled(output)["n_feature_missing"] == 6
    null_context = next(row for row in output["comparisons"] if row["context_column"] == "industry_ref" and row["panel"] == "daily")
    assert null_context["context_value"] is None
    data = frame().assign(base_eligible=False)
    output = analyze(data)
    assert output["role_audit"]["n_eligible"] == 0
    assert pooled(output)["n_eligible"] == 0
    assert pooled(output)["precision"] is None
    assert output["triage"]["nomination"] is None
    json.dumps(output, allow_nan=False)


def test_nullable_classification_basis_missing_is_rejected() -> None:
    data = frame()
    data["classification_basis"] = data["classification_basis"].astype("string")
    data.loc[0, "classification_basis"] = pd.NA
    with pytest.raises(ValueError, match="classification_basis"):
        build_roles(data)
