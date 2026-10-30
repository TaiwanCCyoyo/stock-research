# Followup projection preparation optimization

This is an execution-only change to the existing v5 calculation. The owner
authorized measuring and implementing improvements in isolation before deciding
whether to interrupt the active continuation. No research definition, selection,
universe, acceptance rule, checkpoint format or output schema changes.

## Measured cause and implementation

A read-only profile of existing L2 event projections for stocks 1514, 2002 and
3030 found two calls to `event_flags` per event/horizon. Each call parsed and
validated the visible pivot prefix and checked every date in that prefix. The
profile is diagnostic, not an uninstrumented speed comparison.

`followup_values` already validates the stock calendar once. A private per-call
plan now parses newly visible pivots as event endpoints extend the prefix, and
filters prepared records when a later event has a shorter endpoint. It does not
validate unseen future pivots early. Each event's daily flags are built once and
reused for its observations. Standalone public flag APIs retain their validation.
The numerical kernels, missing-value behavior and pivot ordering are unchanged.

## Comparison protocol

Compare the new implementation against the original pure flags and followup
modules from fixed commit `3d978cf`, using the same three stocks' existing L2
event projections and original stock indicators/pivots, in place. Run old/new,
then new/old for each stock with one numerical thread; record wall and CPU time.
Check all four complete output tables exactly outside the timers, including
order, dtypes and nulls. No study output is published, no original input is
copied, and no new source/input/intermediate digests are added.

Bound the comparison with a separate 2 GiB Windows Job and a 240-second timeout.
Its peak measures the comparison, not capacity of a full-market continuation.
The existing long run continues with its own unchanged source and limits.

## Results, 2026-10-31 Taipei

All six old/new comparisons matched all four tables exactly. Each stock includes
both original horizons. The second round reverses execution order:

| Stock | Event/horizon rows | Round 1 old/new wall (s) | Round 2 old/new wall (s) |
| ----- | ------------------ | ------------------------ | ------------------------ |
| 1514  | 212                | 23.873 / 4.404           | 9.730 / 2.603            |
| 2002  | 178                | 7.432 / 1.600            | 7.250 / 1.582            |
| 3030  | 220                | 38.896 / 7.836           | 10.516 / 3.478           |

Observed wall speedups span 3.02–5.42x; CPU ratios span 3.10–5.42x. Large
between-round variation shows why these are bounded observations rather than a
full-run promise. Both arms shared a host with the continuing study. Plan
construction is included in every new call. Data reads and equality checks are
outside the timed calls. The complete comparison Job peaked at 249,868,288 bytes
(238.3 MiB), exited zero without timeout in 122.904 seconds, and was confirmed
empty. This small single-worker probe does not authorize higher concurrency.

The retained [engineering archive](results/followup-probe-v5.zip) contains the
read-only profiling/comparison helpers and original final JSON metrics. Extract
helpers into `.tmp/` to inspect the recorded paths; they require the retained
original inputs and two named source checkouts. No market results are included.

Final archive SHA-256:
`013cf1e1bca2320c323e4754828ad1d04781480a21515de68e353c639c9ef368`.

Focused flags/followup/local-resume tests passed 64 cases; an additional low-pivot
prefix case then passed with the followup test file (19 cases). The independent
static review found no blocking defect. Tests cover complete table equality,
prefix order, missing/censored paths, future-invalid-pivot validation timing,
duplicate rejection and automatically selected Y3 low-pivot support.

## Switching decision

Projection speed does not apply to conditions, Q4 or followup summary reduction.
Historical L1 logs show about 6 h 7 min between first and last projection messages,
then 1 h 21 min to the summary-complete message; these are log intervals, not an
isolated phase profiler. Interrupting during summary can discard uncheckpointed
reduction, whereas completed stock projections are reusable. Compare remaining
work savings with validation, capacity evidence and restart/revalidation costs
before changing the active attempt. This document alone does not select a new
runtime or replace its existing capacity receipt.
