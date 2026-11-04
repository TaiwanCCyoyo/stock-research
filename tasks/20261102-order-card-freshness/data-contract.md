# P1-A: operation-card input freshness boundary

Recorded 2026-11-02 before implementation. Engineering definition:
`order-card-freshness.v1`. This is the next bounded milestone after E1 assembly
[#146](https://github.com/TaiwanCCyoyo/stock-research/pull/146) merged at
`3d4378a49e80c25c6d59e50bd9f53334bf56b5f7`.

## Why this milestone

The [roadmap](../../docs/en/research-roadmap.md) already requires P1 to withhold
cards when data is not current to the latest trading session, and permits
conservative refusal before O1's real closure adapter exists. This prerequisite
can be implemented without choosing a strategy, sizing/stops, outcomes or a new
market experiment. E1 assembly is complete; its real source adapters remain gated.
S7 cross-week confirmation and O2 publication semantics remain pending. #137's
discussion interface/JSON delivery belongs to its existing owner.

This package provides a pure assessment plus a thin explicit-JSON command. It
does not emit orders or a trading card, load market sources, certify source truth,
decide a strategy's required dataset list, start F1, or deploy anything. A passing
freshness gate is only one prerequisite for a future card generator.

## Calendar and source contract

Reuse the existing public `CalendarFact`, `CalendarSnapshot` and `DayCoverage`
types in `research_core.multi_timeframe_ma_weeks_v1`. Expose a date-range assessment
over their existing coverage primitive; leave S7 week/confirmation semantics
unchanged. Do not duplicate its known-at/close-at/source logic in P1, use quote
dates as an exchange calendar, or silently presume weekdays/weekends/holidays.

The caller declares an expected latest session and supplies calendar facts for
every civil date from it through the snapshot's decision date in Asia/Taipei.
The expected session must be a known session already closed by decision time.
All later dates must be known closures: a newer completed session means the
expected day is stale; an unclosed session conservatively withholds this
after-close assessment. A missing/unknown/not-yet-known fact or unknown close
also withholds. An explicitly known closure needs no quote and is not missing
data. A future expected session cannot pass. Calendar provenance is retained;
the caller still owns official-source authenticity and applicable fact versions.

The caller supplies a nonempty, unique set of daily dataset requirements:
dataset ID, definition and expected generation. No default strategy profile is
invented. Each observation explicitly declares its dataset identity, definition,
generation, calendar ID, universe ID, as-of session, availability time, status
(`complete`, `missing`, `unknown`, `updating`) and source reference. Only complete
observations with exactly matching expected identities/session and known
availability at or before decision may pass. A recently updated metadata file
cannot compensate for an old as-of session. Missing observations withhold;
duplicate or unexpected IDs and malformed declarations are input errors.

All timestamps are explicit and timezone-aware; comparisons use the same instant
after Asia/Taipei conversion. Dates are normalized date-only values. Unknown
session or availability values remain null and do not become zero/false/fresh.
These requirements apply to daily inputs, not month-level revenue completeness
or full-history coverage certification.

## Interface and acceptance

The pure assessment takes a request, calendar snapshot and observations. It
returns `freshness_ready`, stable reason codes, expected/observed source metadata,
calendar-day evidence and the scope limitation. Output ordering is deterministic
regardless of observation order; caller inputs remain unchanged. No callbacks,
root discovery, clocks, network, filesystem, SQLite or label calculation occur
inside assessment.

The CLI consumes only an explicitly named JSON packet and prints JSON to stdout;
no production-root fallback or output file is created. Exit 0 means freshness
passed, 2 means withheld, and 1 means invalid input/read failure. The document
parser and projection belong in `research_core`, with the CLI kept thin. The
handoff will record exact public names and a complete artificial invocation.

Acceptance uses synthetic calendars and observations: current session, stale
source, missing/unknown/updating sources, wrong identities, future availability,
explicit closures, missing closure facts, newer sessions, session still open,
timezone equivalence, terminal equality boundaries, immutable inputs and
forbidden-I/O execution. Existing S7 week tests must retain their behavior. Normal
hooks/CI and an independent review apply before draft PR delivery.

The repository owns code, this contract, small synthetic examples and delivery
records. No shared data family, research scratch run, result receipt, study card
or presentation acceptance is created. The owner's final report-page acceptance,
#113/#128 and E2/E3/S7/O2 gates remain unchanged.
