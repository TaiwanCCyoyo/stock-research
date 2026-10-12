"""Subprocess-only one-off verifier tests over an invented empty publication."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from itertools import product
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core.artifact_store import write_json
from research_core.hhhl_variants_features import FEATURES
from research_core.hhhl_variants_flag_summary import FlagSummaries
from research_core.hhhl_variants_paths import event_flag_records, outcomes_for_closes
from research_core.hhhl_variants_query import REQUIRED_COLUMNS, summary_transport
from research_core.hhhl_variants_rates import RateAccumulator
from research_core.hhhl_variants_selection import split_for_code
from research_core.hhhl_variants_summary import StudySummaries
from research_core.hhhl_variants_summary_fast_v1 import FastStudySummaries

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


def complete_nonzero_frame(empty: pd.DataFrame, *, zero_hits: bool = False) -> pd.DataFrame:
    """Build all CLI-required tables exclusively through public library APIs."""
    summary, flags = FastStudySummaries(), FlagSummaries()
    cohorts = ("P-clean", "P-over", "P-all", "C-nh", "C-52w", "C-base")
    splits = ("development", "cross-check")
    for cohort, split, horizon in product(cohorts, splits, (126, 252)):
        summary.initialize_group(cohort, split, horizon)
    codes = {split: next(str(index).zfill(4) for index in range(1, 99) if split_for_code(str(index).zfill(4)) == split) for split in splits}
    observations: list[dict[str, Any]] = []
    flag_records: list[dict[str, Any]] = []
    variants = ("loss", "flat-win", "unknown", "censored") if zero_hits else ("early-hit", "late-hit", "loss", "flat-win", "unknown", "censored")
    for split, origin, year, variant in product(splits, ("P-clean", "P-over"), (2020, 2021), variants):
        # Independent cohort best years differ, exercising target drop-year
        # slicing against the P-all union rather than each cohort's own drop.
        if variant == "late-hit" and (origin == "P-clean" and year == 2021 or origin == "P-over" and year == 2020):
            continue
        close = np.full(253, 100.0)
        if variant == "early-hit":
            close[2] = 200.0
        elif variant == "late-hit":
            close[10], close[80] = 70.0, 200.0
        elif variant == "loss":
            close[126], close[252] = 80.0, 70.0
        elif variant == "unknown":
            close[10] = np.nan
        elif variant == "censored":
            close = close[:90]
        ma20 = np.full(len(close), 95.0)
        if variant == "late-hit":
            ma20[1] = np.nan
        raw_flags = event_flag_records(close, ma20, np.full(len(close), 90.0), 0, 80.0, 110.0, 60.0, [(0, 20, 70.0)])
        identity = dict(split_id=split, year=year, code=codes[split], event_id=f"{origin}-{split}-{year}-{variant}")
        for cohort in (origin, "P-all"):
            flag_records.extend({**record, **identity, "cohort_id": cohort} for record in raw_flags)
            for horizon in (126, 252):
                outcome = outcomes_for_closes(close, horizon).iloc[0].to_dict()
                row: dict[str, Any] = {**outcome, **identity, "cohort_id": cohort, "horizon": horizon}
                for feature, definition in FEATURES.items():
                    state = "not_applicable" if definition.overhead_only and origin != "P-over" else "feature_unknown" if variant == "unknown" else "known"
                    bins = sorted(set(definition.bin_ids))
                    row[f"{feature}_status"] = state
                    row[f"{feature}_bin"] = bins[year % len(bins)] if state == "known" else None
                    row[f"{feature}_reason"] = (
                        "outside_feature_cohort" if state == "not_applicable" else "synthetic_missing" if state == "feature_unknown" else None
                    )
                observations.append(row)
    summary.add_observations(pd.DataFrame(observations))
    flags.add_flags(pd.DataFrame(flag_records))
    retained = cast(pd.DataFrame, empty[empty["base_row_kind"].isin(("legacy_cross", "near_high"))])
    frame = pd.concat([summary.finalize(), flags.finalize(), retained], ignore_index=True)
    for name in frame.columns:
        if str(name).endswith("_n") and name != "riskset_n":
            frame[name] = cast(pd.Series, frame[name]).fillna(0)
    return frame


@pytest.fixture(scope="module")
def complete_frame(invented_frame: pd.DataFrame) -> pd.DataFrame:
    return complete_nonzero_frame(invented_frame)


@pytest.fixture(scope="module")
def zero_hit_frame(invented_frame: pd.DataFrame) -> pd.DataFrame:
    return complete_nonzero_frame(invented_frame, zero_hits=True)


def target_rows(frame: pd.DataFrame) -> pd.DataFrame:
    mask = frame["base_row_kind"].eq("baseline") & frame["cohort_id"].eq("P-all") & frame["split_id"].eq("development") & frame["horizon"].eq(126)
    return cast(pd.DataFrame, frame.loc[mask])


def test_nonzero_complete_publication_accepts_maximum_hit_year(tmp_path: Path, complete_frame: pd.DataFrame) -> None:
    publication = tmp_path / "nonzero"
    publish_invented(complete_frame, publication)
    completed = invoke(publication)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["checked"]["pattern_union_slices"] == 40


@pytest.mark.parametrize("wrong_year", [None, 2026])
def test_internally_consistent_wrong_drop_year_fails(tmp_path: Path, complete_frame: pd.DataFrame, wrong_year: int | None) -> None:
    frame = complete_frame.copy()
    target = target_rows(frame)
    pooled = cast(pd.Series, target.loc[target["row_kind"].eq("baseline")].iloc[0]).copy()
    pooled["row_kind"] = "drop_best_year"
    pooled["removed_year"] = wrong_year
    # None or an empty 2026 both retain every event, so pooled counts and all
    # rates are internally consistent. Only the fixed year-selection rule fails.
    drop_index = target.index[target["row_kind"].eq("drop_best_year")][0]
    frame.loc[drop_index] = pooled
    publication = tmp_path / "wrong-drop"
    publish_invented(frame, publication)
    completed = invoke(publication)
    assert completed.returncode != 0
    assert "removed year differs from maximum-hit earliest-event year" in completed.stderr


def test_zero_hit_uses_earliest_observed_event_year(tmp_path: Path, zero_hit_frame: pd.DataFrame) -> None:
    frame = zero_hit_frame.copy()
    target = target_rows(frame)
    publication = tmp_path / "zero-hit-correct"
    publish_invented(frame, publication)
    completed = invoke(publication)
    assert completed.returncode == 0, completed.stderr
    drop_index = target.index[target["row_kind"].eq("drop_best_year")][0]
    drop = cast(pd.Series, frame.loc[drop_index]).copy()
    # Drop 2021 instead, preserving 2020's loss event and every corresponding
    # rate/count. Choosing an equally zero-hit later year must be rejected.
    retained = cast(pd.Series, target.loc[target["year"].eq(2020)].iloc[0])
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
    frame.loc[drop_index] = drop
    publication = tmp_path / "zero-hit-wrong"
    publish_invented(frame, publication)
    completed = invoke(publication)
    assert completed.returncode != 0
    assert "removed year differs from maximum-hit earliest-event year" in completed.stderr
