# Batch 3 result: rule v1 final acceptance test

Scored 2026-10-09 by `score_b3.py`, exactly as `batch3-preregistration.md` specifies.
Part A labels are from the db of claude.ai/artifact/K2seibqRVVbqVFxfeVF1ui (`b3a_dump/`).
Part B judgments are from the db of claude.ai/artifact/XviNwgA4LAHk8YtKMwBTJQ (`b3b_dump/`).

## Verdict: v1 FAILS on recall

| part                                           | measure                                  |           result |           bar |
| ---------------------------------------------- | ---------------------------------------- | ---------------: | ------------: |
| A, blind, 30 fresh windows                     | owner buy-breakouts caught (+-1 session) |  **4/10 = 0.40** |    0.75, fail |
| B, blind, breakout day only                    | rule events the owner accepts            | **11/21 = 0.52** |    0.50, pass |
| B controls (new high on volume, no v1 pattern) | accepted                                 |       2/7 = 0.29 | reported only |

There were 10 owner positives (8 像, 2 區間突破), so the batch decides. Of the 30 windows, 17 were
marked 整張沒有型態. Part B shows the structure part adds something over a plain new-high-on-volume
day (52% vs 29%), but the sample is small.

## Why the six misses were missed (diagnostic, v1 unchanged)

| owner breakout                                    | what dropped it                                                                                                      |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| 2375 2024-05-27, 9935 2023-02-23, 2542 2021-07-08 | v1 found the breakout (within 1 session) but tagged it inside_big_range                                              |
| 3675 2020-05-25, 8299 2024-02-20                  | an earlier first close above the same zone failed the volume test, and v1 never re-tests a zone it has marked broken |
| 6167 2024-01-24                                   | the latest low is lower than the one before, so the category is none                                                 |

The big-range filter introduced on the critique round caused half the misses on fresh data. It
had raised development precision from 53% to 70%.

## Data issue raised by the owner

The charts use atlas-v2 prices, which restate permanent corporate actions but leave cash
dividends as price drops. The owner flagged 2459 on 2019-07-11 as an ex-dividend gap that reads
as a pullback. Swing detection sees the same false drop. A v2 should use cash-dividend-adjusted
prices.

## Not done

v1 was not tuned on batch 3. Any fix is v2 and needs a fresh test batch.
