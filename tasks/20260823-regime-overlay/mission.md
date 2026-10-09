# Mission -- can this strategy tell a bear market, and what should it do about one?

## 0. The question, and why it is this one

`20260823-turnover-mechanism` left one configuration standing: `momentum_k10__hold20`,
+97.50% on the holdout at 9.28 round trips per slot per year (4.6% of capital a year in
cost). It also measured, per entry year, the thing this study exists to fix:

|                        |  2019 |  2020 |  2021 |  **2022** |  2023 |
| ---------------------- | ----: | ----: | ----: | --------: | ----: |
| 0050 (adjusted)        |  +36% |  +30% |  +20% |  **-22%** |  +27% |
| `momentum_k10__hold20` | +26.9 | +88.8 | +80.4 | **-32.2** | +51.1 |

A long-only, fully-invested strategy that buys relative strength has no mechanism for
stepping aside. Its ranking always produces "the ten strongest names", including when all
ten are falling. The owner's requirement is that the final strategy not be useful only in a
bull market, and named two responses to consider: raise the cash level, or park capital in 0050.

## 1. What this study can conclude, and what it cannot -- the data ceiling

**`price_daily.parquet` starts 2018-12-07.** Verified directly: 3,455,546 rows, first bar
2018-12-07, 1,778-1,986 distinct codes a year throughout. The 2019-01-02 window start in
`build_rotation_universe.py` is therefore a data limit, not a choice.

That means the backtestable span contains **exactly one full bear year, 2022, and it is in
the training window.** The holdout (2024-01-01..2026-08-14) is bull-dominated. A threshold
chosen because it wins on 2022 is a threshold fitted to a single episode, and no amount of
holdout arithmetic on a bull window can tell you otherwise.

This is the central weakness of the study and it is stated first rather than buried.

**Amended 2026-08-23, from the detector profile and the anchor, before any arm was scored.**
Two parts of the paragraph above turned out to be wrong in the study's favour, and both are
left standing rather than edited away so the reasoning stays legible.

- The holdout is **not** bull-dominated. Enumerating drawdowns by rule 5's own definition
  finds nine episodes on 0050 since 2013, and three of them are inside the holdout:
  -21.7% from 2024-07-11, -28.5% from 2025-01-07, and -15.9% from 2026-06-22 which has not
  recovered. So the holdout does test a bear response.
- 2022 is not this strategy's worst episode. The baseline's own equity curve draws down
  **-34.3% in train and -53.3% in the holdout** -- 2025's crash hit a concentrated momentum
  book far harder than 2022's long grind did. Rule 1 is nonetheless left exactly as
  pre-registered, on the training window, because moving a gate after seeing the baseline is
  how a study talks itself into a result. The holdout drawdown is carried beside it in every
  row and the report weighs it.

**The mitigation, pre-registered here.** The _detector_ -- the part that says "this is a
bear" -- does not need the strategy's data. It needs an index proxy and a breadth series, and
`shioaji_stock_prices/data/official_daily.sqlite` holds TWSE daily bars from **2013-08-01**:
0050 has 3,180 bars from 2013-08-01 to 2026-08-20 with no gaps, and TWSE carries 803 to 1,379
distinct codes a year across the span. So the detector is profiled over thirteen years and
several drawdown episodes, while the strategy P&L is measured over the seven years the price
cache allows.

What the extension does **not** give, and so what it cannot be used for:

- **TPEx (OTC) only starts in 2020** in that database, so the pre-2019 pool is TWSE-only
  and is not the `rotation_pit` universe.
- **`corporate_actions.sqlite` only starts in 2018.** Before that there is no
  `price_factor` and no dividend estimate, so a total-return series cannot be built.

Both of those rule out running the strategy before 2019. Neither rules out measuring when a
detector fires, which is what the extension is for. Detector signals are therefore defined on
**split-adjusted, dividend-unadjusted** prices -- the chart a person actually looks at --
which is also the only definition available consistently across both eras.

## 2. The comparator: paired arms on the engine's equity curve, not the matched null

The previous two studies compared each arm against a deployment-matched random draw
(`null_draw.py`). **That comparator is wrong for this question and would cancel the effect
being tested.** The null redraws each position at the same entry date and the same span. A
regime overlay's entire mechanism is changing _whether you are invested at all_, so the null
moves with the arm, and excess-over-null answers "did I pick good names on the days I chose to
trade" -- which is precisely not the question asked. A book holding 0050 in ten slots has no
representation in that scheme at all, since `draw_books()` rejection-samples for concurrency
exclusivity across distinct symbols.

`book.py` is wrong here for a second, independent reason. Its statistic is
`(1/top_k) * sum(net_return)`, one weight per position. But `broker.buy` accumulates by code,
so "park the freed capital in 0050" is naturally **one** position carrying `top_k` slots'
worth of capital. Counted at 1/`top_k`, that leg's contribution is understated by 10x, and the
result is a table that looks entirely plausible. This is the same shape of failure as the
`date_position_asof` sentinel bug in `20260823-selection-vs-random`.

