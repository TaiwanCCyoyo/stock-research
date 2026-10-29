# S7-B3a pure per-stock counts handoff

`multi-timeframe-ma-counts.v1` implements only in-memory per-stock counts for
research definition `multi-timeframe-ma.v1`, under the frozen [mission](mission.md)
and [data contract](data-contract.md). The study remains `not_evaluated`.
This package supplies synthetic engineering evidence, not market admission or
full S7 acceptance.

## Ownership and baseline

- Owner: the original S7 core/panel implementer, task-15 executor, continuing
  the parent-assigned Astra S7-B3a specification dated 2026-10-29.
- Freshly fetched base: `be2d52277b4076418bce44ede4bc5a169956a576`.
- Branch: `codex/multi-timeframe-ma-counts` in the existing owned checkout
  `C:/Users/xjp01/Documents/Codex/2026-10-27/task-15/repo`.
  The old merged panel branch is preserved at its existing head. No new
  worktree was created; one session-owned checkout is retained for local review
  within the five-worktree session budget. No other worktree was changed.
- Before writes, the owned checkout was clean, PR114's merged final head
  matched the panel branch, and the only open PR was #113. Its pending visual
  acceptance is unrelated and untouched. All 81 exact new-path checks across
  27 registered worktrees and the all-ref path history found no prior counts
  implementation. Parent confirmed no other package or shared-file owner.
- The required `worktree_inventory.py --repo <owned-checkout> --json` finished
  successfully (exit 0, 27 entries). Existing ignored environments/caches were
  preserved. Inventory metadata does not establish other sessions' liveness or
  safe cleanup; no cleanup was performed.
- Read the applicable AGENTS, Git workflow, review principles, program,
  S7 mission/contract/core/panel/weeks handoffs and repository Python skill.
  This round authorizes local edits, synthetic tests and normal commits only;
  no push, PR, hosted CI or deployment is part of delivery.

The only dedicated files are the counts module, its test and this handoff.
Parent also assigned this package sole ownership of the narrow asset-index,
CI domain and selector-test integration. Canonical modules and tests, S7
core/panel/weeks, E1/O2, mission/contract/study card, roadmap and PR113 are unchanged.

## API and fixed axes

```python
count_stock(stock: momentum_only_v1.StockDaily, *,
            calendar: pandas.DatetimeIndex,
            candidate_states: Mapping[str, numpy.ndarray],
            common_mask: numpy.ndarray) -> StockCounts
```

Caller supplies a unique increasing normalized naive calendar in 2010..2026,
four complete saved candidate arrays, one common bool M and aligned StockDaily
arrays. Candidates and accessed CORE atoms require exact int8 -1/0/1; labels
require int8 0/1/2/3; masks require bool. Missing/extra candidate, canonical
label/main or horizon keys are rejected. All twelve canonical labels/main
arrays and three full-horizon masks are required because public `group_counts`
accesses them. H126 is never fabricated and is not an S7 output partition.
No coercion, sorting, dropped positions or calendar filling occurs. An aligned
empty calendar is supported. `M <= stock.eligible` is required.

The frozen `StockCounts` retains `security_id = stock.code`, immutable copied
int64 arrays and explicit tuple axes:

| Field               | Axes                                                               |
| ------------------- | ------------------------------------------------------------------ |
| `counts`            | groups x cadences x labels x years x metrics = 6 x 2 x 8 x 17 x 12 |
| `coverage_counts`   | years x (S6_n, M_n, total_excluded_n)                              |
| `state_counts`      | groups x years x (true_n, false_n, unknown_n), scoped to S6        |
| `membership_counts` | groups x cadences x years x (raw_s6_n, retained_n, admitted_n)     |

Groups are weekly-turn/cross50/cross70/dense/C-base/CORE; cadences daily/cooled;
labels are H252 then H504, each 2/3/5/10; years include every year 2010..2026.
Metrics are canonical event/known/hit/loss/flat_win/unknown/censored/full_unknown
counts, followed by censored_unknown/censored_observed_hit/excluded_known/
quality_unknown counts. Array write flags cannot be re-enabled. None alias
caller inputs. Coverage contains only the supplied totals; it does not invent
upstream P/rank-pool, mask-reason, source/PIT or final coverage evidence.

## Counting and fail-closed behavior

1. Public `condition_sets`, `set_members` and `set_states` define CORE A1&A2.
   Its audit preserves canonical false precedence: (0,-1) false, (1,-1) unknown.
   Candidate true is state==1 and C-base raw membership is the full calendar.
