# Research Objective

For new studies, apply the [current goal text (2026-09-08)](research-goal.md) and
[owner contract](research-owner-contract.md) first: NT$2m, at most five holdings,
manual-execution resilience, revised cost preferences and measurement-first evidence.
The historical objective and study decisions below remain unchanged as evidence.
Their dashboard requirement, cost ceilings, rankings and old measurement verdicts
are not automatically current authority; consult the current contract and explicit
correction/exposure registry before designing a new study.

Recorded 2026-08-22, from the repository owner. This states what the strategy research is
_for_, what that implies for how studies must be built, and what result would say the
objective is out of reach. It is not a vision statement — every section below is meant to
be actionable when designing the next study.

## The objective

Hold a small number of Taiwanese equities that are about to move hard, rotating into them
as leadership shifts between themes — probe cards, memory, passive components, and
whatever leads next. Three qualifications, all of them stated by the owner and all of them
binding on the design:

- **Being wrong is acceptable.** The system does not need high hit rate. It needs the
  winners to be large enough to pay for the losers.
- **A continuous score is wanted, not a binary signal.** While waiting in a position that
  is going nowhere, the owner wants a number that says what to rotate into. The output of
  this research is a ranking, surfaced on the dashboard, not an alert.
- **Turnover is a hard constraint, not a footnote.** The stated failure mode is capital
  ground away by too much switching. Taiwan round-trip cost is roughly 0.44–0.6% (0.3%
  transaction tax plus fees both ways), so a strategy that rebalances its whole book
  twenty times a year burns something like 9–12% before it does anything else.

## Why this is a change of axis, not another strategy

Every study through `20260822` is **time-series**: for one symbol, decide when to be in and
when to be out, independently of every other symbol. `unconstrained` mode exists precisely
to remove interaction between symbols, and the six archetypes are six answers to "is _this_
stock moving?"

The objective above is **cross-sectional**: of N candidates, which K do I hold _right now_,
and when does a better candidate displace one I hold? No study so far contains any
competition between symbols, so none of them can answer it, and adding a seventh archetype
would not change that.

This is the reason to change direction. It is not that the prior work was wrong — it is
that it answers a different question.

## What carries over

The mechanism work produces the inputs a ranking system needs, and three of its findings
are directly load-bearing:

- **The six archetypes become candidate features.** Each is a detector for a different kind
  of "this is moving". A score is a combination of such detectors; the archetype studies
  measured how each behaves and on which sectors.
- **The moving-average scale-out costs about 80% of the return** (`20260821-2b-entry-decomposition`,
  6/6 paired, t = 2.25–5.66). Do not put a "sell half on a moving-average break" rule into a
  rotation design.
- **Risk is measured per position, with holding period beside it** (`mae_analysis.py`).
  Account-level drawdown is contaminated by deployment; see
  [[mae-position-risk-estimator]] and `20260822-ratchet-generalization` §3.

## Design consequences

These four follow from the objective and should be treated as settled constraints, not
re-litigated per study.

### 1. Rotation research runs under `shared` only, so aggregation must be re-specified

Top-K selection only exists when capital is constrained. Under `unconstrained` there is no
cash gate and position size is a fixed fraction of constant `initial_cash`, so "hold the
best 5" degenerates into "hold everything above a threshold". Rotation therefore has to run
in `shared`.

That forfeits the property every prior study leaned on: pooling across baskets is exact
under `unconstrained` and is _not_ exact under `shared`, because symbols compete for cash.
**Any rotation study must pre-register how its cells combine before running**, since they
cannot simply be summed.

### 2. The universe must be rebuilt, and the data is already there

The current `universes/*_liquid20.json` baskets take the twenty most liquid names in each of
five categories. Measured against the themes the owner named, that pool is unfit for ranking
research:

| theme                        | leaders in a universe | leaders absent               |
| ---------------------------- | --------------------- | ---------------------------- |
| probe cards / test interface | **0 of 5**            | 6223, 6510, 5217, 6515, 3131 |
| memory                       | 4 of 8                | 8299, 4967, 5289, 2451       |
| passive components           | 2 of 5                | 3026, 2478, 6173             |

The exclusion is **not** a data problem. Of the twelve absent names, eleven have price
history in `price_daily.parquet` and ten clear the `MIN_BARS = 1750` filter; only 5217 has
no data at all, and 6515 is about 108 bars short of the filter because it listed in 2019-11.

Cache-wide, 1,596 of 2,070 symbols clear the bar filter; 402 also clear a median daily
turnover of 100,000 units, and 606 clear 20,000. Current research uses about 100. The pool
can widen four- to six-fold using data already on disk.

