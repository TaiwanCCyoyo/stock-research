# Tasks: add-autonomous-research-loop

## 1. Experiment spec foundation

- [x] 1.1 Define the `experiment.json` schema (hypothesis, strategy ref, run config, tunable dimensions/ranges, gates with philosophy defaults, train/holdout windows, stop conditions) and a `load_experiment_spec()` validator with machine-readable failure reasons
- [x] 1.2 Implement deterministic gate evaluation over a summary dict (expectancy/payoff/profit-factor thresholds + minimum closed-trade-count guard with distinct "insufficient trades" reason)
- [x] 1.3 Tests: valid spec accepted; missing field / empty range / overlapping windows rejected before any subprocess; gate defaults applied; insufficient-trades failure path

## 2. Iteration harness and journal

- [x] 2.1 Implement the iteration harness script: run backtest/sweep via existing CLIs (subprocess with timeout), evaluate train gates, validate a proposed next move against spec bounds, append one `journal.jsonl` entry per iteration
- [x] 2.2 Implement stop-condition enforcement derived from journal state (max_iterations, no_improvement window, wall-clock) and spec-hash immutability check; refusals are journaled terminal entries
- [x] 2.3 Implement resume-from-journal (continue at N+1 with best-so-far state; no re-running completed iterations)
- [x] 2.4 First-iteration seeding: copy the spec's referenced strategy (default 2B sample) into task `candidates/` when absent
- [x] 2.5 Tests: one full iteration writes exactly one entry; out-of-bounds move rejected without launching a backtest and counts toward no_improvement; stop conditions refuse further runs; resume; write surface limited to task-local artifacts

## 3. Holdout validation

- [x] 3.1 Harness runs holdout-window backtests for train-gate-passing candidates only; journal records train and holdout gate results side by side, plus a running holdout-evaluation count
- [x] 3.2 Acceptance logic: "accepted" only when gates pass on both windows; train-only pass reported as "candidate — failed holdout"
- [x] 3.3 Tests: search input excludes holdout results; overfit candidate not accepted; holdout evaluations metered

## 4. Morning report

- [x] 4.1 Generate `nightly_report.md` mechanically from the journal (hypothesis, iterations + rationale, metric trajectory, train/holdout gate outcomes, holdout-evaluation count, recommended next step)
- [x] 4.2 Tests: report lists exactly the journaled iterations and the holdout count; no unsupported claims

## 5. Retire the template flow

- [x] 5.1 Remove `--template` from `prepare_nightly_research.py` (fail fast with pointer to the experiment-spec flow) and drop `next_prompt.md` generation; keep scaffolding, data audit, `--name`
- [x] 5.2 Update `run_nightly_research.ps1`, README, and `docs/zh-TW/Phase2B-Runner.md` to the new flow; update tests

## 6. Weak-model loop protocol and dry run

- [x] 6.1 Write the night-session protocol document (skill or command) the weak model follows: read journal tail + gate results → propose one in-bounds move with one-line rationale → call the harness; include `search: grid` degenerate mode that needs no LLM
- [ ] 6.2 Supervised end-to-end dry run on the 2B sample task with a 2-iteration budget; verify journal entries, gate evaluation on both windows, report generation
- [ ] 6.3 Document scheduling recipes (`/loop` with a cheap model; Windows Task Scheduler `claude -p`) as user-owned setup, per design D5

## 7. Verification

- [x] 7.1 `uv run python -m pytest tests/ -q` and `uv run mypy` on touched modules all green — 278 passed, 1 skipped; 3 pre-existing failures in `tests/test_dashboard_presentation.py` are unrelated to this change (missing generated `shioaji_stock_prices/data/` artifacts in this worktree, not a code path this change touches); `mypy` clean on all touched modules
- [ ] 7.2 Dry-run artifacts reviewed in the dashboard (journal/report readable); note that Docker smoke is skipped unless container entrypoints changed — BLOCKED: needs 6.2's supervised dry run, which needs real price data this worktree doesn't have
