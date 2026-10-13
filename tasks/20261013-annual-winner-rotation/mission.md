# Taiwan previous-year winner rotation v1

Registered 2026-10-13 before any annual ranks or strategy returns were viewed.
Owner request: independent Taiwan-only study of buying last year's winner and
holding until the next annual rotation. This is separate from PR #14 and the
pattern-scan mission. This request explicitly authorizes the bounded evaluation;
no other study's confirmation/holdout, producer download or scheduler is opened.

## Question and claim boundary

The supplied GURGAVIN screenshot reportedly compares $100 invested from January
2012 through October 9, 2026: S&P 500 about $800 versus $176,114 from its previous
year's best constituent, including dividend reinvestment. These are third-party
claims. Taiwan evidence cannot verify these US amounts. Formal Library transfer
failed at Windows `os.setxattr`; local image inspection remains unavailable. The
parent's visually checked transcription is the source pending local verification.

We distinguish all-Taiwan-stock leadership from PIT index-constituent leadership.
No reliable historical index membership/delisting census is currently available.
Therefore this version is a covered-history development study, not an unbiased
test of either complete market universe or a trade recommendation.

## Fixed selection and windows

- Read historical quote codes, not a present-day ticker list. Main operational
  scope: four-digit codes beginning 1-9, excluding 91xx depositary receipts,
  with official TWSE/TPEx quote observations. Current metadata classifies security
  type only when available; missing type is explicitly unknown, not silently
  discarded. It cannot certify historical venue/security status. Emerging-market
  Shioaji observations are excluded from ranking. Report historical source and
  candidate exclusions separately. No requirement for survival after selection.
- Prior complete calendar year: previous year-end close to current year-end close.
  For 2010 only, first 2010 close is the initial anchor (2009 is unavailable).
  A new listing without the initial anchor is not comparable and is excluded.
  Every intervening market-calendar quote must be observed and valid; missing or
  suspended days yield an unknown rank, rather than filling prices.
- Ranking uses the explicitly estimated economic cash/split reinvestment model
  below. Select its highest calculable return; equal exact floats sort by code.
  This is a **known-return leader**, not a certified market champion when any
  candidate has unknown returns. Preserve every candidate/reason/return. Never
  choose based on next-year quality or replace the leader after holding failure.
- Enter at first positive-volume valid observed raw open in the next year.
  Sell at the first positive-volume valid observed raw open on/after the next
  annual calendar boundary. Record any delay. Missing exit leaves the holding
  unresolved; no liquidation at the last convenient price.
- Begin trading in 2011 if coverage permits; also report 2012-2025 and a data-quality
  diagnostic from 2013. Complete rotation periods end at the next year's open;
  2026 is mark-to-last-covered-close YTD, separately, without annualization or
  mixing into full-year significance tests. Use common entry/exit dates for 0050.

## Economic and execution model

Raw OHLC supplies entry, exit and marks. Reuse `price-basis.v2` for quality and
reference-factor diagnostics. Reference-factor-restated ratios are not cash
reinvestment and must not become economic returns or actual trade prices.

The economic scenario uses cash dividend **estimates** on the ex-date, immediately
reinvested at that day's raw close into fractional units. This assumes available
cash and fractional/odd-lot fills; payment dates, dividend income tax and personal
health-insurance levies are unobserved, so it is an idealized scenario. Ex-date
events at an entry open confer no dividend on the new purchase. Exact externally
verified split ratios may change units; rounded exchange price factors never
infer shares. Rights, mixed rights/dividends, reductions, ambiguous duplicate
events, negative/missing cash and unknown events give unknown economic returns.
Never replace such entitlements with zero or a factor-restated profit.

Gross is no fees. Net uses per-side 0.1425% brokerage, 0.3% stock sell tax,
0.1% ETF sell tax and 10 bps adverse entry/exit price assumption; dividend
reinvestment also pays brokerage. These are fixed scenario assumptions, not
observed charges/fills. No minimum fee or integer-lot account is claimed.
0050 buy-and-hold with the same dividend scenario is the benchmark, not TAIEX
price-only. Annual paired benchmark periods use identical actual strategy dates;
the continuous benchmark pays only initial/terminal costs.

The fixed sensitivities are top5 equal initial weights (at most five holdings,
no in-year rebalance) and avoiding one-price OHLC days on either trade side.
One-price avoidance is a conservative observable scenario, not historical proof
of an inaccessible queue or a reconstructed statutory limit. Missing OHLC/volume,
halts, limits and dividend reinvestment queue are disclosed. No real orders.

## Inference and acceptance

No parameter search. Full-market, unbiased significant outperformance is only
established if universe/entitlement/fill evidence is adequate, all primary periods
are measurable, net wealth beats comparable 0050, one-sided paired annual log
excess sign-flip p<0.05, and seeded iid annual bootstrap 95% lower bound>0.
These are study-chosen diagnostic thresholds, not owner investment guarantees.
Symmetry/iid assumptions, <=15 complete annual observations, exposed history and
coverage bias limit inference; p-values cannot repair data quality. Incomplete
years cannot be cherry-picked into a full strategy CAGR or significance verdict.
Report concentration, best-one/best-two removal of paired years, worst year,
daily drawdown (if complete equity exists), unknowns and gross/net separately.

## Work and preservation budget

No download. Reuse physical hook-produced snapshots with their receipt; source
alignment must be false. Existing shared price bases cover only 25 stocks from
2019 and cannot answer this question; benchmark context is not total return.
Estimate ~2,000 stocks x17 short yearly slices (~33k rows), plus at most 6 held
names/year, under 2 GB observed process memory and <=2 admitted workers.
Measure representative serial and two-worker wall/CPU/memory/I/O/startup before
full computation; choose from measurements and preserve global ranking barrier.
Source/runtime/input pins and every process table are published additively through
PR12 `publish_bundle`/`DataCatalog` in primary `research_data/`; worktrees read
explicit versions through `STOCK_RESEARCH_DATA_ROOT`, without links/copies.
Small task results and the research-program index carry the conclusion and pins.

Session-owned checkout: `D:/Project/stock-research/.worktrees/annual-winner-taiwan`;
branch `codex/annual-winner-taiwan`, initial base
`061cde263b1a03fc845099a2e4b1c3007baafd70`. Other worktrees are not this session's
property and are preserved. Delivery is draft PR; merge belongs to the owner.
