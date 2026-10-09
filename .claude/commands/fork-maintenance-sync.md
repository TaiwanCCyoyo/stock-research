---
description: Reconcile Stock agent infrastructure with the local upstream reference and current owner goals.
---

# Fork Maintenance Sync

Synchronize agent infrastructure from the primary checkout's `.references/agent-starter-kit`.

1. Read `docs/en/fork-maintenance.md` for the last synced commit and known differences, then compare that upstream commit with the reference HEAD.
2. Compare base, current Stock and upstream for every affected path. Local changes identify intent to investigate; they do not make Stock's version preferable.
3. Use the current owner's goals and upstream design as the starting point. Retain a difference only for a concrete current requirement, safety invariant or demonstrated behavior; remove superseded or contradictory rules even when previously documented.
4. Preserve user artifacts and research evidence. Reconsider Stock-only instructions and skills on their merits; do not erase data or history when retiring a workflow.
5. Update the guide with decisions and actual verification. Use relevant behavior tests for executable changes; inspect prose changes without adding wording/model snapshot tests.

Resolve paths from the primary checkout when working in a linked worktree. Use `docs/en/git-workflow.md` for branch isolation and delivery. Importing upstream configuration grants no new credentials, remote-setting or merge authority.
