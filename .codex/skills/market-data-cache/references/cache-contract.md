# Cache Contract

## Daily Prices

`stock-data-downloader/data/price_daily.parquet` has capitalized columns: `Code`,
`Date`, `Open`, `High`, `Low`, `Close`, `Volume`, precomputed `SMA5/10/20/60` and
`EMA5/10/20/60`, plus `Source`. Cast `Code` to string before comparison.

`Volume` is lots, not shares. One Taiwanese lot is 1,000 shares, so:

```text
turnover_in_thousands_of_TWD = Close * Volume
```

Owner update 2026-10-08: the producer's historical SMA/EMA columns and
technical_features are deprecated compatibility data, not definitions for new
research. Stock's explicitly versioned price/indicator cache is described in
`docs/en/research-derived-data.md`. Do not silently substitute its gap-reset
calculations for a historical task's input columns.

As a sanity anchor, `2330` commonly has `Close * Volume` around 70,000,000 on that
scale, or about NT$70 billion. Read only required Parquet columns: as measured on
2026-08-30 the file had 6,529,072 rows, 2,070 symbols, and 4,082 dates covering
2010-01-04 through 2026-08-28.

## The Cache Is Built From Official Data Since 2026-08-30

The Parquet is no longer derived from the Shioaji `{code}_day.csv` files. It is built
from `official_daily.sqlite`, the exchange-published daily artifact, with those CSVs
used only where official data does not cover a symbol or date. That is why it reaches
2010 instead of 2018-12-07, and why every row carries `Source`, valued `official`
(6,346,645 rows) or `shioaji` (182,427).

Stored results produced before that date are not comparable with later ones. Closes did
not move: the median absolute difference across 3.28 million overlapping rows is
0.0000%. Volume did. TWSE's official figures include odd-lot trading, so they run
**+0.24% in 2018 rising to +1.46% in 2026** above the previous Shioaji-derived values.
This is a drift, not a fixed offset, and it tracks the growth of odd-lot trading. TPEx
values are unchanged, because its history feed publishes the round-lot session and
already matched the Shioaji figures share for share.

There is no round-lot-only TWSE source with history, so this is a floor rather than an
oversight. `TWT53U` would allow `STOCK_DAY - TWT53U` but only from 2020-10-26. What is
guaranteed instead is that each market is internally consistent through time, which is
the property a momentum or volume-surge rule depends on.

### What `Source` Distinguishes

- 50 symbols are `shioaji` throughout, including `001`, the market index, for which no
  official daily series exists. They begin in 2018-12 while the rest begin in 2010.
  That shape is intended and is not a defect.
- 307 further symbols are mixed, and their `shioaji` rows are the emerging-board period
  before each stock listed. `symbol_meta.listed_date` matches the date official coverage
  begins exactly. Official TWSE and TPEx quotes cannot cover a stock that has not listed.
  Those rows are real trading history and are retained, but they come from a different
  market with different mechanics. Filter on `Source` when a study should not mix them.

### Start Long-History Studies At 2013-01-01

The cache reaches 2010-01-04, but the corporate-action index does not reach back equally.
Capital reductions begin in 2011 for TWSE and 2013 for TPEx. They are rare, roughly 25
per market per year, and their price factors are large: a median of 1.687 and an observed
maximum of 40.0. A missing one manufactures a price jump that no downstream filter
survives.

Counting day-over-day moves of 40% or more and asking whether a corporate action explains
each one:

| window          | explained | unexplained | unexplained share |
| --------------- | --------- | ----------- | ----------------- |
| 2010-2012       | 21        | 58          | 73%               |
| 2013 to 2018-12 | 115       | 10          | 8%                |
| 2018-12 onward  | 149       | 70          | 32%               |

The newly available 2013-2018 window is therefore the cleanest era in the artifact, and
the three years before it are the worst. Take the extra history down to 2013 and stop
there unless a study explicitly does not depend on corporate actions.

### Bar-Count Filters Admit A Different Set

This is the effect that changes which symbols a study examines rather than the size of a
number:

| whole-history filter | before 2026-08-30 | after |
| -------------------- | ----------------- | ----- |
| at least 750 bars    | 1,910             | 1,929 |
| at least 1,750 bars  | 1,600             | 1,722 |
| at least 2,500 bars  | 0                 | 1,483 |

Median bars per symbol moved from 1,869 to 3,974. Note the last row: the previous cache's
longest symbol had 1,872 bars, so any threshold above that admitted nothing at all. A
filter that appeared selective may have been silently empty.

`SMA60` near the previous start date is also no longer `NaN`. Across
2018-12-07 to 2019-03-31 it was `NaN` on 88.2% of rows and is now `NaN` on 5.9%, because
2010-2018 precedes those rows. A filter written as `SMA60.notna()` therefore admits about
eight times as many rows in that window.

### `{code}_min.csv` Is Deliberately Raw

Shioaji's kbar service returns bars for two Sundays the market never opened, 2024-12-01
and 2021-10-31, and a live re-query confirms it still does. They are filtered out on the
way into `{code}_day.csv`, so the daily CSVs and the Parquet are clean, but the minute
files still contain them. Resampling minute bars independently re-creates the phantom
trading day. The single Saturday in the cache, 2018-12-22, is a real TWSE make-up session:
exclude Sundays only, never weekends.

## Symbol Coverage And Survivorship

The cache is not limited to current survivors. As measured on 2026-08-30:

