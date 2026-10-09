# Historical wave and launch laboratory - exploratory preview v1

Registered before case evaluation on 2026-10-03 (Asia/Taipei). This is the
authorized small-case visual comparison, not a new full catalog, trading
backtest, download, source-policy repair or replacement of old results.

## Owner decisions

Retrospective wave membership is the future definition; this preview does not
switch the market atlas. Major rallies may have no identifiable launch. Future
atlas area uses gain from a fixed representative wave start: twice gain means
twice equivalent diameter; 100x reliable historical cap means 1.25x area. No
hidden area floor. Full-catalog target is all usable local history from 2010
through a pinned snapshot, subject to separate action/delisting coverage audit.

## Bounded inputs and selection

Reuse only verified market-atlas.v1 projection: 2019-01-02..2026-08-14 official
adjusted/raw closes and dated findings. Record SHA-256, catalog hash, actual
case ranges and missing rows. Do not use inconsistent legacy CSV loaders.
This preview does not imply 2010 coverage or completed classification evidence.

Preselected inspection cases, not pattern ground truth: 3017 and 2330
(2019-2026 long paths), 2609 (2020-2022 shipping), 9919 (2019-2021 abrupt
move), 3481 and 2002 (2019-2023 cycles/consolidation), 2498 (2021-2023
rebound/retreat), 4743 (2019-2022 volatile path). Keep cases even without
candidates. Label the inspection question, not an unmeasured verdict.
Explicit synthetic paths: slow 10x, short burst, deep pullback/new high,
consolidation/relaunch, failed launch, flat control, jump and missing quotes.
Never give synthetic paths real security names or measured-result labels.

## Provisional methods

Fit log adjusted closes; raw is a display toggle only. Preserve dates/rows;
split fits at null/invalid values and source-quality events. Slope units are
market sessions. Halts/zero-volume and action-event details are unavailable
in this projection; disclose that limitation rather than inventing states.

A: exact dynamic programming of independent least-squares lines plus segment
penalty; not PELT. B: piecewise-linear trend filtering minimizing
0.5*||y-f||^2 + lambda*||D2 f||_1; disclose numerical convergence. Fine,
balanced and coarse are sensitivity settings, not optimized rules. Support
lengths regularize phases, not return-based inclusion horizons. Compare
negative-to-positive reversal, flat-to-positive launch, and positive-slope
acceleration. Save speed change, persistence, relative daily volatility,
ensuing segment return/drawdown separately, without probability/composite score.
Forward assessments end at the ensuing segment boundary; last segments have
unknown outcomes. Retain failed candidates. Match nearby same-type candidates
across scales; support counts are not probabilities.

Independent wave baseline uses consistent directional reversals, no rolling
lookback or maximum duration. Balanced small/large drawdowns are provisionally
25%/40%; alternatives are labelled. Retain >=60% peak appreciation as an
experimental display floor, not approved final inventory rules. Only complete
containment creates parent links. Peak and end confirmation differ; incomplete
boundaries are censored and never represented as certain endpoints.

Implementation clarification: the directional state machine tracks a trough
until the selected percentage rise confirms an upswing, then tracks the peak
until that scale's percentage drawdown confirms its end. This is independent
of the 60% retention floor. End confirmation does not mean a tradable exit.
Closing-price jumps exceeding a 1.35 ratio in either direction split runs;
they need separate event evidence before waves may bridge them. Numerical
iteration limits may increase to achieve the same solver tolerance/objective;
this does not tune the statistical penalties to the selected cases.

## Deliverable

Add #wave-lab within research_web and inherit themes. Price, two fitted paths,
launch bands, phases and nested wave strips share dates. Provide cases, scales,
layer toggles, raw/adjusted, log/linear, cursor/date, zoom, candidate evidence,
point table and local-only feedback/export. No invented ETF participation.
Figures derive from declared data or clearly marked synthetic paths. User
review determines semantic acceptance; no strategy conclusions follow.

Verify numerical fits, no-launch flat/monotone paths, gaps, jumps, censoring,
nesting and scale invariance with synthetic cases, then actual browser controls
and drilldown. Later validation cases must differ from method-development cases.
