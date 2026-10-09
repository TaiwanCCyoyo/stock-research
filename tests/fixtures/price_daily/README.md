# price_daily.parquet contract fixture

The data producer, `stock-data-downloader`, builds `price_daily.parquet`; Stock only reads it.
`tests/test_build_price_parquet.py` checks Stock's side of that contract: `DataLoader` reads
this file exactly like the same bars written as `{code}_day.csv`, and handles stale CSVs.
It never runs producer code, so Stock's tests and CI do not need the submodule checked out.
Whether the producer builds the file correctly is tested in the producer's own repository.

| file                  | content                                                             |
| --------------------- | ------------------------------------------------------------------- |
| `rows.json`           | the bars, per stock code; the tests write the same bars as day CSVs |
| `price_daily.parquet` | what the pinned producer built from `rows.json`                     |
| `regenerate.py`       | rebuilds the parquet with the checked-out producer submodule        |

Generated with `stock-data-downloader` at commit `8795859` (the submodule pin at the time),
with no `official_daily.sqlite`, so every row has `Source = shioaji`.

## When to regenerate

Regenerate when the producer changes the parquet's columns or semantics, or when `rows.json`
changes:

```
git submodule update --init stock-data-downloader
uv run python tests/fixtures/price_daily/regenerate.py
```

Then update the commit above and commit the new parquet together with any `rows.json` change.
`test_fixture_parquet_holds_exactly_the_fixture_rows` fails if the two drift apart.
