# Mission -- Does ranking pick better than chance, at the same deployment and turnover?

## The question, and why it is the first one

Measured on 2026-08-23: the median holdout trading day offers 51 symbols satisfying a
20-day-high entry, against a five-position book, and 96% of days offer more candidates than
the book can hold. Among those candidates, forward 20-day return is -0.44% for a random pick,
+33.1% for the best five in hindsight and -16.1% for the worst five. The entry signal has no
median edge at portfolio level; its value is entirely in the right tail, and _which_
candidate is held decides whether the tail is reached.

Five studies have optimised the exit on a signal whose portfolio-level median outcome is
zero. This is the first study on the other axis, and it asks the smallest question that can
fail: **does a score pick better than chance?** Not "is this configuration profitable",
which mixes selection skill with market direction and with cost.

## The null, and why it is a distribution

The comparator is **not** basket buy-and-hold. That rule went 0-for-17 across three studies
because a partly-deployed long-only strategy cannot beat a fully-invested basket in a bull
window -- a property of the comparison, not of the strategies. It is retired as a gate here
and reported as context only (`docs/en/research-objective.md`).

The null is a **random draw matched on deployment and turnover**. For every position the
ranked arm actually took, draw a symbol uniformly from the pool eligible on that same entry
date and hold it over the same span. Repeat the whole book 1,000 times to get a distribution,
and report where the ranked arm falls in it.

Matching this way makes three things cancel exactly rather than approximately: the number of
positions, the days invested, and the number of round trips -- so transaction cost is
identical between arms and cannot explain a difference either way. What is left is the
choice of symbol, which is the thing being tested.

**The conditioning this accepts, stated up front.** Holding period is an outcome of the
ranking: a pick that keeps performing stays in the top-K longer. Matching spans therefore
conditions the null on something the ranked arm produced. The effect is muted because
hysteresis exits are triggered as much by other symbols rising as by the held one falling,
but it is real, and it is why rule 2 below adds an unconditioned check.

## Arms

One entry-and-exit mechanism throughout; only the score varies. That is the single-variable
discipline the earlier studies converged on.

| arm           | score                                                        |
| ------------- | ------------------------------------------------------------ |
| `momentum`    | trailing 20- and 60-day return                               |
| `breakout`    | extension above the prior 20-day high, plus volume expansion |
| `cohort`      | momentum, plus the self-excluded cohort return and breadth   |
| `contraction` | momentum, plus ATR contraction (the S4/VCP mechanism)        |
| `all`         | every feature at equal weight                                |

`all` is included precisely because it is the naive choice, and because the smoke run showed
equal weights produce a book that turns over roughly every three days. If a focused score
beats it, that is worth knowing before anyone tunes weights.

Position management is fixed across arms: hold the top `top_k`, sell only when a name falls
past `exit_rank`, no stop. A stop would add a second exit mechanism and make the result
unattributable -- the confound `20260820` introduced and `20260821` had to unpick.

## Grid

`top_k` in {5, 10} x `exit_rank` in {top_k, 3x top_k, 6x top_k} x 5 scores, over train and
holdout. `exit_rank = top_k` is rebalance-on-every-change, the high-turnover extreme;
widening the band buys lower turnover at the cost of responsiveness, which is the tradeoff
the objective names as a hard constraint.

Windows are the same as every prior study: train 2019-01-02..2023-12-31, holdout
2024-01-01..2026-08-14. Capital 10,000,000 TWD, `shared` mode -- top-K selection only exists
under a capital constraint, and `unconstrained` would degenerate into "hold everything above
a threshold". That forfeits the exact-pooling property the earlier studies leaned on, so
there is no basket dimension here to pool over: the pool is one universe.

## Pre-registered acceptance rules

Written before any cell was run.

