---
name: market-data-cache
description: How to read this repo's Taiwan market data correctly - price_daily.parquet column names, units and its Source column, official_daily.sqlite which now feeds it, symbol_meta.sqlite, which symbols and dates each artifact does and does not contain, and how to read a run summary's metrics. Use this whenever a task involves querying prices, volumes, turnover, industry categories, ETFs, the TAIEX/market index, listing or delisting coverage, survivorship bias, building or filtering a universe, or interpreting numbers out of a backtest summary.json - including when the request just says "check how liquid X is", "how many symbols do we have", "how far back does our data go", "can we backtest from 2010", "is 2330 in the data", or "what did that backtest return". The units, column names and the gap between official coverage and backtestable coverage are not guessable and several of them have already produced silently wrong answers.
---

# Market data cache

Everything the backtests read lives in `stock-data-downloader/data/`, which this repo
**consumes and never writes** (the submodule owns acquisition). The facts below were
measured, not assumed, and most of them are the kind that fail silently rather than
loudly — a wrong unit gives you a plausible number, not an exception.

Before restructuring or adding to any of these artifacts, read
`.claude/rules/common/data-structures.md`: there is a long-running download schedule that
must not be collided with.

## price_daily.parquet

**Columns are capitalised.** `Code`, `Date`, `Open`, `High`, `Low`, `Close`, `Volume`, plus
precomputed `SMA5/10/20/60` and `EMA5/10/20/60`. Asking pyarrow for `code` or `date` raises
`ArrowInvalid: No match for FieldRef.Name(code)` — that one at least fails loudly. Cast
`Code` with `.astype(str)` before comparing; codes are strings like `"2330"` but joins from
other sources arrive as ints often enough to be worth the habit.

**`Volume` is lots, not shares.** A Taiwanese lot is 1000 shares, so:

```
turnover_in_thousands_of_TWD = Close * Volume
```

Sanity anchor: 2330 runs around `Close * Volume` = 70,000,000 on that scale, i.e. about
NT$70bn of daily turnover. If a liquidity floor you are picking implies that a mid-cap
trades NT$20,000 a day, the unit is wrong, not the stock.

Scale as of 2026-08-30: **6,529,072 rows, 2,070 symbols, 4,082 dates, 2010-01-04 to
2026-08-28.**

**The cache is built from the official artifact now, not from Shioaji.** That happened on
2026-08-30 and it is why it reaches 2010 instead of 2018-12-07. Every row carries a
**`Source`** column, `official` (6,346,645 rows) or `shioaji` (182,427).

**Numbers moved, and stored results are not comparable across that date.** Closes did not
(median difference 0.0000%). Volume did: TWSE's official figures include odd-lot trading and
run **+0.24% in 2018 rising to +1.46% in 2026** above the old Shioaji-derived values -- a
drift, not an offset, tracking the growth of odd-lot trading. TPEx is unchanged: its history
feed is the round-lot session and matched Shioaji share for share all along.

**Its trading days match the exchange's own exactly** -- no parquet date is absent from
`official_daily.sqlite`. That was not true before 2026-08-29: Shioaji's kbar service returns
bars for two Sundays the market never opened (2024-12-01 and 2021-10-31, 255 and 18 symbols),
and it still does -- a live re-query confirmed them byte-identical. They are filtered out on
the way into `_day.csv`, so anything you read from `_day.csv` or the parquet is clean, but
**`{code}_min.csv` is deliberately left raw and still contains them**. Resample minute bars
yourself and you will re-create the phantom day. The one Saturday in the cache (2018-12-22)
is a real TWSE make-up session (補行交易日) -- never filter weekends, only Sundays.

### Start a long-history study at 2013-01-01, not 2010

The cache reaches 2010-01-04, but the corporate-action index does not reach back equally:
capital reductions begin 2011 (TWSE) and 2013 (TPEx). They are rare, roughly 25 a year per
market, and their price factors are enormous -- median 1.687, observed max 40.0 -- so a
missing one manufactures a price jump nothing downstream survives.

Measured, by counting day-over-day moves of 40% or more and asking whether a corporate
action explains each one:

| window          | explained | unexplained | unexplained |
| --------------- | --------- | ----------- | ----------- |
| 2010-2012       | 21        | 58          | **73%**     |
| 2013 to 2018-12 | 115       | 10          | **8%**      |
| 2018-12 onward  | 149       | 70          | 32%         |

So the newly available 2013-2018 window is the **cleanest era in the artifact**, and
2010-2012 is the worst. Take the extra history down to 2013 and stop there unless a study
specifically does not care about corporate actions.

### What `Source` tells you

- **50 symbols are `shioaji` throughout**, `001` among them -- there is no official daily
  series for the market index. They start 2018-12 while everything else starts 2010. That is
  the intended shape, not a bug.
- **307 more symbols are mixed**, and the `shioaji` half is their **emerging-board (興櫃)
  period before they listed**: `symbol_meta.listed_date` matches the date official coverage
  begins exactly. Official TWSE/TPEx quotes cannot cover a stock that has not listed yet.
  Those rows are real trading history and are kept, but they are a different market with
  different mechanics -- filter on `Source` if a study should not mix them.

