# Data overview and chart overlays

The overview reads saved metadata, never price tables or SQLite. Producer acquisition
owns `data-status.json`; research projects its fields alongside shared-family metadata
and the existing research catalog. The API does not refresh any source.

## HTTP contract

`GET /data-status` (also `/api/data-status`) returns
`schema: research-data-status.v1`, `generated_at`, `status`, `datasets`, and `warnings`.
Each dataset has `id`, `source` (`producer`, `derived`, or `catalog`), a plain Chinese
`name`, `data_period: {from, to}`, `last_updated`, `symbols`, `rows`, and `status`.
Unknown counts and dates are null; zero means a measured zero. The overview status is
`ok`, `partial`, or `updating`; dataset states are `ok`, `stale`, `missing`, or
`updating`. These states describe metadata availability and freshness, not complete
historical coverage or fitness for a study. Frozen catalog entries do not become
stale just because time passes, and are not recommendations of the latest version.

The producer format is `producer-data-status.v1`, with `generated_at` and `datasets`.
Its dataset IDs are `official_daily`, `price_daily`, `institutional`,
`monthly_revenue`, `corporate_actions`, and `symbol_meta`. The producer PR defines
its freshness policy. An old saved status cannot indefinitely advertise fresh data.
Missing or invalid metadata produces an explanatory warning without opening the
underlying database. Derived metadata comes from each `derived/<family>/current.json`
and its pinned `generations/<id>/status.json`; catalog metadata uses existing manifest
validation. No dataset members are loaded. Names and warnings contain no local paths
or hashes.

The weekday 18:00–18:45 guard and running `StockProject-*` checks run before producer
root discovery and again after a read. A busy or uncheckable writer becomes
`updating`; it is not a page error. Public synthetic mode uses explicitly fictional
records and never resolves private data roots. Unknown modes fail closed.

## Stored overlay series

`GET /data-series/v1/institutional/{code}` returns daily stored institutional rows.
Optional `from` and `to` use `YYYY-MM-DD`; optional `market` is `TWSE` or `TPEx`.
Share counts are **shares**, including negative net counts. The endpoint does not
sum categories, turn shares into lots, fill gaps, or derive percentages.

`GET /data-series/v1/monthly-revenue/{code}` returns monthly current-revision rows.
Optional `from` and `to` use `YYYY-MM`; the same market filter applies. Revenue
amounts are integer **thousands of TWD** and stored percentage fields are percentage
points. Rows retain `revenue_month`, `source_report_date`, `announcement_at`,
`available_at`, `availability_kind`, `first_observed_at`, and `last_fetched_at`.
Historical `HISTORICAL_NO_EXACT_TIME` observations do not have an exact availability
timestamp. The chart must not interpret a revenue month as the publication date or
use this current-revision display as point-in-time backtest evidence.

Both endpoints also exist under `/api`, preserve SQL nulls, return ordered rows,
and cap output at 10,000 rows. They accept portable alphanumeric security codes,
validate ranges before opening data, use read-only SQLite with a five-second query deadline,
and recheck writer state and file identity after reading. Busy reads return HTTP 200
with `status: updating` and no rows. Missing or invalid artifacts return a neutral
unavailable result with a plain warning. An empty selection remains empty; it does
not trigger acquisition. Public mode returns a clearly fictional demonstration.

The overall read budget is 15 seconds, allowing two separate Windows scheduled-task
probes of at most five seconds each. Local selected-code smoke reads returned 1,895
institutional rows in 3.738 seconds and 165 revenue rows in 3.205 seconds, including
both probes. The overview read 19 metadata entries across all three sources in
1.988 seconds; it correctly reported the not-yet-published producer status and
historical/partial catalog entries as limitations.

## Measured local coverage

Read-only measurements on 2026-10-24, while both producer tasks were Ready and no
download/backfill process was present:

| Data                | Market | Period                |      Rows | Codes | Distinct periods |
| ------------------- | ------ | --------------------- | --------: | ----: | ---------------: |
| Institutional daily | TWSE   | 2019-01-02–2026-10-22 | 2,146,336 | 1,480 |       1,895 days |
| Institutional daily | TPEx   | 2019-01-02–2026-10-22 | 1,405,715 | 1,137 |       1,895 days |
| Monthly revenue     | TWSE   | 2013-01–2026-09       |   159,903 | 1,089 |       165 months |
| Monthly revenue     | TPEx   | 2013-01–2026-09       |   128,576 |   896 |       165 months |

