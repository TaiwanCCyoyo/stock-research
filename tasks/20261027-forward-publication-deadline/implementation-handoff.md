# O2b-A implementation handoff

Status: **documentation design only; no runtime deadline repair, deployment or
research execution**. Read the [data contract](data-contract.md) and
[acceptance matrix](acceptance-matrix.md) together. O2b-B must not begin before
parent semantic review; this handoff does not authorize a production API/CLI.

## Source and ownership

The assigned specification is `research-wave2-plan.md`, common contract and O2b-A,
provided by parent on 2026-10-27. Repository baseline and fetched `origin/main`:
`71acd4e70f9c0d227eeb6f1941caa4bb6dacb2ce` (PR102). Remote main/open PRs were
verified before work; no open PR or remote branch other than main existed then.

O2b-A author checkout:
`D:/Project/stock-research/.worktrees/forward-publication-contract`, branch
`codex/forward-publication-contract`, created from the fetched SHA above.
This session owns this one task worktree (budget: one of five). The registered
worktree/branch inventory and exact task-path checks found no existing checkout
for this task; they do not establish ownership or inactivity of other sessions.

This package owns only these three new documents under
`tasks/20261027-forward-publication-deadline/`. It changes no legacy contract,
mission, failure evidence, module, schema, roadmap, asset index, CI, scheduler or
production root. No studycard is added for this operational design.

Authoritative existing references:

- [PR102 journal contract](../20261027-forward-attempt-recovery/data-contract.md)
  and [handoff](../20261027-forward-attempt-recovery/codex-handoff.md).
- [Original Astra failure evidence](https://github.com/TaiwanCCyoyo/stock-research/pull/102#issuecomment-6435304921).
- [Frozen v1 public API](../../research_core/momentum_forward_v1.py),
  [public v2 journal API](../../research_core/momentum_forward_attempts_v2.py),
  [v2 orchestration](../../research_core/momentum_forward_run_v2.py), and
  [shared publication primitives](../../research_core/artifact_store.py).
- [Git/review boundaries](../../docs/en/git-workflow.md) and
  [production/data safeguards](../../docs/en/stock-agent-operations.md).

PR102 proved invocation traceability and crash recovery with synthetic fixtures.
Its serialization/publication crossing remains **failed/unmet**. V1's
`recorded_at_utc`/cohort `first_frozen_at_utc` precede serialization; v2's
`finished_at_utc` precedes terminal/ledger persistence. None independently proves
that complete publication finished before 09:00. This package preserves that
evidence and proposes a new protocol rather than changing its interpretation.

## Decision presented for semantic review

| Event                                                        | Proposed content-sealing protocol                                          | Stronger original requirement, if owner intends it             |
| ------------------------------------------------------------ | -------------------------------------------------------------------------- | -------------------------------------------------------------- |
| B complete and observed before D; receipt readable after D   | Accept only after receipt validation; claim only pre-D content publication | Unmet if receipt readability/cohort effect must also precede D |
| Candidate complete but writer dies before receipt durability | Unknown; no cohort and no reconstructed receipt                            | Also not proven                                                |
| Receipt valid/durable, writer dies before terminal/ledger    | Content independently accepted; attempt may remain interrupted/unknown     | Does not prove receipt was readable before D                   |

Astra should assess the exact reviewed SHA for any remaining “mark success, then
finish writing” window, including all covered members, receipt ordering, clock
trust, cohort predecessor validation and recovery. The independent receipt closes
that window only for the explicitly chosen **covered content**. It does not prove
its own pre-D durability. Parent must compare this narrower claim with the
owner's already authorized meaning; where they differ, record the concrete owner
decision before implementation. No semantic choice is claimed settled here.

## O2b-B boundary after review

Expected exclusive implementation paths are
`research_core/momentum_forward_publication_v3.py`,
`research_core/momentum_forward_run_v3.py`,
`scripts/record_momentum_forward_day_v3.py`, corresponding
`scripts/tests/test_momentum_forward_*_v3.py`, and this task's handoff.
Parent serializes any CI-domain and program-index edits with other packages.
Do not modify frozen v1/v2, import private helpers, copy the whole old runner,
monkeypatch production, or reuse v1 `record_day` as the publication primitive.

Implement the versioned prepare/serialize/publish/observe/receipt/reader seams
in the contract. Fix public argument/result types and manual/scheduled duplicate
return/exception behavior before writing assertions; do not select semantics to
make a failing case pass. Reuse public v1 computations and artifact-store/journal
primitives with explicit paths. Journal and publication receipt remain separate
authorities. No accepted flag inside pre-publication bytes may serve as evidence.

O2b-B first uses in-memory fixtures, self-created temporary roots and bounded
child processes only. The matrix is the acceptance plan, not evidence that its
cases have run. Preserve the original PR102 failing test/log and add new v3
assertions for the same failure intent. Legacy byte preservation and v1/v2
regressions accompany the new protocol checks; no real-root smoke test.

## Remaining gates

1. **Semantic gate:** parent/Astra review of this exact design/head; explicit
   owner decision if pre-D content publication does not satisfy the authorized
   deadline meaning. The chosen timed event and observation boundary must be
   documented before O2b-B. Clock trust assumptions must be reviewable.
2. **Implementation gate:** independently reviewed v3 code, all bounded matrix
   assertions and normal hooks/CI, with exact reviewed SHA and evidence. This
   documentation PR cannot satisfy that gate.
3. **Migration/owner gate:** determine separately whether the approved root
   already has a cohort, preserve its start and historical bytes, and approve any
   migration. Never silently start a second cohort or move the original sample.
4. **Deployment gate:** separate explicit authorization for the exact checkout,
   root, CLI/default/task switch and writer coordination. V1/v2 ignore v3 locks;
   all scheduled/manual writers must be prevented from new starts and existing
   writers must exit naturally. Stable locks are not removed to force progress.
5. **Data/compute gate:** production inputs, outcomes, holdout, generation updates,
   downloads and actual research/admission remain separately authorized. No
   deployment, scheduler action, production probe, F1 activation or first future
   on-time day is asserted by this package.

## Documentation verification and retained checkout

The author checks exact three-file scope, UTF-8/whitespace, local relative links,
cross-document invariants and the normal commit hooks. Hosted CI is reported
separately for the delivered PR/head. No v3 synthetic execution or market test
is claimed. The final author handback records the checkout, commit, PR and actual
check results; parent arranges the independent Astra review.

The task checkout is retained for its open draft PR and subsequent semantic
review. Other worktrees, the dirty primary submodule and untracked forward-log
remain untouched and unowned. Inventory is not evidence that unknown sessions
are inactive or eligible for cleanup.
