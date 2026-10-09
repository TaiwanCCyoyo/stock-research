import json
import logging
import subprocess
import sys
from pathlib import Path

from scripts.logging_utils import configure_logging

LOGGER = logging.getLogger(__name__)

APP_ROOT = Path("/app")
REPORT_PATH = APP_ROOT / "reports" / "smoke" / "docker_2330_buy_hold.json"
ENGINE_WRITE_TARGET = APP_ROOT / "StockProject" / "engine" / ".write_probe"
HOST_ENV_TARGET = APP_ROOT / ".env"


def pass_check(message: str):
    LOGGER.info("[PASS] %s", message)


def fail(message: str):
    LOGGER.error("[FAIL] %s", message)
    sys.exit(1)


def assert_writable_report_dir():
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    probe = REPORT_PATH.parent / ".write_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    pass_check("reports directory is writable")


def assert_engine_read_only():
    try:
        ENGINE_WRITE_TARGET.write_text("should not work", encoding="utf-8")
    except OSError:
        pass_check("engine directory is read-only")
        return
    ENGINE_WRITE_TARGET.unlink(missing_ok=True)
    fail("engine directory allowed writes")


def assert_host_env_not_mounted():
    if HOST_ENV_TARGET.exists():
        fail("host .env is visible inside container")
    pass_check("host .env is not mounted")


def run_backtest():
    command = [
        sys.executable,
        "StockProject/backtest_cli.py",
        "--strategy",
        "StockProject/strategies/test_strategy.py",
        "--codes",
        "2330",
        "--start",
        "2024-01-01",
        "--data-path",
        "data",
        "--output",
        str(REPORT_PATH),
    ]
    subprocess.run(command, cwd=APP_ROOT, check=True)
    pass_check("backtest CLI completed")


def assert_summary_schema():
    summary = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    required_top_level = {
        "schema_version",
        "generated_at",
        "run",
        "strategy",
        "data",
        "metrics",
        "portfolio",
        "trades",
        "warnings",
    }
    missing = required_top_level.difference(summary)
    if missing:
        fail(f"summary schema missing keys: {sorted(missing)}")
    if summary["schema_version"] != "1.0":
        fail(f"unexpected schema version: {summary['schema_version']}")
    if summary["metrics"]["trade_count"] < 1:
        fail("summary has no trades")
    pass_check("summary schema is valid")


def main():
    configure_logging()
    assert_writable_report_dir()
    assert_engine_read_only()
    assert_host_env_not_mounted()
    run_backtest()
    assert_summary_schema()
    pass_check("research runtime smoke test completed")


if __name__ == "__main__":
    main()
