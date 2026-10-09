# Batch 5 preregistration: acceptance test of rule v3

Written 2026-10-10, before batch 5 is sampled or shown to the owner. The rule under test is
`hhhl_rule_v3.py` with `bigrange.py`, on `adjprice.load` dividend-adjusted prices. Do not edit
these after the owner starts. A change is v4 with a new batch.

**Bars set by the owner before seeing any batch-5 data (2026-10-09): precision >= 0.60 and
recall >= 0.50.** The bars favour "what the rule picks looks like the owner's pattern", because
the rule feeds a probability study.

## What counts as the v3 pattern

- **Primary (decides pass/fail):** `pattern == True and scale == "big_range"`. That is a
  structural breakout, liquid, with no drawn resistance line above the breakout close.
- Secondary, reported only: `scale == "small_range"`. The owner accepted only 1 of 8 of these in
  earlier judgments, but asked that they be kept as a separate event type.
- Development on all seen data: primary recall 26/42 = 62%, precision 29/40 = 72%. Including
  small_range it was 64% and 62%. This is not a test.

## Design (as batches 3-4)

Stocks used in any earlier batch, review, line check or missed-breakout page are excluded.
Part A and Part B use different stocks. Seed 20261011. The candles are dividend-adjusted.

**Part A (recall).** 30 windows of 100 sessions, one per stock, with end positions drawn
uniformly. Candles only, with no volume and no rule marks. The owner marks every upward
breakout.

- Owner positive: a breakout tagged 像, 區間突破, 底部打底 or 漲停急拉後整理.
- Recall = owner positives with a primary v3 event within +-1 trading session (by the stock's
  own session list) / owner positives.
- If there are fewer than 8 owner positives, add 30 more windows under this file.

**Part B (precision).** 38 charts, one per stock: 24 primary v3 events, 6 small_range v3 events,
and 8 controls. A control is a day with close > 20-session high and volume >= 1.5x that has no
v3 event of any kind on that same day. Each chart ends on that day and marks only that day as the
breakout. The three kinds are shuffled and look identical. The owner answers 算 / 不算 / 看不出來.

- Precision = 算 / (算 + 不算) over the 24 primary events.
- The small_range acceptance and the control acceptance are reported, not judged.

## Pass

**v3 passes if precision >= 0.60 and recall >= 0.50.** If it passes, it is handed to codex for
the probability study (v3 handoff), with small_range events as a separate group. If it fails, the
shortfall is reported as measured and v3 is not tuned on batch 5.
