# Report reading editions

`report-reading.v1` is an editorial layer over preserved study evidence. It does
not grant strategy acceptance or owner acceptance. The Dashboard defaults to
`ready` reading editions; `in_progress` and `history` remain accessible in
separate collections. Missing or invalid registrations appear in history with
a reason. Research verdicts and reading readiness are independent.

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
checkout is not a reconstruction source. Such records remain accessible in
history rather than being deleted or promoted to the default collection.

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
