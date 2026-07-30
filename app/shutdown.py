"""优雅退出信号."""
from __future__ import annotations

import asyncio
import signal

from .logger import get_logger

log = get_logger(__name__)


class Shutdown:
    """统一的优雅退出协调器."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._reason: str = ""

    def request(self, reason: str = "manual") -> None:
        if not self._event.is_set():
            log.info("shutdown requested: %s", reason)
            self._reason = reason
            self._event.set()

    @property
    def reason(self) -> str:
        return self._reason

    async def wait(self) -> str:
        await self._event.wait()
        return self._reason

    def is_set(self) -> bool:
        return self._event.is_set()


_shutdown: Shutdown | None = None


def install_signal_handlers(loop: asyncio.AbstractEventLoop, shutdown: Shutdown) -> None:
    """绑定 SIGTERM/SIGINT 到 shutdown.request."""
    if not hasattr(signal, "SIGTERM"):
        return

    def _handler(sig: int) -> None:
        try:
            name = signal.Signals(sig).name
        except Exception:  # noqa: BLE001
            name = str(sig)
        shutdown.request(f"signal:{name}")

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handler, int(sig))
        except (NotImplementedError, RuntimeError, ValueError):
            # Windows / 子线程
            signal.signal(sig, lambda s, _f: _handler(s))


def get_shutdown() -> Shutdown:
    global _shutdown
    if _shutdown is None:
        _shutdown = Shutdown()
    return _shutdown
