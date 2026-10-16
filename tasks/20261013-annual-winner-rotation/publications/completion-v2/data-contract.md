# Fixed-sequence holding completion v2

Definition: `annual-holding-completion.v2`. The [preregistration](preregistration.md)
defines the economics and claim boundary. This is a later publication of the
same study, with fixed v1 selected issuers and execution dates. Original root
reports, parameters, byte-pinned source and local bundles remain historical.

## Access and ownership

| Asset                                          | Single home                                                                                    | Reader / identity                                                                                                                             |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Source prices and actions                      | Configured canonical producer root, `price_daily.parquet`, `corporate_actions.sqlite`          | `producer_data_root()`, read-only stable reads, input fingerprint in `run-receipt.json`                                                       |
| Captured official event and daily-gap evidence | Producer root `corporate_action_supplements/annual-winner-20261013-v1/`                        | `publication.json` lists every member's size and SHA-256; `load_verified_evidence` verifies once per process while loading the bytes consumed |
| Research economic rules                        | `research_core/annual_rotation_v2.py`, `annual_completion_evidence.py`, `annual_completion.py` | Code commit in the run receipt; synthetic tests in `scripts/tests/`                                                                           |
| Parameters                                     | `../../params/completion-v2.json`                                                              | Recorded values and input identity in receipt                                                                                                 |
| Small results                                  | This `publications/completion-v2/` directory                                                   | `results.json`, `admission-audit.json`, `performance.json`, `run-receipt.json`; Markdown conclusions and a Git-portable HTML reading view     |

The canonical evidence batch preserves 182 captured files and adds the producer's
existing MOPS projection, publication manifest and README. It does not update the
producer's normalized corporate-action database. Stale candidate labels stay in
the original capture; the new admission audit states which gates passed. Original
capture paths in provenance are historical, never runtime dependencies.

The producer's local recursive mirror completed on 2026-10-16 at 18:22 Taipei,
according to `stock-data-downloader/logs/run_daily_20261016.log:4154`. The batch
exists at `D:/StockDataBackup/data/corporate_action_supplements/annual-winner-20261013-v1/`:
all 185 relative file paths, sizes and mtimes match the source (26,706,236 bytes).
This is a successful backup log plus batch metadata comparison, not a repeated
content-checksum pass or restore exercise. Category-specific quarterly archives
still do not include this family; no quarterly or offsite backup was observed.

## Reproduction and update

Run from a committed task branch while the producer is idle and outside its
weekday write window:

```text
python -m scripts.complete_annual_rotation
```

The default is a new publication in this directory. Existing output filenames
are rejected. For another run choose a new named publication with `--output`,
a separately registered parameter/run identity, and preserve this version.
The runner finishes by publishing its authoritative ZIP with no replacement;
it reports success only after that atomic publication. A ZIP arriving during
calculation prevents success rather than hiding the newly calculated run.
No input databases, full price tables, adjusted series or source-code snapshots
are copied into this directory. Daily equity vectors are used in memory and
omitted from the compact publication; carry counts and limitations are retained.

No legacy input bundle or source pin is replaced. Whole-market selection gaps
remain a limitation: a seven-winner supplement cannot repair every unknown
ranking candidate. The adjusted-daily shared family is not substituted for an
economic holding model with cash and share entitlements.

## Cost and integrity

One input fingerprint pass, one official calendar scan, bounded selected-issuer
reads, one supplement verification per process, and result-byte hashes after
formatting. Receipt finalization checks input stat/WAL stability rather than
hashing all large files again. No-rights scenarios and benchmark intervals are
reused in memory. Phase wall/CPU and available process-memory observations are
saved in `performance.json`; unavailable I/O/isolated peak measures are explicit.

The source batch is immutable; disagreement, absent units, missing event prices
and unsupported actions remain unknown. H/N marks are reference marks, not
observed executions or a complete daily drawdown series. Both rights scenarios
must remain visible.

## Explicit version discovery

The study root's `publications.json` uses `research-publications.v1`: `study_id`
matches its task, `current` names one listed publication, and each publication
has a unique `id` plus task-relative `report` and `result` paths. The index lists
the unchanged root v1 and `publications/completion-v2/`, selecting completion-v2.
Paths must name existing task-local files; traversal, linked paths, duplicate
versions, missing targets and unknown current versions fail closed.

`research_core.evidence.task_catalog` exposes the current publication and all
listed historical paths without reading result cards or sealed runs.
`saved_research_studio.research_history` uses that same selection, reads the
current report/card, checks its study identity and retains v1 access paths.
Presentation copy for a versioned study requires a matching `publicationId`, so
an old v1 summary cannot overwrite the new conclusion. Tasks without an index
retain their existing discovery behavior. Neither reader guesses latest by
directory date or rewrites an older result.

## Git transport

`publication.zip` losslessly retains the four original JSON members, including
`run-receipt.json` and `admission-audit.json`. Git also keeps `results.json` and
`performance.json` as small readable projections. Expanded receipt/audit files
remain local; they are not required for clean-clone report generation. The shared
`annual_completion_publication.load_publication` reads the bounded archive in memory
and verifies its three result identities against the consumed bytes exactly once.
It never extracts files or rehashes live producer inputs. An invalid archive fails
closed even if expanded files are present. This uses the established binary
transport for public checksum metadata without changing the secret-scanner baseline.
Each result's full repository-relative receipt path must match the actual
publication directory, so moving an old ZIP into a new version fails closed.
Present `results.json` and `performance.json` reading projections must match the
same in-memory ZIP member bytes; no second ZIP read or result hash is needed.
The reader validates each named member's schema and preserves explicit admission
unknowns. The standard artifact inventory includes this Git publication:

```text
uv run python -m scripts.verify_published_artifacts --only annual-holding-completion
```

The runner packages fresh results automatically. For an older, expanded-only
publication, the independent packaging entry point remains available:

```text
python -m scripts.package_annual_completion --publication <new-publication-directory>
```

Commit the result publication before building the reading page. Pass that full
commit to `scripts.build_annual_completion_report --publication-ref` so deployed
source links survive branch deletion. The committed v2 page points at publication
commit `98476d7`; a default `main` link is also supported for local previews.
When a different named publication is selected with `--publication`, the builder
derives all evidence URLs from its validated repository-relative directory and
checks the study ID. Inputs outside `tasks/<study-id>/publications/<version>/`
are rejected for report publication instead of silently linking to v2.
