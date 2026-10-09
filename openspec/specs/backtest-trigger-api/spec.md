# backtest-trigger-api Specification

## Purpose

Record the retirement of browser-triggered research execution. As of the
owner-authorized 2026-09-21 slimming change, the optional viewer reads artifacts
but does not execute strategies. Historical implementation requirements remain
in the archived `add-dashboard-v2` change, not as current behavior.

## Requirements

### Requirement: The viewer cannot launch or manage backtests

The API MUST NOT register backtest launch, job list or job polling routes, create
job directories on import, or spawn a research process. Approved research uses
the task's CLI independently of the viewer.

#### Scenario: A former client attempts to launch or poll

- **WHEN** a client sends `POST /backtests`, `GET /backtests` or `GET /backtests/{id}`
- **THEN** the request MUST be unavailable (404 or 405), even with `X-Requested-With`
- **AND** no strategy execution or artifact mutation occurs.

#### Scenario: Available strategies are discoverable

- **WHEN** a client requests the list of available strategies for a task
- **THEN** the API MUST return the strategy files discovered under that task's
  `candidates/` directory.

### Requirement: Historical job evidence is preserved

Retirement MUST NOT delete or migrate existing `.tmp/backtest_jobs` records,
logs, study artifacts or market data. It does not cancel any already-running
external process.

#### Scenario: Upgrade with historical job records

- **WHEN** the viewer is imported or launched after the upgrade
- **THEN** existing job evidence MUST remain untouched
- **AND** the UI MUST offer no launch form or job poller.
