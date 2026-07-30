"""M3U / PLS 播放列表解析.

支持:
- 本地 m3u / pls 文件
- 远程 http(s) m3u / pls
"""
from __future__ import annotations

import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from ..logger import get_logger

log = get_logger(__name__)


def parse_playlist(target: str) -> list[str]:
    """解析播放列表，返回 url 列表."""
    if target.startswith(("http://", "https://")):
        return _parse_remote(target)
    return _parse_local(Path(target))


def _parse_local(path: Path) -> list[str]:
    if not path.exists():
        log.error("playlist not found: %s", path)
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    return _parse_text(text, base=path.parent.as_uri() + "/")


def _parse_remote(url: str) -> list[str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = resp.read()
        text = data.decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        log.error("fetch playlist failed: %s: %s", url, exc)
        return []
    base = url.rsplit("/", 1)[0] + "/"
    return _parse_text(text, base=base)


def _parse_text(text: str, base: str = "") -> list[str]:
    """M3U / PLS 兼容解析."""
    urls: list[str] = []
    text = text.strip()
    if text.startswith("[playlist]") or "File1=" in text or text.lower().startswith("[playlist]"):
        # PLS
        for line in text.splitlines():
            if "=" in line and line.lower().startswith("file"):
                v = line.split("=", 1)[1].strip()
                if v:
                    urls.append(v)
    else:
        # M3U
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("http://", "https://", "file://")):
                urls.append(line)
            elif base:
                urls.append(base + line)
            else:
                urls.append(line)
    return urls
