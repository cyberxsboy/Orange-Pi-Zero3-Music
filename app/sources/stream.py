"""网络流 URL 处理.

支持:
- HTTP/HTTPS mp3/ogg/aac
- ICY 电台流（mpg123 自动处理）

不做实际下载，只做 URL 规范化与可达性检查.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from ..logger import get_logger

log = get_logger(__name__)

_STREAM_RE = re.compile(r"^https?://", re.IGNORECASE)


def validate_url(url: str) -> bool:
    return bool(_STREAM_RE.match(url.strip()))


def normalize_url(url: str) -> str:
    return url.strip()


def get_stream_urls(target: str) -> list[str]:
    """stream 类型直接返回 [target]."""
    if not validate_url(target):
        log.error("invalid stream url: %s", target)
        return []
    return [normalize_url(target)]


def is_icy(url: str) -> bool:
    """简单判断是否为 ICY 电台流（基于扩展名 / 路径）."""
    p = urlparse(url.lower())
    if p.path.endswith((".m3u", ".pls")):
        return False
    if p.path.endswith((".mp3", ".aac", ".ogg")):
        return True
    return False
