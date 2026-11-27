# May–August legacy reading editions (P5)

## Purpose and boundary

This batch implements P5 of the [dashboard readability decision](2026-11-02-dashboard-ux-and-report-readability.md).
The owner needs to distinguish the requested question from the experiment actually
run before discussing the next direction. Several original reports generalized a
limited failure to an entire strategy family, mixed account and position returns,
or retained interpretations that later reports corrected.

Each task receives only `reading-report.md` and `reading.json`. The original
missions, reports, study cards, outputs, receipts and hashes remain unchanged.
There are no research runs, market-data reads, predecessor reads, new hashes or
data copies. The editions summarize saved Markdown evidence, not a fresh audit of
daily prices or all result payloads. P1 supplies the independent reading metadata
and Dashboard reader; no new HTML package or data catalog registration is needed
for these editorial views. Existing shared-data/provenance records stay intact.

## Editorial disposition

`ready` means a bounded, readable account of the saved evidence. It grants neither
owner acceptance nor strategy acceptance. A partial or negative answer can be
ready; the unknowns remain visible. `history` is reversible and does not mean a
report is impossible to improve. No source is reconstructed to resolve a gap.

| Task and edition                                                                                              | Authoritative sources read                                                       | Question coverage and important correction                                                                                                                                                                                                                                           | Disposition                                                                        |
| ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| [20260510-two-b-template-smoke](../../../tasks/20260510-two-b-template-smoke/reading-report.md)               | mission, nightly report, walkthrough, strategy diagnosis; later 2B decomposition | Template workflow and mixed-entry limits explained. The saved execution starts in 2024 while mission/diagnosis starts in 2022; diagnosis and nightly report describe different results. No unique performance or endpoint inferred.                                                  | history: version/period reconciliation unresolved                                  |
| [20260812-loop-explore-v2](../../../tasks/20260812-loop-explore-v2/reading-report.md)                         | mission, nightly report; later 2B decomposition                                  | Eight iterations summarized as an exploratory selection process. Internal accepted labels are not independent confirmation; subwindow dates, trade denominators and complete gates are absent.                                                                                       | ready: partial answer; `data_period: null` because actual split is not established |
| [20260816-kline-strategy-category-fit](../../../tasks/20260816-kline-strategy-category-fit/reading-report.md) | mission/report; archetype report, MAE retrofit, ratchet generalization           | Signal quality and account benchmark comparison separated; old corporate-action vintage explicitly bounded. Do not combine old S1–S3 with later results or reject all financial-stock/breakout methods.                                                                              | ready: historical-vintage comparison                                               |
| [20260820-kline-archetype-extension](../../../tasks/20260820-kline-archetype-extension/reading-report.md)     | mission/report, mae_retro; stop isolation and ratchet generalization             | Primary 0/15 retained; post-hoc pooling, small samples and costs disclosed. Later MAE/holding-period corrections replace claims that low account drawdown proves safety.                                                                                                             | ready: bounded negative/partial result                                             |
| [20260821-2b-entry-decomposition](../../../tasks/20260821-2b-entry-decomposition/reading-report.md)           | mission/report; ratchet generalization                                           | Mixed entry, independent 2B and scale-out effects separated. Positions versus sells, open positions versus closed-position tests, and the missing proof of B superiority are explicit.                                                                                               | ready: partial answer                                                              |
| [20260821-stop-mechanism-isolation](../../../tasks/20260821-stop-mechanism-isolation/reading-report.md)       | mission/report; 2B decomposition and ratchet generalization                      | Higher per-entry PnL does not imply lower account drawdown. Fallback and changed entry occupancy limit attribution; later failure to transfer is linked.                                                                                                                             | ready: configuration-specific finding                                              |
| [20260822-ratchet-generalization](../../../tasks/20260822-ratchet-generalization/reading-report.md)           | mission/report; stop isolation and runner retention                              | S2 prevents general transfer. Shared-entry MAE and holding time are paired; neither deeper MAE nor its association with duration proves a universal safety claim.                                                                                                                    | ready: bounded non-transfer result                                                 |
| [20260823-rank-profile](../../../tasks/20260823-rank-profile/reading-report.md)                               | report; selection mission; turnover report                                       | No separate mission exists. Diagnostic mean rank-band comparison lacks power to establish equivalence or prove wider holding bands harmless. Later path-based reversal is linked.                                                                                                    | ready: diagnostic, not preregistered result                                        |
| [20260823-selection-vs-random](../../../tasks/20260823-selection-vs-random/reading-report.md)                 | mission/report; rank profile, turnover report, tail-selection mission            | Formal findings distinguished from non-overlapping confirmation and absolute trading cost. The statistic is a noncompounded position sum, not account balance.                                                                                                                       | ready: bounded ranking evidence                                                    |
| [20260823-turnover-mechanism](../../../tasks/20260823-turnover-mechanism/reading-report.md)                   | mission/report; regime-overlay and runner-retention reports                      | One setting clears the stated gates; result is not universal across scores. Later account-based 2022 reading corrects the use of entry-year position contributions.                                                                                                                  | ready: configuration-specific result                                               |
| [20260823-regime-overlay](../../../tasks/20260823-regime-overlay/reading-report.md)                           | mission/report; ranking-horizon and tail-selection missions                      | No three-value plateau. Detector history is distinct from strategy history; cash/0050 comparison does not measure detector contribution exactly as zero. Static blending and different return bases are bounded.                                                                     | ready: bounded negative result                                                     |
| [20260824-ranking-horizon](../../../tasks/20260824-ranking-horizon/reading-report.md)                         | mission/report; value-chain report, tail-selection mission                       | Eight failed candidates do not disprove all ranking. Mission common train start is 2020-01-01; results say 2020-02-03. Both are disclosed without inventing a correction.                                                                                                            | history: common-period discrepancy unresolved                                      |
| [20260824-value-chain-ignition](../../../tasks/20260824-value-chain-ignition/reading-report.md)               | report; tail-selection mission/report                                            | No separate mission exists. Only the stated ignition definition and twenty-day event comparison are covered. Exact window dates are missing, snapshot bias direction is not assumed known.                                                                                           | ready: bounded event result; `data_period: null`                                   |
| [20260826-runner-retention](../../../tasks/20260826-runner-retention/reading-report.md)                       | mission/report; book-size report §3                                              | Capture/participation denominators and post-hoc pool statistic explained. Later double-counted occupancy and suspended-holding slot defects affect the claimed mechanism; original configurations were not recomputed here.                                                          | history: later defect impact unresolved                                            |
| [20260826-tail-selection](../../../tasks/20260826-tail-selection/reading-report.md)                           | mission/report; ranking-horizon mission; runner-retention report                 | Owner's right-tail/selection/churn questions distinguished from beating an index. Both tails shown. The claim that every arm changes sign is not repeated because the table does not support it; secondary sixty-day count discrepancies are outside the edition's numerical answer. | ready: primary twenty-day comparison only                                          |

