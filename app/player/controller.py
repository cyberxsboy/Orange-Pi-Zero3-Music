"""播放器主控：状态机 + 队列 + 后端."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from ..constants import PlayerBackend as BackendEnum, PlayerState
from ..ipc.bridge import EventBus
from ..logger import get_logger
from .base import PlayerBackend, TrackInfo
from .fsm import StateMachine
from .mpg123_backend import Mpg123Backend
from .queue import PlayQueue, QueueItem
from .vlc_backend import VLCBackend

log = get_logger(__name__)


class PlayerController:
    """播放器主控."""

    def __init__(
        self,
        backend_kind: BackendEnum,
        event_bus: EventBus,
        device: str | None = None,
        initial_volume: int = 80,
    ) -> None:
        self.bus = event_bus
        self.fsm = StateMachine()
        self.queue = PlayQueue()
        self.backend: PlayerBackend = self._make_backend(backend_kind, device, initial_volume)
        self._worker_task: asyncio.Task | None = None
        self._events_task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._current_source: tuple[str, str] | None = None  # (id, name)

    def _make_backend(self, kind: BackendEnum, device: str | None, vol: int) -> PlayerBackend:
        if kind == BackendEnum.MPG123:
            return Mpg123Backend(device=device, volume=vol)
        if kind == BackendEnum.VLC:
            return VLCBackend()
        # auto
        mpg = Mpg123Backend(device=device, volume=vol)
        if mpg.available:
            return mpg
        return VLCBackend()

    # ─────── lifecycle ───────

    async def start(self) -> None:
        await self.backend.start()
        self._worker_task = asyncio.create_task(self._playback_worker(), name="player-worker")
        self._events_task = asyncio.create_task(self._event_consumer(), name="player-events")
        log.info("player started (backend=%s)", type(self.backend).__name__)

    async def stop(self) -> None:
        self._stopping.set()
        for t in (self._worker_task, self._events_task):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        await self.backend.stop()
        self.queue.clear()
        self.fsm.reset()
        log.info("player stopped")

    # ─────── control API ───────

    async def play_source(
        self,
        source_id: str,
        source_name: str,
        urls: list[str],
        shuffle: bool = False,
    ) -> int:
        """切换到指定音乐源."""
        if not urls:
            raise ValueError("empty urls")
        items = [QueueItem(url=u, source_id=source_id, source_name=source_name) for u in urls]
        await self.queue.clear()
        await self.queue.push_many(items, shuffle=shuffle)
        self._current_source = (source_id, source_name)
        self.fsm.transition(PlayerState.LOADING)
        await self.bus.emit("source_changed", {"id": source_id, "name": source_name})
        # 立即播第一首
        first = await self.queue.pop()
        if first:
            await self.backend.play(first.url)
            self.fsm.transition(PlayerState.PLAYING)
        return len(items)

    async def play_url(self, url: str, title: str = "") -> None:
        await self.backend.play(url)
        self.fsm.transition(PlayerState.PLAYING)
        if title:
            cur = await self.backend.get_current()
            if cur:
                cur.title = title

    async def resume(self) -> None:
        await self.backend.resume()
        self.fsm.transition(PlayerState.PLAYING)

    async def pause(self) -> None:
        await self.backend.pause()
        self.fsm.transition(PlayerState.PAUSED)

    async def stop(self) -> None:
        self.fsm.transition(PlayerState.STOPPING)
        try:
            # mpg123/vlc 都用 stop 命令
            if hasattr(self.backend, "_send"):
                await self.backend._send("STOP")  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass
        await self.queue.clear()
        self.fsm.transition(PlayerState.IDLE)

    async def next(self) -> None:
        await self.backend.next()

    async def prev(self) -> None:
        last = await self.queue.history_last()
        if last:
            await self.backend.play(last.url)
        else:
            await self.backend.prev()

    async def set_volume(self, value: int) -> None:
        await self.backend.set_volume(value)
        await self.bus.emit("volume_changed", {"value": value})

    # ─────── workers ───────

    async def _playback_worker(self) -> None:
        """监听 backend events，曲目结束时播下一首."""
        try:
            async for ev in self.backend.events():
                if self._stopping.is_set():
                    break
                t = ev.get("type")
                if t == "track":
                    info = ev.get("value")
                    await self.bus.emit("track_changed", info.to_dict() if info else {})
                elif t == "state":
                    val = ev.get("value")
                    await self.bus.emit("player_state", {"state": val})
                elif t == "error":
                    # 跳过当前曲目
                    nxt = await self.queue.pop()
                    if nxt:
                        await self.backend.play(nxt.url)
                    else:
                        self.fsm.transition(PlayerState.IDLE)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("playback worker error: %s", exc)

    async def _event_consumer(self) -> None:
        """占位：未来可在此处理用户按键事件."""
        try:
            while not self._stopping.is_set():
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
