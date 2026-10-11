# Actual-add grouping — completed directional diagnostic

## Conclusion

Do not proceed directly to another post-add stop. In both saved paths, completed
non-hits with actual add fills have positive net cash, while non-hits without an
add fill have negative net cash. This is not the pattern of aggregate net erosion
being confined to expanded attempts. It motivates investigating initial-trial
quality separately from how an unfilled add is handled under delayed execution.

The delay deterioration is arithmetically dominated by the reduction in positive
cash among the actual-add group, not an increase in its negative subtotal. Native
policy consumes the one allowed add at **proposal**, even when that order does
not fill. Saved add fills fall from99/106 proposals to33/79. This identifies a
concrete execution-policy question, not evidence that retrying would improve
profit: quantities, membership, costs, cash and subsequent decisions all interact.
Do not substitute retrospective actual-add membership as an initial signal.

No new strategy has been evaluated or approved. The original delayed account's
52.898222% profit retention remains a failure of its fixed70% requirement.
The zero-anchor exit and ret60 entry-cap failures also remain unchanged.

## Execution and identity

Mission/source `478596b`, release `2c42093`. One offline run completed in
0.828seconds; no new account, feature/price calculation, download, parameter grid
or reserved-period access. Nineteen focused synthetic tests and normal hooks pass.
Parent repaired linkage/denominator/type issues before any grouped outcome was
computed; no outcome-selected algorithm or threshold amendment.

- Packet `diagnostic-v1.json`: `8050be328c7d2014f834e4b199d5705074256df421f1fe6664047b58a9684232`.
- Verified406 input identities and runtime before and after grouping.
- `runs/diagnostic-v1/analysis.json`: `b039bf1a7c4718dac1a7030b9a60a49e9ed578ac180cc6e07136f64290699d31`.
- `runs/diagnostic-v1/receipt.json`: `aaf415f7d1a31bf09df854cbb8d871f9d63764c807ba199d2804718aa9cb5b5f`.
- `runs/diagnostic-v1/process.json`: `3ce147fe9ff49777d3243f9ae1de838ff6e037a73b0fc3e4603d5be40d430e6d`.

Original daily34-event and delayed38-event registry representations, source
packets/runtime and complete native/diagnostic receipts were checked against
the current45-event history. Native event owners, exact ADD signal/order/trace
IDs, code, decision time and actual positive BUY fills reconcile. Neither an
unfilled proposal nor an initial-order partial fill becomes an actual add.

All303 daily and204 delayed native attempts remain present, including4/3 open.
Each group's gross purchases, costs, hit/non-hit count and captured cash reconcile
to the original reports and account summary. Requests sum to714/978, add proposals
to106/79. This is ledger ownership replay and arithmetic, not a cash/fill rerun.

## Fixed whole-attempt partition

These are counts and cash for complete attempts in exposed2019–2023. Each group
contains the attempt's **entire** recorded lifecycle; cash is not allocated into
pre-add versus post-add subperiods and is not the incremental contribution of
the extra shares. Open attempts are not classified as misses or losses.

| Account / eventual actual-add group | All attempts | Hit / non-hit / open | Gross purchases TWD | Costs TWD |
| ----------------------------------- | -----------: | -------------------: | ------------------: | --------: |
| Daily, add filled                   |           99 |             5 /92 /2 |          32,522,300 |   272,616 |
| Daily, no add fill                  |          204 |            1 /201 /2 |          11,666,700 |    87,263 |
| Delay1, add filled                  |           33 |             4 /29 /0 |          10,866,900 |    94,013 |
| Delay1, no add fill                 |          171 |            9 /159 /3 |           9,649,300 |    75,257 |

| Completed non-hits  | Positive cash TWD | Negative cash TWD |  Net cash TWD | Negative count /mean loss TWD |
| ------------------- | ----------------: | ----------------: | ------------: | ----------------------------: |
| Daily, add filled   |      2,658,262.94 |     -1,439,688.00 | +1,218,574.94 |                 51 /28,229.18 |
| Daily, no add fill  |        105,596.00 |       -927,736.46 |   -822,140.46 |                 164 /5,656.93 |
| Delay1, add filled  |        619,608.00 |       -474,766.00 |   +144,842.00 |                 13 /36,520.46 |
| Delay1, no add fill |        148,763.00 |       -747,643.46 |   -598,880.46 |                 123 /6,078.40 |

