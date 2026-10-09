## Context

`.codex/skills/notion-research-report/` and `scripts/generate_task_report.py` were built to
turn local task artifacts into a Notion research page via Codex. The user has confirmed this
architecture was found unreliable in practice a while ago and is no longer used; a repo audit
confirmed it has no remaining programmatic consumer. This is a removal, not a redesign.

## Goals / Non-Goals

**Goals:**

- Delete the unused flow and every file that exists only to support it.
- Leave no dangling references (test assertions, agent rosters, docs, prompt strings, spec
  text) pointing at deleted files.
- Free the `nightly_report.md` filename for `add-autonomous-research-loop`'s unrelated nightly
  report.

**Non-Goals:**

- No change to `openspec/specs/research-output-safety/spec.md`: its "Prepare Notion output"
  scenario is generic guidance for any Codex-authored Notion page, not specific to this flow,
  and other live Notion-facing skills (e.g. `.claude/skills/notion-dev-log`,
  `.codex/skills/design-notion-pages`) still need it.
- No change to `research_lab/dashboard_core.py`'s `artifact_link_targets`: it already skips
  missing paths, so it needs no edit and still serves the one real historical task directory
  that has these files.
- No deletion of existing task artifacts under `tasks/20260510-two-b-template-smoke/`
  (`nightly_report.md`, `walkthrough.md`, `visual_report.html`, `notion_report_payload.json`,
  `research_report/`). Those are real prior output, not code; deleting them is irreversible and
  provides no benefit.
- No change to `scripts/build_research_dashboard.py`, which the retired skill happened to call
  in its step 4 but which is independently required by the active `research-dashboard` spec.

## Decisions

- **Delete outright rather than deprecate-in-place.** The flow has zero programmatic
  consumers and no tests reference it; there is no migration path to build because nothing
  downstream depends on its output shape. A deprecation shim would only add dead code.
- **Also retire `build_walkthrough()` / `walkthrough.md`**, not just the `nightly_report.md`
  half of `generate_task_report.py`. Both are produced by the same script for the same
  (retired) audience; `walkthrough.md`'s only other consumer is under `legacy/gemini_agent/`
  (already retired), and `tasks/sample/walkthrough.template.md` remains as a template,
  unaffected by removing the generator.
- **Annotate `docs/zh-TW/Plan.md` §7.6 instead of rewriting it.** That document is a historical
  phase-by-phase roadmap (its §8 covers later phases already superseded); marking the section
  as retired preserves the historical record without pretending the plan was written knowing
  this outcome.

## Risks / Trade-offs

- [Some other undiscovered script still shells out to `generate_task_report.py`] → mitigated by
  the repo-wide grep verification step in tasks.md before archiving; if found, the change is
  extended rather than shipped with a broken caller.
- [Removing the `walkthrough.md`/`nightly_report.md` prompt lines from
  `create_research_task.py`/`prepare_nightly_research.py` changes what a Codex session is told
  to produce] → acceptable and intended: those instructions currently point at a generator that
  no longer exists, so removing them fixes a latent bug rather than introducing one.
