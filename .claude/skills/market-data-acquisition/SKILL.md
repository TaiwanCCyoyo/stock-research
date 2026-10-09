---
name: market-data-acquisition
description: How to add or extend a market-data source in the stock-data-downloader pipeline without shipping a silently wrong artifact - probing an endpoint for its observed values before writing a parser, measuring whether two feeds actually agree, and the seam that appears whenever a daily bulk fetch and a historical backfill write the same rows. Use this whenever work involves writing or changing a fetcher, backfiller, or normalizer for TWSE/TPEx data, wiring a new step into run_daily.py, backfilling history for any source, or explaining why two sources disagree about the same day - including when the request is just "add the institutional data", "backfill X further back", "why is the volume different", or "the endpoint changed shape again". The failures this prevents do not raise exceptions; they produce plausible numbers.
---

# Market data acquisition

This skill is about _writing_ into `stock-data-downloader/data/`. For _reading_ those
artifacts correctly, use `market-data-cache` instead.

Every failure catalogued here was found in production, and none of them raised an
exception. They produced numbers that looked fine. That is the thing to hold onto: in this
domain, correctness is something you measure, not something you notice.

The hard constraints live in `.claude/rules/common/data-structures.md` (never destroy data,
check the download schedule, never kill processes indiscriminately). This skill is the
method, not the rules.

## Probe before you parse

The strongest temptation when adding a second market is to write its normalizer against
the first market's. `add-tpex-corporate-actions` planned exactly that — its proposal said
the TPEx bulletins "map onto the existing normalizer almost one-to-one". The columns did.
The values in them did not, and one query per field would have shown it:

| what the plan assumed      | what the endpoint actually returns                           | cost if shipped                                                                               |
| -------------------------- | ------------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| `減資原因` = `退還股款`    | `現金減資`                                                   | 30% of rows degraded to a generic event type                                                  |
| `權/息` = `權`/`息`/`權息` | `除權`/`除息`/`除權息`                                       | **100%** of 3,096 rows classified `UNKNOWN`                                                   |
| dates parse like TWSE's    | compact 7-digit ROC (`1020116`)                              | `SystemExit`, which `except Exception` does not catch — one row would end the whole daily run |
| the declared floor is real | `twtauu` returns nothing before 2011 despite a 2003 constant | a no-argument run asks a 2021-floor endpoint for 2003                                         |

So: **enumerate the observed values before writing the mapping.** Query the live endpoint
across several years, collect the distinct values of every field you plan to branch on, and
write the mapping from what came back. It takes minutes and it is the difference between a
review that catches nothing and one that has nothing to catch.

Two corollaries worth stating because both have bitten this repo:

- **Never key a field mapping off the field _count_.** The TPEx price endpoint had two
  17-field eras that differed only in a column nobody read; a count could not tell them
  apart and the crawler failed on every date in the middle era. Read by field _name_ and
  fail loudly on an unrecognized signature.
- **Never infer a schema from a response with no rows.** `exDailyQ` returns a different,
  older 22-field list when empty. That list is also a real era, so "empty responses are
  weird" is the wrong lesson — the right one is that an empty response is not evidence.

## When two feeds write the same rows

This is the failure mode that is hardest to see and most expensive to leave. An artifact
fed by both a daily bulk fetch and a historical backfill has it by construction.

**They may not publish the same quantity.** Measured on `official_daily_price`:

| feed              | what it counts         | vs the Shioaji-derived cache                   |
| ----------------- | ---------------------- | ---------------------------------------------- |
| TPEx history page | round-lot session only | **1.0000**, exactly equal on 92–94% of rows    |
| TPEx nightly bulk | also odd-lot trading   | 1.0180                                         |
| TWSE `STOCK_DAY`  | also odd-lot trading   | 1.0074, drifting +0.24% (2018) → +1.46% (2026) |

Note what makes that credible: TPEx is 1.0000 in _every single year_, so the TWSE gap is a
definition difference rather than noise. Measure the overlap per segment and report a
median ratio plus an exactly-equal share — one number alone cannot separate the two.

**They share a primary key, so whichever ran last owns the row**, and nothing in the row
says which one that was. This is where the trap closes: a backfill that selects only _gaps_
— days the artifact has no rows for — will never revisit a day the bulk already wrote. TPEx
was history-written through 2026-08-06 and bulk-written every day after, so its volume
changed definition on 2026-08-07 and would have stayed changed forever, on the newest data,
growing by one day per day.

**Select re-fetch work from the checkpoint table.** A day with rows but no settled
checkpoint was written by the other feed. That beats sniffing the stored response's field
signature: no JSON parsing, no schema change, and it survives the endpoint changing shape
again.

