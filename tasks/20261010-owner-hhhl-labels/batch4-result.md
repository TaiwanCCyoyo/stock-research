# Batch 4 result: rule v2 acceptance test

Part B was scored 2026-10-09 by `score_b4b.py`, as `batch4-preregistration.md` specifies. The
judgments are from the db of claude.ai/artifact/PBBUPYvbLKQbpgTPk3tUVw (`b4b_dump/`). Part A was
empty when read: the db of claude.ai/artifact/Te15c5tArp5gasUy2pXRpq held no labels.

## Verdict: v2 FAILS on precision, whatever Part A shows

| group                                      |  算 | 不算 | 看不出來 |                 precision |
| ------------------------------------------ | --: | ---: | -------: | ------------------------: |
| **v2 rule events**                         |   9 |   13 |        2 | **0.41** (bar 0.50, fail) |
| controls (new high on volume, no v2 event) |   2 |    6 |        0 |                      0.25 |
| context clears                             |   7 |    3 |        0 |                      0.70 |
| context inside_big_range                   |   2 |    6 |        1 |                      0.25 |
| context after_decline                      |   0 |    4 |        1 |                      0.00 |
| cat hhhl                                   |   6 |    3 |        0 |                      0.67 |
| cat bottom                                 |   2 |    5 |        1 |                      0.29 |
| cat range                                  |   1 |    5 |        1 |                      0.17 |

The owner's notes on the rejected events say 還在區間 or 大區間 four times. They also say the
range looks bigger when the price fell into it (1558).

## What it suggests for v3 (not applied to v2)

The owner accepts breakouts that **clear the highest close of the 90 sessions before the
restart** (7/10), mostly in the hhhl category. Everything still inside an earlier range is
rejected, whether the run-in was sideways or falling. v1's after_decline exception is
contradicted (0/4). Each group is 5 to 10 events, so this is a direction, not a result. Any v3
built on it needs a fresh test batch, and Part A recall will drop if only clears is kept.

## Part A (read 2026-10-09 after the owner finished; `score_b4a.py`)

There were 7 owner positives (all 像), below the minimum of 8, so the prereg would add 30
windows before judging recall. The verdict does not need it, because v2 already failed on
precision. Indicative recall: v2 caught 5/7 = 0.71, with 59 rule events in the 30 windows. The
clears-only subset caught 4/7 = 0.57, with 23 events. The owner's notes repeat 大區間還在裡面 /
小地方有突破 / 後面在區間. 8423 adds a new point: 成交量就很低，這種要不要直接排除, which
raises a liquidity floor as a candidate condition. One chart, 3016, is marked 整張沒有型態 but
also carries a 像 breakout. It was counted as a positive.
