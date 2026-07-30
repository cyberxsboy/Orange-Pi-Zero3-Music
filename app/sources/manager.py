"""音乐源 CRUD 持久化管理.

- 文件锁保证并发安全（fcntl / msvcrt）
- 原子写入（tmp + replace）
- 热加载（通过 watchfiles 监听文件变更）
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..constants import SourceType
from ..logger import get_logger
from ..utils.filelock import atomic_write_json, file_lock
from ..utils.ids import new_id
from .local import scan_local
from .models import MusicSource, MusicSourceCreate, MusicSourceUpdate, now_iso
from .online import resolve_online, validate_target
from .playlist import parse_playlist
from .stream import get_stream_urls

log = get_logger(__name__)


def _load_raw(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sources": []}
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        log.warning("sources.json read failed: %s", exc)
        return {"sources": []}
    if not text:
        # 空文件视作初始状态
        return {"sources": []}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # 备份损坏文件
        backup = path.with_suffix(path.suffix + ".corrupt")
        try:
            path.replace(backup)
            log.error("sources.json corrupt, backup to %s: %s", backup, exc)
        except Exception:  # noqa: BLE001
            pass
        return {"sources": []}
    if "sources" not in data or not isinstance(data["sources"], list):
        return {"sources": []}
    return data


def _save_raw(path: Path, data: dict[str, Any]) -> None:
    with file_lock(path.with_suffix(".lock")):
        atomic_write_json(path, data)


class SourceManager:
    """音乐源管理器.

    异步 API 内部用 to_thread 包装同步 I/O, 避免阻塞事件循环.
    使用 in-process asyncio.Lock 防止同进程内并发读写竞态,
    跨进程安全由 file_lock 保障.
    """

    def __init__(self, sources_file: Path) -> None:
        self.file = sources_file
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        if not self.file.exists():
            _save_raw(self.file, {"sources": []})

    # ──────── 同步 IO 包装 ────────

    async def _io(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _serialized(self, fn, *args, **kwargs):
        """带进程内互斥的执行."""
        async with self._lock:
            return await self._io(fn, *args, **kwargs)

    # ──────── CRUD ────────

    async def list(self) -> list[dict]:
        def _do() -> list[dict]:
            data = _load_raw(self.file)
            return [s for s in data["sources"]]

        async with self._lock:
            return await self._io(_do)

    async def get(self, source_id: str) -> dict | None:
        def _do() -> dict | None:
            data = _load_raw(self.file)
            for s in data["sources"]:
                if s.get("id") == source_id:
                    return s
            return None

        async with self._lock:
            return await self._io(_do)

    async def create(self, payload: MusicSourceCreate) -> dict:
        def _do() -> dict:
            data = _load_raw(self.file)
            for s in data["sources"]:
                if s.get("name") == payload.name:
                    raise ValueError(f"name exists: {payload.name}")
            new = MusicSource(
                id=new_id(8),
                name=payload.name,
                type=payload.type,
                target=payload.target,
                keywords=payload.keywords,
                description=payload.description,
                enabled=payload.enabled,
                recursive=payload.recursive,
                format_filter=payload.format_filter or ["mp3", "wav", "flac", "m4a", "ogg"],
                shuffle=payload.shuffle,
                created_at=now_iso(),
                updated_at=now_iso(),
            )
            d = new.to_dict()
            data["sources"].append(d)
            _save_raw(self.file, data)
            return d

        async with self._lock:
            return await self._io(_do)

    async def update(self, source_id: str, payload: MusicSourceUpdate) -> dict | None:
        def _do() -> dict | None:
            data = _load_raw(self.file)
            for s in data["sources"]:
                if s.get("id") == source_id:
                    for k, v in payload.model_dump(exclude_unset=True).items():
                        if v is not None:
                            s[k] = v
                    s["updated_at"] = now_iso()
                    # 校验
                    MusicSource(**s)
                    _save_raw(self.file, data)
                    return s
            return None

        async with self._lock:
            return await self._io(_do)

    async def delete(self, source_id: str) -> bool:
        def _do() -> bool:
            data = _load_raw(self.file)
            before = len(data["sources"])
            data["sources"] = [s for s in data["sources"] if s.get("id") != source_id]
            if len(data["sources"]) == before:
                return False
            _save_raw(self.file, data)
            return True

        async with self._lock:
            return await self._io(_do)

    # ──────── 解析为可播放 URL 列表 ────────

    async def resolve(self, source_id: str) -> tuple[dict, list[str]]:
        """返回 (源, urls)."""
        src = await self.get(source_id)
        if not src:
            raise KeyError(source_id)
        if not src.get("enabled", True):
            raise ValueError("source disabled")
        stype = src["type"]
        if stype == SourceType.LOCAL.value:
            urls = await self._io(
                scan_local,
                src["target"],
                src.get("recursive", True),
                src.get("format_filter"),
            )
        elif stype == SourceType.STREAM.value:
            urls = get_stream_urls(src["target"])
        elif stype == SourceType.PLAYLIST.value:
            urls = await self._io(parse_playlist, src["target"])
        elif stype == SourceType.ONLINE.value:
            # 在线 API 源 (GD 音乐台) – 同步 HTTP 调用, 包到 to_thread
            urls = await self._io(resolve_online, src["target"])
        else:
            raise ValueError(f"unknown source type: {stype}")
        if not urls:
            raise ValueError(f"no playable urls for source {source_id}")
        return src, urls

    async def rescan(self, source_id: str) -> int:
        src = await self.get(source_id)
        if not src or src["type"] != SourceType.LOCAL.value:
            return 0
        urls = await self._io(
            scan_local,
            src["target"],
            src.get("recursive", True),
            src.get("format_filter"),
        )
        return len(urls)
