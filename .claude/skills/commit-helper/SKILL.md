---
name: commit-helper
description: Prepare a scoped local commit or commit message, including task-worktree selection, submodule handoff and commit-failure recovery. Use for commit requests and automatic task-owned commits.
---

# Commit Helper

This skill owns local commits. Delivery follows `docs/en/git-workflow.md`.

## Scope

- For a message-only request, return an English Conventional Commit message without staging or running checks.
- Use the task's actual worktree and verify the current branch before staging or committing. Do not commit on the default branch or a detached HEAD.
- Stage only task-owned files under the existing authorization. Preserve unrelated staged and unstaged work; ask only when ownership is genuinely unclear.
- For an intended submodule update, require its committed HEAD and inspect the staged gitlink. A delegated committer must not commit inside a submodule.

## Execution

Commit directly when scope and intent are clear. Delegate only when independent staged review or isolated execution adds value; do not repeat a review already completed.

When delegating, provide the absolute worktree, explicit paths, authorization and one mode:

- **execute supplied message**: use the supplied message and reviewed scope without another full diff review.
- **review supplied message**: inspect the scoped diff for the parent's stated concern.
- **complete rough or missing message**: inspect the scoped diff and draft the message.

Use a normal `git commit`; preserve its hooks. For one simple, directly actionable commit failure, inspect any resulting changes, re-stage only owned paths, and retry once. Return non-trivial failures without broadening the task. A delegated agent returns non-trivial or permission failures with the exact command, error and paths instead of changing caches, environment variables, ACLs or checks.

The repository uses `.githooks`. Use `git -c core.hooksPath=.githooks commit ...` in the task worktree so checks also run when local hook configuration is absent or points at another checkout. Do not invoke a retired legacy hook.

## Result

Use `<type>[optional scope]: <imperative description>` in English; include a body when it explains a material change. Report the commit, checks and remaining worktree changes. Keep reusable project guidance in the repository; memory follows the owner contract and runtime storage permissions.
