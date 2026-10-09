## ADDED Requirements

### Requirement: Definitions retain identity and approval evidence

Stock SHALL index versioned HHHL definitions and legacy proxies with distinct names, source hashes, approval status and task links, and SHALL preserve original rule bytes without modifying historical source packets.

#### Scenario: A consumer looks up an old 2B name

- **WHEN** a consumer follows the method index
- **THEN** it can distinguish owner HHHL from a failed legacy proxy and find the exact implemented definition.

#### Scenario: Frozen source files change during compatibility evaluation

- **WHEN** the registered HHHL archive or registry changes after validated source capture
- **THEN** the detector and every legacy adapter use the same captured texts whose hashes are reported, without mixing later filesystem versions.

### Requirement: New research uses explicit price bases

The opt-in price API SHALL provide raw, permanent-adjusted and reference-factor-adjusted OHLC with raw evidence, explicit cutoff, calendar gaps and quality reasons. It SHALL reject ambiguous factors rather than selecting the first same-day record, and SHALL NOT describe factor-adjusted prices as total return.

#### Scenario: Multiple different events occur on one date

- **WHEN** their factor composition is not established
- **THEN** affected adjusted observations are unknown with an explicit reason, while original rows remain available.

### Requirement: Complete immutable cache versions are reusable

Cache identity SHALL include all input content, calculation identity, basis, calendar, cutoff, parameters and missing-data semantics. Readers SHALL verify complete versions and SHALL NOT mutate or silently fall back from corrupt evidence. Worktrees SHALL use explicit absolute read-only paths without links or copies of immutable cache versions.

#### Scenario: An input snapshot changes

- **WHEN** an on-demand build uses different source bytes
- **THEN** it creates a different version and preserves the previous one.

#### Scenario: An identical version exists

- **WHEN** all identities and artifact hashes verify
- **THEN** the build reuses that version without overwriting it.

#### Scenario: Installed basis names change

- **WHEN** a reader verifies a complete historical version
- **THEN** it uses that version's sealed basis inventory and permits only those selections, independently of installed build defaults.

#### Scenario: Input preparation is interrupted

- **WHEN** source verification or receipt writing fails during bounded input preparation
- **THEN** diagnostics remain in sibling staging, no final input directory is published, and a new attempt can use the same absent final path.

#### Scenario: Another writer creates the final immediately before publication

- **WHEN** a competing file or directory appears after the final precheck
- **THEN** native no-replace publication rejects it without replacing existing bytes; unsupported platforms/filesystems fail safely and retain staging without an overwriting fallback.

### Requirement: Indicators preserve missing values and confirmation timing

ATR and pivots SHALL equal direct calculation under the same versioned definitions, SHALL reset at data gaps, and SHALL retain pivot extreme and confirmation dates separately.

#### Scenario: A pivot is not confirmed yet

- **WHEN** a consumer requests confirmed pivots
- **THEN** no unconfirmed final extreme is presented as known on its extreme date.

### Requirement: Backups and restores are verified and additive

Stock SHALL provide explicit snapshot backup for cache, task datasets and owner annotations, with SHA256 verification and no delete/overwrite behavior. Restore SHALL only create a new destination and SHALL verify recovered files before completion.

#### Scenario: The source moves during backup

- **WHEN** a source hash changes
- **THEN** the snapshot remains incomplete and is not reported as a coherent backup.

#### Scenario: The restore destination exists

- **WHEN** restore is requested
- **THEN** it refuses to replace existing contents.