- 93 symbols had their last bar before 2026-08, including delisted or suspended names.
- 291 symbols first appeared after 2019-01-01, and 858 after 2011-01-01. Only 1,166 of
  2,070 reach the 2010-01-04 floor, so starting at the beginning of the data is the
  exception rather than the norm.

Survivorship bias in the cache's own shape therefore comes from the study's filter.
Underneath it, the official source is survivor-only for TWSE and survivorship-clean for
TPEx: the TWSE backfill draws its universe from codes already present in the artifact, so
a company delisted before this pipeline began fetching was never available to include, at
any depth. The cache inherits the TWSE side of that.
A whole-history minimum-bar filter removes listings and delistings inside the window.
Ranking research needs point-in-time eligibility: sufficient history and trailing
liquidity as of the evaluated date. `tasks/20260823-rotation-universe/eligibility.py`
implements that form, and `verify_eligibility.py` guards against future reads.

## Symbol Metadata

`symbol_meta.sqlite` has one table, `symbol_meta`, with columns `code`, `name`,
`isin`, `listed_date`, `market`, `industry_category`, `is_etf`,
`security_category`, `cfi_code`, and `fetched_at`. On 2026-08-23 it contained about
2,321 rows.

`market`, `industry_category`, and `name` contain Chinese strings. Read distinct
values from the table before filtering instead of typing an assumed literal that may
silently match nothing.

Official `industry_category` cannot represent a market theme reliably. It is too broad
for passive components or probe cards, leaks memory names across categories, and splits
satellite-related names across several categories. Derive a tradable cohort from returns
available through date _t_ rather than applying today's concept-stock labels to history.

Metadata lists roughly 351 ETFs, but only `0050` had cached price history as of
2026-08-30. The inverse and leveraged ETFs `00632R` and `00631L` have no bars, so
foreign-market lead hypotheses are not testable from metadata alone.

A TAIEX series does exist: `001`, with 1,844 bars from 2019-01-23. Older guidance said
otherwise, and for eight months that was accidentally true, because a contract-lookup bug
stopped `001_day.csv` at 2025-12-15. It was fixed and backfilled on 2026-08-28. Prefer
`001` over `0050` where the index itself is wanted: it needs no split adjustment, and
`0050` split four-for-one on 2025-06-18.

## Signal And Execution Prices

The loader exposes adjusted signal prices and raw execution prices as `SignalClose` and
`RawClose`, with `CorporateActionTypes` and `SignalPricePolicy`. Size positions from the
execution price. Sizing from adjusted prices systematically over-allocates dividend-heavy
names.

The corporate-action index has three vintages, and the first two are comparability
boundaries. Check each stored result's `generated_at`.

- **2026-08-17**: TWSE backfilled to 2018. The observed difference reached +28% of
  `total_pnl` on dividend-heavy baskets.
- **2026-08-29**: TPEx and OTC indexed for the first time. Coverage of the backtest
  universe moved from 1 of 891 OTC symbols to 850 of 891, against 97.3% for listed
  symbols. Before this an OTC ex-dividend drop was read as a real decline, because no row
  existed to adjust it away. Any stored backtest touching OTC names predates that fix.
- **2026-08-29, same day**: deep backfill to each endpoint's floor. The index now holds
  32,584 rows over 2,521 codes from 2003-05-05.

The two exchanges use different words for the same events, which is the trap that cost the
most: `除權`/`除息`/`除權息` on TPEx against `權`/`息`/`權息` on TWSE, and `現金減資`
against `退還股款`. A classifier written against one market's vocabulary silently yields
`UNKNOWN` or a degraded event type for the other.

## Backtest Summary Semantics

Values under `summary.json.metrics` are percentages, not fractions. For example,
`return_rate: 5.09` means +5.09%, not 509%.

`closed_trade_count` counts sell events, not positions. A scale-out strategy can emit
several sells per position. Use `buy_count` only when the strategy cannot add, or reconstruct
positions with `tasks/20260821-2b-entry-decomposition/mae_analysis.py`.

Under `--capital-mode unconstrained`, the CLI intentionally nulls `return_rate` and
`max_drawdown_rate`: without a cash gate, account-level returns are not meaningful. Use
that mode for signal quality such as expectancy, payoff, and profit factor. Use `shared`
for account-level values and acknowledge that symbols then compete for capital.

Pooling across symbols is exact under `unconstrained` because sizing uses a fixed fraction
of constant initial cash and symbols do not interact. It is not exact under `shared`.

## Universes And Task Artifacts

`universes/<name>.json` is shaped as `{"name", "description", "codes"}` and is passed as
`--codes @<name>`. Record the construction rule in `description`; a bare ticker list is not
reproducible or falsifiable later.

Under `tasks/`, ignore rules admit only established artifact names. Reuse
`universe_build_report.json` for a universe manifest rather than inventing a filename that
may remain silently ignored.

## Performance Anchors

`DataLoader` indexes prices once per symbol through `_price_by_code`, and
`BacktestEngine` keeps per-symbol date-to-row maps. A 400-symbol one-year run improved from
634 seconds to 51 seconds after these indexes were introduced. If performance regresses,
look first for a newly introduced scan of the full frame inside a per-symbol or per-bar loop.

Snapshot rows passed to `on_bar` are plain dictionaries. Dictionary access such as
`row["Close"]` and `row.get("Volume", 0)` works; pandas `Series` methods do not.
