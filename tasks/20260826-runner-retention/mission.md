# Mission -- the screen finds the runners and the book sells them; can a structure exit hold them?

## 0. The three measurements that make this the next card

`20260826-tail-selection` established that the score is a filter worth having and that nothing
orders its shortlist. Three diagnostics run on 2026-08-26 locate what actually goes wrong, and
each is a different step of the same chain.

**Step 1 -- the screen does not miss the runaways.** Taking each holdout year's twelve largest
runs among names the screen could have held, **36 of 36 entered the score's top thirty**, and
most did so with the bulk of the move still ahead: 2344 華邦電 at **18.9 with +341% left**,
7610 at +49% in with **+1339%** left, 8210 at **-1%** in with +317% left.

**Step 2 -- the engine buys them.** The standing `momentum_k10__hold20` cell holds 2344, 2408,
8210, 7610 and 4909 in the holdout. Selection and execution both work.

**Step 3 -- and then it sells them, having captured about a sixth.** Across the ten largest runs
the baseline bought, measured from each position's own entry:

| code | name              | entries | bars held | captured | available from entry | participation |
| ---- | ----------------- | ------: | --------: | -------: | -------------------: | ------------: |
| 2344 | 華邦電            |       2 |        53 |     +75% |                +419% |           18% |
| 2408 | 南亞科            |       2 |        52 |     +71% |                +382% |           19% |
| 7610 | 聯友金屬          |       2 |       107 |    +604% |               +3859% |           16% |
| 8358 | 金居              |       1 |        45 |    +159% |                +681% |           23% |
| 6739 | 竹陞科技          |       3 |        61 | **-34%** |               +1585% |       **-2%** |
| 6442 | 光聖              |       2 |        52 |     +29% |                +806% |            4% |
|      | **mean over ten** |         |           | **+99%** |            **+831%** |       **12%** |

**Twelve per cent.** The failure is not selection and it is not execution. It is retention.

## 1. Why the current exit cannot hold a runner, measured rather than assumed

The standing rule sells when a holding's cross-sectional rank falls past `exit_rank = 30`.
Tracking 2344 daily from its first top-thirty entry (2025-03-10) to 2026-08-14:

|                                                      |   days | median distance below its own running high |
| ---------------------------------------------------- | -----: | -----------------------------------------: |
| inside the top thirty                                |    105 |                                  **-1.2%** |
| outside                                              |    252 |                                     -15.8% |
| **outside while within 10% of its own running high** | **68** |                                         -- |

Two distinct failures, and the second is the one that matters:

- **It sells on ordinary pullbacks.** A 15% retracement drops the name out of the top thirty.
  The owner's stated requirement is the opposite -- 可以忍受數月盤整.
- **It sells names that are still working, because other names are working harder.** On 68 of
  those 252 days the name sat within 10% of its own running high and was still excluded. On
  2025-05-26 it closed at a new high, up 50% in twenty days, and ranked **170th**.

A cross-sectional percentile is a **selection** device. Used as an **exit** device it forces a
sale whenever the rest of the market is hotter, which is information about the market and not
about the position. No value of `exit_rank` fixes that, because the quantity itself is wrong --
which is why family D below tests widening the band as a _control_ rather than as a candidate.

The owner described the right shape directly: 180 跌破支撐出場. An exit keyed to the position's
own price structure.

## 2. What is held fixed

Everything except the exit. Entry stays **top ten by the `momentum` score** (`r_ret_20 +
r_ret_60`, the standing weights), universe `rotation_pit`, 10,000,000 TWD, `shared` capital
mode, train 2019-01-02..2023-12-31 and holdout 2024-01-01..2026-08-14, and per-slot sizing at
1/10 of **initial** capital.

