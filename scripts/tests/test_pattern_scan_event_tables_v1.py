from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core.artifact_store import object_digest
from research_core.pattern_scan_classification_cache_v1 import ConditionClassificationCache
from research_core.pattern_scan_event_outcomes_v1 import EventIdentity
from research_core.pattern_scan_event_tables_v1 import EventTables, build_event_tables
from research_core.pattern_scan_stock_v1 import EVENT_COLUMNS


def _inputs() -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    n = 380
    calendar = pd.date_range("2020-01-01", periods=n)
    dates = calendar.strftime("%Y-%m-%d").tolist()
    prices = pd.DataFrame({"Close": 100.0, "Low": 90.0, "quality_reason": None}, index=calendar)
    prices.iloc[10, prices.columns.get_loc("quality_reason")] = "unexplained_jump"
    controls = pd.DataFrame(index=calendar)
    for name in ("C-base", "C-52w", "C-dip", "C-trend", "C-nh", "C-P1-breakout"):
        values = np.zeros(n, dtype=np.int8)
        if name == "C-base":
            values[100:102] = 1
        else:
            values[260:262] = 1
        controls[name] = values
        controls[f"{name}:formula"] = values
        controls[f"{name}:cooled"] = np.isin(np.arange(n), [100] if name == "C-base" else [260])
    patterns = pd.DataFrame({name: np.zeros(n, dtype=np.int8) for name in ("B1", "B1:B1a", "B1:B1b", "L1", "L1:L1")}, index=calendar)
    patterns.loc[calendar[100], ["B1", "B1:B1a", "L1", "L1:L1"]] = 1
    patterns.loc[calendar[101], "B1"] = -1
    rows = []
    for pattern, subtype, cohort, start in (("B1", "B1a", "B1a", 0), ("B1", "union", "union", 0), ("L1", "L1", "L1", 60), ("L1", "union", "union", 60)):
        row: dict[str, Any] = dict.fromkeys(EVENT_COLUMNS)
        row.update(
            security_id="TW:0001",
            event_id=EventIdentity("TW:0001", dates[100], pattern, subtype, "def.v1", "input.v1").event_id,
            t0=dates[100],
            calendar_index=100,
            pattern_id=pattern,
            subtype_id=subtype,
            cohort_id=cohort,
            window_start=start,
            pivot=100.0,
            support=90.0,
            lower=80.0,
            member_subtype_ids="[]",
            member_event_ids="[]",
            member_metadata="[]",
            details_json="{}",
            base_eligible=True,
            eligibility_reason=None,
            definition_id="def.v1",
            input_id="input.v1",
        )
        rows.append(row)
    labels = pd.DataFrame([
        {
            "security_id": "TW:0001",
            "t0": date,
            "calendar_index": t,
            "horizon": horizon,
            "label": "hit" if t + horizon < n else "unknown",
            "calendar_full": t + horizon < n,
            "main_eligible": t + horizon < n,
            "unknown_reason": None if t + horizon < n else "truncated",
        }
        for t, date in enumerate(dates)
        for horizon in (126, 252)
    ])
    identity = {"security_id": "TW:0001", "t0": dates, "calendar_index": np.arange(n)}
    common = pd.DataFrame({**identity, "G": 2.0}, index=calendar)
    global_values = pd.DataFrame({**identity, "H": 90.0, "J": 1, "K3": "high", "MKT": "up", "PAT_other_B1": 1, "PAT_other_L1": 1}, index=calendar)
    tables = {
        "prices": prices,
        "indicators": prices[["Close", "Low"]].copy(),
        "pivots": pd.DataFrame(),
        "common_values": common,
        "universe": pd.DataFrame({"base_eligible": True, "eligibility_reason": None}, index=calendar),
        "pattern_states": patterns,
        "cohort_events": pd.DataFrame(rows, columns=pd.Index(EVENT_COLUMNS)),
        "controls": controls,
        "base_labels": labels,
    }
    return tables, global_values


def _build(target: str, tables: dict[str, pd.DataFrame], global_values: pd.DataFrame) -> EventTables:
    return build_event_tables(
        target,
        tables,
        global_values,
        security_id="TW:0001",
        definition_id="def.v1",
        input_id="input.v1",
        base_label_version_id="base.v1",
        base_label_manifest_sha256=object_digest({"synthetic": True}),
    )


def test_shared_stock_classification_cache_preserves_complete_event_tables() -> None:
    tables, global_values = _inputs()
    originals = {name: frame.copy(deep=True) for name, frame in tables.items()}
    global_before = global_values.copy(deep=True)
    cache = ConditionClassificationCache()
    for target in ("B1", "L1", "B1"):
        expected = _build(target, tables, global_values)
        actual = build_event_tables(
            target,
            tables,
            global_values,
            security_id="TW:0001",
            definition_id="def.v1",
            input_id="input.v1",
            base_label_version_id="base.v1",
            base_label_manifest_sha256=object_digest({"synthetic": True}),
            classification_cache=cache,
        )
        for name in ("events", "conditions", "group_memberships"):
            pd.testing.assert_frame_equal(getattr(actual, name), getattr(expected, name))
        for name in ("daily_groups", "formula_groups"):
            assert set(getattr(actual, name)) == set(getattr(expected, name))
            for group in getattr(actual, name):
                pd.testing.assert_series_equal(getattr(actual, name)[group], getattr(expected, name)[group])
    for name, original in originals.items():
        pd.testing.assert_frame_equal(tables[name], original)
    pd.testing.assert_frame_equal(global_values, global_before)


