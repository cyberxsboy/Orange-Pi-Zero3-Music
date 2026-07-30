"""热加载文件变更监听（基于 watchfiles，1GB 模式默认关闭 inotify）."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable

from ..logger import get_logger

log = get_logger(__name__)


class HotReloader:
    """基于 watchfiles 的文件变更监听.

    用法::

        reload = HotReloader(cfg.paths.sources_file)
        reload.on_change = lambda: manager.reload()
        await reload.start()
    """

    def __init__(self, target: Path | str, debounce_ms: int = 300) -> None:
        self.target = Path(target)
        self.debounce_ms = debounce_ms
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.on_change: Callable[[], Awaitable[None]] | None = None

    async def start(self) -> None:
        try:
            from watchfiles import awatch
        except ImportError:
            log.warning("watchfiles not installed; hot reload disabled")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._watch(awatch), name="hot-reloader")

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _watch(self, awatch) -> None:
        if not self.target.exists():
            self.target.parent.mkdir(parents=True, exist_ok=True)
            self.target.touch()
        log.info("hot reload watching: %s", self.target)
        try:
            async for _changes in awatch(
                self.target.parent,
                stop_event=self._stop,
                step=self.debounce_ms,
                recursive=False,
            ):
                if self._stop.is_set():
                    break
                if self.on_change:
                    try:
                        await self.on_change()
                    except Exception as exc:  # noqa: BLE001
                        log.exception("hot reload handler failed: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("hot reload watch failed: %s", exc)