**Sizing is deliberately not an axis here.** The owner also asked for at least ~50% of capital
participating when a move exists, and the standing configuration averages 44% deployment in
train. That is a real gap and it is the next card, not this one, because raising deployment into
a book that sells its winners after fifty bars buys more of the wrong thing. It also carries a
cost that has already been measured -- idle cash was worth roughly 16 points of drawdown in the
holdout -- so it needs its own pre-registered trade-off rather than being folded in here.

**Bear-market detection is not reopened.** `20260823-regime-overlay` ran 29 arms and qualified
none. The owner has now _specified_ the defensive leg (0050 or cash when a bear is judged) rather
than proposing it as a hypothesis, so it is a given input for a later card and absent from this
one. Folding detector design back in would make this the regime study again.

### 2a. ETFs leave the pool, and this is verified inert

The owner's spec excludes ETFs from the stock pool, keeping 0050 only as a future defensive leg.
`rotation_pit` contains exactly **one** ETF, `0050`, and the standing cell **trades it zero times
in both windows** (train 346 distinct codes, holdout 209, neither containing it). The exclusion is
therefore adopted, and `anchor_retention.py` must still reproduce the stored
`momentum_k10__hold20` trade for trade -- which is what proves the change is inert rather than
merely arguing it.

## 3. The two new metrics, defined before anything is measured

Both are the owner's, and both are easy to make unfalsifiable if defined loosely.

**The runaway population is threshold-defined, not chosen after the fact.** The step-1 diagnostic
above used "each year's twelve largest runs", which is a denominator picked after seeing which
names ran. For a gated metric: a name belongs to the window's runaway population if, within
**250 trading days of the first bar on which it entered the score's top ten in that window**, its
total-return-adjusted close reached at least **+150%** above its close on that first bar.
Population sizes at that threshold are **64 names in train and 72 in the holdout**, out of 593
and 455 names that ever entered the top ten. The threshold is reported as a family -- +100%,
+150%, +200%, +300% -- with +150% as the pre-registered headline.

**飆股捕捉率 (capture rate)** -- the share of that population the arm held on at least one bar.

**主升段參與率 (participation rate)** -- for the names it held, the arm's realised return on that
name across all its positions in it, divided by the return available from **first surfacing** to
the highest close between then and the window's end.

The denominator is anchored at **first surfacing in the top ten**, not at the position's own
entry and not at the run's trough. Anchoring at the trough would build in a miss no rule could
avoid and would drag every arm down by the same amount. Anchoring at each arm's own entry would
flatter a late entrant by shrinking its denominator. First surfacing is identical for every arm,
because every arm shares the entry rule, so the denominator is a constant of the comparison and
only the numerator moves.

## 4. Arms

Four ordered families. Every arm keeps the entry rule and differs only in when a holding is sold.
A holding is also sold, in every arm including the baseline, when the name leaves the ranking
entirely -- that is loss of eligibility or delisting, not a rule choice.

**Family A -- ATR trailing stop.** Sell when the close falls `N x ATR(14)` below the highest close
seen since entry. `N` in **2, 3, 4, 5**. This is the standard runner-holding rule: the stop widens
with the name's own volatility, so a jumpy name is not shaken out by its own normal range.

**Family B -- break of the N-bar closing low.** Sell when the close is below the lowest close of
the prior `N` bars. `N` in **20, 40, 60**. This is the closest mechanical form of the owner's
"跌破支撐".

**Family C -- give-back from the peak.** Sell when the close is at or below `(1 - X)` times the
highest close since entry. `X` in **20%, 30%, 40%**. A fixed percentage rather than a volatility
multiple, so families A and C together separate "the stop should scale with the name" from "the
stop should be a fixed give-back".

**Family D -- a wider rank band. This is the control, not a candidate.** `exit_rank` in
**30 (the baseline), 60, 120**. If retention alone is what matters, this family should also work;
if the _quantity_ is wrong rather than its threshold, it should not. `20260823-turnover-mechanism`
already found widening reversed out of sample (6x train +153.8% -> +304.2%, holdout +147.3% ->
+77.4%), so the expectation is stated in advance: family D fails and family A or B does not. If
family D wins instead, the section 1 diagnosis is wrong and the report says so.

