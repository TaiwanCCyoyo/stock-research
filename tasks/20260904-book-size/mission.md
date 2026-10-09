# Mission — is the wide book real out of sample, or was K25's holdout win luck?

Pre-registered 2026-09-04. **The holdout prediction in section 4 was written before the holdout
cell was run.**

## 0. What is already settled, by codex, and must not be re-run

`.worktrees/kline-sizing/tasks/20260827-book-shape-corrected-baseline` measured the whole book-size
family on train with fixed initial-cash sizing. Its train result is a clean pair of monotone trends,
not a sweet spot:

|   K | return | drawdown | capture | participation | pool share | turnover |
| --: | -----: | -------: | ------: | ------------: | ---------: | -------: |
|  10 |  224.2 |    −32.6 |   0.811 |         0.171 |     0.1642 |     4.61 |
|  15 |  182.8 |    −32.9 |   0.932 |         0.183 |     0.2102 |     5.01 |
|  20 |  188.4 |    −29.4 |   0.959 |         0.229 |     0.2664 |     5.28 |
|  25 |  162.2 |    −30.7 |   0.973 |         0.272 |     0.2930 |     5.61 |
|  30 |  148.7 |    −31.0 |   0.973 |         0.292 | **0.3237** |     5.88 |

**Pool share rises monotonically to K=30 and account return falls monotonically to K=30.** K25 was
not a discovered optimum; it was, in codex's own words, "the smallest arm meeting" a gate set that
included a two-thirds-of-baseline **return floor**. K30 failed only that floor.

Re-running this curve would reproduce someone else's work. This card does not.

**Those numbers are not comparable to anything this card produces.** codex's K10 train cell reports
pool share 0.1642 and capture 0.811; the same nominal cell under this line's pipeline reports
0.1231 and 0.938, because the two lines build the feature snapshot and the runaway population
differently. The table above is read for its **shape**, never for its levels, and no number from it
appears in this card's own comparisons.

## 1. The one thing that is open

codex opened the holdout for exactly two book sizes:

|             |    return |  drawdown | pool share (×1.5) |
| ----------- | --------: | --------: | ----------------: |
| K10 holdout |      81.5 |     −53.3 |            0.0461 |
| K25 holdout | **139.4** | **−39.5** |        **0.1550** |

**Out of sample K25 beat K10 on return, on drawdown, and on pool share at once — the train
trade-off inverted.** In train, more slots cost return. In the holdout, more slots gained it.

That inversion is the whole question, and it decides what the owner should do:

- If it is **real**, the return floor that selected K25 was fitted to a train artifact, and the
  right book is further up the K curve than 25, not at it.
- If it is **noise**, K25's holdout win was luck and book width is a genuine trade-off the owner
  must choose a point on.
- If **pool share itself fails to rise** out of sample, book width is not the lever at all and this
  whole direction closes.

## 2. Cells, and why there is no new strategy file

Three train cells, `K in {10, 20, 30}`, run on
`20260826-runner-retention/candidates/rotation_ranker_v5.py` **unchanged** — only `top_k` moves.
No subclass is written, so `backtest_cli.py`'s alphabetical resolver has nothing to pick wrongly;
that trap cost `20260904-execution-delay` an entire grid.

Everything else is the standing configuration: `rotation_pit` point-in-time, ETFs removed before
ranking, score `r_ret_20 + r_ret_60` with the CRC32 tie-break, exit at `rank >= 30` after a 20-bar
minimum hold, entry budget a fixed `initial_cash / K`, shared cash of TWD 10,000,000, engine fee
and tax, and the standing same-close execution convention.

`k10` is the anchor and must reproduce `20260826-runner-retention`'s stored `rank30` cell trade
for trade.

## 3. The band check, which decides whether this card is worth running

At `K = 30` the entry rank and the exit rank coincide: V5 takes `order[:top_k]` and sells at
`rank >= max(exit_rank, top_k)`, so a name enters inside rank 30 and is sold at rank 30. If that
band collapses into churn, K30's low train return is an artifact of the band rather than evidence
about book width, and the section 4 test means nothing.

**This is checked before the holdout is opened, and it is a hard stop.** `k30`'s turnover per slot
per year must be within 1.5x `k10`'s and its mean slots used must be at least 0.8 x 30. The 20-bar
minimum hold is what should prevent the degeneracy; codex's own K30 turnover rose only 27% over
K10, which is the prior, not the evidence. If the check fails, the card stops and reports that K30
is unusable rather than substituting a different K after the fact.

## 4. The pre-registered holdout prediction

**One holdout cell is opened: `k30`.** K10's holdout run already exists under this pipeline as the
retention card's stored `holdout__rank30`, so no second read is added. K30 is holdout-clean —
codex read only K10 and K25 — and it is the sharpest discriminator, being the extreme of both
train trends.

Against this line's own stored K10 holdout numbers (return 81.5%, drawdown −53.3%, pool share
0.0682 at ×1.5), the outcomes are assigned **now**:

| observation                                   | conclusion                                                                                          |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| pool share **>** K10 **and** return **>** K10 | the inversion is real; the train return floor was an artifact and the owner belongs above K25       |
| pool share **>** K10 **and** return **<** K10 | book width is a genuine trade-off; the owner chooses a point, and K25's holdout return win was luck |
| pool share **<=** K10                         | book width is not the lever out of sample; this direction closes                                    |

Drawdown is reported beside each and is not part of the assignment, because two of the three rows
are already decided without it.

There is no second look, no other K, and no re-reading of this cell under a different metric. If
the result is ambiguous the report says so rather than reaching for a tiebreak.

## 5. What this card may not conclude

It moves one parameter under the standing same-close convention, which codex established is
optimistic. It says nothing about a wide book under next-open execution or under stress costs.

**And it cannot settle the owner's constraint.** A 30-name book at this line's costs conflicts with
「用手在合格名單裡挑」 and with 「不能頻繁亂換」 whichever way the number falls — and if the wide book
wins, that conflict gets worse, not better. The report must carry that alongside the result rather
than after it.
