# Mission -- how far can turnover come down before selection is measurably lost?

## The question, and why it is this one

`20260823-selection-vs-random` answered "does ranking beat chance" with **yes, and it barely
matters**: 27 of 30 holdout cells beat the 80th percentile of their matched random-draw null,
and the turnover gate cut that to 4. The 23 that fell out were one shape -- 60 to 167 round
trips per slot per year, 30% to 84% of capital a year in cost. Ranking carries information;
almost none of it survived being traded on.

Two measurements from that study and its follow-up diagnostic point at the same next step.

**`exit_rank` does not control turnover; the score's own day-to-day stability does.** At a
fixed 6x band and a fixed book size, average holding period ran from 3.0 calendar days
(`breakout`) to 22.9 (`momentum`) -- 7.6x, from the score alone.

**Nothing below the top 10, down to rank 60, is measurably worse out of sample.**
`20260823-rank-profile` measured the paired per-day difference against band 1-10 on
non-overlapping windows: not one of five scores x four bands reaches |t| = 2 in the holdout;
`cohort` at ranks 31-60 is +0.60 +- 1.83. Only train `momentum` shows a real penalty for
widening (-2.87 +- 1.39 at 11-30). So there is **no evidence requiring a tight band** -- which
is exactly the licence a wide hysteresis needs, and it is also why the previous grid's
1x -> 3x -> 6x was monotonically better (`cohort` k10: +66.9% -> +114.4% -> +147.3%).

The grid stopped at 6x while the trend was still rising. This study pushes it to where it
turns, and tests two rank-independent mechanisms beside it so the answer is not "one knob
happened to help".

## What is being held fixed

Three configurations carry over as baselines, chosen because they are what the previous
study left standing plus the case that failed the objective:

| baseline          | holdout return | turnover/yr | why it is here                         |
| ----------------- | -------------: | ----------: | -------------------------------------- |
| `cohort` k10 6x   |        +147.3% |        20.3 | best usable finding                    |
| `momentum` k10 3x |         +92.4% |        16.1 | second finding, lowest turnover        |
| `all` k5 6x       |        +151.1% |        55.6 | highest return, fails the cost ceiling |

Everything else is unchanged from that study: `rotation_pit`, 10,000,000 TWD, `shared` mode,
train 2019-01-02..2023-12-31 and holdout 2024-01-01..2026-08-14, the same matched
random-draw null from `book.py` and `null_draw.py`, the same gates
(`verify_null.py`, `verify_ranking.py`).

## Arms

One variable per arm, against its own baseline.

**A. Widen the band further.** `exit_rank` at 6x (baseline), 12x, 20x, and `inf` -- the last
sells only on eligibility loss, which is the boundary case where the book freezes into
whatever it first bought. `inf` is included precisely because it should fail: if it does not,
the ranking is adding nothing after entry and that is a much larger finding than this study
set out to make.

**B. Minimum holding period.** A position cannot be sold for 10 or 20 trading bars regardless
of rank, at the baseline band. This is rank-independent by construction, so it separates "the
ranking is right to churn" from "the ranking is noisy". Eligibility loss still forces a sale --
a name that stops trading or falls under the liquidity floor is not holdable, and overriding
that would make the arm untradeable rather than patient.

**C. Score smoothing.** Rank on the 5- or 10-day mean of the score instead of today's, at the
baseline band. This attacks the instability the mechanism finding identified, rather than
absorbing it downstream.

3 baselines x (4 + 2 + 2) arms x 2 windows = **48 cells**.

## Pre-registered acceptance rules

Written before any cell was run. The primary question has changed from the previous study --
turnover is the dependent variable here, not a gate -- so the rules are not simply inherited.

1. **Absolute cost ceiling: 12 round trips per slot per year**, which is 6.0% of capital a
   year at the 0.5%-per-round-trip rate used throughout. Chosen by the owner on 2026-08-23.
   The previous study's rule 3 was _relative_ (Pareto non-dominance) and let a 27.8%/yr cell
   through as a finding; the objective's constraint is absolute, so this one is too.

