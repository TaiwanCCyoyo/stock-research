# Historical industry source decision — 2026-09-09

Scope: six public endpoint probes for one candidate dependency. No strategy
performance, parameter comparison, market-cache write or holdout access occurred.
This is a source rejection, not a failed strategy or a completed PIT universe.

## Measured result

The TWSE [official announcement dated 2023-05-22](https://www.twse.com.tw/rwd/zh/announcement/announcement_detail?id=346FAB95F87B11EDB2DA005056BE380E&response=html)
states that the new industry classes take effect on 2023-07-03. It references a
2023-03-28 rule amendment and names four digital-cloud companies: 3130, 6165,
6689 and 8454. This establishes the effective-date boundary; it is not a claim
that no public discussion preceded those announcements.

All six requests returned HTTP 200 and a successful JSON envelope with the
requested date. Industry type was `36` on both endpoints.

| Requested session | TWSE digital-cloud codes | TPEx digital-cloud row count |
| ----------------- | ------------------------ | ---------------------------- |
| 2023-03-01        | 3130, 6165, 6689, 8454   | 0                            |
| 2023-06-30        | 3130, 6165, 6689, 8454   | 0                            |
| 2023-07-03        | 3130, 6165, 6689, 8454   | 13                           |

TWSE table 8 is labelled with the requested historical date and `數位雲端`;
its first field is `證券代號`. TPEx table 0 has first field `代號`. The TPEx
post-boundary codes are 2640, 3085, 3687, 5278, 5287, 5321, 6690, 6741,
6763, 6811, 8044, 8472 and 8477. We inspected these membership fields, not
candidate returns. The preserved original responses also contain price fields.

### Interpretation and limits

- **Reject TWSE MI_INDEX type-filtered historical rows as an effective-as-of
  industry-membership source.** The date is historical, but the tested category
  is applied before its effective date, including before the referenced March
  amendment. A naive historical-category join would import a later taxonomy.
  The observations do not identify whether the server uses a current snapshot,
  a fixed later snapshot, or another back-classification mechanism.
- The June result alone would not prove knowledge-time leakage: the May
  announcement was already public. Announcement-time and effective-time joins
  are different policies and must not be silently interchanged.
- TPEx's zero/zero/13 pattern is consistent with respecting this boundary.
  It does **not** certify TPEx's historical category coverage, all earlier
  changes, absent/delisted securities, or the economic meaning of every empty
  response. No category-history backfill is approved by this sample.
- This finding does not invalidate raw historical prices, quantify the effect
  on the old strategy, or prove that historical classifications are unavailable
  from every source. Announcement-based reconstruction remains a possible,
  separate acquisition project, not a hidden prerequisite for every candidate.

## Preserved local evidence

Requests used no credentials, redirects or retries, had connect/read timeouts
of 10/20 seconds, and capped each decoded response body at 2 MiB. No production
acquisition code was added. Each local output directory was newly created and
contains `manifest.json` with request/fetch metadata plus the original decoded
response bodies. These hashes identify decoded payload bytes, not compressed
wire bytes. The ignored local probe is not a production downloader or a seal.

Output A: `.tmp/industry-source-probe-20260909-2caa227bc5bf42088aad9583b0489919/`
(fetched 13:53 UTC). Output B:
`.tmp/industry-source-probe-20260909-28d509868d2b4335a17e3f5574cebf9f/`
(fetched 13:58 UTC). Both were fetched on 2026-09-09.

| Output / body file                     | SHA-256                                                            |
| -------------------------------------- | ------------------------------------------------------------------ |
| A / twse-old-digital.body              | `822a985440d4a2017057e604cc7efd028d3713824a6ce168367eaf2933d1b818` |
| A / twse-new-digital.body              | `60d176605d65bfd5564a6d5231d4b7b5b30ab109f04d33c4c49ffe05cc6e14f8` |
| A / tpex-old-digital.body              | `df8e2c3fad4da9bd6577480c3e4b9bf5f4d49be6a51415222aabd7df4e4d30a8` |
| A / tpex-new-digital.body              | `bddee5a1c0ee15f195a634186642fb2d5dbc8614fc05857307c9a7e6c0b7c148` |
| B / twse-pre-announcement-digital.body | `19750880eea9cba4785544b9e16e519dae3c84ed5fc8e040156539531ba21053` |
| B / tpex-pre-announcement-digital.body | `eb6c1f872e032ffbd462b25b25269853fb3b80bdd2c32aa8d0cc414cafd41576` |

Replay the requested dates with `type=36&response=json` against these official
endpoints; a future response may differ, so compare with preserved hashes:

- TWSE: `https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX`, `date=YYYYMMDD`.
- TPEx: `https://www.tpex.org.tw/www/zh-tw/afterTrading/otc`, `date=YYYY/MM/DD`.

## Stop and next action

Stop probing this TWSE route and do not download a matrix of dates/categories.
The original eight-feature lead remains unavailable for PIT replication through
this route. Preserve its identity and old results.

Advance a separately named six-feature, cohort-free **draft** in the
[candidate packet](research-first-candidate-packet.md). It avoids a dependency
on industry membership; it does not inherit the eight-feature lead's performance
or relax the account, execution, stress or independent-validation requirements.
The next source-to-adapter slice must still establish historical pure-stock
eligibility before calculating cross-sectional percentiles. No candidate may
be evaluated until its unresolved metric and execution choices are fixed and
the executable packet is sealed.
