# Forward content publication protocol v3 (design only)

O2b-A specifies **candidate content sealed before the deadline, followed by an
independent acceptance receipt**. No v3 runtime exists in this change. The
[acceptance matrix](acceptance-matrix.md) defines future synthetic checks; the
[implementation handoff](implementation-handoff.md) records the review and
authorization gates. This is an operational protocol, not a new study.

## Meaning that remains subject to owner review

Let `D = momentum_forward_v1.freeze_deadline(target_day)`: 09:00 Asia/Taipei on
the next weekday under the existing definition. The proposed claim is only:
**the complete covered content was immutably published, and its completion was
observed by the live writer at a trustworthy time strictly before D**.

The receipt, attempt terminal, ledger projection and reader availability can
follow D. A reader accepts nothing until a valid receipt is present. Thus this
protocol does **not** prove that every file, an externally readable acceptance
receipt, or an effective cohort existed before 09:00.

Parent/Astra must decide whether that claim satisfies the owner's original
meaning of complete publication. If the owner requires receipt readability or
cohort effectiveness before D, the delayed-receipt case is **unmet**, even when
the content-sealing predicate passes. Sol does not resolve this choice. O2b-B
remains blocked until semantic review and any required owner decision are
recorded. Repeatedly adding a timestamp after writing the previous proof cannot
prove the proof's own completion; a stronger protocol must first identify its
timed event and observation boundary.

## Covered content and compatibility

The deadline-covered set is exactly one immutable bundle containing:

1. `day.parquet`: the complete day's values, qualifications and signal states.
2. `cohort-proposal.json`: the proposed first-cohort start/end, or the identity
   of the already accepted cohort being continued. It is always present.
3. `manifest.json`: the version, target day, attempt/bundle identities, generation
   and code identity, exact member list, byte lengths and SHA-256 of the other
   two members. The bundle identity also binds the manifest's exact bytes.

No required member may be deferred to a later publication. No extra member is
silently accepted. Hashes identify bytes; they do not establish time. The receipt
and journal are outside this covered set, explicitly rather than implicitly.

Reuse public `momentum_forward_v1.day_frame` for values and
`freeze_deadline`/`is_on_time` for the existing deadline and eligibility predicates.
Generation-as-of equality, mission merge eligibility, `FIRST_CONFIRMATORY_DAY =
2026-10-22`, qualifications, atoms, calendars and the 12-month interval remain
unchanged. The first accepted day starts the interval; its end is start plus
12 calendar months minus one day. No backfill or retry moves that anchor.

V3 uses a new payload envelope: any `recorded_late` returned during preparation
is provisional and must not be serialized as authoritative `False` in v3.
Legacy `recorded_at_utc`/`first_frozen_at_utc` are not v3 publication evidence.
V3 acceptance is derived from the receipt; no accepted flag is set in the bundle
before publication or patched into it afterwards. The v1/v2 schemas and all
existing bytes remain untouched. Do not call v1 `record_day` as the v3 publication
primitive: it already writes the legacy day and cohort before returning.

## Proposed persistence layout

All paths are below an explicitly supplied root; there is no default production
root. These are future v3 paths, not files created by this documentation change.

| Path below `publication-v3/`                                              | Responsibility and authority                                                                                       |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `bundles/<day>/.staging-<bundle_id>/`                                     | Writer-owned incomplete content; never accepted.                                                                   |
| `bundles/<day>/<bundle_id>/`                                              | Complete no-replace candidate directory; existence alone gives no timing/cohort authority.                         |
| `receipts/<day>.json`                                                     | One immutable no-replace acceptance receipt for that day, binding the exact bundle.                                |
| `.staging-receipt-<attempt_id>-<uuid>`                                    | Incomplete receipt outside the candidate bundle; never accepted.                                                   |
| `.publication-v3-writer.lock`                                             | Stable local root writer lock, held through reconciliation, publication, receipt and terminal/projection handling. |
| `attempt-journal-v2/<attempt_id>/{started.json,owner.lock,terminal.json}` | PR102 public journal API reused with the **v3 namespace as its root**; attempt authority only.                     |
| `attempts-v2.jsonl`, `.attempts-v2-append.lock`                           | Journal projection and append lock within the v3 namespace; never the legacy root ledger.                          |

