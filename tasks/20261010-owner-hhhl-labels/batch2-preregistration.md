# Batch 2 preregistration: breakout trigger test

Written 2026-10-06, before batch 2 is sampled or shown to the owner. Do not edit after the
owner starts labelling; any change becomes a new, separately named version.

## Why

Batch 1 (30 charts) showed that every one of the owner's 16 buy-type breakouts closed above the
prior 20-session closing high on volume of at least 1.6x its 20-session mean. That pattern was
found by looking at those 16, so it is a hypothesis. Batch 2 tests it on charts nobody has seen.

## Rule under test (fixed now)

On session t, with closes c, volumes v (lots), and the 20 sessions before t:

- **Primary rule T2:** c[t] > max(c[t-20..t-1]) and v[t] >= 2.0 x mean(v[t-20..t-1]).
- Reported alongside, never used to pick the verdict: T1.5 and T3 (the same rule at 1.5x and
  3.0x volume), and T2-red (T2 plus a red candle whose body is at least 0.5 ATR14).

## Sample

- 30 windows of 100 sessions each, from the atlas-v2 per-stock tables (2019-01..2026-08).
- One window per stock. Stocks used in batch 1 or among the 21 reviewed stocks are excluded.
- Stock order and window end dates are drawn with a fixed seed (20261007), uniformly over all
  end positions that have at least 100 earlier sessions. The rule is not used to choose windows.
- The owner sees candles only, no volume panel, the same view as batch 1.

## Owner's instruction for batch 2

Mark **every upward breakout you notice**, including ones you would not buy (tag 不像), plus
the swing points that explain each one. A chart with none gets 整張沒有型態.

## Scoring

- Owner positive: a breakout tagged 像, 區間突破, 底部打底 or 漲停急拉後整理.
- Match: a rule day within +-1 session of an owner positive.
- Recall = matched owner positives / owner positives.
- Precision = rule days that match an owner positive / all rule days inside the windows.
  A rule day on a breakout the owner tagged 不像 counts against precision; one on a breakout
  tagged 看不出來 is excluded from both counts.
- **T2 passes if recall >= 0.75 and precision >= 0.50.** These bars are judgment calls made
  before seeing data, not derived from batch 1.
- If fewer than 8 owner positives appear, the batch is reported as too small to decide and a
  third batch is drawn under this same file.
