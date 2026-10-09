## 1. Remove the retired flow's files

- [x] 1.1 Delete `.codex/skills/notion-research-report/` in full (`SKILL.md`,
      `agents/openai.yaml`, `scripts/build_notion_research_report.py`,
      `scripts/build_structured_research_report.py`, `scripts/build_visual_research_report.py`,
      `scripts/.gitkeep`).
- [x] 1.2 Delete `.codex/agents/research-report-drafter.toml`.
- [x] 1.3 Delete `scripts/generate_task_report.py`.

## 2. Fix dangling references

- [x] 2.1 Remove the `assert "research-report-drafter" in actual_agents` line (and any
      surrounding comment referring to it) from
      `scripts/tests/test_agent_instruction_contract.py`.
- [x] 2.2 Remove the `.codex/skills/notion-research-report/SKILL.md` entry from
      `.codex/AGENTS.md`.
- [x] 2.3 Remove `.codex/agents/research-report-drafter.toml` and
      `.codex/skills/notion-research-report/` from the Stock-only additions lists in
      `docs/en/fork-maintenance.md`, and update the `test_agent_instruction_contract.py` row
      description there to match the trimmed assertions.
- [x] 2.4 Add a short "retired 2026-08-08" note above §7.6 in `docs/zh-TW/Plan.md`, leaving the
      rest of the section's text intact as historical record.
- [x] 2.5 Remove the `Generate walkthrough.md and nightly_report.md.` line from the prompt
      template in `scripts/create_research_task.py` (around line 79).
- [x] 2.6 Remove the two equivalent `walkthrough.md`/`nightly_report.md` lines from the prompt
      templates in `scripts/prepare_nightly_research.py` (around lines 194 and 204).
- [x] 2.7 Remove the `notion-research-report` mention from
      `.codex/skills/fork-maintenance-sync/SKILL.md`'s Stock-Specific Preservation Rules (a
      live instruction telling future syncs to preserve a now-deleted skill).
- [x] 2.8 Remove the equivalent dangling `walkthrough.md`/`nightly_report.md` mentions from
      `docs/zh-TW/mission.example.md` and `docs/zh-TW/Phase2B-Runner.md` (found via the
      broadened grep in task 4.3; same latent-bug pattern as 2.5/2.6).

## 3. Apply the spec delta

- [x] 3.1 Confirm `specs/research-task-workflow/spec.md`'s MODIFIED requirement matches the
      change proposal's intent (no dedicated generator implied, SHOULD-level guidance kept).

## 4. Verify

- [x] 4.1 Run `uv run python -m pytest tests/ scripts/tests/ -q` and confirm it is green,
      including the trimmed `test_agent_instruction_contract.py`.
- [x] 4.2 Run `uv run python -m scripts.build_research_dashboard` and confirm the static site
      still builds successfully (proves `build_research_dashboard.py` was correctly left
      untouched and has no import on anything deleted).
- [x] 4.3 Run a repo-wide grep for `generate_task_report|notion-research-report|
research-report-drafter|nightly_report|walkthrough` (excluding `.references/`,
      `legacy/`, `tasks/`, and `openspec/changes/archive/`) and confirm no live reference to
      the deleted flow remains outside `add-autonomous-research-loop`'s own (new, unrelated)
      use of `nightly_report.md` and `tasks/sample/walkthrough.template.md`.
- [x] 4.4 Run pre-commit against all changed files.
