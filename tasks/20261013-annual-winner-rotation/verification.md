# Annual rotation execution and verification

The bounded Taiwan study and review-held-path replay are completed locally.
All complete strategy windows remain scientifically incomplete. New delivery
formatting is completed under the owner's explicit follow-up authorization;
Git JSON delivery remains blocked by the unapproved checksum security exceptions.
The shared immutable input, both process versions and originals are retained.

## Frozen execution and reuse

Mission registered at `ee7e80f` before annual ranks were viewed. Original
execution source HEAD: `11ebf32`; review corrections sealed at `0782e9c`.
`params/input-pin-v1.json` pins the prepared input. Original public report is
`params/original-results-v1.json`; `sweep_results.json` pins the reviewed process.
Both use the primary PR12 catalog, absolute external root and immutable bundles;
there is no shared-data copy/link in the worktree. The producer snapshot is a
physical checkout-hook copy with a verified three-consumed-file receipt.

| Phase                              | Observed work/result                                                                                                                                                                                                             |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Representative ranking measurement | 20 fixed evenly spaced codes; identical serial/two-worker row digest. Serial 8.208 s vs two workers 5.606 s; select 2 workers and at most 2 admitted stock tasks. Linear estimate 577.694 s, an estimate rather than a deadline. |
| Original full ranking              | 2,061 stocks, 16 calendar years, 25,883 observed stock-years; ranking wall 359.197 s. Whole CLI run 477.937 s, CPU 122.203 s; worker CPU receipts retained separately.                                                           |
| Memory                             | Original parent lifetime peak 2,001,498,112 bytes, **1,498,112 bytes above the planned 2,000,000,000 observation budget**. No OS hard cap or successful strict budget claim. Concurrent aggregate peak is not measured.          |
| Review-held-path replay            | Whole CLI 161.597 s / CPU 159.734 s; observed lifetime peak 1,793,798,144 bytes. Held-path/summary receipt 67.625 s includes compatibility verification. No new stock ranking: `new_stocks_calculated=0`.                        |
| Scientific equality                | `verdict`, `scope`, `annual_scope`, all three `arms`, `continuous_benchmarks`, and `measurement` exactly match the original public result. New position status/source/receipt/lineage evidence is additive.                      |
| Reader verification                | Original result passed strengthened verifier; reviewed result passed input/process/source-member/public-value and ranking-reuse lineage verification, exit 0 (46.030 s).                                                         |

Process I/O is Windows cached transfer counters, not physical disk throughput.
Pool startup/serialization isolation and token observations are explicitly
unavailable. Per-worker and phase receipts remain in the process bundle.
There were no downloads, producer updates, scheduler changes, trades or paid
reviews. The source snapshots inside the original and reviewed bundles remain
raw-byte pinned; neither old inputs nor any old sealed results were rewritten.

## Changed-behavior tests and hooks

147 distinct tests are covered by the final focused runs: annual economic,
ranking-pool, statistics and fail-closed CLI tests (38), plus publication/reuse
and CI selector/contracts (109). A combined intermediate run exposed a CRLF
synthetic fixture failure; corrected Windows text handling passed the affected
109 group. Test inputs are invented; the suite does not read published market
artifacts. Normal commit hooks at `0782e9c` passed secrets, file hygiene, mypy,
Pyright, Ruff, Prettier and relevant standard hooks without skipping checks.

The meaningful regressions cover future-data isolation; raw-price cash/split
unit accounting and rights remaining unknown; deterministic bounded serial/pool
equality; YTD missing endpoint retention; entire-year suspension/unordered paired
benchmark dates; public arms/verdict tampering and legitimate swapped-input
rejection; and compatible holding-only rank reuse versus changed prefix,
dependencies, historical scope or parameters. The CLI synthetic happy path and
tampering cases use a registered temporary Git primary/worktree.

`uv run python -m scripts.verify_published_artifacts` passed all existing
checks before and after the evidence-reader change. Published-artifact results
agree, including the four architecture bundles and existing HHHL variants. The
annual bundles additionally use their task verifier. Existing envelopes validate
the new `outcome=incomplete` result and appended positive `viewed` exposure event.

## Hosted delivery

