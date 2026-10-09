# Parity checklist: research-dashboard spec → dashboard v2 (research_web)

Maps every scenario in `openspec/specs/research-dashboard/spec.md` to its equivalent in
the new frontend. Verified 2026-07-07 against real local data at http://127.0.0.1:8503/.

## Requirement: Dashboard builds from local task artifacts

| Scenario                                      | v2 equivalent                                                                                                                      | Status                                       |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| Build static dashboard                        | Unchanged — `scripts/build_research_dashboard.py` only imports `research_lab/dashboard_core.py` (kept), not the retired Panel app. | ✅ unaffected                                |
| Serve interactive dashboard                   | Artifact data flows through `research_api` endpoints; no static relative links.                                                    | ✅ verified                                  |
| Discover tasks without eager full-bundle load | `GET /tasks` uses `discover_task_index()` (dir listing only); bundle fetched on selection.                                         | ✅ verified (API test forbids summary parse) |
| Loading state while K-line loads              | Spinner overlay on the chart host during price fetches.                                                                            | ✅ verified                                  |

## Requirement: User-facing language

| Scenario             | v2 equivalent                                                                                              | Status      |
| -------------------- | ---------------------------------------------------------------------------------------------------------- | ----------- |
| Render trade table   | `dateOnly()` strips time; prices/qty/totals via `fmtNum`; actions as zh badges (買進/加碼/賣出/配息/分割). | ✅ verified |
| Render signal labels | `translateSignal()` maps known codes (ma_convergence → 均線糾結 etc.); unknown codes pass through.         | ✅ verified |

## Requirement: Strategy health diagnostics

| Scenario                 | v2 equivalent                                                                                                                                                                                                       | Status                    |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| Health metrics available | `StrategyHealth` panel renders payoff/expectancy/profit factor/Calmar/avg & largest win-loss/verdict from `bundle.health` (computed by `dashboard_core.strategy_health_rows` — same tested pure function as Panel). | ✅ verified               |
| Passive strategy         | Panel hidden when `closed_trade_count == 0`; win rate shows "—".                                                                                                                                                    | ✅ verified (sample task) |
| Diagnosis report exists  | 策略診斷 tab renders text; empty content → explanatory empty state (panel content omitted).                                                                                                                         | ✅ verified               |

## Requirement: Trade verification context

| Scenario                       | v2 equivalent                                                                                                                                         | Status             |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| Matching context               | Drilldown renders whatever `inspect_task_trade` returns for the strategy (price_context/cash_context/signal_events) — strategy-agnostic pass-through. | ✅ verified        |
| Optional technical fields      | `DetailRows` renders present scalar fields; missing → omitted; empty → 無資料.                                                                        | ✅ verified        |
| Existing verification examples | Same `inspect_task_trade` backend as Panel; contract strategy-agnostic.                                                                               | ✅ by construction |

## Requirement: Capital-mode comparison

| Scenario                         | v2 equivalent                                  | Status                     |
| -------------------------------- | ---------------------------------------------- | -------------------------- |
| Render comparison panel          | 資金池比較 tab, all required metrics per mode. | ✅ verified                |
| Omit panel for single-mode runs  | Friendly empty state, no errors.               | ✅ verified (sample task)  |
| Flag contention-affected symbols | 受影響 badge + per-symbol PnL delta column.    | ✅ verified (7/22 flagged) |

## Requirement: Testability pattern

| Scenario                    | v2 equivalent                                                                                                                | Status |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------ |
| Pure data function testable | Health/judgments come from `dashboard_core`'s pure functions via the API (no duplication); frontend logic in `lib/` modules. | ✅     |
| Panel builder returns None  | v2 renders empty states; API returns `judgments: null` without comparison (tested).                                          | ✅     |

## Requirement: Per-pool sub-tabs

| Scenario                          | v2 equivalent                                                                                                                                                                                       | Status      |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| Render per-pool tabs              | 比較總覽 + shared/per_stock/unconstrained sub-tabs; each with pool metrics, verdict, equity+drawdown chart (from `portfolio.equity_curve`), debug block incl. `cash_blocked_entry_count`, warnings. | ✅ verified |
| max_drawdown populated            | Overview falls back to per-mode summaries when comparison.json value is null.                                                                                                                       | ✅ verified |
| Unconstrained null returns marked | Pool verdict text explains diagnostics-only nulls; overview shows "—".                                                                                                                              | ✅ verified |

## Requirement: Per-pool and cross-pool judgments

| Scenario                | v2 equivalent                                                                               | Status      |
| ----------------------- | ------------------------------------------------------------------------------------------- | ----------- |
| Cross-pool judgment     | `bundle.judgments.comparative` from `capital_mode_comparative_verdict` shown atop 比較總覽. | ✅ verified |
| Judgment functions pure | Same pure Python functions, exposed via API (tested in test_research_api.py).               | ✅          |

## Requirement: Help view, no raw artifact links

| Scenario                   | v2 equivalent                                                                                     | Status             |
| -------------------------- | ------------------------------------------------------------------------------------------------- | ------------------ |
| Help view                  | 使用說明 tab: artifact locations, re-run CLI incl. `--capital-mode all`, service launch commands. | ✅ verified        |
| Raw artifact links removed | v2 never rendered raw html/json links.                                                            | ✅ by construction |

## Known deferred items (blocked on second-track changes, not Panel parity gaps)

- Industry/universe filtering (needs `add-universe-management`).
- Institutional buy/sell pane (needs `add-institutional-data-pipeline`).
- Universe comparison view (needs `add-universe-management`).

Panel never had these either, so they do not block retirement.
