# First candidate packet — source audit and unresolved launch decisions

Date: 2026-09-09. Status: **draft / not executable / not sealed**.
The updated owner objective permits provisional, presealed development metrics;
unapproved final acceptance thresholds are not a development-launch blocker.
Provisional hit/attribution definitions and the single two-feature comparator
are now selected in [development measurement](research-development-measurement.md).
That file is not a runnable seal; source/execution assumptions still need fixing.
The [historical security evidence](research-historical-security-type.md) now
provides 72 verified monthly roster seeds and ten dated innovation-board entries;
historical quote names cannot be used as historical board labels.
No new performance run, grid, confirmation or holdout was opened for this packet.
This follows the [launch checklist](research-launch-readiness.md), not a new
framework. It records the actual existing lead before deciding how to remeasure
it. The [owner contract](research-owner-contract.md) still governs acceptance.

## One research question

Does the existing five-slot ranking/retention idea retain useful net runaway
participation after correcting its universe, decision timing and executable
account treatment, without masking non-hit erosion with a few winners?

For the original eight-feature lead, the proposed experiment is a bounded
development remeasurement. The separately named six-feature draft below would
instead be a new development candidate, not a replication. Neither is independent
confirmation or a parameter search. Proposed development interval:
2019-01-02 through 2023-12-31, already included in the viewed exposure registry.
Warm-up is input history only and needs its own PIT coverage; the interval is
not a claim that current sources suffice. Do not open 2024-2026 to choose rules.
No independent confirmation interval is certified by this draft.

## Exact existing lead, not inferred defaults

The source is `tasks/20260906-five-slot-confirmation/run_grid.py`, which selects
V8 (`tasks/20260904-slot-accounting/candidates/rotation_ranker_v8.py`), not V11.
The historical configuration is the k5/er30 `all` cell:

```json
{
    "initial_cash": 2000000,
    "capital_mode": "shared",
    "universe": "rotation_pit",
    "top_k": 5,
    "exit_rank": 30,
    "min_hold_bars": 0,
    "exit_mode": "rank",
    "exit_param": 0.0,
    "weights": {
        "r_ret_20": 1.0,
        "r_ret_60": 1.0,
        "r_ext_20": 1.0,
        "r_above_ma60": 1.0,
        "r_vol_ratio": 1.0,
        "r_contraction": -1.0,
        "r_cohort_ret_20": 1.0,
        "r_cohort_breadth": 1.0
    }
}
```

- Eligibility: 120 strictly prior bars and median of prior 60 bars'
  `Close * Volume >= 100000` in thousands of TWD. These are trailing tests,
  not a whole-history minimum-bar survivor filter.
- Daily percentile features use average ranks within the eligible pool. Cohort
  means/breadth use other eligible members of the static industry category,
  requiring at least two peers. Contraction is the negative-weight component.
- Score descending; ties use ascending `crc32(code)`. The legacy code has no
  explicit third tie key for CRC collisions. Ranks are zero-based.
- A ranked held stock exits from rank index 30 (31st place) onward; a held stock
  absent from the ranking is also an exit candidate when its bar is present.
  There is no minimum holding period for this lead.
- Keep qualifying existing positions rather than force the portfolio into each
  day's current top five. New entries come only from the first five ranked
  names; do not fill unused slots from sixth place onward.
- Each new position targets a fixed NT$400,000 gross budget based on initial
  cash, not a growing fraction of current equity. Legacy sizing uses raw
  execution price and fees but permits individual-share quantities; venue
  feasibility and cash competition require explicit remeasurement.
- No separate market-state switch, ETF defensive allocation or exposure-scaling
  rule is part of this lead. The moving-average/cohort fields are ranking inputs.

V11 delays ranking lookup, not execution of an unchanged request. V14 wraps V8
with a next-open execution approximation and known reuse limitations recorded in
the registry. Neither replaces the shared chronology's exact request/queue,
source-timing, corporate-action and signal-identity requirements.

## Findings that change the next action

1. **Static categories are not historical categories.**
   `features.py:load_categories` reads the current `symbol_meta` snapshot without
   an as-of join. The two cohort inputs cannot be called PIT merely because
   their returns are trailing. Updating today's metadata does not repair this.
