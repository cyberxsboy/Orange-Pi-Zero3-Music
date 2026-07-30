"""本地音乐目录扫描."""
from __future__ import annotations

from pathlib import Path

from ..logger import get_logger

log = get_logger(__name__)

DEFAULT_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aac"}


def scan_local(
    target: str | Path,
    recursive: bool = True,
    format_filter: list[str] | None = None,
) -> list[str]:
    """扫描本地目录，返回可播放文件 URL 列表.

    URL 使用 file:// 协议以便 mpg123 识别.
    """
    target = Path(target)
    if not target.exists():
        log.warning("local target not exist: %s", target)
        return []
    if not target.is_dir():
        # 单一文件
        if target.suffix.lower() in DEFAULT_EXTS:
            return [_to_file_url(target)]
        return []

    exts = DEFAULT_EXTS
    if format_filter:
        exts = {f".{e.lower().lstrip('.')}" for e in format_filter}

    files: list[Path] = []
    if recursive:
        for p in target.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                files.append(p)
    else:
        for p in target.iterdir():
            if p.is_file() and p.suffix.lower() in exts:
                files.append(p)

    files.sort()
    return [_to_file_url(p) for p in files]


def _to_file_url(p: Path) -> str:
    return p.resolve().as_uri()  # file:///...
