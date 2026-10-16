---
name: commit-helper
description: Prepare scoped local Git commits and Conventional Commit messages. Load before staging, drafting a commit message, or running git commit; delegate substantial diff reading and simple hook recovery under the shared delegation principles.
---

# Commit Helper

This skill owns local commits. The main agent owns subsequent PR delivery under `docs/en/git-workflow.md`; a commit request alone does not authorize publication or merge.

## Scope And Execution

1. Determine message-only versus commit execution from the request and standing authorization. A message-only request writes nothing and may proceed on any branch.
2. Before staging or committing, run `git branch --show-current`. Stop on the default branch or an empty result (detached HEAD), as required by the Git workflow contract.
3. The main agent checks filenames/status and establishes the approved scope. Stage only verified agent-owned changes under standing authorization or paths the user authorized. Preserve unrelated staged and unstaged work; stop if the commit boundary cannot be established safely.
4. For an authorized submodule change, confirm its `HEAD` is committed, stage it in the superproject with `git add -- <submodule-path>`, and record the staged gitlink. A delegate verifies that gitlink and must not commit inside a submodule. An uncommitted submodule or unexpected gitlink delta returns to the main agent.
5. Apply `AGENTS.md`'s delegation principles. For substantial diff reading or repetitive, straightforward hook recovery, prefer a built-in general-purpose subagent and select the lowest-cost suitable model through the actual runtime's supported model controls. If model selection is unavailable, follow the shared inherited-model fallback rather than claiming a switch or cost reduction; small, already-understood commits can run directly. Give the delegate this skill, the task intent, repository path, exact staged/staging and editable paths, acceptance criteria, verification, supplied message or drafting request, gitlink evidence, and explicit message-only or commit authorization. Keep one writer on those paths and the Git index.
6. If intent is rough or unknown, the executor inspects only the approved diff and drafts the message. With a complete supplied message and understood scope, preserve the message and skip repeated diff reading unless the main agent explicitly requests review for a concrete concern. A delegate does not add review on its own; changed content still needs inspection during recovery.
7. Return a message-only result without committing. Otherwise execute the authorized commit with normal hooks and the recovery limits below.

## Commit Message

- Write English Conventional Commits: `<type>[optional scope]: <description>`.
- Use an imperative, lowercase description without a final period; keep the subject under 50 characters when practical.
- Add a body explaining why and how only when useful; separate it from the subject with a blank line.

## Hook Recovery And Handoff

- Permit up to three simple fix-and-retry cycles for actionable hook failures within explicitly editable paths. Inspect each resulting diff, re-stage only approved paths, and rerun the normal commit. Stop when a failure repeats without progress or the budget is exhausted.
- Fix formatting, imports, and clear local typing mistakes while preserving behavior. Do not weaken checks, add blanket `Any` or suppression directives, change dependencies, or expand scope to make a commit pass. Ambiguous typing, design changes, secrets, or broader failures return to the main agent with evidence.
- A sandbox or permission failure is an immediate handoff, not a recovery cycle. Return the exact error, attempted step, affected paths, and current state; do not retry, relocate caches, change environment variables or ACLs, seek escalation, or bypass hooks. The main agent may resume the blocked step through its normal authorized execution mechanism without repeating completed diff review.
- Never amend without explicit authorization, include secrets, or stage unrelated work. Never bypass hooks without explicit user authorization.

The repository uses `.githooks`. Use `git -c core.hooksPath=.githooks commit ...` in the task worktree so normal checks also run when local hook configuration is absent or points at another checkout.

## Result

The executor returns the commit hash or drafted message, committed/changed paths, hook results, retry count, and any blocker; keep full logs and diffs out of the main context unless needed to resolve a problem. The main agent verifies the committed filenames and remaining status, reports the result, and owns any follow-up workflow improvements under `AGENTS.md`. Re-read detailed content only when changes or unresolved evidence warrants it. Store required guidance in checked-in files rather than commit narration in memory.
