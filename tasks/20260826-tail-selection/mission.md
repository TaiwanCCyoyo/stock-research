# Mission -- among the names the score already accepts, what picks the runaway?

## 0. The owner restated the objective, and it is not the one the last three studies were graded against

On 2026-08-26 the owner wrote:

> 我最終目的是盡量可以找到飆股，同樣符合條件的股票，我能夠有方法讓我可以選擇，確定不會過度交易。

Three requirements, and each is a different measurement from the one this line has been making:

1. **find runaway stocks** -- the right tail, not the mean;
2. **choose among names that equally satisfy the conditions** -- a tiebreak inside the
   qualified set, not a better ranking of the whole pool;
3. **do not over-trade** -- a tiebreak that reshuffles the shortlist daily fails even if it
   discriminates.

Every study in this line -- `20260823-selection-vs-random`, `20260823-rank-profile`,
`20260823-regime-overlay`, `20260824-ranking-horizon`, `20260824-value-chain-ignition` --
measured a **mean** excess return and graded it against 0050's total return. That is a
different functional and a different benchmark from what the owner just described. This card
changes the outcome variable rather than adding another feature.

## 1. Why requirement 2 is a real, already-measured problem

`20260823-rank-profile` measured forward return by rank band and found no difference between
ranks 1-10, 11-30, 31-60 and 61-120 that reached |t| >= 2 in the holdout; in train only
`momentum` separated, and only from 11-30 outward. Its own conclusion:

> 排序真正可靠地做到的事是**認出不該碰的**，不是**排出最強的前五名**。

That is requirement 2 stated as a finding. The score reliably rejects the bottom of the pool
and then hands back roughly sixty names it cannot order. The owner has ten slots. Something
has to choose, and today the thing that chooses is a checksum tiebreak.

## 2. Orientation already run, and what it establishes

