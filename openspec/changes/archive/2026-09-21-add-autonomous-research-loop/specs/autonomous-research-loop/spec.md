# autonomous-research-loop

## ADDED Requirements

### Requirement: Iterations follow a fixed run-evaluate-decide-journal protocol

The system SHALL provide an iteration harness that, per iteration: runs the backtest or sweep declared by the current parameter set via the existing task CLIs, evaluates acceptance gates deterministically in Python, accepts a next-move proposal, validates that proposal against the experiment spec's declared dimensions and ranges, and appends a journal entry — in that order. Gate math and stop-condition enforcement MUST NOT be delegated to a language model.

#### Scenario: One complete iteration

- **WHEN** the harness runs an iteration for a task with a valid experiment spec
- **THEN** it MUST invoke the backtest/sweep subprocess, compute gate results from the produced summary, and append exactly one journal entry containing the parameters tried, artifact paths, gate results, decision, and rationale.

#### Scenario: Out-of-bounds proposal rejected

- **WHEN** the proposed next move references a parameter dimension not declared in the spec or a value outside its declared range
- **THEN** the harness MUST reject the move without launching a backtest
- **AND** journal the rejection, which MUST count toward the no-improvement stop condition.

### Requirement: Stop conditions are enforced from journal state

The harness SHALL derive loop state (iteration count, best result so far, consecutive no-improvement rounds, elapsed wall-clock) from the journal, and MUST refuse to run further iterations once any stop condition in the experiment spec is met.

#### Scenario: Max iterations reached

- **WHEN** the journal already contains the spec's maximum number of iterations
- **THEN** a further iteration request MUST be refused and the refusal journaled as the terminal entry with reason "max_iterations".

#### Scenario: No-improvement window exhausted

- **WHEN** the last K iterations (K from the spec) produced no improvement on the ranking metric
- **THEN** the harness MUST terminate the loop and journal reason "no_improvement".

### Requirement: The loop never modifies code or engine state

Night iterations SHALL only vary parameter values and run configuration declared in the experiment spec. The harness MUST NOT create or edit strategy code, engine files, or the experiment spec; the only files it writes are run artifacts under the task directory, the journal, and the morning report.

#### Scenario: Write surface is task-local artifacts only

- **WHEN** any iteration completes
- **THEN** the set of files created or modified by the harness MUST be limited to the task's `runs/`, summary artifacts, `journal.jsonl`, and `nightly_report.md`.

### Requirement: Journal is append-only and resumable

The system SHALL record every iteration as one JSON object appended to task-local `journal.jsonl`. The harness MUST be able to resume after interruption by reading the journal tail, without re-running completed iterations.

#### Scenario: Resume after crash

- **WHEN** the loop is restarted after an interruption and the journal contains N completed iterations
- **THEN** the harness MUST continue at iteration N+1 using the journal's recorded best-so-far state.

### Requirement: Morning report derives mechanically from the journal

The system SHALL generate `nightly_report.md` from journal content: hypothesis, iterations tried with rationale, metric trajectory, gate outcomes on train and holdout, holdout-evaluation count, and a recommended next step. The report MUST NOT assert results that lack a corresponding journal entry.

#### Scenario: Report reflects journal only

- **WHEN** the report generator runs against a journal with M iterations and one holdout evaluation
- **THEN** the report MUST list exactly those M iterations and flag that the holdout was evaluated once.
