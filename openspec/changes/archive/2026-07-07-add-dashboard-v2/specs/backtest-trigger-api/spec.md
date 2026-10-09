## ADDED Requirements

### Requirement: A backtest can be triggered from the API with editable parameters

The API MUST accept a request to run a backtest with a chosen strategy, code/universe selection, date range, cash, capital mode, and strategy parameters, without requiring the caller to construct a CLI command.

#### Scenario: Trigger a backtest

- **WHEN** a client sends `POST /backtests` with strategy path, codes or universe
  reference, date range, cash, capital mode, and parameters
- **THEN** the API MUST run `scripts/run_task_backtest.py` with equivalent arguments as a
  background process
- **AND** it MUST return a job identifier immediately without blocking on completion.

#### Scenario: Available strategies are discoverable

- **WHEN** a client requests the list of available strategies for a task
- **THEN** the API MUST return the strategy files discovered under that task's
  `candidates/` directory.

#### Scenario: Parameters are editable without a predeclared schema

- **WHEN** a strategy has no declared parameter schema
- **THEN** the API MUST still accept a raw JSON parameters object and pass it through as
  `--params-json`.

### Requirement: Job status is observable until completion

The API MUST expose the status and log output of a triggered backtest job until it completes, and MUST NOT lose track of a job's outcome across an API restart.

#### Scenario: Poll job status

- **WHEN** a client requests the status of a job id
- **THEN** the API MUST report one of: running, completed, failed
- **AND** it MUST include recent log output for the job.

#### Scenario: API restarts while a job is running

- **WHEN** the API process restarts while a previously triggered job was in progress
- **THEN** subsequent status requests for that job id MUST report an explicit
  "interrupted/unknown" status rather than silently reporting stale "running" or
  fabricated "completed" status.

#### Scenario: Completed job appears in the task browser

- **WHEN** a triggered job completes successfully
- **THEN** its resulting task/run MUST appear via `GET /tasks` without requiring a manual
  refresh step beyond the frontend's normal polling.
