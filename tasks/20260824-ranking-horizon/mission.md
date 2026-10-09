# Mission -- can the ranking be made to hold the steady compounders?

## 0. The question, and why it is this one

`20260823-regime-overlay` failed its own question and, in failing, located a different one.
Measured across the whole pool on total-return prices:

|                        | train 2019-01..2023-12 (1,640 names) | holdout 2024-01..2026-08 (1,860 names) |
| ---------------------- | -----------------------------------: | -------------------------------------: |
| 0050                   |                              +118.2% |                            **+236.7%** |
| 2330                   |                              +209.4% |                            **+319.9%** |
| **median stock**       |                           **+75.0%** |                              **-1.1%** |
| 90th percentile        |                              +307.1% |                                +165.2% |
| **share beating 0050** |                            **35.6%** |                               **6.6%** |

The holdout was an extraordinarily narrow market: the median Taiwanese stock went nowhere while
the index tripled, and only 6.6% of names beat it -- even the 90th-percentile stock lost to it.
No equal-weight ten-name book beats a cap-weighted index under those conditions unless it holds
the same mega-caps. The baseline `momentum_k10__hold20` returned +81.8% against the index's
+236.7%.

**The mechanism is specific and testable.** The score is the cross-sectional percentile of
20- and 60-day return. A mega-cap compounding +319.9% over 2.6 years rarely owns the sharpest
20-day move on any given day, because small caps always spike harder. So the score is not
failing to rank; it is ranking on a horizon at which steady compounding is invisible.

This study asks whether that is fixable inside the ranking, by two independent routes:
**lengthen the horizon**, and **divide by volatility**. If the mechanism claim is right, both
should move the book toward larger, steadier names. If neither does, the claim is wrong and the
strategy family is structurally an equal-weight small-cap instrument.

## 1. What is held fixed, and what is newly at risk

The configuration carries over unchanged from `20260823-turnover-mechanism`: `top_k = 10`,
`exit_rank = 30`, `min_hold_bars = 20`, `rotation_pit`, 10,000,000 TWD, `shared` capital mode,
train 2019-01-02..2023-12-31 and holdout 2024-01-01..2026-08-14. Only the **weights on the
score** change, so every arm is one substitution away from the baseline.

**The holdout is no longer pristine, and this is the third study to read it.** The first
(`20260823-selection-vs-random`) saw it once; the second and third each swept it again, and this
one is being designed _after_ its return distribution has been examined in detail. A holdout
read four times is closer to a validation set than to a held-out sample, and no arithmetic here
repairs that. Two consequences are accepted rather than argued away:

- **The train gate binds first.** An arm that only works in the holdout is not reported as
  working, because that is precisely what a fourth read of the same window would produce by
  chance.
- **The mechanism checks in section 4 carry more weight than the return numbers.** Whether an
  arm actually shifts the book toward larger, steadier names is a claim about composition,
  not about a P&L that has had four chances to look good.

## 1b. The value-chain classification exists now, and is deliberately not used here

`shioaji_stock_prices` gained `data/value_chain_classification.json` on 2026-08-23 (main commit
`977b17f`): the TPEx Industry Value Chain platform, 47 chains, each with upstream/midstream/
downstream nodes, and 2,212 symbols carrying **multiple** memberships. That is the grouping
`docs/en/research-objective.md` has wanted since the cohort work -- official `industry_category`
is too broad for a theme and cannot express one that spans categories, and this can do both.

It is not used in this study, for one reason: this study tests whether the score's **horizon**
is why the book misses steady compounders. Swapping the cohort grouping at the same time would
confound the two, and a finer grouping does not address the diagnosed problem anyway -- a better
theme label still selects equal-weighted mid-caps, which is exactly what section 0 shows cannot
beat a cap-weighted index in a narrow market.

