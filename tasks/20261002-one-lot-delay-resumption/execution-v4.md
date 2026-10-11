# Complete delay account: frozen70percent-profit diagnostic fails

Exactly one account after prospective card `5cef8c7`, implementation `e0aa6ca` /
input-list fix `892b468`,29 passing new synthetic cases and digest-specific
release `312e38c`. Producer exit0 after483.453seconds; native status **complete**,
final2023-12-29T20:00+08:00, diagnostics empty, pending orders empty. Unlike the
preserved v1/v2/v3 failures/partials, this is a valid economic result.

All385 frozen inputs/runtime, original comparator and earlier attempts verified
before economics. Native eight-output and separate eleven-output receipt hashes
verify. Independently reconciled978 requests/routes and438 fills at index+2;
405 ordinary fills show the extra session is active. Both accounts use identical
complete frame timestamps and shared raw price marks with two quiet advice days.
No new baseline, retry, seed/grid/parameter change or additional source request.

## Identities and active corrections

- Packet: `a74ebf68fe527898aadbb7e97d1c4c952e813f51e2896fd1914d63882c481c8b`
- Native receipt: `ca8610d06120f88afb8eb1cb6aab2cd0a34c35a31790ab7b9d8bf28f91c58c94`
- Diagnostic receipt: `a47605b252262cd1f03d34498065c4f140fa97e6aef3445a2c4ef4d6cd074569`
- Process: `1d61ec6980cf16f34ff65383319a208f21413ff93cbf188b011f1244bb1052b2`
- Process log: `81c108a431e94fa147b67d189a72871864bf5e64245200ed0ec94cc3cbbfcb33`
- Summary: `221948e36810243fb779966da0da1c9be6fe0c399e9f14ba20f8f25aec60288a`
- Behavior: `99d8c4efd4265aebf58b1e9bf2740f346dce480daa492ae3e634dc5b35ea3af7`

Pre6443 ledger equals preserved v3; prior pre3680 ledger equals v2. Audited
qualified3680 shares3000 and6443 shares1000, exact source-bound ratios/prices,
standing refusal at assumed07:00, zero subscription debit/new shares. This does
not claim zero opportunity value or observed historical announcement timing.
Named2375 resumption BUY1000 actually fills Mar14 at50.70 from49.85 prehalt
reference; named1760 delayed ADD actually fills2022-02-23 at122.00 from111.50
prehalt reference. Actual PIT venue guard and common cash/lifecycle stay native.

## Paired economic result — exposed2019–2023, modeled not independent

The comparator is the verified **two-quiet-day paired baseline**, not the older
one-quiet-day one-lot run. Currency comparison uses fixed cents:293408515 versus 155207887. Baseline float serialization2934085.1500000004 is within1e-9TWD of its
cent value; no original output was rewritten or alternative denominator chosen.

| Quantity                                            | Paired baseline   | One extra trading day |
| --------------------------------------------------- | ----------------- | --------------------- |
| Initial own capital                                 | 2,000,000TWD      | 2,000,000TWD          |
| Endpoint marked equity                              | 4,934,085.15TWD   | 3,552,078.87TWD       |
| Net account profit                                  | 2,934,085.15TWD   | 1,552,078.87TWD       |
| Closed non-hit positive cash                        | 2,763,858.94TWD   | 768,371.00TWD         |
| Closed non-hit negative cash                        | -2,367,424.46TWD  | -1,222,409.46TWD      |
| Closed non-hit net cash                             | +396,434.48TWD    | -454,038.46TWD        |
| Positive / negative non-hits                        | 78 /215           | 52 /136               |
| Closed hit / non-hit / endpoint-open attempts       | 6 /293 /4         | 13 /188 /3            |
| Closed captured-hit cash                            | 2,385,878.67TWD   | 1,979,004.33TWD       |
| Explicit modeled costs                              | 359,879TWD        | 169,270TWD            |
| Generated requests / active advice evenings         | 714 /549          | 978 /692              |
| Filled native entries                               | 303               | 204                   |
| Capacity-normalized entries per5 slots              | 60.6              | 40.8                  |
| Mean cash loss among losing non-hits                | -11,011.28TWD     | -8,988.30TWD          |
| Mean cash among all closed non-hits                 | +1,353.02TWD      | -2,415.10TWD          |
| Maximum negative-cash streak / consecutive non-hits | 18 /147           | 19 /69                |
| Daily marked-account maximum drawdown               | 18.751516%        | 17.529512%            |
| Longest calendar time below an earlier peak         | 904days, censored | 987days, censored     |
| Completed-hit session waiting median /p90 /max      | 174.5 /501 /501   | 59 /173 /342          |
| Closed hit holding sessions median /p90 /max        | 53 /68 /68        | 57 /90 /91            |
| Closed non-hit holding sessions median /p90 /max    | 14 /28 /75        | 17 /33 /52            |
| Odd-lot request share                               | 1 /714            | 2 /978                |

