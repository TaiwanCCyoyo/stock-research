# 2026-10-24: Three data homes, one scratch area, readers not developers

**Status:** owner decisions, 2026-10-24. This record and the scratch helper land first;
the data move, `study.json` v2 and the dashboard changes follow in their own PRs.

## Why

Sessions afraid of damaging shared space kept private copies, and nobody could tell
which leftovers were finished. Measured on 2026-10-24:

- PR17 (pattern-scan Q2-Q6) left 9.8 GB in one worktree's `.tmp/`. About 9.5 GB was
  rebuildable per-stock intermediates (`_temporary/events`, ~45 min per family); the
  results worth keeping were ~0.4 GB. Its report cited the worktree path, so removing
  the worktree would have lost the evidence. The run is unfinished, and another agent
  assumed it had finished.
- The primary `.tmp/` held about 40 items from different sessions and dates, with no
  owner or state.
- The dashboard assembled research cards from five formats (53 legacy history items
  inside the 2026-10-08 studio package, 5 `presentation.json`, 4 web reports,
  3 `research_result.json`, 1 `publications.json`). 17 of 77 task folders appeared
  nowhere, and tooling tasks showed up as research.
- Shared derived data was already safe for concurrent use: a single-writer OS lock,
  a complete new generation flipped atomically through `current.json`, and holds
  ([2026-10-15](2026-10-15-maintained-shared-data.md)). Copying it was never needed.

## Decisions

### 1. Three homes

| Home          | Path                                 | In Git | Holds                                                                                                                                      |
| ------------- | ------------------------------------ | ------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Repository    | `D:/Project/stock-research`          | yes    | code, docs; per task: mission, report, `web-report/`, study card, small final results and receipts                                         |
| Producer data | `D:/StockData/stock-data-downloader` | no     | acquired market data (prices, institutional, monthly revenue, corporate actions, symbol metadata)                                          |
| Research data | `D:/StockData/stock-research`        | no     | `derived/` maintained families; `catalog/` study bundles; `archive/` frozen legacy packages; `tasks/<id>/` large final results; `scratch/` |

Inputs are still never copied ([2026-10-15](2026-10-15-drop-input-sealing.md)): studies
read the producer and derived data in place, hold a generation if they run long, and
record what they read. Only a study's **outputs** need a home.

### 2. Research data leaves the checkout

`research_data/` (catalog and bundles) and `StockProject/data/private-presentation/`
(the saved studio package) move under the research-data home, as `catalog/` and
`archive/`. This supersedes the 2026-10-12 rule that the primary checkout's
`research_data/` is the formal entry. Method: copy, verify every digest, switch
`.env.local`; the old location is deleted only with the owner's explicit agreement.
Until that move lands, the existing locations and settings remain valid.

### 3. Experiment scratch lives in one labelled place

Intermediate files of an experiment go to
`<research-data home>/scratch/<task-id>/<run-id>/`, created only through
`research_core/scratch_runs.py`, which writes `run.json` (task, run, purpose, owner,
worktree, state, timestamps, optional progress). A worktree's `.tmp/` is only for
diagnostics that are useless within the session.

Run states map to the task-level
[delivery states](../research-program.md#delivery-states):

| `run.json` state | Meaning                                           | Delivery state |
| ---------------- | ------------------------------------------------- | -------------- |
| `running`        | computing or paused; may be resumed               | —              |
| `complete`       | computation finished                              | 研究完成       |
| `delivered`      | every final result recorded at a durable location | 成果交付       |
| `abandoned`      | given up, with a reason                           | —              |

可安全清理 is derived, never stored. A process using a run holds its OS lock, released
by the OS when the process ends. `uv run python -m scripts.scratch_runs list` classifies
every run:

| Classification    | Rule                                                                                  | Who may delete                                |
| ----------------- | ------------------------------------------------------------------------------------- | --------------------------------------------- |
| in use            | a process holds the lock, or an unfinished run lists a path inside it in `depends_on` | nobody                                        |
| paused            | running, lock free, touched within 7 days                                             | nobody                                        |
| awaiting delivery | complete, touched within 7 days                                                       | nobody                                        |
| deletable         | abandoned, or delivered with every result still verifiable (see below)                | any session, without asking (`clean --apply`) |
| ask owner         | stale over 7 days, unlabelled, or delivered results missing                           | owner                                         |

Delivery records an identity for each result: a repository path must have exactly the
content of `origin/main` (nothing changed, untracked or ignored under it) and is kept as
that commit plus the Git object id; a shared-root path is kept as a manifest of file sizes
and SHA-256. Deletion holds the run's writer and dependency locks, re-checks dependents
and result digests under them, and refuses any link or junction inside the run.

### 4. Legacy account runs: the package is the archive

The two 2019–2023 account runs (`20261002-add-retry`, `20261002-entry-extension-cap`)
are archived as the saved studio package already holds them (NAV, accounts, positions,
statistics). Their raw run files, which exist only under the predecessor checkout, are
not rescued. Evaluating them from 2010 is a new study.

### 5. One study card per task

Each `tasks/<id>/` gets one machine-readable card (`study.json`, extending
`study-presentation.v1` to v2): kind (study or tooling), plain question and answer,
a single verdict vocabulary, data period, report link, optional archived account run,
delivery state, and technical provenance kept apart. The dashboard reads only these
cards; a running study's progress comes from its scratch `run.json`. Legacy history
items are converted once; the old package and pinned reports are not rewritten.

### 6. The dashboard speaks to readers

Dashboard and report pages show the question, conclusion, key numbers and data period.
Versions, hashes, snapshots, generations, task IDs and registry states stay out of the
visible text, behind an on-demand source detail.

### 7. PR17 finishes under these rules

Pattern-scan Q2-Q6 runs to completion, executed by Codex after this record and the
runner change land, in a scratch run, with results delivered to
`<research-data home>/tasks/20261013-pattern-scan/`. See
`tasks/20261013-pattern-scan/rerun-handoff-q2-q6.md`.

## What stays

- Never deleting or rewriting existing data without the owner; stored results stay
  readable; pinned evidence stays byte-identical.
- Existing `.tmp/` and worktree leftovers are not swept by this tool. They are
  inventoried and handed off case by case.
- Producer acquisition, schedules and the 18:00–18:45 read guard are unchanged.
