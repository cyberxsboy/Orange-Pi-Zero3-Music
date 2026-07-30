"""播放器后端抽象接口."""
from __future__ import annotations

import abc
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator


@dataclass
class TrackInfo:
    """当前曲目信息."""

    url: str
    title: str = ""
    artist: str = ""
    duration_s: float = 0.0
    source_id: str | None = None
    source_name: str | None = None


class PlayerBackend(abc.ABC):
    """播放器后端抽象接口.

    实现方应通过 `events()` 异步生成器上报状态/曲目变更事件.
    """

    @abc.abstractmethod
    async def start(self) -> None:
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        ...

    @abc.abstractmethod
    async def play(self, url: str | Path) -> None:
        """开始播放指定 url. 替换当前曲目."""

    @abc.abstractmethod
    async def pause(self) -> None:
        ...

    @abc.abstractmethod
    async def resume(self) -> None:
        ...

    @abc.abstractmethod
    async def next(self) -> None:
        ...

    @abc.abstractmethod
    async def prev(self) -> None:
        ...

    @abc.abstractmethod
    async def set_volume(self, value: int) -> None:
        """value: 0-100."""

    @abc.abstractmethod
    async def get_volume(self) -> int:
        ...

    @abc.abstractmethod
    async def get_state(self) -> str:
        """返回 PlayerState 值."""

    @abc.abstractmethod
    async def get_current(self) -> TrackInfo | None:
        ...

    @abc.abstractmethod
    def events(self) -> AsyncIterator[dict]:
        """状态变更事件流.

        事件格式::
            {"type": "state", "value": "playing"}
            {"type": "track", "value": {"url": ..., "title": ...}}
        """
        yield {}  # for type checker
        return
        yield  # unreachable  # noqa: F841

    def __aiter__(self) -> AsyncIterator[dict]:
        return self.events()
