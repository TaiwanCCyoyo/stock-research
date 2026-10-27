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

The owner explicitly authorized branch publication and a draft PR. Parent then
assigned this session the next serial shared integration after PR107 and PR108
merged. The original publication hold is fulfilled. Final hosted checks and
parent-verified Astra review remain pending; this package is **not merge-ready**
and its author must not mark it ready or merge it.

No market prices, real labels, holdout, forward outcomes, production data roots,
downloads, generation holds/updates, scratch research runs, scheduler or deployment
operations were used. Real reader/data/label/compute and original owner gates
remain in force after an eventual code merge. No study card or result changed.

## Shared integration (completed locally; final review pending)

Repository ID `1411737252`, owner `TaiwanCCyoyo`, and PR107/108 merged states
were verified through the GitHub connector. Fetched main
`9a2302651c9e19ff8720a78704d55d8a459d12ff` includes the S7 merge
`32965822fcba8d107a072cf9596c8d2df6fb08fc` and was normally merged into this
existing branch without conflicts or history rewriting. No new worktree was
created. Parent assigned this session sole ownership of the following integration.

The core `research_core/entry_window_inputs_v1.py` and its original 146-test suite
remain byte-identical to independently reviewed
`a3be055f4b998f54cbe6003a81d722986ffe04a9`. Only shared integration and this
handoff changed. Earlier Astra evidence on that implementation included the
146 tests, seven additional probes, 162 interval states, 27 required-key removals
and forbidden-I/O import checks; that evidence is reused for the unchanged code.

- `scripts/ci_test_domains.json`: adds this module/handoff to `entry_window`
  paths, and its test to both domain tests and `reviewed_tests`. The existing B1,
  bootstrap, count-cube, canonical dependencies and S7 domain remain intact.
- `scripts/tests/test_ci_scope.py`: the existing exact A/M owned-path matrix
  adds this module/test/handoff, increasing its cases by six. All E1 paths,
  including B1 core, now select the three E1 suites; changes to an E1 test also
  select the selector test itself. Existing canonical/oracle/count-cube dependency
  cases explicitly require the input suite while preserving exact consumers.
  Unknown-path, broad/full safety fallback and all S7 cases remain unchanged.
- `docs/en/research-program.md`: adds `entry-window-inputs.v1` with E1 contract,
  this handoff, public `stage_stock_inputs` access and pure/synthetic scope.
  Real-source adapters and owner/data/label/compute gates stay explicit.

Local verification:
`uv run pytest scripts/tests/test_entry_window_inputs_v1.py scripts/tests/test_ci_scope.py -q`
passed **410 tests in 80.24s** (146 unchanged input cases and 264 selector cases).
Normal commit hooks and an actual-diff CI selection plan also apply. The author handback
records exact results and final SHA/base. No published-artifact verifier or
unrelated market suite is required or executed by this package. Final hosted CI,
independent Astra review and the parent-controlled ready/merge decision remain
open gates; publication itself does not make this package merge-ready.
