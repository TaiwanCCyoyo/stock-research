## 1. Research source endpoints

- [x] 1.1 Confirm the exact TWSE T86 open-data endpoint URL, response format, and rate
      limits. **Confirmed**: `www.twse.com.tw/rwd/zh/fund/T86?date=YYYYMMDD&selectType=ALLBUT0999&response=json`
      (the `openapi.twse.com.tw/v1/fund/T86` host named in an earlier draft is a 404). Use
      `selectType=ALLBUT0999`, not `ALL` (which includes ~13k warrant rows). Rate limits were
      not independently measured for this endpoint; probing (~40 requests across both markets)
      used the price side's ~2.5s/request throttle without triggering any observed limiting,
      but that is not a confirmed ceiling — treat it as a safe starting point, not a verified
      limit.
- [x] 1.2 Confirm the equivalent TPEx open-data endpoint URL and response format for OTC
      symbols. **MUST explicitly answer**: does TPEx publish a per-symbol, date-ranged
      institutional-flow history endpoint (like TWSE's `STOCK_DAY`-style history), or only a
      latest-day snapshot? **Confirmed: yes, TPEx has a dated whole-market history endpoint** —
      `www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date=YYYY/MM/DD&response=json`
      (use `sect=EW`, not `AL`, for the same warrant-exclusion reason as TWSE's
      `ALLBUT0999`). This reverses the assumption inherited from the price-side finding
      (`backfill_official_history.py:5-7`, which found no dated endpoint) — that gap does
      not apply to institutional data. 2.3/2.5's TPEx path supports full historical backfill,
      not just daily increments.
- [x] 1.3 Document both in a short reference note near the fetcher module (mirroring how
      `fetch_corporate_actions.py`'s sources are documented). **Done**: written as
      `docs/institutional-sources.md`; merged to submodule `main` on 2026-08-26 and relied on by
      the delivered TPEx parser.

## 2. Fetcher and storage

> Delivered in the `shioaji_stock_prices` submodule as `scripts/fetch_institutional.py`
> (828 lines) with `tests/test_fetch_institutional.py`, merged to submodule `main` in
> `2ed8e4c` on 2026-08-26. Verified against the live endpoints, not only fixtures.

- [x] 2.1 Design the `institutional_daily` table schema (PK `date, code`; foreign/trust/
      dealer net + gross buy/sell columns) in `shioaji_stock_prices/fetch_institutional.py`.
- [x] 2.2 Implement the TWSE T86 fetch path with idempotent upsert and a raw-range tracking
      table, consuming the shared `shioaji_stock_prices/shp_utils/official_api.py` helpers
      (`fetch_json_with_retry`, `parse_int`, `parse_number`, `parse_roc_compact_date`) rather
      than re-implementing HTTP fetch/parsing, per `add-official-daily-price-source`'s shared
      foundation.
- [x] 2.3 Implement the TPEx equivalent fetch path with the same key, using the same shared
      `official_api.py` helpers. TPEx's response schema is positional, not name-keyed (the
      same Chinese header repeats across category groups), and the populated entry in its
      `tables[]` array is not at a fixed index — see `docs/institutional-sources.md` for the
      exact parsing approach before hardcoding column offsets. Supports both daily-increment
      and historical backfill (see 2.5).
- [x] 2.4 Rely on `shp_utils.official_api.fetch_json_with_retry`'s built-in retry/backoff for
      all HTTP calls instead of adding a second retry/backoff implementation.
- [x] 2.5 Add a daily-incremental entry point and a historical backfill entry point, **both
      markets** (confirmed feasible for TPEx too by task 1.2). The backfill MUST follow the
      throttle/checkpoint/backoff **structure** of
      `shioaji_stock_prices/backfill_official_history.py` (rate-limited, resumable, bounded
      per-run) but MUST NOT import or extend that module directly: T86/TPEx are daily
      whole-market endpoints, not `backfill_official_history.py`'s per-symbol
      `(code, year_month)` shape, so this fetcher's checkpoint unit is `(market, date)` for
      both markets. Historical range: TWSE from 2012-05-02 (exact, confirmed floor); TPEx
      from approximately mid-to-late 2014 (narrowed but not pinned to an exact day — see
      `docs/institutional-sources.md`). Handle the schema-era transitions noted in
      `design.md` (TWSE 12→19 fields, TPEx 17→25 fields) when parsing older dates.
- [x] 2.6 Add tests: idempotent re-fetch produces no duplicates; a fixture response is
      parsed into the expected row shape for both TWSE and TPEx paths.

## 3. Daily pipeline integration

> Delivered in the same submodule merge. `run_daily.py` is ten steps now; institutional is
> step 7, between monthly revenue and the value-chain refresh.

- [x] 3.1 Add an institutional-fetch step to `run_daily.py`'s sequence, isolated so its
      failure does not abort price/corporate-action steps.
- [x] 3.2 Add a test (or manual check) confirming a simulated institutional-fetch failure
      logs and continues rather than aborting the daily run.

## 4. Opt-in engine access

- [ ] 4.1 Add a method on `DataLoader` (e.g. `attach_institutional_data`) that joins
      institutional columns onto a price DataFrame only when explicitly called.
- [ ] 4.2 Confirm `load_all()`/`load_symbols()` do not call this method automatically.
- [ ] 4.3 Wire the joined fields through to `StrategyBase.on_bar()` snapshots when the
      caller has opted in.
- [ ] 4.4 Add a regression test proving a default (non-opted-in) backtest run's
      `summary.json` is byte-identical to the pre-change baseline.
- [ ] 4.5 Add a test proving the opted-in join produces expected fields, including `null`
      handling for dates with no institutional data.

## 5. Validation

> Not started as a gate for this change. `uv run python -m pytest tests/ -q` and the
> repository's ruff hooks pass in the submodule for the sections 2-3 work (242 tests at
> `5fdffee`), but 5.1-5.5 are written to gate the whole change including section 4's engine
> access, so they stay open until that lands and are then run once over everything.
> 5.3 is genuinely outstanding: the delivered rows were checked for internal consistency
> (the foreign/trust/dealer components sum to the three-institution net for 2330 on
> 2026-08-26) but not against an independent public source.

- [ ] 5.1 Run `uv run python -m pytest tests/ -q` — all tests green.
- [ ] 5.2 Run `uv run ruff check` on new/changed files.
- [ ] 5.3 Manual E2E: backfill a small date range for a few symbols, inspect
      `institutional.sqlite` contents for plausibility against a known public source.
- [ ] 5.4 Re-run `tasks/sample` with default parameters and diff `summary.json` against the
      pre-change baseline — MUST be byte-identical (opt-in only).
- [ ] 5.5 Note any skipped Docker-backed verification with a reason.
