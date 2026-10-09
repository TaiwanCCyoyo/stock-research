# Mission -- Is the box-floor ratchet an exit component, or was that an S1 result?

## What is already known, and what it cannot support

`tasks/20260821-stop-mechanism-isolation` held the Donchian entry constant and swapped
the exit. The box-floor ratchet raised per-entry PnL, and the per-position estimator
added later found it worse at MAE p90 in 10 of 10 cells (pooled -10.4% vs -9.1%, 6,034
positions). That study's own closing line named the next move: if the ratchet holds up,
it is a component that can be bolted onto any breakout entry, and the next step is to
try it on S2 and S3.

One entry is one observation. "The ratchet is an exit component" is a claim about
transfer, and nothing measured so far can distinguish it from "the ratchet happens to
suit a 20-day-closing-high entry".

## Deliberate widening of the queued scope

The queued step was 2 entries x 2 exits. This runs **3 entries x 3 exits**, because the
2x2 cannot separate two different questions that the S1 result silently merges:

- Exit A (fixed ATR floor + rolling 10-day-low trigger) does **not** ratchet.
- Exit B (chandelier: peak close minus `trail_mult` x ATR-at-entry, floored at the
  initial ATR stop) ratchets on **distance from the peak**.
- Exit C (Darvas box floor, ratcheted up as each box confirms) ratchets on **confirmed
  structure**.

The marginal cost is low: exit B already exists as S2's own published exit, so the third
column is a lift rather than a new mechanism, and it buys the one-variable contrast the
2x2 does not contain.

## The grid

Nine arms. Within a row the entry is byte-identical; within a column the exit is
byte-identical. Both directions are checked by AST, not by reading.

| entry                                                       | A: ATR + channel low | B: ATR chandelier | C: box-floor ratchet |
| ----------------------------------------------------------- | -------------------- | ----------------- | -------------------- |
| S1 Donchian 20-day closing high above MA60                  | `s1_atr_channel`     | `s1_chandelier`   | `s1_box_ratchet`     |
| S2 engulfing / hammer on a pullback in an uptrend           | `s2_atr_channel`     | `s2_chandelier`   | `s2_box_ratchet`     |
| S3 20-day high, volume surge, three-bar engulf, stacked MAs | `s3_atr_channel`     | `s3_chandelier`   | `s3_box_ratchet`     |

Entry blocks are lifted verbatim from `20260816`'s three candidates. Exit A is lifted
from `20260821`'s `donchian_atr_baseline.py`, exit B from `20260816`'s
`kline_reversal_pullback.py`, exit C from `20260821`'s `donchian_box_ratchet.py`
(`high_lookback` 20 and the `exit_lookback`-low fallback initial stop, both carried over
with the reasons that study recorded).

All nine files are emitted by `compose_arms.py` from three entry blocks and three exit
blocks. Nothing in `candidates/` is hand-edited. Byte-identity is therefore a property of
the generator, and `verify_isolation.py` verifies the generator's output rather than a
human's discipline.

## The clean contrast is B vs C

**A vs B is not a one-variable test of "does ratcheting help".** Exit A is a fixed ATR
floor _plus_ a rolling 10-day-low trigger, and that trigger is itself structural and can
fall as well as rise. Going A to B changes monotonicity _and_ the reference point at the
same time. A is reported as the non-ratcheting reference; it is not the basis of any
mechanism claim.

**B vs C is one variable**: both ratchet, both are monotone non-decreasing, both start
from an ATR-derived initial stop. They differ only in what the stop tracks -- distance
below the running peak, or the most recently confirmed box floor. Every mechanism claim
in the report must rest on B vs C.

## Two reproduction anchors, run as gates

Two cells of this grid are re-runs of strategies already measured on the current data
vintage, because their entry and their exit are both taken verbatim:

- `s1_atr_channel` is `20260821`'s `atr_baseline`. Its `train`, `holdout`,
  `train_shared` and `holdout_shared` cells must reproduce that study's numbers.
- `s2_chandelier` is `20260816`'s `kline_reversal` as re-run in
  `20260820/runs/prior_refresh/`. Its `train` and `holdout` cells must reproduce those.