Total: **15 editions, 12 ready, 3 history**. The three historical editions remain
readable with an explicit exclusion reason. Restoring default visibility requires
resolving the named evidence inconsistency or impact, not editing a hash or hiding
the original finding. No rerun is requested or authorized by this disposition.

## Verification and remaining acceptance

- Read each batch task's saved report and existing mission in full; diagnostics
  without a mission are labelled as such. Read the relevant later correction
  sections and cite them from the edition and its metadata.
- Checked headline values and denominators against those saved tables. An
  additional decimal-token check found every decimal value verbatim in the
  edition's declared sources; this supports transcription checking, not scientific
  validation of the original calculations.
- All 15 registrations passed P1's `ReportReadings.record` validation using its
  read-only sibling implementation. Edition paths, task-relative source paths,
  existing Markdown sources, date syntax and verbatim answer/limitation excerpts
  were checked. All source links resolve inside this repository's tasks.
- Existing tracked files and the Git index remained unchanged. No evidence hashes
  were generated or modified. Base `.gitignore` still ignores `reading.json`;
  P1's allowlist is an integration dependency, not permission to force-add files.
- Independent content review, normal hooks/CI and integrated Dashboard rendering
  remain with delivery. This batch has not started a preview, accepted browser
  rendering, merged a PR, or claimed full legacy research closeout.

The planned PR should explain the problem as missing question coverage and
overbroad interpretations, the result as separate source-linked reading editions,
and the limitations as the three explicit history holds plus saved-evidence-only
verification. It must not present editorial readiness as owner acceptance.

## Reader-first revision — 2026-11-04

Applied the merged study-presentation skill and its writing, reader-first and magazine references from the primary checkout. This revision keeps the 15 reading editions as the editorial sources for the shared web reader. It changes no original mission, report, result or hash, and creates no per-study HTML package. The three `history` states and reasons remain unchanged; `history` is not reclassified as archived.