A probe (`.tmp/tail_probe.py`, not part of this task's artifacts) measured two things before
this mission was written. Both are inputs to the design, not results of it, and both are
re-derived inside this task by `tail_stats.py` so nothing rests on a scratch file.

**Headroom exists, and it is concentrated in the tail.** Share of eligible names whose
20-day forward total return clears a threshold, non-overlapping dates:

| train           | >= +10% | >= +20% |   >= +30% |
| --------------- | ------: | ------: | --------: |
| whole pool      |  16.83% |   6.91% |     3.20% |
| top-60 by score |  22.10% |  11.46% |     6.03% |
| top-10 by score |  24.11% |  15.54% | **8.57%** |

The lift over the pool **rises with the threshold**: 1.43x at +10%, 2.25x at +20%, 2.68x at
+30% for top-10 in train; 1.29x / 1.70x / 2.03x in holdout. The score is a better
runaway-finder than it is a mean-return generator, which is exactly why it can lose to a
cap-weighted index and still serve the owner's stated objective.

**Most candidate tiebreaks are not collinear with the score inside the qualified set.**
Median per-date Spearman rho against the momentum score within top-60:

| tiebreak candidate | train rho | holdout rho | usable as a tiebreak? |
| ------------------ | --------: | ----------: | --------------------- |
| `ext_20`           |     +0.06 |       +0.10 | yes                   |
| `vol_ratio`        |     +0.03 |       -0.04 | yes                   |
| `cohort_breadth`   |     +0.04 |       +0.09 | yes                   |
| `contraction`      |     +0.20 |       +0.13 | yes                   |
| `ret_250_ex_20`    |     +0.22 |       +0.12 | yes                   |
| `sharpe_250`       |     +0.38 |       +0.30 | borderline, excluded  |
| `ret_120`          |     +0.54 |       +0.47 | **no**                |
| `sharpe_60`        |     +0.63 |       +0.63 | **no**                |
| `above_ma60`       |     +0.81 |       +0.79 | **no**                |

A candidate that restates the score cannot break a tie the score produced. The three marked
**no** and the borderline one are excluded from the arms for that reason, stated here rather
than discovered later.

This is also where the cross-learning from `codex/kline-research` lands.
`tasks/20260823-dynamic-cohort` measured that return-derived peer groups persist out of
sample -- next-20-day pair correlation 0.334 against a matched-null 80th percentile of
0.258 -- but that **adding** peer return and breadth to every name's score made the ranking
worse, because it dilutes the stronger momentum rank; its own conclusion was that the
supported use is diagnostic. A post-hoc tiebreak applied _after_ the score has already
selected is exactly the use that result leaves open, and it is the form used here.

## 3. The trap this design has to avoid, declared before any arm runs

**A raw tail-hit rate is monotone in volatility almost by construction.** A high-volatility
name has a higher P(+30%) and a higher P(-30%). "Prefer the jumpiest name among the tied
ones" would win this measurement, mean nothing, and read as a finding. Note the sign: this
is the opposite of what `ra_60/120/250` tested in `20260824-ranking-horizon`, which preferred
_smooth_ compounding and failed. The trap sits exactly where this study steps.

Three defences, all pre-registered:

- **`vol_60` is arm number one**, declared as the trivial explanation. Any other arm is
  reported against it, not only against the null.
- **Both tails are reported for every arm and every threshold**, and the gate is on the
  **asymmetry** `P(+T) - P(-T)`, never on `P(+T)` alone.
- **Any arm that clears the gate is re-measured inside trailing-volatility terciles.** An arm
  that only works in the high-volatility tercile is volatility wearing a different name, and
  is reported as such rather than as a tiebreak.

`verify_rules.py` asserts this is a live gate by feeding it a synthetic high-volatility,
zero-edge input that must fail.

## 4. What is measured

**Universe and score are frozen from the existing line.** `rotation_pit`, the `eligible`
flag and the `momentum` score (mean of the `ret_20` and `ret_60` cross-sectional percentiles)
exactly as `20260824-ranking-horizon/features_v2.parquet` carries them. Nothing about the
selection changes; only what is measured about it.

**The qualified set is the top 60 by score on each date.** Derived from
`20260823-rank-profile`, which could not distinguish rank bands out to 120 and found the
reliable signal only at 201+. Sensitivity at **30** and **120** is reported for every
headline number; a result that exists only at 60 is a boundary artifact.

**Horizon and thresholds.** Primary is 20 trading days with thresholds
`+10%, +15%, +20%, +25%, +30%`, sampled at stride 20. Secondary is 60 trading days with
`+20%, +30%, +40%, +50%` at stride 60, which leaves roughly 18 train and 9 holdout dates and
is therefore reported as descriptive, with its N printed beside every figure.

Forward returns are net of one round trip on `book.py`'s **total-return adjusted** prices,
the same convention as every prior study in this line; features stay on split-adjusted,
dividend-unadjusted closes, for the reason recorded in `20260823-selection-vs-random` §2.

**The statistic is a date-paired difference, and the standard error is clustered by date.**
On each sampled date the qualified set is split at the median of the tiebreak; the statistic
is the top half's hit rate minus the bottom half's, **within that date**. Market-wide spikes
are common to both halves and cancel. The error bar is then taken across dates, so the
effective N is 56 in train and 29 in holdout -- not the 3,317 and 1,740 name-date cells,
which are not independent because spikes cluster in time. Treating those cells as
independent is the same error class as the overlapping-window inflation this line already
caught once, where t went from +8.8 to +0.2.

**Train is the primary window.** The holdout is on its fifth read across this line and is
reported as one confirmatory look, never as the gate.

## 5. Arms

Nine tiebreaks. Each is applied _after_ the score has chosen the qualified set, and each has
a pre-declared direction with a mechanism. Six come from the existing feature table; three
are new and built by this task's `tail_features.py`.

| arm              | tiebreak                                                     | direction | mechanism claimed                                       |
| ---------------- | ------------------------------------------------------------ | --------- | ------------------------------------------------------- |
| `vol_60`         | stdev of daily returns over 60 bars                          | higher    | **the trivial explanation, declared first**             |
| `ext_20`         | close against the prior 20-day high                          | higher    | already breaking out, not merely strong                 |
| `vol_ratio`      | volume against its own 20-day average                        | higher    | participation confirms the move                         |
| `contraction`    | ATR(14)/close against its own 60-day average                 | **lower** | a tightening base is the VCP precondition for a spike   |
| `cohort_breadth` | share of the official category with a positive 20-day return | higher    | a name moving with its group, not alone                 |
| `ret_250_ex_20`  | 250-day return skipping the most recent 20 bars              | higher    | long-term strength without the reversal-prone month     |
| `node_strength`  | median `ret_20` percentile of the name's value-chain nodes   | higher    | the finer grouping, used as a filter not an addend      |
| `node_breadth`   | share of node members with a positive 20-day return          | higher    | ignition read post-hoc rather than as a score term      |
| `liquidity`      | median 60-day turnover value                                 | **lower** | smaller names travel further -- and must clear `vol_60` |

`node_strength` and `node_breadth` read `value_chain_classification.json`, a **snapshot dated
2026-08-23**. Applying today's membership to 2019 is a mild look-ahead. It has a direction --
the snapshot is most accurate for recent dates -- so it should flatter **holdout** over
**train** here. The two windows are reported separately for that reason. The file is absent
from this worktree's `data/` copy and is resolved from the main checkout the way `detector.py`
resolves `official_daily.sqlite`.

## 6. Acceptance

**Rule 1 -- it must discriminate.** The date-paired asymmetry difference must reach
**t >= 2.0** one-sided in the pre-declared direction, in **train**.

**Rule 2 -- a plateau across thresholds, not a cutoff.** Rule 1 must hold at **three
contiguous thresholds** of the five. Nine arms tested one-sided at t >= 2.0 would produce
roughly half a false positive per threshold by chance; requiring three contiguous is what
controls that, and it is the same plateau constant this line has used since
`20260824-ranking-horizon`.

**Rule 3 -- it must not be volatility.** The arm must still satisfy rule 1 at its plateau's
centre threshold **within the middle and low trailing-volatility terciles**, measured
separately. `vol_60` itself is exempt, because it _is_ the explanation being controlled for;
it is reported to calibrate how large a volatility-driven reading looks.

> **Amended 2026-08-26, after the feature table was built and before any arm was measured.**
> The rule above demands `t >= 2.0` inside each of two terciles, which cuts the qualified set
> from 60 names to 20 per date and therefore tests the arm at a third of the power the same
> rule 1 gets -- so it would reject a real effect for a reason that has nothing to do with
> volatility. That is a power artifact, not a control. The rule becomes a **stratified**
> estimate instead, which removes the volatility contrast without throwing away names: on
> each date the paired asymmetry difference is computed **inside each volatility tercile** and
> the three are averaged equally, then the error bar is taken across dates as before. The arm
> must reach `t >= 2.0` on that stratified statistic **and** keep a positive point estimate in
> the **low** tercile, so an effect carried entirely by the jumpiest third still fails. The
> per-tercile figures are printed beside it either way, so a reader can see the shape rather
> than only the verdict.

**Rule 4 -- it must not make the owner trade more.** Two statistics, both gating:

- **shortlist churn**: names entering a score-then-tiebreak top-10 per slot per year, against
  the score-then-checksum top-10's. At most **1.25x** the incumbent's, because the owner's
  standing ceiling of 12 round trips per slot per year is close and a tiebreak has no licence
  to spend it;
- measured in **train and holdout separately and required in both**, closing the scoping gap
  found in `20260823-regime-overlay`, where an arm passed on the holdout row alone while
  spending 13.55 in train.

**Rule 5 -- the boundary must not be the finding.** Any arm clearing rules 1 to 4 at top-60
is re-reported at top-30 and top-120. An arm that survives only at 60 is reported as a
boundary artifact, not as a tiebreak.

**Rule 6 -- a clean negative is a result.** If no tiebreak discriminates, the finding is that
the qualified set is genuinely unorderable from this data, and the honest advice becomes
"hold more of them, or choose by something outside the price series". That is a usable answer
to the owner's question and gets the same space as a positive.

## 7. What this study deliberately does not do

- **No engine run and no portfolio return.** This is a cross-sectional measurement of a
  selection rule. If an arm passes, putting it in the engine and re-checking turnover under
  real cash constraints is the _next_ card, not this one.
- **No per-node holdings cap.** Forcing dispersion is a portfolio-construction rule that
  trades tail-hit rate against concurrent drawdown, and it needs an axis to decide it that
  this card does not have. It stays out rather than being smuggled in.
- **No re-litigation of the index gap.** Whether the deliverable is a portfolio or a
  shortlist the owner picks from by hand changes the benchmark entirely, and that is a
  question for the owner rather than an assumption to be buried in an acceptance rule.

## 8. Gates

- `verify_tail_features.py` -- every new column passes a truncation test (a table rebuilt
  from bars ending at date T matches the full table on every row up to T, with the lookahead
  injected into the _builder_ rather than the input series, because the latter corrupts both
  rebuilds identically and they agree); no column is available on a bar where its own window
  is incomplete; the carried-over columns are read, never recomputed.
- `verify_rules.py` -- every acceptance rule fires in the direction it is supposed to,
  asserted on synthetic inputs at exact values with the opposite case asserted too, including
  the high-volatility zero-edge input that rule 3 must reject.

## 9. Reproduction

```bash
uv run python tasks/20260826-tail-selection/tail_features.py
uv run python tasks/20260826-tail-selection/verify_tail_features.py
uv run python tasks/20260826-tail-selection/verify_rules.py
uv run python tasks/20260826-tail-selection/tail_stats.py
```

## 10. Amendments after the first run

**2026-08-26, after the first sweep and before the report was written: `score` is added as a
tenth arm.** It is the incumbent rather than a candidate -- splitting the qualified set at the
median of the score itself asks whether the ranking's own remaining order carries tail
information after the top-60 cut. Its omission was an oversight, and it mattered: without it
the study could report that no _new_ tiebreak works while being unable to say whether
_anything_ orders the set, which is the question the owner actually asked. It is subject to
the same rules as every other arm, and its churn ratio is 1.00x by construction, which is
also a self-check on the churn measurement.

**The §2 headroom figures are superseded by this task's own.** They were quoted from the
scratch probe, which sampled 56 train dates because it required a 60-day forward runway for
both horizons; `tail_stats.py` samples the 61 dates a 20-day horizon actually supports. The
task's numbers are stronger than the probe's, not weaker -- top-10 at +30% reads 11.82%
against the probe's 8.57% -- and an independent re-derivation written without reusing any of
`tail_stats.py`'s helpers reproduces them cell for cell. The mission text is left as written
rather than edited to match, so the difference stays visible.