Two facts to carry into whichever study does use it. It is a **snapshot dated 2026-08-23**, with
one prior snapshot archived under `value_chain_classification_history/`, so applying today's
membership to 2019 is a mild look-ahead -- far weaker than a published concept-stock list, but
not zero, and it should be stated wherever it is used. And it is **absent from this worktree's
`data/` copy**, which was taken before the file existed; a worktree's copy is a snapshot, so it
must be read from the main checkout the way `detector.py` resolves `official_daily.sqlite`.

## 2. Features added, and why each one

A new table, `features_v2.parquet`, built by this task's own `features_v2.py`. It is a strict
superset of `tasks/20260823-rotation-universe/features.parquet`: the eight original features and
their eight rank columns are recomputed by the same code path, and `verify_features_v2.py`
asserts they come out **bit-identical** to the existing table. A new table rather than new
columns on the old one, because three committed studies read that file and an in-place change
would silently re-date their inputs.

| new feature                             | what it is, and why it is here                                                                                                                                                                                                                                            |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ret_120`, `ret_250`                    | trailing return over longer horizons -- the direct test of "the horizon is too short"                                                                                                                                                                                     |
| `ret_250_ex_20`                         | the same 250-day return with the most recent 20 bars skipped. Short-horizon reversal is well documented, and if it is present here then the last month of a 250-day window is working against the rest of it                                                              |
| `sharpe_60`, `sharpe_120`, `sharpe_250` | trailing return divided by the standard deviation of daily returns over the same window -- the second, independent route to the same place. A name that triples smoothly outranks one that triples in two spikes, which is exactly the preference the current score lacks |

**One consequence of the long features, stated now rather than discovered later.** Eligibility
requires 120 prior bars, so a name can be eligible without having 250. Long-horizon arms
therefore exclude recent listings as a side effect. That is part of the mechanism being tested
(older, larger names) and also a confound with it; `analyze.py` reports the age distribution of
holdings so the two can be told apart.

**Amended 2026-08-24, after building the feature table and before any cell ran.** Measured
coverage among eligible rows: `ret_120` 100%, `ret_250` and `sharpe_250` **90.9% from
2019-12-25**, `ret_250_ex_20` 89.6% from 2020-02-03. The pre-registration above assumed the
inherited `fillna(0.5)` was a harmless neutral. It is not, and the reason is arithmetic rather
than judgement: **before 2019-12-25 no name in the cache has 250 prior bars**, so every name
would score exactly 0.5, every score would tie, and the CRC tiebreak -- chosen to be
arbitrary-but-fixed -- would silently pick the entire book. A long-horizon arm would spend the
first year of the training window holding ten names selected by a checksum, and nothing in the
output would say so.

Two changes follow, and both are one-directional fixes rather than choices between outcomes:

- **A name is ranked only when every feature its arm weights has a value** (`dropna` instead of
  `fillna(0.5)`, in `rotation_ranker_v4`). A long arm holds nothing until its window exists,
  which is a truthful "no signal yet". Among eligible rows the baseline's two features are 100%
  populated, so this drops no row for the baseline and `anchor_horizon.py` still reproduces
  `momentum_k10__hold20` exactly -- which is the evidence that the change is inert where it
  should be.
- **The gates are evaluated on the common span**: train **2020-01-01**..2023-12-31, the first
  date on which every arm has a real signal, plus the full holdout. The full 2019-01-02 train
  return is reported beside it. Every arm is still _run_ from 2019-01-02, so a long arm simply
  sits in cash until it has a signal and enters 2020 from full cash with no inherited book --
  which makes the common span a clean start rather than a truncation.

## 3. Arms

Nine cells -- the baseline, two ordered families and two standalone arms. Weights are equal within each arm, as
in every prior study, so this measures the horizon rather than a fitted weighting.

**Family A -- horizon.** Four values, ordered from short to long:

| cell         | weights                                  |
| ------------ | ---------------------------------------- |
| `hz_20_60`   | `ret_20 + ret_60` (this is the baseline) |
| `hz_60_120`  | `ret_60 + ret_120`                       |
| `hz_120_250` | `ret_120 + ret_250`                      |
| `hz_250`     | `ret_250`                                |

**Family B -- risk-adjusted.** Three values, ordered by window:

| cell     | weights      |
| -------- | ------------ |
| `ra_60`  | `sharpe_60`  |
| `ra_120` | `sharpe_120` |
| `ra_250` | `sharpe_250` |

**Standalone, and reported as unable to satisfy rule 4 rather than excused from it:**

| cell          | weights                | why                                                                                                    |
| ------------- | ---------------------- | ------------------------------------------------------------------------------------------------------ |
| `skip_250_20` | `ret_250_ex_20`        | isolates short-horizon reversal                                                                        |
| `hz_ra_mix`   | `ret_120 + sharpe_120` | one cell combining both routes, so a reader can see whether they are additive or the same effect twice |

## 4. Acceptance

**Rule 1 -- train must not be broken.** Train return at or above **two thirds** of the
baseline's train return. This is the binding gate, for the reason in section 1. Two thirds is
the same give-back constant the owner set for the turnover study, kept identical so verdicts
stay comparable across studies.

**Rule 2 -- the holdout must improve materially.** Holdout return at or above **1.5x** the
baseline's. The gap being addressed is 155 percentage points wide; an arm that closes a tenth of
it has not demonstrated the mechanism, it has moved within noise.

**Rule 3 -- the cost ceiling still binds, in both windows.** At most **12 round trips per slot
per year**, capital-weighted, measured **separately in train and holdout and required in both**.
The previous study gated this on the holdout row alone and let a cell through that spent 13.55
in train; that scoping gap is closed here rather than repeated. Longer horizons should _lower_
turnover, so this gate is expected to be easy -- which is exactly why it is worth stating that
it is measured rather than assumed.

**Rule 4 -- a plateau, not a winner.** At least **three contiguous values** of an ordered family
must satisfy rules 1 to 3. A family of three can only plateau by passing outright. The two
standalone cells cannot satisfy this and are reported that way.

**Rule 5 -- the mechanism, reported separately from the verdict.** Three composition statistics
per arm, none of them gating:

- median trailing-60-day turnover of held names, against the baseline's -- does the book
  actually move toward larger names;
- whether 2330 is ever held, and for how many bars;
- median listing age of held names -- distinguishes "prefers large" from "excludes young".

An arm that clears rules 1 to 4 **without** moving these is reported as working for an unknown
reason, not as confirming the mechanism. An arm that moves them without clearing the gates is
reported as confirming the mechanism and failing to profit from it. Those are different results
and the report keeps them apart.

**Rule 6 -- a clean negative is a result** and gets the same space as a positive. It is a live
possibility: if neither route moves the book, the honest finding is that this strategy family is
structurally an equal-weight small-cap instrument and cannot be steered toward the index's
leaders from inside the ranking.

## 5. Gates

- `verify_features_v2.py` -- the eight carried-over feature columns and their ranks are
  bit-identical to `features.parquet`; every new column passes a truncation test (a table
  rebuilt from bars ending at date T matches the full table on every row up to T); no new
  column is available on a bar where its own window is incomplete.
- `anchor_horizon.py` -- the `hz_20_60` arm reproduces the stored `momentum_k10__hold20`
  **trade for trade** in both windows, reading the new table. This is what proves the new
  feature table did not move the baseline underneath the comparison.
- `verify_rules.py` -- each acceptance rule fires in the direction it is supposed to, asserted
  on synthetic rows at exact values, with the opposite case asserted too. Carried over from
  the previous study, where the drawdown rule was found inverted after printing a plausible
  table.

## 6. Reproduction

```bash
uv run python tasks/20260824-ranking-horizon/features_v2.py
uv run python tasks/20260824-ranking-horizon/verify_features_v2.py
uv run python tasks/20260824-ranking-horizon/anchor_horizon.py
uv run python tasks/20260824-ranking-horizon/verify_rules.py
uv run python tasks/20260824-ranking-horizon/run_grid.py --workers 6
uv run python tasks/20260824-ranking-horizon/analyze.py
```