Survivorship bias matters differently here than it did for timing research. For a two-armed
timing comparison both arms see the same symbols, so a survivor-tilted basket mostly cancels.
For **ranking** it is disqualifying: filtering to names with 1750 bars of history pre-selects
survivors and then asks the score to pick winners out of a pool already filtered to winners.
Universe construction is the first work item of this direction, ahead of designing any score.

### 3. Turnover is a pre-registered per-cell metric with a cost model

Every rotation study reports turnover per cell alongside return, and the acceptance rule has
the shape: **beats the benchmark after cost, at equal or lower turnover.** Without the
turnover clause, a parameter sweep will reliably surface a high-turnover winner that is a
cost artifact — and it would be the exact failure the owner asked to avoid.

### 4. The benchmark becomes deployment-matched, and buy-and-hold is retired as a gate

`stock_pool_buy_and_hold_return_rate` puts the full initial cash into an equal allocation
across the basket on day one and holds. A long-only strategy that is partly deployed and
sometimes flat cannot beat that in a bull window; the rule went 0-for-17 across three
studies, which is a property of the comparison rather than of the strategies.

Replacement: **a random-draw null matched on deployment.** Same number of positions, same
days invested, same turnover, selection drawn at random from the eligible pool, repeated
enough times to give a distribution; report the strategy's percentile against it. A single
naive rule is itself a strategy and can get lucky — a distribution is the actual null for
"does my ranking add anything".

Basket buy-and-hold stays in the tables as context, with no pass/fail gate attached.

## Evidence: the owner's own diagnosis, measured

The owner described the problem as three weaknesses: the stop-loss method is not good
enough, there is no way to choose among several qualifying candidates, and switching
between them grinds capital away in costs. Two of the three are confirmed and are larger
than stated; one is wrong in an important way. Measured on the 2024-01-01..2026-08-14
holdout.

### The exits give back everything on the median position

Maximum favourable excursion against realised return, per position:

| arm               | positions | median MFE | median realised |      MFE >= 20% | those peaks |  captured |
| ----------------- | --------: | ---------: | --------------: | --------------: | ----------: | --------: |
| S1 + ATR/channel  |     1,087 |      +6.5% |       **-3.0%** |     237 (21.8%) |      +36.1% |     42.4% |
| S1 + chandelier   |     1,201 |      +7.6% |       **-2.5%** |     262 (21.8%) |      +33.2% |     53.6% |
| S1 + box ratchet  |       973 |      +6.7% |       **-2.5%** |     224 (23.0%) |      +35.7% |     37.1% |
| S3 + ATR/channel  |       673 |      +7.2% |       **-3.3%** |     145 (21.5%) |      +37.6% |     44.5% |
| S3 + chandelier   |       716 |      +7.9% |       **-2.8%** |     141 (19.7%) |      +31.5% |     53.5% |
| S3 + box ratchet  |       622 |      +8.2% |       **-2.5%** |     151 (24.3%) |      +37.8% |     39.3% |
| 2B, scale-out on  |     1,215 |      +7.1% |           -1.3% | **137 (11.3%)** |      +27.1% | **20.4%** |
| 2B, scale-out off |     1,215 |      +7.0% |       **+0.6%** |     136 (11.2%) |      +27.2% | **64.3%** |

The typical position rises 6.5-8.2% at its peak and closes **negative**. Roughly one in
five reaches +20%, peaking around +31-38%, and the exit keeps 37-54% of that.

Two corrections to the owner's account fall out of this table. The 2B entry finds runners
at **half** the rate of a plain breakout (11.3% against 20-24%) and its runners peak lower,
so "2B plus dual moving averages can find the leaders" is true only in the weak sense.
And the moving-average scale-out is specifically a runner-killer: 20.4% of peak captured
with it on, 64.3% with it off, which sharpens the earlier finding that it costs about 80%
of the return.

### Selection, not timing, is the dominant lever

Across 606 symbols clearing the 1750-bar filter and a 20,000-unit median turnover floor,
counting how many satisfy S1's entry on the same day:

| percentile of trading days | simultaneous candidates |
| -------------------------- | ----------------------: |
| 10th                       |                      14 |
| 50th                       |                  **51** |
| 90th                       |                     105 |
| max                        |                     186 |

**96% of holdout trading days offer more candidates than a five-position book can hold**,
and only 1.3% of days offer none. At portfolio level the entry rule is not a filter.

What that choice is worth, measured as forward 20-day return among the candidates of each
signal day (581 days with at least ten candidates):

