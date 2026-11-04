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

## Measured pilot and retained evidence

The completed run is
`D:/StockData/stock-research/scratch/20261013-pattern-scan/l1-recovery-pilot-20261103-r2`,
executed at clean commit `37f08f871faa44abf1263379c73608f90862d405`.
All 114 retained L1 parts passed receipt/hash checks. The five stocks produced
238 fixed union events / 476 horizon rows. The 1101 and 3653 saved event and
condition rows matched exactly; 1514, 6223 and 1515 have no retained event golden.

| Horizon | Events | Known | Hit | Loss | Flat win | Unknown | Excluded known | Censored |
| ------- | -----: | ----: | --: | ---: | -------: | ------: | -------------: | -------: |
| H126    |    238 |   226 |  21 |   75 |      130 |      11 |              1 |        7 |
| H252    |    238 |   214 |  44 |   68 |      102 |      18 |              0 |       17 |

Both horizons have five event-bearing stocks. These purposefully selected
recovery-test stocks are not an unbiased sample or a market conclusion. Unknown
and censored overlap. The two explicit eligibility exclusions at each horizon
are a separate count and must not be added to the table's other exclusions.

The one-off [saved-output verifier](verify_l1_recovery_pilot.py) independently
selected each unconditional and marginal bin from saved pilot rows and used
the shared direct summarizer. All **468** summary/annual rows with `split=all`,
`era=all`, `mkt=all` matched (summary `row_kind=full` only), including distinct
stocks and zero denominators; result hashes also matched. Other split/era/market
facets and drop-best-year rows were not covered by this direct pilot check.
It does not read original market inputs. Full-market parity remains `not_run`.

| Measurement                                         |                    Observed value |
| --------------------------------------------------- | --------------------------------: |
| Windows owned job wall time / exit code             |                      165.23 s / 0 |
| Measured worker wall / CPU time                     |               163.49 s / 152.73 s |
| Inventory and 114-part verification                 |                           51.37 s |
| Each selected stock's complete recovery             |                     18.22–19.03 s |
| Event projection itself, each stock                 |                     0.080–0.103 s |
| Final aggregation / serialization / artifact writes |       0.657 s / 0.067 s / 0.026 s |
| Peak job committed memory / configured cap          | 676,241,408 / 2,147,483,648 bytes |
| Sampled worker lifetime peak working set            |                 656,637,952 bytes |
| Worker read / write transfer counters               |       182,219,417 / 386,019 bytes |
| Entire retained run size / output cap               |       433,607 / 134,217,728 bytes |

I/O counters include cached Windows transfers, not physical-disk throughput.
Working-set peaks describe process lifetime, not isolated phases. The job/worker
wall difference includes startup and supervision; isolated startup was not measured.
Separate post-run count verification took approximately 1.4 seconds. Repeated
input-stability/path checks dominate recovery; projection and aggregation do not.

Python changed from original 3.12.11 to 3.13.18; NumPy 2.3.5, pandas 2.3.3 and
PyArrow 25.0.1 match the original source receipt. The first attempt, at
`f205d3fc837610e34d95f463f61bf562cad26493`, stopped before any projection because
the old writer helper required runtime equality. It exited 1 after 18.02 seconds;
the dedicated historical identity reader fixed that integration error without
changing old code, label semantics or saved inputs. Both attempts are preserved.

Portable final evidence is [results/l1-recovery-pilot-v1.zip](results/l1-recovery-pilot-v1.zip)
(197,402 bytes; SHA-256 `d007fe6b1a6b3e2d5974f983309b98010e1b23b4dedb0e616eb2ed800353de1a`).
It contains byte-identical pilot output tables, audit, original run receipt,
job measurements, the separate verification summary and first-attempt failure
evidence. It contains no checkpoint, price or indicator input copies. Scratch is
retained for review; no cleanup, full recovery or UI execution was enabled.

### Next execution boundary

The current CLI intentionally remains capped at five stocks. A direct linear
extrapolation of its observed per-stock costs would be roughly 9.8–10.3 hours
for 1,942 stocks plus fixed work; that is a planning estimate, not a full-run
measurement or a reliable deadline. Repeated global file-stability checks should
first be reduced without losing mutation detection, then measured again on the
same bounded inputs. Only after exact count equivalence should serial and bounded
parallel execution be compared. There is no measured parallel speedup to claim.

Before full recovery, obtain separate authorization for the fixed 1,942-stock
input generation, its execution budget and a new labelled shared run. Start from
one in-flight stock and the demonstrated 2 GiB process-job limit; do not infer
multi-worker capacity from this serial pilot. Measure the revised reader before
setting a full-run wall-time ceiling. The required gates remain the original
Q1 counts, all 34 annual rows, and G/VOL_a marginal summary/annual parity. Only
then may the same fixed event IDs feed a separately approved four-cell result.

PR #153's presentation model accepts an injected producer adapter. This contract
currently provides the overall cohort and four disjoint cells, not arbitrary
A-minus-B comparisons. A consumer must not subtract stock counts or infer
complement summaries from the bounded case references; any additional complement
counts must be explicitly produced from the fixed cohort in the research layer.

## Work allocation

Recovery and bounded runner: `gpt-6.1-terra`, `/root/l1_recovery_core`.
Comparison contract producer/fixture: `gpt-6.1-sol`, `/root/l1_comparison_contract`.
Independent synthetic tests: `gpt-6.1-sol`, `/root/l1_recovery_tests`.
Independent read-only audit: `gpt-6.1-terra`, `/root/saved_input_audit`.
The coordinator owns canonical documents, input selection, real execution,
Git delivery and the final acceptance assessment. Shared files have one writer.
