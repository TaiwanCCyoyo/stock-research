## Why

Three-major-institution (三大法人：外資/投信/自營商) daily buy/sell data does not exist
anywhere in this project. It is a commonly used research signal for Taiwan equities and the
user wants strategies that can condition on it, but today there is no local fetcher, no
storage, and no engine access point. This change adds the data pipeline only — it does not
add a strategy that uses it, keeping the change reviewable and low-risk to existing
backtests.

This is a lower-priority, later-stage piece of a broader "official-data-as-primary"
direction (see `shioaji_stock_prices`'s `add-official-daily-price-source` change, delivered
2026-08-07): that change built a reusable official-OpenAPI HTTP fetch/retry/backoff helper
(`shp_utils/official_api.py`) this pipeline should consume directly, and a rate-limited
resumable history crawler this pipeline's historical backfill should follow the same
_design_ as (see `design.md` for why it is not a direct code-reuse — its checkpoint shape
is TWSE-price-specific). Price data quality and (future) financial-statement /
industry-trend signals rank ahead of institutional data in priority; this change's data does
not need independently-verified correctness to be useful.

## What Changes

- Add `shioaji_stock_prices/fetch_institutional.py`: fetches daily three-major-institution
  buy/sell data from TWSE's dated T86 report
  (`www.twse.com.tw/rwd/zh/fund/T86?date=YYYYMMDD&selectType=ALLBUT0999`) for listed stocks
  and TPEx's dated equivalent
  (`www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date=YYYY/MM/DD`) for OTC
  stocks — confirmed by direct probing, see `docs/institutional-sources.md` in the submodule
  (task 1.3) — following the same idempotent-upsert, retry/backoff, and raw-range-tracking
  pattern already proven in `fetch_corporate_actions.py`.
- Store results in a new local `shioaji_stock_prices/data/institutional.sqlite`, table
  `institutional_daily` keyed by `(date, code)`, with columns for foreign/trust/dealer net
  buy-sell shares (and gross buy/sell shares per category).
- Add a backfill entry point for historical range fetch, and wire a daily incremental fetch
  into `run_daily.py`'s existing pipeline sequence.
- Add an **opt-in** join in `StockProject/engine/data_loader.py` that attaches
  institutional columns to a bar snapshot only when explicitly requested by the caller;
  default (unrequested) behavior is completely unchanged.
- Expose the joined columns to `StrategyBase.on_bar()` snapshots so a future strategy can
  read them, without requiring any existing strategy to change.

## Capabilities

### New Capabilities

- `institutional-data-pipeline`: fetch, storage, and opt-in engine access contract for
  three-major-institution daily data.

### Modified Capabilities

(none — the engine join is additive and opt-in, so it does not change any existing
`backtest-runtime` requirement's default behavior)

## Non-Goals

- No strategy that uses institutional data — this change is data plumbing only.
- No real-time or intraday institutional data — daily aggregates only, matching the
  official TWSE/TPEx publication cadence.
- No change to default backtest behavior: opting in is required to see any effect, and no
  existing task summary should change as a result of this change.
- Docker-backed execution is not required for local validation; note any skipped Docker
  checks in completion notes.

## Impact

- **Sequencing dependency**: the `add-official-daily-price-source` change's shared
  official-OpenAPI fetch helper and rate-limited resumable history crawler have now landed in
  the `shioaji_stock_prices` submodule (archived 2026-08-07), unblocking this change.
  `fetch_institutional.py`'s T86/TPEx fetch MUST consume `shp_utils/official_api.py`'s
  fetch/retry/backoff helpers directly; its historical-backfill entry point MUST follow the
  same throttle/checkpoint/backoff design as `backfill_official_history.py` without importing
  it, since T86's whole-market-per-day shape needs a `(market, date)` checkpoint unit instead
  of that module's per-symbol `(code, year_month)` unit — see `design.md`'s Context section.
- New file: `shioaji_stock_prices/fetch_institutional.py`.
- New local database: `shioaji_stock_prices/data/institutional.sqlite`.
- `shioaji_stock_prices/run_daily.py`: add institutional fetch step.
- `StockProject/engine/data_loader.py`: new opt-in join method.
- `StockProject/engine/strategy_base.py`: snapshot fields available when opted in.
- Tests: fetcher idempotency, join correctness, and a regression test proving default
  (non-opted-in) backtest output is unchanged.
