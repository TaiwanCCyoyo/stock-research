# Design: add-autonomous-research-loop

## Context

Strategy research currently has three manual stages: design an experiment, run backtests/sweeps, interpret results and decide the next step. The repo already provides deterministic building blocks — `run_task_backtest.py` / `run_task_param_sweep.py` (machine-readable summaries with ranking), `strategy_health_rows()` (philosophy-aligned verdicts), `/diagnose-strategy`, and a read-only dashboard. What is missing is the middle: an unattended loop that iterates experiments overnight within human-set bounds. The old `prepare_nightly_research.py` + `next_prompt.md` flow assumed a human would relay the prompt to an agent each night; that never became autonomous, and its `--template` flag is a vestige of that design.

Two constraints shape everything:

1. **Weak models are reliable at rigid tool loops, unreliable at open-ended invention.** The night loop must be a fixed protocol over machine-readable state, with all judgment reduced to "pick the next move from declared bounds".
2. **Single-period backtests + automated search = overfitting machine.** Without a holdout, the loop would optimize noise. Out-of-sample validation is a prerequisite, not an enhancement.

## Goals / Non-Goals

**Goals:**

- A day-time authored, machine-readable experiment contract that bounds what the night loop may do.
- A night loop a weak model can execute: run → evaluate → decide-within-bounds → journal → repeat/stop.
- Gate evaluation and stop conditions enforced deterministically in Python, never delegated to the LLM.
- Train/holdout evaluation so acceptance requires out-of-sample confirmation.
- A morning report derived mechanically from the journal.

**Non-Goals:**

- Night-time strategy _code_ generation or engine changes (day-time, human-reviewed activity).
- Multi-task orchestration or queueing (one experiment per night per task to start).
- Dashboard UI for journals (later change; artifacts are dashboard-consumable by design).
- Cloud execution (local data dependency; local scheduling only for now).

## Decisions

### D1. Experiment spec is a task-local `experiment.json`

Follows the repo's "task directory is the canonical workspace, machine-readable first" spec. Contents: hypothesis (prose), strategy file reference (defaults to the 2B sample candidate), fixed run config (codes, cash, data path), tunable dimensions with explicit ranges/choices, acceptance gates, train window + holdout window, stop conditions (max iterations, no-improvement rounds, wall-clock). Authored during the day (strong model translating the user's natural-language direction), validated by schema, and treated as immutable while a loop runs.
_Alternative considered_: reusing `mission.md` prose — rejected; the loop needs machine-checkable bounds, not prose.

### D2. Deterministic harness + minimal LLM decision surface

A Python driver (`scripts/run_experiment_iteration.py`, name indicative) owns everything checkable: invoking backtest/sweep CLIs, computing gate results on train and holdout summaries, appending journal entries, and refusing to run when stop conditions are met. The weak model's entire job per iteration is: read the journal tail + gate results, choose the next parameter adjustment _from the spec's declared dimensions/ranges_, and state a one-line rationale — which the harness validates against bounds before executing.
_Alternative considered_: pure-script optimizer (grid/random, no LLM) — kept as the degenerate mode (a spec may declare `search: grid`), because parameter search alone does not need an LLM; the LLM earns its cost only for dimension-switching judgment and the morning narrative. _Alternative_: agent-owns-everything loop — rejected; weak models drift, and math/stop enforcement must not depend on model compliance.

### D3. Holdout via orchestration, not engine changes

`run_task_backtest.py` already accepts `--start/--end`. Holdout = the harness re-running the accepted parameter set over the disjoint holdout window and evaluating the same gates on that summary. No `StockProject/engine/` modification. Iteration/search reads only train-window results; holdout results are computed for candidate winners and required for final acceptance (walk-forward style).
_Alternative considered_: native train/test split inside the engine — more invasive, touches the protected engine, and adds no statistical power over two-window orchestration at this stage.

### D4. Append-only `journal.jsonl` as the loop's single source of truth

Each iteration appends one JSON object: iteration number, params tried, run/sweep artifact paths, train gate results, holdout gate results (when run), decision + rationale, timestamps. Crash-safe (append-only), resumable (harness reads the tail to know where it is), and the morning `nightly_report.md` is generated from it mechanically — so the report can never claim something the journal cannot substantiate.

### D5. Scheduling stays outside the repo contract

The loop protocol assumes only "something invokes the next iteration": Claude Code `/loop` with a cheap model, a Windows Task Scheduler `claude -p` job, or manual runs. The spec deliberately does not mandate a scheduler; the harness's stop conditions make any driver safe. Recommended default: `/loop` with Haiku on nights the machine is on.

