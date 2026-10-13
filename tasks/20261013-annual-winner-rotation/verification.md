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
