# Pattern-scan execution and retention v3

Owner instruction: 2026-10-16, following Claude's 2026-10-15 architecture reply.
This addendum supersedes the earlier input-sealing, intermediate-publication and
30/7-day recovery proposals for **new PR17 execution**. Historical missions,
receipts and published artifacts retain their original interpretation.

## Data and execution

Inherited completed work is not queued again: the six-stock 1/2/4-worker parity
profile and the four-stock storage run completed all 276 group/horizons. The
continuation preserved the first 125 checkpoint receipts and added 151; its
327,647,953-byte output is a representative observation, not a full-market result.
These retain source commit `25882a6` and input `d78927d7`, under primary
`.tmp/pattern-scan-execution/profile-2010-20261015-live-v2c` and
`storage-2010-20261015-live-v2c`. Their global pool has four stocks, so its bound
events cannot substitute for events using the full-market cross-sectional pool.
The dirty historical source has no retained diff sufficient to certify adoption
of its numerical stock payload into the new source identity.

- Read the canonical producer through `pattern_scan_live_inputs_v2`; keep the
  approved official-source policy, cutoff 2026-10-12 and 4,110-session calendar.
  Do not switch to the maintained adjusted-daily reader until its `as_of=cutoff`
  interface is merged and all-column, calendar and quality equivalence passes.
  Do not delete PR17's derived price checkpoints before that transition.
- New Parquet writes use ZSTD. Receipts retain actual payload bytes and hashes;
  the final inventory also records row counts and observed codecs. Historical
  SNAPPY files remain readable and unchanged. No compression study is required.
- Existing completed resource observations retain their original source/input
  identities. An explicit `pattern-scan-profile-observation.v3` envelope can use
  their unchanged selected limits as an initial configuration. It proves neither
  current performance nor equivalence of the historical dirty source. New work
  records its own source, input fingerprint, outputs and native Job observations;
  no numerical payload is adopted through this envelope.
- Preparation and independent stock work have separate, identity-bound disk
  admission. Passing either admits only that phase. The new `stock` boundary
  stops before the global barrier. Later global analysis, candidates and Q4–Q6
  need their own evidence; the completed four-stock zero-candidate observation
  does not establish their memory capacity.
- Keep the existing finite limits: at most four stock workers, 6 GiB worker-pool
  budget, 8 GiB owned Job limit, at least 4 GiB host reserve, finite timeouts.
  Disk admission retains at least 32 GiB free-space reserve; disk and RAM are
  separate constraints. Already existing shared bytes are not new allocation.
- For new deferred analysis, Q5/Q6 raw samples are reduced one group/horizon at
  a time using the existing exact accumulators. Observation caches are computed
  once; only completed result tables survive across batches. Raw-array bytes
  exclude Python bookkeeping, quantile temporaries and result frames.

## One retained result, no intermediate publication

New launch requests use `results-only-deferred.v3`. Intermediate prices,
indicators, labels, events, controls and episodes remain owned execution
checkpoints, with explicitly unpublished identities. They are not registered as
new `research_cache/` versions. Old requests still use their historical protocol.

`pattern_scan_retained_v3.collect_retained_files` selects only:

| Retained material                                                     | Purpose                                                                              |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Report and Q1–Q6 summary tables                                       | Conclusions, denominators, unknown/censored counts, annual and exclusion diagnostics |
| Candidate selection record                                            | Fixed development selection and confirmation provenance                              |
| Q4 coverage, at most three examples per group/status                  | Promised missed/lost examples with actual dates and diagnostics                      |
| Narrow Q4 random draws and quotas                                     | Seeds, dates, population, draw counts and quota shortfall audit                      |
| Event, candidate and legacy audit results                             | Independent checks and mismatch evidence                                             |
| Code commit, input fingerprint, execution metadata and result SHA-256 | Traceability and result-integrity verification                                       |

The old promise of arbitrary historical per-event/dashboard drill-down is
retired for this policy: after cleanup, a new grouping or arbitrary detailed
event inspection requires rerunning code on then-available inputs. Q1–Q6 and the
bounded promised audit examples do not require retaining every expanded event,
condition, control or followup row. Input fingerprints cannot recreate deleted
input bytes, prove a calculation correct, or guarantee exact future reproduction.

`pattern_scan_result_lifecycle_v3.record_computed_results` records an unpublished
inventory. Formal destination remains unset until the external `research_data`
catalog/payload contract is settled by the separate task. This PR implements the
mechanism without choosing a competing root or publishing to the legacy cache.

After a caller supplies that destination, `handoff_results` moves retained files
without copying into a sibling staging directory, writes self-contained relative
result references, verifies the staged bundle, and uses `publish_noreplace` before
catalog registration. Immutable journals allow retry after an individual move or
registration interruption. Cross-volume moves are rejected; there is no copy
fallback. The destination therefore needs to share the payload's volume.
Generated snapshots, the result receipt and manifest are fully written, synced
and verified in journal-owned metadata scratch outside the payload tree before
atomic no-replace transfer. A half-written metadata temporary therefore cannot
become a visible destination or enter the final bundle inventory; retry creates
a fresh temporary. Retained partial metadata is retired with the owned run only
after the same publication/cleanup gates pass.

## Immediate retirement, with completion gates

No cleanup occurs while paused, running, incomplete, unverified or unpublished.
PR17's prepared prices also require the separately completed shared-reader
transition: retain `audits/price-reader-equivalence.json` with matching reference
source/input, all 1,943 securities including 0050, 4,110 sessions, fixed cutoff,
all-column/calendar/quality equality and the generation tested. Without this
evidence the retirement gate refuses to delete any run files. This enforces the
owner's explicit instruction to keep PR17's price copy until that transition;
the current change performs no transition or real cleanup.
Cleanup requires the verified final bundle and completed reference handoff, plus
the report and exact ten-event/five-candidate audit packet (54,720 comparison
rows, zero mismatches). Merely computing summary tables does not satisfy this.

After those gates pass, `cleanup_run` immediately removes the explicitly captured
owned checkpoints, derived prices, expanded rows and temporary files. There is no
30-day or 7-day recovery period. It preflights the entire run for aliases and
checks each remaining file against the captured ownership inventory before any
deletion. Unknown or changed files block cleanup. A handoff pointer and cleanup
receipt remain; older sibling runs and shared producer/cache data are untouched.
This addendum does not authorize cleanup of historical runs or shared data.

The producer idle/read-window checks remain in force. Future shared-reader work
will pin one generation per run/stage; a deleted pinned generation must fail,
never silently fall back to the newest one. No permanent full input snapshots or
new generation lease system are introduced here.
