> Archived as retired on 2026-09-21 after PR review. Tasks 6.2, 6.3 and 7.2 remain incomplete and are no longer scheduled for implementation. Delta specs were intentionally not synced: the holdout-coupled workflow was abandoned. Historical task status and artifacts are preserved.

> Retired on 2026-09-20: the owner authorized removal of the holdout-coupled runner and its skill. This proposal is historical context, not execution guidance. Use docs/en/research-foundation.md for current research.

# Proposal: add-autonomous-research-loop

## Why

Today the expensive part of strategy research — running experiments, reading results, deciding the next adjustment — is fully manual: `prepare_nightly_research.py` only scaffolds a task directory and leaves a `next_prompt.md` for a human to hand to an agent. The user wants overnight, unattended research: they give a natural-language direction ("try a trend filter on 2B, get expectancy positive"), and a low-cost model iterates backtests overnight within explicit bounds, so mornings start from reviewed results instead of raw ideas. Doing this safely also exposes a prerequisite gap: single-period backtests let an automated optimizer overfit quickly, so out-of-sample validation must exist before any loop is trusted.

## What Changes

- Introduce an **experiment spec** artifact (`experiment.json` per task): a bounded, machine-readable contract produced from the user's natural-language direction by a strong model during the day. It fixes the hypothesis, the tunable parameter dimensions and ranges, acceptance gates aligned with the big-wins-small-losses philosophy (expectancy > 0, payoff ratio >= 2, profit factor > 1), and stop conditions (max iterations, no-improvement window, wall-clock budget).
- Introduce an **overnight research loop**: a driver that a weak model executes iteratively — run backtest/sweep via existing CLIs, read `summary.json`/`sweep_summary.json`, compare against gates, choose the next adjustment strictly within the experiment spec's bounds, and append a structured entry to an **experiment journal** (`journal.jsonl`). The loop never invents new code paths at night; strategy code changes stay a daytime activity.
- Add **out-of-sample validation** as a prerequisite: backtest runs used by the loop must support a train/holdout split (train period drives iteration; acceptance gates must also hold on the untouched holdout period). This is the anti-overfitting guardrail and lands before the loop is enabled.
- Produce a **morning report** (`nightly_report.md`) derived from the journal: what was tried, why, metric trajectory, whether gates were met on train and holdout, and recommended next steps — reviewable in the existing dashboard.
- **BREAKING**: retire the `--template` flag of `scripts/prepare_nightly_research.py`. Task seeding collapses into the experiment-spec workflow (the spec names the starting strategy file, defaulting to the 2B sample); `next_prompt.md` handoff is superseded by the experiment spec + loop driver.

## Non-Goals

- No real trading, order routing, broker credentials, or investment advice; the loop only runs local/Docker backtests and writes task artifacts.
- No autonomous editing of strategy code or `StockProject/engine/` at night; the loop only varies parameters and run configurations declared in the experiment spec.
- No external/internet research during the loop; local K-line data only.
- No change to the dashboard beyond consuming artifacts the loop already writes (journal/report render via existing views).

## Capabilities

### New Capabilities

- `experiment-spec`: schema and lifecycle of the bounded experiment contract — hypothesis, strategy reference, tunable dimensions/ranges, acceptance gates, train/holdout windows, stop conditions; authored during the day, immutable during a loop run.
- `autonomous-research-loop`: the overnight iteration protocol — how the driver invokes backtests/sweeps, evaluates gates, selects the next move within bounds, journals every iteration, terminates on stop conditions, and emits the morning report.
- `backtest-holdout-validation`: train/holdout period split support in the backtest runtime — running the same strategy/params over a declared holdout window and reporting gate metrics separately, so in-sample search cannot silently overfit.

### Modified Capabilities

- `research-task-workflow`: task directories gain `experiment.json` and `journal.jsonl` as recognized artifacts; the "runner prepares, agent continues via next_prompt" flow is replaced by the experiment-spec flow; template seeding requirement is removed.

## Impact

- **Code**: `scripts/prepare_nightly_research.py` (retire `--template`, emit/validate `experiment.json`), new loop driver script under `scripts/`, `scripts/run_task_backtest.py` / `StockProject/backtest_cli.py` (holdout window support), report generation from journal.
- **Schedulers/agents**: Claude Code `/loop` or Windows Task Scheduler invokes the loop driver with a weak model, following the `night-research-loop` skill's protocol (stop conditions, stall detection); there is no dedicated `loop-operator` agent in this repo.
- **Docs/tests**: `docs/zh-TW/Phase2B-Runner.md` and README workflow sections; new pytest coverage for experiment-spec validation, gate evaluation, holdout metrics, and journal writing.
- **Dashboard**: read-only additions later (render journal/report); not required for the first cut.

## Verification

- `uv run python -m pytest tests/ -q` (experiment spec, gate evaluation, holdout split, journal)
- `uv run mypy` on touched modules
- One supervised end-to-end dry run: a real experiment spec against the 2B sample task with a 2-iteration budget, confirming journal entries, gate evaluation on train + holdout, and morning report generation
- Docker smoke (`docker compose run --rm research-task-smoke`) only if the loop driver changes container entrypoints; otherwise skipped and noted
