# H03: fixed industry roles and leave-one-out peer strength

Recorded 2026-10-05 before this batch's outcomes. One bounded descriptive
exploration under the resumed owner goal; not an executable strategy or independent
confirmation. The parent owns these definitions and provisional continuation rules.

## Question and prior exposure

Among stocks whose other industry members are strong, do long-window leaders,
laggards with positive short-window returns, or still-weak laggards distinguish
future large rises better than peer strength alone and peer strength plus saved
market-relative strength? This tests H03 in the method/environment map; it does
not presume catch-up exists. The previous six F10/F32/F33 combinations failed
their fixed promotion rules. Their results informed this different question;
none of their thresholds or verdicts is changed.

Reuse the exact atlas-v2 and market-context-v2 datasets already indexed in
research-program.md. Stock/date scope remains 2019-01-02..2026-08-14 because those
compatible, preserved observations are available and already exposed. Do not add
2010-2018 or later stock outcomes. The context reader verifies its whole already
exposed 2010-01-04..2026-10-02 package; only exact same-date past-only rows in the
stock window join. No price, feature, industry or rank recomputation from the
latest producer cache; no downloads or sealed-period opening.

The cohort is current-reference, not survivorship-complete. Industry labels are
current metadata, NOT historical PIT membership or precise value-chain themes.
Saved returns use permanent-factor adjusted closes, not cash-dividend total
returns. Retrospective source versions cannot certify historical availability.
This conditional description can suggest a next experiment but cannot approve
investment or establish a historical tradable sector strategy.

## Fixed role definitions

Use saved base_eligible, ret20, ret60 and industry_ref. For each original date
and nonmissing/nonblank industry (case-insensitive `unknown` excluded), the peer
pool consists of eligible stocks with BOTH trailing returns known. The exact
classification_basis must be current_metadata_reference_not_PIT. Future labels,
future completion and saved rank availability NEVER select peers.

Subtract the target's count/return/positive flag from group totals ONLY if it
belongs to that pool. Means are equal-weighted. Save the count of other members,
their mean ret20/ret60 and fraction with ret60 > 0. Require at least FIVE other
members. This is a parent-chosen provisional support floor, not owner approval.

An eligible target with known industry/returns and enough peers receives exactly
one role: leader if own ret60 >= other-member mean ret60 (ties included;
absolute differences <= 1e-12 return fraction are arithmetic ties, zero relative
tolerance, fixed before results to prevent sum/division rounding from breaking ties);
laggard_turning if below that mean AND own ret20 > 0; laggard_weak if below that
mean AND own ret20 <= 0. The turning name means only this short-positive proxy,
not a detected bottom, equal-window acceleration, or a verified catch-up event.
A leader can have negative short-window return. Returns are fractions.

Other-member strength is strong iff mean ret60 > 0 AND positive-ret60 fraction

> = 0.60, otherwise other when measurable. Unknowns stay unknown. Role missing
> reason priority: ineligible, missing_industry, missing_returns, insufficient_peers.
> Malformed keys, nonfinite observed returns/ranks, invalid rank range, invalid
> classification basis or calendar mapping reject the batch instead of becoming
> zero. Missing ranks do not change peers or role, only comparison support.

## Comparisons and budget

All SEVEN arms share role-known AND saved rs60_percentile-known support:
all; relative_strength (saved rank >= 0.8); peer_strong;
peer_strong_rs (both); leader_strong; turning_strong; weak_strong.
The last three select the respective role AND strong other members. Outside
common support every arm is null, even when another condition is false. Preserve
all base-eligible rows in availability counts. Never rerank within an industry.

Panels are daily and ORIGINAL calendar_index % 126 == 0, without reindexing after
filtering. Primary outcome is saved label_126 (future close reaches 2x in 126
slots); secondary is label_63 (1.5x in 63). Retain original full-path completion
and unknown semantics. Stock/date observations overlap and are dependent; grid
sampling does not create independent issuers or independent opportunities.

Compare pooled and each year, market_state and industry_ref SEPARATELY, not their
Cartesian product. At most 64 industry categories, eight years and five market
states. Maximum 2 panels * 2 labels * 7 arms * (1+8+5+64) = 2,184 comparisons.
Exceeded bounds reject the execution; they do not silently truncate categories.
Industry/context/secondary results are diagnostic and cannot rescue pooled failure.

Retain every confusion cell, selected-known/unknown, feature missingness,
precision, winner coverage, nonwinner fraction, unknown-label bounds and selected
distinct issuers/dates. Preserve all/winner/nonwinner price-path distributions:
terminal return, minimum future-close return, peak-to-trough drawdown, with
count/missing/mean/p10/median/p90. Winner waiting time uses known winners only.
Nonwinners include small gains, not just losses; these paths are NOT account PnL.
Paired comparisons against peer_strong, peer_strong_rs and relative_strength
retain ACTUAL shared-winner intersections; candidate TP/control TP is not retention
when selections differ. Undefined denominators remain null.

## Provisional promotion, fixed before results

Three candidates: leader_strong, turning_strong, weak_strong. Each must have >=30
selected-known observations and >=10 selected issuers in BOTH primary pooled
panels, and strictly higher precision than BOTH peer_strong and peer_strong_rs.
Each control also needs >=30 selected-known and >=10 issuers; insufficient control
support is insufficient evidence, not an economic candidate failure.

For daily 2019-2025, years with >=30 selected-known observations in candidate and
peer_strong_rs are evaluable. Require >=4 evaluable years and strict majority
with candidate precision above that control. These are provisional support and
consistency screens, not statistical significance or final owner loss limits.
Coverage and downside are reported, not new numerical vetoes. Unlike the previous
pattern batch, role groups are mutually exclusive alternatives, so its 25% shared
F37-winner retention rule is NOT imported or altered retroactively.

At most one nominee for subsequent account DESIGN: greatest minimum pooled
precision difference vs peer_strong_rs across the two panels; tie order leader,
turning, weak. Any nomination must include nonwinner deterioration, coverage and
unknown bounds. No automatic account run, confirmation or holdout. If none qualify,
stop these exact definitions for promotion without tuning them on these results.

## Execution and preservation

Existing research-job.v1 runner; commit code, mission and approved packet before
one execution. Bind every consumed input file/import dependency, runtime and
contract. One initial run with 1,800-second limit; at most one diagnosed
implementation-only retry under a fresh ID, with unchanged definitions. Preserve
failed runs and distinguish data/measurement/execution failure from a weak candidate.

Synthetic tests verify leave-one-out membership, five-peer boundary, missingness,
zero/ties, outcome-invariant roles, common support, original grid, true shared
winners and promotion boundaries. Reuse unchanged producer tests. No universal
platform work or broader data completion is prerequisite to this batch.

Store complete compact outputs, packet, receipt and exact source/contracts in a
versioned Git-portable package. Reuse the verified publisher with an explicit
industry-role profile; preserve previous packages byte-for-byte. No duplicate bulk
dataset: build_roles is a reusable pure derivation of pinned atlas inputs, not a
claim that per-row roles have been saved. The existing two physical atlas copies
remain local on one drive, not an offsite backup. Archive the pre-event registry
before appending exposure. Update the task report and formal program/method index.

This ongoing interaction branch depends on still-open PR #26 and draft PR #28.
Do not change main, production data, submodule, paused automation or App objective.
