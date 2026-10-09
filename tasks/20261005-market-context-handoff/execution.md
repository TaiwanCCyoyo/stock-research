# Execution record — 2026-10-05

## Scope and seal

- Worktree: `D:/Project/Stock/.worktrees/research-workspace-20261003`.
- New delivery branch: `codex/research-handoff-market-context-20261005`, based on
  fetched main `13723d2e66b35369948eae494ffee3bda164f031`; preserved atlas branch
  `93cb75b97dd6c7c535a251ca2efaa1a79c1d7ddf` was merged without rewriting it
  (merge `1cac1c2`). Existing local submodule snapshot is not staged or changed.
- Fixed benchmark mission/OpenSpec committed through normal hooks as `5702aae`
  before any market state calculation. Formatter changes affected spec spacing
  only. No strategy results were inspected to choose benchmark thresholds.
- Core synthetic tests: `uv run --no-sync python -m pytest
scripts/tests/test_market_context.py` — **31 passed**, Python 3.12.11 / pytest
  9.0.3. Tested threshold boundaries, transition reset, missing windows, centered
  cutoff, past-only prefix invariance, scale invariance and invalid inputs.
- Subagent interpreter-cache permission failure was handed to the parent; the
  parent ran the same scoped test in the authorized normal environment. No ACL,
  cache policy, checks or environment variables were changed.

## Coordination

- Classification chat `01a0fa96-5143-72d2-aa1e-89bc000b3d17` confirmed 0050 is
  price-only in catalog-v2, with no hidden phase generation. This task owns the
  independent descriptor and does not modify that catalog or its stock rules.
- Website chat `01a0f85b-ed76-7153-947c-759892470507` confirmed it has not yet
  integrated the feature-discrimination atlas. Existing OpportunityMap names do
  not refer to this feature dataset. Agreed to retain its own versioned feature
  contract, not coerce descriptive comparisons into an account result schema.
- This task will supply exact portable manifests and read-only examples for a
  bounded consumer smoke check; no website UI work is required or claimed here.

## Preservation choices

Small new artifact directories are Git-tracked with `-text` so Windows newline
conversion cannot invalidate byte hashes. Prettier excludes only these generated
directories. Inputs/producer snapshots use deterministic compressed byte archives;
source bytes are not normalized to fit formatting checks. All ordinary source
and documentation retain normal hooks. The old atlas bulk dataset stays ignored,
unaltered and at its original plus same-drive-copy locations.

The source catalog manifest references many stocks, but this benchmark package
archives only the consumed 0050/calendar files and the manifest itself; it is not
a backup of the full catalog. No downloads or source-cache writes occur.

## Generation and transport-only revision

- Producer `edb5242` generated `market-context-v1` successfully in about 1.2 s
  (including command startup), under the 300 s budget. Initial dataset ID was
  `sha256:7cacf650a64f0bff4d96c4a9ae219a9d06d727c535b9f57395779dd87bfe1fa3`.
  The saved-input verifier and full row recomputation passed.
- Publication v1 kept exact comparisons in gzip (554,214 bytes). Benchmark v1's
  full catalog-manifest gzip was 554,708 bytes. Both exceed the ordinary 500 KiB
  single-added-file limit; no hook threshold or bypass was introduced.
- This diagnosed delivery issue changed transport only, not input data, scientific
  definitions, outcomes, cohort or decision thresholds. Producer `2767e1e` uses
  XZ for the exact atlas comparison JSON (418,040 bytes); `5c46ba7` uses XZ for
  the complete benchmark source manifest (446,076 bytes). Package schemas/paths
  become v2; the scientific rule remains `benchmark-context.rules.v1`.
- The second benchmark generation succeeded, and `--verify --recompute` passed.
  All definitions, summaries, both full row archives, 0050 and calendar archives
  match v1 byte-for-byte. Atlas v1/v2 decompression gives identical original
  comparison JSON bytes. Both first packages are retained locally and ignored;
  they were not deleted or overwritten. This is not an independent trial.
- New task tests after final transport changes: **100 passed in 6.31 s**.
  Normal commit hooks passed; formatting/type corrections did not change rules.
- Final package bytes: benchmark **793,345**, atlas **807,024**. Source manifest
  SHA remained `c7848ae7ad177770babfda774e07923f995ba2cb3fa4a83d77d02f77a0dfe140`.
  Final package IDs and all descriptor hashes are in the report/manifests.

## Independent consumer receipt

The website chat returned a bounded read-only smoke on 2026-10-05: original paths
and separate copies at its `strategy-presentation/.tmp/research-handoff-smoke-20261005-1916`
both verified successfully, 17 files / 1,600,369 bytes with matching identities.
It read F33/daily/regime including unknown contexts, selected-unknown, FP/FN and
the descriptive-not-independent marker. Both benchmark layers had the declared
45 unknown rows; past-only date lookup retained its matching cutoff. No bulk
path, source submodule, download, UI implementation or new research was required.
It reported no reader blocker; per-stock drilldown/continuous distributions still
require bulk, source PIT/total-return limitations and the atlas window remain.
This formal receipt preserves the useful handoff beyond its disposable copy.