### D6. `--template` retires; seeding folds into the experiment spec

The experiment spec names its starting strategy file; the harness copies it into the task's `candidates/` on first iteration if absent (default: the 2B sample). `prepare_nightly_research.py` keeps task scaffolding + data audit + `--name`, drops `--template`/`next_prompt.md`.

### D7. Holdout window is explicit dates, not a fixed split fraction

The experiment spec's train/holdout windows are explicit `start`/`end` dates set by the day-time strong model, not a fixed final-20%-of-period rule. A fixed fraction makes the holdout length depend on how long a period the human happened to request, so holdout windows would be incomparable across experiments and could shrink to statistically meaningless spans for short requested periods. Explicit dates let the day-time author pick a holdout window with enough trading days to be meaningful regardless of the total period length, and make the split auditable in the spec itself rather than implicit in code.
_Alternative considered_: fixed final 20% — rejected for the reason above; kept as a documented fallback the day-time model may still choose to propose (it just has to write the resulting dates into the spec explicitly, like any other window).

### D8. Sweep ranking during the loop uses expectancy, not `return_rate`

`run_task_param_sweep.py`'s existing `--rank-metric` flag is passed through as `expectancy` by default for loop-driven sweeps, overriding the CLI's own general-purpose default of `return_rate`. The loop's acceptance gates are expectancy-led (per the project's "big wins, small losses" philosophy), so ranking candidates by a metric the gates do not use would let the search promote candidates that look good on the wrong axis and only fail gates after the fact. This only changes the loop harness's invocation; the sweep CLI's own default for manual/day-time use is unchanged.

### D9. Night-session runtime is deferred to Migration Plan step 4

Whether the night loop runs as `claude -p` headless or interactive `/loop` is an operational choice, not a design constraint the harness needs to bake in now — the harness's stop conditions and journal make either driver safe (per D5). This is decided with the user at Migration Plan step 4, based on whether the machine is expected to stay on overnight at that time, not resolved speculatively here.

## Risks / Trade-offs

- [Overfitting despite holdout — repeated peeking erodes the holdout] → harness runs holdout only for candidate winners, journals every holdout evaluation, and the report flags holdout-evaluation count; specs should keep tunable dimensions few (guideline: ≤ 3 per night).
- [Weak model proposes out-of-bounds or nonsense moves] → harness validates every proposed move against the spec before executing; invalid moves are journaled and count toward a no-progress stop condition.
- [Runaway cost/time] → stop conditions enforced by harness state in the journal (iterations, wall-clock), not by the model; `MAX_RUNNING_JOBS`-style guard prevents parallel pile-ups.
- [Loop stalls (hung backtest, missing data)] → per-iteration subprocess timeout; a data-audit preflight failure aborts with a journaled reason; the driving session follows the `night-research-loop` skill's stall-detection convention (stop and report if the harness call itself fails or hangs, rather than retrying blindly) — there is no dedicated `loop-operator` agent in this repo.
- [2B sample produces zero trades under some configs (cash-blocked)] → gate evaluation treats `closed_trade_count` below a spec-declared minimum as an automatic fail with a distinct journal reason, so the loop moves on instead of dividing by zero.
- [Breaking `--template` users] → only docs and the ps1 wrapper reference it; both updated in this change; the flag fails fast with a pointer to the new flow.

## Migration Plan

1. Land `backtest-holdout-validation` (harness-level) + experiment-spec schema/validation with tests — no behavior change for existing flows.
2. Land the iteration harness + journal + report generation; supervised dry run (2-iteration budget) on the 2B sample task.
3. Retire `--template`/`next_prompt.md`; update README / Phase2B-Runner docs.
4. Enable overnight scheduling per D5 (user-owned step; document both `/loop` and Task Scheduler recipes).

Rollback: the loop is additive scripts + artifacts; disabling the scheduler entry fully reverts operational behavior.

## Open Questions

None outstanding — see D7 (holdout window), D8 (sweep ranking metric), and D9 (night-session
runtime, explicitly deferred to Migration Plan step 4 rather than resolved here).

## Naming Note

`nightly_report.md` (D4, Migration Plan step 2) was previously produced by
`scripts/generate_task_report.py` for an unrelated, now-retired Codex Notion report flow (see
`retire-codex-notion-research-report`, archived 2026-08-08). That generator and its output are
gone; this change's harness is now the sole producer of `nightly_report.md`, with no naming
conflict to resolve.
