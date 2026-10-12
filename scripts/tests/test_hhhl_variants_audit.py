"""Invented event audit samples preserve timing and deterministic selection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_core.artifact_store import file_digest
from research_core.hhhl_variants_audit import _nullable, write_audit_samples
from research_core.hhhl_variants_inputs import StockInput


def invented_stock(ordinal: int, count: int) -> StockInput:
    code = f"{ordinal:04d}"
    dates = pd.bdate_range("2020-01-02", periods=60)
    raw = pd.DataFrame({"Date": dates, "Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.0, "VolumeLots": 123.0})
    raw.loc[0, "Close"] = np.nan
    events = pd.DataFrame([
        {
            "event_id": f"hhhl_rule_v4:TW:{code}:{dates[t0]:%Y-%m-%d}",
            "calendar_index": np.int64(t0),
            "restart_date": dates[t0 - 3],
            "Z2": 9.0,
            "hz_top": 9.5,
            "bonus_levels": "[]",
            "pivot_sequence": "[]",
            "has_old": False,
            "has_recent_far": False,
        }
        for t0 in range(10, 10 + count)
    ])
    return StockInput(
        ordinal,
        code,
        f"TW:{code}",
        raw,
        raw.drop(columns="VolumeLots").copy(),
        pd.DataFrame({"asof_date": dates, "regime": "up", "industry_ref": None}),
        events,
        np.array([], dtype=int),
        [(9, 12, 8.0)],
        np.ones(60),
        np.ones(60, dtype=bool),
    )


def stage(stocks: list[StockInput], root: Path) -> None:
    root.mkdir()
    for folder in ("features", "flags", "daily"):
        (root / folder).mkdir()
    for stock in stocks:
        daily = pd.DataFrame({"atr_pct": [np.nan] * 2 + [0.02] * 58, "ma20": np.nan, "ma60": np.nan})
        daily.to_parquet(root / f"daily/{stock.ordinal:04}.parquet", index=False)
        if stock.events.empty:
            continue
        features = stock.events.loc[:, ["calendar_index", "event_id"]].copy()
        features["G"] = [float(t0) for t0 in features.calendar_index]
        features["G_bin"] = "ge_5"
        features["G_status"] = "known"
        features["G_reason"] = None
        features.to_parquet(root / f"features/{stock.ordinal:04}.parquet", index=False)
        records = []
        for event in stock.events.to_dict(orient="records"):
            for cohort in ("P-clean", "P-all"):
                for horizon in (126, 252):
                    records.append({
                        "event_id": event["event_id"],
                        "cohort_id": cohort,
                        "horizon": horizon,
                        "landmark": 5,
                        "flag_id": "X4",
                        "trigger_return": np.nan,
                    })
        pd.DataFrame(records).to_parquet(root / f"flags/{stock.ordinal:04}.parquet", index=False)


def test_sampling_sort_then_hash_deterministic(tmp_path: Path) -> None:
    stocks = [invented_stock(2, 8), invented_stock(1, 8)]
    first, second = tmp_path / "first", tmp_path / "second"
    stage(stocks, first)
    stage(list(reversed(stocks)), second)
    receipt = write_audit_samples(stocks, first)
    repeated = write_audit_samples(list(reversed(stocks)), second)
    ordered = sorted((stock.code, event["calendar_index"], event["event_id"]) for stock in stocks for event in stock.events.to_dict(orient="records"))
    ids = [entry[2] for entry in ordered]
    expected = ids[:5] + sorted(ids[5:], key=lambda event: (hashlib.sha256(event.encode()).hexdigest(), event))[:5]
    assert receipt["selected_event_ids"] == expected
    assert receipt == repeated
    assert receipt["rows"] == 10
    assert receipt["sha256"] == file_digest(first / "audit/ten-events.json")
    assert set(receipt) == {"selected_event_ids", "rows", "sampling", "sha256"}
    with pytest.raises(FileExistsError):
        write_audit_samples(stocks, first)


def test_small_sample_keeps_all_nulls_and_confirmation_dates(tmp_path: Path) -> None:
    stock = invented_stock(1, 2)
    root = tmp_path / "small"
    stage([stock], root)
    receipt = write_audit_samples([stock], root)
    assert receipt["rows"] == 2
    payload = json.loads((root / "audit/ten-events.json").read_text(encoding="utf-8"))
    case = payload["cases"][0]
    before = case["feature_inputs_asof_t0"]
    assert before["common_calendar_prefix"][0]["raw"]["Close"] is None
    assert before["common_calendar_prefix"][0]["daily"]["atr_pct"] is None
    assert before["computed_features_asof_t0"]["G"] == 10.0
    assert before["computed_features_asof_t0"]["G_reason"] is None
    assert max(row["calendar_index"] for row in before["common_calendar_prefix"]) == 10
    outcome = case["outcome_flag_path_t0_to_H"]
    assert {row["cohort_id"] for row in outcome["flags"]} == {"P-clean"}
    assert {row["horizon"] for row in outcome["flags"]} == {126, 252}
    assert all(row["trigger_return"] is None for row in outcome["flags"])
    pivot = outcome["frozen_low_pivots"][0]
    assert pivot["extreme_index"] == 9 < 10 < pivot["confirmed_index"] == 12
    assert pivot["extreme_date"] != pivot["confirmed_date"]
    assert outcome["closing_path"][0]["offset"] == 0
    assert outcome["closing_path"][-1]["offset"] == 49
    assert "NaN" not in (root / "audit/ten-events.json").read_text(encoding="utf-8")


def test_no_original_events_needs_no_feature_shards(tmp_path: Path) -> None:
    stock = invented_stock(1, 0)
    root = tmp_path / "empty"
    stage([stock], root)
    result = write_audit_samples([stock], root)
    assert result["selected_event_ids"] == [] and result["rows"] == 0


def test_original_duplicate_ids_rejected(tmp_path: Path) -> None:
    stock = invented_stock(1, 2)
    stock.events.loc[1, "event_id"] = stock.events.loc[0, "event_id"]
    with pytest.raises(ValueError, match="distinct original"):
        write_audit_samples([stock], tmp_path)


def test_recursive_numpy_and_timestamp_nullable_conversion() -> None:
    result = _nullable({
        "date": np.datetime64("2020-01-02", "ns"),
        "missing": np.datetime64("NaT"),
        "values": [np.float64(np.inf), np.int64(2), np.bool_(True), pd.NA],
    })
    assert result == {"date": "2020-01-02T00:00:00", "missing": None, "values": [None, 2, True, None]}