Warmup is unchanged by the composition in both cases -- S2's warmup is
`max(trend_ma 60, pullback_ma 10, atr_window 14) + 2 = 62`, and neither exit A's
`exit_lookback` 10 nor exit C's `high_lookback` 20 displaces the 60 -- so the anchors are
exact, not approximate.

A divergence means this harness is wrong, or the price cache moved under us. `run_daily`
refreshes nightly and `20260821` ran on 2026-08-21, so this is also the vintage-stability
check: the S1 pair is re-run here rather than read from that task's stored cells,
precisely so a silent adjustment change shows up as a failed anchor instead of as a
finding.

## Warmup parity: union-max within an entry, never across entries

For each entry, all three arms return one warmup number: the max over the union of every
parameter any of that entry's three exits touches. This keeps the three arms of a row on
the same effective trading window. It is **not** equalized across rows -- S3 legitimately
needs `volume_ma` and S1 does not, and forcing a common number would hand S3 a warmup it
never asked for. `verify_isolation.py` asserts equality within each row numerically.

## Protocol

Train 2019-01-02..2023-12-31, holdout 2024-01-01..2026-08-14; the same five
`universes/*_liquid20.json` baskets; 10,000,000 TWD; equal-notional 10% of _initial_
capital in integer shares; `unconstrained` primary, `shared` secondary.
9 arms x 5 universes x 4 windows = 180 cells.

Entry counts are known to be adequate before running: read from
`20260820/runs/prior_refresh/`, the thinnest cell is S2 on shipping at 140 train / 73
holdout positions, against a 30-position floor. No cell is expected to be voided for
sample size, so a voided cell is a signal that the composition changed entry behaviour.

## Pre-registered acceptance rules

Written before any cell of this grid was run.

1. **Primary return metric**: holdout `unconstrained` average full PnL per entry, as in
   all three prior studies.

2. **Primary risk metric**: per-position MAE p90 from `mae_analysis.py`, computed on the
   **(code, entry_date) intersection** of the two arms being compared. The arms do not
   take the same entries -- an exit changes when a position closes, and entry is gated on
   `position > 0`, so occupancy drift between arms is guaranteed. Comparing full
   distributions would confound the exit's effect with a different entry set. The
   intersection size is reported per cell; a cell whose intersection falls below 30
   positions is reported as underpowered rather than counted.

3. **MAE must be read alongside holding period.** For a shared entry, the arm that holds
   longer has weakly worse MAE by construction, so "the ratchet deepens per-position
   pain" and "the ratchet holds longer" are not separable from MAE alone. Every MAE
   comparison is reported with median holding period and with MAE-among-losers beside it.
   If the MAE gap is explained by the holding-period gap, the report says so and makes no
   risk claim.

4. **This applies retroactively to the S1 result being generalized.** The 10-of-10 MAE
   finding in `20260821` was computed on full distributions, not on an intersection, and
   without holding period beside it. Re-measuring it under rules 2 and 3 is a
   pre-registered secondary output of this task, whichever way it comes out.

5. **The ratchet transfers as a component** only if C beats B on the primary return
   metric in at least 4 of 5 baskets in the holdout, **for both S2 and S3**, in the same
   direction as S1. One entry replicating and one not is reported as "does not transfer",
   not as a partial win.

6. **Direction must be consistent** between train and holdout. A metric that improves out
   of sample and degrades in sample is a non-finding, as in all three prior studies.

7. **The `shared` return/|max drawdown| tally is reported but has no veto.** MAE under
   rules 2 and 3 is the risk verdict. Carrying two risk metrics with equal standing
   invites picking whichever one is kinder after the fact; `shared` is kept only for
   comparability with the earlier tables.

8. **A clean negative is a result** and gets the same space in the report as a positive.

## Inherited limitations

Survivorship tilt in the baskets, close-to-close fills with no slippage model beyond fee
and the 0.3% transaction tax, and a bull-market bias in both windows. Unchanged from the
prior studies and not re-litigated here.

The beat-buy-and-hold rule that went 0-for-17 across three studies is not carried into
this task. It is structurally unable to pass for a long-only strategy that sits in cash
across two bull windows, and re-specifying it against an invested-capital-matched
benchmark is an open decision for the user, not something this task settles.
