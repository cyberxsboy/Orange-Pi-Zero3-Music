"""文件锁：跨平台（Windows 与 Linux）.

- Linux: 优先使用 fcntl.flock（POSIX 建议锁）
- Windows: 退化为 msvcrt 锁文件
"""
from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path
from typing import Iterator

try:
    import fcntl  # type: ignore[import-not-found]

    _HAS_FCNTL = True
except ImportError:  # Windows
    _HAS_FCNTL = False


@contextlib.contextmanager
def file_lock(
    lock_path: Path | str,
    timeout: float = 5.0,
    poll: float = 0.05,
) -> Iterator[None]:
    """获取文件锁（阻塞 + 超时）.

    Args:
        lock_path: 锁文件路径（建议与被保护文件同目录）
        timeout: 等待超时秒数
        poll: 轮询间隔

    Raises:
        TimeoutError: 等待超时
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    # Windows msvcrt.locking 要求文件至少 1 字节，否则抛 "Invalid argument"
    if not _HAS_FCNTL:
        try:
            size = os.fstat(fd).st_size
            if size == 0:
                os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
        except OSError:
            pass
    try:
        deadline = time.time() + timeout
        while True:
            try:
                if _HAS_FCNTL:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    _windows_lock(fd, blocking=False)
                break
            except (BlockingIOError, OSError):
                if time.time() >= deadline:
                    raise TimeoutError(f"file lock timeout: {lock_path}") from None
                time.sleep(poll)
        yield
    finally:
        try:
            if _HAS_FCNTL:
                fcntl.flock(fd, fcntl.LOCK_UN)
            else:
                _windows_unlock(fd)
        finally:
            os.close(fd)


def _windows_lock(fd: int, blocking: bool = True) -> None:
    """Windows 平台基于 msvcrt 的锁文件."""
    import msvcrt  # type: ignore[import-not-found]

    # 先 seek 到开头
    os.lseek(fd, 0, os.SEEK_SET)
    mode = msvcrt.LK_NBLCK if not blocking else msvcrt.LK_LOCK
    while True:
        try:
            msvcrt.locking(fd, mode, 1)
            return
        except OSError as exc:
            if not blocking:
                raise
            if exc.errno not in (13, 33):  # 13: locked, 33: lock violation
                raise
            time.sleep(0.05)


def _windows_unlock(fd: int) -> None:
    import msvcrt  # type: ignore[import-not-found]

    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def atomic_write_json(path: Path | str, data: dict | list) -> None:
    """原子写入 JSON：先写 .tmp，再 os.replace."""
    import json

    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp.write_text(payload, encoding="utf-8")
    try:
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
