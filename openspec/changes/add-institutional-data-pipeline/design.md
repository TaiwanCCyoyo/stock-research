## Context

`fetch_corporate_actions.py` already establishes a working pattern for pulling official
Taiwan market open data locally: idempotent upsert keyed by a natural key, a raw-ranges
table tracking which date spans have been fetched (so repeated runs don't re-request
already-covered history), and retry/backoff around HTTP calls. Institutional investor data
(三大法人買賣超) has no equivalent in this repo. TWSE publishes it via a dated T86 report at
`www.twse.com.tw/rwd/zh/fund/T86?date=YYYYMMDD&selectType=ALLBUT0999&response=json` for
listed (上市) stocks; TPEx publishes a dated equivalent at
`www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date=YYYY/MM/DD&response=json`
for OTC (上櫃) stocks. Both are free, official, and require no credentials — consistent with
this project's existing data-source choices (TWSE for corporate actions, Yahoo Finance as a
dividend fallback). (The OpenAPI-catalogue host named in an earlier draft of this
change, `openapi.twse.com.tw/v1/fund/T86`, was confirmed by direct probing to be a 404 — it
does not serve this report; the `www.twse.com.tw/rwd/...` endpoint above is the real source.
See the submodule's `docs/institutional-sources.md`, task 1.3's artifact, for full endpoint
detail including field layouts, historical-range floors, and known parsing gotchas.)

**Relationship to `add-official-daily-price-source`** (submodule, price data, delivered
2026-08-07): that change built the first consumer of "fetch an official TWSE/TPEx OpenAPI
endpoint locally" beyond corporate actions. Two pieces are relevant here, and they are
reusable to different degrees:

- **Directly reusable**: `shioaji_stock_prices/shp_utils/official_api.py`'s
  `fetch_json_with_retry`/`parse_int`/`parse_number`/`parse_roc_compact_date` — a generic
  HTTP-fetch-with-retry-and-backoff helper with no TWSE-price-specific assumptions. This
  change should import and consume it directly instead of writing a second retry/backoff
  implementation.
- **Structure only, not directly reusable**: `backfill_official_history.py`, the delivered
  rate-limited resumable history crawler, is shaped specifically for TWSE per-symbol price
  history — it checkpoints by `(code, year_month)` against the `official_daily_price` table
  and is hardcoded to the TWSE single-symbol history URL. T86 is a daily whole-market
  endpoint (one request covers every symbol for one date), so a T86 historical backfill's
  natural checkpoint unit is `(market, date)`, not `(code, year_month)`. This change should
  follow the same throttle/checkpoint/backoff-with-bounded-runs _design_, implemented as its
  own module, rather than importing or extending `backfill_official_history.py`.

That same submodule change's design also confirmed there is no dated single-symbol TWSE price
history endpoint's TPEx equivalent (`backfill_official_history.py:5-7`). Task 1.2 confirmed
that gap does **not** carry over to institutional data: TPEx's `insti/dailyTrade` endpoint
accepts a `date` parameter and returns a full whole-market snapshot for any requested day, so
TPEx institutional data supports the same `(market, date)` historical backfill as TWSE — no
daily-increment-only fallback is needed for either market.

Two other endpoint findings from task 1.1/1.2 that affect the fetcher design:

- **Row-count filtering matters on both sides.** TWSE's `selectType=ALL` returns ~14k rows
  (it includes ~13k warrant codes); `selectType=ALLBUT0999` returns the intended ~1.3k
  stock/ETF rows. TPEx's `sect=AL` similarly includes warrant/bond-style 6-digit codes that
  `sect=EW` excludes. The fetcher must use `ALLBUT0999` and `EW`, not `ALL`/`AL`.
