# Batch 2 result: breakout trigger T2

Scored 2026-10-07 by `score_b2.py`, exactly as `batch2-preregistration.md` specifies. Labels are
from the db of claude.ai/artifact/SQFR98Cz4pzdJpQsux7HXy, dumped to `labels_b2_dump/`.

## Verdict: T2 FAILS

| rule             | owner buy-breakouts | caught (+-1 session) |                    recall | rule days in windows | on owner buys |                 precision |
| ---------------- | ------------------: | -------------------: | ------------------------: | -------------------: | ------------: | ------------------------: |
| **T2** (primary) |                   9 |                    8 | **0.89** (bar 0.75, pass) |                  134 |            13 | **0.10** (bar 0.50, fail) |
| T1.5             |                   9 |                    9 |                      1.00 |                  178 |            16 |                      0.09 |
| T3               |                   9 |                    6 |                      0.67 |                   75 |             9 |                      0.12 |
| T2-red           |                   9 |                    6 |                      0.67 |                   91 |             9 |                      0.10 |

There were 9 owner positives (6 像, 3 區間突破), so the batch decides (minimum 8). No breakout was
tagged 不像 or 看不出來. 21 of 30 windows were marked 整張沒有型態, and T2 still fired 1 to 9 times
in each of them.

What this means: a close above the 20-session closing high on 2x volume finds almost every
breakout the owner picks, but 9 in 10 such days are not ones the owner picks. The trigger narrows
3,000 stock-days to 134. It does not reproduce the owner's judgement.

Label anomaly: b2-14 (3015) is marked 整張沒有型態 but also has a breakout on 2025-05-21 tagged 像.
It was scored as a positive. The owner still needs to confirm it.

## Exploratory only, after the verdict

This section does not change the verdict. Comparing the owner-picked T2 days with the other T2
days gives the same direction in both batches:

|                                    | batch 1 owner / other | batch 2 owner / other |
| ---------------------------------- | --------------------- | --------------------- |
| margin above prior 20-session high | 5.5% / 2.3%           | 5.5% / 3.0%           |
| day's change                       | +7.3% / +3.3%         | +5.5% / +4.2%         |
| volume vs 20-session mean          | 7.5x / 3.2x           | 5.4x / 3.1x           |

A stricter cut does not rescue precision either. With margin >= 4% and volume >= 4x, precision
is 5/31 in batch 1 and 3/26 in batch 2, and it loses about half the owner's picks. Raw breakout
strength therefore does not explain the owner's eye. The remaining difference lies in the
structure before the breakout. Mid-window breakouts were visible together with their aftermath,
which is a contamination risk for any later outcome comparison.
