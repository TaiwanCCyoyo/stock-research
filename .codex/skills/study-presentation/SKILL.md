---
name: study-presentation
description: Present and close out a stock-research study, or improve a report that readers find hard to understand (報告看不懂、用詞拗口、表格太多、互動導讀). Use for 做展示頁、研究收尾、web report、放到 dashboard or 資料要擺好. Build reader-guided views and source-backed history without rerunning research.
---

# Study presentation

Read [the closeout contract](../../../docs/en/research-program.md#收尾條件)
and [study-card.v2 registration](../../../docs/en/study-presentation.md).
Deliver a reading view of saved evidence, not new study conclusions.

## Design for a reader who has forgotten the study

Before building the reading view, state the reader's question, the compared
groups, the target outcome and the time origin in everyday language. A person
who never saw the conversation must understand what was studied and what the
result does and does not support. Explain an unfamiliar condition at first use;
keep research codes and compact statistical labels in the evidence layer.

Build the reading path around the question, the finding, its practical meaning
and limits, then supporting evidence. Lead with an understandable finding rather
than a count of comparison cells. A small hypothetical example can explain a
definition (such as the price used as the target's base); label it as an example,
never as observed data. A timeline helps when observation and outcome windows
differ. Do not turn this reading path into a mandatory layout for simple results.

Choose a visual only when its comparison is valid. Counts, percentages, returns
and different populations must not share comparison bars merely because a card
contains several numbers. Without enough identity to establish comparability,
use labelled values with units. Comparable bars need a shared, visible scale.
Explain each percentage's denominator and observation window beside it, especially
when adjacent measures use different populations. Preserve unknown values and
distinguish percentage-point differences from relative changes.

Use interaction to answer a reader's next question: changing a condition should
update the relevant visual, explanation and selected evidence together. Start
with one clearly explained comparison and expose broader exploration deliberately.
A page of tables with filters alone is not a guided report. Keep full tables,
formulas, uncertainty details and provenance available on demand; keep the main
limitation visible. Do not hide crucial caveats by truncating the answer. Controls
need descriptive labels, keyboard access and a clear path back to the overview.

Review the entire reading route: research list, card, report and evidence links.
Prefer literal page and action names such as 「研究報告」「查看報告」「返回研究列表」
over slogans or fragments that require interpretation. Clarify what a displayed
date means; do not imply task creation is publication or completion. Simplify
labels without changing the underlying research verdict or implying approval.

Before calling the reading view ready, assess whether a new reader can explain
the question, comparison, conclusion and caveat without the chat. Check actual
desktop/narrow-screen reading and meaningful interactions when permitted. Source
inspection and DOM tests establish behavior, not visual readability; record any
missing visual acceptance honestly and honor tool access restrictions.

## Evidence and delivery

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

This workflow does not authorize downloads, updates, backtests, old-package
replacement, cleanup or changes to accepted research rules.
