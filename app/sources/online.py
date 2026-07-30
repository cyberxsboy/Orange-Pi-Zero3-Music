"""在线音乐源解析（基于 GD 音乐台免费公共 API）.

参考自开源项目 AlgerMusicPlayer (src/renderer/api/gdmusic.ts).
AlgerMusicPlayer 内置音源:
- UnblockMusic   (本地部署, 需 Node 服务)
- GD 音乐台      (免认证公共 API)  ← 本项目采用
- 落雪音乐       (需用户自配脚本)
- 自定义 API     (需用户自配)

GD 音乐台 API 端点 (https://music-api.gdstudio.xyz/api.php):
  ?types=search&source={platform}&name={kw}&count=N
      → [{id, name, artist, source, ...}]
  ?types=url&source={platform}&id={id}&br={128|192|320|999}
      → {url, br, size, ...}
  ?types=playlist&source={platform}&id={playlist_id}
      → [{id, name, artist, ...}, ...]
  ?types=pic&source={platform}&id={id}&size=300
      → {url}

支持的 platform: netease / joox / tidal

本模块的 target 字符串格式:
    https://music-api.gdstudio.xyz/api.php?types=playlist&source=netease&id=3778678
即: 一条完整的 GD 音乐台 API URL, types 可以是 playlist / search.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from ..logger import get_logger

log = get_logger(__name__)

# GD 音乐台 API 基础地址
GD_BASE = "https://music-api.gdstudio.xyz/api.php"

# 单源最大曲目数 (避免一次取太多导致 API 慢 / 超时)
DEFAULT_LIMIT = 25

# 每次 HTTP 请求超时
HTTP_TIMEOUT = 8  # 秒

# 音质 (kbps) - 320 为高品质 MP3, Orange Pi Zero3 1GB 内存友好
DEFAULT_BR = "320"

_VALID_PLATFORMS = {"netease", "joox", "tidal"}


# ──────────────────────────── 内部工具 ────────────────────────────


def _http_get_json(url: str, timeout: int = HTTP_TIMEOUT) -> Any:
    """GET 解析 JSON. 失败抛 RuntimeError."""
    req = urllib.request.Request(url, headers={"User-Agent": "opi-music-player/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    try:
        return json.loads(data.decode("utf-8", errors="ignore"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"invalid json from {url}: {exc}") from exc


def _normalize_target(target: str) -> tuple[str, dict[str, str]]:
    """将 target 拆解为 (api_types, params).

    支持两种输入:
    1) 完整 URL:  https://music-api.gdstudio.xyz/api.php?types=playlist&source=netease&id=3778678
    2) 简写协议:  gdmusic://playlist?source=netease&id=3778678

    返回 (types, params) 供内部使用.
    """
    if not target or not target.strip():
        raise ValueError("empty online source target")

    raw = target.strip()
    if raw.startswith("gdmusic://"):
        parsed = urllib.parse.urlparse(raw)
        # 协议: gdmusic://{types}?{query}
        types = parsed.netloc or parsed.path.lstrip("/")
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    else:
        parsed = urllib.parse.urlparse(raw)
        if not parsed.netloc:
            raise ValueError(f"invalid online source target: {target}")
        qs_list = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        types_vals = qs_list.get("types", [])
        if not types_vals:
            raise ValueError(f"missing 'types' param in: {target}")
        types = types_vals[0]
        qs_list.pop("types", None)
        qs = qs_list

    if not types:
        raise ValueError(f"missing types in: {target}")

    params: dict[str, str] = {k: v[0] for k, v in qs.items() if v}
    return types, params


def _build_url(types: str, params: dict[str, str]) -> str:
    q = urllib.parse.urlencode({**params, "types": types})
    return f"{GD_BASE}?{q}"


def _validate_platform(params: dict[str, str]) -> str:
    src = params.get("source", "netease")
    if src not in _VALID_PLATFORMS:
        raise ValueError(
            f"unsupported platform: {src!r}, valid: {sorted(_VALID_PLATFORMS)}"
        )
    return src


# ──────────────────────────── 主入口 ────────────────────────────


def _fetch_list(target: str, limit: int) -> tuple[str, list[dict[str, Any]]]:
    """根据 target 取歌单 / 搜索结果, 返回 (platform, items)."""
    types, params = _normalize_target(target)
    platform = _validate_platform(params)

    if types == "playlist":
        if "id" not in params:
            raise ValueError("playlist target requires id=<playlist_id>")
        url = _build_url("playlist", params)
    elif types == "search":
        if "name" not in params:
            raise ValueError("search target requires name=<keyword>")
        params.setdefault("count", str(limit))
        params.setdefault("pages", "1")
        url = _build_url("search", params)
    else:
        raise ValueError(
            f"unsupported types for online source: {types!r} (use playlist/search)"
        )

    data = _http_get_json(url, timeout=HTTP_TIMEOUT)
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected payload from {url}: not a list")

    items: list[dict[str, Any]] = []
    for entry in data:
        if isinstance(entry, dict) and entry.get("id") is not None:
            # 统一字段: id / name / artist
            artist = entry.get("artist")
            if isinstance(artist, list):
                artist = "、".join(
                    [a.get("name", "") if isinstance(a, dict) else str(a) for a in artist]
                )
            elif not isinstance(artist, str):
                artist = ""
            items.append(
                {
                    "id": entry.get("id"),
                    "name": entry.get("name", ""),
                    "artist": artist or "",
                    "source": entry.get("source") or platform,
                }
            )
    return platform, items


def _fetch_song_urls(
    items: list[dict[str, Any]],
    platform: str,
    br: str = DEFAULT_BR,
    limit: int = DEFAULT_LIMIT,
) -> list[str]:
    """对 [{id, name, artist}, ...] 逐个取播放 URL, 返回有效 URL 列表."""
    urls: list[str] = []
    for item in items[:limit]:
        song_id = item.get("id")
        if song_id is None:
            continue
        url = _build_url("url", {"source": platform, "id": str(song_id), "br": br})
        try:
            data = _http_get_json(url, timeout=HTTP_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            log.warning("resolve song url failed: id=%s err=%s", song_id, exc)
            continue
        if not isinstance(data, dict):
            continue
        u = data.get("url")
        if u and isinstance(u, str) and u.startswith(("http://", "https://")):
            urls.append(u)
    return urls


def resolve_online(
    target: str,
    limit: int = DEFAULT_LIMIT,
    br: str = DEFAULT_BR,
) -> list[str]:
    """解析 online 源 target, 返回可播放 URL 列表.

    Args:
        target: GD 音乐台 API URL (types=playlist 或 types=search).
        limit:  最多取多少首.
        br:     音质 (kbps), 默认 320.

    Returns:
        http(s) mp3 URL 列表. 出错返回空列表.
    """
    try:
        platform, items = _fetch_list(target, limit=limit)
    except Exception as exc:  # noqa: BLE001
        log.error("online source list failed: %s", exc)
        return []
    if not items:
        log.warning("online source empty: %s", target)
        return []

    log.info("online source %s: got %d items", target, len(items))
    urls = _fetch_song_urls(items, platform, br=br, limit=limit)
    if not urls:
        log.error("online source: no resolvable urls (target=%s)", target)
    else:
        log.info("online source: resolved %d/%d urls", len(urls), len(items))
    return urls


def validate_target(target: str) -> bool:
    """轻量校验 target 是否像合法的 GD 音乐台 API URL."""
    try:
        types, params = _normalize_target(target)
    except ValueError:
        return False
    if types not in ("playlist", "search"):
        return False
    if "source" in params and params["source"] not in _VALID_PLATFORMS:
        return False
    if types == "playlist" and "id" not in params:
        return False
    if types == "search" and "name" not in params:
        return False
    return True
