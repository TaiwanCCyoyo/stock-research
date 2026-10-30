---
name: study-presentation
description: Present and close out a stock-research study when asked to 做展示頁, 研究收尾, web report, 放到 dashboard, or 資料要擺好. Register source-backed history, report-kit pages and shared-data references without rerunning research.
---

# Study presentation

Read [the closeout contract](../../../docs/en/research-program.md#收尾條件)
and [study-card.v2 registration](../../../docs/en/study-presentation.md).
Deliver a reading view of saved evidence, not new study conclusions.

- Identify the current report/publication, formal outcome and data contract.
  Quote the report exactly in history registration; do not infer an outcome from
  metrics or replace an unknown result with a favorable label.
- Put maintained reusable data once in external `derived/<family>-v<N>/`.
  Research bundles belong in the external `D:/StockData/stock-research/catalog/` catalog; pinned legacy
  `tasks/<id>/datasets/` stay in place. Use the existing catalog tool to register
  an existing bundle and add its contract/access row to the research-program index.
  Missing payload is a documented gap, not permission to synthesize or move it.
- Create `tasks/<id>/web-report/` using the existing
  `research_web/report-kit/v1/` and the research-web README report-library contract.
  Freeze the copied `kit/` with the report; keep each `data/*.js` under 500 KiB.
  Only saved summary results enter Git, never real daily OHLCV, technical series
  or pivots. Preserve report/source citations and limitations.
- Add `study.json` (`study-card.v2`) described in the contract. Cite saved report
  bytes and a verbatim excerpt; keep technical identity in `provenance`.
  Keep `progress` out of cards: the API reads the referenced scratch run.
  Preserve existing `presentation.json` and old packages when adding v2 cards;
  never re-pin frozen evidence just to make a card load. Record unavailable
  sources or missing conclusions honestly instead of inferring approval.
- Reference existing shared family/catalog IDs in `provenance.shared_data`; link the report
  to `/#data` and relevant symbols to `/#data/<code>`. A saved strategy trade
  and a current-generation chart have different price/date semantics: label them.
  Explain missing shared-data links in the report or data contract.
- Preview locally at `/#studies` (research page; `/#reports` and `/#history` redirect there) and `/#report/<task-id>`.
  Include useful conclusions and limitations in the overview, detailed evidence
  on demand. Record missing report, registration or shared-data links with a reason.

For an unmerged report, register its worktree in the Dashboard's development
preview entry using [the preview workflow](../../../docs/en/development-previews.md).
Keep a stable project ID and update its location when the worktree changes; do
not create per-task desktop shortcuts or hand-assemble frontend/API processes.
Verify the selected branch and shared data configuration before offering its
ready link. Retire the registration after owner merge, independently of the
worktree preservation and cleanup decision.

This workflow does not authorize downloads, updates, backtests, old-package
replacement, cleanup or changes to accepted research rules.
