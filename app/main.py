"""应用入口: 装配 + asyncio 启动.

支持::

    python -m app.main            # 正常运行
    python -m app.main --check    # 配置/模型自检（不启动音频/播放器）
    python -m app.main --web      # 仅启动 Web (供开发调试)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from . import __version__
from .audio.tts import TTSEngine
from .config import AppConfig, ensure_dirs, load_config
from .ipc.bridge import EventBus
from .logger import get_logger, setup_logging
from .player.controller import PlayerController
from .shutdown import get_shutdown, install_signal_handlers
from .sources.manager import SourceManager
from .utils import systemd_notify
from .utils.hotreload import HotReloader
from .voice.listener import VoiceListener
from .web.api import router as api_router
from .web.server import create_app

log = get_logger("main")


# ─────────── 装配 ───────────


async def _build_app(cfg: AppConfig) -> tuple[FastAPI, dict]:
    """构造 FastAPI app 与共享对象."""
    bus = EventBus()
    sources = SourceManager(cfg.paths.sources_file)

    # 播放器
    player = PlayerController(
        backend_kind=cfg.player_backend,
        event_bus=bus,
        device=cfg.audio.get("output_device"),
        initial_volume=int(cfg.player.get("volume", 80)),
    )

    # TTS
    tts = TTSEngine(
        backend=cfg.tts_backend,
        cache_dir=cfg.paths.tts_cache_dir,
        piper_model=cfg.paths.project_root / cfg.tts.get("piper_model", ""),
        piper_config=cfg.paths.project_root / cfg.tts.get("piper_config", ""),
        volume=float(cfg.tts.get("volume", 1.0)),
    )

    # 语音
    listener = VoiceListener(
        cfg=cfg,
        bus=bus,
        sources=sources,
        tts=tts,
        on_command=_make_command_handler(player, sources, tts),
    )

    # FastAPI
    api_app = create_app(cfg.paths.web_dir, api_router)
    api_app.state.cfg = cfg
    api_app.state.bus = bus
    api_app.state.sources = sources
    api_app.state.player = player
    api_app.state.tts = tts
    api_app.state.listener = listener
    api_app.state.log_file = cfg.paths.log_dir / "music-player.log"

    return api_app, {
        "bus": bus,
        "sources": sources,
        "player": player,
        "tts": tts,
        "listener": listener,
    }


def _make_command_handler(player: PlayerController, sources: SourceManager, tts: TTSEngine):
    """指令处理回调."""

    async def handle(cmd) -> None:
        if cmd.action == "play" and cmd.target_id:
            try:
                src, urls = await sources.resolve(cmd.target_id)
                await player.play_source(
                    source_id=src["id"],
                    source_name=src.get("name", ""),
                    urls=urls,
                    shuffle=src.get("shuffle", False),
                )
                await tts.speak("好的")
            except Exception as exc:  # noqa: BLE001
                log.warning("play failed: %s", exc)
                try:
                    await tts.speak("没找到这个音乐源")
                except Exception:  # noqa: BLE001
                    pass
        elif cmd.action == "pause":
            await player.pause()
        elif cmd.action == "resume":
            await player.resume()
        elif cmd.action == "stop":
            await player.stop()
            try:
                await tts.speak("已停止")
            except Exception:  # noqa: BLE001
                pass
        elif cmd.action == "next":
            await player.next()
        elif cmd.action == "prev":
            await player.prev()
        elif cmd.action == "volume" and cmd.payload:
            v = int(cmd.payload.get("value", 80))
            await player.set_volume(v)
            try:
                await tts.speak(f"音量 {v}")
            except Exception:  # noqa: BLE001
                pass
        elif cmd.action == "unknown":
            try:
                await tts.speak("没听清，请再说一次")
            except Exception:  # noqa: BLE001
                pass

    return handle


# ─────────── 启动 ───────────


async def run_app(check_only: bool = False, web_only: bool = False) -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    setup_logging(
        cfg.paths.log_dir,
        level=cfg.raw.get("log_level", "INFO"),
    )
    log.info("=" * 50)
    log.info("OPI Music Player v%s starting", __version__)
    log.info("config: %s", cfg.paths.config_file)
    log.info("memory profile: %s", cfg.memory_profile.value)

    if check_only:
        _check(cfg)
        return

    api_app, ctx = await _build_app(cfg)
    listener: VoiceListener = ctx["listener"]
    player: PlayerController = ctx["player"]

    # 启动播放器
    try:
        await player.start()
    except Exception as exc:  # noqa: BLE001
        log.error("player start failed: %s", exc)

    if not web_only:
        # 启动语音监听
        try:
            await listener.start()
        except Exception as exc:  # noqa: BLE001
            log.error("listener start failed: %s", exc)

    # 热加载
    hot: HotReloader | None = None
    if bool(cfg.raw.get("features", {}).get("enable_inotify", False)):
        hot = HotReloader(cfg.paths.sources_file)
        hot.on_change = listener.reload_sources
        await hot.start()

    # 启动 web
    config = uvicorn.Config(
        api_app,
        host=cfg.web_host,
        port=cfg.web_port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # 避免重复处理
    server_task = asyncio.create_task(server.serve(), name="uvicorn")

    systemd_notify.notify_ready()
    systemd_notify.notify_status(f"running v{__version__}")

    shutdown = get_shutdown()
    install_signal_handlers(asyncio.get_running_loop(), shutdown)

    log.info("web: http://%s:%d", cfg.web_host, cfg.web_port)

    # 等到 shutdown
    try:
        await shutdown.wait()
    finally:
        systemd_notify.notify_status("stopping")
        log.info("shutting down...")
        if hot:
            await hot.stop()
        try:
            await listener.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            await player.stop()
        except Exception:  # noqa: BLE001
            pass
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=3.0)
        except asyncio.TimeoutError:
            server_task.cancel()
        log.info("bye.")


def _check(cfg: AppConfig) -> int:
    """配置/模型自检."""
    print(f"config:    {cfg.paths.config_file} ok")
    print(f"data dir:  {cfg.paths.data_dir} ok")
    print(f"web:       http://{cfg.web_host}:{cfg.web_port}")
    print(f"profile:   {cfg.memory_profile.value}")
    print(f"wake:      {cfg.wake_backend.value}")
    print(f"tts:       {cfg.tts_backend.value}")
    print(f"player:    {cfg.player_backend.value}")
    stt = Path(cfg.voice.get("stt_model_path", ""))
    if stt.exists():
        print(f"stt:       {stt} ✓")
    else:
        print(f"stt:       {stt} ✗ (run scripts/download_models.py)")
    piper = Path(cfg.tts.get("piper_model", ""))
    if piper.exists():
        print(f"tts model: {piper} ✓")
    else:
        print(f"tts model: {piper} ✗ (run scripts/download_models.py)")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="OPI Music Player")
    p.add_argument("--check", action="store_true", help="only check config and models")
    p.add_argument("--web", action="store_true", help="web only (no voice listener)")
    p.add_argument("--version", action="store_true", help="show version")
    args = p.parse_args()

    if args.version:
        print(__version__)
        return

    try:
        asyncio.run(run_app(check_only=args.check, web_only=args.web))
    except KeyboardInterrupt:
        print("interrupted")
    except SystemExit as e:
        raise e


if __name__ == "__main__":
    main()
