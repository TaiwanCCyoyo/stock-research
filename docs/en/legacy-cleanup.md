# Retired-code cleanup

Owner-authorized cleanup on 2026-09-20 removes the three standalone scripts under
`legacy/`, the retired Panel server, and the holdout-coupled experiment iteration
runner with its private gate evaluator, runner/gate tests and obsolete skill.
Current repository entry points do not use these scripts.

The historical report renderer now owns only its journal-reading constants and
helpers; it no longer imports an execution runner. Its schema loader and tests
remain because existing experiment records still need to be readable.

Kept for current consumers:

- `research_lab/dashboard_core.py`, `display.py` and Panel: the current API and
  optional `scripts/build_research_dashboard.py` still use this shared layer.
- OpenSpec archives, research missions, journals and results.
- Runtime compatibility for old result schemas and price inputs: a legacy label
  alone does not mean the behavior is unused.

Deleted source remains available in Git history. This cleanup does not run
research, change caches, or remove submodule files.

On 2026-09-21, the remaining ten obsolete documents under `legacy/` were
removed at the owner's request, including old agent/memory-system descriptions,
handoff notes and schema documentation. The directory has no current consumers;
Git history preserves these documents. The obsolete mypy exclusion and directory
references were removed. No formatter or type-checking gate was weakened.

The retired `.agent/` Antigravity skills and workflows were also removed.
OpenSpec context now follows the shared contract instead of repeating the
superseded English-only and local-customization-preservation rules.
The owner subsequently requested removal of `CLAUDE.md`; no replacement import
or instruction-injection hook is installed.
