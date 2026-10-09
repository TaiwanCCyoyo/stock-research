# Stock-membership source audit — 2026-09-09

This audit follows the [candidate packet](research-first-candidate-packet.md).
It checks membership and acquisition feasibility, not strategy performance,
trailing eligibility, a complete universe or a confirmation sample. All queried
market dates are inside the already-viewed development period.

## Measured coverage: distinguish three artifacts

Two TWSE `MI_INDEX` requests used `type=ALLBUT0999`, not an industry filter.
The official page labels this **all instruments excluding warrants/bull/bear
certificates**, not pure stocks. Both successful responses echoed the requested
date and included one quote table identified by the field `證券代號`.

| Observation                                                       | 2019-01-02 | 2023-12-29 |
| ----------------------------------------------------------------- | ---------- | ---------- |
| Official dated non-warrant roster                                 | 1,075      | 1,222      |
| Roster codes with no TWSE history in local `official_daily_price` | 63         | 23         |
| Roster codes absent from current `symbol_meta`                    | 88         | 76         |
| Roster codes absent on this day from merged `price_daily.parquet` | 157        | 223        |
| Missing official history but supplied by Parquet on this day      | 37         | 9          |
| Missing both official history and this day's Parquet row          | 26         | 14         |

These are instrument counts, **not missing-stock counts**. ETFs and depositary
receipts explain some intentional exclusions; missing regular-session closes
also explain some absent Parquet rows. None of these totals is an estimate of
strategy bias or evidence that every missing instrument meets the candidate's
trailing-liquidity rule.

The SQLite checks used `mode=ro`, `query_only`, a read transaction and indexed
`(market, code, date)` / `(market, code)` lookups, not a date-only table scan.
Metadata and price checks are separate database snapshots, not an atomic seal
of the entire pipeline. The Parquet check read only Code/Date/Source for the two
dates; size and modification time were unchanged during that read. Missing
Parquet here means no row **on that day**, not no history anywhere in that file.

## Concrete missing quotes, not just missing metadata

Three independently observed examples on 2019-01-02 have official regular-session
prices, but no TWSE history in the local official database, no same-day Parquet
row, and no current metadata row:

| Code / name | Official open | Official close | Official shares |
| ----------- | ------------- | -------------- | --------------- |
| 2475 / 華映 | 0.61          | 0.58           | 13,195,257      |
| 3519 / 綠能 | 2.54          | 2.53           | 773,336         |
| 3579 / 尚志 | 6.00          | 6.00           | 223,084         |