```sql
SELECT DISTINCT date FROM official_daily_price WHERE market = 'TPEx'
EXCEPT
SELECT period FROM official_history_raw_ranges
WHERE market = 'TPEx' AND status IN ('ok', 'empty')
```

## Checkpoint semantics

`official_history_raw_ranges` carries `(market, code, period, status, row_count)`. The
status is what stops a unit being re-asked forever, so getting it wrong is either an
infinite request loop or a permanently stranded day.

| status    | meaning                          | re-asked? |
| --------- | -------------------------------- | --------- |
| `ok`      | fetched, rows stored             | no        |
| `empty`   | asked, answered, nothing there   | no        |
| `partial` | the period has not fully elapsed | yes       |
| `error`   | the fetch failed                 | yes       |

**An empty response must not settle a re-fetch.** These endpoints answer "not published
yet" with a successful empty, indistinguishable from a genuine absence. For a _gap_ day
that settles correctly — the market demonstrably traded, so re-asking will not help. For a
day the artifact already holds rows for, settling strands it on the other feed's values
permanently, on today's date, every day. The rule that separates them:

```python
complete = bool(rows) or not already_had_rows
```

Legacy rows exist with `status='ok'` and `row_count=0`, written before `empty` was
introduced. Both count as settled so behaviour is correct; only the label misleads. Leave
them — rewriting settled checkpoints to relabel them is the kind of in-place edit the data
rules exist to prevent.

## Order the daily run so a cache is built after its inputs

`run_daily.py` is the one-click flow and its step order is load-bearing. A derived artifact
rebuilt _before_ the fetch that feeds it takes its newest row from the fallback source and
flips to the primary one on the next run — the same definition seam as above, one layer up,
on the freshest bar of every symbol, once a day.

`build_price_parquet` sits after `fetch_official_daily_price` for exactly this reason. When
adding a step, ask what reads what, and put the reader later.

## Registering a source

`fetch_corporate_actions.py` is the worked example of a multi-market fetcher. A source is a
`SourceConfig` carrying everything that differs per endpoint, so nothing is a module-level
constant that a second market would have to fight:

- `market`, `base_url`, `path`
- `payload_shape` — TWSE returns `fields`/`data` at the top level; TPEx nests them under
  `tables[0]`
- `date_param_format` — TWSE wants `YYYYMMDD`, TPEx wants `YYYY/MM/DD`
- `first_date` — the endpoint's own floor, so a no-argument run does not ask for years it
  cannot answer for
- `implied_event_type` — for endpoints where the _endpoint_ is the event type because no
  column says which it is

Classifiers gain the new market's vocabulary rather than being replaced. Removing the old
spellings silently reclassifies everything already indexed.

Raw responses go to `data/raw/<market-lowercase>/<source>/`. Registered-but-unobserved
sources — ones that answer correctly with zero rows across their whole window — stay
registered and keep being queried. Zero rows is not proof the event never happens.

## Before declaring it done

Measure, and say the number. The pattern that has repeatedly caught real problems:

1. **Fetch one real period and hand-check it against the stored raw response.** Pick one
   row per distinct vocabulary value. For a price factor, confirm
   `previous_close * price_factor` reproduces the published reference price — that check
   found 1,250 of 1,250 rows correct and would have failed loudly on a mis-mapped column.
2. **Count what a downstream quality metric says, before and after, with a control.** Use
   extreme moves (`|return| >= 40%`), not the raw mismatch total, which is dominated by
   ordinary limit-up/down days. The control is what makes the result attributable: when
   TPEx corporate actions were added, OTC extreme gaps fell 115 → 39 while listed symbols
   — already 97% covered — stayed at 24, unchanged by a single event.
3. **State the comparability boundary.** Any change to acquisition means stored results
   from before it are not comparable. Say which artifact, which direction, and how much.
4. **Check what a coverage change does to _which_ symbols a study sees**, not just to the
   numbers. Extending history from 2018 to 2010 moved a 1,750-bar filter from 1,600 to
   1,722 symbols and a 2,500-bar filter from 0 to 1,483. That axis matters more than a
   percentage drift, because it changes the population rather than a measurement.

## Related

- `.claude/rules/common/data-structures.md` — the hard constraints and the download schedule
- `skill: market-data-cache` — reading the artifacts this produces
- `stock-data-downloader/AGENTS.md` — the pipeline's own entry points and invariants
- `stock-data-downloader/docs/tpex-history-sources.md` — probe evidence for the TPEx endpoints
