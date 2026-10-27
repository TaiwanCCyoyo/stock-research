# E1-B2b: in-memory reader staging handoff

Definition: `entry-window-inputs.v1`. Contract: [entry-window data contract](data-contract.md)
and [mission](mission.md). This is a pure engineering boundary with synthetic
validation, not a real reader, PIT certification, study result, or compute admission.

Owner: the E1-B2b task-17 session. Its single isolated checkout is
`C:/Users/xjp01/Documents/Codex/2026-10-27/task-17/repo`, branch
`codex/entry-window-inputs`, based on fetched `origin/main`
`9945d6878e1b3be530e4790ef8fd3a5db6dbcc7a` (merged PR105).
No other checkout was modified or cleaned. PR105's merged state and merge SHA
were independently checked through the GitHub connector. The pre-creation
registered worktree list, open PR collection (empty), task branch refs and the
three allowlist paths were checked for conflicting implementation; no overlap
was found. The repository's full pre-creation inventory completed for 21
registered worktrees; that snapshot is not a cleanup authorization. This session
owns one worktree and retains it for review and eventual integration.

## Public API and invariants

```python
from research_core.entry_window_inputs_v1 import (
    InputRequest, CanonicalPacket, RawQuotePacket, IntervalPacket,
    OfficialLimitsPacket, StagedInputs, stage_stock_inputs,
)

staged = stage_stock_inputs(
    request, canonical=canonical_packet, raw=raw_packet,
    intervals=interval_packet, limits=official_packet_or_none,
)
# A caller may subsequently invoke the merged B1 public API:
# entry_window_v1.count_stock(staged.calendar, staged.stock, staged.quotes)
```

Packet constructors use keyword arguments. The request requires `security_id`,
`generation`, normalized timezone-naive `pd.Timestamp` `study_as_of`, full
`pd.DatetimeIndex` `common_calendar`, `universe_id`, and `calendar_id`. Every
packet repeats these identities with its own explicit `calendar` and a nonempty
`source` description. The calendar is normalized, timezone-naive, unique,
increasing, without NaT and in B1's 2010+ era domain. Exact original date
positions must agree, not just lengths. Explicit Saturday sessions remain valid;
this module does not establish that a calendar is official.

- `CanonicalPacket` supplies `stock`, `definition="momentum-only.v1"`,
  `basis="reference_factor_adjusted"`, and `availability_note`. The stock ID,
  all canonical labels/main-eligible masks and horizon calendar-full masks,
  A1/A2/A3 and every supplied atom, eligibility, jump, C52w and ret120 are
  validated. All original arrays, including non-E1 labels, are retained.
  Missing labels are rejected; no labels or eligibility are calculated.
- `RawQuotePacket` supplies `basis="raw"` and `raw_open/high/low/close`.
  Every price array must already be one-dimensional `np.float64`. Float32,
  object/mixed precision, integer prices and wrong shapes are rejected before
  arithmetic. Once upstream has cast a low-precision source to float64, dtype
  validation cannot recover that lost provenance; adapters must preserve it.
- `IntervalPacket` supplies `action_to_next`, `event_quality_to_next`,
  `quote_quality_to_next`, exact-int8 `event_coverage`, and `coverage_note`.
  States are -1/0/1. Coverage means unknown/incomplete/explicit complete
  coverage. For rows having t1, action=0 or event-quality=1 requires coverage=1.
  Action=1 with incomplete coverage can be retained with non-good event quality
  and is never clean. No empty table or unit price factor establishes no-action.
- Interval states remain on t for `(t,t1]`. `OfficialLimitsPacket`, when present,
  supplies official `source`, `basis="raw"`, float64 `lower/upper` and quality
  tri-states on the quote session. B1 applies the fixed next-session offset.
  Missing limits stay `None`; unknown limits do not alter Q/M or imply a fill.

The result borrows the validated stock, calendar and arrays without changing
them or their writeability. Callers must not mutate them during use. Missing,
non-finite and nonpositive float64 bars remain at their original positions for
B1 classification. There is no sort/join/drop/ffill or per-stock next-valid-day
substitution. The final row cannot acquire t1 from declared interval states.
The immutable `alignment_record` has only identity/source/basis/note metadata;
its `validation_scope` explicitly limits the claim to consistency of upstream
declarations. It contains no price/label arrays, strategy verdict or PIT claim.

## Genuine reader gaps: source unavailable / adapter pending

Only tracked implementation source was inspected; none of these readers was
called on real inputs.

1. `maintained_adjusted_daily.read_adjusted_daily(basis, codes=..., generation=G,
as_of=..., calendar=...)` is the public raw/reference-factor-adjusted access
   path. A future adapter must preserve every common-calendar position and
   missing bar, retain one fixed generation/as-of, and check compatible records.
   Its actual use remains behind owner/data admission.
