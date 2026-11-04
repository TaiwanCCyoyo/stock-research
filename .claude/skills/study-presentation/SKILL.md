---
name: study-presentation
description: Present and close out a stock-research study when asked to 做展示頁, 研究收尾, web report, 放到 dashboard, or 資料要擺好. Register source-backed history, report-kit pages and shared-data references without rerunning research.
---

# Study presentation

Read [the closeout contract](../../../docs/en/research-program.md#收尾條件)
and [study-presentation.v1](../../../docs/en/study-presentation.md).
Deliver a reading view of saved evidence, not new study conclusions.

For reader-first writing, predecessor links and visual aids, follow the Codex version:
`../../../.codex/skills/study-presentation/SKILL.md` and its `references/reader-first-reports.md` and
`references/writing-and-visual-aids.md`.

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
- Add the small `presentation.json` described in the contract. Format its source
  report before hashing; use a verbatim excerpt and the current publication.
  Do not re-pin frozen evidence to make a card load.
  When changing an already registered report, update its presentation title,
  verbatim summary and SHA-256 in the same commit. The repository's strict
  registration test checks every card; a dashboard `登錄需更新` placeholder is
  a visible failure to repair, not successful validation.
- Reference existing shared family/catalog IDs in `shared_data`; link the report
  to `/#data` and relevant symbols to `/#data/<code>`. A saved strategy trade
  and a current-generation chart have different price/date semantics: label them.
  If no registered shared data applies, record `shared_data_reason`.
- Preview locally at `/#studies` (research page; `/#reports` and `/#history` redirect there) and `/#report/<task-id>`.
  Include useful conclusions and limitations in the overview, detailed evidence
  on demand. Record missing report, registration or shared-data links with a reason.

This workflow does not authorize downloads, updates, backtests, old-package
replacement, cleanup or changes to accepted research rules.

## Report look and phone preview (lessons from the strength-flags and pattern-scan reports)

- Page ground is a visible tint of the theme (`--page`, never `--surface`: white
  cards on a white page look like "everything is white"). Use at most three
  fixed-neutral highlight blocks (`--stage-bg`, near-black in dark appearance):
  the headline numbers, the main comparison or ranking, and the reverse card.
  Every other section has no fill or frame; separate with whitespace and a thin
  rule. Theme colour marks the two compared groups and their numbers only.
- Open with a plain-language answer, the two big numbers, then one line with the
  backtest period and how many events qualify, before any method text. Define a
  term where it first appears (strong stock, big-rise day, the signal and which
  trading days it is watched). Show the signal window and the doubling window as
  a timeline that follows the selected options. Never write a number the data does
  not produce: take figures from the saved results.
- A ranking shows the top three plus the baseline; the rest sits in a details
  block. Move counts of comparison cells, codes and version names into details.
- Ask an Opus subagent for a read-only review as a retail subscriber with no
  statistics background, then have a cheaper model implement the list.
- Check at 390 px wide in light and dark: no horizontal scroll, large numbers do not
  clip, tables become card rows. A static `http.server` caches CSS and JS: refetch
  with `cache: "reload"` before judging a screenshot.
- PR preview: the `preview` label publishes `pr-<N>/_preview/`. The gate rejects
  any file outside its extension whitelist (a `.csv.gz` data file blocks the whole
  PR) and any `data:` URI. Check the report's file types before labelling.
