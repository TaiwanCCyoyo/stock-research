---
name: research-direction-draft
description: Open market computation, hold headlines and close out a study against its agreed direction draft. Use when a task has tasks/<id>/direction-draft.md, when asked to 定研究方向, 方向草稿, 開工作包, 研究收尾, or when a result may not fit the agreed headline shape.
---

# Research direction draft

Rules and fields are in [direction-drafts](../../../docs/en/direction-drafts.md); the
template is [direction-draft](../../../docs/en/templates/direction-draft.md). Existing studies
without a draft are not retrofitted.

- Open the market-computation work package only when the draft has `stage: agreed` and
  `fake_headline_approved` is a link. Otherwise stop and report what is missing.
- If the result fits none of the three headline branches, hold the headline, write
  `amendments/YYYY-MM-DD-headline-shape.md` (shape, why three branches fail, a new `▢`
  headline) and wait for the owner. Presentation changes only, never the preregistered reading.
- Titles, `study.json` `question`/`answer` and headlines promise only the main comparison;
  secondary multiples sit in a bracket that says 次要. Define 大漲 or 飆股 in
  `title_outcome_terms` or drop them. Conditions are thresholds, outcomes are targets.
- At closeout put `擁有者原話目的：` plus the verbatim `owner_purpose` in `report.md` and the
  web report, and add a `## 承諾 vs 交付` table to `report.md` (columns 承諾, 實際交付; one row
  per ⑩ promise, none empty), linking any undelivered promise to its open question in ⑫. The
  frozen draft is not edited for closeout.
- Unknown dates, proposers and sources stay `待確認`; never invent an owner quote. A frozen
  draft is not edited: later changes go through `carries`, `closes` or an amendment.

This skill authorizes no backtest, download or recomputation.
