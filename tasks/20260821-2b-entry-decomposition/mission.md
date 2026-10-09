# Mission — 2B entry decomposition (S7), and a per-position risk estimator

## Why this study exists

Two things, and they are independent enough that either alone would justify the run.

**The 2B pattern has never been tested in this project.** `20260814` is filed as a
2B study, but its entry is

```python
converged and trend_ready and (bottom_2b or price_strength)
```

so the false break is an _alternative_, not a requirement. Counting entry reasons
in its own `signal_events`: `bottom_2b` supplied **2 of 84** train entries and
**1 of 34** holdout entries. Every number that study reports as "2B" is, by signal
count, a dual-moving-average convergence breakout. The user's own read of the
result — that the backtests came out unremarkable — is correct about the outcome
and wrong about the cause, because the mechanism being blamed was never switched
on.

**Its tuning conclusion is not attributable.** `two_b_break_pct` was read by
`detect_bottom_2b` (entry) _and_ `detect_top_2b` (exit). Raising it 0 → 1.5 cut
top-2B exits 145 → 45 and lifted the median hold 14 → 30 days; entries fell
176 → 84 as a _consequence_ of positions staying open longer. The mission stated
"exits and sizing stay at defaults so any change is attributable to entry
structure alone" — which the shared parameter makes false. This is the same
confound class `20260821` was built to eliminate, so this study inherits that
study's AST gate.

Alongside it, a repair the last three studies all need: **the risk estimator**.
`20260816`, `20260820` and `20260821` each decide risk questions by tallying
`max_drawdown_rate` across five `shared` runs — five observations — while
deciding return questions on 900+ trades, and print both as if equally solid.
`mae_analysis.py` replaces the tally with a per-position maximum-adverse-excursion
distribution: hundreds of observations, quantiles instead of a vote.

## Design

Entry isolation. The exit, the detectors, the sizing and the bar loop are
byte-identical across arms; only `should_enter` differs, and `verify_isolation.py`
proves it by AST before any cell runs.

| Arm   | Entry                                                         | Question it answers                                           |
| ----- | ------------------------------------------------------------- | ------------------------------------------------------------- |
| **R** | `converged and trend_ready and (bottom_2b or price_strength)` | reference — the original, both branches live                  |
| **A** | `converged and trend_ready and price_strength`                | the momentum branch alone — what `20260814` actually measured |
| **B** | `converged and trend_ready and bottom_2b`                     | **the 2B pattern alone — never measured before**              |

R fires exactly when A or B fires. `verify_isolation.py` checks this over all 16
combinations of the signal flags, so the three arms are a decomposition of one
signal set, not three unrelated strategies, and (A, B) can say which branch was
carrying R.

The regime filter (`converged and trend_ready`) stays in every arm. A bottom 2B
with no trend gate buys every failed breakdown in a downtrend; losing there would
say nothing about the pattern, only that catching knives is expensive. The
question is whether the false break adds anything _within the same regime_ arm A
already trades.

**Second factor: `partial_exit` on/off.** Reconstructing `20260814`'s trade log
position-by-position shows the moving-average scale-out is where the money goes:
223 partial sells at a **14.8% win rate for −1.13M**, against 45 top-2B exits at
77.8% for +2.42M. It is not the disaster protection — the −8% stop is separate —
so it may be pure drag. It is a boolean read by `exit_plan` and nothing else
(gate-checked), which keeps it a clean second factor rather than a third variable.

Grid: 3 arms × 2 exits × 5 universes × 2 windows × 2 capital modes = **120 cells**.

## Windows, universes, parameters

Train `2019-01-02 .. 2023-12-31`, holdout `2024-01-01 .. 2026-08-14`, the five
`*_liquid20` baskets — the archetype standard, so S7 can be read against S1–S6
without translation. 10M initial cash, `unconstrained` primary and `shared` for
account-level context.

Held fixed across every arm: `windows [5,10,20]`, `convergence_pct 2.0`,
`swing_lookback 20`, `reclaim_window 5`, `entry_break_pct 0.0`,
`exit_break_pct 1.5`, `stop_loss_pct 8.0`, `exit_window 10`,
`slow_exit_window 20`, `position_pct 0.10`.

`exit_break_pct 1.5` is the value `20260814` accepted on its own train window. Any
fixed value serves the entry comparison; this one is chosen so the shared exit is
the configuration the user's study settled on rather than an arbitrary pick.
`entry_break_pct 0.0` is the original default and the choice that gives arm B the
most signals — a power decision, made before any holdout cell ran.

## Deviations from `20260814`, stated up front

