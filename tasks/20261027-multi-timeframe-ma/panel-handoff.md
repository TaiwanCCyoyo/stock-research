# S7-B2a complete-universe panel handoff

This is `multi-timeframe-ma-panel.v1`, a pure/synthetic component of research
definition `multi-timeframe-ma.v1`, following the [mission](mission.md) and
[data contract](data-contract.md). It ranks an explicitly supplied complete
universe at one cutoff, then derives one common M. It does not certify sources,
evaluate outcomes or complete the full S7 mission. The study stays `not_evaluated`.

## Ownership and base

- Owner: delegated S7-B2a implementer, 2026-10-27 `task-15` executor.
- Base: fetched main `9073c3813ccc78dccc760c4ed9b9f1209664d816`.
- Branch: `codex/multi-timeframe-ma-panel`; old merged core branch preserved.
- Reused checkout: `C:/Users/xjp01/Documents/Codex/2026-10-27/task-15/repo`.
  No new worktree; this session owns one of its allowed five. Parent confirmed
  no other assigned owner for the new panel paths. Weeks is a separate worker.
- Before writing, bounded checks found no six proposed wave4 paths across
  23 registered checkouts (138 path checks), no path history, no corresponding
  handoff/index records across 48 refs plus latest main, and no open PRs.
- Required `uv run python scripts/worktree_inventory.py --repo <owned-checkout>
--json` completed with exit 0. Its pre-reuse entry recorded zero tracked and
  untracked changes, PR107 merged with matching final head `7680a3d1...`,
  561,387,685 ignored bytes and a citation from the existing core handoff.
  Ignored environment/caches were preserved; nothing was deleted or reassigned.
  Metadata inventory does not establish another session's liveness or deletion
  safety. The prior bounded inventory also verified an uninitialized producer
  submodule and no link attributes on the owned checkout/submodule directories.
- Applicable root AGENTS/workflow/review guidance, program, S7 mission/contract,
  core/handoff and `.codex/skills/python-development/SKILL.md` were read.

Dedicated files:

1. `research_core/multi_timeframe_ma_panel_v1.py`
2. `scripts/tests/test_multi_timeframe_ma_panel_v1.py`
3. `tasks/20261027-multi-timeframe-ma/panel-handoff.md`

Parent assigned this package the first sole shared writer slot. Its only shared
edits are the panel asset row in `docs/en/research-program.md`, panel paths/test
in `scripts/ci_test_domains.json`, and panel-specific selector assertions in
`scripts/tests/test_ci_scope.py`. Core bytes/tests/handoff, E1 modules, weeks,
mission/contract/card, roadmap and all other owners' worktrees are unchanged.

## Public API

`research_core.multi_timeframe_ma_panel_v1` exports:

- Frozen `PanelRequest(codes, generation, decision_cutoff, universe_id,
calendar_id, common_calendar)`. Codes are a nonempty sorted unique tuple of
  explicit nonblank IDs. The supplied calendar is a normalized, increasing,
  unique, naive day-label prefix ending exactly at cutoff. IDs do not certify
  the actual PR61 universe or official calendar; synthetic universes are named.
- Frozen `StockFeaturePacket(security_id, generation, decision_cutoff,
universe_id, calendar_id, s6, daily_state_dates, daily_states, w_current,
w_previous, weekly_series, weekly_ma)`. S6 is a known bool; D is exact int8
  -1/0/1 aligned to the last min(21,n) common dates; W scalars are integer
  tri-state (bool/float rejected). Dates/states are copied. Immutable bytes
  back the copied D array, so its write flag cannot be re-enabled.
- `evaluate_panel(request, packets) -> PanelAtCutoff`. Packets may arrive in
  any order; output always follows request codes. Missing/duplicate/extra
  codes and mixed identities/dates are ValueError, producing no partial panel.
  The complete structural barrier precedes all numeric reductions.

Every weekly series must be the packet's security/G/cutoff, completed_weekly,
reference_factor_adjusted. Public `core.density_at_cutoff` enforces its exact
series/MA lineage; no private core helper is imported. Known density requires
six finite MAs, positive finite denominator and finite nonnegative density.
Inconsistent known core output is rejected. Unknown density keeps all core
reasons. Public `core.ratio_cross` supplies current/previous R and both crosses
from the caller-preserved D, without reconstructing historical prices or D.

