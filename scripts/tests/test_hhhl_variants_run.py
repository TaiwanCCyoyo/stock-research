"""Whole fixed pipeline on invented prices; never opens primary market data."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_variants_inputs import StockInput, calendar_identity, require_hash
from research_core.hhhl_variants_run import cross_section, implementation_receipt, run_study


class InventedBundle:
    def __init__(self, n: int = 310) -> None:
        self.tables = [{"security_id": f"TW:{code}"} for code in ("0000", "0001")]
        self.n = n

    def stock(self, ordinal: int) -> StockInput:
        code = ("0000", "0001")[ordinal - 1]
        n = self.n
        dates = pd.bdate_range("2019-01-02", periods=n)
        closing = 10 * 2 ** (np.arange(n) / 100)
        raw = pd.DataFrame({"Date": dates, "Open": closing, "High": closing + 1, "Low": closing - 1, "Close": closing, "VolumeLots": 1000 + np.arange(n) % 20})
        adjusted = raw.drop(columns=["VolumeLots"]).copy()
        context = pd.DataFrame({"asof_date": dates, "base_eligible": True, "eligibility_reason": None, "regime": "up", "industry_ref": "synthetic-industry"})
        records = []
        for t0 in (20, 90):
            over = ordinal == 2
            records.append({
                "event_id": f"hhhl_rule_v4:TW:{code}:{dates[t0]:%Y-%m-%d}",
                "calendar_index": t0,
                "restart_date": f"{dates[t0 - 5]:%Y-%m-%d}",
                "Z2": closing[t0] * 0.9,
                "hz_top": closing[t0] * 0.98,
                "bonus_levels": json.dumps([{"age": "old", "level": closing[t0] * 3}] if over else []),
                "pivot_sequence": json.dumps([{"k": "L", "rel": "higher", "p": closing[t0] * 0.9, "date": f"{dates[t0 - 2]:%Y-%m-%d}"}]),
                "cat": "hhhl",
                "big_hhhl": False,
                "vx": 1.6,
                "has_old": over,
                "has_recent_far": False,
            })
        events = pd.DataFrame(records)
        volume = raw["VolumeLots"]
        legacy_vx = (volume / volume.shift().rolling(20, min_periods=1).mean()).to_numpy()
        legacy_vx[[20, 90]] = 1.6
        return StockInput(
            ordinal,
            code,
            f"TW:{code}",
            raw,
            adjusted,
            context,
            events,
            np.array([30, 60, 110, 150, 280]),
            [(15, 22, float(closing[15] - 1))],
            legacy_vx,
            np.arange(n) >= 20,
        )


def test_pipeline_preserves_main_denominators_unknowns_and_empty_cells(tmp_path: Path) -> None:
    summary, selection = run_study(InventedBundle(), tmp_path)
    assert not selection["candidates"]  # fixed 300/60 gates were not relaxed
    base = summary.loc[summary.row_kind.eq("baseline") & summary.cohort_id.eq("P-all")]
    assert len(base) == 4
    assert np.allclose(base.calendar_full_n, base.hit_n + base.loss_n + base.flat_win_n + base.unknown_n)
    full126 = base.loc[base.horizon.eq(126)]
    assert full126.hit_n.sum() == 4
    full252 = base.loc[base.horizon.eq(252)]
    assert full252.hit_n.sum() == 2 and full252.censored_n.sum() == 2
    assert base.known_security_n.max() <= 2
    empty = summary.loc[summary.row_kind.eq("baseline") & summary.cohort_id.eq("C-52w")]
    assert len(empty) == 4 and empty.known_n.eq(0).all() and empty.hit_rate.isna().all()
    flag = summary.loc[
        summary.row_kind.eq("reverse_flag") & summary.flag_id.eq("X4") & summary.cohort_id.eq("P-all") & summary.horizon.eq(126) & summary.landmark.eq(5)
    ]
    assert flag.cost_denominator_n.sum() == 4
    assert flag.hit_flag_triggered_n.sum() == 2  # earlier extreme confirmed aftert0
    for ordinal in (1, 2):
        obs = pd.read_parquet(tmp_path / f"observations/{ordinal:04}.parquet")
        assert not obs.duplicated(["cohort_id", "event_id", "horizon"]).any()
    assert not (tmp_path / "manifest.json").exists()  # test never publishes a real dataset


def test_cross_section_ties_other_code_and_missing_industry() -> None:
    rows = []
    for code, industry, amount in (("001", "i", 100.0), ("002", "i", 100.0), ("003", None, 100.0)):
        for t in range(12):
            rows.append({
                "code": code,
                "industry_ref": industry,
                "calendar_index": t,
                "Date": pd.Timestamp("2019-01-02") + pd.Timedelta(days=t),
                "base_eligible": True,
                "legacy_liquid": True,
                "ret120": 0.5,
                "turnover20": amount,
                "is_cnh": code == "001" and t == 0,
            })
    result, boundaries = cross_section(pd.DataFrame(rows))
    assert np.allclose(result.H, (2 / 3) * 100)
    assert result.K3.eq("low").all()  # ties kept together; no code sorting split
    assert result.loc[result.code.eq("001") & result.calendar_index.eq(10), "J"].iloc[0] == 0
    assert result.loc[result.code.eq("002") & result.calendar_index.eq(10), "J"].iloc[0] == 1
    assert result.loc[result.code.eq("002") & result.calendar_index.eq(11), "J"].iloc[0] == 0
    assert result.loc[result.code.eq("003"), "J"].isna().all()
    assert boundaries.k3_security_n.eq(3).all()


def test_input_calendar_and_hash_fail_closed(tmp_path: Path) -> None:
    dates = pd.bdate_range("2019-01-02", periods=3)
    assert calendar_identity(dates)["rows"] == 3
    with pytest.raises(ValueError, match="calendar"):
        calendar_identity(pd.DatetimeIndex([dates[1], dates[0]]))
    artifact = tmp_path / "frozen.bin"
    artifact.write_bytes(b"invented only")
    with pytest.raises(ValueError, match="hash mismatch"):
        require_hash(artifact, "0" * 64)
    with pytest.raises(ValueError, match="PR7"):
        implementation_receipt("0" * 40)
