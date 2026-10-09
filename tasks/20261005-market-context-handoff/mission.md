# Research handoff and 0050 context v1

Recorded 2026-10-05 before state generation. The owner authorized fixing artifact
discoverability and producing reusable 0050 context before receiving a revised
goal. This does not resume strategy research, automation or confirmation/holdout.

## Inputs and period

Use only the already retained `catalog-v2` manifest from
`20261004-sector-wave-full-history-preview`, byte SHA-256
`c7848ae7ad177770babfda774e07923f995ba2cb3fa4a83d77d02f77a0dfe140`.
Its 0050 series descriptor has byte SHA-256
`ec81dfea86cd32379547f49abc5c216eae7ae77d54be424b575b4d64112ed6b4`;
calendar byte SHA-256 is
`bd2861014f9226196a7b9dc6aa9cc04531f07205dd06090ebb8716deee09a236`.
Copy exact consumed bytes; verify hashes and symbol/calendar identities.
Window: 2010-01-04..2026-10-02, 4,105 shared calendar slots. This covers the
existing local benchmark series, not newly acquired history or unseen samples.
Years before 2010 and after the snapshot are not available here. Prior atlas
2019-01-02..2026-08-14 definitions/results remain unchanged.

The adjusted close is the source's permanent non-pure-cash reference-factor,
four-decimal price series, not total return or account profit. Preserve raw
prices, Source, numeric flags, action barriers and coverage caveats. Null,
nonpositive, nonfinite or numerically flagged observations become unusable for
state windows; never fill them. The input snapshot was captured retrospectively;
historical publication times remain unknown. Past-only means computation uses
no later observations, conditional on this source vintage, not certified PIT.

## One fixed provisional definition

Definition `benchmark-context.rules.v1`, selected for an interpretable month-scale
first descriptor, not optimized against this price series or stock outcomes.
There is no parameter sweep, performance test, stock-label join or best-rule search.
An interval of 20 shared calendar steps uses 21 close observations.

- Past-only row at t uses [t-20, t], all 21 points usable. Information cutoff is t.
- Retrospective row at t uses [t-10, t+10], all 21 points usable. Information cutoff
  is t+10; endpoints without enough history/future are unknown. This centered
  descriptor is an exploratory hindsight label, not a native catalog wave or
  validated lifecycle segmentation. It cannot be consumed as a trading feature.
- `window_return = last / first - 1`; `window_range = max / min - 1`, fractions.
- `up` if window_return >= 0.03; `down` if window_return <= -0.03.
- Otherwise `consolidation` if window_range <= 0.08; otherwise `mixed`.
  Unknown windows retain a specific reason (warmup, future unavailable, unusable
  observations). Mixed is not automatically sideways. No smoothing/debouncing.
- State transitions are interpreted in observation-date order separately per layer.
  On the first up observation after a known non-up state, emit `resumption` only
  if an earlier up and then consolidation occurred since the last down/unknown;
  otherwise emit `launch`. Subsequent up days emit no event. A first known up
  immediately after unknown emits no event (history insufficient), but establishes
  up history for later transitions. Down or unknown resets that history. Mixed
  does not itself establish consolidation. Events are descriptive candidates,
  not instructions, confirmed troughs or stock opportunities.

Each row declares security_id, asof_date, layer, state, event, information_cutoff,
missing_reason, window_return, window_range and window start/end dates. Retrospective
rows missing future have no available cutoff. A whole-dataset summary is explicitly
retrospective even when counting past-only rows. New data may change centered tail
labels in a new dataset; it cannot revise saved past-only rows under the same inputs.

## Delivery, verification and stop

Create one immutable `market-context-v1` generation under this task. Retain small
input and output files in a Git-portable evidence package, with source manifest,
formula/parameters, producer hashes, runtime, per-file SHA-256 and counts. Reader
checks all declared identities/hashes and rejects an unavailable or malformed
artifact, not returning zero/empty success. Exact input copies permit recalculation
without the source worktree or price pipeline. No third-party source downloads.

Publish saved atlas aggregate evidence from its existing fixed manifest, retaining
all 7,144 comparisons, negatives, unknowns and definitions. Copying is not a new
experiment. Bulk per-stock observations stay at their existing source and verified
same-drive duplicate, explicitly not available from Git alone or an offsite backup.
Do not rewrite historical packets or silently alias these two datasets.

Synthetic tests precede the market build: threshold boundaries, up/flat/down/mixed,
launch/resumption/reset, missing windows, centered tail, prefix invariance and scale
invariance; package tests cover hashes, paths, identity and overwrite refusal.
One bounded build, at most two diagnosed implementation retries with new run IDs,
maximum 300 seconds per attempt. Preserve partial output; no result-driven tuning.
Then independently read/verify the package and obtain a website-session read-only
smoke receipt. A successful read does not claim a page is implemented.

Finish after publication, documentation and consumer checks. Return an updated
goal proposal to the owner; do not activate it or evaluate a portfolio.
