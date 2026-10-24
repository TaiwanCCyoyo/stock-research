# Bounded parallel continuation of PR17 v5

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
  Reduce `pattern:union`, `C-base-all`, `C-base-no-pattern`, `C-52w`, `C-nh`, and
  `C-dip`, each at 126 and 252 sessions. Missing groups refuse the probe; none are
  substituted. Exact equality is required for all 36 final tables and top rows.
- Projections: the first 16 sorted original stocks outside both the paused cache's
  completed list and original reusable B2 event parts, using a separate run-owned cache for each arm. Compare all five
  projection tables per stock exactly, preserving schema, dtypes, nulls and order.
- Record phase wall/CPU time, initializer and first-result latency, in-flight high
  water mark, IPC pickle bytes/time, worker native I/O and memory, and containing
  Job peak committed memory. Time equality comparisons separately after numerical
  and serialization timings; unavailable observations remain explicit.

Acceptance: all equality checks must pass and the Job must stay within its cap.
Choose the fastest conditions configuration above one worker; within five percent
of the fastest, prefer fewer workers. Require at least **1.2x** conditions throughput
versus the one-worker reference before claiming an improvement. Otherwise keep the
full run paused and use measured phase costs to identify the bottleneck. Report
projection speed separately and do not extrapolate a sample speedup into a promised
six-day completion time. No market acceptance rule is adjusted from this probe.
