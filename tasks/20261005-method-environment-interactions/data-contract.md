# Interaction results consumer contract v1

Producer: `scripts/run_method_environment_interactions.py` and
`research_core/method_environment_interactions.py`. Scientific definitions and
continuation rules have one source: [mission.md](mission.md). This is a
descriptive consumer of retained data, not a new price/feature producer.

## Find and obtain

- `report.md` records the completed run, exact packet digest and verdict; before
  that report exists this task is not yet delivered.
- `preregistration/<job-id>.json.gz` stores the exact packet bytes committed
  before evaluation. The local `params/<job-id>.json` is its uncompressed copy.
- `runs/registered/<job-id>/` retains the original outputs, state, log and receipt
  locally, excluded from Git. No old run is overwritten.
- `publication-v1/manifest.json` will index a Git-portable copy of every compact
  output, the packet, receipt and exact code/contract inputs. Source bulk data is
  NOT included or backed up by this publication. Its original task's preservation
  rules and locations still apply; there is no off-machine bulk backup claim.
- Use `scripts.publish_method_environment_interactions.read_publication(path)`
  for full hash/receipt/packet/archive checks and the saved objects, without the
  original worktree, runtime or stock-price submodule. The reader does not rerun
  calculations. It returns `manifest`, `packet`, `receipt`, `summary`, `results`
  and `input-audit`; do not make a new metric silently behind these identities.

## Results and units

`results.json` (`method-environment-results.v1`) contains:

| Collection       | Keys / purpose                                                                                                                               |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `comparisons`    | `panel`, `family`, `arm`, `label`, `context_column`, `context_value`; all TP/FP/FN/TN, support, availability, precision, coverage and bounds |
| `path_summaries` | Same keys plus `outcome=all/winner/nonwinner`; complete selected path distributions and target waits for winners                             |
| `paired_rows`    | Same comparison keys plus `control`; differences and actual shared-winner retention                                                          |
| `triage`         | Every candidate's failed/passed provisional conditions and at most one account-design nomination; not a strategy approval                    |

`panel` is `daily` or `grid126`; `family` is `F10/F32/F33`; arms are `all`,
`method`, `relative_strength` and `conjunction`. `label_126` is primary,
`label_63` secondary. Pooled context keys are both null. The other context columns
are `year` and `market_state`, not their Cartesian product. Empty context groups
may be absent; absence must not be displayed as a zero-rate observation.

Within a family, all arms use method-known AND F37-known support; `n_eligible`
still includes missing-feature rows. Confusion cells use jointly known features
and outcomes. `n_distinct_securities/dates` describe the eligible group, while
`selected_distinct_issuers/dates` describe selected known-outcome observations.
Do not confuse those support counts. `selected_unknown` stays outside TP/FP.

Returns, coverage, precision, differences and drawdowns are fractions, not percent.
Drawdown is a positive price-path loss; minimum return may be negative. Counts
are stock/date observations, NOT independent stocks, waves or trade attempts.
Path summaries separate winners/non-winners according to the corresponding label,
not according to whether terminal return is positive. Small positive non-winners
therefore remain in that group. Distribution `count` and `missing` apply to the
selected subgroup and metric; missing summaries are null, never zero. Quantiles
use pandas' default linear interpolation. Wait is sessions to first future target,
reported only for known winners. Shared-winner retention divides the intersection
TP count by the control TP count; a zero control count gives null, not zero.

`input-audit.json` preserves source dataset/manifest IDs, projection, fixed window
and exact-date left-join coverage. Missing benchmark dates remain explicit unknowns.
It cannot certify PIT source availability or survivorship completeness. The two
sources retain different price vintages; no updated raw cache replaces either.

## Recompute and preserve

The packet lists ALL files consumed by the verified readers, not just top-level
manifests. `source-inputs.zip` archives exact declared code and contracts, including
the registry version before the new exposure event. It is never extracted or
executed by the reader. Restoring a computation requires a separately prepared
environment with those bytes, runtime identity and separately obtained bulk data;
current source files or latest downloaded prices are not interchangeable.

Preparation: `uv run --no-sync python scripts/run_method_environment_interactions.py --prepare <new-job-id>`.
Execution uses the existing `run_registered_job.py` with the reviewed packet,
its approved digest and `--execute`; preparation/digest alone grants no authority.
Never rerun a completed directory. Stored evidence is immutable; corrections need
a new run/package and an explicit exposure/correction event. Publication verifies
the completed receipt before copying and again after copying, then validates the
saved bytes against that receipt. Hash validity is not statistical validity.
