# Owner HH/HL labels: preserved archive

Task `20261010-owner-hhhl-labels`, executed by Claude on 2026-10-08. This is item 1 of the
owner-approved first batch in the research-data architecture review
(`.tmp/claude-kline/20261010-claude-architecture-review.md`, section 3). It preserves data; it is
not a new study and adds no market exposure.

## Result

- **All 323 owner-written documents** from the 11 labelling pages were re-exported from their
  databases on 2026-10-08 and stored verbatim in `data/owner_labels.json`.
- **What the owner was shown is stored with them**, in `data/chart_sets.zip`: every chart set
  with its bars, and, for the blind precision batches, the hidden `kind` (rule or control) of
  each item. Without the `kind` mapping the blind precision numbers cannot be recomputed.
- **Every published batch 2-5 acceptance number reproduces from these tracked files alone.**
  `recompute.py --check` re-derives 30 table cells: T2 recall/precision, v1/v2/v3 recall,
  and B precision by kind, context and category. All 30 equal the published values.
  `tests/test_recompute.py` keeps that true.

| page                     |    documents | what the owner did                                                |
| ------------------------ | -----------: | ----------------------------------------------------------------- |
| r1 頭頭高底底高標註      |           30 | free labelling of lows, highs and breakouts with relations        |
| b2 標註第二批            |           30 | blind labelling, half random and half rule windows                |
| b3a / b4a / b5a 驗收 A   |      30 each | blind labelling for recall of v1 / v2 / v3                        |
| b3b / b4b / b5b 驗收 B   | 32 / 32 / 38 | blind 算／不算 on the breakout day only, rule mixed with controls |
| reviews 規則突破檢討     |           30 | critique of rule breakouts                                        |
| lines 大區間劃線檢查     |           24 | check of the drawn big-range lines                                |
| missed 第 3 版漏掉的突破 |           17 | review of breakouts v3 missed                                     |

## Fresh export vs the earlier local dumps

All 11 pages match the earlier `.tmp` dumps document for document, except one:

- **b2-14 (3015, window to 2025-09-11).** The dump has verdict `整張沒有型態`. The database has an
  empty verdict, saved 2026-10-06T16:16Z, eight minutes after the dump.
  `batch2-result.md` had flagged this chart as an anomaly: a 像 breakout on a chart marked as
  having no pattern. The owner later confirmed in chat that 3015 is a buy.
  The breakout point was scored as a positive either way, so the batch 2 numbers are unaffected.
- Both versions are kept. The fresh export is in `owner_labels.json`; the dump is under
  `earlier_dumps/` in `data/history.zip`.

The archive also keeps `labels_dump`, the first snapshot of page r1, taken when only 10 charts
were done. Seven of its charts differ from the final export in `points`, `saved_at` and `schema`,
because the owner re-labelled them later under a newer page schema. `build_label_archive.py` refuses
any dump that differs from the fresh export in any other way; only these documented differences are allowed.

## Known gaps

- **Chat-only rulings.** `pages/owner_labels.py` in `data/history.zip` holds 21 early verdicts that the owner
  gave in chat on 2026-10-05/06. Claude transcribed them by hand; there is no database original.
  Other definition rulings were also given in chat and exist only in the conversation transcript,
  for example: highs and lows are zones read from candle bodies, a red K counts as a solid high
  when it closes near its high, and a lone spike bar is an accident. They are summarized in
  Claude's memory and in the handoffs under `.tmp/claude-kline/`, not here.
- **Page 「5A 補充」 (claude.ai/artifact/Gb2cR5vkkZ2pwBYEn6m73J).** Its `labels` collection was empty
  when queried. The batch was dropped, so this does not affect any result. Only that one
  collection name was checked.
- **Page 「頭頭高底底高定義草稿」 (claude.ai/artifact/3cX1QMb3mMLGKTZtG4oBEZ)** was a draft for reading,
  with no labelling database known to Claude.
- **Recall depends on a one-time capture.** `data/rule_hits.json` records what each rule version
  detected, produced by `capture_rule_hits.py` from the `.tmp` rule sources. It refuses to run if
  those differ from `data/rule_sources.zip`. Recomputing the hits themselves needs the atlas-v2 tables and those
  sources. The exact source bytes are kept in `data/rule_sources.zip`; the canonical versioned copies
  are in `research_core/patterns/hhhl/`.

## Dates written in the batch files are wrong; the order is right

The batch files were copied unchanged. Their headers carry the conversation's handoff labels, not
the real dates: for example `batch5-preregistration.md` says "Written 2026-10-10" and
`batch5-result.md` says "Scored 2026-10-10", but all of batch 5 happened on 2026-10-08.

What matters for a preregistration is that it was written before the owner saw the batch. The
file timestamps and the owner's first save show that held for every batch:

| batch | preregistration last modified (UTC) | chart sets written (UTC) | owner's first save (UTC) |
| ----- | ----------------------------------- | ------------------------ | ------------------------ |
| 2     | 2026-10-05 17:32:00                 | 2026-10-05 17:32:10      | 2026-10-06 16:01:25      |
| 3     | 2026-10-07 18:01:33                 | 2026-10-07 18:02:01      | 2026-10-07 18:04:34      |
| 4     | 2026-10-07 18:47:51                 | 2026-10-07 18:48:17      | 2026-10-07 18:49:55      |
| 5     | 2026-10-08 03:26:57                 | 2026-10-08 03:27:23      | 2026-10-08 03:28:33      |

The first two columns are filesystem modification times in the `.tmp` working directory, recorded
with each file's SHA-256 in `data/timeline_receipt.zip` by `record_timeline.py`. They are a
**retrospective record that cannot be independently audited**: Git keeps no file times, and a
modification time can be changed. The third column is the `saved_at` the labelling page wrote; it is
in the archive and `recompute.py` checks it against the receipt. Each committed preregistration is
byte-identical to the `.tmp` file whose time is recorded.

## Files

| file                                                                   | content                                                                                                                          |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `data/owner_labels.json`                                               | the 323 documents, verbatim, grouped by page with artifact URL and collection                                                    |
| `data/chart_sets.zip`                                                  | `sets/`: what was shown, with bars and the blind `kind`                                                                          |
| `data/history.zip`                                                     | early example sets, `earlier_dumps/` (the local dumps the results were scored from), `pages/` (page sources, chat transcription) |
| `data/rule_sources.zip`                                                | exact bytes of the rule sources used for `rule_hits.json`                                                                        |
| `data/rule_hits_inputs.zip`                                            | digests of the atlas tables read and the exact factor rows applied by the capture                                                |
| `data/timeline_receipt.zip`                                            | file times, sizes and SHA-256 behind the preregistration-order table                                                             |
| `data/rule_hits.json`                                                  | rule days per labelled chart for T2 variants, v1, v2 and v3, with the stock's session list around each window                    |
| `batch2..5-preregistration.md`, `batch2..5-result.md`                  | the original preregistrations and results, unchanged (see the dates section)                                                     |
| `build_label_archive.py`, `capture_rule_hits.py`, `record_timeline.py` | how the data files were built                                                                                                    |
| `recompute.py`                                                         | offline recomputation of every published number                                                                                  |

See `data-contract.md` for fields and semantics.