The initial schema, count, and period probes took 34.758 seconds for institutional
data and 9.072 seconds for revenue. Those are full-artifact audit timings, not HTTP
latencies. Neither table is a complete historical listing universe: codes enter and
leave, and stored nulls must remain unknown. The missing-period audit below further
qualifies these bounds. No input copy, download, table migration, or index write was
performed. Existing institutional `(code, date)` and revenue `(market, code,
revenue_month)` indexes support the selected-code queries.

Across the complete institutional span, both markets have the same 1,895 report
dates as their stored official-price calendars: no whole market-day is absent in
that comparison. Within each code's own first-to-last observation, however, 123,186
TWSE and 317,450 TPEx code/day combinations are absent relative to that market
calendar. This is an absence count, not proof of acquisition failure: suspension,
instrument coverage and source reporting can also explain absent rows. All four
stored net columns (`foreign_total_net`, `trust_net`, `dealer_total_net`,
`three_institutions_net`) have zero SQL nulls in this artifact; other source-era
fields may still be null.

Revenue has no completely missing calendar month between 2013-01 and 2026-09.
Within each code's observed span, 175 TWSE and 204 TPEx code/month combinations are
absent. TWSE has 1,158 null month-over-month values, 576 null year-over-year values,
and 156,644 null `available_at` values; TPEx has 1,550, 1,115 and 125,900 respectively.
`current_revenue_k_twd` has zero SQL nulls in both markets. In particular, most
historical rows cannot be placed on an exact publication day. This second audit
took 106.062 seconds for institutional data (including the official-calendar
comparison) and 7.781 seconds for revenue.

## Dashboard pages

`/#overview` (資料總覽) renders `GET /data-status` grouped by source. A catalog
entry's `stale` is shown as 部分保存, because frozen catalog entries do not age.
`/#data/<code>` (個股) adds two opt-in layers that call the overlay endpoints only
when switched on: an institutional net-share pane (三大法人, 外資, 投信 or
自營商; shares, nulls left as gaps, dates outside the price calendar dropped) and
a separate monthly revenue chart on its own monthly axis with year-over-year
change. The revenue chart labels each bar as the revenue month, not a publication
date. Code: `research_web/src/features/data-overview/` and
`research_web/src/features/shared-data/{overlays.ts,RevenueChart.tsx}`.

## Delivery boundary

Producer and research ship separately. The research gitlink is updated only after
the owner merges the producer PR. Production code deployment and the first status
publication remain explicit handoff steps; opening a PR does not create a live status
file or change either scheduler. The dashboard owns rendering and can consume this
contract independently of those deployment steps.

## First formal publication: 2026-10-24

The owner merged producer PR #11 as
`ee4171b0de60e2385ec3bec9aa49b3c252711edd` and research PR #67 as
`892b9f3af2966b4ff22ea030a972a7b691af4f30`. The follow-up gitlink selects that
published producer release, from the preceding `837c211` pin.

The primary producer remained on `main` and was fast-forwarded from `f3ef521` to
`ee4171b`. Its configured data root is `D:/StockData/stock-data-downloader`.
`data-status.json` was first published there at **2026-10-24 10:11:22 Asia/Taipei**;
its `generated_at` is `2026-10-24T02:09:03+00:00` (collection start). The file is
1,900 bytes, with first-publication SHA-256
`143c1df9aac938aa06eb3615c67979a64a00f5a55ee80a9b0f5a3949af746903`.
This hash records the first publication; daily runs atomically replace the file
with a new summary.

| Dataset                     | Stored rows | Distinct source codes | State |
| --------------------------- | ----------: | --------------------: | ----- |
| Official daily prices       |  28,029,043 |                51,414 | ok    |
| Consolidated daily prices   |   6,671,767 |                 2,079 | ok    |
| Institutional daily reports |   3,552,051 |                 2,598 | ok    |
| Monthly revenue             |     288,479 |                 1,984 | ok    |
| Corporate actions           |      32,961 |                 2,534 | ok    |
| Symbol names and industries |       2,353 |                 2,353 | ok    |

The six source files retained identical sizes and modification times. Their
collection phases took 104.676, 8.024, 21.270, 1.571, 0.233, and 0.017 seconds in
table order. Existing task definitions and enabled states were saved before
maintenance; both producer triggers were paused while their processes were idle,
then restored. Exported task XML matched byte-for-byte afterward, and both tasks
were Ready with their original enabled states and next-run times.

The private `/data-status` and `/api/data-status` routes returned HTTP 200 with all
six producer datasets `ok`, while SQLite and Parquet opens were deliberately
blocked in the verification process. Overall `partial` continues to describe
the existing historical/partial catalog entries. The first status file is
rebuildable metadata; the normal daily backup includes it after the next daily
refresh. A separate backup run was not performed for this publication.
