## Context

The only symbol metadata in the repo today is `stock_symbol_mapping.json5` (code→name),
loaded by `research_lab/display.py:stock_names()`. There is no industry/sector field, no
watchlist, and no way to say "run this strategy against every semiconductor stock" without
manually enumerating codes. Meanwhile, `StockProject/backtest_cli.py` already has a proven
pattern for "one command, multiple passes, comparison artifact" from the capital-mode
comparison feature (`build_capital_mode_comparison`, `write_comparison_artifacts`,
Option-A: full summary per pass + thin `comparison.json`). Universe comparison should reuse
that pattern rather than invent a new one.

## Goals / Non-Goals

**Goals:**

- Make "same parameters, different stock group" a first-class, low-friction operation.
- Reuse the existing Option-A comparison-artifact pattern instead of a new format.
- Keep universes as plain, version-controlled, human-editable files.

**Non-Goals:**

- No automatic industry-based strategy tuning.
- No live/streaming reclassification.

## Decisions

**1. Symbol classification metadata stored as a local SQLite table
(`symbol_meta.sqlite`), sourced from TWSE/TPEx ISIN public data.**
Consistent with the existing pattern of one SQLite file per data concern
(`corporate_actions.sqlite`, and the new `institutional.sqlite`). Alternative considered:
extend `stock_symbol_mapping.json5` with an `industry` field — rejected because that file
is a simple lookup map maintained by hand/script, and industry data has its own refresh
cadence and provenance (TWSE ISIN listings) that deserves separate tracking (fetch
timestamp, source).

**2. Universes are plain JSON files under `universes/`, not database rows.**
A universe is either an explicit `codes: [...]` list or a `rule: {industry: "半導體"}`
that expands against `symbol_meta.sqlite` at run time. Keeping them as files makes them
easy to hand-edit, diff, and check into git — matching how `tasks/*/mission.md` and
strategy candidates are already treated as plain, versioned, human-editable artifacts.
Alternative considered: a universes table in SQLite — rejected because universes are a
research researcher-authored input, not derived/fetched data, and the project's convention
is to keep human-authored research inputs as files.

**3. `@universe-name` is resolved once at CLI entry, not deep inside the engine.**
`--codes` parsing in `backtest_cli.py` (and `run_task_backtest.py`) resolves any
`@universe-name` token to its expanded code list before anything else runs; the engine
itself never knows a universe was involved — it only ever sees a plain code list. This
keeps the engine's contract unchanged and isolates the new logic to the CLI boundary.
Alternative considered: pass the universe name through to the engine and resolve inside —
rejected as unnecessary surface-area growth in a component (`StockProject/engine/`) that
this project treats with extra care.

**4. Cross-universe comparison reuses the Option-A summary-plus-comparison pattern.**
Running with multiple universes produces `summary_<universe>.json` per universe plus a
`comparison.json` with headline metrics per universe — mirroring
`build_capital_mode_comparison`/`write_comparison_artifacts` exactly, including keeping
`summary.json` aliased to a default (first) universe's result for backward compatibility.
Alternative considered: a bespoke universe-comparison format — rejected in favor of
consistency with the pattern researchers already know from capital-mode comparison.

## Risks / Trade-offs

- [Risk] TWSE/TPEx ISIN industry data may need periodic manual refresh and could drift from
  reality (delistings, reclassifications) → Mitigation: record a fetch timestamp in
  `symbol_meta.sqlite` and surface it in the dashboard so staleness is visible.
- [Risk] A rule-based universe (`industry: "半導體"`) could silently include/exclude codes
  as classification data changes between runs, making results non-reproducible across time
  → Mitigation: when a rule-based universe is used, record the resolved code list in the
  run's `summary.json` metadata so the actual set used is always auditable after the fact.
- [Risk] Combining `@universe` expansion with existing `--codes` comma-list parsing could
  introduce ambiguity → Mitigation: `@name` is a distinct token prefix, comma-separated
  plain codes remain unchanged; mixing the two in one `--codes` value is explicitly out of
  scope for the first version (one universe token OR a plain code list, not both).

## Migration Plan

- Additive: existing comma-separated `--codes` usage is completely unaffected; `@universe`
  is new syntax recognized only when the value starts with `@`.
- Rollback: remove `@universe` resolution from the CLI entry points; universes files and
  `symbol_meta.sqlite` can remain unused without harm.
