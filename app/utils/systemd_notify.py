"""systemd 通知：Type=notify + Watchdog.

非 Linux 或非 notify 模式下为 no-op.
"""
from __future__ import annotations

import os
import sys

from ..logger import get_logger

log = get_logger(__name__)


def _notify_socket() -> str | None:
    return os.environ.get("NOTIFY_SOCKET")


def is_notify_mode() -> bool:
    return _notify_socket() is not None


def notify_ready() -> None:
    """通知 systemd：服务就绪."""
    if not is_notify_mode():
        return
    _send("READY=1")


def notify_status(status: str) -> None:
    """通知 systemd 状态文本."""
    if not is_notify_mode():
        return
    _send(f"STATUS={status}")


def notify_watchdog() -> None:
    """喂狗."""
    if not is_notify_mode():
        return
    _send("WATCHDOG=1")


def _send(payload: str) -> None:
    if sys.platform != "linux":
        return
    sock = _notify_socket()
    if not sock:
        return
    try:
        import socket

        if sock.startswith("@"):
            sock_path = "\0" + sock[1:]
        else:
            sock_path = sock
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.sendto(payload.encode(), sock_path)
    except Exception as exc:  # noqa: BLE001
        log.debug("sd_notify failed: %s", exc)