Draft [PR15](https://github.com/TaiwanCCyoyo/stock-research/pull/15), branch
`codex/annual-winner-taiwan`, owns this task only. Merge stays with the owner.
At code HEAD `0782e9c`, [CI run 38385792491](https://github.com/TaiwanCCyoyo/stock-research/actions/runs/38385792491)
passed Repository checks and Draft selector/CI contracts. The run concludes
failure solely at **Draft full validation remains pending**; selected full Python
and frontend validation are skipped by the established draft gate. This is not
a full CI pass. The earlier run had real selector failures, now corrected; it is
not retrospectively called a draft-only failure.

## Formatted delivery follow-up

Finalizer source sealed at `f9954cf`, after incorporating current `origin/main`
without rewriting pushed history. No global canonical/write_json change. New
`delivery-v1/` copies are formatted using the configured hook, which passes a
second time without byte changes; then JSON meaning and new delivery SHA256 are
validated. The same order applies to the new receipt. The original task files
remain untouched.

The independently published `annual-rotation-delivery` version `1f66442e…`
(exact identity in `params/delivery-pin-v1.json` and primary catalog) preserves
all four raw originals under `originals/`, finalized copies/receipt under
`delivery/`, finalizer implementation snapshots, and explicit original input,
original process and reviewed process lineage. Content equality and raw-member
verification pass. Input pin was already formatted, so its new hash equals its
original hash; measurement/original-results/reviewed-sweep hashes differ only
because their presentation bytes changed. No market/ranking/download ran.

Initial 29 publication/delivery tests and 97 CI selector/contracts pass; normal source
commit hooks pass. This includes repeatable receipt/hash generation, strict
duplicate-key/nonfinite/UTF-8 handling, numeric 0/0.0 compatibility without bool
substitution, semantic-change rejection and task output isolation. Existing
published artifacts pass before/after this delivery-only helper change.

Parent P2 review correctly identified that the initial existing-directory path
could format copies before comparing its old receipt. Corrected source `79e125d`
checks the verified publication's receipt raw bytes, all local member hashes and
source/formatter/implementation/reference identity before any write; matching
completed deliveries return read-only without calling formatter or publisher.
Any changed identity or unpinned partial directory requires a new version path.
36 publication/delivery tests pass, including real filesystem successful
finalization/reuse, identity changes, receipt mismatch and formatter failure
preserving a prior completed version. Existing published artifacts again pass.

Corrected delivery uses `delivery-v2/`, immutable version `62999248…`, with
explicit `previous_delivery_entry` pointing to unchanged v1 `1f66442e…`. Its four
presentation file hashes equal v1's stable-format hashes; its receipt and
finalizer implementation identity are new. All originals/input/process bytes
remain unchanged. The exact new entry is in `params/delivery-pin-v2.json` and
the primary catalog. Default `delivery-v1` is not silently upgraded.

The last locator fix is sealed at `da2bb35`: newly created unpinned discovery
locators also complete the configured formatter before semantic/bytes validation.
38 publication/delivery integration tests pass, including locator idempotence
and rejecting a different existing entry before formatting. Full corrected
delivery is `delivery-v3/`, immutable version `7293ac31…`, explicitly linked to
v2. All three versions remain retained; the four presentation hashes are stable
across v1/v2/v3. The locator is formatted and does not change any bundle SHA.
Both candidate files, receipt and locator complete an unchanged second normal
formatting pass. Exact v3 identity is in `params/delivery-pin-v3.json` and catalog.
An actual second v3 finalization returns the same version without formatter or
publication output. Read-only audit confirms the local delivery/receipt bytes
match the immutable version and all four source originals remain byte-identical.
The normal scanner's v3 findings total 140 file/value records: input pin 4,
measurement 5, original result 21, reviewed sweep 26, receipt 43 and locator 41.
No record is added to baseline. Exact findings are retained at
`.tmp/formatted-delivery-v3-scanner-findings.json` for the separate owner decision.

Scanner/baseline remain unchanged; new formatted JSON false positives are
recorded read-only at `.tmp/formatted-delivery-scanner-findings.json`. Those
files remain unstaged pending exact owner-approved security scope. New delivery
formatting authorization did not grant baseline exceptions or hook bypass.

## Verification-flow optimization

Cause found by measurement, not assumption (single machine, warm cache, no downloads or
market recomputation). `run_study.py verify` took 180.78 s wall (166.84 s CPU). One
`verified_result` is 0.64-0.89 s of which SHA-256 is about 0.2 s. The remainder was
`DataRoots.from_env(worktree=...)` -> `validate_worktree`, which re-checked every ancestor
of each of 28,472 worktree entries (84% under `.venv`), and the runner calls `catalog()`
once per phase, so `run` paid it up to three times. `scripts.verify_published_artifacts`
was never the slow part: 22 s for its 16 checks (21 s after the change).

| Change                                                                                    | Result                                                                                                      |
| ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `_check_tree`: one `lstat` per entry, same `_reject_alias` predicate                      | worktree walk 1.4-1.8 s (was about 180 s); `run_study.py verify` 1.90-2.03 s over three runs (was 180.78 s) |
| `DataCatalog.get_verified`; `verified_result` no longer verifies the process bundle twice | each bundle member is hashed once per call (test); a saving of milliseconds, kept for clarity               |

Equivalence is tested, not argued: a differential test runs the old per-entry check and
the new walk over clean, nested-hardlink, top-level-hardlink and Windows-junction trees
and requires identical accept/reject; a cost test requires exactly one `lstat` per entry.
The symlink cases of that test are skipped on this unprivileged Windows account (and
therefore in Windows CI); they share `_reject_alias` with the old check. Two traps found
on the way and covered: `os.scandir` entries report `st_nlink=0` on Windows (so the
hardlink check still needs an `lstat` per file), and Python 3.11 `os.walk` descends into
junctions (so the walk must stop at a reparse point before entering it).

Unchanged on purpose: every sealed hash, bundle, pin and delivery version; manifest
double-hash; scanner and baseline; the researched results. Known consequences:

- `finalize_delivery.py` records live digests of `annual_publication.py`,
  `research_data_catalog.py` and `research_data_paths.py`. Those are the three files
  changed here, so re-running it on v1-v3 fails with `ValueError: delivery JSON content
differs from original` (run once on v3: nothing in `delivery-v3/` or `params/` was
  created or changed). The message comes from the receipt comparison, where the recorded
  implementation digests differ; it does not mean delivered data changed. The bundles
  still verify.
- `research_data_incremental.implementation_identity()` hashes every loaded
  `research_core`, `StockProject` and `scripts` module, and `:195` rebuilds instead of
  extending whenever it differs. Any edit to a loaded file (this PR's, or a formatting
  change) makes the next incremental publication a full rebuild. Checked other source-hash
  identities: `derived_cache` (price-bases) and the feature pool v1/v2 lists do not include the
  three changed files, and no incremental bundle exists in `research_data` or `research_cache`
  today, so no stored version loses reuse. Narrowing that identity to the calculation's real
  dependencies is a separate, measured change; it is not made here.
- The walk is a point-in-time check, as before; it no longer re-checks ancestors that
  were already checked earlier in the same walk.

Standard: [artifact integrity and verification](../../docs/en/artifact-integrity.md).

## Minimal exact plan for the scanner and pin blocker

Nothing here changes the scanner, its baseline or any hook, and no further `delivery-vN` is issued.

- **Adopted (zero scanner records):** tracked prose identifies data versions by an 8-character prefix
  (see the one-page summary in `report.md`). Full identities stay in the local `research_data` catalog
  and in the untracked `params/input-pin-v1.json` and `sweep_results.json`.
- **Optional, needs an owner security decision (not done):** track exactly those two files, the ones
  `research_result.json` and `run_study.py verify` point to. The last scan counted 4 records for the input
  pin and 26 for the reviewed sweep, so 30 records (about 9.7 KB of baseline at the current average of
  324 B per record, against about 64 KB of headroom). The other 110 of the 140 records come from the
  measurement and original-result files (26, nothing needs them tracked) and from the receipt and
  locator (84, which exist only for the retired delivery flow).

## Remaining delivery approvals and data blockers

Automatic approval review rejected running `.tmp/audit_annual_checksums.py` to
append persistent exact checksum false-positive exemptions in `.secrets.baseline`,
requiring explicit security-setting authorization. The baseline and scanner
configuration remain unchanged. A read-only review proposal is retained at
`.tmp/checksum-exception-proposal.json` / `.md`; it checks input file digests,
process manifest/object identity, archived source bytes, the exact representative
rank-row digest and fixed parameters digest. No credential is involved.

The earlier explicit Prettier run on original files was rejected as a possible
sealed-evidence rewrite and did not execute. The owner later explicitly requested
new delivery copies to be formatted and hashed while preserving originals; the
follow-up above completes that scoped action. Original files and all old bundles
are unchanged. Security exceptions still require the separate owner decision;
this session does not change the scanner/baseline or duplicate parent's request.

Historical PIT/delistings, economic rights and daily quote/fill gaps still block
an unbiased whole-market champion and full strategy significance claim; see
[data-gaps](data-gaps.md) for the exact seven holding windows and a bounded
producer-first follow-up. The local original-image Library materialization gap
is recorded in mission/report and does not block this independent Taiwan study.

Session-owned worktree `.worktrees/annual-winner-taiwan` is **retained for open
PR15 and the local evidence-delivery approval**, not merged or removed. Other
sessions' worktrees/data are preserved. All annual calculation processes have
exited; no annual bundle writer remains active in this session.
