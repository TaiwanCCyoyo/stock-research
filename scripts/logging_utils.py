from __future__ import annotations

import logging
from typing import Any

RichHandler: Any
try:
    from rich.logging import RichHandler
except ImportError:  # pragma: no cover - rich is an optional display enhancement
    RichHandler = None


def configure_logging(level: int = logging.INFO) -> None:
    """Configure compact console logging with Rich when available."""
    if logging.getLogger().handlers:
        return
    handler: logging.Handler
    if RichHandler is not None:
        handler = RichHandler(markup=False, show_path=False, show_time=False)
    else:
        handler = logging.StreamHandler()
    logging.basicConfig(level=level, format="%(message)s", handlers=[handler])
