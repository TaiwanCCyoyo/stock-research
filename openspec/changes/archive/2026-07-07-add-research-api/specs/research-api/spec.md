## ADDED Requirements

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

### Requirement: The API has no write or mutation endpoints

The research API in this change MUST only expose read (GET) endpoints.

#### Scenario: Attempt a write operation

- **WHEN** a client sends a non-GET request to any endpoint defined by this capability
- **THEN** the API MUST reject it (e.g. 405) rather than silently accepting it.

### Requirement: Missing tasks or trades produce a clear error response

The API MUST translate underlying "not found" conditions into an appropriate HTTP error rather than a raw exception or empty success response.

#### Scenario: Request an unknown task

- **WHEN** a client requests a task id that does not exist under `tasks/`
- **THEN** the API MUST respond with a 404 and a readable error message.

#### Scenario: Request an unknown trade

- **WHEN** a client requests a trade id that does not exist within a valid task
- **THEN** the API MUST respond with a 404 and a readable error message.
