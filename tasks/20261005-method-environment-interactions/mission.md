# Method / relative-strength / market-context exploration

Recorded 2026-10-05 before this batch's joint results are evaluated. The owner
has applied and resumed the revised App goal. This is one descriptive exploration,
not a strategy approval, account backtest, or independent confirmation.

## Question, prior evidence, and unchanged scope

Does adding an entry pattern to relative strength improve the balance between
future large-rise coverage, false positives, and non-winner price deterioration?
Conversely, what is lost when relative strength filters an entry pattern?
Prior atlas results were already viewed: F37 was more consistent than many
individual patterns; F10, F32, and F33 differed between daily and sparse panels.
Selection here is informed exploration, not a claim that these were chosen blind.

Reuse the exact `atlas-v2` outputs of `20261004-feature-discrimination-atlas` and
`market-context-v2` of `20261005-market-context-handoff`. No download, price
recomputation, new stock cohort, industry recoding, or recalculation of F37 ranks.
The fixed window remains 2019-01-02..2026-08-14 because these compatible preserved
observations already exist and have been exposed. It is not the earliest possible
history. 2010-2018 and stock outcomes after 2026-08-14 are not added. The 0050
reader verifies its whole published package, already exposed through 2026-10-02;
only same-date past-only rows within the atlas window enter this experiment.

The current-reference stock cohort is not survivorship-complete; industry is not
PIT-certified. Prices are permanent-factor-adjusted closes, without cash-dividend
total-return accounting. Source vintages differ between the two packages and are
preserved, not spliced. Past-only calculations do not certify historical source
availability. These limitations block investment-readiness claims, not this
explicitly conditional descriptive comparison.

## Fixed arms, populations, and contexts

Three families, reusing saved binary values exactly:

| Family | Method                                                | Hypothesis link             |
| ------ | ----------------------------------------------------- | --------------------------- |
| F10    | Close above the preceding 60 highs                    | H01 continuation / breakout |
| F32    | Close above SMA60 and negative five-session return    | H04 strong-stock pullback   |
| F33    | Legacy 20-low / five-bar subsequent reclaim component | H02 reversal / 2B           |

Within EACH family compare four arms: `all`, `method`, `relative_strength` (F37,
top-quintile contemporaneous 60-session stock return), and `conjunction` (method
AND F37). F37 is not excess return over 0050. No threshold/weight search.
All four arms use the SAME method-known AND F37-known support. Outside it every
arm is unknown, even if one operand is false. Base-eligible rows remain in the
availability counts, so complete-case restriction is visible. Labels retain
their own known/unknown status; unknown is never recoded as failure or zero.

Join the context by exact `asof_date`, many stocks to one benchmark row; retain
every atlas row. Reject duplicate context dates, wrong benchmark/layer, future
information cutoff, duplicate stock/date keys or inconsistent calendar indices.
No nearest join, fill or inner-join deletion. Missing dates become explicit
`unknown` with a separate missing-context reason. Known context states are `up`,
`down`, `consolidation`, and `mixed`; `unknown` is reported separately. No
retrospective state or launch/resumption event is used as a predictor this batch.

Panels: all eligible daily rows and the ORIGINAL calendar_index modulo 126 = 0
grid. Never reindex the grid after filtering. Both contain stock dependence;
daily rows also overlap heavily. Neither represents independent trade attempts.
No new event-onset sampler or data-driven grid offset is added this batch.

Outcomes: primary existing label_126 (a future close reaches 2x within 126 slots),
secondary existing label_63 (1.5x within 63). Require the original full-path
completion semantics. A selected non-winner includes both small rises and falls.
It is NOT a losing account trade, and a labelled winner is NOT captured profit.

Each panel/family/label reports pooled, each of five market states, and each
calendar year 2019-2026 SEPARATELY, not state-by-year-by-industry intersections.
Maximum 3 families * 4 arms * 2 labels * 2 panels * (1 + 5 + 8) = 672 binary
comparison rows. Paired differences are derived from those rows, not extra
searches. Empty groups may be absent and are not positive evidence. Industry /
leader-laggard hypotheses remain a later separately registered batch.

## Outputs and provisional continuation rule

Preserve all confusion cells, same-support base rate, precision, non-winner share,
winner coverage, feature/label missing counts and extreme unknown-label bounds.
For selected known outcomes retain distinct issuers/dates and distributions
(count, missing, mean, p10, median, p90) of terminal return, minimum future-close
return and peak-to-trough drawdown, separately for all / winners / non-winners.
Wait-to-target is summarized only for known winners; non-winners have no target
waiting time, rather than a fabricated zero. These are price paths, not costs,
fills, exit policies, account return, or risk budgets. Paired rows expose change
against both the plain method and F37, including retained winner counts. Retained
winners are the actual candidate/control intersection, not candidate total winners
divided by control winners when those sets differ. For method versus F37, the
numerator is the conjunction's true positives and the denominator is F37's true
positives. The ratio is undefined when the control has no known winners.

Before reading results, fix this bounded triage, NOT a final acceptance gate:
consider a method or conjunction for account-design work only if its PRIMARY
pooled precision exceeds same-support F37 in BOTH panels, each panel has at least
30 selected known observations and 10 selected issuers, and it retains at least
25% of F37's known winners (intersection definition above) in BOTH panels. For daily 2019-2025 annual cells with
at least 30 selected known observations for both candidate and F37, require at
least four evaluable years and strictly higher precision in a strict majority.
2026 and market-state/secondary-label cells are diagnostic, never rescue gates.
These are provisional support/stability screens, not significance tests.

Non-winner price deterioration and unknown-label bounds must accompany any
nomination; the parent must not call a statistically promising count a profitable
strategy. No extra numeric loss budget is invented here. A nomination permits
designing at most ONE next executable account experiment with new preregistration,
not automatic execution or opening a new period. If multiple qualify, prefer the
larger minimum winner-retention fraction across the two panels; ties use F10,
F32, F33 then plain method before conjunction. If none qualifies, stop these
exact combinations for account promotion and choose a different reasoned batch.
Do not tune thresholds or select an attractive market-state cell as a rescue.

## Execution, evidence, and preservation

Use the existing research-job.v1 runner. Preparation only enumerates/hashes inputs
and validates contracts; it does not calculate new market comparisons. Bind all
consumed atlas/context files, code/import dependencies, runtime and contracts in
the packet, commit the code/mission/packet before execution, and supply its exact
approved digest once. One initial run, 1,800-second wall-clock budget; at most one
diagnosed implementation-only retry under a new job ID without changed definitions.
Preserve failed outputs. No parameter sweep, download, automation, confirmation,
holdout, or goal modification is authorized by this packet.

Synthetic tests cover common-support missingness, all four confusion cells,
context joins/cutoffs, fixed-grid membership, non-winner attribution, wait counts,
and triage boundaries. Unchanged atlas/context producers retain their prior tests.
The parent reviews statistical design and judgment; a bounded worker may implement
pure calculations and synthetic tests, not view results or alter this mission.

Store this task's report, complete compact comparisons/path summaries/triage,
packet and completion receipt through the existing task/index conventions. Bulk
source files stay in the already preserved atlas locations; do not overwrite or
move them. New-clone access to compact results must not require the source worktree.
Record the current branch's dependency on reviewed, not-yet-merged PR #26. Update
the shared exposure registry only after input/receipt reuse verification, keeping
the preregistration's registry snapshot intact and never making old dates unseen.
