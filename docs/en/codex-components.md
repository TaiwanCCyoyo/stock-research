# Codex Components Reference

Codex uses Native Plan Mode, native local memories, repo-scoped skills, specialist subagents, project hooks, and installed plugins. It reads the shared root `AGENTS.md`, which Codex discovers natively; repository-wide rules live there and nested `AGENTS.md` files scope rules to their own directory.

## Native And Plugin Equivalents

| Capability                                          | Codex implementation                                           |
| :-------------------------------------------------- | :------------------------------------------------------------- |
| Planning                                            | Native Plan Mode and `<proposed_plan>`                         |
| TDD, debugging, worktrees, completion verification  | Native Codex capabilities, project skills, and explicit checks |
| GitHub issues, PRs, CI, review comments, publishing | Installed GitHub plugin                                        |
| Slash commands                                      | Natural-language skill triggers                                |
| Cross-session planning                              | Native planning plus maintained plan artifacts                 |
| Cross-session recall                                | Native Codex local memories, enabled by project configuration  |

Codex keeps planning and implementation authority in the main agent. Read-only agents provide context-isolated evidence summaries from broad searches, logs, test output, diffs, or commands whose stdout would overwhelm the main context; they do not replace Codex Native Plan Mode or own publication and integration. The main agent follows the [shared Git workflow contract](git-workflow.md).

## Agents

| Agent               | Access        | Purpose                                                                                                                                                                                         |
| :------------------ | :------------ | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `signal_miner`      | Read-only     | Low-cost utility for substantial output isolation; returns concise evidence when delegation has a concrete benefit                                                                              |
| `task_worker`       | Bounded write | Implement explicit low-to-medium-risk tasks with acceptance criteria and verification; stop when scope or risk expands                                                                          |
| `doc_translator`    | Bounded write | Low-tier translator and synchronizer for any file-based translation into one explicit non-canonical target; the main agent selects source and target, and its canonical document wins conflicts |
| `commit-specialist` | Bounded write | Optional delegate for mode-dependent staged review and commits; sandbox failures return to the main agent                                                                                       |
| `researcher`        | Bounded write | Executes a parent-registered stock experiment in an isolated worktree; no direction changes, downloads, or gate tuning                                                                          |

### Model routing

| Tier                          | Model                  | Roles                                                                          |
| ----------------------------- | ---------------------- | ------------------------------------------------------------------------------ |
| Bounded implementation        | `gpt-6.1-sol` / medium | Routine, explicitly scoped implementation through `task_worker`                |
| High-volume mechanical work   | `gpt-6-luna` / medium  | Signal mining and commits                                                      |
| Translation                   | `gpt-6-luna` / low     | One explicit non-canonical document                                            |
| Registered research execution | `gpt-5.6-luna` / max   | Fixed commands, deterministic gates and metric extraction through `researcher` |

Use `explorer` for ordinary code location and `signal_miner` when substantial output isolation saves context. Run short checks locally; avoid same-tier handoffs without a concrete benefit. `task_worker` lets a higher-tier main agent downshift bounded implementation to Sol, while Luna handles mechanical work. Keep ambiguous, architectural, and security-sensitive judgment with the main agent; pull requests also receive hosted Codex review.

The shared four roles, built-in explorer, and Stock researcher cover current recurring work. Add a role only for a demonstrated gap. The main model remains user-selected; role model defaults do not establish measured cost savings or quality. Keep the bounded concurrency and depth defaults unless actual workloads justify changing them.

The main agent owns research direction, owner constraints and final acceptance. `researcher` keeps its existing model and bounded preregistered execution; shared helper updates do not change its authorization. Keep research enforcement and point-in-time validation. Delegate with exact paths, commands, stop conditions and compact context; reuse passing evidence and existing agents. If a helper hits a usage limit, complete safe work locally and report the remaining dependency. Model/config changes apply to newly loaded agents; already-running helpers may retain earlier settings.

## Skills

