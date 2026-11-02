---
name: research-direction-draft
description: Draft and confirm a research direction, gate computation and headlines, and close out against its promises. Use for 定研究方向, 新研究, 方向草稿, mission 之前, 開工作包, or a study with direction-draft.md; do not retrofit existing studies without drafts.
---

# Research direction draft

Rules and fields are in [direction-drafts](../../../docs/en/direction-drafts.md); the
template is [direction-draft](../../../docs/en/templates/direction-draft.md). Existing studies
without a draft are not retrofitted.

- Author the draft in a GitHub draft PR using the linked workflow and
  [PR body template](../../../docs/en/templates/direction-draft-pr.md). Keep the purpose,
  fake headlines and choices readable on a phone; the optional `preview/index.html` is a
  desktop fake report, not a dashboard entry. Before opening the PR, have a subagent read only
  the draft and state purpose, main comparison, headline form and primary/secondary boundary.
- Every unresolved predecessor question, including inherited questions, must be in `carries`
  or explicitly declined in ⑪ with an exact reference and reason. `closes` is planned work,
  must also be carried, and needs delivery evidence before it counts as answered. Inspect
  old reports without drafts manually and preserve unknown sources as `待確認`.
- Market computation is forbidden until the owner confirms purpose, fake headlines and all
  choices. Before opening the work package, verify `stage: agreed`, both confirmation links,
  the confirming owner/revision and merged direction PR. Record that evidence in the package;
  then apply the existing mission/preregistration and execution-authorization gates.
  A URL or an agent-ticked box alone does not authorize computation.
  Copy verified owner confirmations into the draft's approval fields and ⑧ choices before
  the owner merges; leave it discussing while any required confirmation is missing.
- If the result fits none of the three headline branches, hold the headline, write
  `amendments/YYYY-MM-DD-headline-shape.md` (shape, why three branches fail, a new `▢`
  headline) in a separate draft PR, and wait for owner confirmation and merge before publishing.
  Record shape, supporting results and any amendment evidence in report.md's `## 頭條發布確認`;
  the reviewer checks semantic fit. Presentation changes only, never the preregistered reading.
- Titles, `study.json` `question`/`answer` and headlines promise only the main comparison;
  secondary multiples sit in a bracket that says 次要. Define 大漲 or 飆股 in
  `title_outcome_terms` or drop them. Conditions are thresholds, outcomes are targets.
- At closeout put `擁有者原話目的：` plus the verbatim `owner_purpose` in `report.md` and the
  web report, and add a `## 承諾 vs 交付` table to `report.md` (columns 承諾, 實際交付; one row
  per ⑩ promise, none empty). Link each delivered promise to its evidence; mark undelivered
  promises `未交付` and link to ⑫ or an amendment. The reviewer must inspect those links and
  confirm the claims before closeout; a non-empty cell passing the validator is insufficient.
  The frozen draft is not edited for closeout.
- Maintain `research-lineage.md` with source versions, relationship, extra question, differing
  denominators and publication status. Use `data-related-report` links and JSON-LD `isBasedOn`
  as documented; do not extend `study-card.v2` or treat a later rerun as earlier design evidence.
- Unknown dates, proposers and sources stay `待確認`; never invent an owner quote. A frozen
  draft is not edited: later changes go through `carries`, `closes` or an amendment.

This skill authorizes no backtest, download or recomputation.
