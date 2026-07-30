"""VLC 后端（fallback，CPU 略高但格式全）.

使用 cvlc --intf rc + Lua RC 接口.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import AsyncIterator

from ..logger import get_logger
from .base import PlayerBackend, TrackInfo

log = get_logger(__name__)


class VLCBackend(PlayerBackend):
    def __init__(self, rc_host: str = "127.0.0.1", rc_port: int = 4212) -> None:
        self.rc_host = rc_host
        self.rc_port = rc_port
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._state: str = "idle"
        self._current: TrackInfo | None = None
        self._event_q: asyncio.Queue[dict] = asyncio.Queue()

    @property
    def available(self) -> bool:
        return shutil.which("vlc") is not None

    async def start(self) -> None:
        if not self.available:
            raise RuntimeError("vlc not installed")
        cmd = [
            "vlc", "-I", "rc",
            "--rc-host", f"{self.rc_host}:{self.rc_port}",
            "--no-video",
            "--quiet",
        ]
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        # 连接 RC
        await asyncio.sleep(0.5)
        for _ in range(10):
            try:
                self._reader, self._writer = await asyncio.open_connection(self.rc_host, self.rc_port)
                break
            except OSError:
                await asyncio.sleep(0.3)
        if not self._writer:
            raise RuntimeError("vlc RC connection failed")
        asyncio.create_task(self._reader_loop(), name="vlc-reader")

    async def stop(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self._proc.kill()

    async def _reader_loop(self) -> None:
        if not self._reader:
            return
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    break
                txt = line.decode(errors="ignore").strip()
                if "playing" in txt.lower() or "paused" in txt.lower():
                    self._state = "playing" if "playing" in txt.lower() else "paused"
                    await self._event_q.put({"type": "state", "value": self._state})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("vlc reader error: %s", exc)

    async def _send(self, cmd: str) -> None:
        if not self._writer:
            return
        try:
            self._writer.write((cmd + "\n").encode())
            await self._writer.drain()
        except Exception as exc:  # noqa: BLE001
            log.warning("vlc send failed: %s", exc)

    async def play(self, url: str | Path) -> None:
        url = str(url)
        await self._send(f"add {url}")
        self._current = TrackInfo(url=url, title=Path(url).stem if url else "")
        self._state = "playing"
        await self._event_q.put({"type": "track", "value": self._current})
        await self._event_q.put({"type": "state", "value": self._state})

    async def pause(self) -> None:
        await self._send("pause")
        self._state = "paused"

    async def resume(self) -> None:
        await self._send("play")
        self._state = "playing"

    async def next(self) -> None:
        await self._send("next")

    async def prev(self) -> None:
        await self._send("prev")

    async def set_volume(self, value: int) -> None:
        v = max(0, min(100, int(value)))
        await self._send(f"volaudio {v * 2.56:.0f}")

    async def get_volume(self) -> int:
        return 0  # TODO 解析 status

    async def get_state(self) -> str:
        return self._state

    async def get_current(self) -> TrackInfo | None:
        return self._current

    async def events(self) -> AsyncIterator[dict]:
        while True:
            ev = await self._event_q.get()
            yield ev
