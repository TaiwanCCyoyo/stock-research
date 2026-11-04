# Report reading editions

`report-reading.v1` is an editorial layer over preserved study evidence. It does
not grant strategy acceptance or owner acceptance. Research lifecycle and
editorial readiness are separate: the Dashboard offers research reports,
in-progress work and explicitly archived records. Missing or invalid evidence
does not silently archive a study or certify its conclusions.

Owner update 2026-11-04: web reading is the default for every nonarchived study,
not an availability filter. Existing HTML reports keep their primary entry;
legacy Markdown editions use the shared web report layout, source disclosures
and related-study navigation. Valid saved missions have a web reading entry
when results are not yet available. A record lacking a readable source has an
explicit source-gap page, not a fabricated completed report. Only archived
records may lack a web entry. These distinctions must remain visible.

HTML and shared web reading editions meet the same reader-understanding
standard in `study-presentation`: question, compared groups, answer, period,
denominator and meaningful limitation. Test comprehension with an independent
stock-magazine subscriber before checking against the saved evidence. Choose
layout and visual evidence for the actual comparison; do not migrate frozen
report kits or re-pin evidence solely to change presentation.

Register an edition in `tasks/<task-id>/reading.json` with these required fields:

| Field                              | Contract                                                                   |
| ---------------------------------- | -------------------------------------------------------------------------- |
| `schema`, `task_id`                | `report-reading.v1` and the containing task ID                             |
| `state`, `reason`                  | `ready`, `in_progress` or `history`, and an explicit explanation           |
| `updated_at`                       | Editorial update date, not the experiment date                             |
| `edition`                          | Task-relative Markdown path, normally `reading-report.md`, or null         |
| `question`, `answer`, `limitation` | Original question, supported answer and material limits; nonempty text     |
| `data_period`                      | Explicit `{from,to}` dates or null when the source does not establish them |
| `sources`                          | List of `{label,path}` Markdown sources; paths are relative to `tasks/`    |

`ready` requires an edition and at least one existing source. Its answer and
limitation must occur verbatim in the edition. The editor must also check the
claims against the sources: validation of an excerpt alone does not prove it.
Use the original question, actual comparison, supported answer, unanswered
questions, decision use and later corrections as the reading structure. Link
later contradictions or corrections prominently; do not silently reconcile
them or invent missing intentions, dates, metrics or acceptance decisions.

Add new prose separately from original reports, source snapshots, results,
receipts and pinned registrations. No new hashes or research runs are needed
for an editorial edition. Preserve a `source_unavailable` explanation when
evidence cannot be found in this repository's authorized homes; the predecessor
checkout is not a reconstruction source. Such records remain accessible through
a web record that discloses the source gap, without inventing a completed report.
Only explicit archival puts a study in the archived collection; source gaps and
editorial state alone do not archive it or determine its lifecycle collection.

`research_core.report_reading.ReportReadings` validates bounded UTF-8 Markdown,
contained paths and the registration. `GET /studies` adds `readings` and
`reading_warnings` alongside the existing cards. The Dashboard reads an edition
through `GET /studies/{task_id}/reading` and its declared sources through
`GET /studies/{task_id}/source?index=N`. Without an edition, the reading endpoint
can expose a schema/path-validated original Markdown report with an explicit
unreviewed-history notice; this does not repair or suppress its old provenance
warning. Invalid sidecars fail closed. Public synthetic mode reads no local
editions and returns 404 for these document endpoints.

`original_reports` lists task IDs whose original Markdown passed the safe reader;
history placeholders can link to those originals without restoring unverified
summary claims. Visibility-only registrations (`edition: null`) preserve a valid
current study card's evolving summary instead of replacing it with a snapshot.
Reading editions that depend on an undisplayed image for their main claim are
not ready: provide a supported textual explanation or retain history status.

Open `/#report/<task-id>?view=reading` for the Markdown reader. Links preserve
the research collection, search and filter on return. Existing HTML reports
remain available, with their unreviewed status visible until an edition is
registered. A reading edition is an alternative reading view for legacy
closeout; it does not change the original research verdict or data contract.
