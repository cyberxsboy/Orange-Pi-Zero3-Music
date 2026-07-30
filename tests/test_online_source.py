"""在线音乐源 (GD 音乐台) 解析测试.

只做纯函数 / 参数解析级别的单元测试, 不发真实 HTTP 请求.
在线解析路径 (resolve_online) 的端到端测试需要 mock urllib.request.urlopen.
"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.sources.online import (  # noqa: E402
    _normalize_target,
    _validate_platform,
    _build_url,
    validate_target,
    resolve_online,
    _http_get_json,
)


# ──────────────────── _normalize_target ────────────────────


def test_normalize_full_url():
    target = "https://music-api.gdstudio.xyz/api.php?types=playlist&source=netease&id=3778678"
    types, params = _normalize_target(target)
    assert types == "playlist"
    assert params["source"] == "netease"
    assert params["id"] == "3778678"


def test_normalize_short_url():
    target = "gdmusic://playlist?source=joox&id=123"
    types, params = _normalize_target(target)
    assert types == "playlist"
    assert params["source"] == "joox"
    assert params["id"] == "123"


def test_normalize_search():
    target = "https://music-api.gdstudio.xyz/api.php?types=search&source=tidal&name=hello"
    types, params = _normalize_target(target)
    assert types == "search"
    assert params["source"] == "tidal"
    assert params["name"] == "hello"


def test_normalize_empty():
    try:
        _normalize_target("")
        raise AssertionError("should raise")
    except ValueError:
        pass


def test_normalize_missing_types():
    try:
        _normalize_target("https://music-api.gdstudio.xyz/api.php?id=1")
        raise AssertionError("should raise")
    except ValueError:
        pass


# ──────────────────── _validate_platform ────────────────────


def test_validate_platform_default():
    assert _validate_platform({}) == "netease"


def test_validate_platform_valid():
    for p in ("netease", "joox", "tidal"):
        assert _validate_platform({"source": p}) == p


def test_validate_platform_invalid():
    try:
        _validate_platform({"source": "youtube"})
        raise AssertionError("should raise")
    except ValueError as e:
        assert "unsupported platform" in str(e)


# ──────────────────── _build_url ────────────────────


def test_build_url_contains_types():
    url = _build_url("playlist", {"source": "netease", "id": "1"})
    assert "types=playlist" in url
    assert "source=netease" in url
    assert "id=1" in url
    assert url.startswith("https://music-api.gdstudio.xyz/api.php?")


# ──────────────────── validate_target ────────────────────


def test_validate_target_ok_playlist():
    assert validate_target(
        "https://music-api.gdstudio.xyz/api.php?types=playlist&source=netease&id=3778678"
    )


def test_validate_target_ok_search():
    assert validate_target(
        "https://music-api.gdstudio.xyz/api.php?types=search&source=netease&name=hello"
    )


def test_validate_target_bad_types():
    assert not validate_target(
        "https://music-api.gdstudio.xyz/api.php?types=url&source=netease&id=1"
    )


def test_validate_target_bad_platform():
    assert not validate_target(
        "https://music-api.gdstudio.xyz/api.php?types=playlist&source=youtube&id=1"
    )


def test_validate_target_missing_id():
    assert not validate_target(
        "https://music-api.gdstudio.xyz/api.php?types=playlist&source=netease"
    )


def test_validate_target_missing_name():
    assert not validate_target(
        "https://music-api.gdstudio.xyz/api.php?types=search&source=netease"
    )


# ──────────────────── resolve_online (mock) ────────────────────


def test_resolve_online_empty_list():
    """API 返回空数组 → resolve 返回 []."""
    with patch("app.sources.online._http_get_json", return_value=[]):
        urls = resolve_online(
            "https://music-api.gdstudio.xyz/api.php?types=playlist&source=netease&id=99999"
        )
    assert urls == []


def test_resolve_online_with_mock():
    """模拟 playlist 返回 3 首, url 接口返回 2 个有效 URL → 结果 2 个."""
    list_payload = [
        {"id": "1", "name": "A", "artist": "X"},
        {"id": "2", "name": "B", "artist": "Y"},
        {"id": "3", "name": "C", "artist": "Z"},
    ]
    # 第 1、3 首返回有效 url, 第 2 首 url 字段为空
    def fake_http(url, timeout=8):
        if "types=playlist" in url:
            return list_payload
        if "id=1" in url:
            return {"url": "https://example.com/a.mp3", "br": 320, "size": 1024}
        if "id=2" in url:
            return {"url": "", "br": 320}
        if "id=3" in url:
            return {"url": "https://example.com/c.mp3", "br": 320, "size": 2048}
        raise RuntimeError("unexpected url: " + url)

    with patch("app.sources.online._http_get_json", side_effect=fake_http):
        urls = resolve_online(
            "https://music-api.gdstudio.xyz/api.php?types=playlist&source=netease&id=3778678",
            limit=10,
        )
    assert urls == ["https://example.com/a.mp3", "https://example.com/c.mp3"]


def test_resolve_online_bad_target():
    """target 解析失败 → 返回 [] 不抛异常."""
    urls = resolve_online("not a url")
    assert urls == []


def test_resolve_online_limit():
    """limit=2 时, 即使 playlist 返回 5 首也只解析前 2 首."""
    list_payload = [
        {"id": str(i), "name": f"S{i}", "artist": "A"} for i in range(5)
    ]

    called_ids: list[str] = []

    def fake_http(url, timeout=8):
        if "types=playlist" in url:
            return list_payload
        # 从 url 中解析 id
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(url).query)
        sid = qs.get("id", ["?"])[0]
        called_ids.append(sid)
        return {"url": f"https://example.com/{sid}.mp3", "br": 320}

    with patch("app.sources.online._http_get_json", side_effect=fake_http):
        urls = resolve_online(
            "https://music-api.gdstudio.xyz/api.php?types=playlist&source=netease&id=1",
            limit=2,
        )
    assert len(urls) == 2
    assert called_ids == ["0", "1"]


if __name__ == "__main__":
    funcs = [f for n, f in globals().items() if n.startswith("test_") and callable(f)]
    passed, failed = 0, 0
    for fn in funcs:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {fn.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