def test_same_base_b1_l1_scoped_quality_and_conditions() -> None:
    tables, global_values = _inputs()
    before = tables["base_labels"].copy(deep=True)
    b1, l1 = _build("B1", tables, global_values), _build("L1", tables, global_values)
    for result, target, effective in ((b1, "B1", "unknown"), (l1, "L1", "hit")):
        projected = result.events.loc[result.events.pattern_id.eq(target)]
        assert projected.base_label.eq("hit").all()
        assert projected.effective_label.eq(effective).all()
        assert not result.events.duplicated(["event_id", "horizon"]).any()
        assert not result.conditions.event_id.duplicated().any()
        assert cast(pd.Series, result.conditions[f"PAT_other_{target}_status"]).eq("not_applicable").all()
        assert result.conditions.H.eq(90).all()
    pd.testing.assert_frame_equal(tables["base_labels"], before)


def test_cooled_daily_aliases_share_identity_memberships_and_no_support() -> None:
    tables, global_values = _inputs()
    result = _build("B1", tables, global_values)
    memberships = result.group_memberships
    cooled = memberships.loc[memberships.group_id.eq("C-52w"), "event_id"].tolist()
    daily = memberships.loc[memberships.group_id.eq("C-52w-daily"), "event_id"].tolist()
    assert len(cooled) == 1 and len(daily) == 2 and cooled[0] in daily
    event = result.events.loc[result.events.event_id.eq(cooled[0])]
    assert len(event) == 2 and event.cohort_id.eq("C-52w").all()
    conditions = result.conditions.loc[result.conditions.event_id.eq(cooled[0])]
    assert conditions.SR_support_status.eq("not_applicable").all()
    assert result.daily_groups["C-base-no-pattern"].iloc[101] == -1
    same_day = result.events.loc[result.events.calendar_index.eq(260)]
    assert same_day.event_id.nunique() == 5


@pytest.mark.parametrize("damage", ("calendar", "security", "definition", "global_column"))
def test_wrong_fixed_identity_or_calendar_rejected(damage: str) -> None:
    tables, global_values = _inputs()
    if damage == "calendar":
        global_values.index += pd.Timedelta(days=1)
    elif damage == "security":
        global_values["security_id"] = "TW:other"
    elif damage == "definition":
        tables["cohort_events"]["definition_id"] = "changed"
    else:
        global_values["G"] = 999
    with pytest.raises(ValueError):
        _build("B1", tables, global_values)


def test_zero_groups_keep_event_projection_and_membership_schemas() -> None:
    tables, global_values = _inputs()
    tables["cohort_events"] = tables["cohort_events"].iloc[:0]
    tables["universe"]["base_eligible"] = False
    tables["universe"]["eligibility_reason"] = "synthetic_excluded"
    for column in tables["controls"]:
        tables["controls"][column] = False if column.endswith(":cooled") else 0
    result = _build("B1", tables, global_values)
    assert result.events.empty and {"event_id", "horizon", "effective_label"}.issubset(result.events)
    assert result.conditions.empty and "event_id" in result.conditions
    assert tuple(result.group_memberships.columns) == ("group_id", "event_id")


def test_identical_canonical_duplicates_preserve_complete_tables_and_inputs() -> None:
    tables, global_values = _inputs()
    expected = _build("B1", tables, global_values)
    tables["cohort_events"] = pd.concat([tables["cohort_events"], tables["cohort_events"].iloc[[0]]], ignore_index=True)
    originals = {name: frame.copy(deep=True) for name, frame in tables.items()}
    original_global = global_values.copy(deep=True)
    actual = _build("B1", tables, global_values)
    for name in ("events", "conditions", "group_memberships"):
        pd.testing.assert_frame_equal(getattr(actual, name), getattr(expected, name))
    for name in ("daily_groups", "formula_groups"):
        actual_groups, expected_groups = getattr(actual, name), getattr(expected, name)
        assert tuple(actual_groups) == tuple(expected_groups)
        for group_id in actual_groups:
            pd.testing.assert_series_equal(actual_groups[group_id], expected_groups[group_id])
    for name, original in originals.items():
        pd.testing.assert_frame_equal(tables[name], original)
    pd.testing.assert_frame_equal(global_values, original_global)


@pytest.mark.parametrize(("column", "value"), (("support", 91.0), ("support", None), ("details_json", '{"conflict":true}')))
def test_conflicting_canonical_duplicate_metadata_rejected(column: str, value: Any) -> None:
    tables, global_values = _inputs()
    duplicate = tables["cohort_events"].iloc[[0]].copy(deep=True)
    duplicate[column] = value
    tables["cohort_events"] = pd.concat([tables["cohort_events"], duplicate], ignore_index=True)
    before = tables["cohort_events"].copy(deep=True)
    with pytest.raises(ValueError, match="duplicate canonical event identity has differing metadata"):
        _build("B1", tables, global_values)
    pd.testing.assert_frame_equal(tables["cohort_events"], before)
