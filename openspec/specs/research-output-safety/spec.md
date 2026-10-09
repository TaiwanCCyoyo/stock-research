# Research Output Safety

## Purpose

Define the baseline safety and publishing boundaries for local research artifacts, external summaries, and verification reporting.

## Requirements

### Requirement: Local artifacts are the source of truth

The system MUST treat local files under task directories as the authoritative research record; external publishing surfaces are derived summaries.

#### Scenario: Prepare Notion output

- **WHEN** Codex prepares a Notion research page
- **THEN** the content SHOULD be derived from local task artifacts such as summary metrics, rankings, signal events, and data audit files
- **AND** Notion MUST remain a concise index or discussion log rather than the canonical data store.

### Requirement: Research output is not trading execution

Generated reports, dashboard views, and Notion pages MUST remain research outputs and MUST NOT provide real trading execution instructions.

#### Scenario: Summarize strategy results

- **WHEN** Codex writes a research summary or dashboard narrative
- **THEN** it MUST avoid presenting results as investment advice
- **AND** it MUST preserve relevant caveats about data quality, benchmark limitations, and strategy risk.

### Requirement: Secrets and credentials are excluded from outputs

Research workflows MUST NOT print, store, mount, publish, or commit secrets, broker credentials, API keys, passwords, or private agent configuration.

#### Scenario: Write task artifacts

- **WHEN** task files, reports, or generated dashboard artifacts are written
- **THEN** they MUST NOT include broker credentials, API keys, passwords, or private agent session data.

#### Scenario: Run Docker-backed research

- **WHEN** a Docker research service is used
- **THEN** host `.env`, `.env.local`, `~/.codex`, and other private agent state MUST NOT be mounted into the container.

### Requirement: Verification status is explicit

Codex MUST report meaningful verification results for research infrastructure changes and disclose unavailable checks.

#### Scenario: Complete a code or spec change

- **WHEN** Codex finishes a change that affects Python behavior, dashboard rendering, or OpenSpec artifacts
- **THEN** it MUST run the relevant local validation commands when feasible
- **AND** it MUST state any skipped Docker, browser, or external-service verification with a reason.
