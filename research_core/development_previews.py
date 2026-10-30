"""Local, explicitly registered worktree previews; never a data producer."""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from research_core.artifact_store import object_digest, release_os_lock, safe_path, try_os_lock, write_json
from research_core.dashboard_identity import dashboard_identity
from research_core.producer_data import primary_checkout, read_env_file_value

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")
ROUTE_PATTERN = re.compile(r"#(?:[a-z0-9][a-z0-9_-]*)(?:/[a-zA-Z0-9_-]+)*\Z")
DATA_KEYS = (
    "STOCK_PRODUCER_DATA_ROOT",
    "STOCK_RESEARCH_SHARED_ROOT",
    "STOCK_RESEARCH_DATA_ROOT",
    "STOCK_PRIVATE_ARTIFACT_ROOT",
    "STOCK_SAVED_STUDIO_PACKAGE",
    "STOCK_RESEARCH_DATA_MODE",
    "VITE_ARTIFACT_MODE",
)
START_SECONDS = 90
MAIN_START_SECONDS = 720


class PreviewError(ValueError):
    """A bounded preview operation cannot be safely completed."""


def _git(root: Path, *arguments: str) -> str:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=10,
        env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise PreviewError("無法確認開發目錄的 Git 身分。")
    return result.stdout.strip()


def _primary(root: Path) -> Path:
    value = primary_checkout(root)
    if value is None:
        raise PreviewError("找不到這個專案的主要工作目錄。")
    return safe_path(value)


def registry_directory(root: Path = ROOT) -> Path:
    return safe_path(_primary(root) / ".tmp" / "development-previews")


def _identifier(value: str) -> str:
    if not ID_PATTERN.fullmatch(value):
        raise PreviewError("預覽識別名稱只能使用小寫英文、數字與連字號。")
    return value


def loopback_url(value: str) -> str:
    parsed = urlsplit(value)
    try:
        valid = parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port is not None and parsed.port > 0
    except ValueError:
        valid = False
    if not valid or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise PreviewError("正式版網址必須是本機 Dashboard 的入口。")
    return value.rstrip("/") + "/"


@dataclass(frozen=True)
class Preview:
    id: str
    title: str
    worktree: str
    branch: str
    route: str
    pr: int | None
    web_port: int
    api_port: int


def _load(path: Path) -> Preview:
    try:
        data = json.loads(safe_path(path).read_text(encoding="utf-8"))
        item = Preview(**data)
        _identifier(item.id)
        if item.id != path.stem or not isinstance(item.title, str) or not item.title.strip() or len(item.title) > 120:
            raise ValueError("title/id")
        if not isinstance(item.worktree, str) or not isinstance(item.branch, str) or not item.branch:
            raise ValueError("worktree/branch")
        if not isinstance(item.route, str) or not ROUTE_PATTERN.fullmatch(item.route):
            raise ValueError("route")
        if item.pr is not None and (type(item.pr) is not int or item.pr < 1):
            raise ValueError("pr")
        if not all(type(port) is int and 20000 <= port < 30000 for port in (item.web_port, item.api_port)) or item.web_port == item.api_port:
            raise ValueError("ports")
        return item
    except (OSError, TypeError, ValueError) as exc:
        raise PreviewError("預覽登記無法讀取，請由開發 session 重新登記。") from exc


def _write(path: Path, value: Any) -> None:
    temporary = safe_path(path.parent / f".{uuid.uuid4().hex}.tmp")
    write_json(temporary, value)
    os.replace(temporary, safe_path(path))