So the primary statistic for this study is **the engine's own daily equity curve**, which
`backtest_cli.py` already writes into each `summary.json` as `equity_curve`. It is the only
thing here that models idle cash correctly, it weights a concentrated leg by what it actually
holds, and it yields drawdown -- which is the quantity the owner's request is really about.
The engine's accounting differs from `book.py`'s (dividend cash sits idle rather than being
reinvested), but that difference is constant across the paired arms, which is what matters.

The matched null is kept only as a **side check** on the stock legs, to confirm the overlay
did not wreck selection on the days it stayed invested. It decides nothing.

## 3. The detector

All three signals are precomputed offline into one table, point-in-time: the value on date
`t` may use bars up to and including `t` and never anything after. `verify_detector.py`
enforces that by truncation, which is the only check that catches a lookahead, since a
rolling window that forgot to shift produces a perfectly plausible series.

**D1 -- index trend.** 0050 close against its own MA(N), bear when below.
`N in {100, 150, 200, 250}`.

**D2 -- MA60 breadth.** The share of the eligible pool whose `above_ma60` feature is
positive, bear when below `theta in {0.35, 0.45, 0.55}`. Computed from
`tasks/20260823-rotation-universe/features.parquet`, so it inherits `verify_features.py`'s
truncation guarantee rather than opening a new lookahead surface. That table is built from the
price cache, so **D2 exists only from 2019 and has no out-of-window validation at all** -- it
is the one detector here whose evidence is confined to the single episode this study is trying
not to fit. Recorded now rather than discovered later.

**D3 -- advances against declines.** The 20-day mean of the daily share of TWSE names that
closed up, bear when below `theta in {0.42, 0.46, 0.50}`. This is the owner's own suggestion
(watching the daily advance/decline count), and it is the only one of the three that is robust
before 2018: an ex-rights day distorts one name on one day out of a thousand, whereas an MA60
breadth measure computed without corporate-action data would read a stock dividend as a name
falling out of trend for a quarter.

**Order of operations, and it is not negotiable after this file is committed.** The detector
profile over 2013-08-01..2026-08-20 is computed and written **before any strategy cell runs**.
Any parameterisation that fails to flag the pre-2019 episodes is reported as _2022-specific_,
and its strategy result is read as fitted rather than as evidence. The profile does not
hard-filter the grid -- pre-filtering on one statistic and then testing on another is its own
kind of fitting -- it is reported alongside, so a reader can see which detectors earned their
result.

## 4. The responses

Every arm differs from the baseline in exactly one respect. The baseline is
`momentum_k10__hold20`: `momentum` weights, `top_k = 10`, `exit_rank = 30`,
`min_hold_bars = 20`.

**R0 -- baseline.** The overlay disabled. `anchor_arms_v3.py` must reproduce
`momentum_k10__hold20` trade for trade, not metric for metric.

**R1 -- all cash on a bear.** On a flagged day the book is liquidated and the proceeds sit in
cash; on the first unflagged day it refills from the ranking as usual. This is the extreme of
"raise the cash level", chosen over a partial reduction because with one episode a partial
response is even harder to read than a total one.

**R2 -- all 0050 on a bear.** Same trigger, but the freed capital buys 0050 instead of
sitting idle.

**R3 -- per-name entry filter, no regime call at all.** Buy only names whose own `above_ma60`
is positive. In a broad decline fewer names qualify, the book cannot fill, and the cash level
rises _mechanically_ -- without any market-wide switch to whipsaw. It is one parameter, the
feature already exists in `features.parquet` and carries weight 0 in `momentum` so it is
currently unused, and unlike a regime switch it is exercised on every drawdown rather than on
one. Thresholds `{0.0, -0.03}`, widened to `{+0.05, 0.0, -0.03, -0.06, -0.10}` -- see the
dated amendment under rule 4.

**R4 -- per-name exit filter.** Sell a held name when its own `above_ma60` goes negative. The
natural pair to R3, and the one that costs turnover; included so the entry and exit sides can
be told apart rather than bundled.

Two rules that apply to R1 and R2 and are recorded because they are choices, not defaults:

- A regime exit **overrides `min_hold_bars`**, exactly as loss of eligibility does. A
  minimum hold that survived a bear signal would make the arm untradeable rather than
  patient.
- **0050 is excluded from the ranking pool in every arm, including R0.** It is eligible on
  1,743 days and could in principle be selected as a stock, which would make the defensive
  leg and the ranked leg the same position. `verify_defence_symbol.py` asserts that 0050
  never appears in the baseline's trades, so the exclusion is a no-op against the anchor; if
  that assertion ever fails, the exclusion becomes a stated difference from the baseline
  rather than a silent one.

## 5. Acceptance

Turnover is no longer the dependent variable; drawdown is. The rules are therefore not the
previous study's, and they are fixed here before any cell runs.

