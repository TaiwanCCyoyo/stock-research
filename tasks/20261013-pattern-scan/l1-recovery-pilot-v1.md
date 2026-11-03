# L1 retained-outcome recovery pilot v1

## Scope fixed on 2026-11-03

The owner approved the recovery design and parallel engineering on 2026-11-03.
This execution is limited to five stocks, saved artifacts, synthetic comparison
integration and resource measurement. It is not a new full-market study, an
unseen validation period or an investment conclusion. No detector, price,
indicator, cooldown, download, frontend route or deployment is rerun or changed.

The recovery implementation is `research_core.pattern_scan_recovery_v1`;
`scripts.run_l1_recovery_pilot` is a thin entry point over
`research_core.pattern_scan_recovery_pilot_v1`. Projection uses the existing
`project_outcomes`, and reductions use existing Q1 and marginal count engines.
The [comparison contract](l1-volume-comparison-contract-v1.md) and its synthetic
fixture provide the separate display integration without a second outcome rule.

## Fixed sources and selection

The retained input root is
`D:/Project/stock-research/.tmp/pattern-scan-execution/full-2010-20261016-retention-v3`.
Its completed pool has 1,942 stocks and a 4,110-session calendar. There are 114
retained L1 event-part receipts. Their identity and payload hashes are verified
as a preliminary integrity check; only the selected stocks' rows are projected.
This verifies consistency with the currently saved receipts, original identity
fields, and unchanged read fingerprints. It does not authenticate an independent,
immutable archive: coordinated changes to input files and all their receipts
cannot be excluded by this local chain alone. Selected retained-event parity and
the future full saved-table parity gate remain separate evidence requirements.

| Identity                  | Fixed value                                                                        |
| ------------------------- | ---------------------------------------------------------------------------------- |
| Input                     | `5c48eb999a81e42149c858331a601aff700a63af3c7f2fb8d642bf20b1370c05`                 |
| Original numerical source | `a3cfc677ef01547132ce5f3e5cd2a514201fecc02d65f4fa87aeb6fc69cc7ea4`                 |
| Base labels               | `checkpoint-only:27791891061e5d71cd791d3389beaae6923da7f2d6800462985937c2cba6e48f` |
| Calendar                  | 2010-01-04 through 2026-10-12                                                      |

Selection is fixed from receipt metadata before reading outcomes. Counts below
are all-pattern cohort metadata, not L1 event counts or research support.
Distinct choices use ascending code as the tie breaker.

| Code | Selection reason                                                 | All-pattern metadata rows |
| ---- | ---------------------------------------------------------------- | ------------------------: |
| 1101 | First stock with a retained L1 event part                        |                       635 |
| 3653 | Largest retained-stock cohort metadata, excluding earlier choice |                       899 |
| 1514 | First stock without a retained L1 event part                     |                       726 |
| 6223 | Largest missing-part cohort metadata                             |                       926 |
| 1515 | Next stock without a retained L1 event part                      |                       774 |

For the two retained stocks, effective labels, eligibility, event membership and
condition classification must match saved L1 union rows exactly. For the other
three, saved cohort IDs, base labels, quality and calendar drive the same shared
projection; there is no surviving per-event golden result to claim parity with.
The fixed L1 event cohort precedes all volume grouping. No arm is recooled.

Historical checkpoint identity is reconstructed using the original v3 label
descriptor. The original writer's runtime-equality check remains unchanged;
the recovery reader validates the saved Git-source body digest and fixed label
pin, while recording both historical and current runtimes. Reading saved labels
does not claim that the original runtime has been executed again. Selected saved
events and conditions still require exact numerical parity under today's reader.

## Execution and evidence boundary

One Windows child job, one stock in flight, numerical-library threads set to one,
600 seconds maximum job wall time, 2 GiB committed-memory job limit and 128 MiB
total output budget. The supervisor remains outside the child job; its overhead
is not included in the job memory cap. Record the actual job committed-memory
peak separately from sampled process-lifetime working-set peaks. Phase receipts
include available wall/CPU/I/O observations; unavailable measurements stay null.
The preliminary 114-part hash I/O is included in the measured worker cost.

The entry point requires a clean committed executor and creates a new labelled
run through `scratch_runs.create_run`. It preserves failure evidence, never
overwrites a prior run and records final hashes with `run_receipt`. Inputs stay
in place. Per-stock intermediate events and conditions live in the shared
scratch run, not in a worktree. Successful pilot evidence remains retained for
review and later explicit lifecycle handling.

This pilot emits Q1 union and separate G / VOL_a marginal tables, including
annual rows. It does not emit market four-cell results. Four-cell integration
is tested with the synthetic fixture only. H126 and H252 remain separate;
unknown and censored overlap and are never counted as losses.

## Acceptance and next boundary

Pilot acceptance requires exact selected retained-event parity, intact source
identity, unchanged inputs, conservation of selected Q1 and marginal counts,
and successful bounded-job termination with measured resources. Full Q1 and
full marginal parity remain `not_run` regardless of a successful five-stock run.

Before any future market four-cell output, a separately authorized recovery
must reproduce the saved L1 union summary and all 34 annual rows, and the G and
VOL_a single-condition summary/annual denominators. The saved full Q1 targets
include H126 event/known/hit/loss/unknown/excluded-known/censored counts
52,479 / 45,690 / 2,606 / 20,879 / 4,503 / 2,170 / 2,094 and H252 counts
52,479 / 42,422 / 5,077 / 18,241 / 7,678 / 1,766 / 3,965. Distinct stocks are
1,882 at both horizons; annual distinct stocks must be checked separately, not
summed. These are saved historical targets, not newly computed pilot results.

The full targets are in the fixed catalog bundle
`d-results-v1/e54f8fea56898863a3b94ca40057f4fb66f41e0aa22cd3cfbc49ae67a89fe708/pattern-scan-d-finals.zip`
under `D:/StockData/stock-research/catalog/tasks/20261013-pattern-scan`.
Any mismatch stops new comparisons; do not alter methods to fit the targets.

Measured pilot findings and an evidence-based larger execution boundary will
be appended after the bounded run. No full-market runtime is claimed in advance.

## Work allocation

Recovery and bounded runner: `gpt-6.1-terra`, `/root/l1_recovery_core`.
Comparison contract producer/fixture: `gpt-6.1-sol`, `/root/l1_comparison_contract`.
Independent synthetic tests: `gpt-6.1-sol`, `/root/l1_recovery_tests`.
Independent read-only audit: `gpt-6.1-terra`, `/root/saved_input_audit`.
The coordinator owns canonical documents, input selection, real execution,
Git delivery and the final acceptance assessment. Shared files have one writer.
