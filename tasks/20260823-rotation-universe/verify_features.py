"""Gate: no feature reads a bar that had not happened yet.

A rolling window that forgot to shift produces a table that looks entirely normal -- correct
dtypes, sensible ranges, no gaps -- and a backtest built on it reports an edge that cannot
be traded. Nothing about the values themselves reveals the problem, so the only check worth
running is behavioural: recompute the features from a truncated price history and confirm
the values before the cut are identical.

Four checks:

  truncation   features on dates <= cut are unchanged when every bar after cut is deleted
  extension    the same, per feature column, so a single leaking column is named rather
               than hidden inside an aggregate pass
  ranks        percentile ranks are computed among that date's eligible symbols only, and
               land in (0, 1]
  cohort       the cohort columns exclude the symbol's own return

Run from the repository root:
    uv run python tasks/20260823-rotation-universe/verify_features.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

import pandas as pd

TASK_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TASK_ROOT.parents[1]
sys.path.insert(0, str(TASK_ROOT))

from features import FEATURE_COLUMNS, RANK_COLUMNS, compute, load_categories, load_prices  # noqa: E402

CUT = "2025-03-14"
SAMPLE = 120
SEED = 20260823


def main() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(label)

    px = load_prices()
    meta = load_categories()

    codes = sorted(px["Code"].unique())
    sample = set(pd.Series(codes).sample(SAMPLE, random_state=SEED).tolist())
    sample |= {"6223", "6510", "2344", "8299", "2327", "2492", "3026", "3491", "2313"}
    sub = cast(pd.DataFrame, px[px["Code"].isin(tuple(sample))].copy())

    full = compute(sub, meta)
    truncated = compute(cast(pd.DataFrame, sub[sub["Date"] <= CUT].copy()), meta)

    a = cast(pd.DataFrame, full[full["Date"] <= CUT]).sort_values(["Code", "Date"]).reset_index(drop=True)
    b = truncated.sort_values(["Code", "Date"]).reset_index(drop=True)

    check(
        "truncated run covers the same (Code, Date) rows",
        len(a) == len(b) and (a["Code"].equals(b["Code"])) and (a["Date"].equals(b["Date"])),
        f"{len(a)} vs {len(b)} rows",
    )

    leaking = []
    for column in FEATURE_COLUMNS:
        same = a[column].round(10).equals(b[column].round(10))
        both_nan = a[column].isna().equals(b[column].isna())
        if not (same and both_nan):
            differing = (a[column].round(10) != b[column].round(10)) & ~(a[column].isna() & b[column].isna())
            leaking.append(f"{column} ({int(differing.sum())} rows)")
    check(
        f"no feature changes when bars after {CUT} are deleted ({len(a):,} rows x {len(FEATURE_COLUMNS)} columns)",
        not leaking,
        ", ".join(leaking),
    )

    # Ranks are recomputed among a different eligible set in the truncated run only if
    # eligibility itself leaked, which the eligibility gate covers; here just check shape.
    ranked = cast(pd.DataFrame, full[full["eligible"]])
    bad_range = []
    for column in RANK_COLUMNS:
        values = cast(pd.Series, ranked[column]).dropna()
        if values.empty:
            bad_range.append(f"{column} all-NaN")
        elif values.min() <= 0 or values.max() > 1:
            bad_range.append(f"{column} [{values.min():.3f}, {values.max():.3f}]")
    check("percentile ranks land in (0, 1]", not bad_range, ", ".join(bad_range))

    ineligible_ranked = cast(pd.Series, cast(pd.DataFrame, full[~full["eligible"]][RANK_COLUMNS]).notna().any(axis=1)).sum()
    check("ineligible rows carry no rank", ineligible_ranked == 0, f"{ineligible_ranked} rows")

    # Cohort self-exclusion: build a three-member category by hand -- the minimum the guard
    # in `_cohort` accepts -- and confirm each member's cohort return is the mean of the
    # other two, not its own and not the trio's average.
    trio = ["2327", "2492", "3026"]
    probe = cast(pd.DataFrame, sub[cast(pd.Series, sub["Code"]).isin(trio)].copy())
    fake_meta = pd.DataFrame({"Code": trio, "industry_category": ["PROBE"] * 3})
    pair = compute(probe, fake_meta)
    latest = pair[pair["Date"] == pair["Date"].max()].set_index("Code")
    deltas = []
    if len(latest) == 3:
        for code in trio:
            others = [c for c in trio if c != code]
            expected = sum(float(latest.loc[c, "ret_20"]) for c in others) / 2
            deltas.append(abs(float(latest.loc[code, "cohort_ret_20"]) - expected))
    ok_trio = len(deltas) == 3 and max(deltas) < 1e-9
    check(
        "cohort return is the mean of the other members, excluding the symbol itself",
        ok_trio,
        f"max deviation {max(deltas):.3e}" if deltas else "unexpected shape",
    )

    # And the guard: a two-member category yields no cohort value at all.
    duo = cast(pd.DataFrame, sub[cast(pd.Series, sub["Code"]).isin(["2327", "2492"])].copy())
    duo_meta = pd.DataFrame({"Code": ["2327", "2492"], "industry_category": ["PROBE", "PROBE"]})
    duo_out = compute(duo, duo_meta)
    check(
        "a cohort with only one peer produces no cohort value",
        cast(bool, cast(pd.Series, duo_out["cohort_ret_20"]).isna().all()) and cast(bool, cast(pd.Series, duo_out["cohort_breadth"]).isna().all()),
        f"{int(duo_out['cohort_ret_20'].notna().sum())} rows populated",
    )

    # An ineligible peer must not enter the cohort. Four members, one starved of liquidity:
    # the remaining two peers still clear the >= 2 guard, so a NaN here would mean the guard
    # fired rather than that exclusion worked, and the check would prove nothing.
    quad = ["2327", "2492", "3026", "2344"]
    thin_code = "2344"
    starved = cast(pd.DataFrame, sub[cast(pd.Series, sub["Code"]).isin(quad)].copy())
    starved.loc[cast(pd.Series, starved["Code"]) == thin_code, "Volume"] = 1.0
    quad_meta = pd.DataFrame({"Code": quad, "industry_category": ["PROBE"] * 4})
    thin_out = compute(starved, quad_meta)
    thin_latest = thin_out[thin_out["Date"] == thin_out["Date"].max()].set_index("Code")

    detail = ""
    ok_thin = False
    if len(thin_latest) != 4:
        detail = f"expected 4 rows, got {len(thin_latest)}"
    elif bool(thin_latest.loc[thin_code, "eligible"]):
        detail = "the starved symbol stayed eligible, so the check proves nothing"
    else:
        peers = [c for c in quad if c not in (quad[0], thin_code)]
        expected = sum(float(thin_latest.loc[c, "ret_20"]) for c in peers) / len(peers)
        actual = float(thin_latest.loc[quad[0], "cohort_ret_20"])
        ok_thin = abs(actual - expected) < 1e-9
        detail = f"got {actual:.6f}, expected {expected:.6f} from the two eligible peers"
    check("an ineligible peer is excluded from the cohort", ok_thin, detail)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {failures}")
        return 1
    print("all checks passed -- no feature reads the future")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
