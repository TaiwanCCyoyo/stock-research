# Research data entry implementation record

Owner request: use one physical primary shared area, read it through settings,
create no filesystem links, and verify path protection and isolated Windows
deletion. The supplied pattern-scan handoff requires this infrastructure stage
before a separately merged research mission.

## Delivered behavior

- Explicit root and portable path validation, reparse/symlink and hardlink
  rejection, constructor validation and a conservative worktree scan.
- An additive pinned catalog, generated README, original-reader verification,
  immutable publication, and existing bounded feature-engine reuse.
- Seven existing versions registered in primary in place: atlas, HHHL v1/v4,
  variants, the 0050 market context and two 25-stock price demonstrations.
  Historical data, source identities and receipts were not rewritten.
- Shared data included in the existing verified backup/restore scope.
- A retained exact v1 replay bridge, and a new bounded v2 checkpoint kernel with
  immutable feature extension, affected-stock rebuild and actual label/context
  tail publication. Full and chunked v2 outputs are tested exactly equal.

## Actual verification

Windows 11 build 26300, Python 3.12.11, Git 2.43.0.windows.1 and PowerShell
5.1.26100.9549 executed both `git worktree remove --force` and
`Remove-Item -LiteralPath -Recurse -Force` inside wholly synthetic repositories.
Each test checked exact absolute deletion targets and shared-root separation
before deletion. Both writable and read-only shared files survived: relative
filenames, file count, size and SHA256 inventory were identical. Four synthetic
worktrees were removed; no real research worktree or real data was used as a
deletion fixture. Windows junction and actual hardlink regressions also passed;
POSIX symlink tests are skipped on Windows in favor of the junction regression.

Two existing working directories, `research-data-entry` and `lf-text-policy`,
loaded the retained 0050 `past_only` data through this entry. Both returned 4,105
rows with identical full-row identity, external manifest pin and physical primary
manifest path. Neither had a local `research_data`; neither invocation calculated
market features. The second working directory was used read-only.

The actual owned Windows feature adapter, using an invented stock, computed one
SMA20 block. Its second consumer computed zero and admitted zero workers. Adding
BB20_Upper computed one block and reused SMA20. This is synthetic behavior proof,
not a market performance benchmark.

The retained-artifact baseline passed all 16 checks before changes; all 16 also
passed after the entry and after the checkpoint follow-up. The initial checkpoint
targeted run passed 421 tests with two POSIX symlink skips. After the dependency
and execution-boundary changes, all 109 incremental, fresh-source, original cache
boundary and CI-scope tests passed. Normal commit hooks passed on the final code.
The final Windows path/catalog/deletion run passed 135 tests with two POSIX skips,
including all documented superscript COM/LPT aliases rejected before any write.
These are overlapping test groups, not a sum of distinct tests.

Hosted CI at `a696aca` passed normal hooks and all 88 draft selector/CI contracts.
The earlier missing-inventory failures are fixed. Its whole check still concludes
failure at the explicit draft/full-validation gate: the full suite remains
pending. This is not a green PR or proof that the hosted research suite passed;
renewed review and checks must refer to the final delivered head.

[The compressed evidence packet](evidence-v1.json.gz) retains raw source pins,
the owner-designated handoff identity, both synthetic deletion receipts and both
registered-worktree consumer proofs. It contains no real price vectors. Local
raw diagnostics are at `.tmp/research-data-evidence/`, not Git.

## Checkpoint follow-up and research boundary

This entry has not produced 2010-onward full-market features, prices, patterns,
labels or episodes and has not run pattern-scan. The 0050 context's complete scope
is benchmark-only. Existing 2019 datasets remain legacy and the 25-stock versions
remain partial. A missing or differently pinned artifact causes an error.

The initial `d6f6207` draft implemented only an exact replay bridge. The follow-up
adds genuine checkpoint state for EMA/ATR/pivots and bounded per-period reuse of
the existing SMA/BB formula API. Full and chunk computation share the v2 kernel,
including gaps, warmup, equal extrema, confirmation dates and JSON roundtrips.
Rolling execution has a distinct numerical identity; v1 last-bit equivalence is
not claimed. Stored v1 evidence is not rewritten or relabeled.

