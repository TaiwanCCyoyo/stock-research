# O2b-B1 candidate-content publication handoff

Status: local implementation for Astra outcome review. This package creates
candidate evidence only. Acceptance receipts, effective cohorts, a v3 runner/CLI,
market preparation, deployment and scheduler changes are outside this package.
No push or new PR is authorized for this turn.

## Decision and remaining specification

Parent recorded the owner's decision in the 2026-10-28 delegation: the full list,
values and cohort-start proposal must be immutable before 09:00; completion proof
may follow by a few seconds. This resolves which content event must precede the
deadline. It does not authorize production work or make any candidate accepted.
The original message's exact wall timestamp was not supplied; 2026-10-28 is the
date this implementation decision was recorded, not an invented original time.

The finite grace value **G remains undecided**, as does the event G bounds. A
latest time to start writing a receipt differs from its durable completion time;
a pre-write clock check cannot prove the latter. Neither five nor ten seconds is
an approved value. B1 publishes no receipt, so it does not need or choose G.
B2 still needs the finite rule, receipt/reader/cohort-chain integration and the
remaining PR103 T05/T10–T18 acceptance work.

The original [PR103 proposal](data-contract.md),
[matrix](acceptance-matrix.md), [design handoff](implementation-handoff.md), and
[PR102 failure record](https://github.com/TaiwanCCyoyo/stock-research/pull/102#issuecomment-6435304921)
remain historical evidence, unchanged. The v1 serialization/publication crossing
remains failed/unmet under its original classification. New candidate-state
tests do not reinterpret that legacy failure as a repaired or accepted sample.

## Local ownership

Branch: `codex/forward-content-publication`, initially from fetched main
`346156abc534eae591a5bcc67f6f8cc29490352f`.
Worktree: `D:/Project/stock-research/.worktrees/forward-content-publication`.
The older PR102 checkout is retained, clean at its delivered head, for its
existing handoff reference; it is not reused for B1. Other sessions' resources
are unowned and preserved. The worktree inventory is not proof that all concurrent
work is conflict-free. No submodule or producer/shared-data root is initialized,
copied, linked or read by this package.

The exclusive source paths are the new
`research_core/momentum_forward_publication_v3.py`,
`scripts/tests/test_momentum_forward_publication_v3.py` and this file. Parent later
released the shared program/CI writer slot after PR115 became immutable. The
previously staged registration below is now integrated locally; no push or PR
publication is authorized. Core and new-suite bytes remain exactly those reviewed
at `35ce350e4597ad00de8905c186009e9c4e028f49`.

## Public interface and schemas

`CandidateIdentity` is immutable and binds canonical target day, 32-lowercase-hex
attempt/bundle IDs, generation, generation-as-of and a 40-lowercase-hex code commit.
`CohortProposal` is immutable: `first` proposes target day through twelve calendar
months minus one day with null receipt references; `continue` provides that same
interval and explicit anchor/predecessor receipt SHA-256 references. References
are opaque candidate claims here; B1 does not validate an accepted receipt chain.

| API                                                        | Result and authority                                                                                                                     |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `serialize_candidate(frame, *, identity, cohort_proposal)` | Immutable `SerializedCandidate` bytes and identities for exactly three covered members. No root or clock access.                         |
| `publish_candidate(root, candidate)`                       | Explicit root only; `PublishedCandidate` after every member write/flush/fsync/close and native no-replace directory publication returns. |
| `publish_and_observe(root, candidate, *, clock)`           | In-memory `PublicationObservation`, sampled immediately after publication returns; no receipt or accepted result is written.             |
| `inspect_candidate(root, *, target_day, bundle_id)`        | `CandidateInspection` with verified integrity/identity/proposal diagnostics. No time observation, accepted day or effective cohort.      |

The caller supplies an already complete in-memory frame. B1 checks a nonempty
frame, unique string columns, unique canonical `security_id` values, exact `t0`,
and any existing generation/code columns. It cannot certify a market universe's
completeness without the separately scoped preparation/admission layer. It copies
the frame, drops provisional `recorded_late` and pre-serialization legacy time
columns, and clears copied dataframe attributes. It rejects acceptance-evidence
columns. It never changes the source dataframe in place or inserts an accepted
flag. Parquet serialization uses PyArrow/ZSTD without a dataframe index.

Under the explicit root, publication writes only:

```text
publication-v3/bundles/<target_day>/<bundle_id>/
  day.parquet
  cohort-proposal.json
  manifest.json
```

`artifact_store.publish_new_directory` owns unique sibling staging, file fsync and
native no-replace publication. Errors preserve staging and existing bytes; no
merge, overwrite, cleanup or check-then-rename replacement is introduced. Explicit
safe paths reject traversal and NTFS reparse ancestors. The guarantees cover
process crashes, not power loss or directory-metadata durability.

The manifest schema is `momentum-forward-publication-manifest.v3`, protocol
`candidate-content-sealing.v3`. Its exact fields are `schema`, `protocol`,
`identity`, `required_members`, `payloads`, `row_count` and `security_ids`.
`required_members` fixes the three ordered names. `payloads` binds the other two
members' exact lengths and SHA-256; the manifest's own byte digest is separately
retained in the immutable result, avoiding a circular self-hash. The proposal
schema is `momentum-forward-cohort-proposal.v3` with exact `schema`, `identity`
and `proposal` fields. It repeats the identity to detect a one-member manifest
identity change. JSON must be canonical; duplicate keys, nonfinite constants,
missing/unknown fields, invalid identities/intervals and mismatched rows/digests
are rejected. Member-size caps bound inspection: day 256 MiB, proposal 64 KiB,
manifest 1 MiB. These are resource limits, not research eligibility rules.

Integrity is not authenticity or acceptance. Inspection computes the manifest's
current digest; without a future independently pinned valid receipt it cannot
prove the original bytes against a coherent external rewrite of every member.
It does not read mtime as timing evidence or reconstruct an earlier observation.

## Clock and invocation boundary

`ClockSample(wall_time, monotonic_ns, source, trusted, healthy)` has no trusted
defaults. The caller must provide a fresh aware wall sample plus explicit trust
source/health and monotonic order. B1 checks those claims; it does not certify NTP,
the OS clock, or an arbitrary provider's honesty. UTC/Taipei equivalent instants
compare identically without rounding. A pre-publication sample and the immediate
post-return sample must use the same source, strictly increasing monotonic order,
and nondecreasing wall time. Invalid/missing/naive/untrusted/unhealthy samples,
visible wall rollback or contradictory order yield `unknown`, never early evidence.

The content states are `observed_before_deadline`, `observed_late`, `unknown`,
and `ineligible`. They are not journal `on_time` outcomes. V1's public
`freeze_deadline` and `is_on_time` preserve strict `< D`, generation-as-of equality
and `FIRST_CONFIRMATORY_DAY`. A stale or pre-mission candidate is ineligible.
A post-return observation at D is late even if content completed earlier.

Observations exist only in the return object of that live call. No observation,
receipt or effective cohort is persisted. Advancing the clock after an early
observation changes neither its original snapshot nor content identity/bytes.
After child death before observation, or after an early observation but before a
receipt, public PR102 `Attempt`/`recover` yields interrupted/unknown/null finish;
inspection finds only a candidate. It cannot regenerate timing proof.

## Synthetic verification and review gates

The new suite covers serialization and each member's write/flush/fsync/close,
native directory publication, D−1µs/D/D+1µs in UTC/Taipei, invalid clocks,
eligibility, member/schema tampering, traversal/reparse paths, occupied targets,
two real self-created writers and both journal-linked child-death points. All
roots, legacy bytes, junction targets and child processes belong to the tests.
The suite creates no receipt and no accepted cohort. Related artifact-store,
v1/v2 suites are regression checks; their original semantics remain unchanged.
Normal hooks remain enabled. This is not market execution or a production probe.

Validation commands (record actual results at handback):

```powershell
uv run --group dev python -m pytest scripts/tests/test_momentum_forward_publication_v3.py scripts/tests/test_artifact_store.py scripts/tests/test_momentum_forward_v1.py scripts/tests/test_momentum_forward_attempts_v2.py scripts/tests/test_momentum_forward_run_v2.py
```

No `prepare_candidate`, v3 runner/CLI, `publish_receipt`, `read_accepted_day`,
accepted cohort chain or production recovery command is added. B1 does not call
v1 `record_day` or v2 `run` as a publication primitive. Any required frozen-code
change, shared-publication primitive defect, accepted-sample conversion before
G/event selection, or need for production roots/cohort mutation stops at parent.
Migration, deployment, scheduler switching and the first future accepted day
each retain their own gates after eventual review/merge.

## Shared-file integration (writer slot released)

The integration rechecked fetched main `346156ab`; the unpublished task branch
was already current. At that check PR115 remained open/draft at `7a7b58db`, so no
unmerged PR115 content was imported or edited. Existing S7/E1 domain entries and
their test unions are preserved. Recheck main before final handback and normally
sync if PR115 has merged. Publication of this package still requires its own gate.

The following asset row is added to `docs/en/research-program.md`:

```markdown
| `momentum-forward-publication.v3` | [Candidate-content handoff](../../tasks/20261027-forward-publication-deadline/content-publication-handoff.md): immutable three-member candidate bundles and ephemeral live post-publication observations; no receipts/accepted cohort; finite G/event remains pending | `research_core.momentum_forward_publication_v3`: serialize_candidate / publish_candidate / publish_and_observe / inspect_candidate; explicit root, synthetic verification only, production pending |
```

Registered in `scripts/ci_test_domains.json` without changing full-path fallbacks:

```json
{
    "momentum_forward_v3": {
        "paths": [
            "research_core/momentum_forward_publication_v3.py",
            "tasks/20261027-forward-publication-deadline/content-publication-handoff.md"
        ],
        "tests": ["scripts/tests/test_momentum_forward_publication_v3.py"]
    }
}
```

The existing `momentum_only`, `research_data` and `momentum_forward_v2` consumer
sets each gain `momentum_forward_v3`, preserving their other consumers. The new
test is in sorted `reviewed_tests`; test discovery remains in `scripts/tests`.
The v1/public predicate and v2/public journal dependencies propagate to the new
suite. `artifact_*`, JSON-integrity and unknown-forward full fallback remain intact.

Existing `scripts/tests/test_ci_scope.py` now has 34 additional A/M cases: exact
selection for source/test/handoff, nine v1/v2/shared/S7-oracle upstream paths, and
five shared/unknown full-fallback paths. Expected domain and test unions stay
exact; no equality assertion was weakened to containment. The existing E1/S7
selection tests continue to pass, including E1 membership on momentum/count-cube
changes and S7 membership on the public technical oracle. The five earlier v2
selection failures are fixed by registration; their frozen test file is unchanged.

## Author verification before registration (retained)

At base main `346156ab`, the new suite passed **99 cases** in 25.85 s.
The combined new/artifact-store/v1/v2 run then reported **177 passed, 5 failed**
in 31.35 s. All five failures are existing v2 CI-selector assertions: the new
test was not yet in the writer-locked reviewed manifest, so the unchanged selector
correctly switched to full fallback. This was a pending shared-integration gate,
not a claim that the whole regression run passed. No v1/v2 assertion was changed.

The actual unregistered three-path selector returned `full=true`, 324 test files,
with explicit inventory-mismatch/unmapped-source reasons. That full suite was not
executed. Shared program/manifest/selector and all original PR103/v1/v2 files were
verified unchanged. After parent releases the slot, integrate against current main
and recheck the five pending selection assertions plus existing selector contracts.

After explicit NaT type narrowing and bounded child handshake/cleanup adjustments,
the new suite was rerun: **99 passed** in 7.69 s. Shared-registration failures
remained pending at that checkpoint; that rerun did not claim they were repaired.

## Integrated verification

- Selector plus complete v2-run suite: **328 passed** in 50.96 s. This includes
  all five formerly failing cases and the 34 new mapping/fallback cases.
- New candidate, artifact-store, v1 and v2-attempt suites: **160 passed** in
  10.49 s. All tests use synthetic roots; no market research was run.
- Actual tracked integration diff: `full=false`, 22 selected test files, domains
  `ci`, `hooks`, `momentum_forward_v3`, `producer_link`, `prose`. The committed-head
  plan is generated again at handback; its diagnostics stay local under `.tmp/`.
- Core and new-suite files compare byte-identically to the reviewed core commit.
  Original PR103/v1/v2 files and publication primitives remain unchanged. Normal
  commit hooks are retained; final commit/results are supplied in the handback.

Finite G/the exact receipt event, B2 acceptance/reader/cohort-chain work, outcome
review and publication approval remain outstanding. Integration does not choose
G, add receipts, turn any candidate into an accepted sample or authorize deployment.
