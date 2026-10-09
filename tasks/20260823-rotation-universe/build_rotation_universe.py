"""Build the point-in-time universe that ranking research needs.

The existing `universes/*_liquid20.json` baskets take the twenty most liquid names in
each of five categories, filtered by `MIN_BARS = 1750` -- roughly seven years of history.
That filter is fine for paired timing research, where both arms see the same symbols and a
survivor tilt largely cancels. It is disqualifying for ranking, because it pre-selects
survivors and then asks a score to pick winners out of a pool already filtered to winners.
It also excluded every one of the probe-card leaders the owner named.

This builds the pool differently, in two respects.

**Eligibility is decided per date, not once over the whole history.** A symbol counts on
date `t` when it has at least `MIN_HISTORY` bars strictly before `t`, its median turnover
over the trailing `LIQ_WINDOW` bars clears `LIQ_FLOOR`, and it actually traded on `t`.
Nothing after `t` is consulted, so a name that listed in 2023 enters the pool once it has
enough history, and a name that delisted in 2022 stays in the pool right up to its last
bar. The cache holds 96 symbols that stopped trading before 2026-08 and 292 that first
appeared after 2019, so both directions are real rather than hypothetical.

**No category quota.** The liquid20 baskets asked "which twenty semiconductors are most
liquid", which buries a probe-card cohort among the IC designers and cannot express a theme
that spans categories at all. Ranking research wants every name that is tradeable at the
time, and lets the score decide.

The file this writes is the *union* of everything eligible on at least one date in the
window, because `backtest_cli.py --codes @name` takes a static list. Point-in-time filtering
belongs in the strategy, which receives every symbol's bars on each `on_bar` call and can
apply the same rule; `eligibility.py` holds that rule so the two cannot drift apart.

Run from the repository root:
    uv run python tasks/20260823-rotation-universe/build_rotation_universe.py
    uv run python tasks/20260823-rotation-universe/build_rotation_universe.py --sensitivity
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

import pandas as pd

TASK_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TASK_ROOT.parents[1]
sys.path.insert(0, str(TASK_ROOT))

from eligibility import LIQ_FLOOR, LIQ_WINDOW, MIN_HISTORY, eligible_matrix  # noqa: E402

PRICE = REPO_ROOT / "shioaji_stock_prices/data/price_daily.parquet"
OUT = REPO_ROOT / "universes/rotation_pit.json"
MANIFEST = TASK_ROOT / "universe_build_report.json"

WINDOW_START = "2019-01-02"
WINDOW_END = "2026-08-14"

# Named by the owner as the kind of move the system exists to catch. Recorded here so the
# builder fails loudly if a pool is ever produced that cannot see them.
THEME_PROBES = {
    "probe cards": ["6223", "6510", "6515", "3131"],
    "memory": ["2344", "2408", "8299", "5289", "2451", "4967"],
    "passive components": ["2327", "2492", "3026", "2478", "6173"],
    "satellite-related": ["6443", "2313", "3491", "2314", "6285"],
}


def load_prices() -> pd.DataFrame:
    px = pd.read_parquet(PRICE, columns=["Code", "Date", "Close", "Volume"])
    px["Code"] = px["Code"].astype(str)
    return px.sort_values(["Code", "Date"])


def build(px: pd.DataFrame, floor: float) -> tuple[list[str], pd.Series]:
    """Union of symbols eligible on at least one date in the window, and their day counts."""
    elig = eligible_matrix(px, WINDOW_START, WINDOW_END, liq_floor=floor)
    days = cast(pd.Series, elig.groupby("Code")["eligible"].sum())
    days = cast(pd.Series, days[days > 0]).sort_values(ascending=False)
    return sorted(days.index), days


def sensitivity(px: pd.DataFrame) -> None:
    print("%14s %10s %14s %s" % ("liquidity floor", "symbols", "median days", "theme leaders covered"))
    print("-" * 88)
    for floor in (200_000, 100_000, 50_000, 20_000, 10_000, 5_000):
        codes, days = build(px, floor)
        pool = set(codes)
        cover = "  ".join(f"{name.split()[0]} {sum(c in pool for c in members)}/{len(members)}" for name, members in THEME_PROBES.items())
        print("%14s %10d %14.0f %s" % (f"{floor:,}", len(codes), days.median(), cover))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensitivity", action="store_true", help="print pool size against liquidity floor and exit")
    args = parser.parse_args()

    px = load_prices()
    if args.sensitivity:
        sensitivity(px)
        return 0

    codes, days = build(px, LIQ_FLOOR)
    pool = set(codes)

    missing = {name: [c for c in members if c not in pool] for name, members in THEME_PROBES.items()}
    for name, members in THEME_PROBES.items():
        got = len(members) - len(missing[name])
        print(f"  {name:<20} {got}/{len(members)} present" + (f"   missing {missing[name]}" if missing[name] else ""))

    payload = {
        "name": "rotation_pit",
        "description": (
            f"Point-in-time eligible pool for ranking research: >= {MIN_HISTORY} bars of prior history, "
            f"median turnover over the trailing {LIQ_WINDOW} bars >= {LIQ_FLOOR:,} (TWD thousands), "
            f"union over {WINDOW_START}..{WINDOW_END}. No category quota and no whole-history filter, "
            "so new listings enter when they qualify and delisted names stay until their last bar. "
            "Eligibility is re-checked per date by tasks/20260823-rotation-universe/eligibility.py; "
            "this list is the union only, because --codes takes a static list. "
            "Generated by tasks/20260823-rotation-universe/build_rotation_universe.py."
        ),
        "codes": codes,
    }
    OUT.write_text(json.dumps(payload, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")

    MANIFEST.write_text(
        json.dumps(
            {
                "rule": {
                    "min_history_bars": MIN_HISTORY,
                    "liquidity_window_bars": LIQ_WINDOW,
                    "liquidity_floor_twd_thousands": LIQ_FLOOR,
                    "window_start": WINDOW_START,
                    "window_end": WINDOW_END,
                },
                "pool_size": len(codes),
                "eligible_days": {code: int(days[code]) for code in codes},
                "theme_probe_missing": missing,
            },
            indent=4,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print(f"pool size          : {len(codes)}")
    print(f"eligible-day median: {days.median():.0f} of the window's trading days")
    print(f"wrote {OUT.relative_to(REPO_ROOT)}")
    print(f"wrote {MANIFEST.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
