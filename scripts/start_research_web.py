"""Start the local history API and research web development server."""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research_core.dashboard_identity import dashboard_identity
from research_core.producer_data import primary_checkout, read_env_file_value
from research_core.saved_research_studio import StudioError, read_studio_package

LOGGER = logging.getLogger("research_web_launcher")
SCHEMA = "stock-research-service.v1"
SERVICES = (
    ("history-api", 8517),
    ("research-web", 5177),
)
IDENTITY_PATH = "/__research_service__"
STARTUP_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 0.25
MODE_KEYS = ("VITE_ARTIFACT_MODE", "STOCK_RESEARCH_DATA_MODE")
PATH_KEYS = ("STOCK_PRIVATE_ARTIFACT_ROOT", "STOCK_SAVED_STUDIO_PACKAGE")


def launch_environment(root: Path, environ: dict[str, str]) -> dict[str, str]:
    """Resolve launcher settings without modifying the caller's environment."""
    environment = dict(environ)
    primary = primary_checkout(root)
    local = {key: read_env_file_value(primary / ".env.local", key) for key in (*MODE_KEYS, *PATH_KEYS)} if primary is not None else {}
    # An explicit process mode overrides both file modes, including demo use.
    modes = [environ[key] for key in MODE_KEYS if key in environ]
    if not modes:
        modes = [value for key in MODE_KEYS if (value := local.get(key)) is not None]
    if any(mode not in {"local-private", "public-synthetic"} for mode in modes) or len(set(modes)) > 1:
        raise RuntimeError("資料模式無效或前後端模式衝突。")
    for key in PATH_KEYS:
        if key not in environment and local.get(key) is not None:
            environment[key] = str(local[key])
    configured = [key in environment for key in PATH_KEYS]
    mode = modes[0] if modes else ("local-private" if any(configured) else "public-synthetic")
    if mode == "local-private":
        if not all(configured):
            raise RuntimeError("私有模式需要 STOCK_PRIVATE_ARTIFACT_ROOT 與 STOCK_SAVED_STUDIO_PACKAGE。")
        for key in PATH_KEYS:
            value = environment[key]
            if not value.strip() or not Path(value).is_absolute():
                raise RuntimeError(f"{key} 必須是非空的絕對路徑。")
        if not Path(environment[PATH_KEYS[0]]).is_dir():
            raise RuntimeError("私有 artifact 目錄無法讀取。")
        try:
            read_studio_package(Path(environment[PATH_KEYS[1]]))
        except (OSError, StudioError) as exc:
            raise RuntimeError(f"私有 studio 包無法讀取或未通過完整性驗證：{exc}") from exc
    for key in MODE_KEYS:
        environment[key] = str(mode)
    return environment


def _verify_live_mode(name: str, port: int, environment: dict[str, str]) -> None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{IDENTITY_PATH}", timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("dataMode") != environment[MODE_KEYS[0]]:
            raise ValueError("資料模式不符或服務版本尚未提供模式")
        if name == "history-api" and payload.get("configId") != dashboard_identity(environment)["configId"]:
            raise ValueError("私有來源設定不符或服務版本尚未提供設定身份")
        if name == "history-api" and "RESEARCH_WEB_URL" in environment and payload.get("webUrl") != environment["RESEARCH_WEB_URL"]:
            raise ValueError("API 記錄的網站網址不符")
        if name == "research-web" and payload.get("apiTarget") != environment["RESEARCH_WEB_API_TARGET"]:
            raise ValueError("前端 API proxy 目標不符")
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"{name}（{port}）無法確認預期資料模式：{exc}；不會停止既有服務。") from exc


def _announce(message: str) -> None:
    """Write deliberate CLI status, independently of the persistent log."""
    sys.stdout.write(message + "\n")


@dataclass
class ManagedChild:
    name: str
    process: subprocess.Popen[bytes]
    log_file: Any


def project_root() -> Path:
    """Return the checkout root from this script's location."""
    return Path(__file__).resolve().parents[1]


def _port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _read_identity(port: int, root: Path, service_name: str | None = None) -> tuple[bool, str]:
    url = f"http://127.0.0.1:{port}{IDENTITY_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=1.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError, UnicodeDecodeError) as exc:
        return False, f"無法讀取服務身份（{exc}）"
    if not isinstance(payload, dict):
        return False, "身份回應不是 JSON 物件"

    expected_service = service_name or next(name for name, service_port in SERVICES if service_port == port)
    if payload.get("schema") != SCHEMA:
        return False, f"schema 不符：{payload.get('schema')!r}"
    if payload.get("service") != expected_service:
        return False, f"服務角色不符：{payload.get('service')!r}"
    reported_root = payload.get("projectRoot")
    if not isinstance(reported_root, str) or not Path(reported_root).is_absolute():
        return False, "projectRoot 缺失或不是絕對路徑"
    try:
        same_checkout = Path(reported_root).samefile(root)
    except OSError as exc:
        return False, f"無法核對 projectRoot（{exc}）"
    if not same_checkout:
        return False, f"服務來自其他 checkout：{reported_root}"
    return True, "身份正確"


def _inspect_service(name: str, port: int, root: Path) -> str:
    if not _port_is_open(port):
        return "stopped"
    valid, reason = _read_identity(port, root, name)
    if valid:
        return "reusable"
    raise RuntimeError(f"埠 {port} 已被未知或不相符的服務占用（{reason}）；為避免影響其他程序，啟動器不會終止它。")


def _command(name: str, root: Path, port: int | None = None) -> list[str]:
    if name == "history-api":
        uv = shutil.which("uv")
        if uv is None:
            raise RuntimeError("找不到 uv；請先在專案環境安裝 uv。")
        return [
            uv,
            "run",
            "python",
            "-m",
            "uvicorn",
            "research_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port or 8517),
        ]

    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if npm is None:
        raise RuntimeError("找不到 npm；請先安裝 Node.js 與研究網站相依套件。")
    return [
        npm,
        "--prefix",
        str(root / "research_web"),
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        str(port or 5177),
        "--strictPort",
    ]