`PanelAtCutoff` contains request identity, codes, `pool_status` (ranked/empty),
`pool_n`, immutable ordered `stocks`, the **single** immutable `m` tuple, and
`coverage`. `stocks[i]` is frozen `StockPanelState`, containing security, S6,
P membership, density, percentile, dense, current D, R/Rprev, crosses,
W/Wprev, overlapping mask reasons and original density reasons. Public scalar
unknowns use None, feature unknowns -1; no NaN is exposed. There is no per-arm
mask, CORE/candidate/label override or reader/root/callback parameter.

## P before M and coverage

P depends only on supplied S6 and known-valid core density. Ranking uses pandas
ascending `rank(method="average", pct=True)`, including self, with fixed dense
threshold <=0.10. Outside P, percentile=None and dense=-1. A complete empty P
retains every code, pool_n=0, pool_status=empty, unknown dense and false M.
No top-k or minimum number of dense stocks is imposed.

Only after P is ranked, M requires S6, known current D, finite current/previous
R, known W/Wprev, known density and a nonempty ranked pool. Known false D/W and
false crosses remain eligible. CORE, candidate truth/unknown, labels and new
week confirmation do not alter M or P. Subsequent arms must share the one `m`
object rather than construct per-arm masks.

Stable mask reasons are `not_s6`, `daily_bull_unknown`, `r_current_unknown`,
`r_previous_unknown`, `weekly_current_unknown`, `weekly_previous_unknown`,
`weekly_density_unknown`, `rank_pool_unavailable`. The last reason denotes the
global empty pool; a stock outside a nonempty P has its S6/density reason.
Reasons may overlap. No priority ordering suppresses secondary missingness.

Frozen `PanelCoverage` contains s6_n, m_n, excluded_s6_n=s6_n-m_n,
outside_s6_n, pool_n and immutable `(reason,count)` pairs scoped **within S6**.
Consequently not_s6 count within S6 is zero; outside_s6_n records that scope.
Exclusion totals are deduplicated, while reason counts may sum above exclusions.
The original cutoff date/year is retained; this package does not build a full
era/candidate coverage table or substitute ISO year for original t year.

## Synthetic evidence

Command:

```text
uv run pytest scripts/tests/test_multi_timeframe_ma_panel_v1.py scripts/tests/test_ci_scope.py -q
```

Original implementation result at reviewed HEAD `4b57244b...`:
**402 passed in 81.76s** (130 panel cases and 272 selector cases).
Normal-hook evidence accompanies the reported local commit; no publication or
hosted CI is authorized in this turn. No unchanged core or unrelated research
suite is rerun to replace its existing passing evidence.

| Contract                                                                                             | Evidence                                                                                                                                   |
| ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Complete barrier, shuffled input order, public ratio/density calls                                   | `test_sorted_complete_barrier_and_public_oracle_calls`, `test_bad_barrier_fails_before_any_numeric_reduction`                              |
| Exact weekly MA lineage, stock/G/cutoff/kind/basis mismatch                                          | `test_weekly_identity_and_exact_ma_lineage`                                                                                                |
| Single/ten-way ties, distinct .10 boundary, three/four-way lowest ties with manual average ranks     | `test_average_tie_percentiles_and_no_forced_top_k`                                                                                         |
| P independent of D/W/CORE/candidates/outcomes, nine excluded M members still ranked in ten-stock P   | `test_p_precedes_m_and_unrelated_states_cannot_change_rank`                                                                                |
| Known false eligibility, missing W, S6 false, density warmup/invalid                                 | First test, `test_individual_eligibility_reasons_and_legal_pool_changes`, `test_invalid_weekly_close_or_upstream_quality_excludes_density` |
| Short/20/21/long calendars, unknown at either/both R window boundaries, cross equals threshold       | `test_exact_recent_dates_and_public_ratio_warmup`, `test_cross_thresholds_and_known_false_d_do_not_add_mask_gates`                         |
| Empty P and retained code/unknown fields                                                             | `test_empty_pool_preserves_unknowns_and_all_codes`                                                                                         |
| Overlapping reasons, within-S6 scope, deduplicated exclusions and two original years in one ISO year | `test_overlapping_coverage_is_within_s6_and_uses_original_cutoff_year`                                                                     |
| Nondegenerate fixture-specific scaling, future append and unchanged prior result                     | `test_nondegenerate_fixture_scaling_and_future_append_preserve_panel`; not universal scale-invariance acceptance                           |
| Constant-price scale boundary with exact public density/rank parity and observed dense flip          | `test_constant_price_scale_boundary_characterizes_known_dense_flip`; known numerical limitation, not an intended research rule             |
| Malformed identities/calendar/dates/int8/tri-state/S6; inconsistent core density                     | Invalid request/state/date/weekly/known-density parametrized tests                                                                         |
| Input snapshot/aliasing, output immutability, no file/socket/DB calls                                | `test_input_snapshots_immutable_outputs_and_no_io`                                                                                         |