Thus daily non-hit net1,218,574.94-822,140.46=396,434.48TWD;
delayed144,842-598,880.46=-454,038.46TWD. No captured-hit profit is used to offset
either group's non-hit result. Added non-hits' net falls1,073,732.94TWD, while
no-add non-hits improve223,260TWD; combined deterioration850,472.94TWD agrees
with the prior complete delay report. These are composition-inclusive sums,
not matched-attempt causal effects.

Added non-hit positive cash falls2,038,654.94TWD, while its negative component
improves964,922TWD. No-add positive cash rises43,167TWD and negative cash improves
180,093TWD. Simply reducing adverse transactions did not preserve enough smaller
profitable contributions in the delayed account.

For scale, non-hit net/gross-purchases ratios are4.042673% on30,142,800TWD and
-7.156795% on11,487,550TWD in the daily groups;1.514466% on9,563,900TWD and
-6.666115% on8,983,950TWD in delayed groups. These sum purchases across attempts;
they are not annualized, executable-account returns or drawdowns. Open purchases
are excluded from completed ratios. Per-attempt evidence is in `analysis.json`.

Completed captured-hit cash is2,371,600.67/14,278TWD for daily added/no-add,
and1,361,875/617,129.33TWD for delayed groups. More unexpanded hit labels do not
prove a better strategy: cohort membership, deployment and return denominators
can differ. No individual winning issuer is used for the decision.

## Actual execution opportunity versus proposal

| Quantity                                    |      Daily |     Delay1 |
| ------------------------------------------- | ---------: | ---------: |
| Initial BUY requests                        |        307 |        477 |
| Add BUY requests                            |        106 |         79 |
| SELL requests                               |        301 |        422 |
| Actually filled add orders /add fill events |     99 /99 |     33 /33 |
| Proposed add orders without any fill        |          7 |         46 |
| Add proposal fill fraction                  | 93.396226% | 41.772152% |
| Total added shares across fills             |    496,000 |    113,000 |

The current original rule sets `consumed_attempt_ids` when proposing an add
(`../20261002-momentum-probe/probe_rule.py`), not after a positive fill. This is
documented original behavior, not a newly discovered ledger error. Whether a
different bounded completion policy helps requires fresh decision/cash/fill paths
under a separate prospective card; deleting an unfilled proposal from a report
or assigning it a hypothetical fill cannot answer that question.

A source-only inspection found no early-expiry bug: extra-delay1 schedules at
decision frame+2, and dispatch uses that actual window's expiry. The native
in-memory execution has outcome/termination reasons, but saved schedules only
retain requests/routes/fills/pending. The detailed causes of these46 unfilled
adds remain unknown; neither limits, cash nor withdrawal is inferred. No account
is rerun merely to recover omitted diagnostic fields. A future authorized run
should preserve native outcome/termination evidence if it investigates this seam.

## Boundaries and next decision

Under the card's directional rule, negative no-add non-hit sums in both accounts
keep initial-trial admission/risk as a legitimate research question. The separate
delay decomposition also supplies a specific manual-execution mechanism to assess:
what happens after an add is proposed but never filled. It does not justify an
automatic retry policy, an unlimited order chase, a changed stop threshold or
another retrospective filter. No new candidate parameters or process are released.

Actual-add membership is a retrospective state influenced by prior gains, price
limits, cash and competition; groups are not randomized controls. Without a
counterfactual rerun, no estimate of the marginal add's contribution is possible.
Non-hit attribution is not full-account drawdown. Open cash outflows retain stock
value and must not be read as completed losses. Existing waiting/drawdown/turnover
reports remain the authoritative whole-account context, not recomputed here.
Final owner loss-budget agreement, manual stresses, material sensitivities and
independent/forward validation remain unresolved. Broad research goal stays active.
