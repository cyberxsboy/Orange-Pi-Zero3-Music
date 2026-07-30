"""内部 IPC：asyncio 事件总线."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable

from ..logger import get_logger

log = get_logger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    """简单的 pub/sub 事件总线.

    用法::

        bus = EventBus()
        bus.on("wake_detected", handler)
        await bus.emit("wake_detected", {"ts": 123})
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def on(self, event: str, handler: Handler) -> None:
        self._handlers[event].append(handler)

    def off(self, event: str, handler: Handler) -> None:
        if handler in self._handlers.get(event, []):
            self._handlers[event].remove(handler)

    async def emit(self, event: str, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        handlers = list(self._handlers.get(event, []))
        if not handlers:
            return
        results = await asyncio.gather(
            *(h(payload) for h in handlers), return_exceptions=True
        )
        for r in results:
            if isinstance(r, Exception):
                log.warning("event %s handler raised: %s", event, r)
