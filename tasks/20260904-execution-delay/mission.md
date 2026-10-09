# Mission — does the strategy survive acting on a three-day-old ranking?

Pre-registered 2026-09-04, before any cell was run.

## 0. The question, and why it is the owner's question rather than a robustness nicety

The owner's constraint is behavioural: _I will sometimes be away, and I will not sit at the screen
every day._ `20260903-entry-window` answered the price half of that on the train window — a +150%
runaway offers a median of **67 entry days across a 168-day span**, no such name has a window short
enough to be swallowed by a twenty-day absence, and delaying entry three trading days still leaves
**0.98** of the available move at the median and **0.90** at the lower quartile.

That measurement used prices only. It deliberately refused to conclude anything about a strategy,
because a delay also changes which names are still on the list, which slot is free, and what the
account can fund. **This card asks the engine.**

A pass makes "you do not have to trade on the day" a property of the strategy rather than a hope.
A fail is equally useful and would say the entry-window result is a fact about prices that the book
cannot exploit — in which case the honest report is that this strategy family requires daily
execution, and the owner should know that before relying on it.

## 1. Frozen configuration — one axis, and it is not the exit

Every cell is `20260826-runner-retention`'s winning cell `rank30` with a single substitution.

- universe `rotation_pit`, point-in-time, every `symbol_meta.is_etf = 1` code removed before
  ranking, so normal-market 0050 exposure is exactly zero;
- score is equal-weight `r_ret_20 + r_ret_60` with the CRC32 tie-break;
- ten positions, entry rank 10, `rank >= 30` exit after a 20-bar minimum hold;
- entry budget is a fixed tenth of _initial_ capital, unchanged — sizing is a known defect
  (`20260826-runner-retention` §4.2) and holding it fixed is what keeps this card about the delay;
- shared cash, TWD 10,000,000, engine fee and tax;
- execution is the standing engine convention: rank on date `t`'s close, fill at date `t`'s close.

**That last line is an optimistic convention and I am not fixing it here.** Codex established
(`20260828-rank25-next-open-reality`) that an exact whole-market closing rank cannot be known
before receiving that same closing fill. Changing execution realism _and_ delay in one card would
make a failure unattributable. The direction of the resulting bias is stated and is conservative:
the `lag0` baseline captures value that is not actually obtainable, so measuring `lag3` against it
**overstates** the cost of delay relative to an attainable baseline. A delay that looks cheap here
is cheaper still against a realistic one.

## 2. The five cells

```text
lag0   act on today's ranking          -- the standing baseline, must reproduce the anchor
lag1   act on yesterday's ranking
lag2   act on the ranking from two ranking dates ago
lag3   act on the ranking from three ranking dates ago   -- the primary cell
lag5   act on the ranking from five ranking dates ago
```

`signal_lag` shifts the ranking table and nothing else; `on_bar` is inherited unchanged from V5.
**The lag applies to exits as well as entries**, because an owner who is away cannot sell either.
Lagging only entries would measure a strategy nobody can run.

There is no sweep over `top_k`, exit rank, minimum hold, weights, universe or sizing. Five cells,
one axis, ordered.

## 3. Train first; the holdout stays sealed unless the train roots pass

Train is 2019-01-02..2023-12-31. Holdout is 2024-01-01..2026-08-14 and **is not read unless
`lag3` passes every train gate in section 5**. This is the practice adopted in
`20260903-entry-window` and taken from codex, whose cards open the holdout only on a confirmed
nomination.

## 4. What "cost of delay" means here

The headline quantity is `pool_share` at the +150% threshold: of all the return on offer across
that window's runaway population, the share this cell actually captured. `20260826-runner-retention`
established it as the metric with discriminating power — capture rate saturates near 1.0 and
participation trades against it, while pool share moves.

The runaway population is unchanged from that card: threshold-defined, anchored on first surfacing
in the top ten, and **identical across all five cells**, so only the numerator moves.

## 5. Frozen train gates

All against `lag0` in the same window, on the +150% population, using full stored floats.

1. **Pool share.** `lag3` retains at least **0.90** of `lag0`'s pool share. The floor is the lower
   quartile of the price-only delay-3 retention measured in `20260903-entry-window`, chosen there
   before this card existed and not tuned to this card's output.
2. **Capture rate.** `lag3` retains at least 0.90 of `lag0`'s capture rate.
3. **Account.** `lag3`'s return is positive, and its maximum drawdown is no more than 5 percentage
   points worse than `lag0`'s.
4. **Turnover does not rise.** `lag3`'s turnover per slot per year is no higher than `lag0`'s and
   below 12. A delay that improved capture by trading more would not be the finding claimed.
5. **Plateau.** Rules 1-4 hold for **three contiguous lags** including `lag3` — that is `{1,2,3}`
   or `{2,3,5}`. A single passing lag surrounded by failures is a coincidence, not a property.
6. **Anchor.** `lag0` reproduces `20260826-runner-retention`'s stored `rank30` cell **trade for
   trade** — same dates, codes, actions, quantities and totals. If the identity remap changes a
   single fill, nothing downstream is measuring the delay.

    **Amendment, 2026-09-04, before any cell was scored.** As first written this gate said "in both
    windows", which contradicts section 3: checking it on the holdout means running a cell there
    and reading its fills. The anchor is a correctness check rather than an evaluation, but the
    distinction is not one a sealed holdout can afford to rely on. **The gate is therefore checked
    on train now, and on the holdout only at the moment the holdout is legitimately opened.** The
    remap is window-independent by construction, so a train-only identity check tests the same
    code path.

7. **Monotone sanity, reported not gated.** Pool share is expected to fall as the lag grows. A
   non-monotone result is not a failure — the entry-window card measured retention above 1.0 at the
   upper quartile, because a dip after first surfacing gives a late entrant a better basis — but a
   _large_ non-monotonicity is a signal the lag is doing something other than delaying, and the
   report must say so rather than pick the best lag.

## 6. What this card may not conclude

**A pass does not license "trade whenever you like".** It licenses a delay of up to the largest
lag on the plateau, under this exact book, this exact exit and this exact sizing, in the train
window. Nothing here tests a delay combined with a wider book, with next-open execution, or with
the stress costs codex applies.

**The named case, 2344, is reported and never gated.** In `20260826-runner-retention` the three
exit arms that looked best on it were all worse overall and one returned -30.9% across the holdout.
Its run also falls in the sealed holdout, so it cannot be train evidence here either.
