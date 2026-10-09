# Nightly Research Report

## Summary

Strategy `TwoBMovingAverageConvergence` ran on `2330, 2308, 2454, 2317, 3711, 2383, 2345, 3017, 3037, 2360, 2382, 2303, 6669, 2357, 3008, 3034, 3231, 2301, 2324, 2352, 2353, 2356` from `2024-01-01` to `latest available local data`.

Strategy params: `{"add_allocation_pct": 0.12, "convergence_pct": 2.0, "exit_window": 10, "initial_allocation_pct": 0.18, "lot_size": 1000, "ma_type": "sma", "partial_sell_pct": 0.5, "reclaim_window": 5, "slow_exit_window": 20, "stop_loss_pct": 8.0, "swing_lookback": 20, "trend_window": 20, "windows": [5, 10, 20]}`

## Key Metrics

| Metric                           |         Value |
| -------------------------------- | ------------: |
| Final value                      |   913,753.000 |
| Total PnL                        |   -86,247.000 |
| Return rate                      |    -8.624700% |
| Maximum drawdown                 |   -11.974188% |
| Win rate                         |    31.382979% |
| Trade count                      |           302 |
| Buy-and-hold return rate         |    88.334074% |
| Excess return rate               | -96.958774 pp |
| Odd-lot buy-and-hold return rate |    87.850087% |
| Odd-lot excess return rate       | -96.474787 pp |

## Stock Ranking

Rank metric: `total_pnl` (max)

| Rank | Symbol |  Total PnL |      Max DD | Trades |    Win Rate | Key Signals                                                                  |
| ---: | ------ | ---------: | ----------: | -----: | ----------: | ---------------------------------------------------------------------------- |
|    1 | 3711   | 14,402.000 |  -7.817590% |      8 |  75.000000% | bottom_2b:10, buy:4, ma_convergence:136, sell:4, top_2b:25                   |
|    2 | 2356   |  5,056.000 | -68.276404% |     36 |  36.363636% | bottom_2b:18, buy:14, ma_convergence:219, partial_sell:8, sell:14, top_2b:17 |
|    3 | 3037   |  3,339.000 |   0.000000% |      2 | 100.000000% | bottom_2b:17, buy:1, ma_convergence:116, sell:1, top_2b:27                   |
|    4 | 2317   |  1,778.000 |  -1.449275% |      4 |  50.000000% | bottom_2b:18, buy:2, ma_convergence:116, sell:2, top_2b:25                   |
|    5 | 2308   |      0.000 |   0.000000% |      0 |         n/a | bottom_2b:16, ma_convergence:122, top_2b:27                                  |
|    6 | 2330   |      0.000 |   0.000000% |      0 |         n/a | bottom_2b:11, ma_convergence:153, top_2b:27                                  |
|    7 | 2345   |      0.000 |   0.000000% |      0 |         n/a | bottom_2b:18, ma_convergence:83, top_2b:32                                   |
|    8 | 2357   |      0.000 |   0.000000% |      0 |         n/a | bottom_2b:18, ma_convergence:164, top_2b:25                                  |
|    9 | 2360   |      0.000 |   0.000000% |      0 |         n/a | bottom_2b:17, ma_convergence:72, top_2b:33                                   |
|   10 | 2382   |      0.000 |   0.000000% |      0 |         n/a | bottom_2b:21, ma_convergence:95, top_2b:21                                   |
|   11 | 2383   |      0.000 |   0.000000% |      0 |         n/a | bottom_2b:14, ma_convergence:99, top_2b:32                                   |
|   12 | 2454   |      0.000 |   0.000000% |      0 |         n/a | bottom_2b:13, ma_convergence:152, top_2b:19                                  |
|   13 | 3008   |      0.000 |   0.000000% |      0 |         n/a | bottom_2b:24, ma_convergence:175, top_2b:25                                  |
|   14 | 3017   |      0.000 |   0.000000% |      0 |         n/a | bottom_2b:13, ma_convergence:63, top_2b:24                                   |
|   15 | 3034   |      0.000 |   0.000000% |      0 |         n/a | bottom_2b:23, ma_convergence:248, top_2b:19                                  |

## Signal Event Sample

Total signal events: `4,521`

