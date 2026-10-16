# Annual winner holding completion v2

Registered 2026-10-16 under the owner's request to complete the earlier experiment.
This is a post hoc, exploratory completion of the **fixed v1 selected sequence**,
not a new full-market winner ranking. No v2 holding return has been evaluated.
The v1 mission, source, input bundles, results and original report remain historical.

## Question and identity

What would the v1 known-return leaders have returned if the previously captured
share events and official no-quote evidence were admitted under an explicit
holding policy? Definition: `annual-holding-completion.v2`. Keep 2011–2025 complete
holding periods and a separate 2026 YTD through 2026-10-12. The cutoff is unchanged
so a date extension cannot be mistaken for a model correction.

The selection sequence and original dates come from the Git-published PR #15
report (`4706cc4b26ba77e1c6d059adb307173d059f9194`), checked against the current
unchanged report. Do not re-rank only the seven supplemented winners: the other
unknown candidates have not received equivalent evidence. No claim of complete
historical eligibility, delisting coverage or all-market leadership is possible.

## Inputs and source admission

Read canonical producer raw prices, actions and metadata in place, with
`producer_data_root()`, a verified idle writer, stable reads and an input
fingerprint. Do not run legacy `prepare`, initialize a worktree submodule,
copy producer databases, or build a private adjusted-price dataset.

The existing 178-member supplement is captured source evidence, not a completed
economic model. Preserve its original bytes and publish a discoverable, additive
canonical producer batch before evaluation. Reuse existing producer projection
code for MOPS rights statements; the research layer consumes its data. Keep
displayed announcement dates separate from API lookup dates and disclose
unverified revision completeness, actual payment, exercise and delivery.

Admit only source-linked ordinary-share terms with explicit units and ex-dates.
For cross-source terms use the issuer value only after agreement at the fixed
precision in `holding-policy-v2.md` R8. Never average source values, infer stock
rights from a price factor, or map missing terms to zero. Check R3 corroboration (an explicit exchange share ratio or reference price)
and R6 date-shift evidence before admitting a distribution. Noncalendar
date shifting requires the documented market closure and exchange rule.

## Holding economics

Implement a new `research_core.annual_rotation_v2` kernel; leave v1 unchanged.
Apply the R2–R8 economic and quote rules in `holding-policy-v2.md` with the
following execution and reporting clarifications:

- Cash dividends retain v1's estimated, immediate ex-date fractional reinvestment.
  This is an assumption, not observed payment or an executable account.
- Free shares, no-refund reductions and par-value exchanges change units from
  explicit source ratios. Cash and bonus components use the pre-event units.
- Rights have two fixed scenarios: `lapse` (zero credit) and `realize` (immediate
  intrinsic-value realization and reinvestment). Neither is an actual exercise
  history or a proven bound. Preserve both results regardless of performance.
- An H/N day may carry a mark only if official evidence supplies that day's
  classification and no valid OHLC exists. A partial bad quote, duplicate or
  unexplained jump is not excused. Do not infer a zero-trade day from an absent
  row or from the conflicting 3162 trade counts.
- Every event that reinvests cash needs an observed same-day close. A carried
  mark never supplies that price. Non-cash quantity changes need their explicit
  effective/resumption rule. Unrelated unsupported actions stay unknown.
- An entry-day entitlement is not received. A share-changing event at an open
  exit is unresolved except the existing exact ETF split convention.
- 5314's open-ended October halt covers only the documented start day unless
  later dates have their own evidence; all intervening dates must be checked.
- Commission 0.1425%, stock sale tax 0.3%, ETF sale tax 0.1%, and 0.1% adverse
  slippage per side stay unchanged. Reinvestment pays commission.

Evaluate all 15 fixed holdings under the same v2 kernel, not only favourable or
previously missing years. Compare the eight previously calculable years with v1;
report any data-vintage or definition difference rather than forcing agreement.
Top5 and one-price-avoidance arms are not completed by a seven-winner supplement
and remain outside this bounded completion.

This new execution contract replaces the old draft's G1/G2 legacy binding for
this run only: selections are fixed by the published Git report, rather than
claiming `reuse_rank_rows` accepted a changed live-input vintage. Synthetic v1/v2
parity and paired evaluation on the same current inputs validate unchanged
economics; historical input/source bundles and their verifiers remain untouched.

## Aggregation and claims

Chain holdings only if every terminal result exists and each exit equals the
next entry. Otherwise the full strategy terminal value and CAGR stay unknown;
do not multiply a selected subset or silently overlap funded positions.
Compare the complete strategy with continuous 0050 over identical endpoints;
also retain the annual paired, annually charged 0050 comparison separately.
Report gross/net, 2011–2025, 2012–2025, and 2013–2025 windows independently.
Run the existing seeded paired diagnostics only for complete windows, labelled
exploratory; unchanged v1 thresholds do not overcome unknown rank candidates.

Daily drawdown remains unavailable as a complete observed-equity metric when
any day is carried; a carried-mark reference may be shown with its count and
label. 2026 YTD is separate and never annualized. Conclusions about beating the
benchmark must identify which rights scenario they describe; agreement of two
scenarios is not proof about all real exercise behaviours.

## Cost and retained artifacts

This completion has at most 16 selected stock-years plus 0050. Start serial;
record phase wall/CPU time, memory and bytes before considering workers. A
full-market reranking or feature build is not needed for this fixed sequence.
Reuse shared statistics and endpoint helpers, but do not substitute adjusted
close momentum for economic total-return ranking.

Fingerprint live input files once; retain stat/WAL stability checks at receipt
publication. Verify the small supplement once per process and hash consumed
result bytes once. Do not replay the legacy source-copy/delivery hash chain or
weaken byte-at-consumption protection. Record phase timings and retained bytes.

Keep small results, parameters, receipt, admission audit and report in a named
`publications/completion-v2/` publication beside the study. Keep large raw captures only in
the producer canonical batch. The HTML report presents latest and historical
versions with explicit definitions, cutoff, lineage and gaps; it derives its
numbers from the saved summary, never from an API recalculation.
