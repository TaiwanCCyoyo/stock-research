# P1-A freshness prerequisite handoff

Recorded 2026-11-02. Definition `order-card-freshness.v1`; engineering only, with
no market observations or operation cards. The [contract](data-contract.md) was
recorded before implementation. Delivery and validation are tracked in the
[continuation record](../../docs/en/decision-records/2026-11-02-long-term-research-engineering.md).

## Public interfaces

| Interface                                                                                                | Responsibility                                                                                                                                                               |
| -------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `research_core.multi_timeframe_ma_weeks_v1.assess_calendar_range(snapshot, first_day=..., last_day=...)` | Inclusive civil-day evidence using existing `CalendarSnapshot` / `CalendarFact` / `DayCoverage`; missing dates stay unknown. Existing week assessment behavior is unchanged. |
| `research_core.order_card_freshness_v1.FreshnessRequest`                                                 | Expected latest session, universe and nonempty tuple of `DatasetRequirement(dataset_id, definition, generation)`. No strategy profile defaults.                              |
| `DatasetObservation` in the same module                                                                  | Declared dataset/definition/generation/calendar/universe identity, as-of session, availability instant, status and source reference.                                         |
| `assess_card_freshness(request, calendar, observations)`                                                 | Pure assessment returning frozen `FreshnessAssessment`, including all calendar-day evidence and dataset assessments. No root lookup, clock or I/O.                           |
| `research_core.order_card_freshness_json_v1.parse_packet` / `assess_packet` / `result_to_json_document`  | Explicit JSON schema validation and projection; retain nulls, source metadata and stable reasons.                                                                            |
| `read_and_assess_packet(path)` in the JSON module                                                        | Read only the named packet, at most 1,000,000 bytes; reuse `artifact_store.safe_path` and `json_integrity.strict_json_object`.                                               |
| `scripts.check_order_card_freshness`                                                                     | Thin CLI. JSON assessment on stdout; invalid-input diagnostics on stderr. Exit 0 = freshness passed, 2 = withheld, 1 = invalid declaration/read failure.                     |

Python date fields must be normalized timezone-naive `pd.Timestamp` values.
Instant fields must be aware; comparisons and output use Asia/Taipei. JSON dates
use `YYYY-MM-DD`; instants use ISO timestamps with seconds and an explicit
offset or `Z` (up to nine fractional digits). Unknown values use explicit null
only where the contract permits it. All fields are required; unknown fields,
duplicate JSON object keys, nonfinite constants and malformed values are errors.
Calendar facts must already have unique increasing dates. Duplicate/unexpected
dataset IDs are errors; missing observations and valid but mismatched identities
produce withheld assessments. Dataset output is sorted by dataset ID.

Top-level reasons include `expected_session_future`,
`expected_session_not_known_session`, `newer_session`, `dataset_not_ready` and
the existing calendar coverage reasons. Per-day evidence preserves the affected
date; per-dataset reasons identify identity mismatches, unknown availability,
future availability and incomplete status. A passing dataset alone cannot make
an incomplete calendar pass.

## Complete artificial example

From the repository root:

```console
uv run python -m scripts.check_order_card_freshness --input tasks/20261102-order-card-freshness/synthetic-packet.json
```

The tracked [packet](synthetic-packet.json) invents one session, two explicit
closures and one daily dataset. It should return exit 0 and
`"freshness_ready": true`, three calendar-day rows and one dataset assessment.
This is an illustration of declaration consistency, not evidence of actual
exchange dates or a recommended strategy input set. The command creates no file.

Removing a closure fact withholds with `missing_fact`; setting the observation
to an older as-of session withholds with `as_of_session_mismatch`, even if its
availability timestamp is recent. Adding a newer known session withholds with
`newer_session`. An in-progress session also withholds this after-close gate.

## Remaining integration work

A future caller must select its strategy's required daily datasets, authenticate
calendar/source facts, and provide appropriate versions and universe coverage.
This assessment certifies declared metadata consistency only. It does not certify
source truth, monthly revenue completeness, full history/PIT, all strategy
inputs, a valid strategy, card contents or permission to trade.

There is no real reader, card/sizing/stop generator, Dashboard integration,
deployment, F1 start, receipt or market calculation. Existing dashboard freshness
display tolerances are not a substitute for this stricter daily prerequisite.
The S7 first-confirmation/empty-week assembler, scale-invariance, E2/E3 and O2
gates are unchanged. #137's interactive discussion and JSON download remain its
owner's work; this local CLI does not implement that interface. Final report-page
acceptance remains with the owner.
