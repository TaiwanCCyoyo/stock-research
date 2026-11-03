# L1 volume comparison JSON contract v1

This contract describes saved comparisons on one fixed L1 union cohort. It is a
research-data interface for a display adapter, not a second outcome definition,
an execution API, a new holdout, or an approved stock-selection strategy.

Authoritative producer: `research_core.pattern_scan_comparison_v1.build_l1_comparison`.
Portable structural schema: `comparison_json_schema()` in the same module.
Integration fixture: `scripts/tests/fixtures/l1-volume-comparison.synthetic.v1.json`.
The fixture is entirely synthetic. It includes zero denominators, overlapping
unknown/censored cases, all four cells, unavailable conditions, and a selected
stock without events. Its numbers must never be presented as market findings.

## Envelope

| Field                                               | Contract                                                                                                                                                                                                                                            |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema_version`                                    | Exact `l1-volume-comparison.v1`. Reject other versions.                                                                                                                                                                                             |
| `synthetic`                                         | True exactly when `provenance.scope` is `synthetic`.                                                                                                                                                                                                |
| `provenance.scope`                                  | `synthetic`, `pilot`, or future `full`; current recovery is at most five stocks.                                                                                                                                                                    |
| `provenance.data_id`                                | Saved source identity, including its fixed catalog/bundle version when applicable.                                                                                                                                                                  |
| `provenance.definition_id`, `source_id`, `input_id` | Explicit definition, original numerical-source and input identities. Never infer them from a filename or current data.                                                                                                                              |
| `provenance.base_label_version_id`                  | Original immutable base-label version; does not assert that base labels equal effective event outcomes.                                                                                                                                             |
| `provenance.code_commit`, `generation`              | Producing code identity and original price-generation lineage. Synthetic values are explicitly synthetic.                                                                                                                                           |
| `provenance.actual_selected_stocks`                 | Unique stock identities; may include zero-event stocks. Pilot maximum is five.                                                                                                                                                                      |
| `provenance.historical_exposed`                     | Always true for this historical comparison; cannot be relabeled unseen validation.                                                                                                                                                                  |
| `provenance.validation_scope`                       | Explicit booleans: `input_structure_verified`, `full_q1_parity`, `marginal_parity`, `unseen_validation`. In-memory structure checks do not certify market-source integrity. Synthetic/pilot must not claim full parity; unseen validation is false. |
| `cohort`                                            | `pattern_id=L1`, `cohort_id=union`, horizons `[126,252]`, and unique event count before conditions.                                                                                                                                                 |
| `horizons`                                          | Exactly one entry each for H126 and H252. Each contains `cohort`, four `cells`, and eight `unavailable` status combinations.                                                                                                                        |
| `semantics`                                         | Versioned outcome/count/denominator descriptions from the producer.                                                                                                                                                                                 |

## Cells, counts and unavailable inputs

The four `cell_id` values combine `vol_le_0_7` / `vol_gt_0_7` with
`g_ge_1_5` / `g_lt_1_5`, separated by `__`. Boundaries are VOL_a <= 0.7 and
G >= 1.5. The cohort is selected from already cooled saved L1 union events
before these conditions; no cell is independently cooled. Conditions and cell
membership are identical across horizons, while outcomes and eligibility may differ.

Each cell has `summary`, `evaluation_status`, and `references`. `summary` is the
unchanged output of `research_core.pattern_scan_rates_v1.summarize_events`:

- `event_n`: all events in the cell; `distinct_stock_n`: event-bearing stocks.
- `known_n`: effective outcomes admitted to the full-calendar main denominator.
- `hit_n`, `loss_n`, `flat_win_n`: main-eligible labels, summing to known_n.
- `unknown_n`: all effective unknown outcomes; `censored_n`: incomplete calendars.
  These overlap and are never interchangeable with loss.
- `excluded_known_n`: full-calendar known outcomes excluded from the main denominator.
  Explicit eligibility exclusions are separately recorded as
  `full_eligibility_excluded_n` and `censored_eligibility_excluded_n`.
- `hit_rate` and `loss_rate` use known_n. Bounds use their separately recorded
  potential denominators. Zero denominator means JSON null, never zero percent.
- Observed-hit, full-calendar, potential and per-stock diagnostics retain their
  existing definitions. Do not sum distinct stocks across cells or years.

`unavailable` retains every combination of G/VOL_a statuses `known`,
`feature_unknown`, `not_applicable` except known/known (eight combinations).
Each contains the same summary/evaluation/reference fields plus reason counts.
The four cells plus unavailable rows partition event counts at each horizon;
unknown condition input is never assigned to a negative condition cell.

`evaluation_status.status` is `not_evaluated` for both synthetic and pilot
payloads, even though illustrative or pilot counts exist. The reason is
`synthetic_only` or `pilot_only_no_full_research_validation`. A future full payload
can be `evaluated` only with separately accepted full Q1 and marginal parity;
its reason remains `historical_descriptive_only`, not strategy approval.
The builder checks assertions' consistency but does not authenticate their evidence.

References contain only `event_id`, `security_id`, `t0` (ISO date) and `horizon`.
At most three are selected deterministically by stock/date/event identity per
cell. They are trace pointers, not representative examples, URLs, filesystem
paths, or permission to fetch/recompute anything. Empty cells have no references.

## Consumer checks and execution boundary

The JSON Schema checks structure; the typed consumer must also reject duplicate
horizons/cells, inconsistent scope/synthetic/evaluation fields and malformed
count invariants. Treat the schema's fixed order/keys as the producer contract,
not an invitation to infer absent rows or convert unavailable/null values to zero.
Keep provenance, scope, denominators and unevaluated status available alongside
the display. The UI owns rendering only and must not implement outcome rules.

The 2026-11-03 authorized work is recovery engineering, synthetic integration and
a maximum-five-stock pilot. It does not authorize full-market recovery or a new
full-market four-cell study. A pilot's old-event/condition parity is different
from reproducing the saved full Q1 and marginal tables. Current full-market
parity is not evaluated. No report, frontend route, production service, download
or schedule is changed by this contract.
