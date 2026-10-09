# Batch 3 preregistration: final acceptance test of rule v1

Written 2026-10-08, before batch 3 is sampled or shown to the owner. The rule under test is
`hhhl_rule_v1.py` exactly as frozen. It reproduces the development result of 14/16 kept and 8/14
dropped. Do not edit either file after the owner starts. A change is v2 with a new batch.

## Two parts, two fresh stock sets

Stocks used in any earlier batch or review (51 codes plus the 21 reviewed) are excluded. Part A
and Part B use different stocks. Windows come from the atlas-v2 per-stock tables
(2019-01..2026-08). Seed 20261009.

**Part A (does the rule find what the owner sees?)** 30 windows of 100 sessions, one per stock,
with end positions drawn uniformly. Candles only: no volume and no rule marks. The owner marks
every upward breakout and its swing points, as in batch 2.

- Owner positive: a breakout tagged 像, 區間突破, 底部打底 or 漲停急拉後整理.
- Recall = owner positives with a v1 pattern event within +-1 session / owner positives.
- If there are fewer than 8 owner positives, add a further 30 windows under this file.

**Part B (when the rule fires, does the owner agree?)** 32 charts, one per stock: 24 v1 pattern
events drawn at random, plus 8 controls. A control is a day with close > 20-session high and
volume >= 1.5x where v1 finds no pattern. Each chart ends on that day and marks only that day as
the breakout. No swing points, zones or rule reading are shown. The owner answers 算 / 不算 /
看不出來. Rule events and controls are shuffled together and look identical.

- Precision = 算 / (算 + 不算) over the 24 rule events.
- Control acceptance = the same ratio over the 8 controls. It is reported to show whether the
  structure part adds anything beyond a plain new-high-on-volume day.

## Pass

**v1 passes if recall >= 0.75 and precision >= 0.50.** These are the same bars as batch 2.
If v1 passes, it goes to codex for the probability study (6-month 2x rate, with base rates).
If it fails, the shortfall is reported as measured and v1 is not tuned on batch 3.
