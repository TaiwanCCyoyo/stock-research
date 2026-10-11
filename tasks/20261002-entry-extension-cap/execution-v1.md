# Entry-extension cap v1 — completed, candidate failed

## Verdict and execution identity

Close this exact first-entry ret60<=50% configuration. It materially reduces
trial losses and requests, but retains only13.694087917% of the recorded daily
account's profit and has only one captured-hit issuer. Frozen rules2 and5 fail;
rules1,3,4 and the known-window condition6 pass. This is valid completed
measurement of a failed candidate, not a download or execution blocker.

Code/mission `0efe116`, digest release `e6c7bbc`, packet
`3503cd65983f85e02cc94059a2e4c81ddaeb27b364e76e909f863f7682dac5d9`.
One process exited0 after417.812seconds with complete native output, endpoint
2023-12-29T20:00+08:00, no diagnostics, stop or pending requests. Eight focused
synthetic tests and normal commit hooks passed. No new download, source change,
baseline rerun, grid, extra account or reserved-period access.

All356 inputs/runtime, recorded-comparator references and source-capture hashes
were reverified after completion, before economics. Native8-output receipt:
`538c600362d701034d2be2c5d04e372056e5f2568577f7124f3ace49ce4b3a18`.
Diagnostic12-output receipt:
`0fc861f1837526ae5efdf20dd2cc7a099ead0d59bf5092600e03da66699ae0eb`.
Process receipt:
`64139200f2afbf661815dc757cb47fcbd1b462f3b8001b551cd1cf43a998c33a`.
All referenced output hashes passed. Primary artifacts under `runs/cap-v1`:

| Artifact            | SHA-256                                                          |
| ------------------- | ---------------------------------------------------------------- |
| summary.json        | 3d8525313bbc9ea2d63add20fa0567a378693f4dacc1fbd2f8e255f307161757 |
| behavior.json       | 8902deda1331334675c3a947c369965a3eaea99e5b69bc3e40769d80deff1e71 |
| events.json         | 7bf01d31b28933ca079575bf028aa3969e1a0a64aba02a767930fc2deee0b75a |
| cap-traces.json     | d71fdabb2697d4d1ce7398fcbc2065f4584fb2f6db4b3a7a02d7afadd24e3bfb |
| delay-schedule.json | 58657b2d5f38fff5c1d04a891779cce698c81d60cf21fc0d148001799595415f |

After recording this exposure, the registry has45 events. Its complete44-event
release representation is preserved at `e6c7bbc`; explicit append-only validation
and all other input identities still pass. Do not rewrite the old packet or
expect its original strict current-registry hash to match after this append.

## Mechanism and timing checks

Native sizing proposed2,201 initial BUYs before filtering;2,081 were withheld
specifically for finite ret60>0.5,120 passed. No missing/nonfinite rejection
occurred. Withholding spans216 issuers and962 advice evenings; repeated proposals
on later dates are not distinct trades, fills, avoided losses or independent
samples. The94.547933% proposal rejection fraction describes this account path,
not a rejection rate over the universe or over the old baseline's orders.

Every retained trace maps to exactly one emitted original BUY of1,000shares;
every withheld order ID is absent. Trace IDs are unique and reconcile to all
pre-filter ordinary sizing proposals. Full-pool daily ranks/exits and the native
outer add rule are unchanged; no lower-ranked refill. Changed cash/holdings and
subsequent decisions are real simulation interactions, not matched-trade effects.

All267 requests match recorded schedule requests and routes, with due frame
exactly decision frame+1. All265 BUY/SELL fill events match the multiset of
schedule fills on the supplied due trading date, venue, code, side and quantity.
No assumption that one order can only fill once was needed. Two quiet final
advice dates and their recorded decisions agree. These are execution-model
results, not proof of actual historical queue priority, slippage or credit times.

Standing paid-subscription refusal observations include6438 and native3363,
each1,000qualified old shares and zero subscription cash/new shares, with assumed
timing. Existing source-bound economics remain; zero debit is not zero right
value. Final native position2353 remains a genuine open attempt, not forced closed.

## Account comparison — exposed2019–2023 only

Same initial2,000,000TWD and maximum five issuer occupancies; comparator is the
unchanged paired two-quiet-day daily account, not the older one-quiet-day result.
Its delay-failure verdict is not reversed by using it as a research comparator.

