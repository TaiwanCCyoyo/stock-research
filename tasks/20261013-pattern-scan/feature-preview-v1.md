# Local feature candidate, pending shared-data SOP

Owner instruction 2026-10-16: prepare reusable highs/lows, Bollinger bands and
related values in the existing PR17 worktree. Do not write the shared root. The
owner and Claude will decide the shared update SOP before any handoff. This is
an explicit temporary exception to the usual external home for reusable data;
it does not register another maintained family or maintenance command.

## Coverage and access

`scripts.preview_pattern_scan_features` projects already completed PR17 stock
artifacts. It does **not** recalculate stock kernels, read producer prices,
refresh through the shared price reader, or resume expanded event calculation.
The original `full-2010-20261016-retention-v3` run covers 1,942 ordinary stocks,
4,110 sessions, 2010-01-04 through 2026-10-12. This candidate neither extends to
the latest trading day nor claims the broader shared-price universe or 0050.
All values retain the original PR17 official-source
`price-basis.v2/reference_factor_adjusted` preparation at that cutoff.

The local-only destination for this instruction is
`D:/Project/stock-research/.worktrees/pr17-retention-review/.tmp/pr17-feature-preview-20261016/`.
It contains `manifest.json`, `run_receipt.json`, and three ZSTD Parquets per stock:

| Table              | Contents                                                                                                                                                                                             | Availability / limitations                                                                                                                                                                          |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `daily_indicators` | SMA5/10/20/60/120/240, EMA5/10/20/60, ATR14 and its price ratio, BB20 middle/upper/lower and width, RSI14, ADX14, unnormalized MACD histogram, F10/F32/F22–25/F33 flags, quality and row identifiers | Original close-time definition and missing/warmup policy; no fill or reinterpretation. SMA240 and atlas/legacy flags retain their own original implementation, not a new generic family identity.   |
| `confirmed_pivots` | 1.5/4 ATR high/low, extreme position/date/price, confirmation position/date                                                                                                                          | Usable starting at **confirmed_at**; extreme_date alone is not availability. Final unconfirmed extrema were not emitted by the original calculation.                                                |
| `daily_conditions` | Original local MA/BB/support-resistance/candle/volume conditions, HHHL values and unknown reasons, eligibility and metadata                                                                          | Definition-qualified PR17/HHHL outputs. `industry_ref` is current-reference metadata, not historical PIT classification. Existing aliases within this table are retained pending SOP/schema review. |

Daily raw/adjusted OHLC, raw volume/turnover, restatement factors and action
metadata are not copied. BBUpper/BBLower are omitted only after exact equality
with BB20_Upper/BB20_Lower. Essential pivot extreme prices are retained. Daily
quality fields and stock/date keys remain necessary to interpret missing values
and join directly to prices without discarding invalid calendar rows.

Future-dependent `base_labels`, expanded events, controls, cross-sectional ranks,
Q1–Q6 and study conclusions are outside this candidate. Original study artifacts
remain in place for PR17 continuation; creating this preview does not retire them.

Read a table with `research_core.pattern_scan_parquet_v1.read_frame(path)`, which
preserves numeric SR-a, observed `"none"`, and unknown/null as distinct values.
The files' Arrow schema and manifest expose the exact column names. Definitions
remain in `derived_features`, `pattern_scan_indicators_v1`,
`pattern_scan_daily_values_v1`, and `hhhl_variants_daily` under the recorded
**original numerical source**, not the later projection executor.

## Integrity and local preparation

The adapter accepts only a destination beneath its checkout's `.tmp/`; checked
paths reject traversal, links, reparse points and hardlinks. Selected source
artifacts are hash-verified against their unchanged original stock receipts.
Only the three actually read tables are verified: deliberately retired
`prices.parquet` is neither restored nor needed. This is not a claim to have
reverified unrelated events, controls or the entire original stock bundle.

Every output is compared exactly after Parquet roundtrip, including dtypes,
values, missing values and index. Stock identity, complete common calendar,
daily availability and pivot confirmation timing are checked. Source stat
identities are checked at completion, and original preparation/result input
fingerprints must remain unchanged before the run receipt is written.

The manifest pins original numerical source, input ID, producer fingerprint,
stock receipts, selected input hashes, output hashes, rows, bytes and ZSTD.
The run receipt separately records the actual projection commit and dirty flag.
It references `manifest.json` relative to the candidate root so the final sibling
rename preserves references. It fingerprints inputs without copying input bytes.
Neither a fingerprint nor this projection makes the original dirty source an
exact reproducible source archive or proves historical point-in-time availability.

Preparation is serial, one stock at a time. It is bounded file verification,
projection and serialization, with no repeated numerical kernels or global
selection. The first stock and periodic progress record wall/CPU, process memory
and I/O; the enclosing local execution records a finite timeout and native Job
memory cap separately from disk space. Sibling staging moves without replacement
to one local candidate. Failure retains staging for inspection; it does not
overwrite a candidate, retry the study, update a catalog, or delete any data.

Keep this candidate until the owner/Claude SOP discussion resolves definition,
schema, safe read/update coordination, completeness requirements and transfer.
Do not set an automatic expiry, publish to the shared root, or call the preview
the authoritative maintained copy before that decision. Candidate payload stays
local; only adapter code, tests and this contract belong in Git.
