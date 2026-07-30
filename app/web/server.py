"""FastAPI app 工厂."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..logger import get_logger

log = get_logger(__name__)


def create_app(web_dir: Path, api_router) -> FastAPI:
    """构造 FastAPI 实例.

    Args:
        web_dir: 前端文件根目录
        api_router: APIRouter（由 api.py 提供）
    """
    app = FastAPI(
        title="OPI Music Player",
        version="0.1.0",
        description="Orange Pi Zero3 智能语音音乐播放器",
    )
    app.include_router(api_router)

    # 静态资源
    static_dir = web_dir / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        idx = web_dir / "index.html"
        if not idx.exists():
            return FileResponse(content=b"<h1>frontend missing</h1>", media_type="text/html")
        return FileResponse(str(idx))

    return app
