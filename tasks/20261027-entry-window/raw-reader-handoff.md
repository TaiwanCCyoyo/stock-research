# E1 raw quote adapter: engineering scope

Recorded 2026-11-02 before implementation, after #146 assembly and #150 P1-A
freshness merged. Engineering definition: `entry-window-raw-quotes.v1`.

## Why this is the next milestone

The [reader staging handoff](reader-staging-handoff.md) already identifies
`maintained_adjusted_daily.read_adjusted_daily` as the source for a future raw
adapter and defines its `RawQuotePacket` consumer. Joining those existing APIs
removes a concrete E1 input gap without selecting a new strategy or outcome
method. P1/P2 instead require a card/rule and holdings semantics not yet fixed;
this package does not invent them or implement #137's discussion interface.

## Contract and boundary

- An explicit E1 `InputRequest` supplies one security, fixed generation, study
  cutoff, common calendar and declared calendar/universe IDs. Reuse the staging
  module's request validator publicly; preserve existing staging behavior.
  In this adapter, no common-calendar date may follow the study cutoff; a cutoff
  after the final supplied session is allowed. Reject invalid requests before I/O.
- The reader requires an explicit absolute shared root; never resolve a current
  generation or an implicit root. Delegate to the existing public reader with
  `basis="raw"`, `codes=[security_id]`, the exact generation, `as_of=study_as_of`
  and caller calendar. No update, hold/prune, producer read or fallback is added.
- The pure adapter checks frame/record consistency: exact security and original
  calendar positions, generation, raw basis, price definition, cutoff, calendar
  record and single-code scope. Source metadata is retained, including the
  original generation's asof, file/digests, price method and action fingerprint.
  Existing `artifact_store.object_digest` verifies the calendar record; no new
  source or implementation hashing is introduced.
- Use `RawOpen/RawHigh/RawLow/RawClose`, never the quality-masked OHLC columns.
  Require float64 at this boundary without casting. These are the maintained
  reader's already-normalized numbers; they are not a claim of source precision
  before the family's numeric coercion. Retain NaN/nonfinite/nonpositive values
  in their exact positions for the existing E1 core to diagnose.
- Preserve `Quality` and each `quality_reason` separately alongside the packet
  and a detached source-record snapshot. Do not translate a clean daily row,
  empty action snapshot or factor=1 into interval quality, no-action or complete
  event coverage. No `IntervalPacket`, labels or official bounds are produced.
- Refuse `duplicate_date` anywhere in the supplied frame: the maintained source
  has retained only its first quote, so an adapter cannot recover the other
  observation. This is an explicit input failure, not a silent exclusion of a
  stock from research denominators or a chosen deduplication method.
- Refuse malformed/mismatched records, duplicated columns/dates, reordered or
  missing calendar positions and incompatible dtypes. No sorting, joining,
  reindexing, forward fill or next-valid-session substitution occurs here.
  Snapshot arrays/metadata so later caller mutation cannot rewrite the evidence;
  assessment does not mutate the input frame/request/record.

## Validation and remaining work

Use manually constructed frames for boundary tests and one entirely synthetic
temporary maintained generation for the real public reader integration. Test
missing beginning/middle/end bars, Saturday sessions, cutoff after the requested
range, raw-versus-masked prices, source duplication, identity/calendar mismatches,
precision, input immutability and no I/O in the pure adapter. Reuse existing E1
staging/counting with artificial canonical and interval packets to establish
compatibility; do not calculate real labels or outcomes.

No real market generation is opened in this delivery. No market runner, report,
receipt, study card or result is produced. Actual use still requires the caller's
generation retention/hold coordination and data admission. Official calendar
authenticity, original labels/parity, full interval event coverage and quote
quality, official bounds, resources and market computation remain separate gates.
The original report-page acceptance, E2/E3, S7 and O2 boundaries are unchanged.

## Public API and access

`research_core.entry_window_inputs_v1.validate_input_request(request)` exposes
the staging module's unchanged request validation for reuse. The new module is
`research_core.entry_window_raw_quotes_v1`:

```python
# For an already obtained public maintained-reader result:
read = adapt_raw_quote_read(request, frame, record)

# For a separately admitted real-data caller with a retained fixed generation:
# read = load_raw_quote_packet(request, root=explicit_absolute_shared_root)

raw_packet = read.packet
# Pass raw_packet to existing stage_stock_inputs alongside independently admitted
# canonical/interval packets. read.quality is NOT interval quote_quality_to_next.
```

Both functions return `RawQuoteRead`: the existing `RawQuotePacket`, read-only
bool `quality`, date-aligned `quality_reason` tuple, recursively immutable
`source_record` snapshot and an explicit `validation_scope`. Raw price arrays
are read-only copies, and the packet's calendar is detached from the request.
Calendar/universe IDs remain caller declarations because this source record
does not authenticate either. The loader requires an absolute `Path` and an
explicit request generation; errors propagate without fallback or retries.

Boundary tests live in `scripts/tests/test_entry_window_raw_quotes_v1.py`.
The complete artificial producer/shared generation example is
`scripts/tests/test_entry_window_raw_reader_v1.py`; its fixture uses temporary
Parquet and SQLite, not repository or production datasets. Existing source
normalization is left unchanged. There is no command-line runner in this package.

## Local verification

The artificial-generation reader suite and CI selector passed **384 tests in
63.18s**. After adding checks on native column dtypes before NumPy conversion,
the pure adapter plus existing E1 input/count/assembly suites passed **382 tests
in 5.28s**. Independent Terra review found no actionable defects in the final
implementation, tests or delivery scope. Normal hooks and hosted CI are recorded
with the delivery commit/PR in the continuation record; these checks are not
data or market-computation admission.