| pick                                 | median forward 20-day return |
| ------------------------------------ | ---------------------------: |
| random candidate (that day's median) |                   **-0.44%** |
| best five, in hindsight              |                       +33.1% |
| worst five, in hindsight             |                       -16.1% |
| **spread**                           |                   **~50 pp** |

The signal alone has no median edge; its value is entirely in the right tail, and which
candidate is held decides whether the tail is reached. The spread available to selection is
roughly a hundred times the 0.44-0.6 pp round-trip cost, so the owner's fear of churn is
well founded in direction but wrong in magnitude relative to the prize: capturing even a
small fraction of that dispersion outweighs the cost of trading.

The hindsight figures are an unreachable ceiling, not a target. They are recorded to answer
one question only -- whether ranking is worth researching at all -- and the answer is yes.

### What this reorders

Five studies have optimised the exit on a signal whose portfolio-level median outcome is
zero. The exit work was not wasted -- keeping 37% versus 64% of a runner's peak is a large
effect -- but it is the second lever. Selection is the first, and it is entirely unexplored.

## Cohorts and lead-lag

Added 2026-08-23, from the owner. Taiwanese names frequently move as a cohort rather than
individually, and cohorts often start abroad: foreign passive-component names run and the
Taiwanese ones follow; within a theme one name ignites and the rest catch up (the owner's
examples are 6443 leading a satellite-related move ahead of 2313 and 3491, and memory names
moving together with leaders and laggards separating).

This splits into two mechanisms with very different tooling status. Neither is optional --
both are inputs a ranking score would want -- but only one can be worked on today.

### Intra-market cohort behaviour: measurable now, half confirmed

Measured over the 2024-01-01..2026-08-14 holdout, over 606 eligible symbols joined to
`symbol_meta.industry_category`. A category counts as _ignited_ on a day when at least 30%
of its members close up 5% or more; 163 such events occurred.

| forward 20-day median                          |  value |  vs baseline |
| ---------------------------------------------- | -----: | -----------: |
| all symbol-days (baseline)                     | -0.16% |              |
| members that already moved on the ignition day | +1.18% | **+1.35 pp** |
| members that lagged on the ignition day        | +1.23% | **+1.40 pp** |

**Cohort ignition is a real signal**: the whole cohort outperforms for the following month,
which is a usable ranking feature. **Catch-up is not confirmed**: laggards beat movers in
only 48.5% of events, and in semiconductors (24) the movers won by 2.83 pp -- continuation rather than
catch-up.

> **RETRACTED 2026-08-24 by `tasks/20260824-value-chain-ignition`. Do not cite the +1.40 pp.**
> The paragraph above and the table it rests on are left in place because the reasoning that
> followed from them shaped a year of this document, and deleting the premise would make that
> reasoning unreadable. But the effect does not survive two corrections applied together.
>
> **Non-overlapping sampling.** A 20-day forward return sampled every day shares 19/20 of its
> content with its neighbour. Re-measured on the same pool with `stride = 20`, the same
> definition reads **+0.12 pp +- 0.79 (t +0.2)** in the holdout -- against **+1.65 +- 0.19
> (t +8.8)** when sampled daily. The statistic collapses on removing the overlap alone.
>
> **A grouping that can actually express a theme.** The next paragraph's diagnosis was right
> about the categories and wrong about the consequence. The TPEx value chain gives 469 nodes
> carrying a universe name against 34 categories, median 6 members against 28, with multiple
> memberships per symbol -- and it raises the train event count from 20 to 133. With that power
> the answer is a **significant negative**: -1.95 pp +- 0.61 (t -3.2) in train, zero in the
> holdout, and negative for the laggards too. Fixing the grouping did not reveal the effect; it
> removed it.
>
> The look-ahead runs the helpful way: the classification is a 2026-08-23 snapshot, so it should
> flatter train more than holdout, and train is the significantly negative window.

The most likely reason is that the grouping is wrong, not that the effect is absent.
Official industry categories can neither isolate a theme nor contain one:

| theme              | official categories                                                | failure                                                          |
| ------------------ | ------------------------------------------------------------------ | ---------------------------------------------------------------- |
| passive components | all in electronic parts (28)                                       | too broad -- the category holds dozens of unrelated names        |
| probe cards        | all in semiconductors (24)                                         | too broad -- pooled with TSMC and the IC designers               |
| memory             | semiconductors (24), plus 5289 in computer peripherals (25)        | too broad and it leaks                                           |
| satellite-related  | optoelectronics (26) + electronic parts (28) + communications (27) | **spans three categories; the classification cannot express it** |

**Consequence: cohorts must be derived from price behaviour, not from labels.** Symbols that
move together are a cohort by definition, whatever industry code they carry, and clustering
returns needs no data beyond the existing cache.

This also avoids a look-ahead trap that a labelled approach walks straight into. Published
"concept stock" lists are compiled _after_ a theme becomes famous, so backtesting against
today's list uses knowledge that did not exist on the test date. A cohort discovered from
returns up to date _t_ carries no such contamination.

### Cross-market lead: not available today

The price cache holds 2,070 equities but only **one** ETF, no index series, and no foreign
symbols, so no foreign lead can be tested at present. Two routes, both submodule work under
the repository's data-ownership rule:

- **Taiwan-listed ETFs tracking foreign markets.** Time alignment is correct by
  construction -- they trade in Taipei hours and price the prior foreign session -- so there
  is no timezone look-ahead to get wrong. `symbol_meta` already lists 351 ETFs; they simply
  are not in the price cache. The limitation is history: thematic ETFs are mostly recent.
- **Foreign prices directly** (US sector ETFs, Japanese and Korean peers). Longer history,
  but a new source, and the session-overlap alignment has to be handled explicitly or the
  backtest reads a close that had not happened yet.

Until one of these lands, treat the foreign-lead hypothesis as recorded and untested. Do not
approximate it with a Taiwanese proxy and report it as if it were the foreign signal.

## The strategy must survive a bear market, not only a bull one

Added by the owner on 2026-08-23, after the turnover study. Their words: 2022 was a Taiwanese
bear market, and through one you have little to work with beyond 0050 and breadth -- the daily
count of names advancing and declining. Their proposal is to raise the cash level in a bear,
or to park capital in 0050, and they asked for a better mechanism if one exists.

**The problem is measured, and it is worse than neutral.** Attributing each position's net
return to its entry year, every configuration tested lost far more than the index in 2022:

|                              |  2019 |  2020 |  2021 |      2022 |  2023 |
| ---------------------------- | ----: | ----: | ----: | --------: | ----: |
| 0050, total-return adjusted  |  +36% |  +30% |  +20% |  **-22%** |  +27% |
| `momentum` k10 + 20-bar hold | +26.9 | +88.8 | +80.4 | **-32.2** | +51.1 |
| `momentum` k10 baseline      | +21.3 | +90.5 | +95.9 | **-40.3** | +54.8 |
| `cohort` k10 baseline        | +21.6 | +53.9 | +21.4 | **-31.2** | +95.1 |
| `all` k5 baseline            | +11.9 | +68.8 | +84.8 | **-31.9** | +55.5 |

Every arm trailed the index by 9 to 18 points. That is structural rather than unlucky: a
long-only, fully-deployed rotation into relative strength has no exit from a systemic
decline, because the ranking always finds a strongest ten even when all ten are falling. The
lowest-turnover arm was the least bad (-32.2 against -40.3), which says trading less is
itself protection in a bear -- each rotation pays cost to swap one falling name for another.

**The train window already contains this.** Train 2019-2023 holds a full bear year and a
-34.0% drawdown; holdout 2024-2026 has a -27.5% drawdown but only 1.4% of days more than 20%
below the peak. Earlier reports described both windows as bull-tilted, which understated
train. What is missing is not bear data but a mechanism that reads the regime.

### What exists today and what does not

| needed                                                  | status                                                              |
| ------------------------------------------------------- | ------------------------------------------------------------------- |
| a defensive holding (0050)                              | **available**: 1,863 bars from 2018-12-07, covering both windows    |
| breadth (advance/decline, share above a moving average) | **computable from `price_daily.parquet`**; no new data needed       |
| the index itself (TAIEX)                                | absent; 0050 is a usable proxy                                      |
| inverse or leveraged ETFs (00632R, 00631L)              | **no price history**; named in `symbol_meta`, absent from the cache |
| short selling                                           | not supported by the engine                                         |

So raising cash and rotating into 0050 are both buildable now. Hedging with an inverse ETF is
not, and would be `shioaji_stock_prices` work before it could be tested.

**One trap on the way in.** Measured on unadjusted closes, 0050 returned -66.2% in 2025 with a
-77.2% drawdown, which reads as a crash. It is a 4-for-1 split on 2025-06-18 (`price_factor`
0.249987); on total-return adjusted prices 2025 was **+38.1%**. Any regime rule that uses 0050
as a market proxy must run on adjusted prices, or it will manufacture a bear signal on that
one day.

### The falsifier this adds

If no regime signal available from 0050 and breadth reduces the 2022 shortfall without
giving back more than it saves in 2019-2021 and 2023, then this strategy family is a
bull-market instrument, and the honest options are to accept that and size it accordingly, or
to acquire the instruments (inverse ETFs, short access) that would let it be more.

### Answered, 2026-08-23, by `tasks/20260823-regime-overlay` -- and the question was wrong

**The falsifier above fired.** Twenty-nine arms, ten detectors profiled over 2013-08 onward and
nine drawdown episodes, two responses: none qualified. Nine improved the training drawdown by
five points or more, fourteen kept two thirds of the return, twenty-one stayed under the cost
ceiling, and not one did all three across three contiguous parameter values. The only detector
family with long evidence -- 0050 against its own moving average, 0.6% false positives at MA200,
covering 70% of the 2015 decline and 87% of 2022 -- does not reduce this strategy's drawdown
enough in train and costs 25-59% of its return.

The two cells that did clear the first three rules are 0050 wearing a detector. `d3_ad50` flags
**91.8% of all days**, so pairing it with the 0050 response is a disguised buy-and-hold: it
returns +159.4% out of sample, and the identical signal paired with the cash response returns
**+2.6%**. The 157-point gap is the asset, not the signal.

**More importantly, the framing above is wrong, and the table in it is the reason.** That table
attributes each _position's_ net return to its entry year, on `book.py`'s accounting. On the
engine's account equity curve -- which is what an owner's statement would show -- 2022 reads
**-18.9% for the strategy against -21.4% for 0050**. The strategy did marginally _better_ than
the index through the bear year. The two numbers differ because this strategy sizes every slot
at a fixed fraction of _initial_ capital, so idle cash accumulates as it compounds and the
account is only 44% deployed on average through train; both figures are correct and they are
not interchangeable.

The real failure is elsewhere and it is not a bear market:

|                                 |  2019 |  2020 |  2021 |  2022 |  2023 |  **2024** |  2025 |   2026 |
| ------------------------------- | ----: | ----: | ----: | ----: | ----: | --------: | ----: | -----: |
| `momentum_k10__hold20`, account | +25.1 | +80.3 | +34.8 | -18.9 | +24.4 | **-20.9** | +14.2 | +101.4 |
| 0050, total return              | +36.1 | +31.1 | +21.9 | -21.4 | +27.5 | **+49.3** | +36.9 |  +65.5 |

**2024 is a 70-point shortfall in a bull year.** Over the whole holdout the strategy returns
+81.8% against 0050's +215.1% -- while still beating the equal-weight whole-pool benchmark's
+61.8%. So the ranking edge measured by the previous two studies is intact; the return of the
last 2.6 years was concentrated in the cap-weighted mega-caps that an equal-weight top-ten book
structurally cannot hold. In train the same comparison runs the other way (+206.6% against
+82.7%), so this is one window each way, not a verdict.

Two mechanisms are now closed. The **per-name MA60 entry filter** -- attractive because it needs
no regime call at all and is exercised on every decline -- changes **not one trade out of sample**
at any of five thresholds from +5% to -10%, because the top ten by trailing return are
essentially always above their own MA60. The **per-name MA60 exit filter** cuts winners: the
variant that can act promptly keeps 18% of the baseline's holdout return, and the variant that
respects the minimum hold does nothing at all.

What replaces the bear question: attribute 2024's index return to its constituents and measure
what an equal-weight top-ten book gave up; test whether size belongs in the ranking at all, since
none of the eight features sees it; and test a **standing** 0050 allocation rather than a
conditional one, because the degenerate "hold 0050 nearly always" arm beat everything out of
sample and has no detector to fit.

### Answered, 2026-08-24, by `tasks/20260824-ranking-horizon` -- the ranking cannot be fixed

The first of those was run: does the score miss the index's leaders because its **horizon** is
too short? Eight arms across two independent routes -- 120/250-day returns, the 250-day return
skipping the most recent month, and return over its own volatility at 60/120/250 days. **None
qualified.** Nothing reached 1.5x the baseline's holdout return and nothing formed a plateau.

The mechanism did operate, which is why the study separated that verdict from the P&L. Longer
windows and risk adjustment both move the book toward larger, older names: median entry turnover
rises from NT$392m a day at the baseline to **NT$1,045m (2.67x)** for the skipped-month arm, with
holding age rising alongside. It buys nothing -- the best arm returns +82.4% against the
baseline's +81.8%.

**The measurement that closes the line is 2330's own rank.** Over the holdout its median daily
rank is **83rd to 137th out of a pool near 450**, under every one of nine scores; across all of
them it enters the top ten on **exactly one day**. It returned +319.9% and beat 93.4% of the
market over the same span. Both are true because a percentile of trailing return is
cross-sectional and taken daily: 66% a year is never the steepest recent move on any given day.

So **the index's +236.7% is a weighting result, not a selection one.** No equal-weight top-ten
rule ranked on return percentiles can reach it, at any horizon, risk-adjusted or not, because
2330 is a top-7% stock and the tenth slot requires the top 0.5%. Lengthening the horizon made its
rank _worse_; only risk adjustment improved it, by two orders of magnitude too little.

Two directions remain, and they are independent of each other:

- ~~**Weighting rather than selection.**~~ **Withdrawn the same day, on its own logic.** The
  baseline never buys 2330 -- nine scores, zero entries -- and re-weighting ten mid-caps cannot
  produce a mega-cap's return. The only weighting that captures the index is holding the
  index's constituents at the index's weights, which is holding the index. (Testing it at all
  would also need market cap, which `symbol_meta.sqlite` does not carry: only code, name, isin,
  listed_date, market, industry_category, is_etf. Turnover is a liquidity proxy, not a size
  proxy.)
- **The value-chain classification** (`data/value_chain_classification.json`, 47 chains with
  upstream/midstream/downstream nodes, 2,212 symbols with multiple memberships) is the grouping
  this document has wanted since the cohort work. **Its first use failed**: see the retraction
  above -- ignition measured through it is significantly negative in train and zero out of
  sample. That closes ignition, not the grouping. Uses it has not been put to include capping
  holdings per node to force dispersion, and ranking nodes rather than names. It is a
  **snapshot dated 2026-08-23**, so applying today's membership to 2019 is a mild look-ahead
  and must be stated wherever it is used.

One lead recorded without being a finding: the skipped-month arm matches the baseline's holdout
return on **29% of its turnover** with a book twice as liquid. It is a single standalone cell
that cannot form a plateau by design.

### Answered, 2026-08-26, by `tasks/20260826-tail-selection` -- the score is a filter, not a ranker, and it stops adding value at about rank 30

The owner restated the objective on 2026-08-26: **find runaway stocks; choose among names that
equally satisfy the conditions; do not over-trade.** That is a different functional and a
different benchmark from the one the five studies above were graded against -- they all measured
a _mean_ excess return against 0050's total return. This card changed the outcome variable to the
right tail and measured the same frozen selection.

**The score is a much better runaway finder than it is a mean-return generator.** Share of names
returning at least +30% net over 20 trading days, non-overlapping sampling, total-return prices:

|         |  pool | top 120 | top 60 |     top 30 |     top 10 |
| ------- | ----: | ------: | -----: | ---------: | ---------: |
| train   | 2.95% |   4.71% |  6.42% |      8.12% | **11.82%** |
| holdout | 5.37% |   8.68% | 10.59% | **11.51%** |     11.29% |

**That figure needs its other half, and the other half changes the recommendation.** The same cut
pushes the book toward small caps, which spike harder in _both_ directions, so a raw `P(+T)` is
subject to exactly the volatility confound the arms are gated against. The down tail rises too,
and by a larger ratio: `P(<= -30%)` runs 0.35% in the pool against 1.82% in the top ten in train
(5.2x, against the up tail's 4.0x). What survives is the **asymmetry**, `P(+T) - P(-T)`:

| at +/-30% |    pool | top 120 |  top 60 |      top 30 |       top 10 |
| --------- | ------: | ------: | ------: | ----------: | -----------: |
| train     | +2.60pp | +4.12pp | +5.64pp |     +6.91pp | **+10.00pp** |
| holdout   | +4.14pp | +6.37pp | +7.37pp | **+7.85pp** |      +5.81pp |

**Tightening to about 30 names works in both windows. Tightening past it is not merely useless
out of sample -- it is negative.** The 30-to-10 step takes the holdout asymmetry from +7.85pp down
to **+5.81pp** (and +7.20 to +4.84 at +/-20%). On the up tail alone that step reads as a wash
(11.51% to 11.29%); only with the down tail included is it visible that the top ten buys more
volatility rather than more runaways. The actionable form of the result is therefore **stop at
about thirty**, and it is the same conclusion `20260823-rank-profile` reached on the mean, now
reproduced on the tail with a sharper edge.

This also resolves an oddity that has sat unexamined through five studies: the strategy loses
badly to a cap-weighted index _and_ is a good runaway screen, because the index's return comes
from mega-cap weights and the runaway rate comes from the mid-cap right tail. They are not the
same quantity and no single number captures both.

**Nothing else orders the qualified set.** Ten tiebreaks applied _after_ the score has chosen its
top 60 -- `vol_60`, `ext_20`, `vol_ratio`, `contraction`, `cohort_breadth`, `ret_250_ex_20`,
value-chain `node_strength` and `node_breadth`, `liquidity`, and the score itself -- produced
**0 of 10 qualifying in each window**, on a date-paired two-tailed asymmetry statistic with the
standard error clustered by date. The decisive evidence is not the failure to reach significance
but that **every arm changes sign between the windows**: the six positive in train are all
negative in the holdout and the two negative in train are both positive out of sample. The study
was powered to detect a lift of roughly a quarter or more on the runaway rate, so it rules out
large tiebreaks and not small ones.

The three candidates excluded before the run for collinearity with the score inside the qualified
set (`above_ma60` rho +0.81, `sharpe_60` +0.63, `ret_120` +0.54) are recorded in the mission: a
tiebreak that restates the score cannot break a tie the score produced. This is also where
`codex/kline-research`'s `tasks/20260823-dynamic-cohort` result fits -- return-derived peer groups
persist out of sample but _adding_ them to a per-name score dilutes the stronger momentum rank;
using node information as a post-hoc tiebreak instead is the form this card tested, and it fails
too.

**A tiebreak's turnover cost is set by how stable the feature is, not by what it measures.**
Selecting the top 10 out of the top 60 by a second criterion costs between 0.83x and **3.23x** the
shortlist churn of taking the top 10 by score: `ext_20` and `vol_ratio` re-sort the list daily,
`ret_250_ex_20` and `vol_60` barely move it. This reproduces `20260823-selection-vs-random` §5 --
what drives turnover is the score's own day-to-day stability, not how wide the exit threshold is --
one level down. (The absolute figure, ~52 entries per slot per year, is raw daily-recompute
shortlist churn and is _not_ the strategy's turnover, which hysteresis holds under 12. Only the
ratio is meaningful, and even the ratio is a proxy until an engine run measures it.)

One lead recorded without being a finding, because it is the only thing in a 60-configuration scan
that kept its sign in both windows: `contraction` (a tighter base preferred), at **top 120** over a
**60-day** horizon, plateaus across all four thresholds in train at t +2.05 to +2.54 and stays
positive in the holdout. It does not count, for four separate reasons: it is absent from the
pre-registered top-60 reading, so it is the boundary artifact rule 5 exists to catch; it rests on
19 and 10 non-overlapping dates; its volatility-stratified statistic collapses out of sample
(+0.34, +0.36, -0.67, -0.80); and its churn is 1.87x, past the 1.25x ceiling. It also deserved one
extra check, because it is the only arm that _prefers_ low volatility and so should have been the
least vulnerable to the confound: split by volatility tercile, the effect is **largest in the
jumpiest third** at every train threshold (+3.95 to +4.47 against +0.79 to +2.89 in the calmest),
no tercile reaches t >= 2 in either window, and the holdout terciles are near zero or negative. It
describes names that jump hard and have recently gone quiet -- a sharper mechanism than the
original reading and a weaker statistic. One t of about 2 in 60 configurations is the number
chance supplies.

**What this leaves.** The machine narrows 450 names to about 30 with a real two-to-four-fold lift
in runaway rate, and beyond that adds nothing measurable from the price series. The division of
labour that follows is that the last step belongs to the owner, on grounds the price data does not
contain -- and that adding no tiebreak at all is also the cheapest option on turnover.

### Answered, 2026-08-26, by `tasks/20260826-runner-retention` -- the exit is not the lever, and the control family won

The owner's spec of 2026-08-26 asked for participation in the main advance, a runaway capture
rate, a 2022 bear check and a turnover check, rather than an average return. Three diagnostics
located where the chain breaks. The screen does not miss the runaways -- taking each holdout
year's twelve largest runs among names it could have held, **36 of 36 entered the score's top
thirty**, most with the bulk of the move ahead (2344 華邦電 at 18.9 with **+341% left**). The
engine buys them: the standing cell holds 2344, 2408, 8210, 7610 and 4909 in the holdout. And
then it sells them, capturing about **12%** of what its own entries made available.

**Thirteen exit rules, two windows, zero qualified -- and the family that won was the control.**
Ranked by the share of all runaway return on offer that each arm actually captured, the three
rank-based exits take the top three in train (`rank120` 13.8%, `rank60` 13.1%, `rank30` 12.3%) and
first and second in the holdout (`rank30` **6.8%**, `rank60` 6.1%). Every ATR trailing stop,
N-bar-low break and give-back stop does worse. The mission pre-registered the expectation that the
control would fail, so the correction is recorded rather than smoothed: the diagnosis that a
cross-sectional rank is the wrong quantity for an exit is right about the mechanism -- on 68 of
252 excluded days 2344 sat within 10% of its own running high, once at a new high with a
twenty-day return of +50%, ranked 170th -- and wrong about the remedy.

**Why: retention and coverage are close to zero-sum inside a ten-slot book.** `give30` and
`give40` did exactly what the card wanted, lifting participation from the baseline's 11% to **29%
and 32%**; their capture rate fell from 94% to **47% and 33%**, and the product barely moved
(12.3% -> 11.3% -> 8.3%). In train every arm runs at 9.2 to 9.9 of ten slots and is full on 73-89%
of bars. On a full shelf, one book held longer is one book not bought.

**The two windows have opposite binding constraints, and one constant causes both.** The engine's
`cash_blocked_entry_count` cannot carry this: it increments once per attempted name per bar, and
the strategy's buy loop only decrements the free-slot count on a _successful_ buy, so a cash-short
bar retries every unheld top-ten name and records up to ten blocks. The baseline's **2,878 blocks
against 243 buys** is a real ratio and is not "2,878 entries missed" -- which is what a sizing
premise would need. Reconstructing the cash path from the fills instead, validated to the cent
against the engine's own closing cash, gives a categorical answer (`cash_path.py`):

|                  | free-slot bars | of those, cash below one slot | median cash |
| ---------------- | -------------: | ----------------------------: | ----------: |
| `rank30` train   |      146 (12%) |                      39 (27%) |  **14.34M** |
| `rank30` holdout |  **483 (76%)** |                **483 (100%)** |   **0.51M** |
| `low60` holdout  |      571 (90%) |                    571 (100%) |       0.31M |

**In train the book is full on 88% of bars while 14.34M sits idle** -- more cash than the initial
capital, because the account grew to 30M while a slot stayed at 1M. Slots are scarce and cash is
not. **In the holdout a slot is free on 76% of bars and on every single one of them the account
cannot fund it.** The cause is one constant: each slot is a tenth of _initial_ capital, so ten
slots demand the full 10,000,000 while the holdout drawdown reached -53% and equity spent long
stretches below that. The book this configuration intends is physically unfundable in exactly the
periods it most needs to enter, and much of the holdout's low capture is sizing rather than the
exit. The same constant is wrong in both windows, in opposite directions.

**The named case is the trap, and it is worth keeping as a standing example.** The three arms that
did best on the owner's own worked example -- `rank120` +152% on 2344, `low20` +144%, `atr3` +140%,
against the baseline's +75% -- are all worse overall, and `low20` returns **-30.9%** across the
holdout. An exit rule chosen for clearing one named stock is fitted to that stock. This is why the
mission made the case reportable and non-gating.

**No exit rule avoids 2022.** All thirteen land between -12.8% and -24.4% for the year. The exit
from a systemic decline has to come from outside the position -- the owner's specified 0050/cash
defensive leg -- and not from a stop.

**What this leaves.** Selection, ranking horizon, cohort grouping, shortlist tiebreak and now the
exit have each been changed and none was the bottleneck. The one thing never varied is the shape
of the book itself: ten equal-weight slots, each fixed at a tenth of initial capital. The ceiling
that shape imposes is measured here -- the best arm anywhere captures **13.8%** of the runaway
return on offer in train and **6.8%** out of sample -- and it is what the sizing card has to move.

## Falsifiers

The objective is out of reach, and the direction should change again, if:

- The ranking cannot beat the deployment-matched random null at the 80th percentile or
  better, out of sample, at equal or lower turnover — after rebuilding the universe so the
  named themes are actually present. That is the direct test, and it is the one that matters.
- Every configuration that beats the null does so only above a turnover level where cost
  eats the edge. This would mean the signal exists but is not harvestable at Taiwanese
  transaction cost, which is a real and final answer.
- The leaders of a theme are only identifiable after the move is largely over. Measurable:
  rank each theme's leaders on the day the score would have surfaced them and compare with
  the move's own start date.
- Cohorts derived from returns turn out not to be stable enough to trade: the membership
  discovered up to date _t_ does not predict which names move together after _t_. That would
  leave cohort ignition as a descriptive fact with no forward use.

None of these is settled by anything measured so far. They are written down now so that a
negative result is recognised as a result rather than absorbed as a reason to keep tuning.