- **Historical floors and schema versions differ per market and evolved over time.** TWSE
  data goes back to 2012-05-02 (a 12-field schema at the floor vs. 19 fields currently — the
  foreign-investor and dealer sub-splits were added later, exact date not pinned). TPEx data
  starts sometime in the second half of 2014, with a column-count schema change (17→25
  columns) sometime between 2018-01-02 and 2020-01-02. A historical backfill implementation
  needs to handle multiple schema eras per market. Full detail, including the exact TPEx
  `tables[]` parsing gotcha (the populated table's index is not fixed) and the TWSE/TPEx
  non-trading-day response shapes, is in the submodule's `docs/institutional-sources.md`.

**Priority**: institutional data ranks below price data quality and future
financial-statement / industry-trend signals in the project's roadmap: it is useful context,
but its correctness is not gated in a first version (see Non-Goals) the way price data is.
Implement this change after the shared fetch/crawler foundation lands, not in parallel with
it — that foundation has now landed, so this change is unblocked to start, pending its own
open questions (task 1.1/1.2 endpoint research) being answered first.

## Goals / Non-Goals

**Goals:**

- Reuse `fetch_corporate_actions.py`'s idempotent-upsert and raw-range-tracking pattern for
  storage, and consume the shared `shp_utils/official_api.py` HTTP fetch/retry/backoff helpers
  that `add-official-daily-price-source` now provides, rather than inventing a new fetch
  architecture or a second retry/backoff implementation.
- Keep the engine change strictly opt-in so this is safe to merge without touching any
  existing backtest result.
- Make backfill and daily incremental fetch both possible from the same module.

**Non-Goals:**

- No intraday or real-time institutional flow data.
- No strategy logic — that is future work once the data exists locally.
- No UI in this change (Phase 5's universe work and Phase 6's dashboard v2 are separate).
- No independent verification of vendor-published institutional figures against a second
  source in a first version — unlike price data (where a Shioaji/official cross-check is a
  priority), institutional-data correctness is not gated here; price data quality and future
  financial-statement / industry-trend signals rank higher in the project's priorities.

## Decisions

**1. New standalone SQLite database (`institutional.sqlite`), not a table added to
`corporate_actions.sqlite`.**
Institutional data is conceptually distinct (daily flow data vs. discrete corporate events)
and has a different, much higher row-count growth rate (every trading day × every symbol,
vs. corporate actions which are sparse per symbol). Alternative considered: add a table to
the existing corporate-actions DB — rejected to keep each database's growth and backup
characteristics independent, matching this project's existing "flat CSV / separate SQLite
per concern" convention.

**2. TWSE T86 + TPEx equivalent as the sole source, no fallback.**
Both are official, free, and stable enough that a yfinance-style fallback (as exists for
dividends) is not needed for a first version. Alternative considered: also support FinMind
as a fallback source — rejected as unnecessary complexity for a first version; can be added
later if TWSE/TPEx availability becomes a problem.

**3. Engine join is opt-in via an explicit parameter, not automatic.**
`DataLoader` gains a method (e.g. `attach_institutional_data(df, codes)`) that callers
invoke explicitly; `load_all()`/`load_symbols()` do not call it automatically. This
guarantees zero behavior change for any existing strategy or task unless a strategy author
explicitly requests the join. Alternative considered: always join when the database exists
— rejected because it would silently change `on_bar()` snapshot shape for every existing
strategy the moment the database is populated, which is exactly the kind of hidden behavior
change this project's engineering discipline avoids.

## Risks / Trade-offs

- [Risk] TWSE/TPEx open-data endpoint formats or availability could change → Mitigation:
  isolate parsing in one module (mirroring `fetch_corporate_actions.py`'s structure) so a
  format change is a localized fix.
- [Risk] Daily fetch adds another step to `run_daily.py` that could fail and block the
  pipeline → Mitigation: institutional fetch failure must not abort price/corporate-action
  steps; log and continue, matching the existing per-step isolation pattern.
- [Risk] Growing row count (every symbol × every trading day) could bloat the SQLite file
  over years → Mitigation: acceptable at this project's scale (a few thousand symbols ×
  ~250 trading days/year is well within SQLite's comfortable range); revisit only if it
  becomes a measured problem.

## Migration Plan

- Purely additive: new file, new database, new opt-in method. No existing code path is
  modified except adding one more (isolated, failure-tolerant) step to `run_daily.py`.
- Rollback: stop calling the fetch step in `run_daily.py`; delete
  `institutional.sqlite` if desired. No other component depends on its existence.