2. `maintained_adjusted_daily.read_official_quotes(codes=..., as_of=...,
generation=G)` returns quotes, generation calendar and record. Its source
   docstring states that duplicate dates repeat the first row and that corporate
   actions are not included. It cannot directly prove a unique common calendar
   or clean interval absence. Silently deduplicating its result does not satisfy
   this staging boundary or the pending adapter policy.
3. The adjusted family's action snapshot retains price-factor adjustment
   information, not proof of complete coverage of all corporate events over
   `(t,t1]`. Executably verified whole-interval event coverage and quote-quality
   adapters remain `source_unavailable` / `adapter_pending`. Never replace them
   by empty-events/factor=1/no-action guesses. Official bounds and provenance
   adapters also remain pending; a source string is only an upstream declaration.
4. Real canonical loading, S6/atoms/effective-label compatibility, original label
   admission, same-calendar alignment, generation compatibility and PR61 parity
   belong to a separately admitted reader/runner package. No warning was removed
   by opening real inputs. There is no loader callable, path parameter, CLI or
   implicit shared-root fallback in this module.

## Synthetic verification and remaining gates

Focused command:

```text
uv run pytest scripts/tests/test_entry_window_inputs_v1.py -q
```

Final focused verification: **146 passed in 1.27s**. Cases include official
quality shape/enum, overlapping quality losses with Q present, and official-bound
quote-session alignment.
All StockDaily labels were constructed manually. Tests cover exact identities
and calendars, complete canonical keys, float64 endpoints and precision refusal,
missing middle opens, Saturday/year/terminal behavior, explicit coverage,
overlapping diagnostics with deduplicated Q/M losses, count conservation, and
complete equality of B1 rows/diagnostics against directly constructed Quotes.
Read-only arrays remain unchanged through staging and public B1 counting.
One fixture forbids maintained readers, canonical label construction, filesystem,
SQLite and network entry points while staging and B1 counting still succeed.

Normal hooks are required on the final changes. Shared CI/asset integration is
**staged below only**, as instructed by the parent. Until a single writer applies
it and current-head hosted CI and independent Astra review complete, this package
is **not merge-ready**. Publication is held pending the parent's explicit bundled
authorization; local work does not substitute for a delivered draft PR.

No market prices, real labels, holdout, forward outcomes, production data roots,
downloads, generation holds/updates, scratch research runs, scheduler or deployment
operations were used. Real reader/data/label/compute and original owner gates
remain in force after an eventual code merge. No study card or result changed.

## Staged shared integration: one parent-assigned writer only

No shared file has been edited by this package. Apply these additive changes to
the latest integrated main; preserve all sibling package entries.

`scripts/ci_test_domains.json`: append to existing `entry_window.paths`:

```json
[
    "research_core/entry_window_inputs_v1.py",
    "tasks/20261027-entry-window/reader-staging-handoff.md"
]
```

Append `scripts/tests/test_entry_window_inputs_v1.py` to `entry_window.tests` and
`reviewed_tests`. B1 core and canonical/oracle dependencies are already in this
domain; keep their mapping so changes select both B1 and B2b tests.

`scripts/tests/test_ci_scope.py`: extend the existing E1 owned-path A/M matrix
with this module, new test and handoff, and replace its B1-only expected test set
with all current E1 tests. For any changed E1 test, retain the selector test itself
as a consumer. Add the following case using the same domain-derived expectation;
the existing canonical dependency matrix must also include B2b in its assertions:

```python
@pytest.mark.parametrize("status", ["A", "M"])
def test_entry_window_core_selects_staging_consumer(status: str) -> None:
    manifest = ci_scope.load_manifest()
    plan = ci_scope.make_plan([(status, "research_core/entry_window_v1.py")])
    expected = {
        test for test in ci_scope.test_inventory(ci_scope.ROOT, manifest)
        if ci_scope.matches(test, manifest["domains"]["entry_window"]["tests"])
    }
    assert not plan["full"] and not plan["frontend"]
    assert plan["domains"] == ["entry_window"]
    assert set(plan["python_tests"]) == expected
    assert "scripts/tests/test_entry_window_inputs_v1.py" in expected
```

Preserve unknown-path full fallback and existing broad/upstream rules. The new
module must receive direct domain mapping rather than pass via full fallback.
After integration, run `uv run pytest scripts/tests/test_ci_scope.py -q`, focused
E1 tests, normal hooks and current-head hosted checks. No published-artifact
verifier or unrelated market suite is required by this package.

`docs/en/research-program.md`: add this asset row alongside `entry-window.v1`:

| Asset                    | Contract / handoff                                                                                                                                                                                                                                | Public access / scope                                                                                                                                                                                                      |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `entry-window-inputs.v1` | [E1 data contract](../../tasks/20261027-entry-window/data-contract.md), [reader staging handoff](../../tasks/20261027-entry-window/reader-staging-handoff.md): exact calendar/security/generation/as-of/basis alignment of already-loaded packets | `research_core.entry_window_inputs_v1.stage_stock_inputs`; pure in-memory and synthetic only. Real source adapters, reader/runner, original labels and owner/data/compute admission remain gated; no market study has run. |
