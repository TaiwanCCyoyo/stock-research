# Account data readiness: current evidence, not a new download request

2026-10-05. Read-only inventory for the prospective [mission](mission.md). No
market study, data copy, refresh or corporate-event reclassification performed.
Coverage below is reported by existing source audits, not independently rescanned
in this inventory. Exact input hashes belong in the later execution packet.

**Additive correction, 2026-10-05:** the first inventory below stopped too early
at monthly evidence. A later retained daily identity projection and verified
price/factor join already exist. They support conditional development within
2019–2023; do not restart membership acquisition from the older 005/006 gaps.
This correction does not certify complete historical PIT or revise old results.
See [the selected source contract](source-contract.md) for the narrower first
account slice and the remaining source-to-execution work.

## What changed since the September audit

Canonical producer: `D:/Project/Stock/shioaji_stock_prices`, observed clean at
`3e6cbef0d285a0f10358629c4894504a6274702c` (merged producer PR #6).
The delegated Git identity read hit a permission boundary; the parent repeated
that same read in the authorized context. No producer mutation was needed.

The producer's `docs/data-gap-repair-20261004.md` records completion of 4,105 TWSE
day units through 2026-10-02, adding 260,028 rows and 182 previously absent codes
to `data/official_daily.sqlite`. Old rows were preserved. This resolves part of
the old acquisition gap; do not demand those downloads again from the old audit.
New codes are historical observations, not automatic proof of ordinary-stock
identity, delisting, uninterrupted issuer continuity or complete daily membership.

The same audit explicitly leaves `data/price_daily.parquet` at the stable vintage:
6,576,397 rows / 2,075 codes, before the SQLite expansion. A gitlink change or
SQLite repair does not refresh this file or any research worktree snapshot.
The previously sealed atlas remains on its original data, unchanged.

## Existing evidence to reuse before acquiring anything

All producer-relative paths below are under the canonical producer above; Stock
scratch paths are under `D:/Project/Stock`. These are local evidence locations,
not a claim that Git clones contain the raw inputs or that `.tmp` is durable backup.

| Evidence                                                                                                                      | What it supplies                                                                                | Boundary still relevant to an account                                                                                         |
| ----------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `data/official_daily.sqlite` and `docs/data-gap-repair-20261004.md`                                                           | Repaired daily official prices, append-only audit and independent date comparison               | Per-security coverage/type/continuity differ from date coverage; no implicit metadata join                                    |
| `data/price_daily.parquet`                                                                                                    | Stable pre-repair merged snapshot                                                               | Does not contain all new SQLite history; sources/units must not be silently spliced                                           |
| `data/symbol_meta.sqlite`                                                                                                     | Current security/market reference                                                               | No complete effective-dated type history; current-reference cohort cannot certify PIT                                         |
| `.tmp/claude-research-inputs-20260910-1904a2d3fb2745969024af914a8ed724/identity/security_identity.csv`                        | Fixed TWSE monthly seeds and selected dated events                                              | Monthly presence/absence is not daily lifetime or historical exact available_at                                               |
| `.tmp/claude-download/005-artifacts-46d07a89845348c0b1757f988d53dfce/termination-corrections.csv`                             | Corrected 76 endpoint candidates; 43 official termination dates, 33 fund/ETF monthly-seed cases | Supersedes the old 192 month-end termination interpretation, not an assumed liquidation price                                 |
| `.tmp/claude-download/006-codex-data/tpex-monthly-summary.json`                                                               | 72 months in 2018–2023, five categories / 360 retained responses                                | 71 consistent monthly sets, one retained discrepancy; not a daily pure-stock/PIT certificate                                  |
| `data/corporate_actions.sqlite`                                                                                               | Seven configured source range/hash audits; factors and dated action observations                | Price factors do not prove actual cash/shares or historical availability; ETF split view is not ordinary-stock split coverage |
| `.tmp/claude-download/005-artifacts-46d07a89845348c0b1757f988d53dfce/dividend-amount-events.csv` plus `006-codex-handback.md` | 324 amount-stated records and five disputed-event replays                                       | Revision chains and economic event binding incomplete; source refusal is not absence of dividends/revisions                   |

No complete canonical ordinary-stock split/economic-event package was established
by this inventory. That means unverified, not proof that the public data does not
exist. The September source-blocked MOPS requests are not reattempted here.

## Reusable implementation and the smallest remaining work

The later source chain is `.tmp/claude-kline/021-development-universe-policy.md`
→ `022-daily-membership/projected-v2/observed-identities.parquet`
→ `026-market-runtime/readset.py::load_market_readset`. Its preserved binding
receipt covers 2,528,056 market/code/date keys, 1,463 dates and 1,895 codes over
2018-01-02..2023-12-29; 1,194 innovation-board keys are retained but excluded from
scoring. The daily membership artifact and reader hashes were rechecked against
that receipt. Membership does not use today's metadata; source completeness and
original publication times remain unverified, with the latter explicitly null.
The 18:00 availability timestamp is a separately named development assumption.

`026/feature_panel.py::forward_signal` can supply the causal reference-price
index, but its `build_feature_panel` has the old six-feature/120-prior-bar gate.
Do not inherit that eligibility or its ranks for H05. `027-cash-runtime` already
binds cash terms to the existing ledger provider; source-bound share, capital,
halt and execution-limit adapters also exist in the preserved evening-pilot /
momentum-probe tasks. Audit their actual leaf functions and explicit source
terms, not the incompatible add-retry launcher chain. Unknown held entitlements
still stop affected measurement; an empty list is not domain completeness.

Use current `research_core/chronology.py`, `auction.py`, `decision.py`, `ledger.py`,
`attribution_inputs.py` and `attribution.py` rather than another simulator. Existing
synthetic coverage includes exact cash, fees, claim capacity, delayed payment
attribution and share-delivery mechanics. New testing covers only the new policy.

Historical adapter reference: preserved commit
`919aef7211255e54b6f22b94d4ab7e698641fcca`,
`tasks/20261002-momentum-probe/runtime.py::build_account`. It has a decision-transform
seam but depends on prior task launchers and `.tmp/claude-kline` prototypes. The
later add-retry wrapper forces probe/add sizing and reads `recorded_events`, which
the current DecisionContext does not expose. Do not copy that single file and
call the new strategy integrated. Existing result records remain unchanged.

Next adapter work must bind the mission's current-day feature provider to a
source-supported ordinary-stock universe, and separately bind next-session quotes,
limits/capacity/terminal reports and corporate economic events. Use the repaired
canonical sources through their existing export/snapshot interfaces when a later
scope requires them; the first selected slice reuses the retained 026 readset,
not a silent mixture with October repairs. Coordinate
writers before any physical snapshot. Do not copy a live SQLite file directly.
Only material unresolved inputs should trigger a scoped acquisition task. Do not
wait for every classification or source to become perfect before completing the
independent thin-policy work; equally, do not label a survivor-only diagnostic an
executable, independently credible account result.