@contextmanager
def _lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    with safe_path(directory / "registry.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        if not try_os_lock(handle):
            raise PreviewError("另一個預覽操作正在進行，請稍後再試。")
        try:
            yield
        finally:
            release_os_lock(handle)


def _validate_worktree(primary: Path, target: Path, branch: str | None = None) -> tuple[str, str]:
    target = safe_path(target)
    if not target.is_dir() or target == primary:
        raise PreviewError("預覽必須使用仍存在的獨立 worktree。")
    records = _git(primary, "worktree", "list", "--porcelain", "-z").split("\0")
    registered = {os.path.normcase(str(Path(line[9:]).absolute())) for line in records if line.startswith("worktree ")}
    if os.path.normcase(str(target)) not in registered or _primary(target) != primary:
        raise PreviewError("這個目錄已不屬於本專案的 worktree，請重新登記。")
    actual = _git(target, "branch", "--show-current")
    if not actual or actual in {"main", "master"} or (branch is not None and actual != branch):
        raise PreviewError("開發分支已改變，請重新登記這個預覽。")
    for relative in ("scripts/start_research_web.py", "research_web/package.json"):
        if not safe_path(target / relative).is_file():
            raise PreviewError("開發目錄缺少標準網站啟動器。")
    return actual, _git(target, "rev-parse", "HEAD")


def _available(port: int) -> bool:
    with socket.socket() as connection:
        try:
            connection.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def register(*, identifier: str, title: str, route: str, worktree: Path, pr: int | None = None, root: Path = ROOT) -> Preview:
    identifier = _identifier(identifier)
    if not title.strip() or len(title) > 120 or not ROUTE_PATTERN.fullmatch(route) or (pr is not None and (type(pr) is not int or pr < 1)):
        raise PreviewError("請提供有效的名稱、頁面路徑與 PR 編號。")
    primary = _primary(root)
    target = safe_path(worktree.absolute())
    branch, _ = _validate_worktree(primary, target)
    directory = registry_directory(root)
    with _lock(directory):
        path = directory / f"{identifier}.json"
        previous = _load(path) if path.exists() else None
        if previous and (previous.worktree != str(target) or previous.branch != branch):
            state = _state(previous, primary, directory, dict(os.environ))
            if state["status"] in {"ready", "starting"}:
                raise PreviewError("原預覽仍在使用中，請關閉分頁並等服務結束後更新位置。")
        ports: tuple[int, int] | None
        if previous:
            ports = (previous.web_port, previous.api_port)
        else:
            used = {
                port
                for path in directory.glob("*.json")
                if not path.name.endswith(".launch.json")
                for item in [_load(path)]
                for port in (item.web_port, item.api_port)
            }
            ports = next(
                (
                    (port, port + 1)
                    for port in range(20000, 30000, 2)
                    if port not in used and port + 1 not in used and _available(port) and _available(port + 1)
                ),
                None,
            )
            if ports is None:
                raise PreviewError("目前沒有可用的預覽連接埠。")
        item = Preview(identifier, title.strip(), str(target), branch, route, pr, *ports)
        _write(path, asdict(item))
    LOGGER.info("Registered development preview %s on %s", identifier, branch)
    return item


def retire(identifier: str, *, root: Path = ROOT) -> None:
    directory = registry_directory(root)
    with _lock(directory):
        safe_path(directory / f"{_identifier(identifier)}.json").unlink(missing_ok=True)
    LOGGER.info("Retired preview registration %s; processes and files preserved", identifier)


def preview_environment(primary: Path, environment: Mapping[str, str]) -> dict[str, str]:
    result = {key: value for key, value in environment.items() if not key.startswith("GIT_")}
    for key in DATA_KEYS:
        value = environment.get(key)
        if value is None:
            value = read_env_file_value(primary / ".env.local", key)
        if value is not None:
            result[key] = value
    modes = {result[key] for key in ("STOCK_RESEARCH_DATA_MODE", "VITE_ARTIFACT_MODE") if key in result}
    if len(modes) > 1 or (modes and not modes <= {"local-private", "public-synthetic"}):
        raise PreviewError("目前前後端資料模式不一致，請先修正設定。")
    mode = next(iter(modes), "local-private" if result.get("STOCK_PRIVATE_ARTIFACT_ROOT") else "public-synthetic")
    result.update(STOCK_RESEARCH_DATA_MODE=mode, VITE_ARTIFACT_MODE=mode, VITE_API_BASE="/api")
    return result


def _configuration(environment: Mapping[str, str]) -> str:
    return object_digest({key: environment.get(key) for key in DATA_KEYS})


def _json_response(port: int, path: str) -> dict[str, Any] | None:
    # No redirects/proxies: identities must come from the selected local socket.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(f"http://127.0.0.1:{port}{path}", timeout=0.3) as response:
            value = json.loads(response.read(65536))
            return value if isinstance(value, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _state(item: Preview, primary: Path, directory: Path, environment: Mapping[str, str]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": item.id,
        "title": item.title,
        "pr": item.pr,
        "branch": item.branch,
        "head": "",
        "status": "unavailable",
        "message": "",
        "url": None,
    }
    try:
        _, row["head"] = _validate_worktree(primary, Path(item.worktree), item.branch)
        expected = preview_environment(primary, environment)
        web = _json_response(item.web_port, "/__research_service__")
        api = _json_response(item.api_port, "/__research_service__")
        launch_file = directory / f"{item.id}.launch.json"
        launch = json.loads(safe_path(launch_file).read_text(encoding="utf-8")) if launch_file.exists() else {}
        pending = isinstance(launch, dict) and 0 <= time.time() - float(launch.get("started", 0)) < START_SECONDS
        if web is None and api is None and _available(item.web_port) and _available(item.api_port):
            row.update(status="starting" if pending else "stopped", message="正在啟動預覽。" if pending else "開啟時會啟動這個項目的預覽。")
            return row
        if web is None or api is None:
            row.update(
                status="starting" if pending else "unavailable",
                message="正在確認前後端服務。" if pending else "預覽服務不完整或連接埠已被占用，請由開發 session 檢查。",
            )
            return row
        for identity, service in ((web, "research-web"), (api, "history-api")):
            if (
                identity.get("schema") != "stock-research-service.v1"
                or identity.get("service") != service
                or os.path.normcase(str(Path(str(identity.get("projectRoot", ""))).absolute())) != os.path.normcase(item.worktree)
            ):
                raise PreviewError("連接埠上的服務不是這個開發項目；不會接管或停止它。")
            if identity.get("dataMode") != expected["STOCK_RESEARCH_DATA_MODE"]:
                raise PreviewError("預覽與正式版的資料模式不同，請由開發 session 檢查。")
        if web.get("build") != "development" or web.get("apiTarget") != f"http://127.0.0.1:{item.api_port}":
            raise PreviewError("前端沒有連到這個預覽的 API，請由開發 session 檢查。")
        config = _configuration(expected)
        if api.get("previewConfigId") != config:
            raise PreviewError("無法確認共用資料設定一致；請更新分支的預覽支援，並重新啟動。")
        expected_identity = dashboard_identity(expected)
        if api.get("configVersion") != expected_identity["configVersion"] or api.get("configId") != expected_identity["configId"]:
            raise PreviewError("預覽尚未提供完整資料位置核對，或使用的資料位置已改變，請更新並重新啟動。")
        reports = _json_response(item.web_port, "/reports/index.json")
        if not reports or reports.get("version") != "development":
            raise PreviewError("報告清單與開發頁面版本不同，請由開發 session 檢查。")
        row.update(status="ready", message="使用正式版的資料來源，呈現開發中的修改。", url=f"http://127.0.0.1:{item.web_port}/{item.route}")
    except (PreviewError, OSError, ValueError, subprocess.SubprocessError) as exc:
        row["message"] = str(exc) if isinstance(exc, PreviewError) else "無法確認預覽狀態，請由開發 session 檢查登記與啟動紀錄。"
    return row


def list_previews(*, root: Path = ROOT, environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    environment = os.environ if environment is None else environment
    primary = _primary(root)
    directory = registry_directory(root)
    items = []
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith(".launch.json"):
            continue
        try:
            items.append(_state(_load(path), primary, directory, environment))
        except PreviewError:
            LOGGER.warning("Ignoring invalid preview registration %s", path.name)
    current = None
    current_id = environment.get("RESEARCH_PREVIEW_ID")
    for item in items:
        if item["id"] == current_id:
            current = {
                "id": item["id"],
                "title": item["title"],
                "pr": item["pr"],
                "mainUrl": loopback_url(environment.get("RESEARCH_PREVIEW_MAIN_URL", "http://127.0.0.1:5177/")),
            }
    return {"items": items, "current": current}


def open_preview(identifier: str, *, root: Path = ROOT, environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    environment = os.environ if environment is None else environment
    primary = _primary(root)
    directory = registry_directory(root)
    with _lock(directory):
        item = _load(directory / f"{_identifier(identifier)}.json")
        state = _state(item, primary, directory, environment)
        if state["status"] != "stopped":
            return {key: state[key] for key in ("status", "url", "message")}
        target = Path(item.worktree)
        _validate_worktree(primary, target, item.branch)
        child_environment = preview_environment(primary, environment)
        child_environment.update(
            RESEARCH_WEB_VERSION="development",
            RESEARCH_PREVIEW_ID=item.id,
            RESEARCH_PREVIEW_MAIN_URL=loopback_url(
                environment.get("RESEARCH_PREVIEW_MAIN_URL") or environment.get("RESEARCH_WEB_URL", "http://127.0.0.1:5177/")
            ),
            RESEARCH_PREVIEW_CONFIG_ID=_configuration(child_environment),
            RESEARCH_PREVIEW_MAIN_API_TARGET=loopback_url(
                environment.get("RESEARCH_PREVIEW_MAIN_API_TARGET") or environment.get("RESEARCH_WEB_API_TARGET", "http://127.0.0.1:8517/")
            ),
        )
        pid = _detach("preview", identifier=item.id, root=root, environment=child_environment)
        _write(directory / f"{item.id}.launch.json", {"started": time.time(), "pid": pid})
    LOGGER.info("Started development preview %s (launcher %s)", item.id, pid)
    return {"status": "starting", "url": None, "message": "正在啟動；完成後即可開啟預覽。"}


def _main_urls(environment: Mapping[str, str]) -> tuple[str, str]:
    web = loopback_url(environment.get("RESEARCH_PREVIEW_MAIN_URL", "http://127.0.0.1:5177/"))
    api = loopback_url(environment.get("RESEARCH_PREVIEW_MAIN_API_TARGET", "http://127.0.0.1:8517/"))
    if web == api:
        raise PreviewError("正式版的網站與 API 連接埠不可相同。")
    return web, api


def main_environment(primary: Path, environment: Mapping[str, str]) -> dict[str, str]:
    """Read primary configuration afresh; preview overrides cannot become main."""
    excluded = {*DATA_KEYS, "VITE_API_BASE", "RESEARCH_WEB_VERSION", "RESEARCH_WEB_URL", "RESEARCH_WEB_API_TARGET", "RESEARCH_WEB_BUILD"}
    result = {
        key: value
        for key, value in environment.items()
        if key not in excluded and not key.startswith(("GIT_", "RESEARCH_PREVIEW_", "RESEARCH_DESKTOP_", "RESEARCH_WEB_BUILD_"))
    }
    return preview_environment(primary, result)


def _main_setup(root: Path, environment: Mapping[str, str]) -> tuple[Path, str, str, dict[str, str]]:
    primary = _primary(root)
    if _git(primary, "branch", "--show-current") != "main":
        raise PreviewError("主要工作目錄目前不在 main，請由開發 session 確認後再啟動正式版。")
    if not safe_path(primary / "scripts/start_research_web.py").is_file():
        raise PreviewError("正式版缺少標準啟動器。")
    web, api = _main_urls(environment)
    return primary, web, api, main_environment(primary, environment)


def _main_status(root: Path, environment: Mapping[str, str]) -> dict[str, Any]:
    primary, web_url, api_url, expected = _main_setup(root, environment)
    web_port, api_port = urlsplit(web_url).port, urlsplit(api_url).port
    assert web_port is not None and api_port is not None
    launch_path = registry_directory(root) / ".main.launch.json"
    launch = json.loads(safe_path(launch_path).read_text(encoding="utf-8")) if launch_path.exists() else {}
    pending = isinstance(launch, dict) and 0 <= time.time() - float(launch.get("started", 0)) < MAIN_START_SECONDS
    found: list[dict[str, Any] | None] = []
    for port, service in ((web_port, "research-web"), (api_port, "history-api")):
        identity = _json_response(port, "/__research_service__")
        if identity is None:
            if not _available(port):
                if pending:
                    return {"status": "starting", "url": None, "message": "正在確認正式版服務，完成後即可返回。"}
                raise PreviewError("正式版連接埠已被無法確認的服務占用，不會停止或接管它。")
            found.append(None)
            continue
        if (
            identity.get("schema") != "stock-research-service.v1"
            or identity.get("service") != service
            or os.path.normcase(str(Path(str(identity.get("projectRoot", ""))).absolute())) != os.path.normcase(str(primary))
        ):
            raise PreviewError("正式版連接埠屬於其他服務，不會停止或接管它。")
        if identity.get("dataMode") != expected["STOCK_RESEARCH_DATA_MODE"]:
            raise PreviewError("執行中的正式版與目前資料設定不同，請由開發 session 檢查。")
        if service == "history-api":
            expected_identity = dashboard_identity(expected)
            if identity.get("configVersion") != expected_identity["configVersion"]:
                return {
                    "status": "unavailable",
                    "url": None,
                    "reason": "identity_update_required",
                    "message": "正式版需要更新；更新並重新開啟後，就能從這裡返回。",
                }
            if identity.get("configId") != expected_identity["configId"]:
                raise PreviewError("正式版 API 的資料設定已改變，請由開發 session 檢查。")
        if service == "research-web":
            if identity.get("build") != "production" or identity.get("apiTarget", "").rstrip("/") != api_url.rstrip("/"):
                raise PreviewError("執行中的頁面不是正式版，或未連到正式版 API。")
            release = identity.get("release")
            index = _json_response(port, "/reports/index.json")
            manifest = _json_response(port, "/release.json")
            if not release or release == "development" or not index or not manifest or index.get("version") != release or manifest.get("version") != release:
                raise PreviewError("正式版頁面與報告清單版本不同，請由開發 session 檢查。")
        found.append(identity)
    if all(found):
        return {"status": "ready", "url": web_url, "message": "正式版已就緒。"}
    if pending:
        return {"status": "starting", "url": None, "message": "正在啟動正式版；首次啟動可能需要建置頁面。"}
    return {"status": "stopped", "url": None, "message": "正式版尚未完整啟動，可以從這裡啟動後返回。"}


def main_status(*, root: Path = ROOT, environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    try:
        return _main_status(root, os.environ if environment is None else environment)
    except (PreviewError, OSError, ValueError, subprocess.SubprocessError) as exc:
        message = str(exc) if isinstance(exc, PreviewError) else "暫時無法確認正式版狀態，請稍後重試。"
        return {"status": "unavailable", "url": None, "message": message}


def open_main(*, root: Path = ROOT, environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    environment = os.environ if environment is None else environment
    directory = registry_directory(root)
    with _lock(directory):
        status = main_status(root=root, environment=environment)
        if status["status"] != "stopped":
            return status
        primary, web, api, child_environment = _main_setup(root, environment)
        # Only the short-lived helper receives these routing hints. It strips
        # them again before spawning the primary launcher's production process.
        child_environment.update(RESEARCH_PREVIEW_MAIN_URL=web, RESEARCH_PREVIEW_MAIN_API_TARGET=api)
        pid = _detach("main", root=root, environment=child_environment)
        _write(directory / ".main.launch.json", {"started": time.time(), "pid": pid})
    LOGGER.info("Started primary dashboard launcher %s from %s", pid, primary)
    return {"status": "starting", "url": None, "message": "正在啟動正式版；完成後會返回正式版頁面。"}


def _python(primary: Path) -> Path:
    executable = primary / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return executable if executable.is_file() else Path(sys.executable)


def _detach(kind: str, *, root: Path, environment: Mapping[str, str], identifier: str | None = None) -> int:
    """Wait for an intermediate parent to exit, breaking taskkill /T ancestry."""
    command = [str(_python(_primary(root))), "-B", "-m", "research_core.development_previews", f"--detach-{kind}"]
    if identifier is not None:
        command.append(_identifier(identifier))
    with safe_path(registry_directory(root) / "detach.log").open("ab") as output:
        result = subprocess.run(
            command,
            cwd=root,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=output,
            timeout=20,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    try:
        pid = int(result.stdout)
        if result.returncode or pid <= 0:
            raise ValueError("spawn failed")
    except (ValueError, TypeError) as exc:
        raise PreviewError("啟動器未能完成啟動，請由開發 session 檢查啟動紀錄。") from exc
    return pid


def _spawn_detached(kind: str, *, root: Path, environment: Mapping[str, str], identifier: str | None = None) -> int:
    """Internal helper: only fixed primary or CLI-registered preview launchers."""
    primary = _primary(root)
    if kind == "main":
        target, web, api, child_environment = _main_setup(root, environment)
        web_port, api_port = urlsplit(web).port, urlsplit(api).port
        options: list[str] = []
        logfile = ".main.log"
    elif kind == "preview" and identifier is not None:
        item = _load(registry_directory(root) / f"{_identifier(identifier)}.json")
        target = Path(item.worktree)
        _validate_worktree(primary, target, item.branch)
        web_port, api_port = item.web_port, item.api_port
        child_environment = dict(environment)
        options = ["--dev"]
        logfile = f"{item.id}.log"
    else:
        raise PreviewError("不支援這個啟動操作。")
    command = [
        str(_python(primary)),
        "-B",
        str(target / "scripts/start_research_web.py"),
        *options,
        "--desktop",
        "--no-browser",
        "--web-port",
        str(web_port),
        "--api-port",
        str(api_port),
    ]
    with safe_path(registry_directory(root) / logfile).open("ab") as output:
        process = subprocess.Popen(
            command,
            cwd=target,
            env=child_environment,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            start_new_session=os.name != "nt",
            close_fds=True,
        )
    return process.pid


if __name__ == "__main__":
    # Private, fixed helper protocol. No arbitrary paths, command or shell input.
    arguments = sys.argv[1:]
    if arguments == ["--detach-main"]:
        launched = _spawn_detached("main", root=ROOT, environment=os.environ)
    elif len(arguments) == 2 and arguments[0] == "--detach-preview":
        launched = _spawn_detached("preview", root=ROOT, environment=os.environ, identifier=arguments[1])
    else:
        raise SystemExit("Use python -m scripts.development_preview for preview management.")
    sys.stdout.write(str(launched))
