# Pattern-scan v1 aggregate data dictionary

This dictionary documents the implemented schemas and units. Execution completion and market results require the separately retained fixed-input receipt and report. Code pointers below refer to research_core/pattern_scan_*_v1.py unless another module is named.

## Identity, facets and units

- `security_id` identifies the stock; original string code after `TW:`/`TW` prefix removal retains leading zeros for CRC32 development/cross-check split. `event_id` is canonical EventIdentity; `horizon` is common trading sessions (126/252), not calendar days. `calendar_index`, offsets, peak/first-day/landmark values count sessions; t0 is index zero for an event.
- Q1-Q3 identity: pattern_id/control_id/cohort_id/horizon + feature_id/bin_id/condition_status + split/era/mkt; candidate_id and candidate_atoms_json identify conjunctions. `row_kind=full|drop_best_year`; annual rows instead use `year`. Zero cells remain present.
- Q1-Q3 split: all/development/cross-check; era: all/2010-2012/2013-2018/2019+; mkt: all/up/down/consolidation/mixed/unknown. Q5-Q6 split_id has development/cross-check only and last era label is `2019-2026` (do not silently equate field spellings).
- Q5-Q6 META: group_id/target_pattern_id/horizon/split_id/era/mkt. Outcome-separated diagnostics also have population=hit/nonhit/unknown. nonhit means loss OR flat-win, never unknown.
- Counts (`*_n`) are event, session, or distinct-stock integers as named; rates/fractions/bounds and returns are fractions, not percentages (0.10 = 10%). Price metadata is same adjusted research price basis. Rank H condition is percent rank, a different unit; offsets may have fractional quantile/median values though underlying offsets are integers.
- Evidence pointers: reporting_v1.py:23; followup_summary_v1.py:25-65; candidate_coverage_v1.py:20-22; flags_v1.py:234-255.

## Q1-Q3 event populations and exact denominators

Use effective_label, never substitute preserved base_label. `event_main_eligible` requires full-calendar known effective outcome and no event eligibility/quality block.

- `event_n`: every supplied event. `known_n`: event_main_eligible count. `hit_n/loss_n/flat_win_n`: main eligible with corresponding effective label; these sum to known_n.
- `unknown_n`: every effective_label=unknown. `censored_n`: calendar_full=False. They overlap; they are not a mutually exclusive partition of event_n. `excluded_known_n`: full-calendar, known effective label, but not main eligible.
- `observed_hit_n`: every effective hit, regardless of qualification/calendar completeness. `full_calendar_observed_hit_n` and `censored_observed_hit_n` restrict only calendar fullness. These are not qualified hit_n.
- `full_calendar_n`, `full_calendar_unknown_n`, `censored_unknown_n`: corresponding calendar and unknown audits.
- `event_eligibility_excluded` is explicit eligibility block. Full/censored eligibility excluded counts retain that dimension separately. Legacy optional fallback infers excluded as full & known & not eligible; formal runner supplies the explicit field.
- `full_main_potential_n` = full & not excluded & (main eligible OR effective unknown). `censored_potential_n` = not full & not excluded.
- hit_rate = hit_n / known_n; loss_rate = loss_n / known_n.
- full_calendar_hit_lower_bound = hit_n / full_main_potential_n.
- full_calendar_hit_upper_bound = (hit_n + full, non-excluded, effective-unknown count) / full_main_potential_n.
- censored_hit_lower_bound = censored non-excluded observed-hit count / censored_potential_n.
- censored_hit_upper_bound = (same observed-hit count + censored non-excluded unknown count) / censored_potential_n.
- All zero denominators produce null, not 0. `distinct_stock_n` in Q1-Q3 counts all event-bearing stocks, not only eligible ones; per_stock_event_count_median/max use all supplied events per stock.
- `drop_best_year`: remove the year with most eligible hits; earliest year wins ties. Empty cell removed_year=null. Nonempty cell with no hits can select earliest registered year even if no event falls there. Recompute all counts/stock sets after exclusion; do not average yearly rates.
- N/A condition cells keep counts but full/drop/annual rate and bound fields are null. Feature_unknown is unresolved condition evidence, separate from unknown outcome. Candidate coverage retains true_n/false_n/feature_unknown_n/not_applicable_n and all event_n; conjunction states are 1/0/-1/-2 respectively, N/A dominates, then known false, then unknown.
- Evidence: rates_v1.py:55-107; dense_counts_v1.py:31-53,166-205; summary_store_v1.py:25-48; reporting_v1.py:108; analysis_v1.py:275,295.

