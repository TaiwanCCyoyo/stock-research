"""Subprocess-only one-off verifier tests over an invented empty publication."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from itertools import product
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest

from research_core.artifact_store import write_json
from research_core.hhhl_variants_flag_summary import FlagSummaries
from research_core.hhhl_variants_query import REQUIRED_COLUMNS, summary_transport
from research_core.hhhl_variants_rates import RateAccumulator
from research_core.hhhl_variants_summary import StudySummaries

ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "tasks/20261012-hhhl-v4-variants/evidence/verify_summary.py"


@pytest.fixture(scope="module")
def invented_frame() -> pd.DataFrame:
    summary = StudySummaries()
    for cohort in ("P-clean", "P-over", "P-all", "C-nh", "C-52w", "C-base"):
        for split in ("development", "cross-check"):
            for horizon in (126, 252):
                summary.initialize_group(cohort, split, horizon)
    legacy = RateAccumulator()
    for cohort, split, horizon, landmark, age, state in product(
        ("P-clean", "P-over"), ("development", "cross-check"), (126, 252), (5, 10, 20, 40), ("old", "recent_far"), ("triggered", "all_false", "unknown")
    ):
        metadata = dict(
            row_kind="legacy_cross",
            cohort_id=cohort,
            split_id=split,
            horizon=horizon,
            landmark=landmark,
            flag_id=f"legacy_{age}",
            flag_state=state,
            riskset_id="legacy_active",
            feature_price_basis="frozen_v4_factor",
            not_applicable_reason="no_bonus_lines" if cohort == "P-clean" else None,
        )
        legacy.add((cohort, split, horizon, landmark, age, state), metadata, 2019, {})
    near = []
    for cohort, bins in (("P-clean", ("ge100", "ge095")), ("C-52w", ("clean_overlap",))):
        for split, bin_id in product(("development", "cross-check", "pooled"), bins):
            near.append(
                dict(
                    row_kind="near_high",
                    base_row_kind="near_high",
                    cohort_id=cohort,
                    split_id=split,
                    feature_id="D",
                    bin_id=bin_id,
                    near_high_all_n=0,
                    near_high_known_n=0,
                    near_high_unknown_n=0,
                    near_high_matched_n=0,
                    near_high_rate=None,
                    near_high_lower=None,
                    near_high_upper=None,
                )
            )
    frame = pd.concat([summary.finalize(), FlagSummaries().finalize(), pd.DataFrame(legacy.finalize()), pd.DataFrame(near)], ignore_index=True)
    defaults: dict[str, Any] = {name: None for name in REQUIRED_COLUMNS if name not in frame}
    defaults["known_security_n"] = 0
    defaults["flag_unknown_n"] = 0
    for name, value in defaults.items():
        if name not in frame:
            frame[name] = value
    for name in frame.columns:
        if str(name).endswith("_n") and name != "riskset_n":
            frame[name] = cast(pd.Series, frame[name]).fillna(0)
    return frame


def publish_invented(frame: pd.DataFrame, root: Path) -> None:
    stream = io.BytesIO()
    frame.to_parquet(stream, index=False)
    contents, descriptor = summary_transport(stream.getvalue(), len(frame))
    root.mkdir()
    for name, data in contents.items():
        (root / name).write_bytes(data)
    write_json(root / "receipt.json", {"schema_version": "hhhl-variants-publication.v1", "dataset_id": "invented-zero-events-only", "summary": descriptor})


def invoke(publication: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(VERIFIER), "--publication", str(publication)], cwd=ROOT, capture_output=True, text=True, check=False)


def test_invented_publication_complete_conservation(tmp_path: Path, invented_frame: pd.DataFrame) -> None:
    publication = tmp_path / "invented"
    publish_invented(invented_frame, publication)
    completed = invoke(publication)
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt["dataset_id"] == "invented-zero-events-only"
    assert receipt["checked"]["single_partitions"] == 5760
    assert receipt["checked"]["reverse_flag_slices"] == 4800
    assert receipt["checked"]["rise_partitions"] == 11520
    assert "hit_rate" not in receipt


def test_valid_transport_but_mutated_core_count_fails(tmp_path: Path, invented_frame: pd.DataFrame) -> None:
    broken = invented_frame.copy()
    broken.at[0, "hit_n"] = 1
    publication = tmp_path / "mutated"
    publish_invented(broken, publication)
    completed = invoke(publication)
    assert completed.returncode != 0
    assert "full labels do not partition" in completed.stderr


def test_missing_annual_row_fails(tmp_path: Path, invented_frame: pd.DataFrame) -> None:
    broken = invented_frame.drop(index=1)
    publication = tmp_path / "missing-year"
    publish_invented(broken, publication)
    completed = invoke(publication)
    assert completed.returncode != 0
    assert "fixed annual/drop table incomplete" in completed.stderr


def invoke_basic(frame: pd.DataFrame, path: Path) -> subprocess.CompletedProcess[str]:
    """Exercise the retained verifier's basic checks in a fresh subprocess."""
    frame.to_parquet(path, index=False)
    program = "import runpy,sys,pandas as pd; runpy.run_path(sys.argv[1])['Conservation'](pd.read_parquet(sys.argv[2])).basic()"
    return subprocess.run([sys.executable, "-c", program, str(VERIFIER), str(path)], cwd=ROOT, capture_output=True, text=True, check=False)


