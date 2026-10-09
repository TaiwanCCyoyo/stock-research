## Why

The Codex Notion research-report flow (`.codex/skills/notion-research-report/`, its
`research-report-drafter` agent, and `scripts/generate_task_report.py`) was judged unreliable
in practice and is no longer used. A repo audit found its outputs (`nightly_report.md`,
`walkthrough.md`, `research_report/*`, `notion_report_payload.json`) have zero programmatic
consumers: no dashboard (Panel legacy or React v2) or test reads them, and the drafter agent's
only source material duplicates data the dashboard already reads directly from `summary.json`.
Retiring it also frees the `nightly_report.md` filename, which `add-autonomous-research-loop`
needs for its own (unrelated) nightly-loop report and would otherwise collide with.

## What Changes

- **BREAKING**: Remove `scripts/generate_task_report.py` and its `nightly_report.md` /
  `walkthrough.md` generation.
- **BREAKING**: Remove `.codex/skills/notion-research-report/` (SKILL.md, `agents/openai.yaml`,
  three `build_*.py` report scripts) and `.codex/agents/research-report-drafter.toml`.
- Remove references to the retired flow from `scripts/tests/test_agent_instruction_contract.py`,
  `.codex/AGENTS.md`, `docs/en/fork-maintenance.md`, and `openspec/specs/research-task-workflow/
spec.md`.
- Remove the now-dangling `Generate walkthrough.md and nightly_report.md.` prompt lines from
  `scripts/create_research_task.py` and `scripts/prepare_nightly_research.py`.
- Annotate `docs/zh-TW/Plan.md` §7.6 as retired (historical phase-roadmap document; keep the
  original text for traceability rather than rewriting it).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `research-task-workflow`: the "Research outputs are machine-readable first" requirement's
  scenario no longer names `walkthrough.md`/`nightly_report.md` as example prose artifacts
  produced by a dedicated generator; the SHOULD-level guidance about deriving prose from
  machine-readable artifacts is otherwise unchanged.

## Impact

- Deletes: `scripts/generate_task_report.py`, `.codex/skills/notion-research-report/` (6
  files), `.codex/agents/research-report-drafter.toml`.
- Edits (references only, no behavior change beyond the removed prompt lines):
  `scripts/tests/test_agent_instruction_contract.py`, `.codex/AGENTS.md`,
  `docs/en/fork-maintenance.md`, `docs/zh-TW/Plan.md`, `scripts/create_research_task.py`,
  `scripts/prepare_nightly_research.py`.
- Not touched: `openspec/specs/research-output-safety/spec.md` (its "Prepare Notion output"
  scenario is generic and still applies to other live Notion-facing skills, e.g.
  `.claude/skills/notion-dev-log`); `research_lab/dashboard_core.py` (its artifact link list
  already tolerates missing files and needs no edit); existing historical task artifacts under
  `tasks/20260510-two-b-template-smoke/` (real prior output, left in place).
- Non-goals: no change to `StockProject/engine/`, the backtest runtime, or any dashboard code.
- Verification: `uv run python -m pytest tests/ scripts/tests/ -q`,
  `uv run python -m scripts.build_research_dashboard` (confirms the static site builder is
  unaffected), and a repo-wide grep for residual references. No Docker smoke needed — this
  change removes an unused reporting flow and touches no runtime data or engine path.