2. **Pure-stock filtering happens too late for some features.**
   Percentiles/cohorts are calculated before V5 excludes `is_etf=1`. The old
   universe manifest also lists index `001` and ETF `0050`; the strategy does
   not independently hard-code both exclusions. This is a membership/filtering
   risk, not a claim that either was actually traded in the selected run.
3. **The legacy universe label is not enough.**
   Trailing eligibility can be PIT while the outer source universe and security
   classification are survivor-biased or undated. Both must be checked.
4. **Request timing is a strategy change unless specified.**
   Legacy sell-then-buy planning can assume freed cash/slots. Shared opening
   reservations cannot use hoped-for proceeds to fund a simultaneous order.
   Lot rounding, rejected exits and explicit retry identities can alter later
   decisions. Document these differences rather than promise identical trades.

## Bounded local source inventory

Read-only SQLite `mode=ro` / `PRAGMA query_only=ON` schema queries and a Parquet
footer read were performed on the live main checkout. No large price-table scan,
new download or source mutation was used. These observations are not sealed data
identities and will need a consistent snapshot before execution.

- `price_daily.parquet`: 6,544,649 rows, seven row groups; raw OHLC/Volume,
  Code/Date/Source and precomputed averages exist. A footer is not PIT proof.
- `official_daily.sqlite`: `official_daily_price` has market/code/date,
  OHLC, shares volume, value, transactions, close-missing flag, raw fields and
  fetched time. Raw-range metadata does not itself certify all historical codes.
- `corporate_actions.sqlite`: `cash_dividend_events`, `split_events` and
  `price_adjustment_factors` are **views** over the corporate-action table, not
  missing tables. Field presence is not value coverage or actual cash timing.
- `symbol_meta.sqlite`: 2,321 rows fetched 2026-07-13 UTC. Market values are
  上市 (1,284), 上市臺灣創新板 (28), 上櫃 (1,009). Category/ETF pairs are 股票/0
  (1,942), 創新板/0 (28), ETF/1 (351). The current schema has fetched time and
  listed date but no category-valid-from/to history. These are current-snapshot
  counts, not a historical universe or an instruction to include innovation-board
  shares under ordinary-board execution assumptions.

## Launch decisions, with no implicit approval

| Decision                 | What must be fixed before outcomes                                                                                                                          | Current disposition                                                                                                                |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Cohort/stock eligibility | Dated membership for the eight-feature lead, or explicitly name a different cohort-free candidate and rebuild its percentiles on a verified stock universe. | TWSE dated category filter rejected by source probes; distinct six-feature draft below. Pure-stock eligibility remains unresolved. |
| Feasible execution       | Lot/venue policy, actual source observations versus allocation assumptions, limits, halts, expiry/retry, spendable dividend timing and costs.               | Shared helpers exist; market adapter and assumptions are not finalized.                                                            |
| Captured hit             | Net captured return threshold, return denominator, holding/observation and settlement-as-of conventions; open attempts remain unresolved.                   | Owner approved actual capture only, not the numerical definition.                                                                  |
| Non-hit loss tolerance   | Account-independent non-hit contribution/erosion, both TWD and fixed-capital fractions; owner-approved loss budget and support.                             | Twenty attempts/about 20% is a warning reference, not an approved hard veto.                                                       |
| Control and comparisons  | One feasible comparator/control protocol and explicit comparison count for this bounded question, using the same capacity/cost/source rules.                | Not selected from outcomes; no random null may copy impossible baseline trades/capital.                                            |
| Manual stresses          | Candidate-specific signal/retry identity, preselected seeds/aggregation/support, exact next-session delay and best-attempt entry-child suppression.         | Implementations exist; no market seed list or aggregate pass rule is sealed.                                                       |

The [six source probes](research-industry-source-evidence.md) reject TWSE's dated
industry filter as effective-as-of membership. Stop this endpoint investigation;
do not expand it into a category-history crawler. The original eight-feature
lead is not executable through that route and remains unevaluated here.

## Explicit next draft: `price-volume-six-k5-er30`

This is a different candidate, selected for further preparation on source
feasibility grounds before viewing new outcomes. It is not a corrected result
for the eight-feature lead and inherits no claim about that lead's returns.
Historical results for any overlapping six-feature configuration, if present,
must remain disclosed in the comparison/exposure record; this name does not
make the idea or proposed development period unseen.

