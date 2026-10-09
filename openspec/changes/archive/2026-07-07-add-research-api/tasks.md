## 1. Service scaffold

- [x] 1.1 Add a FastAPI app skeleton (new directory, e.g. `research_api/main.py`) with
      health-check endpoint and app-level exception handling that maps known "not found"
      conditions to 404 responses.
- [x] 1.2 Add a run script/entry point (e.g. `open_research_api.cmd`) analogous to
      `open_research_dashboard.cmd`, documenting the chosen port.
    > Note: port 8503 (Panel dashboard stays on 8502).
- [x] 1.3 Add `uv` dependency entries for FastAPI + ASGI server (e.g. uvicorn).
    > Note: `fastapi` added to project deps; `uvicorn` and `httpx` (TestClient transport)
    > were already resolved in the environment; `uvicorn` is invoked via the run script.

## 2. Task endpoints

- [x] 2.1 Implement `GET /tasks` calling the lazy task-index function from
      `update-price-loading-performance`.
    > Note: returns `{task, mtime}` rows only; the index's `path` field is intentionally
    > not exposed over HTTP.
- [x] 2.2 Implement `GET /tasks/{task_id}` calling `load_task_bundle`; return 404 for
      unknown task ids.
- [x] 2.3 Add tests for both endpoints against `tasks/sample` (or a test fixture task).
    > Note: tests use tmp-path fixture tasks (`tests/test_research_api.py`); manual E2E
    > additionally verified against the real `tasks/sample`.

## 3. Price endpoint

- [x] 3.1 Implement `GET /tasks/{task_id}/prices?codes=...` calling
      `DataLoader.load_symbols` for exactly the requested codes.
    > Note: data root comes from the task summary's `data.path` via
    > `resolve_price_data_root`, same as the Panel dashboard.
- [x] 3.2 Include corporate-action markers (event type, date) in the response alongside
      OHLCV rows.
    > Note: added public `DataLoader.get_corporate_actions(code)` (TDD-covered in
    > `tests/test_data_loader_symbols.py`) instead of reaching into the private frame.
- [x] 3.3 Add a test proving the endpoint's data matches direct `load_symbols` output for
      the same codes, and that requesting one symbol does not load others' data.
    > Note: `pd.read_csv` spy asserts only `2454_day.csv` is read when `codes=2454`.

## 4. Trade endpoints

- [x] 4.1 Implement `GET /tasks/{task_id}/trades` calling `list_task_trades`, with the same
      filter parameters (code, action, limit) as the existing function.
- [x] 4.2 Implement `GET /tasks/{task_id}/trades/{trade_id}` calling `inspect_task_trade`;
      return 404 for unknown trade ids.
- [x] 4.3 Add tests for both endpoints, including the per-mode summary query paths
      (`summary_per_stock.json`, `summary_unconstrained.json`) already supported by
      `inspect_task_trade`.
    > Note: `summary_file` query param is whitelisted via `Literal` (422 on anything else)
    > to block path traversal.

## 5. Method restriction and error handling

- [x] 5.1 Confirm non-GET requests to any endpoint in this capability are rejected (405),
      either via FastAPI route method restriction or an explicit test.
    > Note: FastAPI's GET-only route registration provides this; pinned by parametrized
    > tests over POST/PUT/DELETE.
- [x] 5.2 Add a global exception handler translating underlying query errors into
      consistent JSON error responses.
    > Note: `QueryError` → 404 `{detail}`; unexpected exceptions → 500
    > `{"detail": "internal server error"}` with server-side logging.

## 6. Validation

- [x] 6.1 Run `uv run python -m pytest tests/ -q` (including new API tests) — all green.
    > Evidence: 130 passed.
- [x] 6.2 Run `uv run ruff check` on new files.
    > Evidence: `research_api/`, new/updated tests, `data_loader.py` all clean; the only
    > repo findings are pre-existing in the `shioaji_stock_prices` submodule. `mypy` on
    > `research_api` also clean.
- [x] 6.3 Manual E2E: start the API service alongside the existing Panel dashboard, hit
      each endpoint with a real task id and confirm response content matches what the Panel
      dashboard shows for the same task.
    > Evidence: both served concurrently (Panel 8502 → HTTP 200, API 8503); `/tasks` lists
    > the same 5 tasks as the dashboard selector; `tasks/sample` bundle `return_rate`
    > 111.0154 matches `summary.json`; `/prices?codes=2330` returned 1,834 OHLCV rows with
    > SignalClose and CASH_DIVIDEND markers; trades/trade-detail/404/405 all verified.
- [x] 6.4 Confirm starting/stopping the API service has no effect on the existing Panel
      dashboard's behavior.
    > Evidence: Panel still answered HTTP 200 after the API process was killed.
- [x] 6.5 Note any skipped Docker-backed verification with a reason.
    > Note: no Docker verification run — the API is a local read-only process with no
    > container deployment target in this repository.
