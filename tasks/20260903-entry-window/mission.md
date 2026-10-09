# Mission — how many days wide is the entry window on a stock that turns out to run?

Pre-registered 2026-09-03, before any cell was computed.

## 0. Why this is a measurement card and not a strategy card

The owner's constraint is not "trade less". It is: _if I am away, or I do not act on the exact
day, does the strategy still work?_ Codex formalised that as a signal-execution rate `a` and
modelled the realised hit rate as `a x p`, which assumes an entry chance is a single coin flip
that is gone once missed.

That assumption is the thing to test, and the standing evidence already contradicts it. In
`20260826-runner-retention` the owner's own named case, 2344, sat inside the score's top thirty for
**74 trading days** and its top ten for **50** while the move was still ahead. If that is typical,
missing a day costs a slice of one move, not the move; if it is not typical, the whole strategy
family is fragile in a way no turnover ceiling would reveal.

**This card therefore nominates nothing, gates nothing, and selects nothing.** It measures a
property of the opportunity set. Its output is the input to a later card's threshold, which is
exactly why the threshold cannot be chosen here — see section 5.

## 1. Frozen inputs

- Price grid: `book.build_price_grid()`, total-return adjusted closes, as used by every card in
  this line.
- Features: `tasks/20260824-ranking-horizon/features_v2.parquet`, columns `Date`, `Code`,
  `eligible`, `r_ret_20`, `r_ret_60`.
- Score: equal-weight `r_ret_20 + r_ret_60`, CRC32 tie-break, unchanged.
- Universe: `eligible` rows only, every `symbol_meta.is_etf = 1` code removed before ranking,
  matching `20260826-runner-retention`.
- Window: **train only, 2019-01-02..2023-12-31.**

## 2. The holdout stays sealed, and that is a deliberate change of practice

Every prior card in my line opened the holdout — ten of ten. Codex opens it only on a confirmed
nomination, and is right. A descriptive measurement looks harmless, but this one exists to set a
numeric threshold for a later acceptance gate; measuring it across both windows would be choosing
that gate with the holdout in hand. **2024-01-01..2026-08-14 is not read by this card.**

## 3. Population, unchanged from the prior card so the two are comparable

A name belongs to the runaway population at threshold `t` if, within 250 trading days of the first
bar on which it entered the score's **top ten** in the train window, its adjusted close reached at
least `t` above its close on that first bar. Thresholds reported: 0.50, 1.00, 1.50, 2.00.

The population is anchored on **top ten** at every threshold and for every measurement below, so
widening the measurement's K cannot move the denominator. This is the same threshold-defined,
arm-independent construction as `20260826-runner-retention`; gate 1 asserts it reproduces that
card's count exactly.

Two properties are stated here so they are not misread later. The population is **conditional on
the move having happened** — it describes the opportunity that existed, not a set anyone could have
identified in advance. And the window's right edge truncates late runs, which shortens measured
windows rather than flattering them.

## 4. The three measurements

For each name in the population: `first_row` is its first top-ten bar, `peak_row` the highest
close in `[first_row, min(first_row + 250, window_end)]`, and `available = close[peak_row] /
close[first_row] - 1`.

**4.1 Window width.** The number of trading days in `[first_row, peak_row]` on which the name is
inside the score's top K, for K in {10, 30}, plus the **span** — last such day minus first, plus
one. Reported as a distribution (min, p10, p25, median, p75, max), never as a mean alone.

**4.2 Delay cost.** For d in {0, 1, 2, 3, 5, 10, 20, 40} trading days, `retained(d) =
(close[peak_row] / close[entry_row(d)] - 1) / available`, under two entry rules:

- `calendar`: `entry_row = first_row + d` — models an absence. Entry happens whether or not the
  name is in the top K that day, because a returning owner can act on a name they already know.
- `signal`: `entry_row` is the (d+1)-th day at or after `first_row` on which the name is in the
  top K — models only ever acting on a live signal.

`retained` above 1.0 is real (the price dipped after first surfacing, so a late entrant got a
better basis) and is reported, not clipped. Entries at or after `peak_row` retain 0. Medians and
quartiles across the population, per threshold; means are not the headline because one 20x name
would carry them.

**4.3 Total-miss exposure.** A contiguous absence of B trading days can only cost a name entirely
if that name's whole top-K span fits inside B. Reported: the share of the population whose top-K
span is <= B, for B in {5, 10, 20}. This is the direct form of "I went away and missed it".

## 5. What would make this card wrong, and what it is not allowed to conclude

The measurement is correct if the verification gates pass. It is still _uninformative_ if the
population is small enough that a percentile is noise, so the population count is reported beside
every distribution and any threshold with fewer than 20 names is reported but marked not usable.

**This card may not conclude that a delay is free.** It can only say how much of the available
move survives a delay of d days on names that ran. Whether a strategy delayed by d days still
earns that return after costs, slot competition and the entries it displaces is an engine
question, and belongs to a later card with its own arms and its own gates.

## 6. Verification gates, all asserted before the result is read

1. **Anchor.** The threshold-1.50 train population count and its member set equal
   `20260826-runner-retention`'s, recomputed here from the same inputs.
2. **Definitional.** `retained(0)` is exactly 1.0 for every name under `calendar`, and
   `available` equals `retention_rules.available_return` over the same span.
3. **Mutation.** Shifting the top-K table forward by one bar must change at least one reported
   window width. A measurement that reads a table it does not depend on would pass everything else.
4. **Containment.** Every top-K day counted lies in `[first_row, peak_row]`, and `span >= count`
   for every name at every K.
5. **K monotonicity.** Each name's top-30 day count is greater than or equal to its top-10 count,
   for every name. A violation means the two tables disagree about the same score.
6. **Named case.** 2344's top-30 and top-10 counts are reported. Reported, never gated — the three
   exit arms that looked best on 2344 in the prior card were all worse overall and one returned
   -30.9%, so this card repeats that rule rather than relearning it.
