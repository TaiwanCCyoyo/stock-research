# Codex Components Reference

Codex uses Native Plan Mode, native local memories, repo-scoped skills, built-in subagents, project hooks, and installed plugins. It reads the shared root `AGENTS.md`, which Codex discovers natively; repository-wide rules live there and nested `AGENTS.md` files scope rules to their own directory.

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

## Delegation

Use the built-in general-purpose subagent for bounded work and the native `explorer` for focused code discovery. Ordinary work uses built-in agents; the registered stock-research role below remains project-specific. `AGENTS.md` owns the shared delegation principles; skills retain task-specific workflow details.

Prefer `gpt-6-luna` for straightforward work with substantial input, output, noise, or repetitive cycles. Long translations, document synchronization, large diff/log inspection, and mechanical hook fixes share this routing rule; they do not need separate roles or translation skills. Short checks run directly when a handoff offers no benefit. Choose a suitable model for implementation that needs more judgment, preserving the user's main-model choice.

Inspect the actual runtime's model controls; local Codex clients and API orchestration need not expose the same interface. The [local Codex subagent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents#choosing-models-and-reasoning) describes explicit spawn model settings and configured defaults. Use supported controls to select Luna. If only parent-model inheritance is available, report that limit and run directly, or delegate for a concrete context-isolation or parallelism benefit without claiming model or cost reduction. If model selection requires a fresh context, supply the task, relevant instructions, scope, and evidence explicitly. Return concise results rather than copying raw output into the main context. Request actual platform restrictions when needed; describing a task as read-only does not enforce a sandbox boundary. Keep the configured concurrency and depth limits unless actual workloads justify changing them.

For document translation or synchronization, the main agent selects the authoritative source and explicit target. Preserve structure, links, code, and identifiers; report source conflicts or ambiguous terminology. This is an application of the shared rule for derived outputs.

### Registered stock research

`researcher` remains a project-specific bounded execution role (`gpt-6-luna`, max, workspace-write). The main agent owns research direction, preregistration, authorization and acceptance; the role cannot download, tune gates, publish or integrate changes. Its existing instructions and point-in-time validation remain unchanged.

## Skills

| Skill                | Purpose                                                                                                 |
| :------------------- | :------------------------------------------------------------------------------------------------------ |
| `python-development` | Python logging and log-driven debugging                                                                 |
| `gen-commit`         | Scoped local commits, built-in delegation for substantial diff reading and hook recovery, and reporting |

## Claude Capability Decisions

| Claude capability                                               | Codex decision                       | Reason                                                                                                                                                                                                   |
| :-------------------------------------------------------------- | :----------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/plan`                                                         | Native/optional artifact replacement | Conversational planning is provided by native Plan Mode. Durable cross-session handoff uses a maintained plan artifact.                                                                                  |
| `plan-reviewer`, `implementation-reviewer`, `security-reviewer` | Removed 2026-10-02                   | Native Plan Mode, current model capability, hosted Codex PR review, and pre-commit gates cover them; ordinary delegation now uses built-in agents.                                                       |
| `/feature-dev`                                                  | Native replacement                   | Brainstorming, Plan Mode, test-first development, verification, and review already form the workflow.                                                                                                    |
| `/build-fix`                                                    | Native replacement                   | Evidence-driven debugging plus repository verification covers incremental diagnosis and repair.                                                                                                          |
| `/code-review`                                                  | Native/plugin replacement            | Local review uses the native Codex review stance; PR review uses the GitHub plugin.                                                                                                                      |
| `/python-review`                                                | Native replacement                   | Native Python review and existing repository checks cover this workflow.                                                                                                                                 |
| `/security-scan`                                                | Agent and gate replacement           | detect-secrets, hooks, pre-commit, and hosted PR review are installed; AgentShield is not.                                                                                                               |
| `/test-coverage`                                                | Native replacement                   | Standard pytest-cov usage needs no dedicated skill or command wrapper.                                                                                                                                   |
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
| Verification scope                                                | `AGENTS.md` verification section                          |
| Python development rules                                          | `python-development`                                      |
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

Python verification follows changed behavior and reuses unchanged evidence. Normal commits run `.githooks/pre-commit`; the README and CI define the available test commands.

`gen-commit` applies the shared delegation principles: a built-in Luna agent can read substantial diffs and handle bounded simple hook recovery, while the main agent owns scope and the final result. A complete supplied message skips repeated diff reading unless a concrete concern calls for review; rough intent requires reading the approved diff. Delegates return concise verification evidence and stop immediately on sandbox or permission failures. See the skill for editable-path boundaries and recovery limits.

## Deferred Capabilities

- Unattended background curation or changes outside the active project; project-local improvements during authorized work use the standing authorization above.
- Eval-driven development infrastructure until a real runner, deterministic graders, baselines, repeated-run metrics, and CI integration exist.
- Domain skills for LLM API cost routing or transaction-authorized agents until the repository adopts those application surfaces.

## Runtime Verification

The edit hook retains only Ruff `F` diagnostics excluding `F401,F841,F842`, limited to Python files named by that event. Full linting and formatting remain in pre-commit; this hook does not auto-fix or expand the lint rule set.

Codex runs no SessionStart hook. It discovers the root `AGENTS.md` natively, and branch or worktree context is a Git command away, so neither needs injecting. Hooks use the prepared environment with `uv run --no-sync`; set up dependencies before use. PostToolUse runs Ruff once per edit event with `--no-fix` and a timeout, and reports warnings without replacing the original tool result.

Entrypoint tests verify protocol output and real Ruff execution, not dispatch from every desktop tool path. Live matcher coverage must be checked in the target runtime before treating hooks as enforcement. Normal commit hooks and PR CI provide the automated checks.

The [official model guidance](https://developers.openai.com/api/docs/guides/latest-model) recommends auditing conflicting skill instructions. The [hook reference](https://learn.chatgpt.com/docs/hooks) documents that `continue: false` replaces the normal PostToolUse result; diagnostic-only feedback here uses `systemMessage`, with stock-research retaining explicit `continue: true` and a 6,000-character advisory limit.
