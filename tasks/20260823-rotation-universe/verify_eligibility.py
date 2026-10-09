"""Gate: the two forms of the eligibility rule must agree, symbol by symbol and bar by bar.

`eligibility.py` holds the rule twice -- a vectorised `eligible_matrix` the universe builder
uses, and a scalar `is_eligible` the ranking strategy will call while it walks bars. Two
implementations of one rule is exactly the failure the module claims to prevent, and a
divergence would not crash: the builder would admit a symbol the strategy silently skips, or
the reverse, and the study would rank a different pool than the one it documented.

Also checks the property that makes the rule point-in-time at all: eligibility on date `t`
must not change when every bar from `t` onward is deleted. If it does, the rule is reading
the future.

Run from the repository root:
    uv run python tasks/20260823-rotation-universe/verify_eligibility.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Protocol, cast

import pandas as pd

TASK_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TASK_ROOT.parents[1]
sys.path.insert(0, str(TASK_ROOT))
sys.path.insert(0, str(REPO_ROOT))

from eligibility import LIQ_WINDOW, MIN_HISTORY, add_eligibility_columns, eligible_matrix, is_eligible  # noqa: E402

from research_core.producer_data import producer_data_root  # noqa: E402

PRICE = producer_data_root() / "price_daily.parquet"
WINDOW_START = "2019-01-02"
WINDOW_END = "2026-08-14"
SAMPLE_SYMBOLS = 40
SEED = 20260823


class PriceRow(Protocol):
    Date: pd.Timestamp


class EligibilityRow(PriceRow, Protocol):
    Code: str
    eligible: bool


def main() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(label)

    px = pd.read_parquet(PRICE, columns=["Code", "Date", "Close", "Volume"])
    px["Code"] = px["Code"].astype(str)
    px = px.sort_values(["Code", "Date"])

    codes = sorted(px["Code"].unique())
    sample = pd.Series(codes).sample(SAMPLE_SYMBOLS, random_state=SEED).tolist()
    # Force the named theme leaders in, so the check covers the names the pool exists for.
    sample = sorted(set(sample) | {"6223", "6510", "6515", "3131", "2344", "8299", "2327", "3491"})

    sub = cast(pd.DataFrame, px[px["Code"].isin(sample)].copy())
    vector = eligible_matrix(sub, WINDOW_START, WINDOW_END)
    vector_map = {(row.Code, row.Date): row.eligible for raw in vector.itertuples() for row in [cast(EligibilityRow, raw)]}

    # -- 1: scalar form reproduces the vectorised form ---------------------
    mismatches = []
    compared = 0
    for code, grp in sub.groupby("Code", sort=False):
        grp = grp.reset_index(drop=True)
        turnovers = (grp["Close"] * grp["Volume"]).tolist()
        for i, raw in enumerate(grp.itertuples()):
            row = cast(PriceRow, raw)
            key = (cast(str, code), row.Date)
            if key not in vector_map:
                continue
            compared += 1
            scalar = is_eligible(prior_bars=i, trailing_turnovers=turnovers[:i])
            if scalar != bool(vector_map[key]):
                mismatches.append((code, str(row.Date)[:10], scalar, bool(vector_map[key])))
    check(
        f"scalar is_eligible matches eligible_matrix over {compared:,} symbol-days",
        not mismatches,
        str(mismatches[:5]),
    )

    # -- 2: the rule reads no future bar -----------------------------------
    # Truncate each symbol at a cut date and confirm eligibility up to that date is unchanged.
    cut = "2024-06-28"
    truncated = cast(pd.DataFrame, sub[sub["Date"] <= cut])
    full_before_cut = vector[vector["Date"] <= cut]
    trunc_matrix = eligible_matrix(truncated, WINDOW_START, cut)
    merged = full_before_cut.merge(trunc_matrix, on=["Code", "Date"], suffixes=("_full", "_trunc"))
    drift = merged[merged["eligible_full"] != merged["eligible_trunc"]]
    check(
        f"eligibility up to {cut} is unchanged when later bars are removed ({len(merged):,} rows)",
        drift.empty,
        f"{len(drift)} rows differ",
    )

    # -- 3: the shift is real, not assumed ---------------------------------
    # `liquidity` on a row must equal the trailing median that excludes that row's own bar.
    cols = add_eligibility_columns(sub)
    probe = cols[cols["Code"] == "2327"].reset_index(drop=True)
    turn = (probe["Close"] * probe["Volume"]).tolist()
    idx = 400
    expected = pd.Series(turn[idx - LIQ_WINDOW : idx]).median()
    check(
        "liquidity at a probe row excludes that row's own turnover",
        abs(float(probe.loc[idx, "liquidity"]) - float(expected)) < 1e-6,
        f"got {probe.loc[idx, 'liquidity']}, expected {expected}",
    )

    # -- 4: history threshold behaves at the boundary ----------------------
    boundary = [
        is_eligible(MIN_HISTORY - 1, [10 * LIQ_FLOOR_PROBE] * LIQ_WINDOW),
        is_eligible(MIN_HISTORY, [10 * LIQ_FLOOR_PROBE] * LIQ_WINDOW),
    ]
    check("history threshold rejects at MIN_HISTORY-1 and accepts at MIN_HISTORY", boundary == [False, True], str(boundary))

    # -- 5: a short liquidity window is not eligible -----------------------
    short = is_eligible(MIN_HISTORY + 500, [10 * LIQ_FLOOR_PROBE] * (LIQ_WINDOW - 1))
    check("fewer than LIQ_WINDOW trailing bars is not eligible", short is False, str(short))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {failures}")
        return 1
    print("all checks passed -- one rule, two forms, no future reads")
    return 0


LIQ_FLOOR_PROBE = 100_000

if __name__ == "__main__":
    raise SystemExit(main())