Bundle staging/final directories are siblings on one filesystem. Use public
`artifact_store.publish_new_directory`/`publish_noreplace` and safe paths instead
of a new check-then-replace implementation. All member writes, flushes, fsyncs,
closes and the native no-replace directory publication must return successfully
before the completion observation. Receipt publication likewise writes complete
bytes, flushes, fsyncs, closes and publishes without replacement. Unsupported
filesystem semantics or errors fail closed; retain staging and prior bytes.
These are process-crash guarantees, not filesystem/hardware power-loss or
directory-metadata durability claims.

The receipt has a distinct schema `momentum-forward-publication-receipt.v3` and
protocol `candidate-content-sealing.v3`. Required fields bind `target_day`,
`attempt_id`, `bundle_id`, manifest byte digest, exact member identities,
generation/as-of, code commit, `deadline_utc`, trusted clock evidence,
`publication_observed_at_utc`, and the cohort proposal. A receipt also identifies
its accepted predecessor/cohort anchor, or explicitly proposes the first anchor.
Strict parsing rejects missing/duplicate/unknown contract fields, invalid dates,
unsupported versions, invalid identities and conflicting content. There is no
receipt for a late, unknown, incomplete or ineligible publication.

There is no second authoritative `cohort.json` to publish later. The new reader
derives the cohort from the first valid receipt whose proposal starts it; later
receipts must reference that same anchor and interval. The single root writer
validates the existing chain before publishing another receipt. A conflicting
start, missing predecessor or fork stops automatic acceptance; it never selects
an arbitrary winner or silently starts another sample. A cached view, if added
later, is non-authoritative and must be reproducible from valid receipts.

## Public API seams proposed for O2b-B

Names below describe a future versioned API, not currently callable functions.
Each input root, generation, target day, code identity and clock is explicit.

| Seam                                         | Result and restriction                                                                                                                                                    |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `prepare_candidate(...)`                     | Uses public v1 day computation and fixed eligibility; returns a candidate frame and cohort proposal, with no writes or acceptance.                                        |
| `serialize_candidate(...)`                   | Produces all covered bytes and their identities; no timing verdict or cohort side effect.                                                                                 |
| `publish_candidate(...)`                     | Stages/fsyncs/closes all members and publishes the entire immutable directory; returns its identity only after all operations complete.                                   |
| `observe_publication(...)`                   | Immediately samples the live invocation's trusted aware wall clock after publication returns; returns an in-memory observation, never a receipt reconstructed from files. |
| `publish_receipt(...)`                       | Validates eligibility, identity, clock and strict deadline; only the same live invocation may persist its acceptance receipt.                                             |
| `read_accepted_day(...)`, `read_cohort(...)` | Verify bundle plus receipt and cohort chain; return accepted views only, with candidate/late/unknown diagnostics separate.                                                |
| `reconcile_publications(...)`                | Revalidates and replays already durable receipts; never manufactures a missing receipt or original observation.                                                           |

`momentum_forward_run_v3` would own sequencing and lazy dependencies. Reuse public
PR102 `Attempt`, `root_lock`, `recover` and `read_attempts` where their contracts
fit; do not import private helpers or call v2 `run` to perform publication.
`Attempt.finish` remains responsible for terminal persistence and projection.
Journal recovery without a terminal still yields `interrupted`, completion
`unknown`, `finished_at_utc: null`; a separate valid publication receipt can
establish content acceptance without rewriting that historical attempt outcome.
Conversely an `on_time` terminal cannot replace a missing publication receipt.

## Clocks and event order

All accepted wall-clock samples are timezone-aware and normalized to UTC while
comparison uses the exact instant returned by v1 `freeze_deadline`. Keep full
available precision; do not round 09:00 backwards. The clock provider must state
its trust source/health. Missing trust, naive/missing/invalid samples, sampled
wall-clock rollback or incompatible monotonic ordering yield unknown/failed.
A monotonic clock may detect ordering anomalies; it cannot establish civil time
or certify an untrusted wall clock. No file mtime or restart clock is evidence.

