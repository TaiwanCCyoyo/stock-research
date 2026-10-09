# Batch 5 result: rule v3 acceptance test (interim)

Scored 2026-10-10 by `score_b5.py`, as `batch5-preregistration.md` specifies.
B is from the db of claude.ai/artifact/FeBnWGeda7HtMwr8u3v4v5. A is from the db of
claude.ai/artifact/8JHTEezx6LqcroDVFsHkKF.

## Part B: precision PASSES

| group                                               |  算 | 不算 | 看不出來 |                     ratio |
| --------------------------------------------------- | --: | ---: | -------: | ------------------------: |
| **primary v3 (big_range)**                          |  15 |    7 |        2 | **0.68** (bar 0.60, pass) |
| small_range (reported only)                         |   1 |    5 |        0 |                      0.17 |
| controls (new high on volume, no v3 event that day) |   2 |    4 |        2 |                      0.33 |
| primary, cat hhhl                                   |   8 |    1 |        1 |                      0.89 |
| primary, cat bottom                                 |   4 |    3 |        1 |                      0.57 |
| primary, cat range                                  |   3 |    3 |        0 |                      0.50 |
| primary, limit-up day                               |   8 |    1 |        1 |                      0.89 |

small_range is rejected again (1/6, and 1/8 before). The owner's notes on the unsure cases say
卡在區間上緣 / 快突破又還沒.

## Part A: recall NOT YET DECIDED

There were only 4 owner positives (all 像), below the minimum of 8. Under the prereg, 30 further
windows are drawn under the same file. On these 4, the primary v3 caught 0, and 1 if small_range
is included. That is too few to judge, but the sign is bad.

| owner breakout  | v3                                                              |
| --------------- | --------------------------------------------------------------- |
| 1432 2024-10-07 | no event within 5 sessions                                      |
| 3705 2021-10-18 | no event within 5 sessions                                      |
| 2527 2023-04-07 | event on the day, blocked by a line at 20.48 (inside_big_range) |
| 6870 2025-06-26 | event on the day, small_range                                   |

Four more owner breakouts have no tag (6023 2022-11-18, 1907 2020-05-15, 2527 2023-06-02,
6235 2021-12-01). Under the prereg they are not positives. The owner is asked to tag them without
being told what v3 did.