Profit retention **52.8982217847%**, account profit lower by1,382,006.28TWD.
Positive comparator profit/nonnegative delayed profit pass; fixed>=70percent
**profit**, not NAV, fails. Actual perturbation and completion checks pass.
Thus `failed_frozen_diagnostic`, not strategy approval or invalid measurement.

The delayed account loses454,038.46TWD from closed non-hits alone; big captured
winners do not erase that burden. Negative cash is less adverse by1,145,015TWD,
but small positive non-hit cash falls1,995,487.94TWD, worsening non-hit net by
850,472.94TWD. More qualifying hits do not prove a better method. Increased
unfilled/request burden despite fewer fills is part of the actual modeled
adaptive path, not a reason to delete failed orders or reprice pending limits.

## Risk and operational limits, not new vetoes

Known fully classified twenty-non-hit windows: baseline186, delayed63. Largest
reported from-zero non-hit loss425,961.59TWD versus283,156TWD; associated
peak-to-trough attribution490,565.59TWD versus286,673TWD. These are separate
non-hit capital attribution, **not full-account drawdown or an executable
misses-only account**. Baseline global summary remains unavailable; delayed
native window-summary status is ok, with conditional maximum8.999567% of its
window-start equity. Genuine endpoint-open attempts remain unclassified in both
accounts (baseline718/725/729/731; delayed458/463/464); no owner-approved global
twenty-attempt loss-budget certificate follows. No approximate20percent veto.

Underwater spans end at the fixed endpoint: baseline2021-07-08→2023-12-29;
delayed2021-04-16→2023-12-29. Values are supplied evening marks, not observed
intraday drawdown, guaranteed recovery dates or performance bounds. Endpoint
NAV includes genuine open holdings and is not entirely realized cash.

Five-capacity-normalized entry counts are not persistent-slot assignments;
per-slot history is still a final-delivery gap. No new water/odd-lot threshold.
Closed positive-profit concentration top1/top3: baseline21.2030%/36.9568%,
delayed25.4285%/43.7541%; relative to net account profit37.2143%/64.8645% and
45.0117%/77.4502%. These descriptive ratios do not replace a best-attempt
decision/cash/fill rerun. Best1 was not run, and is not needed to rescue this
already failed delay requirement.

Annual explicit costs2019–2023 are baseline64103/71066/85806/72388/66516TWD,
delayed34394/30168/39792/34962/29954TWD. Corresponding half-two-sided turnover
against annual mean NAV: baseline3.4831/2.4188/2.2341/2.0167/1.8297;
delayed1.9587/1.5208/1.3921/1.3518/1.0931. Cost fractions2.7303/1.9569/1.8070/
1.5794/1.4312% and1.5508/1.1831/1.1432/1.0775/0.8669%. Reported, not enforced
as the withdrawn3x/2percent caps. Complete hit-wait intervals, attempt durations,
annual costs and burden remain in the hashed `behavior.json`.

## Decision and next boundary

Close this exact one-lot candidate as an owner-ready lead: do not advance it to
independent confirmation/final adoption, alter70percent, tune another delay,
or complete every final stress merely to obtain a prettier historical verdict.
Its earlier initial-sizing triage and nominal missed10 result remain historical
facts, including the missed10 non-hit erosion warning. This new completed result
does not silently rewrite those reports or the old partial runs.

Next direction must address dependence on precisely timed daily rotation and
positive non-hit recycling, not just a higher selection hit rate. A separate
prospective mechanism/scope and limited exposed-history comparison are required
before another candidate account. Reuse validated source/execution capabilities;
no further lookup or platform build is justified by this failed candidate.
No downloads/cache/producer/submodule mutation, reserved period, automation or
remote delivery occurred in this batch. Independent evidence and the final
owner loss-budget agreement remain open; the broader goal stays active.
