# PR17 shared-price continuation v4

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

`scripts.continue_pattern_scan` launches `prices`, `retire-prices`, `barrier` or
`analysis` in the existing owned Windows Job, with a finite timeout, at most
8 GiB committed Job memory and at least 4 GiB available host reserve. A separate
capacity plan admits only that phase, with explicit additional disk components,
pinned evidence and at least 32 GiB disk reserve. Existing shared and stock bytes
are not additional allocation. Estimates, native Job measurements and disk
observations are distinct. A four-stock historical profile does not certify a
full-market barrier, candidate pool or Q4-Q6 memory requirement.

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

Implementation tests use synthetic data. Actual execution, equality, retirement
counts and resource measurements are reported in their run receipts; passing
tests alone never establishes any of those facts.
