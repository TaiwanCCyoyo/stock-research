# E1 canonical reader: engineering scope

Recorded 2026-11-02 before implementation, after #151 merged. Engineering
definition: `entry-window-canonical.v1`. This closes the existing
`CanonicalPacket` input gap in the [reader staging handoff](reader-staging-handoff.md)
by connecting two already public APIs, without changing their research methods.

## Contract

- `adapt_canonical_read(request, frame, record, *, ordinary_reference,
availability_note)` is a pure adapter. `load_canonical_packet(request, *, root,
ordinary_reference, availability_note)` delegates one fixed-generation read to
  `maintained_adjusted_daily.read_adjusted_daily("reference_factor_adjusted", ...)`.
  Both return `CanonicalRead(packet, source_record, ordinary_reference,
validation_scope)`, where packet is the existing `CanonicalPacket`.
- The root is an explicit absolute `Path`; generation, security, study cutoff,
  caller calendar and declared universe/calendar IDs come from `InputRequest`.
  No calendar date may follow the cutoff. Reject invalid declarations before I/O.
  There is no default root, current-generation selection, hold/prune, update,
  producer read or fallback. A separately admitted caller owns generation holds.
- `ordinary_reference` is a required exact Python bool, with no default. The
  nonempty `availability_note` records the caller's universe/availability
  limitations. Neither it nor the request's universe ID proves historical
  membership. False must reach the existing calculation unchanged.
- Reuse the raw adapter's request, source-record and frame-identity validation
  in one shared `research_core.entry_window_price_inputs_v1` module. Raw behavior
  stays unchanged. Validate the requested price basis, generation, definition,
  as-of method/cutoff, generation asof, single-code scope, source file/digests and
  caller calendar record. Retain a recursively immutable detached record.
- Require original calendar positions and exact security; no sorting, joining,
  padding, fill or date substitution. Canonical numeric columns are native
  float64 `Open/High/Low/Close`, `RawClose`, `VolumeLots`, `Turnover`; `Quality`
  is native bool and `quality_reason` is text or None. Do not coerce nullable,
  Arrow or other dtypes implicitly. The maintained reader already normalized
  source precision; this boundary cannot certify original acquisition values.
- Refuse source `duplicate_date` diagnostics for the whole call, as in the raw
  adapter. Other missing/invalid values and daily quality remain in place for the
  original calculation; do not invent a stock exclusion or quality overlay.
- On a detached frame, drop `Code`, set `Date` as the index and call the existing
  `momentum_only_v1.stock_daily(security_id, prepared,
ordinary_reference=ordinary_reference)` exactly once. Preserve its eligibility,
  jump flags, C-52w, local atoms, ret120, all 12 labels, main eligibility and
  calendar-full arrays. No replacement formulas, A4/H cross-sectional ranking,
  new thresholds, interval claims or outcome admission are introduced.
- Packet definition remains `momentum-only.v1`, basis
  `reference_factor_adjusted`; retain the caller's availability note and explicit
  reader provenance. Copy the calendar and detach input metadata/frame so this
  call and later caller mutation cannot rewrite the produced packet's inputs.
  Existing staging retains its borrowed-array contract.

## Validation and remaining gates

Boundary cases use manually constructed frames. End-to-end examples use only
temporary artificial producer/shared generations, including an action, missing
bars and warmup/censoring. Compare every StockDaily field with the original
public calculation on the same artificial prepared frame; test both ordinary
reference states, exact identity/calendar/dtype failures, determinism and input
immutability. Prove that the pure path opens no files or network connections and
does not invoke data-source readers; existing calculations retain their diagnostic
logging, whose host-configured handlers may themselves have side effects. Do not
disable or alter global logging. Invalid loader requests must fail before a read.
Feed canonical/raw packets to
existing staging/counting with separately declared artificial interval evidence.

No real market generation, real labels or stored result is read or recalculated.
This wiring does not establish PR61 frozen-result parity or admit market labels.
Calendar/universe authenticity, original-label admission, complete interval
event coverage/quote quality, official bounds, resources and market computation
remain separate gates. In particular, the actions snapshot is not proof of a
complete interval event source. There is no runner, report, result or deployment.
The owner report-page hold, E2/E3, S7, O2 and #137 boundaries remain unchanged.

## Public access and verification

```python
from research_core.entry_window_canonical_v1 import adapt_canonical_read

read = adapt_canonical_read(
    request,
    frame,
    record,
    ordinary_reference=declared_ordinary_reference,
    availability_note=declared_availability_note,
)
canonical_packet = read.packet
```

`load_canonical_packet` offers the equivalent explicit-root reader path for a
separately admitted caller. `source_record` is detached and recursively immutable;
the packet's calculated arrays are governed by existing staging's borrowed-array
contract. No CLI is added. Shared checks are
`entry_window_price_inputs_v1.validate_price_request`, `validate_price_root` and
`validate_price_read`; the latter returns a detached record without copying or
rewriting its input frame.

Local verification completed on artificial inputs only:

- Existing raw adapter/reader regression: **133 passed in 14.85s**.
- New public-reader integration plus initial CI selector: **380 passed in 43.43s**.
- Canonical boundary tests, existing E1 input/count/bootstrap/assembly and final
  CI dependency selection: **816 passed in 27.64s**.

The real-reader fixture has 620 artificial sessions, an action before and after
the requested cutoff, a missing bar and separately unknown interval evidence.
Both ordinary-reference states match every original StockDaily field; empty
calendars also retain the original empty calculation. Boundary fixtures exercise
strict types, false declarations, identities, no source I/O and input mutation.
Independent Terra review found no actionable defects. Normal hooks and hosted
checks are recorded with delivery evidence; these checks do not relax the gates
above or establish parity against real historical results.
