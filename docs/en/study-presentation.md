# Study presentation registration

## Study cards (v2)

New registrations use `tasks/<task-id>/study.json` with `schema: "study-card.v2"`.
The [schema](../../tasks/20261024-data-homes-and-scratch/study-card-v2.schema.json)
defines the saved contract. Each dated task has one card, including engineering
tasks (`kind: "tooling"`); `tasks/sample` is a template, not a study.
`question`, `answer` and `limitation` are plain-language reading text. Keep
technical identity in `provenance`. Never infer approval or research completion
from a merged code change. The seven verdicts are `promising`, `no_edge`,
`mixed`, `failed`, `running`, `not_evaluated` and `archived`.

`research_core.study_cards.StudyCards` validates the schema, enclosing task ID,
existing task-contained report paths and verbatim contiguous source excerpts.
`provenance.answer_source` and each `key_numbers[].source_excerpt` must occur in
the Markdown report, or within one original text field of the same-ID legacy
`researchHistory` item when `legacy_history_id` is set. Read that item from
the configured saved studio package, before display overlays or current history
projection; never reconstruct evidence by joining fields. When a task has no
report yet, an existing mission or handoff may be the task-relative
`report.markdown` source. Such a card describes documented scope, never an
undocumented result. Leave `data_period` unknown and `key_numbers` empty when
the source does not substantiate them.

For backfill, inspect v1 registrations first, then the original package's
same-ID history, then saved task reports/results. A legacy entry can contain
only preflight or introductory text even when its task has a full result.
Do not turn that short excerpt into a claim that no result exists: inspect the
full report. If it is needed to substantiate the card, cite that report directly,
leave `legacy_history_id` null and explain the source selection in the delivery
record. Keep both the old package and original reports unchanged.

`provenance.report_sha256`, when present, describes the cited report bytes.
A mismatch produces a warning associated with that card; it never requires
rewriting reports or v1 registrations. Invalid cards are isolated, so other
cards remain readable. The reading endpoints are:

```text
GET /studies
GET /studies?include_tooling=1
```

For existing reports, backfill `report_sha256` from the primary checkout's
current raw bytes. Some retained primary reports use CRLF while Git checkouts
use LF; do not normalize those existing files to make the hash agree. Such a
worktree legitimately returns a digest warning even when its source text is
identical. Record both contexts in delivery verification. The digest check stays
byte-exact; the new card does not repair or re-pin the retained v1 registration.

The same routes are mounted at `/api/studies` for the web proxy and
`/history-api/studies` alongside history. The dashboard's research page and home
read `/history-api/studies` (`research_web/src/features/studies/v2.ts`); a card's
`report_sha256_mismatch`, `source_unavailable` and `scratch_unavailable` warnings
appear on that card, and only if the route fails does the page fall back to the
saved history and static report index. Responses are
`{cards: [...], warnings: [{task_id, code, message}]}`. Engineering cards are
hidden unless requested. All cards are validated; warnings may concern hidden
engineering cards too. Missing cards, unavailable legacy sources and invalid
citations are warnings, never conclusions. A mismatched
`X-Research-Data-Mode` is rejected, as in the saved studio routes.
`public-synthetic` serves only clearly fictional examples: a completed study,
a running study, engineering work and an old account simulation. It never
opens local tasks, packages or scratch runs.

If neither an original report nor a legacy history source can be located,
retain only an explicitly unassessed card and emit `source_unavailable`.
Document the missing source and the evidence for its task classification in
the delivery record; never rebuild a conclusion from code or another study.

With `scratch_run: {"run": "..."}`, the reader obtains
`<shared root>/scratch/<task-id>/<run>/run.json` through `scratch_runs.read_run`.
The response adds `progress` and `run_state` from that record on each request;
neither belongs in the saved card. An unavailable run produces
`scratch_unavailable` while retaining the card. Run state does not change the
recorded verdict or delivery state. Old account links use `account_run` and
explicitly label the saved 2019–2023 period. A new card never creates or
refreshes an account simulation.

A `not_evaluated` card for a study still in direction-draft discussion may set `report.markdown` to its `direction-draft.md` ([direction drafts](direction-drafts.md)).

## Retained v1 registrations

`study-presentation.v1` adds current, source-backed report cards to the private
dashboard's research history without rewriting the saved account package.
Account returns and trades remain that package's fixed snapshot: a new history
card does not create a new strategy run.