## Q5-Q6 path and first-flag diagnostics

- Paths: direct_failure/rise_then_fall/sideways/slow_decline/unknown. These do not rewrite effective outcome; hit rows may have any corresponding diagnostic path.
- Path uses future closes only. direct failure is first -10% before first +10% (or no +10%). Otherwise maximum >=20% is rise_then_fall; otherwise maximum<20% and minimum>-15% is sideways; remaining is slow_decline. Any incomplete/missing full path gives unknown.
- path_summary `path_n`: eligible events in selected category. `_audit` counts refer to the broader facet population, not category-specific numerator. max_gain known/unknown and q25/median/q75 only sample those selected category events.
- first_flag_summary: first_state is triggered/all_false/unknown; first_n counts eligible rows whose first flag matches flag_id; none/unknown identifiers remain explicit. same_day_tie_n is membership in the stored tie list and is not additive exclusive population; offset quantiles use first offsets of chosen eligible rows.
- Followup AUDIT distinct_stock_n counts main-eligible stocks; unlike Q1-Q3 all-event stock count. unknown_label_n counts all unknown labels; excluded_n is explicit block; known_ineligible_n counts full known non-excluded non-main rows; censored overlaps these.
- Evidence: events_v1.py:140; followup_summary_v1.py:148-176,298-323; followup_v1.py:228-246.

## Flags, landmark populations and bounds

- Nine flags: Y1/Y2/Y3/X5_MA20/X5_MA60/X6_10/X6_15/X7/X8. `flag_state` uses pre-hit history; raw_flag_state is a separate uncut observation. Cost is triggering before the hit target, not post-hit triggering.
- nonhit_* uses main-eligible loss/flat-win events; hit_cost_* uses main-eligible hits. Within each: triggered_n/all_false_n/unknown_n are flag-state counts. known_n=triggered+all_false; all_n=known+unknown.
- *_known_rate = triggered/known; *_lower=triggered/all; *_upper=(triggered+unknown)/all; zero denominator=null.
- tradeoff_points nonhit_trigger_rate and hit_before_target_cost are these known_rate values; lower/upper and population_n fields retain the respective flag-state uncertainty denominator. They are retrospective diagnostics, not strategy performance.
- trigger_return is first pre-hit trigger Close / t0 Close - 1. In flag summaries, distributions use main eligible triggered rows across eligible labels; finite returns supply linear p10/median/p90, missing/nonfinite have separate unknown count.
- Landmarks: 5/10/20/40 sessions, must precede fixed horizon. Only `new_no_hit_valid_prefix` riskset, riskset_eligible=true, selected flag_state, and selected return_bin enter each cell. Pooled includes missing return-bin observations; specific bins do not.
- return_bin `lt1`, `b1_1p10`, `b1p10_1p25`, `ge1p25` corresponds to Close[landmark]/Close[t0] <1, [1,1.10), [1.10,1.25), >=1.25. These are four stored bins plus pooled, not percent field labels.
- Landmark hit_n/loss_n/flat_win_n are main eligible within the chosen riskset/state/bin. unknown_n is full-calendar, non-excluded unknown labels; potential=known+unknown. hit_rate=hit/known; loss_rate=loss/known; hit_lower=hit/potential; hit_upper=(hit+unknown)/potential. Censored/excluded are retained audit counts but not this potential denominator.
- unknown_return_n is missing rise_bin in active rows. `exclusions` lists source_table/reason_scope/reason/event_n, including overlapping label/calendar/eligibility reasons rather than a disjoint total.
- Evidence: followup_summary_v1.py:179-205,324-371; hhhl_variants_rates.py:174-216; flags_v1.py:226-255.

