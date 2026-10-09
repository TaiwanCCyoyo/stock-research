# MAE/MFE retrofit for all six K-line archetypes

This measures per-position risk (maximum adverse excursion, MAE, and maximum
favorable excursion, MFE) for all six archetypes studied in this task family,
using `tasks/20260821-2b-entry-decomposition/mae_analysis.py` against the
existing run summaries. No backtest was re-run; the tool reconstructs
positions from each summary's trade log and replays the adjusted bars the
position spanned. See that script's module docstring for the exact position
and price-basis definitions.

Sources (five baskets pooled per strategy, per window):

- `tasks/20260820-kline-archetype-extension/runs/train` and `runs/holdout` —
  S4 VCP, S5 Darvas, S6 RSI-2 (generated 2026-08-20)
- `tasks/20260820-kline-archetype-extension/runs/prior_refresh/train` and
  `prior_refresh/holdout` — S1 Donchian, S2 candle reversal, S3 momentum,
  re-run on the current data vintage (generated 2026-08-21)

`generated_at` sampled from one file in each directory:

| Directory                    | `generated_at`      |
| ---------------------------- | ------------------- |
| `runs/train`                 | 2026-08-20T22:15:18 |
| `runs/holdout`               | 2026-08-20T22:21:34 |
| `runs/prior_refresh/train`   | 2026-08-21T11:15:44 |
| `runs/prior_refresh/holdout` | 2026-08-21T11:16:54 |

`tasks/20260816-kline-strategy-category-fit/runs/` was **not** used: those
summaries predate the 2026-08-17 corporate-action backfill, so their stored
`signal_price` sits on the old adjustment basis while `mae_analysis.py`
replays bars on the current one.

Regenerate with:

```bash
PYTHONIOENCODING=utf-8 uv run python tasks/20260821-2b-entry-decomposition/mae_analysis.py tasks/20260820-kline-archetype-extension/runs/holdout
PYTHONIOENCODING=utf-8 uv run python tasks/20260821-2b-entry-decomposition/mae_analysis.py tasks/20260820-kline-archetype-extension/runs/train
PYTHONIOENCODING=utf-8 uv run python tasks/20260821-2b-entry-decomposition/mae_analysis.py tasks/20260820-kline-archetype-extension/runs/prior_refresh/holdout
PYTHONIOENCODING=utf-8 uv run python tasks/20260821-2b-entry-decomposition/mae_analysis.py tasks/20260820-kline-archetype-extension/runs/prior_refresh/train
```

## Holdout window

| Strategy             | Positions | MAE median | MAE p75 | MAE p90 | MAE worst | MFE median | Hold days (median) |
| -------------------- | --------: | ---------: | ------: | ------: | --------: | ---------: | -----------------: |
| S1 Donchian breakout |     1,087 |      -4.9% |   -7.4% |   -9.8% |    -72.0% |       6.5% |                 22 |
| S2 K-line reversal   |       450 |      -5.1% |   -8.8% |  -12.6% |    -71.3% |       9.0% |                 26 |
| S3 Momentum breakout |       827 |      -4.8% |   -7.1% |   -9.0% |    -73.6% |       4.7% |                 10 |
| S4 VCP               |        70 |      -4.9% |   -7.8% |   -9.9% |    -13.7% |       4.9% |                 24 |
| S5 Darvas box        |       130 |      -7.6% |  -11.2% |  -16.0% |    -44.4% |      15.5% |                 51 |
| S6 RSI-2 reversion   |     3,205 |      -2.2% |   -5.3% |   -9.3% |    -29.4% |       3.0% |                  4 |

## Train window

| Strategy             | Positions | MAE median | MAE p75 | MAE p90 | MAE worst | MFE median | Hold days (median) |
| -------------------- | --------: | ---------: | ------: | ------: | --------: | ---------: | -----------------: |
| S1 Donchian breakout |     2,056 |      -4.1% |   -6.6% |   -8.8% |    -34.4% |       6.7% |                 26 |
| S2 K-line reversal   |       877 |      -4.5% |   -7.7% |  -10.9% |    -29.0% |       6.6% |                 28 |
| S3 Momentum breakout |     1,847 |      -4.0% |   -6.2% |   -8.1% |    -30.4% |       4.4% |                 11 |
| S4 VCP               |       278 |      -4.2% |   -7.3% |   -8.8% |    -15.7% |       6.9% |                 26 |
| S5 Darvas box        |       356 |      -7.0% |   -9.7% |  -13.8% |    -30.3% |      12.1% |                 47 |
| S6 RSI-2 reversion   |     7,622 |      -1.7% |   -4.0% |   -7.5% |    -29.8% |       2.3% |                  4 |

## Position count vs. `closed_trade_count`

`report.md` quotes holdout `closed_trade_count` per strategy in its §7 table
(1,038 / 428 / 811 / 66 / 117 / 3,186 for S1–S6) and quotes the S5 Darvas
train count (332) in prose in §1. Positions differing materially from the
quoted number:

- S1 Donchian breakout, holdout: 1,087 positions vs. 1,038 `closed_trade_count`.
- S2 K-line reversal, holdout: 450 positions vs. 428 `closed_trade_count`.
- S4 VCP, holdout: 70 positions vs. 66 `closed_trade_count`.
- S5 Darvas box, holdout: 130 positions vs. 117 `closed_trade_count`.
- S5 Darvas box, train: 356 positions vs. 332 `closed_trade_count`.