**One asymmetry, stated now rather than discovered later.** `min_hold_bars = 20` blocks a
_rank-driven_ sale and nothing else -- that is what it already does in `rotation_ranker_v4`. The
structure families have no rank-driven sale, so their stops fire whenever they fire, with no
minimum hold. That is correct for a stop and it is a genuine difference between the baseline and
the arms: a structure arm can be shaken out in five bars where the baseline cannot. Rule 3 is what
prices that.

**The cost of retention, reported because it is real.** A book that holds until stopped cannot
buy a new top-ten name while it is full. Every arm reports entries and the number of bars on which
a top-ten candidate could not be bought for lack of a slot, so the opportunity cost of holding is
visible beside the benefit.

## 5. Acceptance

**Rule 1 -- participation must rise materially.** Mean participation over the runaway population
at least **2x** the baseline's, in **train**. The baseline sits near an eighth of what its own
entries made available; an arm that lifts it to a sixth has not changed the character of the
strategy.

**Rule 2 -- capture must not be bought by giving up coverage.** Capture rate at or above the
baseline's, in **both** windows. An arm that holds its winners longer by entering fewer names is
solving a different problem.

**Rule 3 -- the cost ceiling still binds, in both windows.** At most **12 round trips per slot per
year**, capital-weighted, measured separately in train and holdout and required in both. This is
the owner's standing absolute constraint, not a relative comparison.

**Rule 4 -- drawdown must not blow out.** Maximum account drawdown no worse than the baseline's by
more than **10 percentage points**, in both windows. Holding through consolidations necessarily
deepens drawdown; the rule bounds how much. The 2022 calendar slice inside train is reported
separately as the owner's named bear check, and is reported rather than gated because a single
year cannot carry a gate.

**Rule 5 -- a plateau, not a winner.** At least **three contiguous values** of an ordered family
must satisfy rules 1 to 4. Families B and C have three members and can only plateau by passing
outright.

**Rule 6 -- the named case is reported, never tuned to.** 2344 華邦電 from its 18.9 entry in March
2025: each arm's entries, exits and captured fraction are printed. It is the owner's own worked
example and it is how a reader checks that a passing number means what it appears to mean. It is
**not** an acceptance criterion, because an arm selected for clearing one name is fitted to it.

**Rule 7 -- a clean negative is a result** and gets the same space as a positive. If no exit rule
lifts participation within the cost and drawdown ceilings, the finding is that a ten-slot,
equal-weight, fully-rotating book cannot hold a runner at all, and the constraint that has to move
is the book's shape rather than its exit.

## 6. Gates

- `verify_retention_features.py` -- ATR(14) and the rolling N-bar lows pass a truncation test (a
  table rebuilt from bars ending at T matches the full table on every row up to T), with the
  lookahead injected into the **builder** rather than the input series; no column carries a value
  before its own window is complete.
- `anchor_retention.py` -- the `rank30` arm reproduces the stored `momentum_k10__hold20`
  **trade for trade** in both windows, with ETFs excluded and the exit refactored. This is what
  proves the harness did not move the baseline underneath the comparison.
- `verify_rules.py` -- each acceptance rule fires in the direction it is supposed to, asserted on
  synthetic values with the opposite case asserted too, and each new metric is asserted against a
  hand-computed case.

## 7. Reproduction

```bash
uv run python tasks/20260826-runner-retention/retention_features.py
uv run python tasks/20260826-runner-retention/verify_retention_features.py
uv run python tasks/20260826-runner-retention/verify_rules.py
uv run python tasks/20260826-runner-retention/anchor_retention.py
uv run python tasks/20260826-runner-retention/run_grid.py --workers 6
uv run python tasks/20260826-runner-retention/analyze.py
```