1. **Primary**: the ranked arm's total return must exceed the **80th percentile** of its
   matched random-draw distribution, in the holdout, after cost. Below that, the score is
   not distinguishable from luck at this sample size and the arm is reported as a
   non-finding regardless of its absolute return.

2. **Unconditioned confirmation**: the same arm's top-K by score must also beat a random
   draw on **fixed-horizon 20-day forward return**, measured on every signal day without
   reference to when the strategy actually exited. This check does not condition on holding
   period, so agreement between rules 1 and 2 is what rules out the span-matching artifact.
   Disagreement is reported as unresolved, not resolved in the favourable direction.

3. **Turnover is a gate, not a statistic.** Every cell reports round trips per year and the
   cost drag they imply at 0.5% per round trip. An arm that wins on rule 1 while turning over
   more than the arm it beats has not won; the rule is **beats the null at equal or lower
   turnover**, and turnover equality is guaranteed within a cell by construction but not
   across cells.

4. **Direction must hold between train and holdout**, as in all four prior studies. An arm
   that clears the null out of sample and fails in sample is a non-finding.

5. **A clean negative is a result.** If no score beats its null, that is the answer to
   whether ranking is worth pursuing, and it gets the same space as a positive.

## Decisions pinned before the harness was written

Each of these is unfixable after the fact, or would otherwise be settled by whatever the
code happened to do first.

**The null draws without replacement within a concurrent book.** Two null positions held at
the same time must be different symbols, because the ranked arm cannot hold the same name
twice either. Sampling with replacement would let the null concentrate in a way the ranked
arm structurally cannot, which would flatter the ranked arm for a reason that has nothing to
do with selection.

**Cohort features count only eligible peers.** `cohort_ret_20` and `cohort_breadth`
originally aggregated every listed name in a category, so the signal was partly built from
symbols the strategy could never hold. Fixed on 2026-08-23 and pinned by a test. Measuring
the whole sector is a defensible thing to want, but it is not a thing a rotation score can
act on, and the number stays plausible either way -- which is exactly why it needed a test
rather than a reading.

**Ties in the score are broken by a fixed CRC of the symbol code.** Summing eight averaged
percentile ranks produces real ties, and a stable sort would resolve them by the feature
table's row order, which is code order -- handing the lowest ticker every tie for the life
of the study. The CRC is arbitrary, but it is a decision and it is reproducible.

**Turnover is measured as round trips per position slot per year**: completed sells divided
by `top_k`, divided by the window's length in years. Reported per cell with the cost it
implies at 0.5% per round trip. Rule 3 calls turnover a gate, so it has to be a number that
can fail a cell, not something read off a table afterwards.

**"Fails in sample" means below its own null's median.** Rule 4 says direction must hold
between train and holdout without saying where the line is; setting it in code first would
let the threshold be chosen after seeing the numbers. It is the 50th percentile: an arm that
clears the 80th percentile out of sample while sitting below the median of its in-sample
null has not held direction. Fixed 2026-08-23, before any grid cell was analysed.

**Rule 3's cross-cell half is the half that can fail something.** Within a cell the null
shares the arm's schedule exactly, so turnover is identical by construction and the gate is
automatically satisfied. What can fail is the comparison the rule actually names: a cell does
not get to be the finding if another cell clearing rule 1, at the same window and book size,
reached a higher return on lower turnover. Comparisons stay inside a `(window, top_k)` group so
that book size is held fixed alongside the window. Turnover is already measured per slot, so
comparing across book sizes would have been defensible too; it changes none of the verdicts.

**A drawn symbol that stops trading mid-span is realised at its last bar.** Added
2026-08-23, before any cell was run, because the pool deliberately includes delisted names
and whatever the code did first would otherwise have decided this. Truncation is what a
holder can actually do: there is no later price to sell into. Redrawing until a survivor
appears would bias the null toward names that survived, which is the exact bias the
point-in-time pool exists to avoid. The count of truncated positions is reported per cell so
the size of the effect is visible rather than assumed.

