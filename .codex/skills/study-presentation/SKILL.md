---
name: study-presentation
description: Present and close out a stock-research study, or improve a report that readers find hard to understand (報告看不懂、用詞拗口、表格太多、互動導讀). Use for 做展示頁、研究收尾、web report、放到 dashboard or 資料要擺好. Build reader-guided views and source-backed history without rerunning research.
---

# Study presentation

Read [the closeout contract](../../../docs/en/research-program.md#收尾條件)
and [study-card.v2 registration](../../../docs/en/study-presentation.md).
Deliver a reading view of saved evidence, not new study conclusions.

## Design for a reader who has forgotten the study

Reconstruct the research lineage before writing the opening. Identify the prior
question, its saved answer, what this study reuses, and the additional question
it asks. Link stable task/report sources and register that relationship in the
research index or a task-owned lineage record so another session can recover it
without chat history. Distinguish a direct comparison baseline from a source of
methods; do not imply that a follow-up replaces or disproves its predecessor.
Mark partial or unpublished predecessor reports honestly and preserve the source
version used at the time. Do not substitute a later rerun, a temporary preview
URL or another session's worktree for the historical source. When populations,
time origins or denominators differ, explain that beside any cross-study
comparison. Synchronize this context across the reading page, report and card.

Every mention of a predecessor is a clickable report link written as
`<a data-related-report="<task-id>">`. In the breadcrumb every station except
the current study is such a link. Say what each predecessor supplies (the
baseline conditions, or the source of a method), never just "前作". For machines,
add an inert `<script type="application/ld+json">` whose `isBasedOn` entries
are keyed by task ID and whose `citation` points to that task's
`research-lineage.md`, the canonical record. Do not use `rel="prev|next"` for
lineage, do not add fields to study-card.v2, and do not edit a predecessor
report to add a back link; the reverse relation is registered in the research
index.

Before building the reading view, state the reader's question, the compared
groups, the target outcome and the time origin in everyday language. A person
who never saw the conversation must understand what was studied and what the
result does and does not support. Write for a magazine reader who never joined
the discussion. Wherever a group is defined by a threshold, multiple or window,
give one plain sentence at first use plus the concrete numbers of one shared
example for the whole page (for example a start price of 100). Rewriting a
formula in words is not an explanation. Keep research codes, statistical
abbreviations and symbols in tables and the evidence layer. See
[writing and visual aids](references/writing-and-visual-aids.md).

Draft the main answer before choosing tables or UI components. For each main
panel, write a short sentence stating the supported finding, then choose the
evidence that makes it understandable. Put population, denominator and period
beside that evidence; a headline must not silently broaden the claim. For a new
reading design or a report readers find confusing, apply the sourced techniques
in [reader-first reports](references/reader-first-reports.md). Adapt presentation
techniques to a self-contained page: there is no speaker to supply missing context.

Build the reading path around the question, the finding, its practical meaning
and limits, then supporting evidence. Lead with an understandable finding rather
than a count of comparison cells. A small hypothetical example can explain a
definition; label it as an example, never as observed data
([choosing the aid](references/writing-and-visual-aids.md)). When signal observation and outcome tracking use different
windows, show their order on a timeline with a named starting point and explicit
day ranges; avoid making readers infer which event "before" or "after" refers to.
Do not turn this reading path into a mandatory layout for simple results.

Choose a visual only when its comparison is valid. Counts, percentages, returns
and different populations must not share comparison bars merely because a card
contains several numbers. Without enough identity to establish comparability,
use labelled values with units. Comparable bars need a shared, visible scale.
Explain each percentage's denominator and observation window beside it, especially
when adjacent measures use different populations. Preserve unknown values and
distinguish percentage-point differences from relative changes.

Reports are HTML, so do not default to paragraphs and cards. When the finding is a
paired comparison, a sequence or a proportion, give it a visual protagonist (front-page
numbers, a timeline, an icon array) and keep prose as narrow footnotes. Techniques and
their motion limits are in [magazine layout and motion](references/magazine-motion.md).

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

Guide through layout and responsive explanations, not a lecturing voice. Prefer
neutral statements over repeated 「先知道」「下面帶你看」 introductions. Keep an
ordinary scope note brief and visually quiet. Put secondary qualifications next
to the relevant measure or in the details, while preserving the main limitation
in view.

Remove narration of interactions the interface already makes clear; retain the
date, units and qualifications that identify the displayed values. A detail
action should reveal the selected evidence directly, not expand every table
before it. In an embedded report, coordinate focus and scrolling with the host
after its layout updates, and keep the target clear of sticky navigation.
Write limits as facts beside the number they qualify (population, window,
missing independent period, unknown is not 0), and only when they change how
the reader reads that number. Do not make an unmeasured reader action (selling,
stop-losses, trading rules) the subject of a sentence, do not title sections as
warnings, and do not add disclaimers, 「僅供參考」 or 「不要照做」 lines. Write to
inform a reader, not to guard against imitators. Before/after wording is in the
tone table of [writing and visual aids](references/writing-and-visual-aids.md#tone).

Design failure states as part of the reading route. Explain what could not be
loaded, what remains usable, and the next available action. Distinguish missing
reports, connection failures and mismatched versions when evidence permits;
never imply the report itself is missing just because its index failed. Label
technical diagnostics as error details, not data sources. Keep retries bounded
and user-initiated, preserve version checks, and do not promise that a refresh
will repair a persistent build inconsistency.

Before calling the reading view ready, assess whether a new reader can explain
the question, comparison, conclusion and caveat without the chat. Check actual
desktop/narrow-screen reading and meaningful interactions when permitted. Source
inspection and DOM tests establish behavior, not visual readability; record any
missing visual acceptance honestly and honor tool access restrictions.

Before delivering a report or revising its reader-facing presentation, require
an independent subagent that did not write the draft to review it in two passes.
First provide only the reader-facing overview, without the author's explanation
or expected answer. Have it state the question, compared populations, time windows
and main conclusion in everyday language. If it must consult the appendix to
understand a group name or find the answer, revise the overview. Then provide the
mission and saved evidence to check meaning, denominators and unsupported claims.
Require concrete passages, likely misunderstandings and proposed corrections,
including teaching or disclaimer language and redundant UI narration. The main
agent decides and integrates changes while preserving necessary limitations.
An agent's fluent paraphrase is only a preliminary check; reader confusion or
failed actual interactions overrides it. This review does not substitute for
desktop/mobile acceptance or authorize hosted reviews.

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

For an unmerged report, register its worktree in the Dashboard's development
preview entry using [the preview workflow](../../../docs/en/development-previews.md).
Keep a stable project ID and update its location when the worktree changes; do
not create per-task desktop shortcuts or hand-assemble frontend/API processes.
Verify the selected branch and shared data configuration before offering its
ready link. Retire the registration after owner merge, independently of the
worktree preservation and cleanup decision.
Verify returning to main with its original launcher closed: the return action
must restore a verified primary service, retain the preview on failure, and
keep the two launchers' lifetimes independent. A clickable URL is insufficient.

This workflow does not authorize downloads, updates, backtests, old-package
replacement, cleanup or changes to accepted research rules.
