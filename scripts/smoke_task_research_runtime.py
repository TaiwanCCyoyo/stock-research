import subprocess
import sys
from pathlib import Path

RUNNING_IN_CONTAINER = Path("/app").exists()
APP_ROOT = Path("/app")
if not RUNNING_IN_CONTAINER:
    APP_ROOT = Path(__file__).resolve().parents[1]
TASK_ROOT = APP_ROOT / "tasks" / "sample"
CANDIDATE_PATH = TASK_ROOT / "candidates" / "two_b_ma_convergence.py"
RUN_OUTPUT_PATH = TASK_ROOT / "runs" / "two_b_smoke_2330.json"
SUMMARY_PATH = TASK_ROOT / "summary.json"
SWEEP_SUMMARY_PATH = TASK_ROOT / "sweep_summary.json"
ENGINE_WRITE_TARGET = APP_ROOT / "StockProject" / "engine" / ".write_probe"
HOST_ENV_TARGET = APP_ROOT / ".env"
LOCAL_DATA_PATH = "shioaji_stock_prices/data/adjusted_prices/daily"
# 2B's initial_allocation_pct (0.18) can't afford a 1000-share 2330 lot at the
# default 1,000,000 cash (strategy_diagnosis.md documents 2330 as a 0-trade
# symbol for exactly this reason); the smoke run needs enough cash headroom.
SMOKE_CASH = 10_000_000.0


def pass_check(message: str):
    sys.stdout.write(f"[PASS] {message}\n")


def fail(message: str):
    sys.stderr.write(f"[FAIL] {message}\n")
    sys.exit(1)


def assert_task_contract():
    required_paths = [
        TASK_ROOT / "mission.md",
        TASK_ROOT / "candidates",
        TASK_ROOT / "runs",
        CANDIDATE_PATH,
    ]
    missing = [str(path.relative_to(APP_ROOT)) for path in required_paths if not path.exists()]
    if missing:
        fail(f"task contract missing paths: {missing}")
    pass_check("sample task contract is present")


def assert_task_output_writable():
    RUN_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    probe = RUN_OUTPUT_PATH.parent / ".write_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    pass_check("task runs directory is writable")


def assert_engine_read_only():
    if not RUNNING_IN_CONTAINER:
        pass_check("engine read-only check skipped outside container")
        return
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


def smoke_data_path():
    if RUNNING_IN_CONTAINER:
        return "data"
    return LOCAL_DATA_PATH


def run_task_backtest():
    command = [
        sys.executable,
        "scripts/run_task_backtest.py",
        "--task",
        "sample",
        "--strategy",
        "candidates/two_b_ma_convergence.py",
        "--codes",
        "2330",
        "--start",
        "2022-01-01",
        "--cash",
        str(SMOKE_CASH),
        "--run-name",
        "two_b_smoke_2330",
        "--params-file",
        "params/two_b_default.json",
        "--data-path",
        smoke_data_path(),
        "--promote-summary",
    ]
    subprocess.run(command, cwd=APP_ROOT, check=True)
    pass_check("task candidate backtest completed")


def assert_summary_schema():
    import json

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
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
    if summary["strategy"]["name"] != "TwoBMovingAverageConvergence":
        fail(f"unexpected strategy name: {summary['strategy']['name']}")
    if summary["strategy"].get("params", {}).get("lot_size") != 1000:
        fail(f"unexpected strategy params: {summary['strategy'].get('params')}")
    if summary["metrics"]["trade_count"] < 1:
        fail("summary has no trades")
    pass_check("task summary schema is valid")


def run_task_param_sweep():
    command = [
        sys.executable,
        "scripts/run_task_param_sweep.py",
        "--task",
        "sample",
        "--strategy",
        "candidates/two_b_ma_convergence.py",
        "--grid-file",
        "params/two_b_ma_convergence_sweep.json",
        "--codes",
        "2330",
        "--start",
        "2022-01-01",
        "--cash",
        str(SMOKE_CASH),
        "--run-prefix",
        "smoke_two_b_sweep",
        "--data-path",
        smoke_data_path(),
    ]
    subprocess.run(command, cwd=APP_ROOT, check=True)
    pass_check("task parameter sweep completed")


def assert_sweep_summary_schema():
    import json

    summary = json.loads(SWEEP_SUMMARY_PATH.read_text(encoding="utf-8"))
    required_top_level = {
        "schema_version",
        "generated_at",
        "task",
        "strategy",
        "grid_file",
        "rank_metric",
        "rank_direction",
        "best",
        "runs",
    }
    missing = required_top_level.difference(summary)
    if missing:
        fail(f"sweep summary schema missing keys: {sorted(missing)}")
    if summary["schema_version"] != "1.0":
        fail(f"unexpected sweep schema version: {summary['schema_version']}")
    if len(summary["runs"]) != 4:
        fail(f"unexpected sweep run count: {len(summary['runs'])}")
    if summary["best"]["rank"] != 1:
        fail(f"unexpected best sweep rank: {summary['best']['rank']}")
    pass_check("task sweep summary schema is valid")


def main():
    assert_task_contract()
    assert_task_output_writable()
    assert_engine_read_only()
    assert_host_env_not_mounted()
    run_task_backtest()
    assert_summary_schema()
    run_task_param_sweep()
    assert_sweep_summary_schema()
    pass_check("task research runtime smoke test completed")


if __name__ == "__main__":
    main()