## Author one small file

Create `tasks/<task-id>/presentation.json`. See the four registrations introduced
for HHHL v4 probability, HHHL v4 variants, annual-winner completion-v2 and
pattern-scan. Required fields:

| Field                | Meaning                                                                                              |
| -------------------- | ---------------------------------------------------------------------------------------------------- |
| `schema`             | `study-presentation.v1`                                                                              |
| `task_id`            | Exact enclosing task directory name                                                                  |
| `publication`        | Current `publications.json` publication, or `null` for an unversioned task                           |
| `section`            | `method`, `market` or `design`                                                                       |
| `report_path`        | Task-relative current report path; never an external path                                            |
| `report_sha256`      | SHA-256 of the source report's saved bytes, after formatting                                         |
| `title`              | Exact first Markdown H1 in that report                                                               |
| `summary`            | Nonempty, verbatim contiguous excerpt from that report; preserve limitations                         |
| `web_report`         | Boolean; true requires `web-report/index.html`                                                       |
| `web_report_reason`  | Optional text or null; explain why the reading page is absent when `web_report` is false             |
| `shared_data`        | Existing maintained family or catalog data IDs used/produced by this result                          |
| `shared_data_reason` | Required when the list is empty; explain unavailable/unregistered data or why no shared data applies |

Dates come from the task ID and are labeled task dates, not certified completion
dates. New formal outcomes come from the current `research_result.json`.
When that file is absent, an existing saved card retains its historical outcome;
a descriptive report or presentation card never grants approval.

For new closeout registrations without a reading page, provide a concrete
`web_report_reason` for display on the history card. Existing registrations and
saved packages may omit it for compatibility. Registering an older completed
study does not require rewriting its pinned report: record the missing reading
page and its follow-up here, preserving the report bytes and digest.

Local preview: launch the private dashboard, open `/#studies` (the merged research
page; the old `/#history` and `/#reports` addresses lead there), then `/#report/<task-id>`. Shared-data links lead to `/#data` and individual symbols
to `/#data/<code>` when that feature is installed (PR-B). The history registration
is still useful without a chart viewer. Never insert real daily price or indicator
series into these JSON files.

## Read and integrity contract

`research_core.study_presentation.project_study_history` uses the existing
`task_publications` current-publication selection for opted-in task directories only.
It requires a bounded registration
and report, contained task paths, matching SHA-256, exact title and excerpt.
Invalid opted-in registrations show only that card as `登錄需更新`, with its
task ID and a safe reason; other registered and legacy cards remain available.
Warnings identify the affected task without exposing invalid payloads or paths.
The strict `read_study_presentation` reader still raises validation errors, and
the repository test validates every `tasks/*/presentation.json` through it.
When modifying an already registered report, review and update its presentation
title, verbatim summary and SHA-256 in the same commit. Never edit pinned evidence
to make a registration pass; correct the registration or record the limitation.

The private studio first validates its original package and title-origins
sidecar. Only then does it append/replace registered task cards in the response.
It never rewrites old packages, result files, receipts or title-origin pins.
The final history projection contributes to the existing history source hash.
Public synthetic mode remains fictional and does not load local task cards.

`research-presentation.v1.json` remains legacy display metadata. Editing it alone
cannot add new task IDs to an old saved studio package. The title-origin sidecar
is tied to that old history digest and must not be applied to a newly appended
history before its original checks.

## A future new strategy package

`scripts/export_saved_research_studio.py` can export to a new filename or split
manifest and refuses to overwrite an existing output. It re-reads saved runs
and their sources; it is not a metadata-only append operation. Source availability,
preservation and any nested publication title-origin handling must be established
before a separate package refresh. This change does not export a new account
package or claim newer strategy results are represented there.

## Closeout deliverables

A completed study provides a `web-report/` reading view, its `study.json`
registration, and discoverable references to shared data, or explicitly records
why an item cannot be provided. `report.md`, data contracts, catalog metadata and
the research-program asset index remain authoritative. The presentation is a
reading interface over that evidence, never a replacement for it.

Existing `presentation.json` registrations remain readable through the v1
reader and history projection above. Keep them and old packages unchanged
during v2 registration. A known stale v1 registration can continue to show its
warning while the independently verified v2 card cites the current report.
