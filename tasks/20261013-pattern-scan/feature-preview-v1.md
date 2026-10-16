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

### 2026-10-16 本機候選實測

13:56 台北完成；原本已算好的數值全部重用，沒有重新計算指標或型態。
目前僅存於下述 worktree 目的地，未推送 payload、未寫共用 root、未刪原資料。

| 類別           | 股票數 |      列數 |    ZSTD bytes |
| -------------- | -----: | --------: | ------------: |
| 每日指標       |  1,942 | 7,981,620 | 1,113,532,088 |
| 已確認高低點   |  1,942 | 1,297,408 |    61,459,595 |
| 原定義每日條件 |  1,942 | 7,981,620 | 1,142,988,278 |

Parquet 合計 **2,317,979,961 bytes（2.32 GB）**；含 manifest／run receipt 共
2,322,735,005 bytes、5,828 檔。原三類表共 2,697,327,651 bytes，投影去掉
379,347,690 bytes 的重複欄位；原檔仍保留，這次候選是 owner 指定的暫時額外一份。
這是目前範圍的候選實測，尚不是未來全市場、更新到最新日的共用家族容量。

整批耗時 326.48 秒，所有輸出逐值／dtype／缺值／索引讀回相等。native Windows Job
committed memory peak 為 1,176,604,672 bytes（約 1.18 GB；不是磁碟用量），
2 GiB cap，結束後已確認 Job 無程序。共用 `current.json` 前後 SHA 相同；程式未寫共用位置，
不宣稱另做了一次整個共用 family 的完整 payload 驗 hash。

投影 executor 是 clean commit `00c74325e3b5cc5b6d476ce765fc40c5924ff556`；
原數值仍是原收據的 `0d1db8f`／dirty=True，不能改標成新 executor 計算。
27 項合成回歸及正常 hooks 通過；16 項既有發布產物驗證與修改前相同。
候選的 manifest 與 run receipt 引用在 sibling rename 後已核對，完整檔案數與大小一致；
沒有再重複掃描全部 payload 雜湊。小型摘要與 native Job 收據分別在同 worktree
`.tmp/pr17-feature-preview-20261016-summary.json` 與
`.tmp/pr17-feature-preview-20261016-execution.json`。

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