Normal secret scanning flagged checksum strings in the three new manifests.
The parent audited them as SHA256 fields (including retained-original byte
hashes) from the verified packages and added 1,974 exact path/value baseline
entries. No directory/filter/detector was disabled. The existing regression
proving a newly introduced suspect checksum remains rejected passed (1 test).
This does not bless new future values or mutable files at those paths.

## Research boundary

App goal remains for owner update/resumption. No portfolio, feature combination,
holdout, source refresh or automation has been started by this handoff. The new
0050 exposure event records this task only; missing wider shared history is not
treated as evidence of an unseen period. The next small batch is a future task.

## Delivery locator

Published as [Stock PR #26](https://github.com/TaiwanCCyoyo/Stock/pull/26).
All 17 staged/committed artifact blobs were compared with the verified working
bytes and matched. Main's intervening documentation-only changes through
`2a6df6d` were merged normally into the already-pushed branch; no force push or
sealed history rewrite. The current-head check/review state remains in the PR,
not inferred from this static receipt. The final owner handoff must report the
actual reviewed head and any pending gate. Owner controls merge and App activation.
The pre-existing research worktree and ignored original inputs/results are not
disposable task scratch; preserve them during any later merged-branch cleanup.

## PR review corrections — 2026-10-05

The finalizer now validates the full registered packet and its requested task/run,
then uses `verify_reuse` before writing anything. A completed status alone is no
longer accepted. Copy roots equal to, inside, or containing the source are rejected
before directory creation. These guards are tested with synthetic artifacts.
The old atlas was not finalized again: its retained packet, archived packet and
receipt were read-only checked and all bind to packet digest `728a9659…788a4a3`;
the archived packet file also matches its existing input-archive byte hash.

The price adapter had incorrectly masked any 40% adjusted-price jump, including
a known cash-event decline that its contract says to retain. The correction
exempts only negative jumps on exact calendar dates with a known cash event;
positive unexplained jumps, non-calendar events, bad OHLC and unsupported or
ambiguous permanent events remain guarded. Noncash permanent factors still apply.

Bounded saved-output impact audit, not a fresh experiment: the retained inventory
has exactly two `unexplained_adjusted_jump` rows. Their table hashes match the
saved manifest, and the projected saved rows are:

| Security | Date       | Recorded event | Effect of this correction    |
| -------- | ---------- | -------------- | ---------------------------- |
| TW:2429  | 2024-07-02 | EX_RIGHT       | None; not a cash event       |
| TW:7810  | 2025-12-24 | empty          | None; no recorded cash event |

Thus the correction does not change this atlas under its saved inputs. Neither
row was declared economically explained; both existing gaps remain. No feature,
label, comparison or packet was rewritten. Any future execution of the changed
adapter needs a new code identity/registration, not reuse of the old seal.

The market-context reader now binds the **entire** rules-v1 document to its fixed
canonical identity, including events, missing-value semantics, units and caveats.
Historical reads do not depend on the active producer's mutable definition.
Recomputation tolerates only Git LF/CRLF conversion in its source comparison;
retained byte hashes remain exact, and actual source changes are rejected.
Both small published packages remain byte-for-byte unchanged.

The subsequent head review found a missing binding between the bulk manifest's
`identity` and its declared `dataset_id`. Both the bulk reader and its portable
publication consumer now recompute the producer's `fda-` identity formula, even
when optional file hashing is disabled. Rebuilding only the publication envelope
cannot hide a changed source identity. Read-only checks of the original and
same-drive atlas manifests confirmed both already satisfy this rule; their
stored identities are not migrated or regenerated.

After all review fixes, the seven focused atlas/finalizer/market-context test files
passed **177 tests**, with one Windows symlink-creation test skipped because the
host does not grant that capability (24.83 s). Nested ordinary-path rejection
and the other path cases passed. Actual retained benchmark verification plus full
row recomputation, and portable atlas verification with the strengthened reader,
passed without changing either package. Hosted review/checks remain the live PR
gate; this local evidence is not a review approval.

## Delivery synchronization with the research studio — 2026-10-05

The owner's preparation-only follow-up found PR #26 still open and conflicting
with the newly merged research studio on `origin/main` (`17f959b`). Its existing
review threads were all resolved and the prior head `7372f5a` had successful CI;
neither fact certifies the new merge head.

A dedicated `research-handoff-delivery-20261005` worktree preserves the separate
ongoing research branch and its local artifacts. The normal merge retains both
sets of exact evidence attributes and formatter exclusions. The secret baseline
uses a three-way per-path merge (7 ours / 12 theirs / 17 combined paths), without
changing detector configuration or adding new exception values. The native
worktree hook made a physical producer-data copy, not a link; this incidental
copy is not an approved research input refresh or canonical producer update.

Both portable dataset directories and their readers are unchanged relative to
the previously reviewed head. Delivery verification reads the existing packages
from this independent checkout; it does not rerun the atlas, generate a new
market context, evaluate strategies or open any sealed period. Latest-head CI
and hosted review remain PR gates, and merge remains with the owner.