**Rule 1 -- it must actually help in the bear.** The training window's maximum drawdown, from
the engine equity curve, must improve by at least **5 percentage points** against the
baseline's own measured drawdown.

**Rule 2 -- it must not pay for that with the bull.** Holdout total return must stay at or
above **two thirds** of the baseline's holdout return, and train total return likewise. The
holdout is the binding one, because a bull-dominated window is exactly where a regime switch's
false positives are paid for. Two thirds is the same give-back the owner set for the turnover
study; keeping it identical means the two studies' verdicts remain comparable.

**Rule 3 -- the owner's cost ceiling still binds.** The arm's **measured** turnover, at most
**12 round trips per slot per year** (6.0% of capital a year at 0.5% a trip), with the
defensive legs counted as positions. A whole-book flip is about one round trip per slot, and
`hold20` already spends 9.28 of the 12, so an overlay that flips often will fail this on its
own arithmetic. It is measured rather than budgeted.

**Rule 4 -- a plateau, not a winner.** A response passes only if it satisfies rules 1 to 3
across **at least three contiguous values** of its detector's parameter. One winning cell
surrounded by failures is recorded as a **negative**, because with a single bear episode that
is what a tuned threshold looks like.

**Amended 2026-08-23, while the overlay cells were still running and before any filter cell
had been read.** Section 4 listed two entry thresholds and two exit cells, and a family of two
cannot supply three contiguous passes however well the arm performs -- so as written, rule 4
was a test those two arms were structurally unable to sit. The rule is unchanged; the grid is
widened to make it answerable. Entry thresholds become `{+0.05, 0.0, -0.03, -0.06, -0.10}`.
The exit side becomes three `hard` thresholds `{0.0, -0.05, -0.10}` plus the single `soft`
cell, which stays outside the family because `soft` and `hard` are two mechanisms rather than
two values of one parameter, and is reported as unable to satisfy rule 4 rather than excused
from it. The timing matters and is the reason this note records it: the change was made from
the shape of the grid, not from any result it produced.

**Rule 5 -- episodes are defined by drawdown, not by calendar year.** From the 0050
split-adjusted close: an episode runs from a running-peak day through the recovery of that
peak, whenever the trough between them is at least 10% below it. All episodes in
2013-08-01..2026-08-20 are enumerated by that definition and reported; none are chosen by
hand. "2022 as a sub-window" would not launder the fact that 2022's numbers are already
known.

**Rule 6 -- a clean negative is a result** and gets the same space in the report as a
positive. It is a genuinely likely outcome here: one episode, several thresholds, and a bull
holdout is a configuration in which the honest answer may well be "not measurable".

## 6. Gates, each of which must fail when the thing it guards is broken

- `anchor_arms_v3.py` -- R0 reproduces `momentum_k10__hold20` trade for trade.
- `verify_detector.py` -- truncation (no lookahead); the 0050 series has no single-day move
  past 25% once the 2025-06-18 4-for-1 split (`price_factor` 0.249987) is applied, and no
  detector state flips across that date; official and cached closes agree on the overlap.
- `verify_defence_symbol.py` -- 0050 absent from the baseline's trades; the defensive leg is
  sized from available cash and is sold before the book refills.
  **Amended 2026-08-23, after the anchor ran and before any cell was scored: "sized from
  available cash" was wrong and is replaced by "sized from the market value of the book it
  replaces".** The reason is a property of the baseline that this file did not know about
  when it was written. `equal_notional_quantity` sizes every slot at a fixed fraction of
  _initial_ capital, so as the account compounds the deployed notional stays at 10,000,000
  while the rest accumulates as cash -- at the end of the training window the baseline holds
  30.7M of equity against 19.5M of cash, only 36% deployed. A defensive leg sized from cash
  would therefore push all of that idle money into 0050 on precisely the days the arm is
  meant to be stepping out of the market, roughly tripling exposure. R2 would then differ
  from the baseline in two respects at once and would lose on the one it did not intend to
  change. Sizing the leg at the book's own market value keeps it one variable: same money,
  different asset. `verify_overlay.py` now proves the distinction on a scenario where half
  the account is idle, because the original check ran fully invested, where cash and book
  value coincide and both sizings give the same answer -- it passed against the exact defect
  it was written to catch.
- `verify_overlay.py` -- on a synthetic regime series, the bear state overrides
  `min_hold_bars`, does not override eligibility, and re-entry happens on the first
  unflagged bar and not before.

## 7. Reproduction

```bash
uv run python tasks/20260823-regime-overlay/detector.py
uv run python tasks/20260823-regime-overlay/verify_detector.py
uv run python tasks/20260823-regime-overlay/anchor_arms_v3.py
uv run python tasks/20260823-regime-overlay/verify_overlay.py
uv run python tasks/20260823-regime-overlay/verify_defence_symbol.py
uv run python tasks/20260823-regime-overlay/run_grid.py --workers 6
uv run python tasks/20260823-regime-overlay/analyze.py
```