def nonzero_group(*, zero_hits: bool = False) -> pd.DataFrame:
    accumulator = RateAccumulator()
    metadata = {"row_kind": "baseline", "cohort_id": "P-all", "split_id": "development", "horizon": 126}
    key = ("baseline", "P-all", "development", 126)
    if zero_hits:
        accumulator.add(key, metadata, 2020, {"calendar_full_n": 1, "loss_n": 1}, ("0001",))
        accumulator.add(key, metadata, 2021, {"calendar_full_n": 1, "unknown_n": 1})
    else:
        accumulator.add(
            key,
            metadata,
            2020,
            {"calendar_full_n": 3, "hit_n": 2, "unknown_n": 1, "censored_n": 1, "censored_unknown_n": 1},
            ("0001", "0002"),
        )
        accumulator.add(key, metadata, 2021, {"calendar_full_n": 3, "hit_n": 1, "loss_n": 1, "flat_win_n": 1}, ("0001",))
    return pd.DataFrame(accumulator.finalize())


def test_nonzero_basic_group_accepts_maximum_hit_year(tmp_path: Path) -> None:
    frame = nonzero_group()
    completed = invoke_basic(frame, tmp_path / "nonzero.parquet")
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("wrong_year", [None, 2026])
def test_internally_consistent_wrong_drop_year_fails(tmp_path: Path, wrong_year: int | None) -> None:
    frame = nonzero_group()
    pooled = cast(pd.Series, frame.iloc[0]).copy()
    pooled["row_kind"] = "drop_best_year"
    pooled["removed_year"] = wrong_year
    # None or an empty 2026 both retain every event, so pooled counts and all
    # rates are internally consistent. Only the fixed year-selection rule fails.
    frame.loc[frame.index[-1]] = pooled
    completed = invoke_basic(frame, tmp_path / "wrong-drop.parquet")
    assert completed.returncode != 0
    assert "removed year differs from maximum-hit earliest-event year" in completed.stderr


def test_zero_hit_uses_earliest_observed_event_year(tmp_path: Path) -> None:
    frame = nonzero_group(zero_hits=True)
    completed = invoke_basic(frame, tmp_path / "zero-hit-correct.parquet")
    assert completed.returncode == 0, completed.stderr
    drop = cast(pd.Series, frame.iloc[-1]).copy()
    # Drop 2021 instead, preserving 2020's loss event and every corresponding
    # rate/count. Choosing an equally zero-hit later year must be rejected.
    retained = cast(pd.Series, frame.loc[frame["year"].eq(2020)].iloc[0])
    for name in frame.columns:
        if str(name).endswith("_n") or str(name) in (
            "hit_rate",
            "loss_rate",
            "hit_lower",
            "hit_upper",
            "loss_lower",
            "loss_upper",
            "censored_hit_lower",
            "censored_hit_upper",
            "small_sample",
        ):
            drop[name] = retained[name]
    drop["removed_year"] = 2021
    frame.loc[frame.index[-1]] = drop
    completed = invoke_basic(frame, tmp_path / "zero-hit-wrong.parquet")
    assert completed.returncode != 0
    assert "removed year differs from maximum-hit earliest-event year" in completed.stderr
