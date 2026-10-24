# Bounded parallel continuation of PR17 v5

Current status, 16:15 Taipei: PR #81 merged as `24fff65`; PR #82 adds timeout
memory receipts and the full-market capacity gate below. The full run remains
paused until that follow-up merges, then begins with the bounded invocation.

## Prospective runtime amendment, 2026-10-24

The owner stopped the single-worker continuation and requires parallel execution,
leaving one or two physical cores for everyday use. The verified host has an
i7-12700 with 12 physical cores, 20 logical processors and approximately 64 GiB RAM.
The former instruction to run one whole family at a time is superseded for runtime
coordination by this owner instruction. The numerical definition stays v5; the
mission, acceptance rules, labels, horizons, fixed selections and stored results
are unchanged. The full `q2-q6-v6` run remains paused while this change is prepared.

The new work is bounded inside one existing 8 GiB Windows Job, including all pool
descendants, with at most ten workers and ten in-flight jobs. BLAS/OpenMP and Arrow
worker thread pools are limited to one to avoid nested oversubscription. The
launcher still reserves at least four additional GiB of host RAM. A worker count
is a concurrency budget, not a promise that Windows assigns particular cores.

Two independent phases use the pool:

- Event projections: one original stock per job, each writing a unique staging
  directory. Only the coordinator publishes it and updates the completion list.
- Conditions: after complete event preparation and fixed selection, one
  group/horizon per job. Every group still processes the same complete stock list
  in its original order. Only the coordinator publishes groups and reports progress;
  final paths and confirmation are assembled in original group/horizon order.

Workers attach to completed caches explicitly and must not silently rebuild a
missing projection during group reduction. Q4 and followup retain their existing
global/industry barriers; in particular, per-stock followup must not race writers
of the same industry holding block. Completed B1/H1 phases, 49 previously completed
groups and the partially built event cache are reused. Old receipts are not edited.

## Preregistered engineering probe

This is a bounded runtime/equality measurement, not a full study rerun or a new
evaluation of the market conclusion. It may run before review to provide evidence;
the full continuation waits for the runner change to merge. Output goes to a separate
labelled scratch run depending on both the original input directory and paused
`q2-q6-v6`; no source data or existing projection is copied or overwritten.

Compare worker counts **1, 2, 4, 8 and 10**, in that order, using identical inputs.
Warm the selected input-file bytes once before timed arms, recording warmup time
separately. Cache reference tables once for equality checks rather than repeatedly
reading or comparing the one-worker reference against itself.
The one-worker arm is a short reference measurement, not resumption of the full
serial research. Each arm has fresh output directories, and the containing Job has
an explicit 1,800-second limit.

- Conditions: first four sorted currently cached B2 stocks in each CRC split
  (development and cross-check), eight stocks total. Keep the original B2 selection.
  The pilot found about 98/109 seconds for its first two groups, so the original
  twelve-group matrix was stopped after 428 seconds instead of exhausting the
  1,800-second limit before higher worker counts. It retains its outputs and Job
  memory receipt (peak 867,196,928 bytes); it does not establish a speedup.
  Before the revised probe, fix two cases: `pattern:union` at 252 sessions and
  `C-base-all` at 126 sessions. Repeat both cases equally, once per pair of workers
  (one pair for worker counts one and two). This gives 2/2/4/8/10 jobs and keeps
  all requested workers occupied. Compare **jobs per second**, not unequal batch
  wall times. Every repeated job's three tables and top rows must exactly match
  its one-worker reference case. Missing groups refuse the probe.
- Projections: the first 16 sorted original stocks outside both the paused cache's
  completed list and original reusable B2 event parts, using a separate run-owned cache for each arm. Compare all five
  projection tables per stock exactly, preserving schema, dtypes, nulls and order.
- Record phase wall/CPU time, initializer and first-result latency, in-flight high
  water mark, IPC pickle bytes/time, worker native I/O and memory, and containing
  Job peak committed memory. Time equality comparisons separately after numerical
  and serialization timings; unavailable observations remain explicit.

Acceptance: all equality checks must pass and the Job must stay within its cap.
Choose the highest conditions job throughput above one worker; within five percent
of the fastest, prefer fewer workers. Require at least **1.2x** conditions throughput
versus the one-worker reference before claiming an improvement. Otherwise keep the
full run paused and use measured phase costs to identify the bottleneck. Report
projection speed separately and do not extrapolate a sample speedup into a promised
six-day completion time. No market acceptance rule is adjusted from this probe.

## Measured decision, 2026-10-24

The revised probe completed at 15:49 Taipei from clean commit `d067671`. All
parallel conditions outputs (72 tables and 24 top-row comparisons) and all parallel
projection outputs (320 tables) exactly match their one-worker references. The
one-worker rows are references, so their comparison counts are zero.

