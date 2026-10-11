# Catalog participation: completed descriptive diagnostic

## Decision

The catalog is useful for separating entry and holding questions. It does not
support rescuing the failed weekly exit rule: peak-close participation improves
by only two episodes, while the preserved weekly account's non-hit attribution
fails its original screen. Many actual first holdings begin after the catalog's
doubling qualification, and repeated attempts in stocks without an overlapping
catalog ascent also consume cash. Both entry selection and attempt risk merit
attention; this diagnostic does not identify a profitable replacement rule.

Next research priority: one prospective entry/trial-exposure candidate, using
only decision-time prices and the existing account model. Examine the available
PIT entry features before fixing that candidate; do not directly exclude stocks
using hindsight episode membership. Keep the tentative economic-risk exit
unsealed until that choice is made. No cadence tuning, catalog-based acceptance
gate, threshold sweep, new data acquisition or independent period follows here.

## Fixed comparison and evidence

The [mission](mission.md) compares the preserved daily paired baseline with the
completed weekly v2 account over 2019-01-02 through 2023-12-29. Initial capital
NT$2m, at most five issuer occupancies; their original models and verdicts remain.
This reads saved executions and replays their accounting; it is not a new trading
simulation or counterfactual strategy. Catalog adjusted-price gains exclude cash
dividends; native captured hits retain the completed +50%-of-gross-buys cash rule.

Mission and original code were committed at `38a0267`. The first diagnostic
stopped before any joined result: an overly strict calendar check rejected
recorded nontrading-day dividend events. Its process and packet remain intact.
[Correction v2](correction-v2.md), committed at `67b12c0`, preserves those events
in the ledger prefix and still rejects nontrading-day BUY/SELL records.
Eight focused synthetic cases and normal commit hooks passed.

One explicit corrected calculation completed: child computation 6.500 seconds,
launcher 7.640 seconds, process exit 0. All 676 declared input identities, runtime,
completion receipt and output hashes were rechecked before interpreting results.
Original account receipts/packets and their input identities were also verified;
their original 34/40-event registry histories remain preserved prefixes of the
42-event intake registry. The source catalog's 280 chunk hashes match its receipt.
No downloads, native account reruns, raw price recalculation or producer writes occurred.

Output directory: `runs/diagnostic-v2`. Identities:

- Packet: `903264b906dfbec297908caa4e7baac0d36130e21414f4c65add5f4d01a35659`.
- Analysis: `839ccca97b92b438ea959b26a765e663e1c9c0add7be9bea023cc9c22699b8d1`.
- Replayed holdings: `bad3378a977045d27feb4d9dc70f23d11fc7820369a203cfe50922202f10fc07`.
- Receipt: `6dc2788a52f63a4bbd60bd668d4ab545c7beafbe28f84a25a9e1b01bdeaf287c`.
- Process: `653104e2d41f3ab96477d798ce7130b0206dadf3e822da043f803931e3ef2832`.

## Participation, not executable opportunity returns

The fixed primary set has 1,434 unflagged, fully confirmed episodes from 960
issuers. It excludes 1,127 catalog episodes under the preregistered boundary,
censoring and quality rules. Exclusion reasons overlap: 1,105 confirmation dates
outside the window; 1,099 peaks outside; 1,041 qualifications outside; 883 starts
outside; 21 unfinished/censored; 7 flagged. These are not independent exclusions
and cannot be summed. Long ascents unfinished by the cutoff are not failures.

| Primary episode observation                               | Daily | Weekly |
| --------------------------------------------------------- | ----: | -----: |
| Never held at any supplied close from trough through peak | 1,292 |  1,302 |
| Held, but no tradable shares at peak close                |    67 |     55 |
| Positive tradable shares at peak close                    |    75 |     77 |
| Total episodes with any close holding                     |   142 |    132 |
| Distinct issuers in those held episodes                   |   135 |    124 |
| First close holding on/before doubling qualification      |    46 |     44 |
| First close holding after doubling qualification          |    96 |     88 |

The five-stock account cannot own every historical winner; the 1,434 denominator
is not an owner acceptance target, predictive hit rate or a PIT stock pool.
Holding the peak close neither means selling there nor capturing the full ascent.
Likewise, earlier exit can be reasonable; these labels alone cannot justify a
different sell date. Claims without delivered shares are not tradable holdings.

