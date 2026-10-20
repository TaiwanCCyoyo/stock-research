# PR17 shared-price continuation v4

## Current continuation policy: owner update 2026-10-19

This section takes precedence over the historical orchestration and intermediate
hash requirements below for newly written phases. It follows section 6 of
Claude's `pr17-shared-data-reply-claude-20261017.md` and the owner's explicit
instruction. Existing receipts, completed results and numerical source/input
identities remain unchanged; this is not authority to rerun completed work.

- Do not execute `maintain_adjusted_daily update` before
  [PR #34](https://github.com/TaiwanCCyoyo/stock-research/pull/34) is merged. The
  current main updater ignores holds and could prune the generation used by
  this study. Before any later authorized update, use the merged implementation
  that honors holds; merge alone does not request an update or scheduler change.
- The existing hold is `pr17-pattern-scan`, for generation
  `2026-10-15-20261015T161626Z`. It protects the original Q2--Q6 inputs. Continue
  reading the original derived tables; do not switch this unfinished run to the
  newer technical generation. The hold file was checked read-only on 2026-10-19.
- After Q2--Q6 finish, release this holder with the merged hold-aware CLI:

    ```text
    uv run python -m scripts.maintain_adjusted_daily release --holder pr17-pattern-scan
    ```

    This removes the hold, not the generation payload; a later update may prune
    the now-unheld generation. Do not release while Q2--Q6 remain incomplete.

- Apply the owner-approved results-only policy from
  [PR #35](https://github.com/TaiwanCCyoyo/stock-research/pull/35) to newly written
  phases and future runs now. Hash final result tables and record inputs, shared
  generation and actual code commit in the run receipt. Do not hash intermediate
  stock parts, phase outputs, worker files or previews; do not create per-file
  intermediate receipts/manifests or repeat payload verification between phases,
  including through legacy helpers. Missing or damaged intermediates require
  rerunning the affected step, not another archival layer. Numerical tests,
  schema/count checks and deterministic aggregation remain appropriate.

The older per-file pins and receipts below describe retained execution history
and its compatibility path, not a template for new stages. Preserve those stored
records and completed Q1 outputs. This policy update itself runs no calculation,
shared update, release or deletion.

## Local Q2–Q6 v5

Owner instruction 2026-10-20 authorizes continuation after synchronizing main.
PR #34 is merged (`0b3e8d6`); main `d164227` also includes #30 and #38.
PR #35 remained open when checked, but the owner's results-only policy applies
to new stages immediately. No update is needed for this continuation.

`scripts.run_pattern_scan_remaining` reads the original 1,942 stocks, 4,110
sessions and original global barrier through cutoff 2026-10-12. It reuses the
1,372 existing event parts and completed Q1, without source/input re-pinning,
new producer fingerprints compared with old ones, or per-file verification.
Neither the shared latest technical tables nor the 2.32 GB preview is an input.
Preview retirement is handled by another session under the owner's instruction.

New missing event/condition projections are temporary, limited to one target.
Q2/Q3 keep exact development integer counts, CRC split, Fraction ranking,
family gate and all registered candidates; one group/horizon accumulator lives
at a time. Q4 keeps the fixed random seed, dates/quota selection records and
bounded examples. Q5/Q6 reuse per-stock followup projections and original
holding grids. Same-industry holding partitions retain every reference peer in
original column order and are tested exactly against the full-grid kernel.

Q4 uses `pattern_scan_candidate_daily_v2` for the mission's daily tri-state
coverage rule. A candidate can be selected from eligible development events
while one of its conditions is not applicable on other raw signal dates (for
example H outside its comparison cohort, or H1 A without bonus levels). Such
dates remain unknown, with the original conjunction's N/A precedence preserved.
They neither prove candidate absence nor remove an episode. A known match still
absorbs unknown; an unknown day before it keeps first timing uncertain. The
historical `candidate_daily_v1` and its callers stay byte-identical. Candidate
selection, event membership, Q1 and completed conditions tables do not change.

The final summary/annual/coverage/selection/episode/followup tables receive
SHA-256s through `write_run_receipt`; inputs are descriptions and original
lineage, shared generation and actual executor commit are recorded. New phase
progress records completed groups/stocks rather than per-file hash manifests.
Completed components are referenced and not rerun. The owned Windows Job is
limited to 8 GiB committed memory, one serial target and a finite timeout, with
4 GiB additional available host memory required. Measurements distinguish
process memory, Job committed memory and disk space.

Interrupted publication resumes from sibling staging. Complete final tables
can finish their receipt and no-replace publication without repeating stock
work. Partial final writes preserve valid tables and reuse completed temporary
stock projections to fill the missing summary family. One small phase-start
record keeps the original executor; a later recovery commit is recorded
separately when it computes or finalizes the remainder. A legacy unfinished
phase without that record requires an explicit recovery of its known executor,
never a guessed commit. Reusing an already receipted final bundle verifies its
stored result digests once in that process; intermediate files remain unhashed.

Candidate-selection JSON, the legacy preparation benchmark and temporary
holding projections publish through sibling staging. An interrupted write
repairs only the unreceipted metadata or affected cache; valid existing files
retain their bytes and modification times. Recovery of a missing legacy
producer-read receipt preserves the original input fingerprint and read-code
identity, records the recovery code and any later source drift, and explicitly
states that no producer read was repeated. It does not require today's producer
files to reproduce completed derived bytes or rewrite existing receipts.

The launcher reuses the shared maintenance code's OS-lock primitive. The small
`.active.lock` file remains in place; the operating system releases its lock
when the coordinator dies. A new-protocol diagnostic marker can then be
replaced under that lock. Legacy PID markers, malformed markers and foreign
markers require explicit verified recovery and are never automatically taken
over. This protects the still-running original executor. The legacy analysis
selection also publishes atomically; an already consumed or receipted selection
is never repaired in place.

First creation of the local diagnostic marker also uses atomic no-replace
publication. A legacy launcher that enters after the initial absence check
therefore wins its exclusive-create without being overwritten by the new one.

Legacy `continue_pattern_scan` and `pattern_scan_run_v2` launchers deliberately
remain fail-closed. An operator recovering their marker must first prevent all
concurrent launches for that run, identify its owned request/launch record,
recorded code and exact marker bytes, and establish that the original
coordinator **and its owned Job/workers have ended**. A reused or absent PID,
file age or an idle-looking log is insufficient. Confirmation from the exact
owned Job teardown, or a verified machine reboot after the recorded launch,
can establish that boundary. If ownership or Job termination is unknown, retain
the marker and do not start another writer. Only after that verified quiescent
boundary may the owner remove the matching stale marker and resume the recorded
phase with its existing checkpoints. Preserve the data and receipts; do not
restart stock/global/Q1 or retire a generation as part of marker recovery.
This is a recovery procedure, not authorization to stop or take over the live
`4f5daaa` study, and no legacy marker was removed by this change.

Only this continuation's new temporary projections are cleaned after a target's
three final components are saved, readable and receipt-recorded. Original
inputs/checkpoints, Q1 and preview are retained. Q2–Q6 completion is reported only
after all twelve targets finish all three components. The owner-authorized
`release --holder pr17-pattern-scan` follows that completion; partial runs never
release the held generation.

## Historical execution contract

Owner instruction: 2026-10-16, after PR26 merged (`804a765`). This addendum
supersedes only the v3 requirement to retain PR17's own prices until formal
publication. Historical receipts and completed numerical work keep their bytes
and original source identity. Non-price retirement still requires the verified
formal result and completed reference handoff described in retention v3.

## Reuse and price transition

The completed `full-2010-20261016-retention-v3` stock phase contains 1,942 stocks,
with the approved 4,110-session calendar and cutoff 2026-10-12. It stops before
the global barrier. Continuing this run must not call its stock kernels again.
The stock source commit is numerical ancestry; each new phase independently
records its actual executor commit/runtime and the unchanged stock-result hash.

`pattern_scan_shared_prices_v4` adapts the existing maintained family's
`read_adjusted_daily(as_of=cutoff, calendar=..., generation=...)`. It creates no
private family, price cache, input archive or generation lease. The root comes
from `STOCK_RESEARCH_SHARED_ROOT`. One explicit generation, its status hash,
actual raw/actions inputs, price definition, official-source policy and complete
calendar are pinned. Missing or changed dependencies fail; there is no fallback
to current data. Metadata and universe remain in PR17's original fingerprint.

`pattern_scan_price_references_v4.create_price_handoff` compares the **actual**
prepared frames for all 1,943 securities including 0050 and the 1,942 stock-part
price frames against that reader. Every column, dtype, calendar position, value
and unknown/quality value must agree exactly. The three stock metadata columns
are appended by the same defined construction; prices are never coerced to make
a comparison pass. Original stock receipts remain unchanged. A completed transfer
journal binds the equality certificate, shared reference, original receipts and
explicit ownership inventory. Interrupted final metadata publication resumes
that completed comparison rather than recomputing it.

Only after this certificate and reference transfer validate,
`retire_own_prices` may remove the registered `prepared/` price Parquets and their
receipts plus `parts/*/prices.parquet`. It requires explicit retirement authority,
an available pinned generation, an idle run or its exact owned coordinator, full
alias/ownership preflight and unchanged prices. Unknown or changed files block
the entire operation before the first unlink. Its journal permits a partial
unlink retry. All indicators, patterns, labels and other completed stock work
remain available. This authorizes no cleanup of another run or shared family.

## One admitted continuation phase

`scripts.continue_pattern_scan` launches `prices`, `retire-prices`, `barrier`,
`events` or `analysis` in the existing owned Windows Job, with a finite timeout, at most
8 GiB committed Job memory and at least 4 GiB available host reserve. A separate
capacity plan admits only that phase, with explicit additional disk components,
pinned evidence and at least 32 GiB disk reserve. Existing shared and stock bytes
are not additional allocation. Estimates, native Job measurements and disk
observations are distinct. A four-stock historical profile does not certify a
full-market barrier, candidate pool or Q4-Q6 memory requirement.

The `events` boundary consumes the verified full-market barrier and all original
stocks, writes the same reusable per-stock/target event checkpoints used by
analysis, then stops before candidate selection or summary/followup allocation.
Its inventory binds every target/code receipt, original labels and global table
pins. It admits only event projection. Later analysis verifies and reuses these
completed checkpoints, while its capacity plan can use their actual row counts
and representative accumulator observations rather than treating unknown later
memory as zero.

Control requests and responses live in an explicitly named sibling control run,
outside the original completed run's ownership inventory. An active marker blocks
a second Job. Original stock numerical receipts are verified through the explicit
price replacement seam; generic file verification never accepts an absent file.
The barrier and analysis consume those completed stocks, with ZSTD for new
Parquet output and actual bytes/hashes in receipts. Analysis remains unpublished.

## Retained evidence and limits

The computed result keeps the original stock source separately from the actual
analysis executor, the stock-result pin, shared generation/reference and small
equality/retirement certificates. Its final result receipt identifies the actual
executor. Large handoff inventories and expanded event/control tables are
execution intermediates, not permanent input snapshots.

Completed continuation phases also retain their small request, response, native
Job and capacity JSON under `execution/phases/<phase>/`. Their source/input,
stock/reference pins, output locators and Job limits are checked before adoption.
Different historical executors are allowed and recorded as they actually ran;
they are never relabeled with the analysis commit. An entirely absent phase is
listed as unavailable; a partial evidence set fails verification.

When a source update requires a new sibling control, `--phase-history` pins a
small `pattern-scan-phase-history.v4` JSON manifest. It names completed phases'
original sibling controls and exact request/response/Job/capacity file pins;
metadata is read in place. The original request bytes and actual executors stay
unchanged. The new phase request pins this manifest, and retries require the same
pin. A current phase cannot also be supplied by history, nor can a partial
current phase fall back to history. Scope, metadata aliases, pins, source/input,
output locators and native Job evidence remain checked. The manifest and phase
metadata become retained execution evidence in the formal result.

An interrupted attempt is listed separately with its original request and
owner-directed cancellation receipt, never as a completed phase. Those small
records are retained under `execution/interruptions/`; its unavailable native
peak is not replaced with a later Job's observation. A new executor reuses event
parts only after checking their original source/input, labels, stock and global
identity and payload hashes. Such identity checks do not themselves establish
implementation equivalence: assess the source change before reuse, and change
the numerical definition or invalidate affected parts if behavior changed.

The analysis Job's native peak is pending when the immutable computed index is
captured. After `launch` returns and its Job has closed, the CLI calls
`record_analysis_completion` to retain `analysis/audits/continuation-completion.json`.
This bounded audit pins the computed index, contains the small request and Job
evidence, and retains the expanded response's hash plus identity projection.
Formal handoff must include it as `audits/continuation-completion.json` through
`audit_files`; the computed index is not amended. A failed audit write can be
retried against the completed phase without recomputing results. Sibling control
metadata remains temporary until these retained records are verified in the
formal bundle; cleanup of the original run does not implicitly delete siblings.

`scripts.audit_pattern_scan_candidates` independently reconstructs the five
selected candidates from explicit unpublished computed results and the pinned
stock/barrier/label ancestors. Its 54,720 comparison rows do not replace the
separate ten-event audit. A smaller selection is reported as incomplete rather
than claiming the promised audit passed. Audits retain their actual executor.

Long-term material remains the report, Q1-Q6 tables, selections, denominator/
unknown/censored counts, bounded promised examples, audits, code commit and run
receipt. After formal verification and single-copy publication, non-price
checkpoints and expanded rows are retired immediately without a recovery period.
The external catalog/payload destination remains the separate catalog task's
decision; this continuation does not publish new versions to `research_cache/`.
Receipts retain identities and comparison evidence, not deleted input bytes or a
guarantee that a removed shared generation can ever be reproduced.

Implementation tests use synthetic data, including a real small maintained
generation read through the as-of adapter, handoff and retirement without mocked
price reads. Actual execution, equality, retirement
counts and resource measurements are reported in their run receipts; passing
tests alone never establishes any of those facts.
