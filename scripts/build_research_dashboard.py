import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import panel as pn

LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research_lab.dashboard_core import (  # noqa: E402
    SITE_ROOT,
    build_index_view,
    build_task_view,
    discover_tasks,
    make_template,
    safe_slug,
)
from scripts.logging_utils import configure_logging  # noqa: E402


def save_template(template: Any, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    template.save(output_path, embed=False, resources="cdn")
    LOGGER.info("[WRITE] %s", output_path)


def build_site(output_dir: Any = None):
    pn.extension("plotly", sizing_mode="stretch_width")
    site_root = Path(output_dir) if output_dir else SITE_ROOT
    site_root.mkdir(parents=True, exist_ok=True)

    tasks = discover_tasks()
    index = make_template("Local Research Dashboard", build_index_view(static=True))
    save_template(index, site_root / "index.html")

    for task in tasks:
        page = make_template(task["task"], build_task_view(task["task"]))
        save_template(page, site_root / f"{safe_slug(task['task'])}.html")

    return site_root


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description="Build the static local research dashboard site.")
    parser.add_argument("--output-dir", default=None, help="Output directory; defaults to research_lab/site")
    args = parser.parse_args()
    build_site(output_dir=args.output_dir)


if __name__ == "__main__":
    main()