### Bar-count filters admit a different set now

This is the change that alters _which_ stocks a study looks at rather than by how much a
number moves:

| whole-history filter | before 2026-08-30 | after |
| -------------------- | ----------------- | ----- |
| `>= 750` bars        | 1,910             | 1,929 |
| `>= 1,750` bars      | 1,600             | 1,722 |
| `>= 2,500` bars      | **0**             | 1,483 |

Median bars per symbol went 1,869 to 3,974. Note the last row: the old cache's longest symbol
had 1,872 bars, so **any threshold above that used to admit nothing at all** -- a filter that
looked selective may have been silently empty.

**`SMA60` near the old start date is no longer NaN.** Over 2018-12-07..2019-03-31 it was NaN
on 88.2% of rows and is now NaN on 5.9%, because 2010-2018 sits behind those rows. A filter
written as `SMA60.notna()` therefore admits about eight times as many rows there.

**Read only the columns you need.** The file is ~3.4M rows; pulling every column to compute
one ratio is the difference between a second and a minute.

## Which symbols are in there

The cache is **not** a snapshot of today's survivors, and assuming it is leads to the wrong
conclusion about survivorship bias:

- 93 symbols have their last bar before 2026-08 -- delisted or suspended.
- 291 symbols first appear after 2019-01-01; 858 after 2011-01-01. Only 1,166 of 2,070 reach
  the 2010-01-04 floor, so "starts at the beginning of the data" is a minority, not the norm.

So survivorship bias in a study comes from **the filter, not the cache**. A whole-history
requirement like "at least 1750 bars" silently drops every company that listed or delisted
during the window -- and since 2026-08-30 it drops a different set than it used to, because
most symbols now carry roughly twice as many bars. A per-date rule (enough prior history _by
that date_, plus trailing liquidity) keeps both.
`tasks/20260823-rotation-universe/eligibility.py` implements the per-date form, and
`verify_eligibility.py` proves it reads no future bar.

That is the cache's own shape. Underneath it, **the official source is survivor-only for
TWSE and survivorship-clean for TPEx** -- see `official_daily.sqlite` below. The cache
inherits the TWSE side of that, so a company delisted before this pipeline began fetching
was never available to be included, at any depth.

That distinction matters much more for ranking than for timing. In a paired timing test both
arms see the same symbols and a survivor tilt largely cancels; a ranking study filtered to
survivors is asking a score to pick winners from a pool already filtered to winners.

## official_daily.sqlite -- the source the cache is built from

The exchange-published daily data (TWSE + TPEx), ~15.8GB, 2010-01-04 to now for both
markets, verified complete on 2026-08-29. **Since 2026-08-30 `price_daily.parquet` is built
from it**, so for most questions you want the parquet, not this file. Go to the sqlite when
you need something the parquet does not carry: turnover value, transaction counts, the
no-trade days the parquet excludes, or instruments outside the pipeline's 2,070-symbol
universe.

Reading it: open read-only with a `file:...?mode=ro` URI. Table `official_daily_price`
(`market, code, date, open, high, low, close, volume, value, transactions, close_missing`),
**volume in shares** -- not lots, unlike the parquet. From a worktree the file is excluded
from the data copy by design; resolve the main checkout via
`git rev-parse --path-format=absolute --git-common-dir`.

**Its survivorship properties are the opposite of what you would guess, and differ by
market.** The TWSE backfill takes its universe from codes already in the table
(`SELECT DISTINCT code ... WHERE market='TWSE'`), so it holds 1,380 _surviving_ codes and a
company delisted before this pipeline started is absent forever. The TPEx backfill fetches
the whole market per day, so it captures whatever was listed that day -- 49,733 distinct
codes, including long-gone warrants and delistings. **TPEx history is survivorship-clean;
TWSE history is not.** The parquet inherits the TWSE side of that.

**Volume has one definition per market, and they are not the same definition.** TPEx's
history feed is the round-lot session; TWSE's `STOCK_DAY` also counts odd-lot trading and so
runs about 1.5% higher and drifting. There is no round-lot-only TWSE source with history, so
this is a floor, not an oversight -- `TWT53U` would allow `STOCK_DAY - TWT53U` but only from
2020-10-26. What is guaranteed instead is that each market is internally consistent through
time, which is what a momentum or volume-surge rule actually depends on.

## symbol_meta.sqlite

One table, `symbol_meta`, with columns `code, name, isin, listed_date, market,
industry_category, is_etf, security_category, cfi_code, fetched_at`. About 2,321 rows, split
roughly 1,284 main-board / 1,009 TPEx / 28 innovation-board.

`market`, `industry_category` and `name` hold Chinese strings. Filter on values read back
from the table rather than on a literal you type -- a typed literal that is subtly different
matches nothing and returns an empty frame rather than an error.

**`industry_category` is the official TWSE/TPEx classification, and it cannot express a
theme.** It fails in both directions at once, so do not reach for it as a cohort definition
without saying which failure you are accepting:

