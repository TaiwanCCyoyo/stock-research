# Claude Code Components Reference

Current contract: `AGENTS.md`; the owner requested removal of `CLAUDE.md`. Use Claude Code 2.1.281 or later with built-in `agents-md` support enabled. It loads root `AGENTS.md` natively when no project or ancestor `CLAUDE.md`/`CLAUDE.local.md` takes precedence; this repository adds no import or injection hook. Before local implementation/security review, confirm the contract in `/context` or `/memory`. If native loading is unavailable or overridden, explicitly read root `AGENTS.md` before reviewing so its severity, secret classification, and authority boundaries apply. See [official instruction loading](https://code.claude.com/docs/en/memory#agentsmd). Historical removal notes below do not describe current rule loading.

This document lists all agents, commands, skills, hooks, and rules active in the `.claude/` directory.
Intended for Python and SystemVerilog/UVM developers.

**ECC source**: [affaan-m/ECC](https://github.com/affaan-m/ECC) v2.0.0-rc.1
**ECC integration date**: 2026-06-02
**Memory**: Claude uses Claude Code's built-in memory only; required repository guidance remains checked in — see `AGENTS.md` §Working With The Owner.

The project settings intentionally disable the external Superpowers, Ponytail, and Karpathy plugins. This reference describes the repository-owned Claude components plus native Claude capabilities; GitHub, skill-creator, and Pyright LSP remain enabled in `.claude/settings.json`.

---

## Agents

Agents are specialized subagents invoked by the main Claude session for focused tasks.

Claude auto-delegation is primarily guided by each agent's description and the current task context. `signal-miner` is the lowest-cost native read-only utility for bounded high-output commands. Route test suites, benchmarks, broad searches, verbose diagnostics, dependency traces, and large diff/log inspections to it when output isolation is worth a round trip; run short focused checks directly in the main context and use the built-in Explore agent for ordinary code location. `task-worker` is a mid-cost option only for a higher-tier main session to downshift bounded implementation with an explicit goal, scope, acceptance criteria, and verification. A lowest-cost main session handles simple work directly or uses built-in Explore or general-purpose as appropriate; it does not escalate to `task-worker`. Keep ambiguous, cross-cutting, security-sensitive, architectural, and planning work with the main session or a suitable built-in agent.

Claude keeps `model: "opusplan"` in `.claude/settings.json`: native Plan Mode uses `opus`, and execution uses `sonnet`. Custom agents are not used to transfer plans back to the main session.

### Workflow (original — not from ECC)

| Agent               | Model           | Tools                               | Purpose                                                                                                                                                                                           |
| ------------------- | --------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `commit-specialist` | haiku           | Bash, Read                          | Review staged changes and draft commit messages                                                                                                                                                   |
| `doc-translator`    | haiku           | Read, Write, Edit                   | Low-tier translator and synchronizer for any file-based translation into one explicit non-canonical target; the main session selects source and target, and its canonical document wins conflicts |
| `signal-miner`      | haiku           | Read, Grep, Glob, Bash              | Lowest-cost isolation for commands expected to produce large logs or stdout; returns concise signal instead of raw output                                                                         |
| `task-worker`       | sonnet (medium) | Read, Grep, Glob, Write, Edit, Bash | Implement explicit low-to-medium-risk tasks with acceptance criteria and verification; stop when scope or risk expands                                                                            |

### Not ported from ECC (with reasons)

| Agent                                                                                                                                              | Reason                                                                                                                                                                            |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `planner`                                                                                                                                          | Removed 2026-06-08 — superseded by Native Plan Mode (`EnterPlanMode`/`ExitPlanMode`)                                                                                              |
| `architect`, `code-reviewer`, `code-simplifier`, `loop-operator`, `performance-optimizer`, `python-reviewer`, `silent-failure-hunter`, `tdd-guide` | Removed 2026-07-13 — native Claude capabilities and focused reviewers cover their responsibilities without overlapping delegation.                                                |
| `implementation-reviewer`, `plan-reviewer`, `security-reviewer`                                                                                    | Removed 2026-10-02 — current models, native Plan Mode, built-in `/code-review`, hosted Codex PR review, and pre-commit gates cover them; the remaining agents exist to save cost. |
| `refactor-cleaner`                                                                                                                                 | Depends on Node.js tools (knip, depcheck, ts-prune); Python project                                                                                                               |
| `harness-optimizer`                                                                                                                                | Requires ECC-internal `/harness-audit`; not portable                                                                                                                              |
| All `*-build-resolver` (11 agents)                                                                                                                 | Non-Python languages not in use                                                                                                                                                   |
| Language reviewers (non-Python)                                                                                                                    | Unused languages                                                                                                                                                                  |
| `gan-*`, `seo-specialist`                                                                                                                          | Out of scope                                                                                                                                                                      |
| `homelab-*`, `network-*`, `healthcare-reviewer`                                                                                                    | Domain mismatch                                                                                                                                                                   |
| `marketing-agent`                                                                                                                                  | Deferred — add when short-form video planning starts                                                                                                                              |

---

## Interactive, Automated, and Company Use

- Interactive work: enter Native Plan Mode, approve the plan, then return to execution mode.
- Unattended work: use separate planning and execution sessions. The planning session writes a maintained plan artifact; the execution session reads the approved artifact. Do not use a planner subagent as the main-session handoff.
- Claude-only company copy: retain instructions, rules, agents, skills, and hygiene hooks as-is. Use organization-approved model IDs or alias mappings rather than this repository's personal-Pro defaults.

`REVIEW.md` is not part of the local baseline. Add it only when the repository is enrolled in Claude's managed Team or Enterprise Code Review service.

---

## Commands (Slash Commands)

### Workflow (original — not from ECC)

| Command       | Purpose                                                        |
| ------------- | -------------------------------------------------------------- |
| `/gen-commit` | Generate a Conventional Commit message via `commit-specialist` |
| `/worktree`   | Create, resume, and finish isolated task worktrees             |

Native Git/GitHub operations follow the [shared Git workflow contract](git-workflow.md). Local-only delivery is the default; owner-enabled PR delivery authorizes task-branch pushes and PR updates, while merge requires separate authorization.

### Removed (2026-06-10 cleanup — agents and built-in `/code-review` now cover these)

| Command          | Replacement                                                                   |
| ---------------- | ----------------------------------------------------------------------------- |
| `/build-fix`     | Native evidence-driven debugging + `python-testing` skill                     |
| `/code-review`   | Built-in `/code-review` (incl. `ultra` cloud review) + hosted Codex PR review |
| `/feature-dev`   | Native Plan Mode + native test-first workflow + `signal-miner` agent          |
| `/python-review` | `python-testing` skill and built-in `/code-review`                            |
| `/security-scan` | Built-in `/security-review` + `detect-secrets` gate                           |
| `/test-coverage` | `python-testing` skill (`pytest --cov`)                                       |

### Not ported from ECC (with reasons)

| Command                                         | Reason                                                                                                                            |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `/pr`, `/review-pr`                             | PR workflow not needed                                                                                                            |
| `/multi-*` (5 commands)                         | Multi-agent orchestration premature                                                                                               |
| `/learn`, `/skill-create`                       | Depend on ECC observation hooks and full instinct pipeline; replaced by the `skill-authoring` rule and the `skill-creator` plugin |
| `/evolve`                                       | Replaced by the `skill-authoring` rule and the `skill-creator` plugin                                                             |
| `/hookify-*` (4 commands)                       | ECC-internal hook management                                                                                                      |
| `/sessions`, `/save-session`, `/resume-session` | Replaced by Claude Code's built-in memory and session history                                                                     |
| Language-specific build/test/review             | Go/Rust/Kotlin/Java etc. not in use                                                                                               |
| `/cost-report`, `/model-route`                  | Add later if needed                                                                                                               |
| `/jira`, `/prp-*`, `/plan-prd`                  | No PM integration planned                                                                                                         |

---

## Skills

Skills are internal workflow documents loaded when a matching command or agent needs them.

### Workflow (original — not from ECC)

| Skill                    | Purpose                                                                   |
| ------------------------ | ------------------------------------------------------------------------- |
| `commit-helper`          | Conventional Commits format, scoped commit execution                      |
| `dependabot-remediation` | Read-only alert retrieval, minimum-safe upgrades, and completion evidence |

### Development (ported from ECC v2.0.0-rc.1)

| Skill            | Purpose                                                                                                                                   |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `python-testing` | Repository-specific behavioral tests, hook JSON fixtures, and Windows path behavior. Test-first decisions use native Claude capabilities. |

### Removed (2026-08-23 cleanup — native GitHub operations and focused security workflow)

| Skill        | Reason                                                                                                                                                                                                                                        |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `github-ops` | Generic issue, PR, CI, and release commands duplicated Claude's native `gh` capability and imposed multi-contributor stale policies. Dependabot work moved to `dependabot-remediation`; PR delivery follows the shared Git workflow contract. |

### Removed (2026-08-19 cleanup — `/learn-eval` never triggered in practice)

| Skill / Command                | Reason                                                                                                                                                                                                                                                                                                                                                                 |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `skill-curator`, `/learn-eval` | The manual port of ECC's holistic verdict gate and Hermes' curator lifecycle went untriggered — the only prompt was a weekly Stop-hook reminder. Replaced by the always-loaded `AGENTS.md` §Working With The Owner rule stating the durable intent (write a project skill when a task class will recur) plus the already-enabled `skill-creator` plugin for authoring. |

### Removed (2026-08-07 cleanup — dormant-by-design ECC demo skills, no downstream usage)

| Skill                        | Reason                                                                                                                                                                                                                                                                                                                     |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cost-aware-llm-pipeline`    | This repo never calls an LLM API (meta-tooling only), so the skill only matched by description in a downstream project; it hardcoded a stale model ID (`claude-sonnet-4-6`) and a 2025-2026 price table that would leak into generated code. Re-add from ECC when a project built from this kit actually calls an LLM API. |
| `llm-trading-agent-security` | No trading-agent functionality in this repo. Removing it narrows the `security-review` coverage claim below — restore if trading-agent work begins.                                                                                                                                                                        |

### Removed (2026-06-08 cleanup — native Claude verification now covers these)

| Skill               | Reason                                                                                                                                                    |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `coding-standards`  | Native guidance plus the narrowed `coding-style` rule cover this                                                                                          |
| `tdd-workflow`      | Replaced by the native test-first workflow                                                                                                                |
| `verification-loop` | Replaced by native testing, review, and pre-commit verification                                                                                           |
| `git-workflow`      | 716-line Git textbook; repo commit policy is now solely in the `commit-helper` skill (the `git-workflow` rule was also removed in the 2026-06-13 cleanup) |

### Not ported from ECC (with reasons)

| Skill                                      | Reason                                                                                                                                                                                                    |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `python-patterns`                          | Automated formatting belongs to repository gates; semantic guidance lives in Python rules                                                                                                                 |
| `deep-research`                            | Requires firecrawl + exa MCP — deferred until MCP configured                                                                                                                                              |
| `api-design`, `backend-patterns`           | Stock project is not a web backend                                                                                                                                                                        |
| `security-review`                          | Covered by built-in `/security-review` and hosted Codex PR review; trading-specific patterns (spend limits, circuit breakers) no longer covered since `llm-trading-agent-security` was removed 2026-08-07 |
| Non-Python language patterns               | Unused languages                                                                                                                                                                                          |
| `homelab-*`, `network-*`, `healthcare-*`   | Domain mismatch                                                                                                                                                                                           |
| `angular-developer`, `react-*`, `nextjs-*` | No frontend planned                                                                                                                                                                                       |
| `eval-harness`                             | Removed 2026-06-09: referenced nonexistent `/eval` commands and had no runner, graders, baseline format, Python commands, or CI integration. Restore only after those capabilities exist.                 |

---

## Hooks

Hooks are Python scripts executed automatically by the Claude Code harness.

| Hook                              | Trigger                 | What it does                                                                                                       |
| --------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `claude_post_tool_use_hygiene.py` | After Python Edit/Write | Runs read-only Ruff `E722,F601,F602,F634` diagnostics that complement Pyright; it does not format or modify files. |

Workspace editor defaults live in `.vscode/settings.json`: trim trailing whitespace, keep one final newline, use Ruff for Python formatting and explicit code actions, and exclude generated caches plus local agent state from search, watchers, and local history.

Claude Code uses the official Pyright plugin for immediate type-aware navigation and diagnostics. Its PostToolUse hook adds a read-only targeted Ruff check for `E722,F601,F602,F634`, which complements Pyright without repeating its common undefined-name and unused-symbol diagnostics. Both the hook command and its internal Ruff invocation use `uv run --no-sync` so an edit never triggers an environment resync. Complete Ruff linting and formatting are deferred to pre-commit, so normal edits do not trigger repository-wide formatting. Normal commits run `.githooks/pre-commit` for formatting and validation.

### ECC hook concepts noted but not ported

| Concept                         | Status              | Why                                                                                                                                      |
| ------------------------------- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| PostToolUse continuous learning | **Not implemented** | The hook-based observation pipeline (instinct YAML, background Haiku agent) is not ported — too heavyweight without a persistent process |
| Stop governance capture         | Deferred            | ECC logs security events at session end — relevant if project grows to include autonomous trading agents                                 |

---

## Rules

Rules are path-scoped markdown files loaded when Claude works with matching file types.

| Rule set        | Paths                 | Source                     | Notes                                                 |
| --------------- | --------------------- | -------------------------- | ----------------------------------------------------- |
| `rules/python/` | `**/*.py`, `**/*.pyi` | ECC v2.0.0-rc.1 (modified) | Logging and log-driven debugging, and pytest pointers |

Detailed procedures live in skills or agent definitions.

### Removed (2026-08-23 cleanup — merged into CLAUDE.md)

`rules/common/` matched `paths: "*"`, so it was injected on the first file access of any session regardless of content, making its only functional difference from CLAUDE.md a delivery-timing quirk rather than a real scoping benefit. Its routing content (review severity, security triggers, phase routing, skill authoring, memory routing, risk-based testing baseline) was folded directly into `CLAUDE.md`, and the directory was deleted.

| Rule                   | Reason                                                                    |
| ---------------------- | ------------------------------------------------------------------------- |
| `rules/common/*` (all) | No longer path-scoped in practice (`paths: "*"`); merged into `CLAUDE.md` |

### Removed (2026-06-13 cleanup — owned by skills and CLAUDE.md)

| Rule                        | Reason                                                                                                  |
| --------------------------- | ------------------------------------------------------------------------------------------------------- |
| `rules/common/git-workflow` | Shared authority lives in [git-workflow.md](git-workflow.md); `commit-helper` owns local commit checks. |
| `rules/common/agents`       | Agent index owned by CLAUDE.md `Subagents`; parallel-execution guidance migrated there                  |

### Removed (2026-08-07 cleanup — model priors and CLAUDE.md already cover these)

Because every `rules/common/` file matches `paths: "*"`, the set is injected on the first file access of any session, so its content competes with CLAUDE.md rather than deferring cost. Generic craft guidance was dropped and only non-derivable routing decisions were kept.

| Rule                                      | Reason                                                                                                                                       |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `rules/common/coding-style`               | Generic craft guidance duplicated CLAUDE.md `Engineering Discipline`; the structural review heuristic moved to `rules/common/code-review.md` |
| `development-workflow` §Research & Reuse  | Verbatim duplicate of CLAUDE.md `Engineering Discipline`                                                                                     |
| `development-workflow` §Pre-Review Checks | Generic pre-merge hygiene; CI and native GitHub operations own it                                                                            |
| `testing` §AAA and §Test Naming           | Generic pytest structure and naming examples; owned by `skill: python-testing`                                                               |
| `code-review` §Security Review Triggers   | Pointer-only section; the reviewer routing list already links `security.md`                                                                  |

### Not ported from ECC (with reasons)

| Rule set                                 | Reason                                                                                             |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `rules/typescript/`, `rules/react/` etc. | Unused languages                                                                                   |
| `rules/cpp/`                             | SV/UVM differs too much from C++; deferred — create `rules/systemverilog/` when UVM project starts |

---

## Deferred Items

| Item                            | Type                    | Condition                                                                                                      |
| ------------------------------- | ----------------------- | -------------------------------------------------------------------------------------------------------------- |
| `deep-research` skill           | ECC port                | Configure firecrawl + exa MCP first                                                                            |
| `marketing-agent` agent         | ECC port                | Short-form video planning confirmed                                                                            |
| `uvm-patterns` skill            | Custom build            | UVM project starts                                                                                             |
| `rules/systemverilog/`          | Custom build            | UVM project starts                                                                                             |
| Eval-driven development harness | Workflow infrastructure | Add a real runner, deterministic graders, baselines, repeated-run metrics, Python commands, and CI integration |