def _start_child(name: str, root: Path, log_dir: Path, environment: dict[str, str] | None = None, port: int | None = None) -> ManagedChild:
    log_path = log_dir / f"{name}.log"
    log_file = log_path.open("ab")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            _command(name, root, port),
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    except OSError:
        log_file.close()
        raise
    LOGGER.info("已啟動 %s，pid=%s，記錄檔=%s", name, process.pid, log_path)
    return ManagedChild(name=name, process=process, log_file=log_file)


def _stop_child(child: ManagedChild) -> None:
    process = child.process
    if process.poll() is None:
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired):
                LOGGER.exception("無法停止 %s 的子程序樹", child.name)
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    child.log_file.close()
    LOGGER.info("已停止本次啟動的 %s", child.name)


def _wait_until_ready(child: ManagedChild, port: int, root: Path) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        exit_code = child.process.poll()
        if exit_code is not None:
            raise RuntimeError(f"{child.name} 啟動失敗（結束碼 {exit_code}）；詳見 .tmp/research-web-launcher/{child.name}.log。")
        if _port_is_open(port):
            valid, reason = _read_identity(port, root, child.name)
            if valid:
                return
            # A just-started server can bind its socket before registering routes.
            if "schema 不符" not in reason and "服務角色不符" not in reason:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            raise RuntimeError(f"{child.name} 回報的服務身份不符：{reason}")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError(f"等待 {child.name} 就緒逾時；詳見 .tmp/research-web-launcher/{child.name}.log。")


def _configure_logging(root: Path) -> Path:
    log_dir = root / ".tmp" / "research-web-launcher"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_dir / "launcher.log", encoding="utf-8")],
    )
    return log_dir


def run(*, no_browser: bool = False, check: bool = False, api_port: int = 8517, web_port: int = 5177) -> int:
    root = project_root()
    if api_port == web_port or not all(1 <= port <= 65535 for port in (api_port, web_port)):
        raise RuntimeError("API 與網站 port 必須不同，且介於 1–65535。")
    environment = launch_environment(root, dict(os.environ))
    environment["RESEARCH_WEB_API_TARGET"] = f"http://127.0.0.1:{api_port}"
    # The API points visitors of its own port to the real website.
    environment["RESEARCH_WEB_URL"] = f"http://127.0.0.1:{web_port}"
    mode = environment[MODE_KEYS[0]]
    _announce(f"資料模式：{mode}")
    _announce(
        "私有 studio 包：可讀，已通過 reader 完整性驗證" if mode == "local-private" else "目前是合成示範，設定方式見 research_web/README.md；私有包未讀取。"
    )
    services = (("history-api", api_port), ("research-web", web_port))
    try:
        states = {name: _inspect_service(name, port, root) for name, port in services}
        for name, port in services:
            if states[name] == "reusable":
                _verify_live_mode(name, port, environment)
    except KeyboardInterrupt:
        _announce("檢查期間收到 Ctrl+C，沒有啟動任何服務。")
        return 130
    if check:
        for name, port in services:
            _announce(f"{name}（{port}）：{'可用' if states[name] == 'reusable' else '未啟動'}")
        return 0 if all(state == "reusable" for state in states.values()) else 1

    log_dir = _configure_logging(root)
    children: list[ManagedChild] = []
    try:
        for name, port in services:
            if states[name] == "reusable":
                _announce(f"沿用現有 {name}（{port}）")
                continue
            _announce(f"正在啟動 {name}（{port}）…")
            child = _start_child(name, root, log_dir, environment, port)
            children.append(child)
            _wait_until_ready(child, port, root)
            _verify_live_mode(name, port, environment)
            _announce(f"{name} 已就緒")
        _announce(f"研究網站已就緒：http://127.0.0.1:{web_port}")
        _announce("服務記錄位於 .tmp/research-web-launcher/")
        if not no_browser:
            webbrowser.open(f"http://127.0.0.1:{web_port}")
        while children:
            failed_child = next(
                (child for child in children if child.process.poll() is not None),
                None,
            )
            if failed_child is not None:
                raise RuntimeError(
                    f"{failed_child.name} 意外結束（結束碼 {failed_child.process.returncode}）；詳見 .tmp/research-web-launcher/{failed_child.name}.log。"
                )
            time.sleep(0.5)
        return 0
    except KeyboardInterrupt:
        _announce("收到 Ctrl+C，正在停止本次啟動的服務…")
        return 130
    except (OSError, RuntimeError) as exc:
        sys.stderr.write(f"啟動失敗：{exc}\n")
        LOGGER.exception("啟動研究網站失敗")
        return 1
    finally:
        for child in reversed(children):
            _stop_child(child)


def main() -> int:
    # Windows redirected streams can default to cp1252 even though this CLI
    # deliberately speaks Chinese. Set only this process's console transport.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="啟動研究網站與歷史 API")
    parser.add_argument("--no-browser", action="store_true", help="啟動後不開啟瀏覽器")
    parser.add_argument("--check", action="store_true", help="只檢查兩個服務身份與可用狀態")
    parser.add_argument("--api-port", type=int, default=8517, help="API port")
    parser.add_argument("--web-port", type=int, default=5177, help="網站 port")
    args = parser.parse_args()
    try:
        return run(no_browser=args.no_browser, check=args.check, api_port=args.api_port, web_port=args.web_port)
    except (RuntimeError, ValueError, OSError) as exc:
        sys.stderr.write(f"啟動失敗：{exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
