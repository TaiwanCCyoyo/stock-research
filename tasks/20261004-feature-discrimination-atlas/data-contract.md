# Feature discrimination atlas v1 — consumer contract

2026-10-08 discovery link: [pattern dictionary](../../docs/en/pattern-definitions.md) distinguishes F20/F21/F33 proxies from owner HHHL versions. This link does not change these frozen atlas formulas, data or results. New consumers must explicitly select the [Stock price/feature basis](../../docs/en/research-derived-data.md); legacy outputs are not silently migrated.

This producer answers feature coverage and false discoveries before portfolio
design. It is independent of the retrospective wave/catalog producer. A website
may display these artifacts, but must not recalculate a different result behind
the same dataset identity or present descriptive labels as executable profit.

## Stable entry and identity

The run directory contains `manifest.json`, `receipt.json`, `summary.json`,
`definitions.json`, `inventory.json`, `comparisons.json`, `continuous.json`,
`benchmark.parquet`, `cross_section.parquet` and `tables/<code>.parquet`.
The task report records the authoritative run and the physical redundant copy.

- `dataset_id` hashes the input data identities, definitions, code, mission,
  schema and explicit evaluation window. `run_id` identifies one execution.
- `feature_definition_id` and `outcome_definition_id` are separate. Changing an
  implementation, threshold, label or source makes a different dataset identity.
- `security_id` uses `TW:<code>`; the row key is
  `(dataset_id, security_id, asof_date)`. `sample_id` serializes that key.
- `asof_date` is the close observation date in Taiwan local calendar terms, not
  a reconstructed historical source-release timestamp. Generation timestamp is
  only recorded in the summary; it must not be reused as historical availability.
- Per-file hashes and row counts protect integrity. JSON receipt validates the
  declared JSON outputs; the dataset verifier additionally validates **all**
  Parquet sidecars and exact join coverage. A receipt alone does not verify them.

The authoritative run must be treated as immutable. Corrections use a new run,
explicit supersession record and retained old outputs. Local bulk files are
ignored by Git; a fresh clone alone cannot reproduce the saved data without the
identified input snapshot. A second local copy is not an off-machine backup.

The preservation step also supports a separate `<run-id>-inputs/` archive of the
exact declared raw data, code and contracts, with hashes checked against the
packet. This preserves byte identities even if a later Git checkout normalizes
line endings or the active cache changes. Its `input-archive.json` is a copy
receipt, not a new study approval or a certification of source-data correctness.

## Tables and joins

| Object                  | Content                                                                                                                         | Consumer rule                                                                          |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `tables/<code>.parquet` | One row on every shared calendar date; raw/research OHLC, quality, eligibility, F01–F35, continuous values and forward outcomes | Keep feature-negative, ineligible and unknown rows; filter base eligibility explicitly |
| `cross_section.parquet` | Same exact security/date keys, RS20/RS60 ranks, 0050-relative return and F36–F38                                                | Full one-to-one join; no silently dropped rows or duplicate membership                 |
| `benchmark.parquet`     | 0050 raw/research OHLC, causal trailing features and fixed market regime                                                        | Price benchmark/descriptor, not a position or total-return series                      |
| `definitions.json`      | All 38 flags, formulas, defaults, method IDs, continuous names and unimplemented full theories                                  | Display the exact definition version, not just a familiar theory name                  |
| `comparisons.json`      | Complete daily and fixed grid126 panels; each flag × label × pooled or single context                                           | Preserve all rows, including zero support, unknowns and unhelpful results              |
| `continuous.json`       | Fixed 10/25/50/75/90% feature quantiles separately by outcome                                                                   | Descriptive distributions, not fitted score bins or calibrated probabilities           |
| `inventory.json`        | Included/excluded securities, snapshot hashes, source counts, per-security quality and coverage                                 | Current reference cohort/industry is not historical PIT membership                     |

Parquet nulls are meaningful. Binary flags are `0`, `1`, or null. A null flag
means undefined/warmup, not no signal. A null outcome means incomplete or invalid
future path, not a losing stock. Null ratios must never become zero.

Prices are in TWD, volume in lots, raw close × volume turnover in thousand TWD.
`ret*`, distance, path return, ATR ratio, relative return, ranks and drawdowns use
fractions, not percent. RSI/ADX are index points. Forward waiting times use shared
calendar sessions. Drawdown columns are positive **price-path** drop fractions,
not account drawdowns. Outcomes start strictly after the observation close.

## Reading comparison denominators

