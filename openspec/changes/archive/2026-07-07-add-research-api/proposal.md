## Why

The user wants a modern, fast, directly-operable dashboard (React + lightweight-charts)
to eventually replace Panel, but building the frontend directly against ad hoc file reads
would duplicate logic already correctly implemented in `research_lab/dashboard_core.py` and
`scripts/stock_research_query.py`. This change adds a thin, read-only FastAPI backend that
exposes exactly the same task artifacts through HTTP endpoints, so `add-dashboard-v2` has a
stable API to build against and both the old Panel dashboard and the new frontend can read
from the same underlying data during the transition period.

## What Changes

- Add a FastAPI app (`research_api/` or similar) exposing:
    - `GET /tasks` — lightweight task index (reusing `update-price-loading-performance`'s
      lazy task-index work).
    - `GET /tasks/{task_id}` — full task bundle (summary, comparison, rankings, signal
      events), reusing `load_task_bundle`.
    - `GET /tasks/{task_id}/prices?codes=...` — per-symbol OHLCV plus corporate-action
      markers, reusing `DataLoader.load_symbols` from `update-price-loading-performance`.
    - `GET /tasks/{task_id}/trades` and `GET /tasks/{task_id}/trades/{trade_id}` — wrapping
      `list_task_trades`/`inspect_task_trade` from `scripts/stock_research_query.py`.
- The API is a pure read-only view over existing artifacts: it MUST NOT introduce a new
  artifact format, recompute metrics, or duplicate logic already in `dashboard_core.py`/
  `stock_research_query.py` — it calls into those modules directly.
- No authentication is added — this is a localhost-only research tool, matching the
  existing Panel dashboard's trust model.

## Capabilities

### New Capabilities

- `research-api`: the read-only HTTP contract over existing task artifacts.

### Modified Capabilities

(none — this is a new, additive read surface; it changes no existing behavior contract)

## Non-Goals

- No write endpoints in this change — triggering backtests from the API is
  `add-dashboard-v2`'s later phase (6c), built on top of this read API.
- No new artifact schema — every response is a direct projection of files already produced
  by the backtest runtime and trade-query tooling.
- No replacement of the Panel dashboard yet — Panel keeps running unchanged until
  `add-dashboard-v2` reaches parity.
- Docker-backed execution is not required for local validation; note any skipped Docker
  checks in completion notes.

## Impact

- New service directory (e.g. `research_api/main.py` plus route modules).
- No changes to `StockProject/engine/`, `StockProject/backtest_cli.py`, or existing task
  artifact formats.
- Reuses `research_lab/dashboard_core.py`'s data-loading functions and
  `scripts/stock_research_query.py`'s query functions directly (no duplication).
- Depends on `update-price-loading-performance` for `load_symbols`/lazy task index; should
  be sequenced after that change lands.
