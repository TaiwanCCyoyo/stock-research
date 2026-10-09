# Feature discrimination atlas: prospective exploratory contract

Recorded 2026-10-04 before evaluating this batch. Owner authorized completion of
the feature/non-winner data organization without repeated routine confirmation.
This is a descriptive feature study, not a portfolio strategy, trading advice,
independent validation, or an approval of a captured-account hit definition.

## Question and fixed scope

First compare which features precede large observed rises and how many eligible
feature-positive observations do NOT subsequently rise. Do not choose a breakout
strategy first. Preserve ordinary, failed, unknown and feature-negative cases.
Methods are collected broadly, while this first runnable batch uses explicit
fixed definitions, not an automatic search across all theories or parameters.

Use the physical local price/metadata/action snapshot in this worktree, read-only.
The supplied data files cover additional history; this batch reads quote/action
rows only in 2019-01-02..2026-08-14. This window is already recorded as viewed in
research-registry.json and overlaps previous price and catalog studies. It is
chosen for developmental continuity, NOT because 2019 is the earliest data, a
source restriction, or a new holdout. No 2010-2018 or post-2026-08-14 outcome is
opened by this batch; their usable coverage and exposure are not certified here.
Early feature warmup uses only this same window, with insufficient history null.

This is the observable-cache cohort, NOT a survivorship-complete historical
Taiwan market. Current metadata identifies ordinary TWSE/TPEx stock references;
it does not establish historical industry membership. Record cached codes absent
from metadata, excluded instruments, no-price references and coverage gaps.
Include all qualifying cached stocks, not a chosen list of winners or a
whole-history minimum-bar filter. Future end dates do not select eligibility.
No download, data overwrite, cache migration or website fixture is required.

## Observation and price definitions

- Calendar: sorted distinct official quote dates in the fixed window, a measured
  calendar proxy rather than proof of a complete exchange-calendar artifact.
- Unit: one security and one calendar close. Keep daily data; never call daily
  overlapping observations independent stock opportunities. Also report a fixed
  grid with calendar-index modulo 126 equal to zero, not a best-offset search.
- Base eligibility: ordinary stock reference, positive internally consistent OHLC,
  positive observed volume today, and at least 60 consecutive calendar observations
  of usable prices through today. Individual longer features retain own warmup nulls.
  No liquidity/return-based preselection; trailing liquidity remains a feature.
- Available source: official OHLCV only. Non-official rows are counted/excluded,
  never silently relabeled or spliced across venue histories.
- Research price: apply the existing permanent corporate-action price-factor
  policy (splits, rights, reductions) to OHLC before feature/outcome comparison.
  Use unrounded raw-price times factor; no dividend-fill-window signal distortion.
  Cash dividends remain price drops. This is a restated price research proxy,
  NOT total return, share-entitlement evidence, or executable proceeds.
- Future multiplicative rebasing must not alter dimensionless past features;
  test this with synthetic prefix and scale-invariance cases. Historical source
  first-publication timestamps are not reconstructed; do not claim fully PIT
  fundamentals or classification. Current industry is descriptive stratification only.
- Unsupported/missing factors, duplicate conflicting dates, impossible OHLC and
  unexplained adjusted close jumps >=40% invalidate the affected price point.
  Missing calendar observations remain missing, never forward-filled. A future
  defect cannot retroactively remove an otherwise eligible observation; its label
  becomes unknown. Record all reasons. Corporate-factor adjustments do not prove
  economic shareholder profit and do not revise historical stored results.
- Turnover proxy is RAW close * observed volume in lots (thousand TWD). Volume
  features in this atlas use this proxy, not an invented share-adjustment factor.

## Outcomes, not account hits

Anchor is the observation close, not a retrospectively selected trough. Main label:
at least 2x anchor on a future CLOSE within 126 calendar trading observations.
Secondary label: at least 1.5x within 63. Both thresholds and horizons are parent
provisional exploratory choices; neither becomes the owner's account-hit gate.
The anchor itself is excluded from the future target search. Full follow-up with
usable anchor and all h future closes is required for a known primary label;
otherwise retain unknown/window-end or missing/invalid-path, even if an interim
rise is visible. Do not silently count delisted/missing continuations as failures.

Retain 20/63/126-session terminal return, maximum/minimum close excursion, maximum
peak-to-trough drop including the anchor, number of observed future sessions,
completion state, and earliest target waiting time. These are price-path facts,
not strategy PnL, account drawdown or executable stop-loss costs. Prior catalog
trough/peak episodes and this forward label are different objects; no false
one-to-one crosswalk or reuse of a hindsight episode as a causal trigger.