All weekly values are built through real public core MA/density functions on
small artificial close arrays. Known-output corruption tests alone monkeypatch
the core result to exercise contract rejection. No real data or reader parity
is claimed. The nondegenerate fixture's density tolerance does not establish
universal rank/dense invariance; production ranking has no added tolerance.

## MEDIUM known numerical limitation: scale boundary

**The frozen mission's universal scale-invariance acceptance remains
UNSATISFIED.** Exact public-oracle parity is not evidence that this numerical
boundary meets that mission requirement.

Both independent Astra/planner reviews reproduced the following artificial
case at reviewed HEAD `4b57244b4739fdff68d099863bce765f826bf00b`, using the locked
environment **Python 3.12.15 / NumPy 2.3.5 / pandas 2.3.3**:

- Ten FAKE stocks; each has 150 constant weekly closes `100+i`, S6=true,
  21 saved D states=0, and W/Wprev=0. Scale every weekly price by 0.97.
- For FAKE_00, the existing core density changes from approximately
  `1.2183270001374245e-15` to zero. Its exact pandas average percentile changes
  from 1.0 to 0.10 and dense changes from 0 to 1.
- P remains 10 and every M remains true at both scales. Panel density equals
  public core density and ranks equal the exact pandas average-tie oracle at
  each scale. The difference originates in the existing EMA floating tails.

The added constant-price characterization locks the observed dense flip under
these dependencies without locking every float digit. It explicitly checks
P/M stability and exact oracle parity. The renamed nondegenerate scaling test
continues to cover its own fixture only. Neither test treats the discrepancy
as the intended research definition or as a satisfied mission acceptance.

Classification impact is demonstrated: numerically tiny density differences
can alter P-relative rank and the fixed 0.10 dense classification near this
boundary. **Market impact is not quantified**; no real prices, populations,
labels or research computation were read or run to estimate prevalence/effect.

### Explicit parent/planner disposition

On 2026-10-27 the parent accepted the planner's bounded MEDIUM disposition:
engineering delivery may proceed after regression characterization and explicit
documentation, while universal S7 scale-invariance acceptance stays unsatisfied.
This is **not a waiver or amendment of the frozen mission** and needs no new
owner choice for this characterization. A future numerical-contract change is
separate work. Core/panel production bytes, EMA operation order, epsilon,
rounding, normalization, tie handling and the 0.10 threshold are unchanged.
This correction edits only this handoff and the existing panel test; shared
integration files and frozen mission/contract/study are also unchanged.

Characterization validation:
`uv run pytest scripts/tests/test_multi_timeframe_ma_panel_v1.py -q` →
**131 passed in 5.55s**. The selector mapping and tests are unchanged, so their
existing passing evidence is retained. Normal hooks must pass on the local
correction commit before parent Astra recheck; publication remains pending.

## Shared integration and remaining gates

The existing multi_timeframe_ma domain retains core, original handoff,
mission/data-contract and both oracle dependencies. Panel module/handoff/test
are appended and the test is in reviewed_tests. Selector A/M cases cover the
panel module/test/handoff, existing core dependency and both public oracles;
unknown panel paths still select full fallback. Existing E1 and count-cube
downstream tests/consumers are retained. No new momentum/count-cube dependency
or workflow policy is introduced. Weeks must add its own entries only in its
later serialized writer slot; this package does not register absent weeks code.

Local-only delivery: commit then stop before push/PR, for parent Astra review
and publication-scope reconciliation. No market data/prices/calendar catalog,
labels, holdout, forward outcomes, shared/producer root, downloads, holds,
scratch/research run, deployment, scheduler or trading are accessed.

Deferred: official sources/PIT/known_at, calendar assessment and weekly assembly,
historical original-cutoff D/W production, late/multiple confirmations,
provisional EMA, canonical S6/CORE calculation and cooldown, labels/counts,
contrast/bootstrap/lead-lag/episode, full era/candidate coverage, real reader,
runner and market acceptance. Original owner/data/compute gates, S1/S2 completion
or explicit reorder, fixed-G/as_of inputs, original-owner overlap and single
long-run admission remain. No result/report/receipt/evaluated verdict is created.