| Field/event                                                   | When sampled; use                                                                                                                                                              |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `attempted_at_utc`                                            | PR102 durable start, before lazy dependencies; invocation identity, not publication.                                                                                           |
| `prepared_at_utc`, `serialized_at_utc` (optional diagnostics) | After each respective stage; never acceptance authority.                                                                                                                       |
| `publication_observed_at_utc`                                 | First trusted live sample after **all** covered publication operations return; an upper bound on content completion, not its exact instant. Must be strictly `< deadline_utc`. |
| `receipt_prepared_at_utc` (optional)                          | Before receipt persistence; cannot claim receipt durability/readability completion.                                                                                            |
| Receipt publication returns                                   | Reader may subsequently see a valid receipt; no self-certifying receipt-completion timestamp is claimed.                                                                       |
| `finished_at_utc`                                             | Entry into attempt finalization, before terminal/ledger persistence; retains PR102 meaning.                                                                                    |
| Terminal/ledger writes return                                 | Normal invocation return requires both; neither changes the content observation or original cohort anchor.                                                                     |
| `recovered_at_utc`                                            | Actual reconciliation time; never substituted for original completion.                                                                                                         |

The required order is prepare → serialize → covered write/flush/fsync/close →
no-replace bundle publication returns → live observation → receipt construction
and publication → reader validation. Terminal/ledger persistence follows the
attempt's finalization path. If publication completed before D but observation
is at or after D, classify late conservatively. Publication errors or lost clock
evidence remain unknown/failed. Generation or preregistration ineligibility also
prevents acceptance, even with an early observation.

## Authority, crashes and concurrency

| State                                                    | Reader/cohort authority; next permitted action                                                                                                  |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Durable start / preparing / serialized / staged          | None; live invocation may continue, verified abandoned journal may recover as interrupted.                                                      |
| Published candidate, no valid receipt                    | None; live invocation may observe and publish a receipt only while its trusted evidence is still available. After death, completion is unknown. |
| Live observation late, invalid, absent or ineligible     | None; record late/refused/failed with explicit reason; preserve candidate.                                                                      |
| Valid durable receipt + matching complete bundle         | Accepted content under this proposed protocol; first qualifying receipt supplies cohort anchor. Ledger projection may remain pending.           |
| Valid receipt, terminal/ledger missing                   | Content remains independently verifiable; reconcile journal under its own ownership rules, without inventing attempt success.                   |
| Corrupt/partial receipt, conflicting bundle/chain/ledger | Fail closed and preserve bytes; manual review required, no truncation or replacement.                                                           |

Hard termination at any stage cannot turn staged bytes or a candidate into
success. A complete candidate with an undurable receipt remains completion
unknown, including a crash after an in-memory early observation. Only a complete
durable valid receipt may be replayed. Recovery obtains the original cooperating
local owner's released OS lock; unknown/foreign owner, missing lock, lock failure
or active owner stays pending. Age/PID alone is never permission to recover.

The root lock serializes all cooperating v3 writers through acceptance and
journal handling. Same-day duplicate invocations return the existing verified
publication without creating a second receipt or cohort; manual versus scheduled
return/exception details must be fixed in O2b-B before testing. Native no-replace
still protects each final path when locks contend. Do not delete stable locks,
overwrite conflicts, or infer exactly-once persistence from a partial JSONL.

V1/v2 writers do not honor the v3 root lock. Separate deployment authorization
must prevent all legacy scheduled/manual writers from starting and establish
natural completion of existing writers before any switch. No lock here supplies
that coordination automatically.

Existing v1/v2 day, cohort and journal bytes are neither reclassified nor migrated.
An existing production cohort requires an explicit owner migration decision that
preserves its original research start; no second confirmatory cohort or silent
delay is allowed. No production inspection, deployment, scheduler/default switch,
real data read, outcome access, download or research computation is authorized by
this design. See the [handoff gates](implementation-handoff.md#remaining-gates).
