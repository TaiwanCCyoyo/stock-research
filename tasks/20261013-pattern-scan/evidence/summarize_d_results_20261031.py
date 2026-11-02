"""Summarize saved D final tables; never calculate market features or outcomes.

Run from the delivery checkout using its Python environment. The Q1 root contains
<family>-summary.parquet; remaining root contains <family>/conditions,q4,followup.
Output is a new compact interpretation artifact, not a research receipt.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from research_core.pattern_scan_groups_v1 import PRIMARY  # noqa: E402

LOGGER = logging.getLogger(__name__)
COUNTS = ("hit_n", "known_n", "hit_rate", "loss_rate", "unknown_n", "censored_n")


def records(frame: pd.DataFrame) -> list[dict]:
    payload = frame.to_json(orient="records", double_precision=15)
    if payload is None:
        raise RuntimeError("DataFrame JSON serialization returned no text")
    return json.loads(payload)


def read_slice(path: Path, **filters: object) -> pd.DataFrame:
    return pd.read_parquet(path, filters=[(key, "==", value) for key, value in filters.items()])


def summarize(q1_root: Path, remaining_root: Path) -> dict:
    q1, candidates, coverage, paths, flags, landmarks = [], [], [], [], [], []
    for family, primary in sorted(PRIMARY.items()):
        LOGGER.info("Reading saved summaries for %s", family)
        first = read_slice(
            q1_root / f"{family}-summary.parquet", split="all", mkt="all", cohort_id="union", feature_id="unconditional", bin_id="all", condition_status="known"
        )
        first = first[first.control_id.isin(["pattern", "C-base-daily", "C-base-all", primary])]
        first = first[first.horizon.eq(252) | (first.era.eq("all") & first.row_kind.eq("full"))]
        q1.extend(records(pd.DataFrame(first[["pattern_id", "control_id", "horizon", "era", "row_kind", "removed_year", *COUNTS]])))
        root = remaining_root / family
        for horizon in (126, 252):
            groups = {}
            for control in ("pattern%3Aunion", "C-base-no-pattern", primary):
                name = f"{control}-h{horizon}"
                groups[control] = read_slice(
                    root / "conditions" / name / f"{family}-{name}-summary.parquet",
                    split="cross-check",
                    era="all",
                    mkt="all",
                    row_kind="full",
                    feature_id="candidate",
                    condition_status="known",
                ).set_index("candidate_id")
            pattern = groups["pattern%3Aunion"]
            delta = pattern.hit_rate - groups["C-base-no-pattern"].hit_rate
            primary_delta = pattern.hit_rate - groups[primary].hit_rate
            candidates.append({
                "family": family,
                "horizon": horizon,
                "candidate_n": len(pattern),
                "higher_n": int(delta.gt(0).sum()),
                "lower_n": int(delta.lt(0).sum()),
                "equal_n": int(delta.eq(0).sum()),
                "incomparable_n": int(delta.isna().sum()),
                "known_lt100_n": int(pattern.known_n.lt(100).sum()),
                "known_zero_n": int(pattern.known_n.eq(0).sum()),
                "primary_control": primary,
                "primary_higher_n": int(primary_delta.gt(0).sum()),
                "primary_comparable_n": int(primary_delta.notna().sum()),
            })
        cov = read_slice(root / "q4/coverage.parquet", split="cross-check", era="all", mkt="all")
        cov = cov[cov.group_id.isin([f"{family}:original", f"{family}:original:C-base-random"])]
        coverage.extend(
            records(
                pd.DataFrame(
                    cov[
                        [
                            "group_id",
                            "episode_n",
                            "matched_n",
                            "unmatched_n",
                            "unknown_n",
                            "coverage_rate",
                            "coverage_lower_bound",
                            "coverage_upper_bound",
                            "timing_known_n",
                            "timing_median",
                            "entry_return_known_n",
                            "entry_return_median",
                            "remaining_return_known_n",
                            "remaining_return_median",
                        ]
                    ]
                )
            )
        )
        facets = {"split_id": "cross-check", "era": "all", "mkt": "all", "group_id": family, "horizon": 252}
        path = read_slice(root / "followup/path_by_outcome.parquet", **facets)
        path = path[path.population.isin(["hit", "nonhit"])]
        paths.extend(records(pd.DataFrame(path[["group_id", "population", "path_category", "sample_n", "path_n"]])))
        flag = read_slice(root / "followup/flag_summary.parquet", **facets)
        flags.extend(
            records(
                pd.DataFrame(
                    flag[
                        [
                            "group_id",
                            "flag_id",
                            "nonhit_triggered_n",
                            "nonhit_known_n",
                            "nonhit_known_rate",
                            "nonhit_unknown_n",
                            "hit_cost_triggered_n",
                            "hit_cost_known_n",
                            "hit_cost_known_rate",
                            "hit_cost_unknown_n",
                        ]
                    ]
                )
            )
        )
        landmark = read_slice(root / "followup/landmark_summary.parquet", **facets)
        landmark = landmark[landmark.return_bin.ne("pooled")]
        paired = landmark.pivot(index=["flag_id", "landmark", "return_bin"], columns="flag_state", values=["hit_rate", "known_n"])
        paired = paired.dropna(subset=[("hit_rate", "triggered"), ("hit_rate", "all_false")])
        for flag_id, group in paired.groupby(level="flag_id"):
            delta = pd.Series(group["hit_rate"]["triggered"] - group["hit_rate"]["all_false"])
            landmarks.append({
                "family": family,
                "flag_id": flag_id,
                "comparable_n": len(group),
                "lower_n": int(delta.lt(0).sum()),
                "higher_n": int(delta.gt(0).sum()),
                "equal_n": int(delta.eq(0).sum()),
                "both_known_ge100_n": int(((group["known_n"]["triggered"] >= 100) & (group["known_n"]["all_false"] >= 100)).sum()),
            })
    candidate_frame = pd.DataFrame(candidates)
    totals = candidate_frame.groupby("horizon", as_index=False)[
        ["candidate_n", "higher_n", "lower_n", "equal_n", "incomparable_n", "known_lt100_n", "known_zero_n"]
    ].sum()
    landmark_totals = pd.DataFrame(landmarks)[["comparable_n", "lower_n", "higher_n", "equal_n", "both_known_ge100_n"]].sum().to_dict()
    flag_ranges = pd.DataFrame(flags).groupby("flag_id")[["nonhit_known_rate", "hit_cost_known_rate"]].agg(["min", "max"])
    flag_ranges.columns = ["_".join(column) for column in flag_ranges.columns]
    path_frame = pd.DataFrame(paths)
    path_frame["share"] = path_frame.sample_n / path_frame.groupby(["group_id", "population"]).sample_n.transform("sum")
    path_ranges = path_frame.groupby(["population", "path_category"], as_index=False).share.agg(["min", "max"])
    return {
        "schema": "pattern-scan.interpretation-evidence.v1",
        "scope": "Saved final tables only; descriptive overlapping events/cells, no acceptance gate or independent holdout.",
        "units": "Rates are fractions. Percentage points = 100 * (pattern_rate - control_rate).",
        "source_contract": {
            "roots": {"q1": "--q1-root: directory containing <family>-summary.parquet", "remaining": "--remaining-root: directory containing each family"},
            "q1": {
                "path": "q1/{family}-summary.parquet",
                "filters": {"split": "all", "mkt": "all", "cohort_id": "union", "feature_id": "unconditional", "bin_id": "all", "condition_status": "known"},
                "rows": "H252 all eras/full and drop_best_year; H126 all-era full. Pattern/daily/all/PRIMARY controls.",
                "columns": ["pattern_id", "control_id", "horizon", "era", "row_kind", "removed_year", *COUNTS],
            },
            "candidates": {
                "path": "remaining/{family}/conditions/{control}-h{horizon}/{family}-{control}-h{horizon}-summary.parquet",
                "controls": ["pattern%3Aunion", "C-base-no-pattern", "PRIMARY[family]"],
                "filters": {"split": "cross-check", "era": "all", "mkt": "all", "row_kind": "full", "feature_id": "candidate", "condition_status": "known"},
                "columns": ["candidate_id", "known_n", "hit_rate"],
                "formula": (
                    "Join by candidate_id; count sign(pattern.hit_rate - control.hit_rate). NaN difference is incomparable; no "
                    "sample filter or top-10 selection. Sum family counts: 12*92=1104 per horizon."
                ),
            },
            "coverage": {
                "path": "remaining/{family}/q4/coverage.parquet",
                "filters": "split=cross-check, era=all, mkt=all; original and its original:C-base-random",
                "formula": (
                    "coverage_rate=matched/(matched+unmatched); bounds=matched/episode_n and (matched+unknown)/episode_n; use "
                    "stored metric-specific known_n for timing."
                ),
            },
            "followup": {
                "path": "remaining/{family}/followup/{path_by_outcome,flag_summary,landmark_summary}.parquet",
                "filters": "split_id=cross-check, era=all, mkt=all, group_id=family (original union), horizon=252",
                "path_formula": (
                    "Within each family and population, path share=sample_n/sum(sample_n across path_category), including unknown "
                    "path; no cross-family pooling."
                ),
                "flag_formula": (
                    "nonhit_known_rate=nonhit_triggered_n/nonhit_known_n; "
                    "hit_cost_known_rate=hit_cost_triggered_n/hit_cost_known_n. Ranges are min/max across 12 families, never pooled "
                    "counts."
                ),
                "landmark_columns": ["flag_id", "landmark", "return_bin", "flag_state", "hit_rate", "known_n"],
                "landmark_formula": (
                    "Exclude return_bin=pooled. Pair triggered/all_false on family, flag_id, landmark, return_bin; retain when both "
                    "stored hit_rate non-null. Count signs of triggered minus all_false. All 9 flags, 4 landmarks, 4 bins; 1528 "
                    "comparable cells. both_known_ge100 requires each side known_n>=100."
                ),
            },
        },
        "q1": q1,
        "candidate_by_family": candidates,
        "candidate_totals": records(pd.DataFrame(totals)),
        "coverage_original_pairs": coverage,
        "path_populations_h252": paths,
        "path_share_ranges_h252": records(pd.DataFrame(path_ranges)),
        "flag_rates_h252": flags,
        "flag_rate_ranges_h252": records(flag_ranges.reset_index()),
        "landmark_by_family_flag_h252": landmarks,
        "landmark_totals_h252": {key: int(value) for key, value in landmark_totals.items()},
        "limitations": [
            "Each drop_best_year row removes its own highest-hit-count year, not necessarily the same year as its control.",
            "CRC cross-check period is already exposed; candidates, event sets and landmark cells overlap.",
            "Unknown and censored may overlap; rates with zero denominator stay null.",
            "No source/input hashing, raw-price reads, feature calculation, reselection or research execution.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--q1-root", type=Path, required=True)
    parser.add_argument("--remaining-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.output.exists():
        parser.error("output already exists; choose a new path")
    result = summarize(args.q1_root, args.remaining_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    LOGGER.info("Wrote interpretation summary to %s", args.output)


if __name__ == "__main__":
    main()
