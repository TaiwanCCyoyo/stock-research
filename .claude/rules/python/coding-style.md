---
paths:
    - "**/*.py"
    - "**/*.pyi"
---

# Python Coding Style

## Logging

Use `logging` for diagnostics; CLI output and hook protocol responses belong on the required stdout/stderr stream.

Favor diagnostic logging in scripts so future failures can be understood from their execution history. Record meaningful stages, safe input identifiers or counts, consequential decisions, external-call outcomes, and exception context.

Retain useful diagnostic logs at appropriate levels after a fix, and add targeted logs during debugging as needed. Avoid logging every statement, full payloads, credentials, tokens, or personal data.
