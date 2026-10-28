# Exact integer count-plan optimization

This is an execution amendment to `pattern-scan-local-remaining.v5`, not a new
research definition, selection, universe or acceptance rule. The owner requested
an efficiency audit, then paused D for optimization and a reboot on 2026-10-28.
Work resumes on `codex/pr17-count-plan-performance` from main `9073c381`.

## Why the old calculation is expensive

The original preparation has 1,942 stocks on 4,110 aligned calendar dates
(7,981,620 stock/date positions). Conditions evaluate 52 features and, after
development selection, up to 92 one-, two- and three-atom candidates. Each event
belongs to eight combinations of its split, era and market facets. A heavy
candidate group therefore expands each event into as many as 1,152 temporary
membership rows before joining string cell identities and grouping them again.

Existing phase measurements identify the count matrix as the main cost: 78.54%
of measured B2 group wall time and 81.66% of B4's last heavy group, compared with
6.69%/4.74% for reading frames and 1.10%/0.82% for summary writing. These are retained
runtime observations, not new market evaluations.

Completed phase receipts, complete group tables, event projections and saved
development selections are reused. Internal repetition remains: every group and
horizon reads its stock projections and reduces its own event population. A
group has no partial-stock accumulator checkpoint, so an interruption discards
that group's unfinished accumulation. The six-hour capacity timeout and the
owner-requested stop each interrupted four groups. Published groups were adopted,
not recomputed. Q4 and followup retain their global/industry barriers.

## Equivalent calculation

`StockCountPlan` compiles each condition's registered cells to integer positions.
For one stock it obtains the unchanged 21 int64 event-count vectors, counts each
condition into state/year/market buckets using unweighted integer `bincount`,
then adds the occupied buckets into their eight registered facets. It constructs
the public sorted cell/stock/year matrix only at the end. No event-by-feature
string table or event-by-facet merge is needed.

The public `stock_memberships` and `aggregate_memberships` remain the independent
legacy oracle. Integer counts, missing/unknown/censored categories, candidate
N/A-before-false-before-unknown precedence, cross-check-only candidate facets,
zero cells, stock identities, sorted rows and int64 dtypes remain unchanged.
The existing per-call allocation guard and too-small-for-one-event rejection
remain. All complete-stock summaries still receive one whole-stock matrix.

## Bounded measurement protocol

Compare the old `StockCountPlan` from commit `73635ce` with the new implementation
on identical inputs; time plan construction and matrix calculation separately,
then perform exact DataFrame equality outside the timers. Synthetic coverage uses
4,110 events, all 17 years, all 52 features, mixed known/unknown/N/A states and 92
candidates. A separate read-only check uses four existing B3 `C-base-all`/126
stock projections, two from each split, with their original saved selection.
It publishes no study group and copies no inputs.

Compare 1/4/8/10 workers on the same 40 synthetic stock jobs, one numerical thread
per worker and one reused plan per worker. Record startup separately and preserve
wall/CPU timing plus the complete owned Windows Job committed-memory peak under
8 GiB. The serial reference is an engineering comparison only. Small-sample
throughput and memory are not full-market capacity or a full-study ETA.

### Measured engineering results, 2026-10-28

On this i7-12700 host, the synthetic exact comparison produced 152,322 identical
matrix rows. Matrix wall time fell from 15.868 to 1.162 seconds (13.65x); CPU fell
from 15.219 to 1.141 seconds. Plan construction increased from 0.180 to 0.939
seconds, paid once per group worker rather than once per stock.

| Workers | 40-job execution wall (s) | Setup wall (s) | Jobs/s |
| ------- | ------------------------- | -------------- | ------ |
| 1       | 73.207                    | 1.175          | 0.546  |
| 4       | 12.448                    | 1.381          | 3.213  |
| 8       | 9.913                     | 1.485          | 4.035  |
| 10      | 10.554                    | 1.722          | 3.790  |

All pool configurations agree on per-stock row counts and count-field totals;
that scalar check does not replace the single-stock exact matrix comparison.
The complete synthetic benchmark Job peaked at 1,737,994,240 bytes (1.62 GiB),
exited zero in 132.167 seconds, and was confirmed empty. The 1-to-4 ratio is
superlinear in this single sequential trial; host scheduling and caching were
not controlled. Eight workers improved this small compute sample by 25.6% over
four; ten did not improve it. Full-market reducers retain additional per-stock
counts, so neither small peak authorizes eight workers in the full run.

The read-only original-input comparison covered stocks 1101/1102 (development)
and 1104/1110 (cross-check), 188/191/193/152 events, with all original 92 candidates.
All four matrices matched exactly, including order and dtypes. Old/new matrix
CPU seconds were 4.328/0.859, 3.953/0.547, 3.484/0.875 and 3.234/0.516 (4.0–7.2x).
The last old wall observation was 19.973 seconds despite 3.234 CPU seconds, so
its wall ratio is not used as a speed claim. The read-only probe Job peaked at
681,295,872 bytes, exited zero, and published no study output.

The small [engineering evidence archive](results/count-plan-probe-v5.zip) retains
the measurement helpers, original JSON metrics and whole-Job receipts. Extract
it into this checkout's `.tmp/` and run the recorded commands with the existing
virtual environment; the real-input helper requires the original paths and a
producer-idle check. No input, source or intermediate byte hashes were added.
These diagnostics used uncommitted optimization code atop `9073c381`; they do
not certify clean-source full-market execution. The code and tests accompany
this amendment in its delivery commit.

Final archive SHA-256:
`368449994098e62816f6ef8cf02975b0fb4afc84eb2388b509fe3630c7882955`.
Focused count/membership/dense tests passed 83 cases; conditions/pool/continuation
integration tests passed 84 cases. A separate static review found no concrete
equivalence defect. Hosted validation and actual full-market capacity remain
separate gates.

## Checkpoint and restart boundary

The owner stop is recorded in the existing scratch run's
`launches/continuation-20261027T120959Z/owner-pause-for-optimization.json`.
That attempt's Job peak was 4,374,364,160 bytes; the nonzero termination exit was
the requested pause, not an unexplained runtime failure. B1/H1/B2/B4 retain all
three phases (12 of 36 terminal receipts), and B3 retains 16 of 26 conditions
groups. The OS writer lock is free. The `running` metadata label is resumable
state, not evidence of a live process.

The `d` heartbeat is paused during optimization. Resume only from clean, fixed,
validated code, with the producer idle, outside its writer window and at least
12 GiB host memory available. Keep the same original stock-result and
`q2-q6-v6` scratch run, the 8 GiB Job cap and all checkpoints. The original
generation hold remains until final result delivery merges. Measure useful
remaining full-market groups under the optimized code before accepting its
long-run capacity; do not treat the old code's capacity report or synthetic
probe as that evidence. Increasing workers requires measured throughput and
capacity, not simply the host's core count.