Paired transitions: 62 episodes are held at peak in both accounts; weekly gains
11 from daily's held-not-at-peak category and 4 from never-held, but loses 3 to
held-not-at-peak and 10 to never-held. Net peak participation is therefore +2.
Nine formerly held-not-at-peak episodes become never-held, five never-held become
held-not-at-peak, 47 stay held-not-at-peak, and 1,283 stay never-held.

Seven daily and ten weekly episodes link to at least one captured-hit attempt,
but there are only six and eight distinct native hit attempts respectively.
Attempts spanning episodes are counted once in all cash tables; episode-linked
hit counts must not be mistaken for independent completed trades.

## Entry evidence and limits

Among never-held episodes, daily/weekly have 147/152 with at least one recorded
top-five-but-unaffordable observation and 54/67 with an affordable observation.
These overlap: affordability can change across dates. Their observation counts
are 1,665/1,792 unaffordable stock-days and 160/234 affordable stock-days.
Affordability means one regular lot fits the fixed initial gross budget, not
that the whole account has free cash or capacity. It is a concrete entry constraint,
not proof that raising the budget would help after costs and losses.

Both accounts have eight never-held episodes with saved BUY advice/ordinary
proposals during the interval. This does not establish failed execution: advice
on the peak close would naturally execute later. No saved entry observation
exists for 1,100 daily and 1,098 weekly never-held episodes. Their cause is unknown
in this diagnostic; absent traces cannot prove low rank or cash/capacity failure.

## All attempts and non-hit attribution

TWD below are whole-attempt cash contributions, not profit earned only inside
the labeled episode days, account drawdown or an executable misses-only account.
The two strategies can create different attempts and captured-hit labels; these
partition differences are descriptive associations, not matched-trade causal effects.

| Native measurement                      |         Daily |        Weekly |
| --------------------------------------- | ------------: | ------------: |
| All attempts: hit / non-hit / open      |   6 / 293 / 4 |   8 / 247 / 5 |
| All non-hit positive cash               |  2,763,858.94 |  2,121,879.00 |
| All non-hit negative cash               | -2,367,424.46 | -2,537,296.46 |
| All non-hit net cash                    |    396,434.48 |   -415,417.46 |
| Costs, all attempts                     |    359,879.00 |    327,146.00 |
| Attempts overlapping primary ascents    |           158 |           141 |
| Non-hits among primary-overlap attempts |           152 |           133 |
| Primary-overlap non-hit positive cash   |  2,451,445.94 |  1,758,243.00 |
| Primary-overlap non-hit negative cash   | -1,401,556.00 | -1,748,496.00 |
| Primary-overlap non-hit net cash        |  1,049,889.94 |      9,747.00 |
| Complement attempts                     |           145 |           119 |
| Complement non-hit net cash             |   -653,455.46 |   -425,164.46 |

The primary-overlap non-hit sum decreases by TWD1,040,142.94, while the complement
improves by TWD228,291.00; together they reconcile the TWD811,851.94 deterioration
in all non-hit net cash. Even stocks appearing in documented ascents can generate
losing attempts. Their hindsight label cannot excuse that erosion.

The complement includes 17 daily and 15 weekly attempts touching excluded/unfinished
episodes. Their non-hit sums are +170,001.00 and +202,331.00; keep that uncertainty.
The remaining 128 daily and 104 weekly attempts have no catalog-ascent overlap:
daily 128 non-hits total -823,456.46; weekly 103 non-hits total -627,495.46 plus
one open attempt. This is absence of an overlapping catalog label, not proof of
no future opportunity or permission to filter those stocks retrospectively.

## Peers and coverage

28,044 distinct comparable in-window security/period pairs cover 1,640 issuers,
after removing 523 repeated group views. Another 35,613 source rows are excluded:
6,034 noncomparable/quarantined, 29,579 outside the requested account window.
These overlapping peer periods are descriptive reference windows, not independent
observations, an unbiased control group or a market-wide predictive denominator.

| Peer category                          | Windows | Unique issuers | Held windows daily / weekly |
| -------------------------------------- | ------: | -------------: | --------------------------: |
| Overlaps a primary episode             |   6,246 |            889 |                   666 / 623 |
| No catalog episode overlap             |  21,580 |          1,627 |                   195 / 171 |
| Only excluded/boundary episode overlap |     218 |             98 |                       8 / 3 |

Issuers can occur in multiple categories and periods. No account PnL is summed
across peer windows. Today's group labels remain retrospective; their historical
availability is not established by this result. No named star drives the decision.

The batch is complete and useful for direction selection. It does not establish
a new strategy, satisfy the owner's final loss budget, or create independent
evidence. Existing delay/weekly failures stand; the broad research goal remains active.
