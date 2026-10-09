## Context

This change was originally written before two things were settled. First, project
data-ownership: generic data acquisition, conversion, and repair work belongs in the
`shioaji_stock_prices` submodule, which now has its own OpenSpec baseline
(`price-data-pipeline`, `corporate-actions-index`, `adjusted-price-cache`,
`symbol-metadata`, `daily-update-orchestration`) and builds the health-check tool itself
under its own change, `add-data-quality-report`. Second, dashboard v2: the original target
(`data_quality_panel` in `research_lab/dashboard_core.py`, the retired Panel app) has been
superseded by `research_web` (React) + `research_api` (FastAPI, port 8503).

This change is now scoped to what only Stock can own: reading the submodule's report
artifact for display, and computing a backtest-window-scoped partial-gap warning (which
needs the requested date range — information the submodule's standalone health check does
not have).

## Goals / Non-Goals

**Goals:**

- Surface the submodule's `data_quality_report.json` in dashboard v2 without duplicating its
  scanning logic.
- Distinguish "fully missing symbol" (already handled via `missing_symbols`) from "partially
  incomplete symbol within the requested backtest window" (new, `partial_data_symbols`).
- Keep Stock decoupled from the submodule's internals: read one JSON artifact by contract,
  nothing more.

**Non-Goals:**

- No health-check scanning logic in this repo — that is the submodule's `add-data-quality-report`.
- No automatic backfill or repair — repair is a submodule-owned, explicit re-fetch action.
- No hard failure of backtests on data gaps — visibility, not enforcement.

## Decisions

**1. `research_api` reads the report file directly; no cross-repo API call.**
`shioaji_stock_prices` is a git submodule checked out alongside this repo, so
`research_api` can read `shioaji_stock_prices/data/data_quality_report.json` from the
filesystem the same way `DataLoader._resolve_corporate_action_db` already probes candidate
paths for `corporate_actions.sqlite` (`StockProject/engine/data_loader.py:241`). This avoids
inventing a network contract between the two projects.

**2. `partial_data_symbols` is computed independently from the report file.**
The report file only knows about the trading-day calendar in general; it has no concept of
"the date range this particular backtest requested." The engine already has that range and
already loads each symbol's trading dates, so it computes the partial-gap warning itself
from data already in memory rather than depending on the submodule artifact's freshness or
schema for a correctness-sensitive backtest signal. The report file remains purely a
dashboard-facing completeness view.

**3. `partial_data_symbols` is a new, separate warning list from `missing_symbols`.**
Keeping them separate lets the dashboard and any consumer distinguish "we have nothing for
this symbol" from "we have most of it but should be careful," which need different visual
treatment and different researcher responses.

## Risks / Trade-offs

- [Risk] The dashboard panel shows stale data if the submodule's daily refresh (which now
  includes the health check as its fifth step) hasn't run recently → Mitigation: the report
  includes a generated-at timestamp; the panel surfaces it so staleness is visible rather
  than assumed.
- [Risk] `research_api`'s path-probing for the report file could silently return nothing if
  the submodule's data directory layout changes → Mitigation: mirror the existing
  multi-candidate probing pattern already proven for `corporate_actions.sqlite`, and treat
  "not found" as the neutral state, not an error.

## Baseline Spec Rewrite Note

`openspec/specs/price-data-pipeline/spec.md`'s Purpose and Non-Goals prose (not just its
requirements) describe producer behavior that no longer belongs to Stock. When this
change's `price-data-pipeline` delta is synced or archived, rewrite Purpose to describe
Stock's consumption contract (reads `{code}_day.csv`, `corporate_actions.sqlite`,
`price_daily.parquet` as artifacts produced elsewhere) and drop the Non-Goals bullets that
were really just describing gaps in the old producer scope.

## Migration Plan

- Purely additive: new endpoint, new panel, new warning category with a default threshold
  that must be explicitly exceeded to trigger. Existing summaries without the new warning
  category remain valid (`partial_data_symbols` defaults to empty).
- Rollback: remove the endpoint and panel wiring; the `partial_data_symbols` warning can be
  disabled independently since it does not depend on the submodule's report file.