Synthetic feature publication tests append twice, verify full-v2 equality on
readback and keep all old files byte-identical. Separate tests show zero compute
for the same request, only a missing feature initialized, and only a corrected
or factor-changed stock rebuilt. Actual H126/H252 and both context-layer updates
publish new pinned bundles, reference unchanged prefixes and reproduce the
retained full calculations. Tail updates preserve context event history. These
are mechanism tests, not a full-market performance measurement or completion of
the future pattern-scan's pattern/episode builders.

Parent review identified missing CI test inventory, incomplete pre-write Windows
name validation, missing linked-worktree identity checks and unbound market-context
input declarations. The follow-up adds the reviewed domain/inventory without
weakening full fallback, validates every payload name before any dataset write,
checks Git registration/common directory/admin back-pointer and canonical data
overlap, and binds all three benchmark source identities to the sealed manifest.
Negative and mutation tests cover each finding. Draft CI must be reported as its
actual contracts/checks scope, not as the full research suite.

Additional local review identified transitive retained-segment verification and
stale in-memory source identity gaps. Extensions now verify every retained source
bundle before reuse. Public builders reuse the existing fresh-source worker,
with loaded-byte checks before calculation and publication. Synthetic regressions
cover deleted/corrupt ancestors, stale callers and source changes during a run.

The subsequent review at `f022d0f` identified nullable scalar conversion, missing
CI consumer edges and an ambiguous calendar-only label coverage claim. The
follow-up normalizes OHLC through the existing validator, preserves dtype and
missing-versus-zero identity, adds both upstream consumer edges, and derives new
label coverage from actual main eligibility. Full-calendar, eligible and unknown
counts and disjoint eligible runs are reported separately. Public synthetic
regressions cover Float64/Int64 gaps, append/full equality, all-NaN H126 input,
gapped eligibility islands and retained early-hit-before-missing semantics.
All 113 incremental, fresh-source and CI-scope tests passed; a post-formatting
gapped-coverage regression passed again, and normal commit hooks passed.
[Review evidence v2](review-evidence-v2.json.gz) pins this follow-up separately;
the earlier evidence packet remains unchanged.

The automatic review of `d416a66` identified silent feature removal when an
extension requested only a subset of the base columns (MEDIUM). The follow-up
rejects any removal before calculation/publication, preserving both unchanged
and appended base versions. Targeted regressions assert zero kernel calls, no
new catalog/version and unchanged readback of the omitted column.
All 31 incremental tests passed, including unchanged subset, appended subset and
missing-feature addition; normal commit hooks passed. The task branch normally
merged owner-approved `main` at `ee1baec` (PR #13), without conflicts or history
rewrites. [Feature-retention evidence v3](retained-features-evidence-v3.json.gz)
records these pins separately; earlier packets remain unchanged.

Primary's HHHL variants `params/input-pins-v1.json` raw bytes did not match its
retained execution pin during registration; the task checkout's tracked bytes
did match. Their canonical JSON identities were also verified equal. The catalog
conservatively leaves that input period unknown rather than rewriting primary or
re-pinning an old result. This is a raw-byte observation, not a corruption claim;
the original result reader passed.

## Ownership and next stage

Session-owned checkout:
`D:/Project/stock-research/.worktrees/research-data-entry`, branch
`codex/research-data-entry`, based on `origin/main` at creation. Its normal checkout
hook initialized the producer submodule and physically seeded ignored inputs;
these are not new shared-area copies and were not used for market computation.
Keep this worktree for the PR and unfinished extension/mission work. Other
sessions' worktrees and primary branch were preserved.

On 2026-10-13 the owner explicitly confirmed
`D:/Project/stock-research/.tmp/claude-kline/20261012-claude-handoff-pattern-scan.md`
as the execution handoff. Its actual local raw-byte identity is retained in the
evidence packet; no Library transfer or independent Library byte-equivalence is
claimed. Pin those designated bytes in the later mission. Do not equate the
owner's spoken 2B definition with legacy F33 or HHHL without the final explicit
definition and confirmation rule.
