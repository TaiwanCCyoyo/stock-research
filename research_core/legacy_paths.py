"""Placeholders that historical records use for locations outside this project.

Records written before 2026-10-10 named absolute paths in a predecessor checkout and repository.
Those paths were rewritten to `<legacy-checkout>/...` and `<legacy-repository>`: provenance that
identifies where something once was, never a location to read from or write to.
"""

from __future__ import annotations

LEGACY_CHECKOUT = "<legacy-checkout>"
LEGACY_REPOSITORY = "<legacy-repository>"


def is_legacy_location(value: str) -> bool:
    """True for a recorded predecessor path, which stands in for an absolute path on another host."""
    return value == LEGACY_CHECKOUT or value.startswith((LEGACY_CHECKOUT + "/", LEGACY_CHECKOUT + "\\"))