| Skill                | Purpose                                                                                        |
| :------------------- | :--------------------------------------------------------------------------------------------- |
| `python-development` | Python logging and log-driven debugging                                                        |
| `python-testing`     | Targeted behavioral tests, optional coverage, hook fixtures, and Windows-path requirements     |
| `gen-commit`         | Scoped local commits, optional specialist review and execution, sandbox handoff, and reporting |

## Claude Capability Decisions

| Claude capability                                               | Codex decision                       | Reason                                                                                                                                                                                                   |
| :-------------------------------------------------------------- | :----------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/plan`                                                         | Native/optional artifact replacement | Conversational planning is provided by native Plan Mode. Durable cross-session handoff uses a maintained plan artifact.                                                                                  |
| `plan-reviewer`, `implementation-reviewer`, `security-reviewer` | Removed 2026-10-02                   | Native Plan Mode, current model capability, hosted Codex PR review, and pre-commit gates cover them; remaining agents exist to save cost.                                                                |
| `/feature-dev`                                                  | Native replacement                   | Brainstorming, Plan Mode, test-first development, verification, and review already form the workflow.                                                                                                    |
| `/build-fix`                                                    | Native replacement                   | Evidence-driven debugging plus repository verification covers incremental diagnosis and repair.                                                                                                          |
| `/code-review`                                                  | Native/plugin replacement            | Local review uses the native Codex review stance; PR review uses the GitHub plugin.                                                                                                                      |
| `/python-review`                                                | Skill replacement                    | `python-testing` provides repository-specific behavioral tests and optional coverage guidance.                                                                                                           |
| `/security-scan`                                                | Agent and gate replacement           | detect-secrets, hooks, pre-commit, and hosted PR review are installed; AgentShield is not.                                                                                                               |
| `/test-coverage`                                                | Skill replacement                    | Optional coverage is part of `python-testing`; Codex does not need a command wrapper.                                                                                                                    |
| `github-ops`                                                    | Plugin replacement                   | The GitHub plugin supplies repository, issue, PR, CI, comment, and publishing workflows with current connector semantics.                                                                                |
| `cost-aware-llm-pipeline`                                       | Not ported                           | It is application-domain guidance with provider-specific model names and volatile pricing, not a Codex workflow. Create a shared, vendor-verified skill when this repository builds an LLM API pipeline. |
| `eval-harness`                                                  | Removed/deferred                     | It referenced nonexistent `/eval` commands and lacked a runner, grader implementation, baseline format, Python commands, and CI integration. Restore only after those capabilities exist.                |
| `llm-trading-agent-security`                                    | Not ported                           | It is domain-specific to transaction-signing or wallet-authorized agents. Share it when the repository contains that execution surface.                                                                  |
| `architect`, `code-simplifier`, `loop-operator`, `tdd-guide`    | Not mirrored                         | Codex keeps planning and implementation in the main agent and uses project-scoped skills; duplicating write-capable specialists would add overlapping authority.                                         |
| `code-reviewer`, `silent-failure-hunter`, `python-reviewer`     | Consolidated                         | Native review, hosted PR review, Python skills, and systematic debugging cover the useful review dimensions.                                                                                             |
| `performance-optimizer`                                         | Main-agent review                    | Require a measured bottleneck before requesting targeted performance analysis.                                                                                                                           |

## Shared Policy Alignment

| Shared behavior                                                   | Codex owner                                               |
| :---------------------------------------------------------------- | :-------------------------------------------------------- |
| Operating contract, scoped changes                                | `AGENTS.md`                                               |
| Project conventions and tool preferences                          | `AGENTS.md` project conventions                           |
| Review severity and CRITICAL/HIGH completion policy               | `AGENTS.md` review and security section                   |
| Risk-based test scope                                             | `AGENTS.md` verification section                          |
| Python development rules                                          | `python-development`                                      |
| Repository Python verification                                    | `python-testing`                                          |
| Planning, TDD, debugging, review, verification, branch completion | Native Codex, project agents, and repository verification |

Shared development behavior now mirrors the Claude common-rule routing layer: plan through Native Plan Mode; test and debug through native workflows, task-specific tests, and project skills; delivery review through the hosted PR integration; prepare PRs through the GitHub plugin when available; and follow the [shared Git workflow contract](git-workflow.md) for delivery and integration authority.

## Plans, Native Memory, And Commits

- `.references/` is read-only local reference storage for upstream clones and comparison material.
- Codex native local memories live under the user's Codex home outside the repository and provide optional recall; required repository rules remain in checked-in guidance.
- Include applicable workflow corrections in the verified commit when possible. Standing authorization permits project-local skills, hooks, rules, and agent configuration improvements without repeated approval: validate, commit locally, and report what changed and why. External actions, global settings, and platform permissions are outside that authorization.
- Memory writes need no prior approval; report afterwards when stored content changes future behavior.

## Hooks And Gates

| Layer                                         | Responsibility                                                                                                       |
| :-------------------------------------------- | :------------------------------------------------------------------------------------------------------------------- |
| `.codex/hooks/codex_post_tool_use_hygiene.py` | One read-only Ruff invocation per edit event, explicit Python targets only, bounded advisory output                  |
| `.pre-commit-config.yaml`                     | Formatting, file hygiene, detect-secrets, Ruff including T201, and targeted mypy/Pyright (including both hook trees) |
| `.vscode/settings.json`                       | Final-newline and trailing-whitespace hygiene plus Ruff formatter defaults for Python                                |

Python verification follows changed behavior and reuses unchanged evidence. Normal commits run `.githooks/pre-commit`; Python skills describe the available test commands.

`gen-commit` uses `commit-specialist` for substantial review, rough or missing messages, and explicitly requested independent checks. The main agent may commit small verified agent-owned changes directly with a complete message and no unrelated staged files, using the same verification and normal hooks. If a delegated step fails on a sandbox or cache permission boundary, the specialist returns the exact error without retries or environment changes; the main agent resumes only the blocked step in its authorized context.

Diff inspection is mode-dependent rather than automatic. Missing or rough intent asks the specialist to inspect the staged diff and write the message. A complete message for a clean, well-understood scope skips diff inspection and focuses the specialist on commit execution and bounded hook recovery. A complete message receives an additional diff check only when the main agent explicitly requests it for a concrete concern; the specialist cannot promote itself into that review mode.

## Deferred Capabilities

- Unattended background curation or changes outside the active project; project-local improvements during authorized work use the standing authorization above.
- Eval-driven development infrastructure until a real runner, deterministic graders, baselines, repeated-run metrics, and CI integration exist.
- Domain skills for LLM API cost routing or transaction-authorized agents until the repository adopts those application surfaces.

## Runtime Verification

The edit hook retains only Ruff `F` diagnostics excluding `F401,F841,F842`, limited to Python files named by that event. Full linting and formatting remain in pre-commit; this hook does not auto-fix or expand the lint rule set.

Codex runs no SessionStart hook. It discovers the root `AGENTS.md` natively, and branch or worktree context is a Git command away, so neither needs injecting. Hooks use the prepared environment with `uv run --no-sync`; set up dependencies before use. PostToolUse runs Ruff once per edit event with `--no-fix` and a timeout, and reports warnings without replacing the original tool result.

Entrypoint tests verify protocol output and real Ruff execution, not dispatch from every desktop tool path. Live matcher coverage must be checked in the target runtime before treating hooks as enforcement. Normal commit hooks and PR CI provide the automated checks.

The [official model guidance](https://developers.openai.com/api/docs/guides/latest-model) recommends auditing conflicting skill instructions. The [hook reference](https://learn.chatgpt.com/docs/hooks) documents that `continue: false` replaces the normal PostToolUse result; diagnostic-only feedback here uses `systemMessage`, with Stock retaining explicit `continue: true` and a 6,000-character advisory limit.
