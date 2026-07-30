"""播放器状态机 + 队列单元测试."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.constants import PlayerState  # noqa: E402
from app.player.fsm import StateMachine  # noqa: E402
from app.player.queue import PlayQueue, QueueItem  # noqa: E402


def test_fsm_valid_transitions():
    fsm = StateMachine()
    assert fsm.state == PlayerState.IDLE
    assert fsm.transition(PlayerState.LOADING)
    assert fsm.state == PlayerState.LOADING
    assert fsm.transition(PlayerState.PLAYING)
    assert fsm.transition(PlayerState.PAUSED)
    assert fsm.transition(PlayerState.PLAYING)
    assert fsm.transition(PlayerState.STOPPING)
    assert fsm.transition(PlayerState.IDLE)


def test_fsm_invalid_transitions():
    fsm = StateMachine()
    # IDLE -> PLAYING (跳过 LOADING) 应被拒
    assert not fsm.transition(PlayerState.PLAYING)
    assert fsm.state == PlayerState.IDLE


def test_fsm_listener():
    fsm = StateMachine()
    seen = []
    fsm.on_change(lambda o, n: seen.append((o.value, n.value)))
    fsm.transition(PlayerState.LOADING)
    fsm.transition(PlayerState.PLAYING)
    assert seen == [("idle", "loading"), ("loading", "playing")]


async def test_queue_push_pop():
    q = PlayQueue()
    await q.push(QueueItem(url="a", title="A"))
    await q.push(QueueItem(url="b", title="B"))
    assert len(q) == 2
    item = await q.pop()
    assert item.url == "a"
    assert (await q.pop()).url == "b"
    assert await q.pop() is None


async def test_queue_shuffle():
    q = PlayQueue()
    items = [QueueItem(url=str(i)) for i in range(10)]
    await q.push_many(items, shuffle=True)
    out = []
    while True:
        x = await q.pop()
        if not x:
            break
        out.append(x.url)
    assert sorted(out) == [str(i) for i in range(10)]  # 内容一致


async def test_queue_history_last():
    q = PlayQueue()
    await q.push(QueueItem(url="1"))
    await q.push(QueueItem(url="2"))
    await q.pop()  # 1 -> history
    await q.pop()  # 2 -> history
    last = await q.history_last()
    assert last and last.url == "1"


def main():
    funcs = [f for n, f in globals().items() if (n.startswith("test_fsm") or n.startswith("test_queue")) and callable(f)]
    passed, failed = 0, 0
    for fn in funcs:
        try:
            if asyncio.iscoroutinefunction(fn):
                asyncio.run(fn())
            else:
                fn()
            print(f"  ✓ {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {fn.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