| Workers | Conditions jobs | Conditions wall, seconds | Jobs/minute | Throughput vs 1 | Projection wall, seconds | Projection speed vs 1 |
| ------- | --------------- | ------------------------ | ----------- | --------------- | ------------------------ | --------------------- |
| 1       | 2               | 266.938                  | 0.450       | 1.000           | 123.450                  | 1.000                 |
| 2       | 2               | 88.958                   | 1.349       | 3.001           | 42.911                   | 2.877                 |
| 4       | 4               | 87.395                   | 2.746       | 6.109           | 35.878                   | 3.441                 |
| 8       | 8               | 171.415                  | 2.800       | 6.229           | 52.919                   | 2.333                 |
| 10      | 10              | 223.219                  | 2.688       | 5.979           | 61.872                   | 1.995                 |

**Select four workers and at most four in-flight jobs.** Four is within five
percent of the highest conditions throughput (eight workers), exceeds the 1.2x
acceptance threshold, and is also fastest on this projection sample. Ten workers
do not improve either sample. The ten-worker ceiling remains available; the
continuation command uses the measured four-worker setting.

The containing Job peaked at **6,873,600,000 committed bytes (6.40 GiB)** under its
8 GiB cap. Whole-probe wall time was 1,462.078 seconds under the 1,800-second limit.
The launcher confirmed that its Job was empty before marking this engineering run
`complete`. At probe completion, `q2-q6-v6` remained paused pending runner PR #81's
owner merge; that PR subsequently merged at 16:05 Taipei.

The small final metrics and `run-receipt.v1` are retained in
[`results/parallel-probe-v5.zip`](results/parallel-probe-v5.zip). It contains
`summary.json`, `measurements.json`, `decision.json`, `probe-job-memory.json`,
`launch.json` and `run-receipt.json`. The receipt hashes the four final metric files
only; their archived bytes were checked against those hashes once. For relocated
verification, match the receipt's result keys to the same-named archive entries;
its absolute result paths describe the original scratch location. No input,
projection, source file or intermediate receives a new byte hash.

The full diagnostic run remains at
`D:/StockData/stock-research/scratch/20261013-pattern-scan/q2-q6-parallel-probe-v2/`.
The receipt identifies the original metadata and fixed selection by post-run
size/mtime observations, the samples, held generation and starting code commit.
Start and end both observed clean `d067671`; source stats were not captured at
startup, so the standard receipt records that observation as unavailable and
`runtime_code_verified: false`. It does not attest the loaded source bytes or
continuous input immutability.

These are small, sequential, single-host runtime measurements, including pool
startup in timed phases. They are not repeated randomized trials. In particular,
the superlinear conditions ratio is an observed sample ratio, not a claim of
sixfold full-market scaling. CPU placement, filesystem caching and other host
activity can affect it. The original input calendar, definitions and full-stock
barriers remain unchanged. Observe the full run before estimating its completion
date; do not apply the sample factor to the former six-day estimate.

Windows CI on this code passed **2,410 tests in 424.11 seconds**. Earlier local
Windows spawn tests also verified exact group tables with one, two and four
workers, failure draining, bounded admission and parent-only publication. The
published-artifact compatibility checks remain 17/17 passing before/after the
reader change. These checks do not establish completed Q2–Q6 market results.

## Full-market capacity gate before a long continuation

Four workers are the small-sample throughput choice, not a measured full-market
memory guarantee. `DenseCounts` retains nonzero per-stock cell/year event counts
across stocks and builds an additional index during finalization; four full-market
groups can therefore require more memory than the eight-stock probe. The retained
H1 conditions receipt reports a 4,798,099,456-byte process-lifetime peak, which
cannot identify a particular group's requirement or be multiplied as an isolated
group measurement.

The retained H1 phase walls are 49,308.918 seconds conditions, 2,518.915 seconds Q4
and 7,435.371 seconds followup, all from `40bf6fd`. Conditions account for 83.2%
of that measured total; prioritizing it is supported, while followup remains a
material serial portion. These are whole-phase observations, not a prediction of
the remaining families' duration.

After the timeout-receipt follow-up PR #82 merges, start the existing run with four workers and an explicit
six-hour timeout (`--timeout-seconds 21600`), scoped to B2 conditions. This is useful
continuation work: completed projections/groups remain checkpoints in the same
run. Preserve that invocation's logs and `job-memory.json`, including on timeout
or worker failure. If it completes no full-market groups, capacity remains
unmeasured; do not describe the cache-preparation peak as a group peak.

Before using the ten-day long-run timeout, inspect complete-group timings,
per-worker measurements and the aggregate Job peak. A memory-limit failure keeps
the Job cap at 8 GiB and requires a smaller parallel configuration or a measured
memory improvement, followed by another bounded capacity check. There is no
single-worker full-run fallback. A timed-out invocation also leaves the run paused
with all published checkpoints retained. The hold remains in place throughout.

The timeout/receipt cleanup change passed all 68 launcher/continuation tests in
47.07 seconds, including a timeout that records the Job peak and a receipt-write
failure that still terminates and closes the owned Job.
