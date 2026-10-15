"""Give every test process a synthetic producer data root.

Several modules resolve the producer root at import time, and the resolver has
no fallback: without this, collection fails wherever no primary `.env.local`
exists (CI), and locally the suite would read the real producer data. Set before
collection so imports and subprocess tests inherit it.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

from research_core.producer_data import ENV_KEY, SENTINEL

_ROOT = Path(tempfile.mkdtemp(prefix="synthetic-producer-root-"))
(_ROOT / SENTINEL).write_bytes(b"")
atexit.register(shutil.rmtree, _ROOT, ignore_errors=True)
os.environ[ENV_KEY] = str(_ROOT)