| theme              | what the official categories do                                         |
| ------------------ | ----------------------------------------------------------------------- |
| passive components | all in one category — but that category holds dozens of unrelated names |
| probe cards        | all in semiconductors, pooled with TSMC and the IC designers            |
| memory             | mostly semiconductors, but 5289 sits in computer peripherals            |
| satellite-related  | spans optoelectronics, electronic parts and communications at once      |

Cohorts that match how the market actually moves have to be derived from returns. See
`docs/en/research-objective.md`.

**351 ETFs are listed in `symbol_meta`, but only one has price history in the cache** — and
it is `0050`, with 1,868 bars from 2018-12-07 to 2026-08-28. The inverse and leveraged ETFs
(`00632R`, `00631L`) have no bars at all, so "use a US-tracking ETF as a foreign lead signal"
is still unanswerable: the metadata exists and the prices do not.

**There IS a TAIEX series now — `001`, 1,844 bars from 2019-01-23 to 2026-08-28.** Older
guidance said there wasn't, and for eight months that was accidentally true: `001_day.csv`
stopped at 2025-12-15 because the download gate was written as `if "001" in
api.Contracts.Indexs.TSE`, and shioaji 1.2.9 keys that collection by `TSE001`, so the
membership test is permanently False while `.get("001")` still returns the contract. Fixed
and backfilled 2026-08-28. Prefer `001` over `0050` as a market proxy where you want the
index itself: it needs no split adjustment, whereas 0050 does (see below).

**0050 split 4-for-1 on 2025-06-18, and reading it unadjusted invents a crash.** On raw
`Close` it shows 2025 returning **-66.2%** with a **-77.2%** drawdown; the event is a
`price_factor` of 0.249987, and on total-return adjusted prices 2025 was **+38.1%**. Any
regime rule, drawdown measure, or benchmark that uses 0050 must run on adjusted prices, or it
will manufacture a bear signal on that one day. `tasks/20260823-selection-vs-random/book.py`
builds the adjusted series; the engine's own `SignalClose` handles splits but not the
dividend accretion a multi-year return needs.

## Prices are layered: signal vs execution

The loader emits both an adjusted signal price and a raw execution price
(`SignalClose` / `RawClose`, with `CorporateActionTypes` and `SignalPricePolicy` alongside).
The rule that matters when writing a strategy: **size positions off the execution price**,
because adjusted prices sit below raw prices by the dividends still to come, and sizing off
the signal price hands systematically larger positions to dividend-heavy names.

Corporate actions for 2018–2025 were all fetched on **2026-08-17**. Runs produced before
that date are not comparable with runs after it — the gap reaches +28% of `total_pnl` on
dividend-heavy baskets. Check `generated_at` in a stored summary before comparing against it.

## Reading a run summary

`summary.json`'s `metrics` are **percentages, not fractions**. `return_rate: 5.09` means
+5.09%, and `win_rate: 35.8` means 35.8%. Formatting one with `"{:.2%}"` produces `509%`,
which is the kind of number that gets quoted in a report before anyone checks it.

`closed_trade_count` counts **sells**, not positions, so a strategy that scales out reports
several "trades" per position. It is not a sample size. `buy_count` is the position count
when the strategy has no add path; otherwise reconstruct positions with
`tasks/20260821-2b-entry-decomposition/mae_analysis.py`.

Under `--capital-mode unconstrained` the CLI **nulls `return_rate` and
`max_drawdown_rate` on purpose** — there is no cash gate, so a return rate would be
meaningless. That mode is for signal quality (expectancy, payoff, profit factor); use
`shared` when you need account-level numbers, and remember those are contaminated by how
many positions the account could afford to hold at once.

## Universe files

`universes/<name>.json` is `{"name", "description", "codes"}` and is addressed as
`--codes @<name>`. Put the rule that produced the list into `description` — a bare list of
codes six months later is unfalsifiable.

Under `tasks/`, `.gitignore` ignores everything and re-admits a fixed set of filenames:
`*.md`, `*.py`, `report.html`, `sweep_results.json`, `benchmark_drawdown*.json`,
`buy_and_hold_*.json`, `universe_build_report.json`, `experiment.json`, `candidates/*.py`,
`params/*.json`. A JSON artifact you want committed has to be named one of those — pick
`universe_build_report.json` for a pool manifest rather than inventing a name that will be
silently dropped.

## Performance

`DataLoader` indexes prices by symbol once (`_price_by_code`) and `BacktestEngine` keeps a
per-symbol `date -> row` map. Both replaced full-frame scans that cost `symbols x rows` and
`symbols x bars^2`; a 400-symbol one-year run went from 634s to 51s. If a large-pool run is
unexpectedly slow again, look for a newly introduced per-symbol scan over the whole frame
before blaming the strategy — that shape is invisible at twenty symbols and fatal at a
thousand.

Snapshot rows handed to `on_bar` are plain dicts, so `row["Close"]` and `row.get("Volume", 0)`
work and Series methods do not.