The [official delisting register](https://www.twse.com.tw/company/suspendListingCsvAndHtml?lang=zh&startYear=&type=html)
records termination dates of 2019-05-13, 2019-05-02 and 2019-06-26 respectively.
Those later dates are audit corroboration, not information supplied to a
2019-01-02 trading decision. No assumption about their later liquidation value
or strategy eligibility is made.

Conversely, 1262, 1589, 1704, 1724, 2499 and 6288 have a Shioaji-sourced
Parquet row on 2019-01-02 despite missing official history. Do not describe the
merged cache as containing only current survivors. Seven other nonzero
four-digit/non-91-or-92-prefix examples missing from that day's Parquet have
`--` official open/close, including some with positive total shares. Absence
of a regular-session quote must remain distinct from zero total trading or a
proven suspension. A code-shape screen is diagnostic, not certified stock type.

## Reusable acquisition route verified

One `STOCK_DAY` request per code for 2475, 3519 and 3579 in January 2019 returned
21 rows each. All 63 rows passed the existing
`scripts/backfill_official_history.py:normalize_twse_history_payload` without
loss/duplicate dates or identity changes. For January 2, all seven fields
(open/high/low/close, shares, value and transaction count) matched the separate
whole-market response for each code: **21 of 21 field comparisons**.

This shows the public monthly route still serves these delisted codes. It does
not prove that every delisted code/month is available. No new downloader or
production parser was required; the verification ran in the submodule's locked
environment. Captured payloads remain separate from existing caches.

The existing automatic backfill obtains its codes solely from
`SELECT DISTINCT code FROM official_daily_price WHERE market = 'TWSE'`
(`load_twse_backfill_universe`). Consequently, automatic backfill cannot discover
a code absent from its own database, however many months it retries. The merged
Parquet builder separately restricts official imports to codes already represented
in Shioaji daily files. Fixing just one of these boundaries does not automatically
fix the other or create historical stock classification.

## Historical security type: remaining boundary

The official query page has no single pure-stock option. Its non-warrant option
still includes ETFs and TDRs. The historical
[TWSE B.11 transmission manual, appendix II](https://www.twse.com.tw/docs1/data01/market/public_html/1040202-1040600224-1.pdf)
describes different code families and explicitly notes legacy four-digit TDRs
and reserved 9201–9299 codes. Thus `len(code) == 4` alone is not a stock filter.
The code conventions are a source lead, not certification of every security or
of later rule vintages. The PDF text was readable; screenshot rendering failed,
so no production classifier was implemented from the flattened table.

Keep main-board/innovation-board identity, transfers and historical stock type
explicit in the input adapter. Current metadata may corroborate an identity,
but must not become a required inner join that drops historical exits. Do not
use today's industry labels to repair this separate security-type question.

## Preserved evidence and next action

Local ignored directory A:
`.tmp/stock-membership-audit-20260909-ea6410b249c34984ac7389ce8e3dc707/`
contains both full-market responses, `audit.json` (code-level read-only database
comparisons), and `parquet-comparison.json` (code-level cache comparisons).
Directory B:
`.tmp/delisted-month-probe-20260909-9a4a04ba586d4ad395fe4a9311c6fb8e/`
contains the three monthly responses, their manifest and
`normalization-check.json` with parser/source hashes and field comparisons.

| Raw response           | SHA-256                                                            |
| ---------------------- | ------------------------------------------------------------------ |
| A / twse-20190102.json | `8348ca3dcbb028e9237c85fc115439b8fd7089caae05feae4d99598bb748b17a` |
| A / twse-20231229.json | `e3fb77aee79eacfe48d7945143b2c195b7ad8050ab7d58298b7d985b6dc4454c` |
| B / 2475-201901.json   | `9d1816543fac191777a9e4ab617a2f07ba87f951870d13b2c9855ef3c347c87b` |
| B / 3519-201901.json   | `10e1549c5754cce747180784012f372be8139d516e71cfec72bb44641541078e` |
| B / 3579-201901.json   | `b6f23072135b4729b4ec08558a6f4860e1787056aedc5da72881de8ac841fa59` |

Next acquisition should seed explicit candidate-period code/month work from
dated whole-market evidence, then reuse the verified monthly parser into a new
source-identified artifact. Do not rerun automatic backfill with its unchanged
code list, overwrite the old database/Parquet, silently mix volume conventions,
or build another downloader framework. The research input path must not retain
the old Shioaji-code restriction. Verify contemporary stock type, required
warm-up and source consistency before a complete candidate evaluation.

No market cache, scheduled task, submodule source or old result was changed by
this audit. This is progress on a recoverable source gap, not proof that the
candidate passes or that its full data dependency is now resolved.

## Offline export verification — 2026-09-09 follow-up

The additive `scripts/export_official_price_slice.py` in the data submodule now
exports explicitly selected official rows without a current-metadata or CSV join.
The new OpenSpec change is `add-explicit-official-price-slice`; legacy jobs and
cache schemas are unchanged. Its focused 11 tests and changed-file pre-commit
checks passed. Scoped implementation review returned no concrete findings;
the parent separately fixed the test fixture's misplaced SQL primary key and
verified the actual CLI. These are export checks, not a strategy gate.

The three captured monthly responses above were normalized into a **new** scratch
SQLite database, retaining their original captured fetch timestamps. A CLI export
with a 63-row cap was independently compared against that database: 63 rows times
14 fields, all 882 values equal. Three raw response hashes, both output hashes
and the unchanged source-database hash were verified. No network or existing-cache
write was required for this follow-up. Null behavior is covered by synthetic
tests; the real sample does not certify coverage of suspended instruments.

Local evidence directory:
`.tmp/official-price-slice-check-20260909-fc56f1dfbe54411fb160ae23c285596b/`
contains `input-evidence.json`, `source.sqlite`, `export/prices.parquet`,
`export/manifest.json` and `inspection.json`. Independent check script:
`.tmp/inspect-official-slice-20260909.py`.

| Artifact identity       | SHA-256                                                            |
| ----------------------- | ------------------------------------------------------------------ |
| Scratch source database | `6c7f6096dceadc6b5bf2bbb7df663df443b6ea5acdf531a1497a04d3ad26a0e6` |
| Canonical selected rows | `c1c11835384d30c524068a2b7e9a4af0714f33e3b014fc0b20939e5fa72d9632` |
| Exported Parquet        | `f8c89f44691b3d3dcc55f61e47946fcaa5bb5f4ce1a5730aa07b3c16cde5cad1` |
| Export manifest         | `331e2bcd307351c03ce4b5c0041ed406172b9881de41b6618ed5747ce639c2a0` |

This removes the CSV-only export dependency for recovered rows. It does not
recover missing months, classify the historical stock universe, establish
tradability, or demonstrate that any of these three stocks meets the candidate's
trailing liquidity rule. The submodule files remain uncommitted pending the
separate owner authorization; the parent gitlink has not been updated.