All 15 editions now open with the saved answer and the material evidence boundary. Research codes move behind plain group names; relevant percentages identify their population, time origin and denominator. Compact comparisons replace the repeated question/comparison/answer/warning template where they reduce reading effort. Hypothetical prices or counts explain definitions and are explicitly labelled as examples. Generic approval warnings and unmeasured reader-action advice were removed from report prose; editorial readiness retains its meaning in this disposition and the shared interface.

| Edition                              | Concrete reading improvement                                                                                                                                            |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 20260510-two-b-template-smoke        | Two source versions shown separately with their starting dates; explains partial sells versus complete positions, retains unknown end dates and version reconciliation. |
| 20260812-loop-explore-v2             | Opens with the failed original direction and later reversal; separates eight attempts from six reused validation evaluations and preserves unknown units/split dates.   |
| 20260816-kline-strategy-category-fit | Names the three entry mechanisms and five industries; explains return/drawdown with a labelled example and keeps the pre-backfill vintage visible.                      |
| 20260820-kline-archetype-extension   | Defines contraction, box breakout and short-term rebound; places per-entry capital and closed-position counts beside pooled values, preserving post-hoc status.         |
| 20260821-2b-entry-decomposition      | Plain mixed/momentum/false-break groups replace arm-only labels; separates signal-rule success from risk-rule failure and explains partial sales and adverse excursion. |
| 20260821-stop-mechanism-isolation    | Explains the upward-only box boundary; keeps per-entry improvement beside account drawdown and labels fallback implementation.                                          |
| 20260822-ratchet-generalization      | Defines peak-following and box-following exits; pairs named entry groups with their five-industry result and common-entry holding duration.                             |
| 20260823-rank-profile                | Shows same-day grouping then twenty-day tracking; identifies uncertainty from 30 validation dates and distinguishes cross-sectional rank from a held-position path.     |
| 20260823-selection-vs-random         | Explains same-entry/same-exit random controls, ranking-band multiples and percentile meaning; places return and turnover on distinct labelled columns.                  |
| 20260823-turnover-mechanism          | Pairs original and twenty-day minimum holding; places 94% beside its excess-return denominator and distinguishes position sums from account returns.                    |
| 20260823-regime-overlay              | Defines the advancing-stock signal with a count example; separates the long detector profile from the strategy window and pairs cash/0050 responses.                    |
| 20260824-ranking-horizon             | Names long-window and recent-month exclusion; pairs turnover, return and drawdown while preserving the unresolved common-start discrepancy.                             |
| 20260824-value-chain-ignition        | Defines group ignition and laggards with a ten-stock example; states the event-to-outcome sequence, overlapping sample issue and unknown calendar bounds.               |
| 20260826-runner-retention            | Explains the 150% population threshold, capture versus participation, and full-pool denominator; keeps later slot defects visible with their source.                    |
| 20260826-tail-selection              | Explains first screening versus within-list ranking; pairs both price tails on the same twenty-day window and names date-level uncertainty.                             |

Predecessor and follow-up mentions now carry local Markdown report links and describe what they supply. Additional report references are registered in the sidecars. These are the reader's navigable source relationships; the shared web presentation and routing remain parent-owned. No new historical result is inferred from a follow-up or from another checkout.

Representative visual candidates for the shared viewer are the turnover report's original-versus-twenty-day pair (separate scales for turnover and return), and tail-selection's full-pool-versus-top-thirty probabilities (same window and scale for the up/down proportions). They are already expressed as labelled tables. The current revision has passed all 15 `ReportReadings` registrations and exact question/answer/limitation checks, with 12 ready and 3 history preserved; 99 Markdown links resolved on the first static check. This establishes source navigation and metadata consistency, not fresh-reader understanding or visual acceptance. Parent-owned independent two-pass review and web/desktop/mobile acceptance are still pending for this revision.

### Independent review and second edit pass

The parent coordinated an independent reader-only pass followed by a mission/source comparison. The second edit pass incorporated the resulting concrete fixes: the stop-isolation opening now names both baseline exit triggers; tail-selection states both tails and the full-pool/top-thirty denominator in its opening; runner-retention names its 64-stock population, first-top-ten time origin and training window beside the capture figures; ratchet-generalization separates per-entry industry wins from the shared-account result (two of five for each entry type). Technical opening terms were replaced with descriptions of held-position price declines, long-period market-signal statistics and returns relative to all eligible stocks. Known calendar windows now appear directly in the opening; unknown split dates and the three historical holds remain explicit.

Both editorial review passes were completed and their requested corrections applied. This is still separate from the parent-owned shared web presentation and actual desktop/mobile acceptance. The second pass changes no saved source or acceptance rule; question, answer and limitation remain verbatim in each edition and synchronized with its sidecar.
