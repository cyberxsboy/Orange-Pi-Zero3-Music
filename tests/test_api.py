"""FastAPI 集成测试."""
import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 必须在 import 前设置 (uvicorn loop 兼容性)
import pytest  # noqa: E402

from app.ipc.bridge import EventBus  # noqa: E402
from app.player.controller import PlayerController  # noqa: E402
from app.sources.manager import SourceManager  # noqa: E402
from app.web.api import router  # noqa: E402
from app.web.server import create_app  # noqa: E402


def _tmp() -> Path:
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    f.close()
    return Path(f.name)


class FakeBackend:
    def __init__(self):
        self.state = "idle"
        self.vol = 80
        self.current = None

    async def get_state(self): return self.state
    async def get_current(self): return self.current
    async def get_volume(self): return self.vol
    async def set_volume(self, v): self.vol = v
    async def start(self): pass
    async def stop(self): pass
    async def play(self, u): self.state = "playing"; self.current = type("T", (), {"url": u, "title": u, "to_dict": lambda s: {"url": u}})()
    async def pause(self): self.state = "paused"
    async def resume(self): self.state = "playing"
    async def next(self): pass
    async def prev(self): pass

    def events(self):
        async def gen():
            if False:
                yield {}
        return gen()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    sources = SourceManager(_tmp())
    bus = EventBus()
    player = PlayerController.__new__(PlayerController)  # bypass __init__
    player.fsm = None
    player.queue = None
    player.bus = bus
    player.backend = FakeBackend()
    player._stopping = asyncio.Event()

    app = create_app(ROOT / "web", router)
    app.state.sources = sources
    app.state.player = player
    app.state.bus = bus
    app.state.log_file = _tmp()
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["ok"] is True


def test_sources_crud(client):
    r = client.post("/api/sources", json={
        "name": "t1", "type": "stream",
        "target": "http://x/a.mp3", "keywords": ["k"],
    })
    assert r.status_code == 200
    sid = r.json()["data"]["id"]
    r = client.get("/api/sources")
    assert r.status_code == 200
    assert len(r.json()["data"]) == 1
    r = client.put(f"/api/sources/{sid}", json={"description": "x"})
    assert r.status_code == 200
    assert r.json()["data"]["description"] == "x"
    r = client.delete(f"/api/sources/{sid}")
    assert r.status_code == 200


def test_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert "state" not in body["data"] or body["data"].get("player") in ("idle", "playing", "paused")


def test_volume(client):
    r = client.post("/api/player/volume", json={"value": 50})
    assert r.status_code == 200
    assert r.json()["data"]["volume"] == 50


def test_player_pause_resume(client):
    r = client.post("/api/player/pause")
    assert r.status_code == 200
    r = client.post("/api/player/play")
    assert r.status_code == 200


def test_audio_devices(client):
    r = client.get("/api/audio/devices")
    assert r.status_code == 200
    # devices list may be empty on non-Linux; just verify structure
    assert isinstance(r.json()["data"], list)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