**Returns are measured on total-return adjusted prices, on both sides.** The engine models
cash dividends as account cash with a five-bar signal fill window, which is right for
deciding entries and wrong for measuring a held span -- a close-to-close return across an
ex-date silently loses the dividend. That would not be neutral here: a momentum score tilts
toward low-yield growth names while a uniform draw includes the high-yield financials, so
dropping dividends would penalise the null more than the arm. Numbers from `book.py` are
therefore a different accounting from a `summary.json`'s `return_rate`, which is reported
beside them as context and never differenced against them.

**Rule 2 is computed vectorised, not as a backtest.** The fixed-horizon check reuses the
dispersion measurement already written on 2026-08-23: rank every eligible symbol each day,
take the top K, and compare their forward 20-day return against a random draw from the same
day's eligible pool. Running it through the engine would take an hour to produce the same
answer.

The last 20 trading days of each window are **dropped, not filled**. A row there has no
forward return inside its own window, and carrying the last price forward would score those
days at zero for every arm alike -- which reads as agreement and is arithmetic. Two
implementations of one ranking is its own hazard, so `verify_ranking.py` compares the
vectorised order against the strategy's own, per date, and fails on the first disagreement.

> **Robustness check added 2026-08-23, after rule 2 ran and before the grid was analysed.**
> "Every signal day" with a 20-day horizon means each observation shares 19/20 of its content
> with the next, so the arm's ~1,110 numbers carry perhaps 55 observations' worth of
> independent information -- while the null, redrawing each day, has its dispersion shrink as
> if all 1,110 were independent. A percentile of 100.0 therefore reads far stronger than it
> is. `--stride 20` reruns the same check on non-overlapping windows. Both are reported; the
> pre-registered daily version is the one rule 2 formally refers to, and the strided one is
> the one to read for how large and how durable the effect is. They disagree, materially, and
> the report says so rather than quoting whichever is kinder.

**The engine rewrite is re-anchored before this study's numbers are believed.**
`s2_chandelier` must still reproduce `20260820/runs/prior_refresh/kline_reversal`. The
earlier six-cell equivalence check covered `shared` mode, but not a book that holds many
positions at once against a real cash gate, which is the path every cell here takes.

> **Amended 2026-08-23, before any grid cell was run.** The second sentence above is wrong
> and the anchor it names is weaker than it claims. `refresh_prior_arms.py` runs
> `--capital-mode unconstrained`, and all ten `prior_refresh` kline_reversal cells report
> `cash_blocked_entry_count = 0` -- so that anchor cannot exercise the cash gate at all,
> and satisfying it would have proved nothing about the path this study takes.
>
> The pre-registered anchor still runs, because dropping a gate once it turns out to be
> weak is the failure this study exists to avoid. A second set runs beside it:
> `20260822-ratchet-generalization/runs/{train,holdout}_shared` holds 90 cells, 74 with
> `cash_blocked_entry_count > 0`, generated before the rewrite and after the last
> `price_daily.parquet` write. Six of the heaviest are re-run and compared trade for trade.
> `anchor_engine.py` carries the evidence. Result: 16/16 cells reproduce exactly, all six
> gate cells blocking between 389 and 670 entries.

## What would falsify the whole direction

If every score fails rule 1, selection as measured here adds nothing over chance, and the
objective's first falsifier is met (`docs/en/research-objective.md`). The honest next step
would then be to ask whether the features are wrong or whether the ranking premise is, not
to tune weights until something passes.

## Inherited limitations

Close-to-close fills; fee and the 0.3% transaction tax modelled, no slippage or market
impact beyond that -- the NT$100m liquidity floor was chosen so a NT$1m position is ~1% of a
day's trade, which is where ignoring impact is defensible. Both windows are bull-tilted. The
pool is point-in-time and includes delisted names, so it is not survivor-filtered, but the
price cache itself only holds what was ever downloaded.