`tp/fp/fn/tn` include only base-eligible rows where both feature and label are
known. Selected means the flag is 1. `precision = tp/(tp+fp)` and
`nonwinner_among_selected = fp/(tp+fp)` are complements; neither is account PnL.
`winner_coverage = tp/(tp+fn)` applies to feature-known positives, not every
positive row in the whole cache. The same-context baseline uses that same
jointly-known population. Missing features and labels have separate marginal
counts; `selected_unknown` records feature-positive unknown outcomes.

`precision_lower/upper` include selected unknowns as respectively all negative
or all positive. These are missing-outcome bounds, **not confidence intervals**,
and do not bound bias from missing historical securities. Industry/year/regime
rows are separate slices, not their Cartesian intersection. `grid126` is a
pre-fixed sparse date panel, not a set of statistically independent trades.

## Catalog/website bridge

No episode or wave ID is fabricated. `catalog_episode_crosswalk` is null. A later
join must specify the external bundle/manifest identity plus its native event ID,
security, rule and dates. A code, webpage case ID or shared start date alone is
not a verified event crosswalk. Retrospective wave membership is never silently
used as an as-of signal or eligibility filter.

The website session reported a separate all-local-history catalog project on
2026-10-04. That does not expand this frozen 2019-01-02..2026-08-14 study or make
2010-2018 outcomes newly authorized here. Both products must retain their actual
windows, source snapshots and price policies; matching schema names is not proof
of matching evidence.

## Read-only command examples

Run from this task's repository checkout. Use the report's dataset path:

```powershell
uv run python -m scripts.query_feature_discrimination_atlas DATASET --verify
uv run python -m scripts.query_feature_discrimination_atlas DATASET --recompute
uv run python -m scripts.query_feature_discrimination_atlas DATASET --feature F33 --panel daily --context regime
```

Python callers use `research_core.feature_atlas_dataset.load_analysis` with an
explicit column projection. It verifies hashes, row counts, identities and join
keys. Projecting fewer fields does not silently relax path or join integrity.

## Availability and maintenance — 2026-10-04

Producer is `scripts/build_feature_discrimination_atlas.py` under the frozen v2
packet; result publication is `tasks/20261004-feature-discrimination-atlas/finalize.py`.
Known consumers are the query CLI, this task's report and its research-result
envelope. A website or another strategy is a prospective consumer, not an already
verified integration. The research-core module owner maintains the schema;
historical datasets and their definitions remain immutable.

Tracked code/report/results live on `codex/feature-discrimination-atlas` in
`D:/Project/Stock/.worktrees/research-workspace-20261003`; report publication is
commit `0f1266c`. The large run remains ignored. Its verified second physical copy
is `D:/Project/Stock/tasks/20261004-feature-discrimination-atlas/datasets/atlas-v2`;
the sibling `atlas-v2-inputs` contains the exact declared input/code/contract bytes,
original packet and `input-archive.json`. This copy is independently located from
the worktree, but on the same physical drive. Remote/offsite availability is not
verified. A new local checkout may explicitly read this dataset with the query
CLI; a clean clone on another machine cannot obtain it from Git alone.

Status is completed/verified descriptive data, strategy not evaluated. If a copy
is moved, preserve every manifest-referenced file and validate with `--verify`;
do not copy only the summary or regenerate against current market files and call
that the same result. The packet's input paths point to their original locations;
an archived input copy is evidence, not permission to silently rewrite a sealed
packet. Any future replay needs an explicit path mapping with unchanged byte
identities. No replay from a new machine has been claimed.

## Portable publication follow-up — 2026-10-05

The availability paragraph above records the 2026-10-04 handoff. The subsequent
[publication-v2 manifest](publication-v2/manifest.json) now makes all 7,144 saved
comparisons, original definitions and summary Git-portable without rerunning the
atlas. Source dataset ID and original byte hashes are unchanged. The publication
reader does not claim bulk-table availability or verify bulk paths. Bulk files
named in the source manifest are provenance, not included publication files.
New consumers start from the [handoff report](../20261005-market-context-handoff/report.md)
and its commands; bulk consumers retain the original contract above.

The independent 0050 dataset in that handoff does not replace this atlas's
existing benchmark regime or add a context comparison to this run. The website
session independently copied and verified both small packages on 2026-10-05;
that read-only smoke does not claim website UI integration or strategy validity.

The subsequent [PR correction audit](../20261005-market-context-handoff/execution.md#pr-review-corrections--2026-10-05)
documents a cash-event gap-classification fix and stronger publication guards.
The two saved jump gaps contain no cash event, so existing atlas values and
identities remain unchanged under their saved inputs. Future adapter executions
must register the corrected code; do not edit the original packet or outputs.
