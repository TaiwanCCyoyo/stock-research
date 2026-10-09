# Fork Maintenance Guide

This project is a soft fork of [agent-starter-kit](https://github.com/TaiwanCCyoyo/agent-starter-kit).
It inherits the agent infrastructure (Claude Code, Codex, Agents layers) and adds
Stock-specific features on top. The goal is to stay close to upstream while
retaining only differences justified by current owner goals or concrete Stock requirements.

## Upstream Remote

Use the owner-maintained `.references/agent-starter-kit` clone in the primary checkout for local comparisons. Historical notes below retain the former `.tmp/` path as evidence.

```bash
git remote add upstream https://github.com/TaiwanCCyoyo/agent-starter-kit.git
git fetch upstream
```

## Default Rule

**Any shared file not listed in the "Intentional Divergences" table or supplemental audit list below should be kept
identical to upstream.** Sync it with:

```bash
git checkout upstream/main -- <path>
```

The divergence table records decisions to reassess, not permanent exemptions. Before replacing an affected path, compare the recorded upstream base, current Stock file, and new upstream version. Resolve undocumented local edits before overwriting; a previously reviewed local improvement can already implement or intentionally differ from the incoming change.

### Documentation Update Caution

Upstream README and documentation updates can change a document's structure,
headings, lists, links, and code fences substantially. Context-based patches may
therefore fail or leave a translated document stale. For divergent documentation,
compare the complete upstream source, update the corresponding local document as
a whole when appropriate, and verify links and code blocks after the sync.

## Intentional Divergences

The owner requested a compact root contract on 2026-09-20: no skill/agent-name
routing, duplicated pre-commit rules, or generic model instructions. Use the current upstream contract with only justified Stock language/research
differences; descriptions select skills and agents.

| Surface                                                                                                     | Stock difference and sync approach                                                                                                                                                                     |
| ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `AGENTS.md`                                                                                                 | Upstream 5992dfc contract, including session-owned worktree lifecycle and Stock owner-authorized merged-task cleanup, plus flexible prose language and Stock research/data boundaries.                 |
| `CLAUDE.md`                                                                                                 | Removed at the owner's explicit request; do not recreate an import or injection hook. Claude uses supported native AGENTS loading or explicitly reads the root contract before local review.           |
| `docs/en/stock-agent-operations.md`                                                                         | Preserved Stock data-copy, backup, submodule and reporting detail; read on demand.                                                                                                                     |
| `docs/en/git-workflow.md`, `docs/*/pr-*.md`                                                                 | Stock destination and pending setup; sync and policy-review follow-ups have scoped PR authorization; CI/review are active, branch protection is plan-limited.                                          |
| `.claude/settings.json`                                                                                     | Adopt upstream push-policy removal; retain only configuration with a current Stock purpose.                                                                                                            |
| `.githooks/pre-commit`                                                                                      | Invoke checks through the configured hooks directory alongside Stock's post-checkout hook.                                                                                                             |
| `.github/workflows/ci.yml`                                                                                  | Run change-range hooks except mypy (local only); prose-only changes skip shared-tool tests; do not expand targeted typing to unrelated legacy files or require private data.                           |
| `.gitignore`, `pyproject.toml`, `uv.lock`                                                                   | Preserve research ignores and Stock dependency graph; never copy the upstream lock wholesale. This infrastructure sync does not upgrade Stock's runtime AnyIO.                                         |
| `scripts/file_hygiene.py`, its tests, `.pre-commit-config.yaml`                                             | Preserve UTF-8-only hygiene and Stock targeted type checks; adopt serial mypy execution.                                                                                                               |
| `.claude/hooks/claude_post_tool_use_hygiene.py`, `.codex/hooks/codex_post_tool_use_hygiene.py`, their tests | Preserve read-only argument separation, one batch, explicit patch fields and bounded advisory output.                                                                                                  |
| `.codex/agents/{signal-miner,researcher,doc-translator}.toml`                                               | Preserve bounded delegation, research authorization and target-language routing; shared helpers follow upstream model updates while the Stock researcher keeps its registered execution configuration. |
| `scripts/tests/test_agent_instruction_contract.py`                                                          | Preserve Stock role subsets and research constraints; retire assertions about removed entrypoints and superseded prose.                                                                                |
| `.codex/skills/{python-development,python-testing,stock-backtest-report,stock-research-query}/SKILL.md`     | Adopt upstream logging and log-driven debugging guidance; preserve Stock verification and connected-tool routing. Generic FastAPI/security guidance is retired with upstream.                          |
| `.codex/skills/openspec-*/SKILL.md`                                                                         | Retired in stock-research; do not reintroduce OpenSpec skills or OPSX commands. Preserve historical contracts as read-only reference.                                                                  |
| `.codex/skills/{fork-maintenance-sync,dependabot-remediation}/SKILL.md`                                     | Preserve scoped checks; resolve the reference clone from the primary checkout.                                                                                                                         |
| `README.md`, `docs/zh-TW/README.md`, component references                                                   | Retain Stock identity, headless research entrypoint and private role/skill rows while removing retired integration references.                                                                         |

## Stock-Only Paths (reassess instructions; preserve artifacts and data)

- `.claude/agents/strategy-diagnostician.md`
- `.codex/agents/researcher.toml`
- `.codex/skills/market-data-cache/`
- `.codex/skills/stock-backtest-report/`
- `.codex/skills/stock-research-query/`
- `.codex/skills/design-notion-pages/`
- `.codex/skills/fork-maintenance-sync/`
- `.claude/commands/fork-maintenance-sync.md`
- `.claude/rules/common/data-structures.md`

## Sync Workflow

```bash
# 1. Fetch latest upstream
git fetch upstream

# 2. Review what changed since last sync
git log <last-sync-commit>..upstream/main --oneline

# 3. Identify affected files
git diff <last-sync-commit>..upstream/main --name-status

# 4. For each file:
#    - Not in Divergences table: sync wholesale:
git checkout upstream/main -- <path>
#    - Removed upstream: delete explicitly; checkout cannot restore an absent path:
git rm -- <path>
#    - In Divergences table: apply diff manually

# 5. After verification, update "Last Synced" and include it in the scoped local commit
```

## Last Synced

upstream commit: `5992dfc361e03c8983ac4a66c41468e5a20aef58` - feat(git): enforce worktree lifecycle (#17)

Notes:

- **2026-10-09 sync (`d1eeee8..5992dfc`).** Fast-forwarded the owner-requested primary reference; Stock `main` was already current at `324bbfc`. Imported the upstream read-only inventory and its behavioral tests unchanged, adopted session ownership, task checkout reuse, preserved probe removal, five-worktree budget, abandoned-work reporting and PR-state-based merge evidence. Preserved Stock delivery/merge authority and production/data safeguards. Applied the Stock portion of Claude's `20261010-agents-md-worktree-suggestion.md` from the primary `.tmp/claude-kline/`: reusable datasets have a primary task location, immutable caches keep their existing versioned primary location, and new feature/label/price variants reuse canonical definitions or declare a new version. Frozen mutable input snapshots remain explicit copies; no blanket deduplication or retroactive result migration. Cleanup must separately inspect ignored producer-submodule data because generic byte totals omit tracked submodules. Existing canonical-data provenance, backups and preservation gates still apply; no unrelated worktrees are removed. Verification: 25 inventory regression tests passed on Windows; normal commit hooks and hosted CI/review are recorded with the task delivery. This session creates no worktree; it uses the clean primary checkout on `codex/sync-starter-kit-lifecycle-20261009`.

- **2026-10-05 owner clarification after #24.** The owner confirmed that merged-task automatic cleanup is intended for Stock too: after verifying merge into `main`, the acting session may update local `main` and remove its own task worktrees, local branches and corresponding approved `origin` branches without asking again. Updated the current root contract, Git workflow and both READMEs to record this standing authorization. The earlier sync note below describes the initial conservative interpretation, superseded by this clarification. Existing preservation checks, submodule delivery authority, production gates and separate scheduler permissions remain effective.

- **2026-10-05 sync (`7e0c524..d1eeee8`, 1 commit).** Fast-forwarded the clean primary reference and started an isolated task worktree from current Stock `origin/main` at `13723d2`, including merged #22 and #23. Adopted the post-merge preservation, merged-state verification, clean fast-forward, remote-deletion lease and host-lifecycle procedure in root guidance, Git workflow and both READMEs. Reset the upstream repository-specific standing grant: Stock cleanup still requires explicit owner authorization. Retained #23's proactive producer improvements and two-stage PR delivery, including the already-authorized primary producer update after owner merge when its existing gates are met. Added Stock-specific protection for physical data copies, needed ignored research artifacts, canonical-data handoffs, initialized-submodule removal limitations, production writers and separately authorized scheduler operations. Stock pulls explicitly disable recursive submodule updates. Verification uses base/local/upstream document comparison and normal commit hooks; this sync performs no worktree deletion, producer update, data acquisition, backtest or scheduler change.

- **2026-10-03 sync (`4eeebf4..7e0c524`, 1 commit).** Fast-forwarded the clean primary-checkout reference and started a fresh task worktree from Stock `origin/main` at `1fb18ea` (including Stock #16). Adopted upstream Communication guidance, including simple text by default, relationship-based visuals, selective interactive HTML, visible findings/risks/uncertainty/verification summaries, decision export and self-contained HTML guidance. Stock adapts the opening sentence to describe the section's purpose as presentation preferences for task explanations and deliverables. Existing Review And Security rules remain intact. Adapted the two upstream README changes into Stock's existing English defaults and Traditional Chinese agent-workflow sections instead of importing starter-kit setup instructions. Existing owner communication guidance already covers plain language, concrete units and optional interactive comparisons; retained it without duplicating or weakening research-record precision. Preserved all Stock research/data rules, historical evidence, scoped delivery/merge authority, security settings, hooks, dependencies and the price-submodule pin. Verification uses direct base/local/upstream document comparison and normal commit hooks; no wording-only tests, downloads, backtests, scheduler changes or #14 changes are part of this sync.

- **2026-10-03 sync (`023c926..4eeebf4`, 3 commits).** Updated the owner-requested `.references/agent-starter-kit` checkout with a clean fast-forward and integrated from refreshed Stock `origin/main` in a dedicated worktree. Adopted upstream's new-request branch freshness rule; removed the three local reviewer roles, their role-only test, and generic FastAPI/security guidance; retained hosted PR review and root severity/authority boundaries. Updated shared Codex helpers to upstream models (`gpt-6-luna`, `gpt-6.1-sol`) while preserving Stock researcher authorization/configuration, bounded evidence delegation, target-language routing, compact commit wrappers and normal hooks. Stock's lock already contains PyJWT 2.15.0, so no dependency or lock change is needed. Reconciled English and Traditional Chinese component references, preserving Stock-specific entries and targeted typing. PR follow-up also corrects retired-reviewer claims in both READMEs and documents Claude's supported native AGENTS loading, precedence, and explicit-read fallback before local review without adding a shim/hook. Verified local Claude version 2.1.282, user loading settings and absence of project/ancestor overrides against official documentation; an external-model live-session probe was rejected by automatic approval review and was not run. Local role contract: 8 passed; normal commit hooks passed. Initial PR CI: 44 headless compatibility tests, 666 shared-tool/hook tests and 96 viewer/API tests passed, 1 skipped. Final-head checks/review are reported with the PR; no backtest, market-data refresh, direct main integration, or repository-setting change is part of this sync.

- **2026-09-20 policy review.** Removed stale push settings, duplicate commit checks, mandatory Claude commit delegation and obsolete prose/model assertions. Reassessed local skills: retired the holdout-coupled night-loop entrypoint, aligned bounded study execution and diagnosis with the current owner contract, and reused explicit OpenSpec selections. See `docs/en/agent-policy-review.md` for decisions and retained differences.

- **2026-09-20 sync (`57ea7ff..119f15e`).** Consolidated the owner-pruned Stock contract at root, removed SessionStart injection and Antigravity, imported PR workflow/CI and serial mypy, and preserved private data/research rules and local permissions. Kept a Claude import shim and moved detailed Stock operations to an on-demand document. Added an English/Traditional-Chinese comparison. Stock runtime dependencies remain unchanged. Verification and PR status are recorded with the delivered commit/PR; no direct main integration or repository-settings mutation is part of this sync.

- **2026-09-08 sync (`4ca1468..57ea7ff`, 4 commits).** Adopted unique Claude/Codex hook module names, targeted Pyright, mypy coverage of both hook trees, and removal of redundant Claude Python rules. Merged the Pyright development dependency into Stock's own lock (no runtime dependency upgrades). Preserved Stock UTF-8-only hygiene, permissions, owner/data boundaries, private skills, bounded delegation and read-only Ruff argument separation; existing hook bodies were renamed without modification. Updated active routing references and retained the Stock research-first documentation. The new gate also prompted local pandas type narrowing in the query/API layer and explicit rejection of a missing trade date. Verification: hook/shared-tool suite 127 passed, 1 Windows symlink test skipped; query suite 33 passed; API suites 51 tests passed; changed-file pre-commit including both mypy and Pyright passed; `uv lock --check` passed. Tests exercise script entrypoints, not live desktop matcher dispatch. No research, data backfill, objective change or research-worktree synchronization was performed.

- **2026-09-06 sync (`0bdeeb0..4ca1468`, 2 commits).** Reconciled upstream workflow simplification with the local Codex audit rather than replacing reviewed Stock guidance. Adopted prepared-environment hook execution, timeout and bounded instruction reads, explicit patch fields, removal of commit-subject injection, optional commit delegation, trust-boundary review routing and Sol high security review. Preserved Stock research/owner rules, private skills, proportional checks, batched read-only Ruff, explicit `continue: true`, and bounded advisory output. Updated sync entrypoints to compare base/local/upstream and removed obsolete CJK allowance instructions. Fixed the Claude Ruff argument boundary for option-like filenames, with a real-entrypoint non-mutation regression. Verification: hook/shared-contract suite 70 passed, followed by the affected Claude hook suite 9 passed after the argument-boundary fix; live desktop matcher dispatch remains unverified.

- **2026-08-31 sync (`d24b9f1..0bdeeb0`, 2 commits).** Adopted upstream's removal of the Codex AI co-author trailer requirement and Claude attribution settings. Preserved Stock's existing autonomous skill-authoring authorization in `CLAUDE.md` and `.codex/AGENTS.md`, plus Stock-specific Claude settings and all other documented divergences.

- **2026-08-27 sync (`b9fe391..d24b9f1`, 1 commit).** Removed the obsolete Antigravity `agy` delegation surface from Claude/Codex settings and guidance, deleted `.codex/skills/antigravity-subagent/`, and synchronized the English and Traditional Chinese component references. Preserved Stock's permission, language, research, and private-skill divergences.

- **2026-08-23 sync (`bc827f7..b9fe391`, 1 commit).** Adopted upstream's
  Codex sandbox/permission-failure handoff rule and its regression coverage in
  `.codex/AGENTS.md` and `scripts/tests/test_agent_instruction_contract.py`.
  Preserved Stock's standing commit authorization, research-specific agents,
  Traditional Chinese and mixed-language guidance, `T201` research-script
  exception, private skills, and broader agent-set assertions.

- **2026-08-23 sync (`277c300..bc827f7`, 1 commit).** Adopted upstream's explicit commit routing modes across Claude and Codex commit-specialist guidance, clarified that pre-commit runs in every mode, and documented that specialists must not self-promote into diff review. Updated the English and Traditional Chinese Codex component references and extended the contract tests while preserving Stock-specific agent assertions.

- **2026-08-23 sync (`d797f90..277c300`, 2 commits).** Adopted the safer Codex commit workflow: `commit-specialist` owns staged-content review, pre-commit, one ordinary bounded hook recovery, message drafting, and normal commit execution; sandbox or permission failures hand back to the main agent without cache or ACL workarounds. Updated the Codex contracts, component references, and regression assertions while preserving Stock's standing main-agent authorization and language guidance.

- **2026-08-23 sync (`ab7a003..d797f90`, 4 commits).** Removed upstream's generic `github-ops` skills and common rules that were folded into `CLAUDE.md`, added the focused `dependabot-remediation` skills, and updated GitHub workflow documentation and dependency locks. Preserved Stock's `GEMINI.md` language guidance, data-structure rule, research-specific content, private skills, and remote-mutation authorization boundaries.

- **2026-08-23 sync (`361f588..ab7a003`, 2 commits).** Reconciled the Antigravity layer with upstream: moved its shared operating contract to `GEMINI.md`, removed the legacy fragmented `.agent/rules/` and generic skills that upstream retired, added the focused `python-testing` and `antigravity-subagent` skills, and switched the Antigravity PostToolUse hook to read-only Ruff correctness diagnostics. Added the matching Codex, Claude, English, and Traditional Chinese routing documentation and regression coverage. Moved Stock's language guidance into `GEMINI.md`, while preserving its research-specific README and agent guidance, private skills, and unrelated untracked task work.

- **2026-08-22 sync (`1cb694f..361f588`, 1 commit).** Removed Claude Code's
  legacy `SessionStart` hook and its tests, removed the matching settings and
  README entries, and updated the agent-instruction contract to assert that
  Claude exposes only `PostToolUse`. Preserved Stock-specific permissions and
  hook configuration in `.claude/settings.json`.

- **2026-08-21 sync (`20d466b..1cb694f`, 7 commits).** Pulled from the local
  `.tmp/agent-starter-kit` clone (not `.references/agent-starter-kit` — that path never existed on
  this machine; the skill, the Claude command, and this guide's own workflow commands all pointed
  at the wrong location and were corrected here). Upstream retired its entire shared-memory stack
  (`.memories/` SQLite, the `memory-db` MCP server and `.mcp.json`, `memory-manager`/`memory-sql`/
  `save-memory`/`compress-memory`/`skill-curator`/`worktree-memory-sync` skills, `memory-auditor`/
  `memory-compressor` agents, `memory_health_check` hooks, the `Stop` hook event on every agent) in
  favor of each agent's own native local memory (Claude Code's built-in memory, Codex's
  `.codex/config.toml` `memories = true`). The user explicitly confirmed migrating Stock the same
  way rather than keeping the shared system, after checking that `.memories/memories/MEMORY.md` and
  `USER.md` were already duplicated in Claude Code's built-in memory (`~/.claude/projects/<project>/
memory/`) — no content was lost. `.memories/` (git-ignored) was deleted from disk and dropped from
  `.gitignore` and the Stock-Only Paths list above; all memory-system skills/agents/hooks/rules
  listed above were deleted to match upstream, `.claude/settings.json`'s `enabledMcpjsonServers` and
  the `mcp__memory-db__read_query` permission were removed, and `CLAUDE.md`/`.codex/AGENTS.md`'s
  Memory sections were rewritten to upstream's built-in-memory routing text. New upstream
  `.claude/rules/common/skill-authoring.md` / `.claude/rules/common/memory.md` and
  `.codex/AGENTS.md`'s new `## Skill Authoring` section were adopted wholesale. This same commit
  range also carried an unrelated commit-attribution overhaul (Claude-side `Co-authored-by`
  trailers dropped entirely; Codex keeps its trailer) and explicit delegation-mode wording for the
  commit specialists — both non-memory changes, synced wholesale via the already-divergent
  `commit-specialist`/`doc-translator`/`gen-commit`/`commit-helper` files.
  `scripts/tests/test_agent_instruction_contract.py` was rewritten against upstream's new version:
  two tests already existed upstream at `20d466b`
  (`test_agent_instructions_delegate_pre_commit_owned_checks`,
  `test_root_agent_instructions_remain_bounded_routing_maps`) but had never been synced into Stock —
  closed that gap in the same pass. The line-count bound in
  `test_root_agent_instructions_remain_bounded_routing_maps` was widened for `.codex/AGENTS.md`
  (140 vs. upstream's ~90) since Stock's file carries two whole sections
  (`Codex Private Skills`, `Codex Command-Like Skills`) with no upstream equivalent. Two
  undocumented pre-existing divergences were found and fixed while touching adjacent content:
  `.agent/rules/LANGUAGE_RULES.md`'s CJK boundary list was missing `.tmp/`/`.references/` (added
  to the Divergences table above), and `scripts/tests/test_file_hygiene.py` had an
  upstream-removed `test_memory_paths_allow_cjk` test alongside Stock's own
  `test_openspec_paths_allow_cjk` (added to the Divergences table above). Full verification: `uv
run python -m pytest tests/ -m "" -q` (291 passed, unchanged baseline),
  `.claude/hooks/tests .codex/hooks/tests scripts/tests` (57 passed), and `pre-commit run` against
  every touched file (prettier reformatted several files; clean on rerun).

- **2026-08-08 follow-up pass (same `20d466b` sync point, no new upstream commits).** The user
  flagged that `.claude/agents/planner.md` and `CLAUDE.md`/`.codex/AGENTS.md` had drifted much
  further from upstream than the Divergences table implied, and asked for a direct diff against
  upstream's current files rather than incremental line-by-line judgment calls. Findings and
  actions:
    - `.claude/agents/planner.md` was a stale, unapplied instance of upstream's own 2026-06-08
      removal (superseded by Native Plan Mode) — generic ECC content (Stripe worked example, no
      Stock content), never referenced by CLAUDE.md's Subagents list or any command. Deleted;
      removed from Stock-Only Paths below; added a regression assertion
      (`"planner" not in actual_agents`) to `test_agent_instruction_contract.py`.
    - `CLAUDE.md` (116 → 54 lines) and `.codex/AGENTS.md` (166 → 132 lines) were rebuilt starting
      from upstream's current full text, re-inserting only facts with no upstream or skill-file
      equivalent (paths, the `shioaji_stock_prices` submodule-ownership rule, Codex's private-skill
      file list and command-like-skill triggers). Verified before cutting, not assumed: the detailed
      agent model-tier routing prose in both files duplicated `docs/en/{claude,codex}-components.md`
      (already wholesale-synced and confirmed byte-identical to upstream); the Memory section's
      routing-table detail duplicated `.claude/skills/{memory-manager,memory-sql}/SKILL.md` and
      `.claude/rules/memory/storage.md`; each subagent's "stop and return the failed step" SOP is
      already in that agent's own file. Adopted upstream's short Prompt Defense and folded
      Learning-And-Escalation content on the reasoning that both restate safety/escalation behavior
      already covered by the outer harness system prompt.
    - `CLAUDE.md`'s title ("AI Agent Starter Kit" — the wrong project name) and its Scope section's
      claim that "Karpathy behavioral guidance is supplied by the installed Claude plugin" were both
      stale/wrong: `.claude/settings.json` has `andrej-karpathy-skills@karpathy-skills: false` and
      `superpowers@claude-plugins-official: false` (also test-asserted). CLAUDE.md's own superpowers
      paragraph (naming 8 `superpowers:*` skills as "always-available") was equally dead. Removed
      all three; also removed the now-unnecessary "superpowers is Claude-only" explanatory sentence
      from `.codex/AGENTS.md` (added earlier this session, no longer needed once the dead references
      were gone) and the `superpowers:finishing-a-development-branch` references in
      `docs/zh-TW/claude-components.md`'s Rules section. Per explicit user instruction, `.agent/`
      (which holds a real, non-empty local MIT-licensed port of the superpowers techniques) was left
      untouched and not investigated further — its actual discovery/invocation mechanism for Claude
      or Codex remains unconfirmed.
    - Fixed four files hardcoding `c:\Users\xjp01\Documents\Stock` or
      `C:/Users/<user>/Documents/Stock/.tmp/agent-starter-kit` (wrong drive/path even for the
      original machine): `.claude/commands/diagnose-strategy.md`, `.claude/commands/fork-maintenance-sync.md`,
      `.codex/skills/fork-maintenance-sync/SKILL.md`, `.claude/agents/strategy-diagnostician.md`.
      Replaced with repo-relative resolution (`git rev-parse --show-toplevel` or plain relative
      paths run from the repository root) per the user's stored preference for repo-relative paths.
    - Fixed a real (not cosmetic) bug in `.codex/AGENTS.md`'s Scope section: it referenced
      `.agents/` (plural), which does not exist — the actual directory is `.agent/` (singular).
    - `docs/zh-TW/claude-components.md` still needs the same full reconciliation pass (stale hook
      name `stop_memory_check.py` → `memory_health_check.py`, missing Stock-only
      agents/commands/skills rows, dead `code-reviewer`/`evidence-gatherer` agent references) —
      tracked as a following step in this same session, not yet complete as of this note.

- `20d466b` was pulled from the local `.tmp/agent-starter-kit` clone (range `66286d0..20d466b`,
  6 commits: `e83c4f2`, `3cbf16e`, `6c4617b`, `bef5977`, `f3ef15b`, `20d466b`). Every non-divergent
  candidate file was diffed against the prior sync point (`66286d0`) before being overwritten;
  three files (`.claude/hooks/memory_health_check.py`, `.codex/agents/commit-specialist.toml`,
  `.codex/agents/signal-miner.toml`) showed byte differences that were confirmed to be CRLF-only
  (Stock's Windows checkout vs. the clone's LF), not real content drift, so they were synced
  wholesale too.
- Removed upstream: `.claude/rules/common/coding-style.md`, `.claude/rules/python/patterns.md`,
  `.claude/commands/compress-memory.md`, `.claude/commands/memory-sql.md`,
  `.claude/commands/save-memory.md`. The three command files are redundant wrapper files only —
  the underlying skills (`compress-memory`, `memory-sql`, `save-memory`) are kept and still
  resolve as `/<skill-name>` because the Skill tool registers each `.claude/skills/<name>/SKILL.md`
  by its own `name`. Applied the same removal to CLAUDE.md's Commands and Skills table (previously
  an enumerable table at L100-110, now prose) and to `docs/zh-TW/claude-components.md`.
- Also removed `.claude/skills/cost-aware-llm-pipeline/SKILL.md` and
  `.claude/skills/llm-trading-agent-security/SKILL.md`, matching upstream's own removal in
  `bef5977`. Verified first that neither skill had any inbound reference outside the component
  catalogs (`docs/en/*`, `docs/zh-TW/claude-components.md`) — Stock's engine is a rule-based
  backtester, not an LLM-signing trading agent or an LLM-API caller, so upstream's "dormant ECC
  demo skill, never matched" rationale applies here too, not just in the upstream meta-tooling repo.
- Applied `3cbf16e`/`6c4617b`'s "trim model-derivable guidance" principle to CLAUDE.md's Memory
  section: dropped the redundant "secrets, credentials" clause from the "keep X outside memory"
  bullet (secrets are already covered by the Operating Contract) but kept the
  "plans, raw transcripts, command narration, ... private user data" clause, since — unlike
  upstream's own (shorter) Memory section — that guidance is not restated anywhere else in Stock's
  CLAUDE.md.
- `docs/en/claude-components.md` and `docs/en/codex-components.md` were confirmed byte-identical
  to upstream at `66286d0` before this sync (Stock has never diverged them — only the zh-TW
  translation carries Stock-specific rows), so both were synced wholesale rather than manually
  merged.
- `scripts/tests/test_agent_instruction_contract.py` was not touched upstream this round, but
  three of its assertions broke because they hard-coded exact upstream wording that changed:
  `test_signal_miner_descriptions_proactively_route_high_output_commands` required the literal
  phrase "delegate before running" in both the Codex and Claude signal-miner descriptions, but
  upstream's `20d466b` reworded only the Codex side to "when delegation is authorized"; and
  `test_commit_agents_use_formal_coauthor_identity_trailers` /
  `test_commit_model_attribution_uses_codex_coauthor_identity` required the literal
  `Co-authored-by: Codex gpt-5.6 <codex@openai.com>` trailer inside
  `.codex/agents/commit-specialist.toml`, but `bef5977` deduplicated that trailer text out of the
  `.toml` file in favor of a pointer to `.codex/skills/gen-commit/SKILL.md` as the sole source of
  truth. Updated the three assertions to check the new (semantically equivalent) wording instead
  of reverting upstream's dedup.

- `66286d0` (previous sync point) was pulled from the local `.tmp/agent-starter-kit` clone.
  Ordinary paths were synchronized wholesale; divergence paths preserved Stock memory, language,
  research, and agent-routing behavior while adopting the native workflow and disabled external
  plugin configuration. The Stock-only `research-report-drafter` and other custom agents remain
  covered by subset assertions.

- `5ca8fb4` (permission allowlist trim) and `8740634` (extend prettier coverage to all
  supported file types) were applied. `8740634` touched `.claude/hooks/post_tool_use_hygiene.py`,
  `.claude/hooks/tests/test_claude_post_tool_use_hygiene.py`, `.pre-commit-config.yaml`, and
  `.vscode/settings.json` — none are in the Divergences table, so they were synced wholesale.
- `5ca8fb4` only removed permission keys from `.claude/settings.json`. Per the Divergences table
  rule ("add new upstream keys; never overwrite existing blocks") there was nothing to merge
  automatically, but the user explicitly asked to mirror the trim locally too, relying on
  `defaultMode: "auto"` instead of a large explicit `allow` list. Applied upstream's exact
  `allow`/`deny` lists; kept `additionalDirectories: ["~/.claude"]` (not present upstream) since
  it is a hard file-access scope boundary, not just a prompt bypass, and the auto-memory system
  depends on it.
- `ca9319b` itself (the full-project Prettier reformat) is recorded as synced here, but its file
  content changes were deliberately **not** applied to Stock's existing files at sync time. Stock
  later ran its own project-wide `prettier --all-files` / `taplo-format --all-files` pass using the
  synced `.pre-commit-config.yaml` config, and mirrored the same `prettier`/`taplo-format` hooks
  plus `.prettierrc.json` into the `shioaji_stock_prices` submodule so both repos format
  consistently.

- **2026-09-21 sync (`119f15e..97f51b6`).** Adopted upstream removal of redundant check instructions in reviewers, commit roles, dependency skills and Python guidance; removed `scripts/auto_format.py`. Compact Stock commit wrappers already implement optional delegation and commit-hook-only execution, so upstream verbose wrappers were not reintroduced. Root AGENTS.md now follows the shared upstream contract, differing only in prose language and Stock research/data boundaries. Removed CLAUDE.md at the owner's request without replacement injection. Local mypy/Pyright and remote Pyright check scopes remain as approved.

- **2026-09-21 local upstream follow-through (`7e9ace6`).** Adopted the PR lifecycle addition from the owner's clean `D:/Project/agent-starter-kit` checkout. The read-only reference and GitHub upstream still point to `97f51b6`; this is an explicitly recorded local-source addition, not a claim that the reference advanced. CI and current-head review, scoped fixes and verified thread resolution belong to delivery; merging remains owner-controlled.

- **2026-09-21 sync (`4e10cf7..023c926`).** The formally released `4e10cf7` matches the previously adopted local follow-through change. Adopted `023c926`: resolve verified, pushed fixes before renewed review, verify actual review start, and poll with three-to-five-minute backoff within host wait limits. This changes delivery sequencing, not merge authority or CI checks.
