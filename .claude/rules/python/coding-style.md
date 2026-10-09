---
paths:
    - "**/*.py"
    - "**/*.pyi"
---

# Python Coding Style

## Logging

Use `logging` for diagnostics; CLI output and hook protocol responses belong on the required stdout/stderr stream.

While writing code, add `logging` at key points (inputs, branch decisions, external call results, caught exceptions) so that history logs from a later failure locate the cause without a rerun. Log identifiers and summaries rather than credentials, tokens, or personal data.

When a failure's cause is not obvious from the code and error, add targeted `logging` at the relevant boundaries (inputs, branch decisions, external call results) and reproduce it before changing behavior. Keep log statements that would help diagnose future failures, at an appropriate level, instead of removing them after the fix.

## Reference

See skill: `python-testing` for pytest patterns and coverage requirements.
