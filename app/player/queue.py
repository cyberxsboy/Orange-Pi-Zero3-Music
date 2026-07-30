"""播放队列."""
from __future__ import annotations

import asyncio
import random
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Iterator


@dataclass
class QueueItem:
    url: str
    title: str = ""
    source_id: str | None = None
    source_name: str | None = None


class PlayQueue:
    """FIFO 队列 + 上一首历史."""

    def __init__(self, maxlen: int = 10000) -> None:
        self._q: Deque[QueueItem] = deque(maxlen=maxlen)
        self._history: Deque[QueueItem] = deque(maxlen=50)
        self._lock = asyncio.Lock()

    async def push(self, item: QueueItem) -> None:
        async with self._lock:
            self._q.append(item)

    async def push_many(self, items: list[QueueItem], shuffle: bool = False) -> None:
        async with self._lock:
            if shuffle:
                random.shuffle(items)
            self._q.extend(items)

    async def pop(self) -> QueueItem | None:
        async with self._lock:
            if not self._q:
                return None
            item = self._q.popleft()
            self._history.append(item)
            return item

    async def clear(self) -> None:
        async with self._lock:
            self._q.clear()

    def __len__(self) -> int:
        return len(self._q)

    async def history_last(self) -> QueueItem | None:
        async with self._lock:
            if len(self._history) < 2:
                return None
            return self._history[-2]

    def snapshot(self) -> list[dict]:
        return [
            {"url": i.url, "title": i.title, "source_id": i.source_id, "source_name": i.source_name}
            for i in self._q
        ]