## Outcome-separated failure summary tables

- path_by_outcome, first_flag_by_outcome, holding_by_outcome have population hit/nonhit/unknown and preserve counts before numeric sampling.
- For known hit/nonhit, numeric samples require event_main_eligible. Unknown outcome numeric samples require full calendar and not excluded; metric must then be finite. This does not relabel unknown outcomes as hit/nonhit.
- event_n/distinct_stock_n count facet population; sample_n/sample_distinct_stock_n count admitted diagnostic population. Each metric separately has known_n/unknown_n/q25/median/q75. `numeric_sample_scope` states the actual population rule.
- max_return is a fraction; peak_offset and first_day are session counts; holding own/peer/benchmark return and state fractions use fraction units. Same-day first-flag tie counts are not exclusive.
- Evidence: failure_summary_v1.py:26-42,58-96,115-138.

## Holding context

- Identity security_id/t0/calendar_index/horizon; `information_scope=retrospective_holding_diagnostic` is not an entry condition.
- own_return and benchmark_return are fixed-endpoint Close[t+h]/Close[t]-1 only with full endpoint and valid positive prices, no unexplained jump/unknown jump-quality across the bounded interval. Truncation stays NaN with reason window_end, not shortened endpoint return.
- peer_return is equal-weight mean of known endpoint returns of other supplied ordinary-reference stocks in same industry reference, excluding own stock. No t0 liquidity filter. potential_peer_n is all other supplied same-industry stocks; known_peer_n finite returns; unknown_peer_n=potential-known. Unknown industry and no-peer cases have explicit reasons.
- `observed_sessions` counts available t0+1..min(t0+h,last). holding_<state>_n counts supplied retrospective 0050 context state on those sessions; fraction=count/observed_sessions, including unknown sessions in denominator. No observed future yields null fractions.
- calendar_full/censored/endpoint_out_of_range remain separate from known endpoint returns; context may have observed proportions even while return is censored.
- Evidence: holding_v1.py:17-38,68-94,110-118,204-251.

## Episode coverage and timing

- Admission: security_id/t0/calendar_index/label/calendar_full/admitted/exclusion_reasons. Episodes retain start_indices, anchor_index, peak_index, status/reason; episode_id hashes security/start identity.
- Observation: group_id/episode_id/security + anchor_t0/anchor_mkt, observed_coverage_status versus effective coverage_status, quota_shortfall, window bounds/knownness, matching_indices, first_matching_index, timing certainty, price diagnostic knownness and late flags.
- Match window is anchor-20..anchor+40 inclusive. A retained true match yields matched even with unknown edges; absent match yields unmatched only if full window and every daily state known, otherwise unknown. First timing is certain only if preceding window edge is present and all states from anchor-20 through before first match known.
- observed_offset = first matching index - anchor index (can be negative). entry_return=entry Close/anchor Close-1. remaining_return=peak Close/entry Close-1. late means first match strictly after peak; late_known needs both dates.
- coverage episode_n=matched+unmatched+unknown; known=matched+unmatched. coverage_rate=matched/known; lower=matched/episode_n; upper=(matched+unknown)/episode_n; null on zero denominator.
- timing quantiles use first_timing_certain, not merely observed match; entry/remaining return quantiles independently use their price-known booleans. *_unknown_n=all episodes minus known diagnostic count. late_n and late_known_n remain separate (there is no implied late rate denominator).
- Random-control coverage can be unknown due to quota shortfall even when observed coverage has a match; observed status is retained. Drawn/quota records retain seed, stock/year quota, pool pin and shortages; do not silently drop shortage episodes.
- Evidence: episode_coverage_v1.py:41-95; episode_tables_v1.py:21-49,244-275.