| Date                | Symbol | Event        |   Price |   Qty | Reason                        |
| ------------------- | ------ | ------------ | ------: | ----: | ----------------------------- |
| 2024-02-02T00:00:00 | 2352   | buy          |  47.500 | 3,000 | ma_convergence_price_strength |
| 2024-02-16T00:00:00 | 2324   | buy          |  36.850 | 4,000 | ma_convergence_price_strength |
| 2024-02-16T00:00:00 | 2353   | buy          |  48.650 | 2,000 | ma_convergence_price_strength |
| 2024-02-19T00:00:00 | 2317   | buy          | 103.000 | 1,000 | ma_convergence_price_strength |
| 2024-02-19T00:00:00 | 2352   | sell         |  47.950 | 3,000 | top_2b_exit                   |
| 2024-02-19T00:00:00 | 2353   | sell         |  47.400 | 2,000 | top_2b_exit                   |
| 2024-02-21T00:00:00 | 2317   | sell         | 103.000 | 1,000 | top_2b_exit                   |
| 2024-02-22T00:00:00 | 2317   | buy          | 103.500 | 1,000 | ma_convergence_price_strength |
| 2024-02-23T00:00:00 | 2324   | partial_sell |  36.200 | 2,000 | ma_break_partial_exit         |
| 2024-02-26T00:00:00 | 2324   | partial_sell |  36.000 | 1,000 | ma_break_partial_exit         |
| 2024-02-29T00:00:00 | 2324   | sell         |  36.500 | 1,000 | top_2b_exit                   |
| 2024-03-01T00:00:00 | 2301   | buy          | 112.500 | 1,000 | ma_convergence_price_strength |
| 2024-03-04T00:00:00 | 2324   | buy          |  38.000 | 3,000 | ma_convergence_price_strength |
| 2024-03-05T00:00:00 | 2301   | sell         | 114.000 | 1,000 | top_2b_exit                   |
| 2024-03-05T00:00:00 | 2324   | sell         |  37.800 | 3,000 | top_2b_exit                   |
| 2024-03-05T00:00:00 | 2352   | buy          |  47.250 | 3,000 | ma_convergence_price_strength |
| 2024-03-05T00:00:00 | 2356   | buy          |  56.500 | 2,000 | ma_convergence_price_strength |
| 2024-03-06T00:00:00 | 2317   | sell         | 106.500 | 1,000 | top_2b_exit                   |
| 2024-03-06T00:00:00 | 2352   | partial_sell |  45.050 | 1,000 | ma_break_partial_exit         |
| 2024-03-07T00:00:00 | 2303   | buy          |  50.200 | 2,000 | ma_convergence_price_strength |
| 2024-03-07T00:00:00 | 2352   | partial_sell |  44.550 | 1,000 | ma_break_partial_exit         |
| 2024-03-07T00:00:00 | 2356   | partial_sell |  55.100 | 1,000 | ma_break_partial_exit         |
| 2024-03-11T00:00:00 | 3231   | buy          | 121.000 | 1,000 | ma_convergence_price_strength |
| 2024-03-11T00:00:00 | 2352   | sell         |  43.250 | 1,000 | stop_loss_exit                |
| 2024-03-12T00:00:00 | 2324   | buy          |  37.200 | 3,000 | ma_convergence_price_strength |

## Per-Symbol Metrics

| Symbol |   Total PnL | Max Drawdown | Trades |    Win Rate | Final Qty |
| ------ | ----------: | -----------: | -----: | ----------: | --------: |
| 2301   | -10,006.000 |   -8.108108% |     28 |  35.714286% |         0 |
| 2303   | -27,289.000 |  -69.324222% |     48 |  32.258065% |         0 |
| 2308   |       0.000 |    0.000000% |      0 |         n/a |         0 |
| 2317   |   1,778.000 |   -1.449275% |      4 |  50.000000% |         0 |
| 2324   | -32,131.000 |  -80.332779% |     63 |  20.930233% |     4,000 |
| 2330   |       0.000 |    0.000000% |      0 |         n/a |         0 |
| 2345   |       0.000 |    0.000000% |      0 |         n/a |         0 |
| 2352   | -12,609.000 |  -75.651769% |     50 |  22.857143% |         0 |
| 2353   | -27,289.000 |  -76.692913% |     38 |  25.000000% |         0 |
| 2356   |   5,056.000 |  -68.276404% |     36 |  36.363636% |         0 |
| 2357   |       0.000 |    0.000000% |      0 |         n/a |         0 |
| 2360   |       0.000 |    0.000000% |      0 |         n/a |         0 |
| 2382   |       0.000 |    0.000000% |      0 |         n/a |         0 |
| 2383   |       0.000 |    0.000000% |      0 |         n/a |         0 |
| 2454   |       0.000 |    0.000000% |      0 |         n/a |         0 |
| 3008   |       0.000 |    0.000000% |      0 |         n/a |         0 |
| 3017   |       0.000 |    0.000000% |      0 |         n/a |         0 |
| 3034   |       0.000 |    0.000000% |      0 |         n/a |         0 |
| 3037   |   3,339.000 |    0.000000% |      2 | 100.000000% |         0 |
| 3231   |  -1,498.000 |   -7.048458% |     25 |  66.666667% |     1,000 |
| 3711   |  14,402.000 |   -7.817590% |      8 |  75.000000% |         0 |
| 6669   |       0.000 |    0.000000% |      0 |         n/a |         0 |

## Benchmark Notes

- Method: Equal cash allocation by symbol, first available close, broker fee, dividends, no tax until liquidation. Fractional benchmark is for comparability; integer-share benchmark approximates Taiwan odd-lot buy-and-hold accessibility but does not model intraday odd-lot execution quality or same-day trading restrictions.
- Benchmark allows fractional shares for comparability.
- It does not model Taiwan odd-lot intraday restrictions or day-trading constraints.
- It is not a trade execution model.
- Odd-lot benchmark: Benchmark buys whole shares to approximate Taiwan odd-lot buy-and-hold accessibility.
- Odd-lot benchmark: It does not model intraday odd-lot execution quality or same-day trading restrictions.
- Odd-lot benchmark: It is not a trade execution model.

## Interpretation Checklist

- Compare the strategy return against the benchmark before treating the result as useful.
- Check whether performance comes from one symbol or is distributed across the pool.
- Review stock rankings and signal events before deciding whether the 2B add logic helped.
- Treat this report as research output, not an investment recommendation.

## Next Step

Codex should review this mechanical draft, inspect the run artifacts, and add strategy-specific interpretation before publishing to Notion.
