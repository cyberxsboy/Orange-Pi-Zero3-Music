"""麦克风采集：sounddevice InputStream + 线程安全 ring buffer.

输出: 16kHz/mono/int16 PCM 帧.
"""
from __future__ import annotations

import collections
import threading
import time
from typing import Callable

from ..logger import get_logger

log = get_logger(__name__)


class AudioCapture:
    """后台线程采集麦克风，提供同步读取接口."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        blocksize: int = 4000,
        device: str | int | None = None,
        ring_seconds: float = 8.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize
        self.device = device
        self._ring_capacity = int(sample_rate * ring_seconds)
        self._ring: collections.deque[bytes] = collections.deque(maxlen=self._ring_capacity)
        self._lock = threading.Lock()
        self._stream = None
        self._running = False
        self._on_error: Callable[[Exception], None] | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    def set_error_handler(self, handler: Callable[[Exception], None]) -> None:
        self._on_error = handler

    def start(self) -> None:
        if self._running:
            return
        try:
            import sounddevice as sd
        except OSError as exc:
            log.error("PortAudio not available: %s", exc)
            raise

        def _callback(indata, frames, time_info, status):  # noqa: ARG001
            if status:
                log.debug("capture status: %s", status)
            with self._lock:
                self._ring.append(bytes(indata))

        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=self.blocksize,
                device=self.device,
                callback=_callback,
            )
            self._stream.start()
            self._running = True
            log.info(
                "audio capture started (rate=%d, ch=%d, blocksize=%d, device=%s)",
                self.sample_rate, self.channels, self.blocksize, self.device,
            )
        except Exception as exc:
            log.error("failed to start audio capture: %s", exc)
            if self._on_error:
                self._on_error(exc)
            raise

    def stop(self) -> None:
        if not self._running:
            return
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("capture stop error: %s", exc)
        finally:
            self._stream = None
            self._running = False
            log.info("audio capture stopped")

    def read(self, n_bytes: int, timeout: float = 2.0) -> bytes | None:
        """从 ring buffer 读取最多 n_bytes 数据. 超时返回 None.

        若不足 n_bytes，会等待直到累积或超时.
        """
        deadline = time.time() + timeout
        while True:
            with self._lock:
                # 把所有片段拼起来
                buf = b"".join(self._ring)
                if len(buf) >= n_bytes:
                    # 从 ring 里移除前 n_bytes
                    self._clear_until(n_bytes)
                    return buf[:n_bytes]
                remaining_n = n_bytes - len(buf)
            if time.time() >= deadline:
                # 超时，返回已有数据
                with self._lock:
                    buf = b"".join(self._ring)
                    self._clear_until(len(buf))
                    return buf if buf else None
            time.sleep(0.02)

    def drain(self) -> None:
        """清空 ring buffer."""
        with self._lock:
            self._ring.clear()

    def _clear_until(self, n: int) -> None:
        # 消耗 ring 头部 n 字节
        consumed = 0
        while self._ring and consumed < n:
            seg = self._ring[0]
            if consumed + len(seg) <= n:
                consumed += len(seg)
                self._ring.popleft()
            else:
                rest = n - consumed
                self._ring[0] = seg[rest:]
                consumed = n

    def __enter__(self) -> "AudioCapture":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