**No arm reproduces the original's absolute numbers.** Universe (8 large caps →
5×20 baskets), windows (2022–24/2025 → 2019–23/2024–26), and sizing all move. The
bridge back to the user's own results is the _direction_ of A versus B, not the
levels.

1. **Sizing** moves from `buy_by_allocation` (18% of current cash, lot-rounded) to
   `equal_notional_quantity` (fixed fraction of initial cash, integer shares). The
   original's sizing drifts with the equity curve and with how many names are
   already held, which would let occupancy differences between arms leak into
   position size. This is also what puts S7 on S1–S6's scale.
2. **The add-on-2B path is removed.** It fired once in the entire original train
   run, and its firing rate depends on how often a position happens to be open —
   which the exit controls, not the entry.
3. **`two_b_break_pct` is split** into `entry_break_pct` / `exit_break_pct`.
4. **`partial_quantity` rounds to whole shares, not 1000-share lots**, because
   sizing is now integer shares; lot rounding would scale the exit differently for
   a 2400 TWD semiconductor than for a 20 TWD shipping name.

**Data vintage.** All cells run on the post-2026-08-17 corporate-action backfill,
the same vintage as `20260820`'s refreshed S1–S3 and as `20260821`. The
`20260814` numbers predate it and are understated relative to everything here;
that is one more reason the bridge is directional.

## Pre-registered acceptance rules

Written before any holdout cell ran. `analyze_decomposition.py` applies them
mechanically and prints the verdict whatever it is.

**Unit.** Every count and every shape statistic is **per position**, never per
sell. `closed_trade_count` increments on every SELL, so the scale-out arms report
several "trades" per position — `20260814`'s holdout reports 124 against 28 real
positions. S1–S6 sell the whole position in one call, so only the position-level
unit is comparable with them.

**Primary metric.** Holdout `unconstrained` mean full pnl per entry
(`total_pnl / buy_count`), pooled over the five baskets — the same definition as
`20260820` §4.1.

**Sample scope, decided from a train-window probe before any holdout cell ran.**
Arm B on `semiconductor_liquid20`, the largest basket over the longer window,
yields **29 positions**. Per-universe arm-B cells are therefore under-powered by
construction, and **arm B is evaluated pooled only**. Pooling is exact rather than
approximate here: under `unconstrained` with sizing off constant `initial_cash`,
symbols never interact, so a pooled result equals the sum of its cells (proved in
`20260820` §5). Arm A and arm R are reported both ways.

**Rule 1 — signal quality.** An arm passes if pooled train and pooled holdout mean
pnl per entry are **both positive** and pooled holdout positions **≥ 30**.
Holdout-only positivity is recorded as non-conclusive, not as a pass.

**Rule 2 — risk (replaces the drawdown vote).** Paired on pooled MAE: an arm
passes if its **holdout MAE p90 is no worse than the comparison arm's, in both
windows**. Compared arms are named in Rule 4. Account-level `max_drawdown_rate`
from the `shared` cells is still reported, but it is **informational only** in
this study.

**Rule 3 — beat buy-and-hold: demoted to informational, with the reason on the
record.** It has now gone 0-for-17 across three studies and has a structural
explanation: both windows are Taiwanese electronics bull markets, and a long-only
strategy that is sometimes flat cannot beat a fully-invested benchmark in one. A
pre-registered rule that cannot pass is not discriminating, it only manufactures a
partial failure. It is reported here as a number, not as a gate. Re-specifying it
against an invested-capital-matched benchmark is left as an open decision for the
user, not settled unilaterally in this study.

**Rule 4 — the named comparisons.** Fixed now so that no contrast is chosen after
seeing the numbers:

|     | Contrast                                     | Question                                                           |
| --- | -------------------------------------------- | ------------------------------------------------------------------ |
| C1  | B vs A, pooled, both windows                 | does the false break beat the momentum branch it was hiding behind |
| C2  | B absolute (Rule 1)                          | does the 2B pattern have an edge at all                            |
| C3  | partial off vs on, **within each entry arm** | is the scale-out drag real                                         |
| C4  | R vs the better of A / B                     | did keeping both branches add anything                             |

**Reported regardless of outcome:** per-arm entry counts, median holding span, and
sell-to-position ratio. Turning the partial exit off lengthens holds and therefore
changes entry counts through occupancy — precisely the mechanism that misled
`20260814` — and the analysis must not read that as an entry effect.

**Everything is reported, including a total null.** All three arms failing is a
possible outcome and is itself the answer to "is 2B worth building on".

## Constraints

- No real trading, no broker credentials, no live data.
- Do not modify `StockProject/engine/`.
- Only `should_enter` may differ between arms; `verify_isolation.py` is the gate.
- Ratchet generalization onto S2/S3 is the _next_ study, not this one.
