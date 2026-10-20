---
name: study-presentation
description: Present and close out a stock-research study when asked to 做展示頁, 研究收尾, web report, 放到 dashboard, or 資料要擺好. Register source-backed history, report-kit pages and shared-data references without rerunning research.
---

# Study presentation

Read [the closeout contract](../../../docs/en/research-program.md#收尾條件)
and [study-presentation.v1](../../../docs/en/study-presentation.md).
Deliver a reading view of saved evidence, not new study conclusions.

- Identify the current report/publication, formal outcome and data contract.
  Quote the report exactly in history registration; do not infer an outcome from
  metrics or replace an unknown result with a favorable label.
- Put maintained reusable data once in external `derived/<family>-v<N>/`.
  Research bundles belong in the primary `research_data/` catalog; pinned legacy
  `tasks/<id>/datasets/` stay in place. Use the existing catalog tool to register
  an existing bundle and add its contract/access row to the research-program index.
  Missing payload is a documented gap, not permission to synthesize or move it.
- Create `tasks/<id>/web-report/` using the existing
  `research_web/report-kit/v1/` and the research-web README report-library contract.
  Freeze the copied `kit/` with the report; keep each `data/*.js` under 500 KiB.
  Only saved summary results enter Git, never real daily OHLCV, technical series
  or pivots. Preserve report/source citations and limitations.
- Add the small `presentation.json` described in the contract. Format its source
  report before hashing; use a verbatim excerpt and the current publication.
  Do not re-pin frozen evidence to make a card load.
- Reference existing shared family/catalog IDs in `shared_data`; link the report
  to `/#data` and relevant symbols to `/#data/<code>`. A saved strategy trade
  and a current-generation chart have different price/date semantics: label them.
  If no registered shared data applies, record `shared_data_reason`.
- Preview locally at `/#reports`, `/#report/<task-id>` and `/#history`.
  Include useful conclusions and limitations in the overview, detailed evidence
  on demand. Record missing report, registration or shared-data links with a reason.

This workflow does not authorize downloads, updates, backtests, old-package
replacement, cleanup or changes to accepted research rules.
