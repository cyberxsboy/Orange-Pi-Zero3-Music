"""音乐源 CRUD 测试."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.sources.manager import SourceManager  # noqa: E402
from app.sources.models import MusicSourceCreate, MusicSourceUpdate  # noqa: E402


def _tmp() -> Path:
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8")
    f.write('{"sources": []}')
    f.close()
    return Path(f.name)


async def test_create_list_get():
    f = _tmp()
    mgr = SourceManager(f)
    payload = MusicSourceCreate(
        name="测试源",
        type="local",
        target="/tmp",
        keywords=["测试", "t1"],
    )
    src = await mgr.create(payload)
    assert src["id"] and len(src["id"]) >= 8
    items = await mgr.list()
    assert len(items) == 1
    one = await mgr.get(src["id"])
    assert one and one["name"] == "测试源"


async def test_update_and_delete():
    f = _tmp()
    mgr = SourceManager(f)
    src = await mgr.create(MusicSourceCreate(
        name="upd", type="stream", target="http://x/y.mp3", keywords=["k"],
    ))
    upd = await mgr.update(src["id"], MusicSourceUpdate(description="new desc", enabled=False))
    assert upd["description"] == "new desc"
    assert upd["enabled"] is False
    ok = await mgr.delete(src["id"])
    assert ok
    assert await mgr.get(src["id"]) is None


async def test_duplicate_name():
    f = _tmp()
    mgr = SourceManager(f)
    await mgr.create(MusicSourceCreate(name="dup", type="stream", target="http://x", keywords=["k"]))
    try:
        await mgr.create(MusicSourceCreate(name="dup", type="stream", target="http://x", keywords=["k"]))
        raise AssertionError("should raise")
    except ValueError:
        pass


async def test_resolve_stream():
    f = _tmp()
    mgr = SourceManager(f)
    src = await mgr.create(MusicSourceCreate(
        name="s", type="stream", target="https://example.com/stream.mp3", keywords=["k"],
    ))
    s, urls = await mgr.resolve(src["id"])
    assert urls == ["https://example.com/stream.mp3"]


async def test_resolve_disabled():
    f = _tmp()
    mgr = SourceManager(f)
    src = await mgr.create(MusicSourceCreate(
        name="dis", type="stream", target="https://x/y.mp3", keywords=["k"], enabled=False,
    ))
    try:
        await mgr.resolve(src["id"])
        raise AssertionError("should raise")
    except ValueError:
        pass


async def test_concurrent_writes():
    f = _tmp()
    mgr = SourceManager(f)

    async def add(i: int):
        await mgr.create(MusicSourceCreate(
            name=f"src{i}", type="stream", target=f"http://x/{i}", keywords=[f"k{i}"],
        ))

    await asyncio.gather(*(add(i) for i in range(10)))
    items = await mgr.list()
    assert len(items) == 10


async def test_corrupt_file_recovery():
    f = _tmp()
    f.write_text("not json", encoding="utf-8")
    mgr = SourceManager(f)
    items = await mgr.list()
    assert items == []
    # 备份文件存在（_load_raw 把损坏文件 move 成 .corrupt）
    candidates = [f.with_suffix(f.suffix + ".corrupt"), f.with_name(f.name + ".corrupt")]
    assert any(p.exists() for p in candidates), "no .corrupt backup"


def main():
    funcs = [f for n, f in globals().items() if n.startswith("test_") and callable(f)]
    passed, failed = 0, 0
    for fn in funcs:
        try:
            asyncio.run(fn())
            print(f"  ✓ {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {fn.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
