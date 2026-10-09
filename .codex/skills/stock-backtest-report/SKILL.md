---
name: stock-backtest-report
description: Produce a concise Traditional Chinese report from a local stock backtest study's mission, deterministic gates, analyzer outputs, and artifacts. Use when the user wants study results in chat instead of a dashboard; use stock-research-query for individual trade inspection.
---

# Stock Backtest Report

Report what the registered study established without replacing its acceptance rules with a
post-hoc narrative.

## Evidence Order

1. Read `tasks/<task-id>/mission.md` first. Treat its question, arms, windows, acceptance
   rules, amendments, and declared limitations as the study contract.
2. For a status/report request, inspect recorded verification evidence and the relevant analyzer
   entrypoint before reading result JSON. Rerun only a missing, stale, or disputed check, after
   checking its side effects and period access. Do not automatically launch every `verify_*.py`,
   rebuild inputs, open a sealed period, or rerun a sweep merely to summarize existing results.
3. Prefer analyzer output and committed reports over manually recomputing raw JSON. If the
   analyzer omits a requested value, state the additional calculation and its source.
4. Apply `market-data-cache` when interpreting prices, volume, liquidity, universes,
   corporate-action vintage, or summary metrics.
5. Mark live, partial, stale-vintage, pre-rule-amendment, or uncommitted artifacts plainly.
   Incomplete evidence is not a negative finding and must not be promoted to a conclusion.
6. Use `docs/en/research-foundation.md` and the shared exposure/correction registry for
   new result contracts. Distinguish schema/execution success from strategy acceptance,
   synthetic non-hit effects from actual equity drawdown, and recorded-ledger replay
   from counterfactual stress execution. Do not port an old card's private metric copy
   into a new gate without checking the common definition and synthetic fixtures.

## Decision Rules

- Evaluate every pre-registered rule, including turnover and robustness gates. Higher raw
  return alone is not a pass.
- Keep train, holdout, daily-overlap, and non-overlapping robustness results separate.
- Distinguish facts emitted by scripts from interpretation by the reporting agent.
- Preserve exact values and units. Do not convert percentage-valued summary fields as if
  they were fractions.
- Do not tune, amend the mission, or choose a new strategy while writing the report.

## Chat Report Contract

Return a compact Traditional Chinese report in the conversation; do not create a dashboard
or durable report file unless the user asks. Include:

- the question and compared arms;
- gate results and artifact completeness;
- the primary train and holdout evidence;
- turnover and modeled cost drag;
- robustness or sensitivity evidence;
- pass/fail/unresolved for each pre-registered rule;
- the decision supported by those rules;
- essential limitations and the exact evidence paths or commands.

Use `stock-research-query` separately when the request concerns a particular trade, its
signal reason, same-day values, quantity, or cash context.
