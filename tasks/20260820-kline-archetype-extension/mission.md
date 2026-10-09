# Mission -- Do other K-line archetypes fill the holes the breakout study left?

## Why this exists

`tasks/20260816-kline-strategy-category-fit` ran three momentum/breakout entries
(Donchian channel, candlestick reversal, Taiwan volume-surge momentum) across five
liquidity-equalized industry baskets. Two of its conclusions define this task:

1. **Financials are dead ground for breakouts.** All three candidates landed at or
   below zero expectancy on `financial_liquid20`. The report's own next step was
   "try mean reversion or seasonality instead" -- untested.
2. **Signal quality is real but does not beat buy-and-hold.** Donchian reached ~8%
   per entry with a 4.6-5.2 payoff ratio in the electronics groups, yet lost to
   equal-weight buy-and-hold on return/drawdown in both windows. Only one of fifteen
   cells (volume momentum x shipping) survived both windows.

So the open question is not "tune those three". It is **whether a structurally
different K-line archetype changes either answer**. This task adds three archetypes
that share no mechanism with the original three, and runs them through the identical
protocol so the numbers sit next to the old ones without translation.

## Candidates

Each is sourced from published trading literature and reduced to rules computable
from daily OHLCV alone. No subjective judgement, no intraday data.

| id               | file                                     | archetype                          | entry                                                                              | exit / stop                                                                              |
| ---------------- | ---------------------------------------- | ---------------------------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `vcp`            | `candidates/vcp_contraction_breakout.py` | volatility contraction (Minervini) | base of shrinking pullbacks + volume dry-up, then close breaks the pivot on volume | tight initial stop under the last contraction (<=7%), then a wide 3xATR chandelier trail |
| `darvas`         | `candidates/darvas_box_breakout.py`      | box ratchet (Darvas)               | close breaks a confirmed box top on >=1.5x average volume                          | stop at the box bottom, ratcheted up as each new box confirms                            |
| `rsi2_reversion` | `candidates/rsi2_mean_reversion.py`      | mean reversion (Connors RSI-2)     | RSI(2) below 10 while price is above its long trend MA                             | close above MA5, a 10-bar time stop, or a 2xATR disaster stop                            |

**Why these three and not others.** The existing study covers fixed-lookback channel
breakout, single-bar candlestick reversal, and volume-surge momentum. `vcp` tests
whether _pre-breakout contraction_ is a quality filter that the fixed 20-day channel
misses. `darvas` tests a _structural ratcheting stop_ built from price geometry rather
than an ATR multiple. `rsi2_reversion` is the only non-momentum entry in either task,
and is the direct answer to the financials hole.

Each file is self-contained. The CLI loads a strategy by scanning one module for a
`StrategyBase` subclass, so a shared helper module would risk binding the wrong class;
helper methods are duplicated per file on purpose.

## Protocol -- held identical to the 20260816 study

Changing any of these would silently break comparison with the prior report.

- **Windows.** Train 2019-01-02..2023-12-31, holdout 2024-01-01..2026-08-14.
- **Universes.** The same five `universes/*_liquid20.json` baskets, 20 symbols each.
- **Capital.** 10,000,000 TWD. `unconstrained` is the primary lens (it nulls
  `return_rate` by design, leaving expectancy / payoff / profit factor, which do not
  depend on how many positions the account could afford); `shared` supplies the
  realistic return and drawdown.
- **Sizing.** Equal notional -- 10% of _initial_ capital per entry, integer shares,
  sized off the broker's execution price rather than the adjusted signal price.
- **Benchmark.** `stock_pool_buy_and_hold_return_rate` on the same basket, because
  0050 has no local day file and `benchmark_return_rate` is null for every run.

## Pre-registered acceptance rule

Written before any holdout number was read, because fifteen new cells make the best
cell look good under pure noise.

1. **Primary metric** -- holdout `unconstrained` average full PnL per entry
   (includes dividends and open positions), the same measure as the prior §4.1.
2. **A cell counts as a signal-quality finding** only if train and holdout are both
   positive _and_ the holdout has at least 30 closed trades. Positive in the holdout
   alone is reported as a non-finding, not a result.
3. **A cell beats buy-and-hold** only if its return/|max drawdown| exceeds the same
   basket's equal-weight buy-and-hold in _both_ `train_shared` and `holdout_shared`.
4. **Reported regardless of outcome.** A clean negative on all fifteen cells is the
   expected outcome given the prior study, and is a result.

## Documented deviations from the sources

- **Trend filters are capped at 120 bars.** Minervini's template uses MA50/150/200,
  Connors uses a 200-day filter, and Darvas screened 52-week highs. The engine clips
  every symbol's history at the window start and provides no pre-window warm-up, so a
  200-bar filter would consume roughly a third of the 640-bar holdout window before
  the first signal could fire. Every long filter here is 120 bars instead. This costs
  fidelity to the sources and is the main threat to external validity.
- **Warm-up differs by strategy** (~150 bars for `vcp`, ~125 for `darvas`, ~125 for
  `rsi2_reversion`), unlike the prior study where all three shared ~62. It is still
  identical across the five universes for a given strategy, so the _category_ ranking
  within a strategy is unaffected; cross-strategy trade counts must be read with the
  warm-up in hand.
- **Minervini's relative-strength ranking is dropped.** RS-line percentile is
  cross-sectional against the whole market; the engine feeds one basket at a time and
  has no market-wide RS input. `vcp` substitutes "close within 25% of its 120-bar
  high", which is the proximity half of the trend template but not the ranking half.
- **`rsi2_reversion` is expected to have the wrong trade shape.** Mean reversion pays
  a high win rate for small wins and rare large losses -- the inverse of this
  project's "big wins, small losses" philosophy. It is included to answer whether the
  financials basket is tradable at all, not as a philosophy-aligned candidate, and its
  payoff ratio should be read as a disqualifier rather than a surprise.

## Inherited limitations

These carry over unchanged from the 20260816 study and are not re-litigated here:
survivorship tilt (baskets only hold symbols spanning the whole window), split-unadjusted
volume, close-to-close fills with no slippage model beyond fee and transaction tax, and
a bull-market bias in both windows that structurally favours buy-and-hold.