2. Form raw membership with S6; run public `cooled(raw, eligible)` on complete
   history for the cooled cadence; apply the same M only afterward. No year,
   era, quality or label boundary restarts cooling. Excluding index 0 from M
   cannot refill index 20 in [0,20,21]. Quality unknown retains its event and
   occupied cooldown position. Unknown CORE/candidates never shrink other arms.
3. Every arm uses public `groups()['C-base-daily'][1]` for outcome quality,
   not S7's signal warmup. Public `calendar_years` assigns the original t year.
   Before public `group_counts`, row count is bounded by canonical int32
   capacity. Its output is immediately converted to int64 and the eight S7
   labels are selected without reimplementing the original eight metrics.
4. Added diagnostics use the same admitted events and public `quality_unknown`
   overlay. Censored observed hits remain outside principal hit/known.
   Quality unknown may overlap censored unknown; these diagnostics are not
   additional mutually exclusive main categories.
5. On admitted S7 events, effective full-calendar known but main=false raises
   a ValueError with code/group/cadence/label/year and `excluded_known_n`.
   Main=true with effective unknown or censoring, and effective censored
   loss/flat also fail closed. Quality overlay applies before these checks.
   Nonadmitted states do not create outcomes. Successful outputs always have
   excluded_known_n=0; excluded known is never relabeled full_unknown.
6. Each label/year checks known=hit+loss+flat,
   event=known+full_unknown+censored, unknown=full_unknown+censored_unknown,
   nonnegative counts and event=admitted. S6 state audits partition S6 and
   total_excluded=S6-M.

## Synthetic evidence and integration

Environment: Python 3.12.15, NumPy 2.3.5, pandas 2.3.3.

- Dedicated collection initially found 77 cases and its execution passed
  77/77. An additional censored quality-overlay characterization brings the
  final dedicated suite to 78 cases.
- Final focused collection: **781 tests collected** (1.49s).
- Actual focused execution: **781 passed** (56.11s), including all 78 dedicated
  cases, existing S7 core/panel/weeks, canonical momentum, pattern events/groups
  and the entire selector test module. Collection is separate evidence, not
  claimed as execution.
- The first selector run had six failures from an incorrect E1 test filename
  in a newly added assertion. It was corrected to the existing inputs suite;
  the final combined run above passed. No existing consumer was removed.
- Cases include complete zero axes and empty inputs; S6/M/state conservation;
  six independent arms; exact [0,20,21] cooling; 2012/13, 2018/19 and ordinary
  cross-year boundaries; t-year versus ISO year; distinct hand-counted eight
  labels; jump at t/t+H/t+H+1 and earlier signal warmup; malformed keys, dates,
  dtypes, lengths and values; excluded-known errors and effective partition
  consistency; input immutability/no alias and forbidden reader/IO calls.
  Seeded artificial packets cross-check all original metrics against public
  `group_counts` and `cooled`; extra diagnostics also have hand-counted oracles.
- Asset row and the S7 domain register this module, handoff and reviewed test.
  Actual upstreams momentum_only_v1, pattern_scan_events_v1 and
  pattern_scan_groups_v1 select all four S7 suites, preserving existing E1,
  strength, tenbagger and O2 v2/v3 consumers. No unused count_cube dependency
  was added. A/M own paths, test-self selection, program/prose contracts,
  technical/derived upstreams and unknown-path full fallback are tested.
  Existing full-path exceptions, frontend policy and other domain mappings stay.

Normal commit hooks and the final SHA-bound local report complete delivery
verification. Local patch/log artifacts are review aids, not market results.

## Remaining gates and limitations

- **MEDIUM, unresolved:** existing EMA floating tails can alter exact density
  ranking/dense after uniform scaling. The panel handoff's constant-price
  characterization and bounded engineering disposition still apply.
  Universal S7 scale-invariance acceptance remains **UNSATISFIED**. Counts do
  not fix, waive or quantify its market impact. No epsilon, rounding,
  normalization, EMA ordering, ties or threshold changes were made.
- This component has no price/loader/path/root/callback/reader/IO entry point,
  outcome builder, cross-stock aggregate, rates, contrasts, bootstrap,
  drop-best, lead-lag, episodes, runner, research verdict or deployment.
- Historical first confirmation, late/multiple-week handling and empty-week
  joining still need a separate method/wiring specification. No such choice
  was made here. Real E1 sources, label admission, PIT/source coverage and
  S7/S1/S2/PR17 data/compute gates remain. O2 finite G/receipt event and PR113's
  actual visual acceptance remain with their existing owners.
- Parent arranges Astra review of the final local HEAD. Publication requires
  the existing separate gate; this round stops at local committed artifacts.
