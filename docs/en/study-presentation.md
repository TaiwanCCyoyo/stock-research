# Study presentation registration

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
| `shared_data`        | Existing maintained family or catalog data IDs used/produced by this result                          |
| `shared_data_reason` | Required when the list is empty; explain unavailable/unregistered data or why no shared data applies |

Dates come from the task ID and are labeled task dates, not certified completion
dates. New formal outcomes come from the current `research_result.json`.
When that file is absent, an existing saved card retains its historical outcome;
a descriptive report or presentation card never grants approval.

Local preview: launch the private dashboard, open `/#history`, then `/#reports`
or `/#report/<task-id>`. Shared-data links lead to `/#data` and individual symbols
to `/#data/<code>` when that feature is installed (PR-B). The history registration
is still useful without a chart viewer. Never insert real daily price or indicator
series into these JSON files.

## Read and integrity contract

`research_core.study_presentation.project_study_history` uses the existing
`task_publications` current-publication selection for opted-in task directories only.
It requires a bounded registration
and report, contained task paths, matching SHA-256, exact title and excerpt.
Invalid opted-in registrations fail explicitly, instead of silently replacing
their evidence. A report change requires reviewing and updating its registration.

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

A completed study provides a `web-report/` reading view, its `presentation.json`
registration, and discoverable references to shared data, or explicitly records
why an item cannot be provided. `report.md`, data contracts, catalog metadata and
the research-program asset index remain authoritative. The presentation is a
reading interface over that evidence, never a replacement for it.