## Methods and comparisons fixed before results

F01-F32 and continuous components are specified in
`research_core/feature_atlas_features.py` / its exported FEATURE_SPECS. Families:
MA location/crossover/slope, momentum, prior-high breakout, Bollinger contraction
and confirmed closes, ADX/ATR, turnover contraction/surge/imbalance, spring,
three-session 2B recovery proxy, engulfing/piercing/harami/hammer, inside-bar break,
Wilder RSI, MACD, range contraction and strong-trend pullback. Numeric defaults are
design choices, not fitted optimums. Method source/legacy crosswalk goes in report.
A component/proxy is not a faithful full reproduction of a named trading theory.
Cup/handle, full Wyckoff phases and RSI divergence remain distinct not-implemented
full-method entries, not fabricated signals. Preserve them in the method inventory.

Parent additionally permits a separate legacy-stateful 20-low/5-bar-reclaim 2B
component (F33), SMA5/10/20 convergence <=2% (F34), and their convergence +
nonnegative 19-session close change conjunction (F35), with exact definitions in
the legacy-feature module. These do not include old position/exit/sizing logic.
F33 waits for a later bar after a break; same-day spring F20 is a separate feature.
RS20/RS60 compare each eligible stock's return with eligible contemporaneous
stocks, with deterministic average ties; F36/F37 top quintile (>=0.8) respectively.
F38 is stock ret60 greater than contemporaneous 0050 ret60. Missing reference
is unknown. No weighted score fitting or feature pair search in this batch.

Compare all 38 flags against both outcomes, pooled and separately by observation
year, 0050 regime and current metadata industry. No full Cartesian cross of all
contexts. 0050 regime uses Close/SMA60 and 20-session SMA60 slope: above+rising
up, below+falling down, other known mixed, missing unknown. It is a coarse fixed
descriptor, not a proven regime detector or portfolio asset. Also produce the
same comparison family on the pre-fixed sparse grid, with low support visible.

Budget is 38 * 2 * (1 + observed year categories + regime categories + industry
reference categories), at most 100 industry categories, for EACH of daily and
sparse panels. Store actual count including empty/unknown-support cells. Continuous
feature quantiles by outcome are descriptive only, not additional optimized bins.
No post-result parameter changes, only measurement corrections with old artifacts
preserved and explicit retry version/reason. All negatives stay in the output.

Each comparison records TP/FP/FN/TN on feature-known and outcome-known eligible
observations, feature missingness, label unknowns and selected unknowns. Report
winner coverage, non-winner fraction among selected, precision, same-context
base rate and lift; undefined denominator is null. Include pessimistic/optimistic
selected-unknown bounds, unique issuer/date counts, and per-year variation.
No binomial IID p-values or ranking claims from overlapping daily observations;
the sparse panel still has cross-stock dependence and is not independent validation.

## Durable evidence and completion

Stable dataset identity hashes explicit input bytes, definitions and schema;
sample key combines dataset identity, security ID and as-of date. Feature and
outcome definition IDs are separate. Classifications include snapshot identity
and basis, not invented effective dates. Existing catalog events keep their native
IDs and dataset versions; unknown links remain null. UI and CLI read the same
manifest and tables, not independently recalculated summary numbers.

Write one new immutable run under this task, including per-security Parquet
features/outcomes/eligibility, full comparison tables, source inventory, method
definitions, quality records, source/output SHA256 manifests and completion receipt.
Use existing registered-job/receipt and research-result envelope; any non-JSON
sidecar is enumerated and verified through the dataset manifest. Keep an explicit
small tracked aggregate and report; large rows stay local with an additive second
copy under the primary repository's task directory and hash verification. This
second copy is same-machine redundancy, not an off-machine disaster backup.
Do not overwrite an existing dataset/run or scatter sole artifacts in .tmp.

One initial job, at most two diagnosed measurement/implementation retries, each
with a new ID and preserved outputs. Maximum deterministic runtime per attempt:
3600 seconds. Test core calculations with synthetic hand-checkable cases first.
Pin mission, code, data and runtime in an approved packet before any evaluation.
After completion verify all output identities and recompute aggregate evidence
from stored rows; retain local query paths and an explicit list of concerns.
No automatic next strategy, confirmation/holdout or automation is authorized here.
