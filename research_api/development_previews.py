"""Local-only control surface for explicitly registered development previews."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request

from research_core.development_previews import PreviewError, list_previews, loopback_url, open_preview


def _local_request(request: Request, *, mutation: bool) -> None:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "預覽入口只接受本機操作。")
    try:
        web = loopback_url(os.environ.get("RESEARCH_WEB_URL", "http://127.0.0.1:5177/"))
        api = loopback_url(os.environ.get("RESEARCH_WEB_API_TARGET", "http://127.0.0.1:8517/"))
    except PreviewError as exc:
        raise HTTPException(503, str(exc)) from exc
    hosts = {urlsplit(url).netloc for url in (web, api)}
    if request.headers.get("host") not in hosts:
        raise HTTPException(403, "預覽入口的本機網址不符。")
    origin = request.headers.get("origin")
    if origin is not None and origin != web.rstrip("/"):
        raise HTTPException(403, "請從目前的 Dashboard 開啟預覽。")
    if mutation and (request.headers.get("x-requested-with") != "development-preview" or origin is None):
        raise HTTPException(403, "缺少預覽操作的來源確認。")


def create_development_preview_router(root: Path | None = None) -> APIRouter:
    router = APIRouter()
    root = root or Path(__file__).resolve().parents[1]

    @router.get("/development-previews")
    def previews(request: Request) -> dict:
        _local_request(request, mutation=False)
        try:
            return list_previews(root=root)
        except (PreviewError, OSError) as exc:
            raise HTTPException(503, "預覽清單暫時無法讀取，請稍後重試。") from exc

    @router.post("/development-previews/{identifier}/open")
    def open_registered_preview(identifier: str, request: Request) -> dict:
        _local_request(request, mutation=True)
        try:
            return open_preview(identifier, root=root)
        except PreviewError as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "無法啟動預覽，請由開發 session 檢查啟動紀錄。") from exc

    return router
