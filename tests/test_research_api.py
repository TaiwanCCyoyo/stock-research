"""Read-only research API: thin FastAPI pass-throughs over existing query functions."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from research_api import main as api_main
from StockProject.engine.data_loader import DataLoader


@pytest.fixture
def client() -> TestClient:
    return TestClient(api_main.app)


@pytest.fixture
def tasks_root(monkeypatch: MonkeyPatch, tmp_path: Path) -> Path:
    from research_lab import dashboard_core
    from scripts import stock_research_query

    root = tmp_path / "tasks"
    root.mkdir()
    monkeypatch.setattr(dashboard_core, "TASKS_ROOT", root)
    monkeypatch.setattr(stock_research_query, "TASKS_ROOT", root)
    return root


def make_task(tasks_root: Path, task_id: str, summary: dict | None = None) -> Path:
    task_dir = tasks_root / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "summary.json").write_text(
        json.dumps(summary or {"metrics": {"return_rate": 0.1}, "trades": []}),
        encoding="utf-8",
    )
    return task_dir


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_data_quality_returns_not_available_when_report_missing(client: TestClient, monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(api_main, "DEFAULT_DATA_PATH", tmp_path / "no-such-dir")

    response = client.get("/data-quality")

    assert response.status_code == 200
    assert response.json() == {"available": False, "report": None}


def test_data_quality_returns_report_contents_when_present(client: TestClient, monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    report = {"schema_version": 1, "generated_at": "2026-07-20T00:00:00+00:00", "calendar": {}, "symbols": {"2330": {"file_missing": False}}}
    (tmp_path / "data_quality_report.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(api_main, "DEFAULT_DATA_PATH", tmp_path)

    response = client.get("/data-quality")

    assert response.status_code == 200
    assert response.json() == {"available": True, "report": report}


def test_unknown_task_returns_404_with_readable_message(client: TestClient, tasks_root: Path) -> None:
    response = client.get("/tasks/no-such-task")

    assert response.status_code == 404
    assert "no-such-task" in response.json()["detail"]


def test_list_tasks_returns_lightweight_index_newest_first(client: TestClient, tasks_root: Path) -> None:
    os.utime(make_task(tasks_root, "task-old"), (1000.0, 1000.0))
    os.utime(make_task(tasks_root, "task-new"), (2000.0, 2000.0))

    response = client.get("/tasks")

    assert response.status_code == 200
    payload = response.json()
    assert [row["task"] for row in payload["tasks"]] == ["task-new", "task-old"]
    for row in payload["tasks"]:
        assert set(row) == {"task", "mtime", "title"}


def test_list_tasks_title_falls_back_to_task_id_without_title_file(client: TestClient, tasks_root: Path) -> None:
    make_task(tasks_root, "task-a")

    payload = client.get("/tasks").json()

    assert payload["tasks"][0]["title"] == "task-a"


def test_list_tasks_title_reads_research_dashboard_title_file(client: TestClient, tasks_root: Path) -> None:
    task_dir = make_task(tasks_root, "task-a")
    title_dir = task_dir / "research_dashboard"
    title_dir.mkdir()
    (title_dir / "title.txt").write_text("人類可讀標題", encoding="utf-8")

    payload = client.get("/tasks").json()

    assert payload["tasks"][0]["title"] == "人類可讀標題"


def test_get_task_returns_bundle_content(client: TestClient, tasks_root: Path) -> None:
    make_task(tasks_root, "task-a", {"metrics": {"return_rate": 0.42}, "trades": []})

    response = client.get("/tasks/task-a")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task"] == "task-a"
    assert payload["title"] == "task-a"
    assert payload["summary"]["metrics"]["return_rate"] == 0.42
    assert isinstance(payload["root"], str)
    assert set(payload) >= {"summary", "mode_summaries", "rankings", "events", "comparison", "diagnosis", "stock_names"}


def test_get_task_bundle_includes_health_and_judgments(client: TestClient, tasks_root: Path) -> None:
    """The bundle carries strategy-health rows and capital-mode judgments computed by
    the tested pure functions in dashboard_core, so the frontend does not duplicate them."""
    task_dir = make_task(
        tasks_root,
        "task-a",
        {"metrics": {"return_rate": 5.0, "payoff_ratio": 2.5, "expectancy": 100.0, "closed_trade_count": 4}, "trades": []},
    )
    (task_dir / "summary_shared.json").write_text(
        json.dumps({"metrics": {"payoff_ratio": 2.5, "expectancy": 100.0, "cash_blocked_entry_count": 0}}),
        encoding="utf-8",
    )
    (task_dir / "comparison.json").write_text(
        json.dumps({"modes": {"shared": {"return_rate": 5.0}}, "symbols": {}}),
        encoding="utf-8",
    )

    payload = client.get("/tasks/task-a").json()

    assert payload["health"]["closed_trade_count"] == 4
    assert "verdict" in payload["health"]
    assert "shared" in payload["judgments"]["pools"]
    assert isinstance(payload["judgments"]["comparative"], str)
    assert "verdict" in payload["mode_health"]["shared"]


def test_get_task_bundle_judgments_absent_without_comparison(client: TestClient, tasks_root: Path) -> None:
    make_task(tasks_root, "task-a")

    payload = client.get("/tasks/task-a").json()

    assert payload["judgments"] is None
    assert "health" in payload


def test_get_task_bundle_stock_names_joins_current_snapshot(client: TestClient, tasks_root: Path, monkeypatch: MonkeyPatch) -> None:
    from research_lab import display

    make_task(tasks_root, "task-a", {"run": {"codes": ["2330"]}, "trades": []})
    mapping_path = tasks_root.parent / "stock_symbol_mapping.json5"
    mapping_path.write_text('{"2330": "台積電", "9999": "他股"}', encoding="utf-8")
    monkeypatch.setattr(display, "SYMBOL_MAPPING_PATH", mapping_path)
    display.stock_names.cache_clear()

    payload = client.get("/tasks/task-a").json()

    assert payload["stock_names"] == {"2330": "台積電"}
    display.stock_names.cache_clear()


def write_day_csv(data_root: Path, code: str, rows: list[tuple[str, float, float, float, float, int]]) -> Path:
    path = data_root / f"{code}_day.csv"
    lines = ["Date,Open,High,Low,Close,Volume"]
    for date, open_, high, low, close, volume in rows:
        lines.append(f"{date},{open_},{high},{low},{close},{volume}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_corporate_actions_db(data_root: Path, rows: list[tuple]) -> Path:
    db_path = data_root / "corporate_actions.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE corporate_actions ("
            "code TEXT, ex_date TEXT, event_type TEXT, previous_close REAL, "
            "reference_price REAL, cash_dividend_estimate REAL, price_factor REAL, "
            "evidence_status TEXT)"
        )
        conn.executemany(
            "INSERT INTO corporate_actions (code, ex_date, event_type, previous_close, "
            "reference_price, cash_dividend_estimate, price_factor, evidence_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return db_path


@pytest.fixture
def price_task(tasks_root: Path, tmp_path: Path) -> dict:
    """A task whose summary points at a tmp data root with two symbols and one corporate action."""
    data_root = tmp_path / "data"
    data_root.mkdir()
    write_day_csv(
        data_root,
        "2330",
        [
            ("2025-01-02", 100.0, 102.0, 99.0, 100.0, 1000),
            ("2025-01-03", 96.0, 97.0, 94.0, 95.0, 1200),
        ],
    )
    write_day_csv(
        data_root,
        "2454",
        [
            ("2025-01-02", 50.0, 52.0, 49.0, 51.0, 500),
        ],
    )
    write_corporate_actions_db(
        data_root,
        [
            ("2330", "2025-01-03", "CASH_DIVIDEND", 100.0, 95.0, 5.0, 0.95, "confirmed"),
        ],
    )
    make_task(
        tasks_root,
        "task-prices",
        {
            "metrics": {"return_rate": 0.1},
            "trades": [
                {"date": "2025-01-02", "code": "2330", "action": "BUY", "price": 100.0, "qty": 1000, "total": -100000.0},
                {"date": "2025-01-03", "code": "2330", "action": "SELL", "price": 95.0, "qty": 1000, "total": 95000.0},
            ],
            "data": {"path": str(data_root)},
        },
    )
    return {"task": "task-prices", "data_root": data_root, "tasks_root": tasks_root}


def test_prices_returns_ohlcv_and_corporate_action_markers(client: TestClient, price_task: dict) -> None:
    loader = DataLoader(str(price_task["data_root"]))
    loader.load_symbols(["2330"])
    expected = loader.get_stock_data("2330")

    response = client.get("/tasks/task-prices/prices", params={"codes": "2330"})

    assert response.status_code == 200
    payload = response.json()
    rows = payload["prices"]["2330"]
    assert [row["Date"][:10] for row in rows] == [d.strftime("%Y-%m-%d") for d in expected["Date"]]
    assert [row["Close"] for row in rows] == list(expected["Close"])
    assert [row["SignalClose"] for row in rows] == pytest.approx(list(expected["SignalClose"]))
    markers = payload["corporate_actions"]["2330"]
    assert markers == [{"event_type": "CASH_DIVIDEND", "date": "2025-01-03"}]


def test_prices_reads_only_requested_symbol_files(client: TestClient, price_task: dict, monkeypatch: MonkeyPatch) -> None:
    read_paths: list[str] = []
    original_read_csv = pd.read_csv

    def spy_read_csv(path: object, *args: object, **kwargs: object) -> pd.DataFrame:
        read_paths.append(os.path.basename(str(path)))
        return original_read_csv(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pd, "read_csv", spy_read_csv)

    response = client.get("/tasks/task-prices/prices", params={"codes": "2454"})

    assert response.status_code == 200
    assert read_paths == ["2454_day.csv"]
    assert payload_codes(response.json()) == ["2454"]


def payload_codes(payload: dict) -> list[str]:
    return sorted(payload["prices"])


def test_prices_unknown_task_returns_404(client: TestClient, tasks_root: Path) -> None:
    response = client.get("/tasks/no-such-task/prices", params={"codes": "2330"})

    assert response.status_code == 404
    assert "no-such-task" in response.json()["detail"]


def test_trades_lists_all_trades_with_ids(client: TestClient, price_task: dict) -> None:
    response = client.get("/tasks/task-prices/trades")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert [row["trade_id"] for row in payload["trades"]] == ["T001", "T002"]
    assert payload["trades"][1]["realized_pnl"] == pytest.approx(-5000.0)


def test_trades_supports_action_filter_and_limit(client: TestClient, price_task: dict) -> None:
    response = client.get("/tasks/task-prices/trades", params={"action": "SELL", "limit": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["trades"][0]["action"] == "SELL"


def test_trade_detail_returns_inspection(client: TestClient, price_task: dict) -> None:
    response = client.get("/tasks/task-prices/trades/T001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["trade_id"] == "T001"
    assert payload["trade"]["code"] == "2330"
    assert "price_context" in payload
    assert "cash_context" in payload


def test_trade_detail_supports_per_mode_summary_file(client: TestClient, price_task: dict) -> None:
    task_dir = price_task["tasks_root"] / "task-prices"
    (task_dir / "summary_per_stock.json").write_text(
        json.dumps({
            "metrics": {},
            "trades": [
                {"date": "2025-01-02", "code": "2454", "action": "BUY", "price": 51.0, "qty": 1000, "total": -51000.0},
            ],
            "data": {"path": str(price_task["data_root"])},
        }),
        encoding="utf-8",
    )

    response = client.get("/tasks/task-prices/trades/T001", params={"summary_file": "summary_per_stock.json"})

    assert response.status_code == 200
    assert response.json()["trade"]["code"] == "2454"


def test_trade_detail_rejects_unlisted_summary_file(client: TestClient, price_task: dict) -> None:
    response = client.get("/tasks/task-prices/trades/T001", params={"summary_file": "../../outside.json"})

    assert response.status_code == 422


def test_trade_detail_unknown_trade_returns_404(client: TestClient, price_task: dict) -> None:
    response = client.get("/tasks/task-prices/trades/T099")

    assert response.status_code == 404
    assert "T099" in response.json()["detail"]


def test_trades_unknown_task_returns_404(client: TestClient, tasks_root: Path) -> None:
    response = client.get("/tasks/no-such-task/trades")

    assert response.status_code == 404
    assert "no-such-task" in response.json()["detail"]


def test_trades_supports_per_mode_summary_file(client: TestClient, price_task: dict) -> None:
    task_dir = price_task["tasks_root"] / "task-prices"
    (task_dir / "summary_per_stock.json").write_text(
        json.dumps({
            "metrics": {},
            "trades": [
                {"date": "2025-01-02", "code": "2454", "action": "BUY", "price": 51.0, "qty": 1000, "total": -51000.0},
            ],
            "data": {"path": str(price_task["data_root"])},
        }),
        encoding="utf-8",
    )

    response = client.get("/tasks/task-prices/trades", params={"summary_file": "summary_per_stock.json"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["trades"][0]["code"] == "2454"


def test_trades_rejects_unlisted_summary_file(client: TestClient, price_task: dict) -> None:
    response = client.get("/tasks/task-prices/trades", params={"summary_file": "../../outside.json"})

    assert response.status_code == 422


def test_trades_missing_mode_summary_returns_404(client: TestClient, price_task: dict) -> None:
    response = client.get("/tasks/task-prices/trades", params={"summary_file": "summary_shared.json"})

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/tasks"),
        ("put", "/tasks/task-a"),
        ("delete", "/tasks/task-a/trades"),
        ("post", "/tasks/task-a/prices"),
    ],
)
def test_non_get_methods_are_rejected_405(client: TestClient, tasks_root: Path, method: str, path: str) -> None:
    """The API is read-only: write verbs on known routes must be rejected."""
    response = getattr(client, method)(path)

    assert response.status_code == 405
    assert response.json()["detail"]


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "research_web" / "dist" / "index.html").is_file(), reason="frontend not built")
def test_serves_frontend_at_root_when_built(client: TestClient) -> None:
    """The API process also serves the built research_web frontend (dashboard v2)."""
    response = client.get("/")

    assert response.status_code == 200
    assert 'id="root"' in response.text


def test_unexpected_errors_return_consistent_json_500(tasks_root: Path, monkeypatch: MonkeyPatch) -> None:
    make_task(tasks_root, "task-a")

    def boom(task_id: str) -> dict:
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(api_main.dashboard_core, "load_task_bundle", boom)
    client = TestClient(api_main.app, raise_server_exceptions=False)

    response = client.get("/tasks/task-a")

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
