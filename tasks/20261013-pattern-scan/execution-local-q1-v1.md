# Worktree-only Q1 continuation

Owner instruction 2026-10-16: continue locally without waiting for routine
questions, do not expand algorithms or hash-driven archival mechanisms, avoid
duplicate payloads, and leave shared locations untouched. This execution
addendum changes storage/orchestration only; the approved mission, formulas,
unknown/censor handling, stock universe and observation period stay fixed.

## Scope

Compute the original Q1 unconditional pattern/subtype and control tables for
the completed 1,942-stock, 4,110-session run through 2026-10-12. Q2--Q6, candidate
selection, independent candidate/event audits and the final study report remain
separate unfinished work. This does not claim a strategy or account result.

`scripts.run_pattern_scan_local_q1` reads the existing original stock-result,
preparation and global barrier in place. Its output is restricted to the calling
checkout's `.tmp/`. For this run the destination is:

`D:/Project/stock-research/.worktrees/pr17-retention-review/.tmp/pr17-q1-local-20261016/<target>/`.
The optional `--target` selects an original registered family as an execution
batch; it does not change the research universe or invent a new pattern. The
local coordinator visits all twelve serially, with one finite owned Job per
family. A completed family is already the Q1 result, not another copy of its
event payload. The batch manifest names its targets explicitly; only a final
rollup covering all twelve may call Q1 complete. Completed family outputs are
verified and referenced on continuation rather than recomputed.

Existing event parts are referenced through `--reuse-event-root`; their original
ancestry and the three Q1-consumed artifacts are checked. Missing event parts
use the same `groups_for_pattern` and extracted `project_group_outcomes` that
the original full event builder uses. Q1 needs event membership and outcome
fields plus the already calculated MKT background, so it does not calculate
condition columns or save any new expanded event, condition or control table.
Indicators, prices, base labels and the global barrier are never recomputed.

All 12 families are visited by the coordinator. One family's integer count accumulators live at a
time; each stock's projected rows are discarded from memory after reduction.
Existing `StockCountPlan` expands only the inventory it was asked to count;
Q1 requests only unconditional cells. `DenseCounts` keeps the per-stock/year
integer evidence needed for distinct-stock counts, medians and removing the
best hit year. Rates are calculated after summing integers, never averaged.
The original 72 split/era/market facets, both horizons, zero cells, all 17 annual
rows, exclusion/unknown/censor denominators and earlier-year tie rule are kept.

The largest existing cohort-event stock is processed first for a representative
resource observation. This is execution order, not sample selection. Synthetic
tests verify that reversing the stock order leaves every result unchanged.
No new worker pool, shared updater, catalog, generation lease, input snapshot,
source archive or nested hash-version system is introduced. The existing run
receipt records code commit, input identity and result hashes. Input payloads
are verified once per process, with in-process file identity/change checks on
later reads; there is no persistent verified cache.

## Outputs and retention

Sibling staging contains one summary Parquet and one annual Parquet per family,
plus a small existing-format run receipt for each completed family. These small
receipts make already finished family results inspectable if a later family is
interrupted. The final manifest/run receipt marks the complete Q1 component;
the staging directory moves without a full copy when all families finish.
It is a local result pending full-study audits, not a shared publication.

Only result tables and small receipts are written. They may be kept as the Q1
portion of the eventual study result. No original inputs/checkpoints or preview
files are deleted. The reusable feature candidate remains where it is until
the owner and Claude agree on the shared update/transfer SOP.

The runner uses a clean committed executor and refuses a changed executor before
recording a completed family. Original numerical source/input identity is
recorded separately. A finite owned Windows Job bounds the actual run; disk
allocation, process working set and native committed memory are reported
separately. Representative timing and native observations precede a long-run
claim. Final Q1 row counts, bytes and resource evidence belong in the local run
summary, not in an invented full-study completion receipt.
