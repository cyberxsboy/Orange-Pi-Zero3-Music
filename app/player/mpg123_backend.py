"""mpg123 后端：-R 远程控制协议.

支持 mp3 / 网络电台流 / 一些 ogg.
"""
from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import AsyncIterator

from ..logger import get_logger
from .base import PlayerBackend, TrackInfo

log = get_logger(__name__)


# mpg123 -R 输出协议（关键行）
# @P 1   - 暂停
# @P 0   - 播放
# @F 44100 2 ...  - 帧信息
# @I 0 - 0..9  曲目索引
# @S PATH  - 当前流路径
# @E <err> - 错误

class Mpg123Backend(PlayerBackend):
    def __init__(
        self,
        device: str | None = None,
        volume: int = 80,
        output_buffer: int = 4096,
    ) -> None:
        self.device = device
        self._volume = max(0, min(100, volume))
        self._buffer = output_buffer
        self._proc: asyncio.subprocess.Process | None = None
        self._state: str = "idle"
        self._current: TrackInfo | None = None
        self._event_q: asyncio.Queue[dict] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return shutil.which("mpg123") is not None

    # ───────── lifecycle ─────────

    async def start(self) -> None:
        if not self.available:
            raise RuntimeError("mpg123 not installed")
        await self._spawn()

    async def stop(self) -> None:
        await self._terminate()

    async def _spawn(self) -> None:
        cmd = ["mpg123", "-R", f"-{self._buffer}"]
        if self.device:
            cmd += ["-a", self.device]
        # 初始音量
        # mpg123 远程控制协议里 LOAD <file> 即可

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            log.error("mpg123 not found: %s", exc)
            raise
        self._state = "idle"
        self._reader_task = asyncio.create_task(self._reader_loop(), name="mpg123-reader")

    async def _terminate(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.stdin.write(b"QUIT\n")
                await self._proc.stdin.drain()
            except Exception:  # noqa: BLE001
                pass
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self._proc.kill()
        self._proc = None

    # ───────── reader ─────────

    async def _reader_loop(self) -> None:
        assert self._proc and self._proc.stdout
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="ignore").strip()
                await self._handle_line(text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("mpg123 reader error: %s", exc)

    async def _handle_line(self, line: str) -> None:
        if line.startswith("@P "):
            # @P 1 (paused) or @P 0 (playing)
            v = line[3:].strip()
            self._state = "paused" if v == "1" else "playing"
            await self._event_q.put({"type": "state", "value": self._state})
        elif line.startswith("@S "):
            path = line[3:].strip()
            if path:
                if not self._current or self._current.url != path:
                    self._current = TrackInfo(url=path, title=Path(path).stem if path else "")
                    await self._event_q.put({"type": "track", "value": self._current})
        elif line.startswith("@E"):
            log.warning("mpg123 error: %s", line)
            await self._event_q.put({"type": "error", "value": line})
        # 忽略其它行

    # ───────── command ─────────

    async def _send(self, cmd: str) -> None:
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("mpg123 not running")
        try:
            self._proc.stdin.write((cmd + "\n").encode())
            await self._proc.stdin.drain()
        except Exception as exc:  # noqa: BLE001
            log.error("mpg123 send failed: %s", exc)
            raise

    async def play(self, url: str | Path) -> None:
        url = str(url)
        async with self._lock:
            await self._send(f"LOAD {url}")
            self._current = TrackInfo(url=url, title=Path(url).stem if url else "")
            await self._event_q.put({"type": "track", "value": self._current})
            self._state = "playing"
            await self._event_q.put({"type": "state", "value": self._state})

    async def pause(self) -> None:
        async with self._lock:
            await self._send("PAUSE")
            self._state = "paused"
            await self._event_q.put({"type": "state", "value": self._state})

    async def resume(self) -> None:
        async with self._lock:
            # mpg123: PAUSE 是 toggle
            if self._state == "paused":
                await self._send("PAUSE")
                self._state = "playing"
                await self._event_q.put({"type": "state", "value": self._state})

    async def next(self) -> None:
        async with self._lock:
            # mpg123 不直接支持 next, 通过跳到下一首由 controller 负责
            await self._send("SKIP +1")

    async def prev(self) -> None:
        async with self._lock:
            await self._send("SKIP -1")

    async def set_volume(self, value: int) -> None:
        self._volume = max(0, min(100, int(value)))
        # mpg123 不支持软音量；用 amixer 控制 USB 声卡
        if shutil.which("amixer"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "amixer", "-q", "set", "Speaker", f"{self._volume}%",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            except Exception as exc:  # noqa: BLE001
                log.warning("amixer failed: %s", exc)

    async def get_volume(self) -> int:
        return self._volume

    async def get_state(self) -> str:
        return self._state

    async def get_current(self) -> TrackInfo | None:
        return self._current

    async def events(self) -> AsyncIterator[dict]:
        while True:
            ev = await self._event_q.get()
            yield ev
