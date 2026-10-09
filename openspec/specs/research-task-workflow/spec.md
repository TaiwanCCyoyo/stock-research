# Research Task Workflow

## Purpose

Define the baseline workflow for organizing strategy research as local task directories with durable artifacts, clear constraints, and machine-readable results.

## Requirements

### Requirement: Task directories are the canonical research workspace

The system MUST organize each daily or ad hoc strategy investigation as a task directory under `tasks/`, with task-local inputs, candidates, runs, summaries, and reports treated as the canonical research record.

#### Scenario: Create a standard task

- **WHEN** Codex or a script creates a new research task for a set of Taiwan stock symbols
- **THEN** the task directory MUST be created under `tasks/`
- **AND** it MUST include task-local `candidates/` and `runs/` directories
- **AND** it MUST include a `mission.md` describing scope, constraints, objective, and expected artifacts.

#### Scenario: Continue an existing task

- **WHEN** Codex continues prior research for a task
- **THEN** it MUST inspect existing task artifacts such as `mission.md`, `data_audit.json`, `summary.json`, or `sweep_summary.json` when present before changing the task.

### Requirement: Research tasks preserve safety constraints

The task workflow MUST surface the safety boundaries defined by `research-output-safety` in each task's mission and execution context.

#### Scenario: Render task mission constraints

- **WHEN** a task mission is generated
- **THEN** it MUST state that there is no real trading
- **AND** it MUST state that broker credentials are not allowed, as governed by `research-output-safety`
- **AND** it MUST state whether Docker is required or optional for generated strategy execution
- **AND** it MUST prevent task work from modifying `StockProject/engine/`.

### Requirement: Candidate strategies are task-local experiments

Generated or experimental strategy code MUST live under task-local candidate locations unless a separate OpenSpec change explicitly promotes reusable behavior into the core project.

#### Scenario: Prepare strategy experiments

- **WHEN** a strategy candidate is created for a research task
- **THEN** it SHOULD be written under the task's `candidates/` area
- **AND** core engine files SHOULD remain unchanged during ordinary strategy experiments.

### Requirement: Research outputs are machine-readable first

Research tasks MUST produce machine-readable artifacts before prose summaries so agents and dashboards can consume the result deterministically.

#### Scenario: Promote a selected run

- **WHEN** a backtest run is selected as the task result
- **THEN** the selected run MUST be promoted or copied to task-level `summary.json`
- **AND** any prose artifacts a researcher chooses to write SHOULD derive from local machine-readable task artifacts rather than being authored independently of them.

### Requirement: Parameter sweeps produce ranked task-local summaries

The task workflow MUST support task-local parameter sweeps that run multiple strategy parameter sets and write a deterministic `sweep_summary.json` artifact.

#### Scenario: Run grid-based parameter sweep

- **WHEN** `scripts/run_task_param_sweep.py` runs for a task strategy and sweep grid file
- **THEN** the grid file MUST decode to a JSON object
- **AND** each generated run MUST write a run summary under the task's `runs/` area
- **AND** the sweep output MUST include schema version, generation timestamp, task path, strategy path, grid file, rank metric, rank direction, best run, and ranked runs.

#### Scenario: Promote best sweep result

- **WHEN** a parameter sweep is run with best-result promotion enabled
- **THEN** the best run summary MUST be copied to task-level `summary.json`
- **AND** associated signal events or stock rankings SHOULD be copied to task-level artifacts when those run artifacts exist.
