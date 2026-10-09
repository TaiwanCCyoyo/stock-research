"""Cross-sectional ranking features, computed once and vectorised.

Why offline rather than inside the strategy. The archetype strategies recompute their
indicators from a growing Python list on every bar, which is O(lookback) per symbol-bar.
That is fine for twenty symbols and not fine for the 1,345 in `rotation_pit`. Computing the
features once in pandas and having the strategy look them up turns the per-bar cost into a
dict access and a sort of a few hundred floats.

It also makes the score a first-class artifact rather than a backtest internal. The owner
asked for "a number that says what to rotate into", so the same table that drives the
backtest is what a dashboard would display.

**Timing convention.** The existing strategies decide on the current bar's close and trade
at that same close (`should_enter(prior, bar)` reads `bar["close"]`, then
`broker.buy(code, bar["close"], ...)`). Features here follow that convention: the value on
date `t` may use bars up to and including `t`, and never anything after. `verify_features.py`
enforces the second half by truncation, which is the only check that actually catches a
lookahead -- a rolling window that forgot to shift produces a perfectly plausible table.

**Features.** Deliberately few and individually interpretable, because the first ranking
study asks whether ranking beats a random draw at all. A large feature set would confound
that question with a fitting question.

  ret_20, ret_60   trailing return -- relative strength, the classic rotation signal
  ext_20           close against the prior 20-day closing high; positive means breaking out
  above_ma60       close against MA60 -- the regime filter every archetype uses
  vol_ratio        volume against its own 20-day average -- participation
  contraction      ATR(14)/close against its own 60-day average; below 1 is a tightening
                   base, which is the mechanism S4 (VCP) exists to capture
  cohort_ret_20    mean ret_20 of the symbol's official industry category, excluding the
                   symbol itself
  cohort_breadth   share of the rest of that category with a positive 20-day return -- the
                   closer analogue of the ignition effect, which was about how many members
                   moved rather than how far the average one moved

The two cohort columns use the official `industry_category` while knowing it is the wrong grouping:
it is too broad for a theme and cannot express one that spans categories, as recorded in
`docs/en/research-objective.md`. It is included because cohort ignition measured +1.4pp of
excess over 20 days even through that blunt grouping, so it is a real signal being read
through a poor lens. Deriving cohorts from returns is a separate study; keeping the official
version here means the two can be compared rather than conflated.

Self-exclusion matters: without it a symbol's own move leaks into its cohort score and the
feature partly restates `ret_20`.

Run from the repository root:
    uv run python tasks/20260823-rotation-universe/features.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import cast

import pandas as pd

TASK_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TASK_ROOT.parents[1]
sys.path.insert(0, str(TASK_ROOT))

from eligibility import LIQ_FLOOR, MIN_HISTORY, add_eligibility_columns  # noqa: E402

PRICE = REPO_ROOT / "shioaji_stock_prices/data/price_daily.parquet"
META = REPO_ROOT / "shioaji_stock_prices/data/symbol_meta.sqlite"
OUT = TASK_ROOT / "features.parquet"

FEATURE_COLUMNS = [
    "ret_20",
    "ret_60",
    "ext_20",
    "above_ma60",
    "vol_ratio",
    "contraction",
    "cohort_ret_20",
    "cohort_breadth",
]

RANK_PREFIX = "r_"
RANK_COLUMNS = [RANK_PREFIX + c for c in FEATURE_COLUMNS]


def load_prices() -> pd.DataFrame:
    px = pd.read_parquet(PRICE, columns=["Code", "Date", "Open", "High", "Low", "Close", "Volume"])
    px["Code"] = px["Code"].astype(str)
    return px.sort_values(["Code", "Date"]).reset_index(drop=True)


def load_categories() -> pd.DataFrame:
    with sqlite3.connect(META) as con:
        meta = pd.read_sql("select code as Code, industry_category from symbol_meta", con)
    meta["Code"] = meta["Code"].astype(str)
    return meta


def compute(px: pd.DataFrame, meta: pd.DataFrame | None = None) -> pd.DataFrame:
    """Feature table keyed (Code, Date). Every column reads only bars up to its own date."""
    out = px.copy()
    grouped = out.groupby("Code", sort=False)

    close = out["Close"]
    out["ret_20"] = grouped["Close"].transform(lambda s: s / s.shift(20) - 1.0)
    out["ret_60"] = grouped["Close"].transform(lambda s: s / s.shift(60) - 1.0)

    # Prior 20-day closing high, excluding today, so a new high reads positive.
    prior_high = grouped["Close"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).max())
    out["ext_20"] = close / prior_high - 1.0

    ma60 = grouped["Close"].transform(lambda s: s.rolling(60, min_periods=60).mean())
    out["above_ma60"] = close / ma60 - 1.0

    vol_avg = grouped["Volume"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
    out["vol_ratio"] = out["Volume"] / vol_avg

    prev_close = grouped["Close"].shift(1)
    true_range = pd.concat(
        [
            out["High"] - out["Low"],
            (out["High"] - prev_close).abs(),
            (out["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["_tr"] = true_range
    atr = out.groupby("Code", sort=False)["_tr"].transform(lambda s: s.rolling(14, min_periods=14).mean())
    atr_pct = atr / close
    out["_atr_pct"] = atr_pct
    atr_baseline = out.groupby("Code", sort=False)["_atr_pct"].transform(lambda s: s.rolling(60, min_periods=60).mean())
    out["contraction"] = atr_pct / atr_baseline

    if meta is None:
        meta = load_categories()
    out = out.merge(meta, on="Code", how="left")

    # Eligibility is needed before the cohort columns, not after: a cohort signal built from
    # names the strategy could never hold is not a tradeable signal. See `_cohort`.
    elig = add_eligibility_columns(px)
    out["eligible"] = ((elig["prior_bars"] >= MIN_HISTORY) & (elig["liquidity"] >= LIQ_FLOOR)).to_numpy()

    out["cohort_ret_20"], out["cohort_breadth"] = _cohort(out)

    # Cross-sectional percentile rank, computed among the symbols eligible on that date and
    # nowhere else. Two reasons. A weighted sum of raw features is not interpretable when
    # `vol_ratio` runs to 20 and `above_ma60` sits near 0.05, so a weight would encode scale
    # rather than importance. And the percentile is itself the number the owner asked to see
    # -- "this name is in the top 3% on relative strength today" is readable in a way that
    # "ret_20 = 0.31" is not.
    ranked = out[out["eligible"]]
    for column in FEATURE_COLUMNS:
        rank = ranked.groupby("Date", sort=False)[column].rank(pct=True, method="average")
        out[RANK_PREFIX + column] = rank

    out = out.drop(columns=["_tr", "_atr_pct"])
    return cast(pd.DataFrame, out[["Code", "Date", "industry_category", "eligible", *FEATURE_COLUMNS, *RANK_COLUMNS]])


def _cohort(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Self-excluded cohort mean return and breadth, per date and industry category.

    Mean rather than median because self-exclusion has a closed form for a mean -- the
    group sum less the row's own value, over one fewer member -- and none for a median, and
    the direct per-row form is a Python loop over millions of rows.

    Breadth is the share of the rest of the cohort with a positive 20-day return. It is the
    closer analogue of the ignition effect measured on 2026-08-23, which was defined on how
    many members moved rather than on how far the average member moved, and it is far less
    sensitive to one member running away.

    Self-exclusion is the point of both. Without it a symbol's own move enters its cohort
    score, and the feature partly restates `ret_20` while looking independent of it.

    Peers are restricted to symbols eligible that day. Counting every listed name in the
    category would measure the sector, which is a defensible thing to measure but not the
    thing a rotation score can act on.
    """
    keys = ["Date", "industry_category"]
    own = df["ret_20"]
    # Only eligible peers count. Without this the cohort is computed over every listed name
    # in the category, so the signal is partly made of illiquid symbols the strategy could
    # never hold -- and nothing downstream would reveal it, because the number stays
    # plausible. A row's own eligibility does not matter here: an ineligible symbol still
    # gets a cohort reading, it just never reaches the ranking.
    valid = own.notna() & df["eligible"]
    positive = (own > 0) & valid

    grouped = df.assign(_v=own.where(valid), _n=valid.astype(float), _p=positive.astype(float)).groupby(keys, sort=False, dropna=True)
    total = grouped["_v"].transform("sum")
    count = grouped["_n"].transform("sum")
    pos = grouped["_p"].transform("sum")

    others = count - valid.astype(float)
    mean = (total - own.fillna(0.0)) / others.where(others > 0)
    breadth = (pos - positive.astype(float)) / others.where(others > 0)
    # At least two peers, not one. A single peer is not a cohort signal -- the feature
    # would just be that one symbol's return wearing a different name, and on a date when
    # it happens to gap the score would read as breadth.
    thin = others < 2
    return mean.mask(thin), breadth.mask(thin)


def main() -> int:
    px = load_prices()
    features = compute(px)
    features.to_parquet(OUT, index=False)
    covered = cast(pd.Series, cast(pd.DataFrame, features[FEATURE_COLUMNS]).notna().all(axis=1)).sum()
    usable = cast(pd.Series, cast(pd.Series, features["eligible"]) & cast(pd.DataFrame, features[FEATURE_COLUMNS]).notna().all(axis=1)).sum()
    print(f"rows           : {len(features):,}")
    print(f"fully populated: {covered:,}  ({covered / len(features):.1%})")
    print(f"eligible+full  : {usable:,}  ({usable / len(features):.1%})")
    print(f"symbols        : {features['Code'].nunique():,}")
    print(f"dates          : {features['Date'].nunique():,}")
    per_date = features[features["eligible"]].groupby("Date").size()
    print(f"eligible/date  : median {per_date.median():.0f}, 10th {per_date.quantile(0.1):.0f}, 90th {per_date.quantile(0.9):.0f}")
    print(f"wrote {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
