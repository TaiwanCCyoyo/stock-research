## ADDED Requirements

### Requirement: Independent benchmark context

The producer SHALL create a new immutable, identified benchmark dataset from retained inputs and SHALL NOT alter the stock atlas, catalog, source cache or trading acceptance rules.

#### Scenario: Existing generation

- **WHEN** the requested output directory already exists
- **THEN** the producer refuses replacement and preserves all prior artifacts.

### Requirement: Timing-separated labels

The dataset SHALL separate past-only states from retrospective states. Every row SHALL declare its observation date, information cutoff, state, optional transition event and missing-data reason. Unknown and mixed SHALL NOT be represented as consolidation.

#### Scenario: Future prices change

- **WHEN** prices after a past-only row's date are changed or removed
- **THEN** that row's state, components and transition event remain identical.

#### Scenario: Retrospective tail lacks follow-up

- **WHEN** the required centered window is incomplete
- **THEN** the retrospective label is unknown, with its missing-follow-up reason, and cannot be consumed as an as-of signal.

### Requirement: Source and definition identity

Consumers SHALL validate input/output hashes, symbol/calendar identities, definition version and declared row/date coverage before returning data. Missing prices or flagged numeric barriers SHALL stay missing and reset transitions.

#### Scenario: Corrupted or mismatched input

- **WHEN** a descriptor hash or declared symbol/calendar differs from the actual artifact
- **THEN** generation and reading fail explicitly without returning a successful dataset.
