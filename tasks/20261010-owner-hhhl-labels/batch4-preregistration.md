# Batch 4 preregistration: acceptance test of rule v2

Written 2026-10-09, before batch 4 is sampled or shown to the owner. The rule under test is
`hhhl_rule_v2.py` (derived from v1 by `make_v2.py`), run on `adjprice.load` total-return
adjusted prices. Do not edit either file after the owner starts. A change is v3 with a new
batch.

Development results on everything already seen (batches 1-3 and the critique round) are not a
test. Recall was 13/16, 6/9 and 8/10, 27/35 = 77% pooled. Precision proxies were 15/29 = 52%
and 11/23 = 48%. The precision bar is therefore at risk.

## Design (same as batch 3)

Stocks used in any earlier batch, review or batch-3 set are excluded. Part A and Part B use
different stocks. Seed 20261010. Charts show dividend-adjusted candles. The pages say so,
because the prices will not match raw quotes.

**Part A (recall).** 30 windows of 100 sessions, one per stock, with end positions drawn
uniformly. Candles only, with no volume and no rule marks. The owner marks every upward
breakout and its swing points.

- Owner positive: a breakout tagged 像, 區間突破, 底部打底 or 漲停急拉後整理.
- Recall = owner positives with a v2 pattern event within +-1 session / owner positives.
- If there are fewer than 8 owner positives, add a further 30 windows under this file.

**Part B (precision).** 32 charts, one per stock: 24 v2 pattern events drawn at random, plus 8
controls. A control is a day with close > 20-session high and volume >= 1.5x where v2 has no
event within 3 sessions. Each chart ends on that day and marks only that day. The owner answers
算 / 不算 / 看不出來. The two kinds are shuffled and look identical.

- Precision = 算 / (算 + 不算) over the 24 rule events.
- Control acceptance is reported, not judged.
- The v2 context tag (clears / after_decline / inside_big_range) is recorded for each rule
  event, and precision is reported per tag. That decides later whether the tag should become
  a filter again. It does not change this verdict.

## Pass

**v2 passes if recall >= 0.75 and precision >= 0.50**, the same bars as batches 2 and 3.
If it passes, codex reruns the probability study with v2. If it fails, the shortfall is
reported as measured and v2 is not tuned on batch 4.
