---
name: research-direction-draft
description: Draft and agree a research direction before any mission is written. Use when asked to 定研究方向, 新研究, 方向草稿, mission 之前, 停損研究, 想找…方法, or when a new study's purpose, title, headline or predecessor questions need the owner's confirmation before market computation.
---

# Research direction draft

Follow [direction-drafts](../../../docs/en/direction-drafts.md) and start from
[the template](../../../docs/en/templates/direction-draft.md). The draft is
`tasks/<task-id>/direction-draft.md`; it is the only record and applies to new studies,
never to rewriting existing reports.

A finished direction draft satisfies:

- Its first section is the owner's own words, confirmed by the owner. Closeout shows it
  verbatim in `report.md` and the web report. The draft is frozen once agreed: closeout
  writes a `## 承諾 vs 交付` table in `report.md`, never in the draft.
  Each delivered promise links to evidence; undelivered promises say `未交付` and link to ⑫
  or an amendment. Before closeout, the reviewer must inspect the links and substantiate the
  claims; the validator's non-empty-cell check does not establish delivery.
- It says what the owner does if the answer holds, does not hold, or cannot be told, and how
  many steps remain to the owner's final purpose.
- Every fork raised in conversation is logged with a reason and a source, including dropped
  ones. "Later" becomes an open question. Every unresolved predecessor question, including
  inherited questions, must be carried or explicitly declined with an exact reference and
  reason. `closes` is only a planned answer, must also be carried, and needs closing evidence
  in the later report/lineage. Inspect old reports without drafts manually.
- The title and card promise only the main comparison; secondary results say 次要.
  Condition numbers are thresholds, outcome numbers are targets, using the fixed legend.
- GitHub preserves the draft and confirmation record; it is not the only discussion surface.
  When choices, comparisons or outcome branches benefit from exploration, proactively use the
  [interactive discussion kit](../../../docs/en/direction-discussion-ui.md). Deliver a working
  standalone view first, reusable by the later dashboard. Simple questions can stay conversational.
  In ③ record what can be operated, what changes, and how the feedback returns; HTML-wrapped
  prose is not sufficient. Show overview first, exploration next, evidence/details on demand.
- The [PR body template](../../../docs/en/templates/direction-draft-pr.md) keeps purpose,
  fake headlines and choices readable on a phone and links the same-revision interactive view.
  Invite one concrete interaction; verify controls and export. Reconcile exported choices/notes
  with the current draft, show changes and then obtain confirmation. Stale feedback is a proposal
  to reconcile, never an approval; clicks and downloads must not set `agreed`.
- Market computation is forbidden before owner confirmation of purpose, fake headlines
  (numbers as `▢▢%`) and choices. Verify the owner and approved revision behind both approval
  links, `stage: agreed` and the merged direction PR before opening a work package; record the
  evidence and apply the ordinary mission/preregistration and execution-authorization gates.
- A result that fits none of the three branches must go back to the owner in a separate
  amendment draft PR before any headline is published. Wait for confirmation and merge;
  record shape, supporting result and amendment evidence in report.md's `## 頭條發布確認`
  for the reviewer. Never self-approve a new shape or change preregistered interpretation.
- Maintain `research-lineage.md`, stable `data-related-report` links and JSON-LD `isBasedOn`
  as documented, preserving source versions and publication status. Do not extend study-card.v2.

Record `待確認` for dates, proposers and sources you cannot find; never invent an owner quote.
Before opening the draft PR, have a subagent read the draft, exercise the view and state the purpose, main
comparison, headline form and primary/secondary boundary. Copy the owner's PR ticks and links
into the file before merge. This skill authorizes no backtest, download or recomputation.
