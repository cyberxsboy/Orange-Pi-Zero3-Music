"""指令匹配器测试."""
import sys
from pathlib import Path

# 把项目根加入 sys.path（避免 import 失败）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.voice.matcher import CommandMatcher  # noqa: E402

SOURCES = [
    {"id": "AAAA0001", "name": "流行轻音乐", "type": "local",
     "keywords": ["流行", "轻音乐", "pop"], "enabled": True, "shuffle": True},
    {"id": "BBBB0002", "name": "HitFM 电台", "type": "stream",
     "keywords": ["电台", "hitfm"], "enabled": True},
    {"id": "CCCC0003", "name": "古典音乐", "type": "local",
     "keywords": ["古典", "classical"], "enabled": True},
    {"id": "DDDD0004", "name": "白噪音", "type": "stream",
     "keywords": ["白噪音", "睡眠"], "enabled": False},  # 禁用
]


def test_play_by_keyword():
    m = CommandMatcher(SOURCES, use_pinyin=False)
    cmd = m.match("播放流行")
    assert cmd and cmd.action == "play" and cmd.target_id == "AAAA0001", f"got {cmd}"
    cmd = m.match("来一首轻音乐")
    assert cmd and cmd.action == "play" and cmd.target_id == "AAAA0001"
    cmd = m.match("想听古典音乐")
    assert cmd and cmd.action == "play" and cmd.target_id == "CCCC0003"


def test_play_disabled_ignored():
    m = CommandMatcher(SOURCES, use_pinyin=False)
    cmd = m.match("播放白噪音")
    # 禁用源不应被选中；无其它源匹配 -> None
    assert cmd is None or cmd.target_id != "DDDD0004"


def test_system_intents():
    m = CommandMatcher(SOURCES, use_pinyin=False)
    assert m.match("暂停").action == "pause"
    assert m.match("继续").action == "resume"
    assert m.match("停止").action == "stop"
    assert m.match("下一首").action == "next"
    assert m.match("上一首").action == "prev"
    assert m.match("不听了").action == "stop"


def test_volume():
    m = CommandMatcher(SOURCES, use_pinyin=False)
    cmd = m.match("音量调到 60")
    assert cmd and cmd.action == "volume" and cmd.payload["value"] == 60
    cmd = m.match("音量 80")
    assert cmd and cmd.action == "volume" and cmd.payload["value"] == 80
    cmd = m.match("音量调到 200")  # clamp
    assert cmd and cmd.action == "volume" and cmd.payload["value"] == 100


def test_pinyin_fallback():
    try:
        import pypinyin  # noqa: F401
    except ImportError:
        print("    [skip] pypinyin not installed")
        return
    m = CommandMatcher(SOURCES, use_pinyin=True)
    # 即使中文文字相似但字面不命中，拼音兜底应能匹配
    cmd = m.match("播放 liuxing")
    # "liuxing" 是 "流行" 的拼音
    assert cmd is not None
    assert cmd.action == "play"
    assert cmd.target_id == "AAAA0001"


def test_empty_text():
    m = CommandMatcher(SOURCES)
    assert m.match("") is None
    assert m.match("   ") is None


def test_unknown_returns_none_or_unknown():
    m = CommandMatcher(SOURCES, use_pinyin=False)
    # 不包含任何触发词或关键字 -> None
    cmd = m.match("今天天气真好")
    assert cmd is None
    # 含播放但无匹配 -> unknown
    cmd = m.match("播放广告")
    assert cmd is None or cmd.action == "unknown"


def test_no_sources():
    m = CommandMatcher([])
    assert m.match("播放流行") is None


if __name__ == "__main__":
    # 简单 runner
    import inspect
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
