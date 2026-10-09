# Market context and feature-evidence handoff

> Current public-export availability (2026-10-09): source-data packages containing
> real quote vectors, anchor-close samples or corporate-action factors are retained
> locally, not distributed in the public repository. Historical receipts and fixed
> hashes retain their original identity. The 0050 context cannot be activated without
> its complete original input package; readers fail closed and do not download or
> recompute missing data. See [the bootstrap availability record](../../docs/en/bootstrap-stock-research.md#public-export-availability).

## Purpose and fixed definitions

This task publishes two independent products, not a new account backtest or a new
joint comparison. The [mission](mission.md) fixes the benchmark definition and
inputs before generation (commit `5702aae`). Atlas rules and all old run bytes
remain unchanged. The benchmark descriptors are provisional, not a demonstrated
optimal market regime or a stock-wave segmentation.

| Product                                  | Can answer                                                                                                     | Cannot answer                                                                                                       |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Atlas `publication-v2`                   | Every saved feature comparison, including false positives, negative results, unknown counts and denominators   | Per-stock daily drilldown without the separate bulk dataset; trade PnL; independent predictive confidence           |
| Benchmark `market-context-v2` (rules v1) | 0050 daily trailing/centered states and transition candidates, with calculation cutoffs and exact input prices | Historical publication-time certainty; total return; profitable strategy; market breadth or all-Taiwan-stock regime |

No implicit join is supplied. The atlas uses 2019-01-02..2026-08-14; the benchmark
uses the retained 2010-01-04..2026-10-02 catalog calendar. Neither expands the old
atlas experiment. A future join needs its own task, overlapping date scope,
source-vintage/price-policy check, comparison budget and exposure record.

## Benchmark row contract

One row per `(security_id, asof_date, layer)`. Security is `TW:0050`; dates are ISO
dates on the supplied shared observation calendar, not a freshly reconstructed
exchange calendar. Windows use 21 observations over 20 calendar steps. `past_only`
uses [t-20,t]; `retrospective` uses [t-10,t+10]. The centered layer is prohibited as
an as-of trading feature even though both tables use the same date key.

| Field                        | Meaning                                                                                                     |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `state`                      | `up`, `down`, `consolidation`, `mixed` or `unknown`; mixed is not consolidation                             |
| `event`                      | `launch`, `resumption` or null; transitions under the fixed mission, not orders or native catalog event IDs |
| `information_cutoff`         | Last required observation date; centered tail without enough future is null                                 |
| `window_start`, `window_end` | Required endpoints when present; missing endpoints remain null                                              |
| `window_return`              | last/first - 1, a fraction, not account return or total return                                              |
| `window_range`               | max/min - 1, a fraction; not equity drawdown                                                                |
| `missing_reason`             | `warmup`, `future_unavailable`, `unusable_observations`, or null                                            |

States use inclusive +/-3% endpoint movement, otherwise range <=8% consolidation,
otherwise mixed. Comparisons use exact fractions of decimal input representations,
not a fitted tolerance. Events are observation-ordered separately per layer:
an up transition after a known non-up state is resumption only with earlier up and
then consolidation since the last down/unknown; otherwise launch. No launch is
asserted on the first known up after unknown. Unknown/down reset event history.
These operational names do not claim to find an economic cycle's true start/end.

Source adjusted prices use the catalog's permanent non-pure-cash reference factor,
rounded to four decimals; cash dividends are not reinvested. Raw/adjusted values,
flags, barriers, source labels and caveats remain in the exact input archive.
Unusable prices are never filled. **Past-only is a computation property conditional
on a retrospectively assembled source vintage, not historical PIT certification.**
Whole-period summaries use hindsight and are not row-date-available features.

## Preservation and readers

The new small packages are tracked with byte-preserving Git attributes and exempt
from content formatters at only their immutable artifact paths. This protects
manifest hashes on Windows and other checkouts; ordinary code/prose checks remain.
Source/producer snapshots are compressed byte archives, not executable plugins.
Readers validate package identity and all declared files before returning data;
an unavailable file is an error, never a successful empty result.

The benchmark package retains only the consumed 0050 series and calendar plus the
source manifest, not every stock named in that upstream manifest. Recalculation
requires no price-pipeline access. Readers do not execute archived Python code.
The atlas publication retains all original comparison values, definitions and
summary, not newly estimated results. Use its own feature-publication contract;
do not coerce it into the account `research-result.v1` presentation contract.

Large atlas tables remain local, ignored and unchanged:

- `D:/Project/Stock/.worktrees/research-workspace-20261003/tasks/20261004-feature-discrimination-atlas/runs/registered/atlas-v2`
- `D:/Project/Stock/tasks/20261004-feature-discrimination-atlas/datasets/atlas-v2`
- Exact replay inputs: sibling `atlas-v2-inputs/input-archive.json`.

These are same-drive physical copies, not offsite protection. A new clone can read
the small packages after this PR is integrated; it cannot obtain those bulk
tables from Git. Bulk drilldown still follows the original
[atlas contract](../20261004-feature-discrimination-atlas/data-contract.md).
Do not silently regenerate against today's cache to replace missing old evidence.

## Consumer boundary

Formal entry is [research-program.md](../../docs/en/research-program.md), then the
producer's report/manifest/contract and read-only CLI. The website session can
validate and use these schemas in a bounded adapter later. A successful read-only
smoke check is not an implemented page and not a strategy result. Known readers,
actual verification receipts and final commands are recorded in [report.md](report.md).

Maintain this contract with the shared research modules. Definitions and saved
generations are immutable; changed definitions get a new version and task record,
not a rewritten old file. No automated refresh is configured by this task.
