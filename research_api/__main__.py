"""Production launcher for the research dashboard's API + static frontend.

Runs uvicorn.Server directly (rather than `uvicorn research_api.main:app` on the
CLI) so this process owns the Server object and can:

- stop it gracefully from inside the process when POST /shutdown sets
  `server.should_exit = True` (see research_api.main.post_shutdown), and
- watch research_api.main.heartbeat and stop the server itself once the
  frontend has missed heartbeats for longer than HEARTBEAT_GRACE_SECONDS,
  i.e. the browser tab was closed.

`uv run --group viewer python -m research_api` is the entry point wired into
open_research_dashboard.cmd. The Vite-dev launcher (open_research_api.cmd)
intentionally keeps using plain `uvicorn research_api.main:app` instead — the
dev API process should not self-terminate just because a dev browser tab closed.
"""

from __future__ import annotations

import asyncio
import logging
import time

import uvicorn

from research_api import main as api_main

logger = logging.getLogger(__name__)

# How often the monitor checks the heartbeat age; independent of the frontend's
# own send interval, just needs to be well under HEARTBEAT_GRACE_SECONDS.
MONITOR_INTERVAL_SECONDS = 5


async def _watch_heartbeat(server: uvicorn.Server) -> None:
    """Stop `server` once a previously-seen heartbeat has been silent too long.

    Does nothing until the first heartbeat arrives, so the server doesn't shut
    itself down before the frontend has even loaded and started sending them.
    """
    while not server.should_exit:
        await asyncio.sleep(MONITOR_INTERVAL_SECONDS)
        last_seen = api_main.heartbeat.last_seen
        if last_seen is None:
            continue
        if time.monotonic() - last_seen > api_main.HEARTBEAT_GRACE_SECONDS:
            logger.info("no heartbeat for over %ss; shutting down", api_main.HEARTBEAT_GRACE_SECONDS)
            server.should_exit = True
            return


async def _run() -> None:
    config = uvicorn.Config(api_main.app, host="127.0.0.1", port=8503)
    server = uvicorn.Server(config)
    api_main.app.state.server = server

    serve_task = asyncio.create_task(server.serve())
    watch_task = asyncio.create_task(_watch_heartbeat(server))
    try:
        # Whichever finishes first (server.serve() exits on should_exit, or the
        # monitor detects a stale heartbeat and sets should_exit itself) should
        # trigger prompt cleanup of the other, rather than waiting out the
        # monitor's next poll interval.
        await asyncio.wait({serve_task, watch_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (serve_task, watch_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(serve_task, watch_task, return_exceptions=True)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