| Measure                                     | Recorded daily |     Entry cap |
| ------------------------------------------- | -------------: | ------------: |
| Endpoint equity, TWD                        |   4,934,085.15 |  2,401,796.20 |
| Net account profit, TWD                     |   2,934,085.15 |    401,796.20 |
| Completed hits / non-hits / open attempts   |      6 /293 /4 |     1 /118 /1 |
| Distinct captured-hit issuers               |              6 |             1 |
| Positive non-hit cash, TWD                  |   2,763,858.94 |    694,994.00 |
| Negative non-hit cash, TWD                  |  -2,367,424.46 |   -546,141.87 |
| Net non-hit cash, TWD                       |    +396,434.48 |   +148,852.13 |
| Losing non-hit count /mean loss, TWD        | 215 /11,011.28 |  76 /7,186.08 |
| Requests /active advice evenings            |       714 /549 |      267 /218 |
| Fill events /add proposals                  |       702 /106 |       265 /28 |
| Modeled costs, TWD                          |        359,879 |       113,172 |
| Worst daily account drawdown                |     18.751516% |    10.376418% |
| Longest underwater calendar days            |  904, censored | 688, censored |
| Known full20 from-zero non-hit erosion, TWD |     425,961.59 |    176,699.00 |
| Known full20 peak-to-trough erosion, TWD    |     490,565.59 |    218,557.00 |

The negative non-hit subtotal improves1,821,282.59TWD, but positive non-hit cash
falls2,068,864.94TWD; net non-hit contribution therefore falls247,582.35TWD.
Both components include all completed non-hits, not only losing trades, and
exclude hit gains. Cross-file native attempt IDs, code, disposition, gross
purchases, costs and captured cash reconcile for all120 candidate attempts and
all303 comparator attempts. Minor binary-float endpoint residues under1e-6TWD
are displayed at cents; the failed13.69%-versus70% earnings gate is not borderline.

Frozen rule1 passes complete measurement and active cap. Rule2 fails despite
positive profit:13.694088% retention is far below70%. Rule3 passes positive net
non-hit cash and lower negative magnitude, without hiding the reduced positive
component. Rule4 passes both burden reductions. Rule5 fails one versus required
at least two captured-hit issuers. Rule6 has no known counterexample above the
fixed425,961.59TWD comparison; it does not certify the unknown global maximum.

## Sustainability, costs and limits

There are89 known full20-attempt windows versus186. Global maxima remain
unavailable: genuine open attempt280 versus comparator718/725/729/731. Retain
classification incompleteness; neither these cash-attribution measures nor
per-attempt compounding is actual account drawdown or an executable misses-only
account. The from-zero and peak-to-trough maxima may come from different windows.

Maximum consecutive completed non-hits108 versus147, while maximum consecutive
negative non-hit cash results10 versus18. Candidate non-hit holding duration
median11, p90=23, maximum75 trading sessions; its single hit lasted66 sessions.
The one completed hit wait was166 sessions, but the subsequent still-unfinished
wait is1,049sessions/1,570calendar days through the endpoint. Do not present the
single completed wait as a representative distribution. Underwater span
2022-02-09–2023-12-29 is censored; future recovery is unknown.

Candidate requests comprise148 BUY and119 SELL, all regular-open; zero odd-lot
requests/fills. Active-evening mean1.2248 requests, maximum3; the all-evening p90
is1, including zero-order evenings. New filled attempts120/5=24 per capacity
slot over the whole period, not persistent-slot replacement histories; the latter
final reporting gap remains. Comparator303/5=60.6 has the same limitation.

Positive closed-profit concentration top1/top3 is26.7015%/57.1840%; relative to
net account profit63.0108%/134.9443%. These are descriptions, not best-attempt
removal reruns and not a single-star acceptance argument.

| Year | Half-two-sided turnover /annual mean NAV | Modeled costs TWD | Costs /annual mean NAV |
| ---- | ---------------------------------------: | ----------------: | ---------------------: |
| 2019 |                                 1.781133 |            31,682 |              1.387685% |
| 2020 |                                 0.920294 |            18,881 |              0.768496% |
| 2021 |                                 0.378292 |             7,590 |              0.305321% |
| 2022 |                                 2.325888 |            44,174 |              1.804192% |
| 2023 |                                 0.555098 |            10,845 |              0.452771% |

Withdrawn3x/2% ceilings are not reinstated. Daily valuation is not intraday
drawdown, endpoint equity is not entirely realized cash, and modeled results are
not a performance lower bound. Repeated exposed-period comparisons have not
created statistical or independent evidence.

Do not tune another cap/lookback or run further stresses to rescue this version.
The completed observation supports only the narrow verdict: this cap reduces
exposure/erosion but sacrifices too much earnings and captured-hit breadth under
the preserved ranking. It does not establish that all anti-extension approaches
fail. Any further mechanism needs a separate reasoned prospective card; do not
select it while reporting this result. Final owner loss budget, complete manual
resilience, sensitivity and independent/forward evidence remain unresolved.