- Retain the six non-cohort feature definitions and weights above:
  `r_ret_20`, `r_ret_60`, `r_ext_20`, `r_above_ma60`, `r_vol_ratio` at +1,
  and `r_contraction` at -1. Do not read or impute the two cohort inputs.
- Recompute average-rank percentiles within verified, contemporaneously
  eligible pure stocks **before** scoring. Do not reuse the old mixed-universe
  percentiles or require non-null cohort fields for eligibility.
- Preserve the proposed five-holding ceiling, top-five entry/rank-31 exit
  logic, no minimum hold and initial-capital NT$400,000 target per new
  position. Add code-ascending as a final deterministic tie key after CRC.
  This remains a policy draft; sizing/venue/retry and cash competition must
  be fixed before execution, not inherited from the legacy broker.
- No new market switch, search grid, added feature or relaxed acceptance rule
  is introduced. The purpose is still captured runaway participation with
  tolerable non-hit erosion and manual-execution resilience.

The [stock-membership audit](research-stock-membership-evidence.md) now identifies
recoverable old-code omissions at both the automatic-backfill code seed and
merged-cache import boundary. Three previously missing codes yielded 63 monthly
rows using the existing parser; this is source evidence, not a complete universe.
Next: use dated membership to seed the explicit required code/month work into a
separate research input artifact, retaining historical stock-type and board
evidence. Do not rebuild the downloader or rerun its unchanged auto code list.
Implement only the selected candidate's small market-to-account slice once its
input semantics are established. Industry history is no longer a dependency
of this **new** candidate; PIT stock membership, adjusted signal history versus
raw execution prices, corporate cash, feasible fills, the control and unresolved
owner metrics still are. This draft is not a preregistration, launch permission,
source-completeness assertion or acceptance verdict.

No production acceptance claim is possible until the owner-facing metric choices
are settled. Development may use explicit provisional definitions sealed before
outcomes; do not choose whichever definition happens to look best afterward.
The final manual-stress suite and independent validation follow only if the
candidate merits further work, not as universal prerequisites to exploration.

## Audited source bytes (not a seal)

At parent `b548d7f`, the following SHA-256 values identify the inspected policy
source. They do not cover imported runtime, feature data, universe, dependencies
or a future adapter and therefore are not a runnable job packet.

| Repository-relative file                                           | SHA-256                                                            |
| ------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `tasks/20260906-five-slot-confirmation/run_grid.py`                | `e7d6721536bda6b792e28374cad2863f863af089f6fefecc1570e6acbcae46e2` |
| `tasks/20260904-slot-accounting/candidates/rotation_ranker_v8.py`  | `167ea874948bf26947b854deb4d6e6d8074e3c86c49988a7f83303ce759bf287` |
| `tasks/20260826-runner-retention/candidates/rotation_ranker_v5.py` | `61608f53a35116b32f0bf7e7e3a1e85285a3cc6532f18c59d93ddd8dfe7c9d91` |
| `tasks/20260823-rotation-universe/eligibility.py`                  | `8e3ff7c5a072a7abc83f289d3e27e741fbd42b7613a8651dafa40d3df7316f74` |
| `tasks/20260823-rotation-universe/features.py`                     | `14f1ab8d7a47e6a013e349730584166af05ee0386db9291bf3ba54094dfe896a` |
| `tasks/20260824-ranking-horizon/features_v2.py`                    | `9b47a3ac66f3d6eb7457176c0d7e8ab0fe5aa7c50d8f8c52f6a3dd8682788e45` |

## New-checkout availability — 2026-10-09

This packet remains the historical draft described above. The six policy-source
identities in its table locate original evidence, not a runnable promise in the
new stock-research checkout. Earlier standalone study runners (including V5/V8
and the confirmation runner) are retained in Stock-legacy and the private source
archive, rather than included in the current code closure. The exact omission
paths, byte counts, source commit and SHA256 values are recorded in
[the omission inventory](omitted-legacy-code.json). Rotation-universe helper
methods remain in the current checkout for H05. No historical results, policy
bytes or admission limits above have been recalculated or rewritten.
