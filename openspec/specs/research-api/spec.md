# research-api Specification

## Purpose

TBD - created by archiving change add-research-api. Update Purpose after archive.

## Requirements

### Requirement: The API is a read-only projection of existing task artifacts

The research API MUST expose existing task artifacts over HTTP without introducing new computed metrics or a new artifact format.

#### Scenario: Serve a task list

- **WHEN** a client requests `GET /tasks`
- **THEN** the API MUST return the lightweight task index (id, title, generated timestamp)
  for all discoverable tasks under `tasks/`.

#### Scenario: Serve a full task bundle

- **WHEN** a client requests `GET /tasks/{task_id}`
- **THEN** the API MUST return the same data `load_task_bundle` produces for that task,
  including per-mode summaries and comparison data when present.

#### Scenario: Serve per-symbol price data

- **WHEN** a client requests `GET /tasks/{task_id}/prices` with one or more symbol codes
- **THEN** the API MUST return OHLCV data and corporate-action markers for exactly those
  symbols, without reading price data for other symbols.

#### Scenario: Serve trade list and trade detail

- **WHEN** a client requests `GET /tasks/{task_id}/trades` or
  `GET /tasks/{task_id}/trades/{trade_id}`
- **THEN** the API MUST return the same data `list_task_trades`/`inspect_task_trade`
  produce for that task and trade.

### Requirement: Research artifacts cannot be mutated through the API

Artifact endpoints MUST expose only read operations. The separate heartbeat and
shutdown lifecycle controls below do not authorize artifact writes or research
execution. The API is installed with the optional `viewer` dependency group and
MUST NOT import Panel or Plotly merely to read artifacts.

#### Scenario: Attempt a write operation

- **WHEN** a client sends a non-GET request to an artifact endpoint
- **THEN** the API MUST reject it (e.g. 405) rather than silently accepting it.

### Requirement: Missing tasks or trades produce a clear error response

The API MUST translate underlying "not found" conditions into an appropriate HTTP error rather than a raw exception or empty success response.

#### Scenario: Request an unknown task

- **WHEN** a client requests a task id that does not exist under `tasks/`
- **THEN** the API MUST respond with a 404 and a readable error message.

#### Scenario: Request an unknown trade

- **WHEN** a client requests a trade id that does not exist within a valid task
- **THEN** the API MUST respond with a 404 and a readable error message.

### Requirement: Shutdown and heartbeat endpoints support dashboard lifecycle control

The API MUST expose `POST /shutdown` and `POST /heartbeat` so the frontend can stop the
local dashboard server explicitly or let it detect that the browser tab has closed. Both
endpoints MUST require an `X-Requested-With` header to prevent simple cross-origin
POSTs, since no `CORSMiddleware` is configured and the API remains bound to
`127.0.0.1`.

#### Scenario: Reject shutdown/heartbeat requests without the CSRF header

- **WHEN** a client sends `POST /shutdown` or `POST /heartbeat` without the
  `X-Requested-With` header
- **THEN** the API MUST respond with 403 and MUST NOT act on the request.

#### Scenario: Heartbeat updates last-seen state

- **WHEN** a client sends `POST /heartbeat` with the required header
- **THEN** the API MUST record the current time as the most recent heartbeat.

#### Scenario: Shutdown signals the owning server process

- **WHEN** a client sends `POST /shutdown` with the required header and the API process was
  started by the production launcher (`research_api.__main__`)
- **THEN** the API MUST signal that owning server to stop gracefully
- **AND** it MUST still return a successful response when no owning server is attached
  (e.g. under a test client or the Vite-dev launcher), without raising an error.

### Requirement: Data quality is readable without a live health-check run

The API MUST expose a read-only `GET /data-quality` endpoint that returns the local data
completeness report produced by the `shioaji_stock_prices` submodule, or a neutral "not yet
checked" response when no report exists.

#### Scenario: Report file exists

- **WHEN** `GET /data-quality` is called and
  `shioaji_stock_prices/data/data_quality_report.json` is found at one of the candidate
  probe paths
- **THEN** the API MUST return that report's contents.

#### Scenario: Report file does not exist

- **WHEN** `GET /data-quality` is called and no report file is found at any candidate path
- **THEN** the API MUST return a neutral "not yet checked" response
- **AND** it MUST NOT return an error status for this case.
