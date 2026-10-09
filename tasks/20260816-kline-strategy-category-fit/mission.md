# Mission — Which K-line strategy fits which Taiwan industry group?

## Question

Three K-line-based entries, sourced from public trading literature, run against five
liquidity-equalized Taiwan industry baskets. The question is not "which strategy is
best" but **which entry belongs in which group**, judged on a trade shape this project
cares about: big wins, small losses.

## Candidates

| id               | file                                    | entry                                                                        | exit                                                                        | source shape                           |
| ---------------- | --------------------------------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------- |
| `donchian`       | `candidates/donchian_breakout.py`       | 20-day closing high, above MA60                                              | 10-day low break, or 2×ATR stop                                             | turtle-style channel breakout          |
| `kline_reversal` | `candidates/kline_reversal_pullback.py` | bullish engulfing or hammer, in an MA60 uptrend, after a pullback below MA10 | ratcheting chandelier stop (peak close − 2.5×ATR), floored at entry − 2×ATR | candlestick reversal with trend filter |
| `tw_momentum`    | `candidates/tw_momentum_breakout.py`    | 20日新高 + 量 > 5日均量×2 + 一紅吃三黑 + MA5>MA10>MA20                       | close below MA10, or 2×ATR stop                                             | Taiwan broker's 短線動能突破 screen    |

Each file is self-contained: the CLI loads a strategy by scanning a single module for
a `StrategyBase` subclass, so a shared helper module would risk the loader picking the
wrong class.

## Universes

`universes/*_liquid20.json`, built by `build_universes.py`: per industry category, the
top 20 symbols by median daily turnover (Close × Volume × 1000) over 2019-01-01..2026-08-14,
requiring ≥1750 bars and data through the window end.

| universe                        | industry         | character                       |
| ------------------------------- | ---------------- | ------------------------------- |
| `semiconductor_liquid20`        | 半導體業         | index-leading, highest turnover |
| `computer_peripherals_liquid20` | 電腦及週邊設備業 | AI-server hardware              |
| `electronic_parts_liquid20`     | 電子零組件業     | mid-cap components              |
| `financial_liquid20`            | 金融保險業       | low beta, dividend-heavy        |
| `shipping_liquid20`             | 航運業           | boom-bust cycle                 |

Equal basket size is deliberate. Under `shared` capital, a 200-symbol basket exhausts
cash on early signals and never trades its tail, so any category ranking taken from
unequal baskets would measure basket size instead of signal quality.

## Design decisions

- **Equal-notional sizing.** Every entry buys `position_pct` (10%) of _initial_ capital
  in integer shares, not 1000-share lots. A 2400 TWD semiconductor and a 20 TWD shipping
  name therefore carry the same weight; lot sizing would have made price level the
  dominant variable, and at 10M capital a single 2330 lot is 24% of the account. Integer
  shares match the CLI's own `integer_shares` odd-lot benchmark, and Taiwan has had
  intraday odd-lot trading since 2020-10 (an approximation for 2019-2020).
- **`unconstrained` is the primary lens.** The CLI nulls `return_rate`, drawdown and
  benchmark deltas in that mode by design, leaving expectancy, payoff ratio and profit
  factor — metrics that do not depend on how many positions the account could afford.
  A `shared` pass over the holdout window supplies the realistic return and drawdown,
  and doubles as the check that the category ranking is not cash contention in disguise.
- **Train / holdout split on explicit dates.** Train 2019-01-02..2023-12-31, holdout
  2024-01-01..2026-08-14. Fifteen strategy × category cells means the best cell looks
  good under pure noise, so the holdout number is the headline and an in-sample-only
  win is reported as a non-finding.
- **Warm-up.** Each strategy needs ~62 prior bars before it can signal, and history
  starts empty at the window start, so roughly the first three months of each window
  produce no trades. This is identical across all cells.
- **Benchmark.** `--benchmark-code` defaults to 0050, which has no local day file yet,
  so `benchmark_return_rate` is null and every run carries a benign
  "No benchmark price data" warning. The comparison uses
  `stock_pool_buy_and_hold_return_rate` instead — equal-allocation buy-and-hold on the
  same basket, which is the more direct answer to "should I have just held this group".

## Known limitations

- Symbols must span the whole window, so delisted names are excluded: a survivorship
  tilt, accepted for basket comparability.
- Volume is not adjusted for splits, so a split inflates the volume-surge test on that
  one bar (`tw_momentum` only).
- Entries and exits fill at the same day's close. There is no slippage model beyond the
  broker's fee and transaction tax.
