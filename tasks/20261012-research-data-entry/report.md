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
- A tested exact state-replay extension bridge and correction/tail planner;
  efficient checkpoint continuation remains open, as detailed below.

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

The retained-artifact baseline passed all 16 checks before changes. Final normal
hooks, targeted results and the post-change retained-artifact comparison are
recorded with delivery after source formatting stabilizes. Local raw diagnostics
are at `.tmp/research-data-evidence/`, not Git.

## Explicit incomplete handoff requirements

This entry has not produced 2010-onward full-market features, prices, patterns,
labels or episodes and has not run pattern-scan. The 0050 context's complete scope
is benchmark-only. Existing 2019 datasets remain legacy and the 25-stock versions
remain partial. A missing or differently pinned artifact causes an error.

Handoff 10.10a asks for efficient daily state continuation, corrected-stock
rebuilds and actual retrospective tail updates under new immutable versions.
This stage implements planning and exact replay parity, but not that complete
incremental builder. Full calendar replay is recorded honestly; it is not
advertised as computation of new dates only. The efficient mechanism and its
end-to-end version-publication verification remain required work.

Primary's HHHL variants `params/input-pins-v1.json` raw bytes did not match its
retained execution pin during registration; the task checkout's tracked bytes
did match. The catalog therefore leaves that input period unknown rather than
rewriting primary or re-pinning an old result. This metadata observation does
not claim the retained result was corrupted: its original reader passed.

## Ownership and next stage

Session-owned checkout:
`D:/Project/stock-research/.worktrees/research-data-entry`, branch
`codex/research-data-entry`, based on `origin/main` at creation. Its normal checkout
hook initialized the producer submodule and physically seeded ignored inputs;
these are not new shared-area copies and were not used for market computation.
Keep this worktree for the PR and unfinished extension/mission work. Other
sessions' worktrees and primary branch were preserved.

Only `20261012-claude-handoff-pattern-scan.md` was found in the provided primary
handoff directory; a `(1)` version was not locally available. Pin the actual
supplied bytes in the later mission, and reconcile any newer supplied version
before mission approval. Do not equate the owner's spoken 2B definition with
legacy F33 or HHHL without the final explicit definition and confirmation rule.
