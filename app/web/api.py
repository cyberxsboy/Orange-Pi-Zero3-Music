"""REST API 路由.

所有响应统一::

    {"code": 0, "msg": "ok", "data": ...}
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..audio.devices import list_devices
from ..constants import (
    ERR_AUDIO_DEVICE,
    ERR_CONFLICT,
    ERR_INTERNAL,
    ERR_NOT_FOUND,
    ERR_PARAM,
    ERR_PLAYER_BUSY,
)
from ..logger import get_logger
from ..sources.models import MusicSourceCreate, MusicSourceUpdate

log = get_logger(__name__)
router = APIRouter(prefix="/api")

_started_at: float = time.time()


# ─────────── 响应包装 ───────────


def ok(data: Any = None, msg: str = "ok") -> dict:
    return {"code": 0, "msg": msg, "data": data}


def err(code: int, msg: str, http: int = 400) -> JSONResponse:
    return JSONResponse(status_code=http, content={"code": code, "msg": msg, "data": None})


# ─────────── health ───────────


@router.get("/health")
async def health() -> dict:
    return ok({"ok": True, "uptime_s": time.time() - _started_at})


# ─────────── 音乐源 ───────────


@router.get("/sources")
async def list_sources(request: Request) -> dict:
    mgr = request.app.state.sources
    items = await mgr.list()
    return ok(items)


@router.get("/sources/{source_id}")
async def get_source(source_id: str, request: Request) -> dict:
    mgr = request.app.state.sources
    item = await mgr.get(source_id)
    if not item:
        raise HTTPException(status_code=404, detail=err(ERR_NOT_FOUND, "not found").body.decode())
    return ok(item)


@router.post("/sources")
async def create_source(payload: MusicSourceCreate, request: Request) -> dict:
    mgr = request.app.state.sources
    try:
        item = await mgr.create(payload)
        return ok(item, "created")
    except ValueError as exc:
        return err(ERR_CONFLICT, str(exc), http=409)
    except Exception as exc:  # noqa: BLE001
        log.exception("create source failed: %s", exc)
        return err(ERR_INTERNAL, "internal error", http=500)


@router.put("/sources/{source_id}")
async def update_source(source_id: str, payload: MusicSourceUpdate, request: Request) -> dict:
    mgr = request.app.state.sources
    item = await mgr.update(source_id, payload)
    if not item:
        return err(ERR_NOT_FOUND, "not found", http=404)
    return ok(item, "updated")


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str, request: Request) -> dict:
    mgr = request.app.state.sources
    ok_ = await mgr.delete(source_id)
    if not ok_:
        return err(ERR_NOT_FOUND, "not found", http=404)
    return ok({"id": source_id}, "deleted")


@router.post("/sources/{source_id}/rescan")
async def rescan_source(source_id: str, request: Request) -> dict:
    mgr = request.app.state.sources
    n = await mgr.rescan(source_id)
    return ok({"scanned": n})


# ─────────── 播放控制 ───────────


class VolumeBody(BaseModel):
    value: int = Field(..., ge=0, le=100)


class PlayBody(BaseModel):
    shuffle: bool = False


@router.post("/player/play/{source_id}")
async def player_play(source_id: str, body: PlayBody, request: Request) -> dict:
    mgr = request.app.state.sources
    player = request.app.state.player
    try:
        src, urls = await mgr.resolve(source_id)
    except KeyError:
        return err(ERR_NOT_FOUND, "source not found", http=404)
    except ValueError as exc:
        return err(ERR_PARAM, str(exc), http=400)
    try:
        count = await player.play_source(
            source_id=source_id,
            source_name=src.get("name", ""),
            urls=urls,
            shuffle=body.shuffle or src.get("shuffle", False),
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("play failed: %s", exc)
        return err(ERR_PLAYER_BUSY, str(exc), http=503)
    return ok({"queued": count, "source_id": source_id, "name": src.get("name", "")})


@router.post("/player/play")
async def player_resume(request: Request) -> dict:
    player = request.app.state.player
    await player.resume()
    return ok({"state": "playing"})


@router.post("/player/pause")
async def player_pause(request: Request) -> dict:
    player = request.app.state.player
    await player.pause()
    return ok({"state": "paused"})


@router.post("/player/stop")
async def player_stop(request: Request) -> dict:
    player = request.app.state.player
    await player.stop()
    return ok({"state": "idle"})


@router.post("/player/next")
async def player_next(request: Request) -> dict:
    player = request.app.state.player
    await player.next()
    return ok({"next": True})


@router.post("/player/prev")
async def player_prev(request: Request) -> dict:
    player = request.app.state.player
    await player.prev()
    return ok({"prev": True})


@router.post("/player/volume")
async def player_volume(body: VolumeBody, request: Request) -> dict:
    player = request.app.state.player
    await player.set_volume(body.value)
    return ok({"volume": body.value})


# ─────────── 状态 / 日志 / 设备 ───────────


@router.get("/status")
async def status(request: Request) -> dict:
    player = request.app.state.player
    state = await player.backend.get_state()
    current = await player.backend.get_current()
    volume = await player.backend.get_volume()
    queue_size = len(player.queue)
    return ok({
        "player": state,
        "current": current.to_dict() if current else None,
        "volume": volume,
        "queue_size": queue_size,
        "uptime_s": time.time() - _started_at,
    })


@router.get("/logs")
async def get_logs(lines: int = Query(200, ge=1, le=2000), request: Request = None) -> dict:
    log_file: Path = request.app.state.log_file
    if not log_file.exists():
        return ok({"lines": []})
    try:
        with log_file.open("rb") as f:
            data = f.read()[-200_000:]  # 最多读最后 200KB
        text = data.decode("utf-8", errors="ignore")
        all_lines = text.splitlines()
        return ok({"lines": all_lines[-lines:]})
    except Exception as exc:  # noqa: BLE001
        return err(ERR_INTERNAL, str(exc), http=500)


@router.get("/audio/devices")
async def audio_devices() -> dict:
    return ok(list_devices())
