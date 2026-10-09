# research-task-workflow (delta)

## ADDED Requirements

### Requirement: Experiment artifacts are recognized task artifacts

Task directories SHALL recognize `experiment.json` (bounded experiment contract) and `journal.jsonl` (append-only iteration journal) as first-class machine-readable task artifacts, alongside existing summaries and reports. Agents continuing a task MUST inspect these artifacts when present before changing the task.

#### Scenario: Continue a task with an experiment in progress

- **WHEN** an agent continues a task whose directory contains `experiment.json` and `journal.jsonl`
- **THEN** it MUST read both before proposing new experiments or modifying candidates.

### Requirement: Task seeding is driven by the experiment spec

When a new task needs a starting strategy, the strategy reference in `experiment.json` SHALL drive seeding (defaulting to the tracked 2B sample candidate); the task-preparation script MUST NOT maintain a separate named-template mechanism.

#### Scenario: First iteration seeds the strategy

- **WHEN** the loop harness starts iteration 1 and the spec's referenced strategy file is absent from the task's `candidates/`
- **THEN** the harness MUST copy the referenced sample strategy into the task's `candidates/` before running.

#### Scenario: Retired template flag fails fast

- **WHEN** a user invokes the task-preparation script with the retired `--template` flag
- **THEN** the script MUST fail fast with a message pointing to the experiment-spec workflow.