2. **At most one third of the excess may be given up to get there.** An arm's excess is its
   book return minus its null's mean. A qualifying arm must retain **>= 2/3 of its own
   baseline's excess** in the holdout. Both numbers are absolute and both were fixed before
   any cell ran, because choosing them afterwards is choosing them while looking at results.

3. **Direction must hold between train and holdout, at the 80th percentile in both.** The
   previous study bound this to the null's _median_ and 27 of 27 cells passed, so it
   confirmed nothing -- the train nulls sit far below the arm once cost destroys them. The
   threshold is the same 80th percentile as the holdout rule, in both windows.

4. **The unconditioned check still applies.** The arm's top-K by score must beat a day-wise
   random draw on fixed-horizon 20-day forward return, measured on **non-overlapping windows**
   (`--stride 20`). The previous study pre-registered daily sampling and then measured how
   badly the 19-in-20 overlap inflates a randomisation percentile; carrying that forward
   knowingly would be a choice, not an inheritance.

5. **A clean negative is a result.** If no mechanism reaches 12 round trips a year while
   keeping two thirds of its excess, that is the answer about how cheap this strategy family
   can be made, and it gets the same space as a positive.

## Decisions pinned before the harness was written

**Smoothing means the N-day mean of the score, not of the underlying features.** Measured on
2026-08-23 before choosing: the two definitions produce the same ordering. Spearman between
them is 1.0000 for `momentum` and 0.9999 for `cohort` and `all`, and the top-10 sets agree on
99.7% to 100% of days. `momentum` is exact because a rolling mean and a weighted sum are both
linear; the others differ only where `fillna(0.5)` meets the rolling window. So this is a
choice of the cheaper implementation (one rolling series per arm instead of eight) and not a
modelling decision -- recorded because it looked like one.

Note what smoothing a _rank_ does and does not do: averaging five days of percentile ranks
averages five different cross-sections, so a name whose own features never moved can still
drift because the pool moved around it. That is not a defect here -- that drift is precisely
the instability being smoothed.

**The minimum hold does not override eligibility.** It blocks only the rank-based sale.

**`inf` is implemented as an exit rank larger than the pool, not as a separate code path**, so
the arm differs from its baseline in one parameter and nothing else.

**Turnover, cost, and excess keep their previous definitions** -- round trips per slot per
year from `null_draw.turnover_per_slot_year`, cost at 0.5% per round trip, excess as book
return minus null mean, all from `book.py` so arm and null share one statistic. A number here
is comparable to the previous study's by construction.

**The engine anchor does not need re-running.** `anchor_engine.py` passed 16/16 trade-for-trade
on 2026-08-23 against this same data, and `price_daily.parquet` and `corporate_actions.sqlite`
in this worktree are byte-identical to the main checkout's (md5 verified at worktree
creation). If either file changes, the anchor runs again before any number here is believed.

## What would falsify the direction

If the `inf` arm -- never selling on rank -- matches its baseline, then the ranking contributes
nothing after entry, and the whole hysteresis framing is decoration on a buy-and-hold of the
first top-K. That would redirect the work to entry timing rather than to rotation.

If every mechanism that reaches the cost ceiling loses more than a third of its excess, the
answer is that this strategy family cannot be made cheap enough, and the next move is a
different feature set or a different holding horizon, not another turnover knob.

## Inherited limitations

Close-to-close fills; fee and the 0.3% transaction tax modelled, no slippage or market impact
beyond that. Both windows are bull-tilted. The pool is point-in-time and includes delisted
names. Returns are measured on total-return adjusted prices while features use unadjusted
closes, for the reasons in `20260823-selection-vs-random/report.md` §2; the dividend component
of any finding is reported per cell rather than assumed neutral, because assuming it cost that
study a wrong claim.
