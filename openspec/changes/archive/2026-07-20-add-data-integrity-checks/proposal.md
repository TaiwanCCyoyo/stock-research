## Why

`DataLoader.get_stock_data()` already reports a symbol with no local data at all via
`missing_symbols`, but a symbol that has data merely missing some trading days within a
requested backtest window produces no warning at all — the backtest just runs on whatever
rows exist, with no signal that the result might reflect an incomplete local dataset rather
than real market behavior. Separately, a researcher has no way to see local data
completeness at all: no report exists, and no dashboard surface shows one.

Per project data-ownership rules, all producer-side work (health-check scanning, silent
failure fixes, targeted re-fetch) belongs in the `shioaji_stock_prices` submodule, which now
has its own OpenSpec baseline and is building this itself as
`add-data-quality-report` (see that change's proposal for the `data_quality_report.json`
artifact contract). This change is Stock's consumer-side counterpart: read that artifact,
show it in dashboard v2, and add the backtest-runtime warning that only Stock's engine can
compute (it needs the requested backtest window, which the submodule does not know about).

## What Changes

- Add a read-only `GET /data-quality` endpoint to `research_api` that reads
  `shioaji_stock_prices/data/data_quality_report.json` (probing candidate paths the same way
  `DataLoader._resolve_corporate_action_db` already does for `corporate_actions.sqlite`) and
  returns its contents, or a neutral "not yet checked" response when the file does not exist.
- Add a data-quality panel to `research_web`: missing symbols, symbols with partial
  trading-day gaps, and flagged corporate-action mismatches from the report; a neutral empty
  state when no report exists yet.
- Add a "partial gap within range" warning distinct from the existing "symbol entirely
  missing" (`missing_symbols`) warning: when a requested symbol has data but is missing more
  than a configurable threshold of trading days within the backtest window, add it to a new
  `partial_data_symbols` warning list in `summary.json`. This is computed directly from
  loaded data (the union of trading dates already read by the engine), independent of the
  submodule's report file, since only the engine knows the requested backtest window.

## Capabilities

### New Capabilities

- None. (The `data-integrity-checks` capability proposed earlier now lives in the
  `shioaji_stock_prices` submodule as `data-quality-report`; see that repo's
  `add-data-quality-report` change.)

### Modified Capabilities

- `research-api`: gains a read-only `GET /data-quality` endpoint.
- `research-dashboard-v2`: gains a data-quality panel fed by the new endpoint.
- `backtest-runtime`: summary warnings gain a `partial_data_symbols` category distinct from
  fully-missing symbols.
- `price-data-pipeline` (Stock's own baseline spec, not the submodule's): rewritten to
  describe only the artifact contracts Stock consumes (file paths, schemas, degrade-without-
  crashing behavior), since the producer behavior itself now lives in the submodule's own
  baseline. See this change's `price-data-pipeline` spec delta.

## Non-Goals

- No automatic repair — repair (targeted re-fetch) is submodule-owned and out of scope here.
- No change to corporate-action adjustment math (see `expand-corporate-action-adjustments`).
- Does not hard-fail backtests on incomplete data — research must remain usable with
  imperfect data; this only makes the imperfection visible.
- Does not duplicate the submodule's health-check scanning logic — Stock only reads the
  artifact the submodule produces.

## Impact

- New endpoint: `research_api/main.py` `GET /data-quality`.
- New component: `research_web/src/components/DataQualityPanel.tsx` (or equivalent).
- `StockProject/backtest_cli.py` / `StockProject/engine/data_loader.py`: new
  `partial_data_symbols` warning category.
- `openspec/specs/price-data-pipeline/spec.md`: rewritten as a consumer contract (see
  this change's spec delta).
- Depends on: `shioaji_stock_prices`'s `add-data-quality-report` change producing
  `data/data_quality_report.json` before the dashboard panel has anything to show (the
  endpoint and panel work correctly with the neutral "not yet checked" state either way).
