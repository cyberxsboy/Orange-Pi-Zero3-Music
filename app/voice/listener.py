"""语音监听主循环: 唤醒 → STT → 匹配 → 命令派发."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from ..audio.capture import AudioCapture
from ..audio.tts import TTSEngine
from ..constants import WakeBackend
from ..ipc.bridge import EventBus
from ..logger import get_logger
from ..sources.manager import SourceManager
from .matcher import CommandMatcher
from .stt import VoskSTT
from .wakeword import WakeWordEngine

log = get_logger(__name__)


class VoiceListener:
    """语音监听主控.

    状态机:
        IDLE (唤醒词检测) → LISTEN (识别 5s) → MATCH → IDLE
    """

    def __init__(
        self,
        cfg,
        bus: EventBus,
        sources: SourceManager,
        tts: TTSEngine,
        on_command,
    ) -> None:
        self.cfg = cfg
        self.bus = bus
        self.sources = sources
        self.tts = tts
        self.on_command = on_command  # async callback
        self._capture: AudioCapture | None = None
        self.wake: WakeWordEngine | None = None
        self.stt: VoskSTT | None = None
        self._matcher: CommandMatcher | None = None
        self._stopping = asyncio.Event()
        self._listen_event = asyncio.Event()
        self._busy = asyncio.Lock()
        self._enabled: bool = bool(cfg.voice.get("enabled", True))

    async def start(self) -> None:
        if not self._enabled:
            log.info("voice listener disabled by config")
            return

        # 1) 麦克风
        device = self.cfg.audio.get("input_device")
        self._capture = AudioCapture(
            sample_rate=int(self.cfg.audio.get("sample_rate", 16000)),
            channels=int(self.cfg.audio.get("channels", 1)),
            blocksize=int(self.cfg.audio.get("input_blocksize", 4000)),
            device=device,
        )
        self._capture.set_error_handler(self._on_capture_error)
        try:
            self._capture.start()
        except Exception as exc:
            log.error("audio capture start failed: %s (voice disabled)", exc)
            self._enabled = False
            return

        # 2) 唤醒词
        self.wake = WakeWordEngine(
            backend=self.cfg.wake_backend,
            keywords=list(self.cfg.voice.get("wake_keywords", [])),
            sample_rate=int(self.cfg.audio.get("sample_rate", 16000)),
            threshold=float(self.cfg.voice.get("wake_threshold", 0.5)),
            model_dir=self.cfg.paths.wakeword_dir,
        )
        await self.wake.start()

        # 3) STT
        stt_path = Path(self.cfg.voice.get("stt_model_path", "data/stt_models/vosk-cn-small"))
        self.stt = VoskSTT(
            model_path=stt_path,
            sample_rate=int(self.cfg.audio.get("sample_rate", 16000)),
            hotwords=self.cfg.voice.get("stt_hotwords"),
        )
        self.stt.load()
        if not self.stt.is_available:
            log.error("STT not available (model missing?)")

        # 4) Matcher
        src_list = await self.sources.list()
        self._matcher = CommandMatcher(
            sources=src_list,
            use_pinyin=True,
            use_fuzzy=bool(self.cfg.features.get("enable_fuzzy_match", False)),
        )

        # 5) 启动主循环
        self._stopping.clear()
        asyncio.create_task(self._run_loop(), name="voice-listener")
        log.info("voice listener started")

    async def stop(self) -> None:
        self._stopping.set()
        if self.wake:
            await self.wake.stop()
        if self._capture:
            self._capture.stop()
        log.info("voice listener stopped")

    async def reload_sources(self) -> None:
        if not self._matcher:
            return
        src_list = await self.sources.list()
        self._matcher.update_sources(src_list)
        log.info("voice matcher reloaded: %d sources", len(src_list))

    # ─────────── 主循环 ───────────

    async def _run_loop(self) -> None:
        assert self._capture is not None
        try:
            while not self._stopping.is_set():
                # 取一段 0.5s 的音频
                pcm = self._capture.read(
                    int(self.cfg.audio["sample_rate"] * 0.5 * 2),  # 16bit
                    timeout=1.0,
                )
                if not pcm:
                    continue

                # 唤醒检测
                if self.wake and self.wake.active:
                    hit = await self.wake.detect(pcm)
                    if hit:
                        log.info("wake detected: %s", hit)
                        await self.bus.emit("wake_detected", {"keyword": hit})
                        # 短暂 TTS 提示
                        try:
                            await self.tts.speak("我在")
                        except Exception as exc:  # noqa: BLE001
                            log.debug("tts ack failed: %s", exc)
                        # 进入识别
                        if self.stt and self.stt.is_available:
                            text = await self._listen_once()
                            if text:
                                log.info("stt final: %s", text)
                                await self.bus.emit("stt_final", {"text": text})
                                await self._dispatch(text)
                else:
                    # 无唤醒词: 持续 STT (push-to-talk 模式可后续接入)
                    # 为节省资源，1GB 模式下若 wake 未启用则不进入 STT
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("voice loop error: %s", exc)
            await asyncio.sleep(1)

    async def _listen_once(self, max_seconds: float = 5.0, silence_stop_s: float = 0.7) -> str:
        """唤醒后开启一次 STT, 收集一段语音并返回 final 文本."""
        assert self._capture is not None and self.stt is not None
        self.stt.reset()
        text_acc = ""
        last_voice_ts = time.time()
        deadline = time.time() + max_seconds
        sample_bytes_per_100ms = int(self.cfg.audio["sample_rate"] * 0.1 * 2)

        while time.time() < deadline:
            pcm = self._capture.read(sample_bytes_per_100ms, timeout=0.5)
            if not pcm:
                continue
            final = self.stt.accept_waveform(pcm)
            if final:
                text_acc = (text_acc + " " + final).strip()
                last_voice_ts = time.time()
                # 还可以继续听，但暂以第一段 final 收尾
                return text_acc
            else:
                # 用 partial 估算是否在说话（仅启发）
                p = self.stt.partial()
                if p:
                    last_voice_ts = time.time()
            # 静音超时
            if time.time() - last_voice_ts > silence_stop_s and text_acc:
                return text_acc
        # 强制收尾
        tail = self.stt.final()
        return (text_acc + " " + tail).strip() if tail else text_acc

    async def _dispatch(self, text: str) -> None:
        if not self._matcher:
            return
        cmd = self._matcher.match(text)
        if not cmd:
            return
        log.info("command: %s", cmd.to_dict())
        await self.bus.emit("command", cmd.to_dict())
        try:
            await self.on_command(cmd)
        except Exception as exc:  # noqa: BLE001
            log.exception("command handler failed: %s", exc)

    def _on_capture_error(self, exc: Exception) -> None:
        log.error("capture error: %s", exc)
        # 重试 1 次
        asyncio.create_task(self._retry_capture())

    async def _retry_capture(self) -> None:
        await asyncio.sleep(2)
        if self._stopping.is_set() or not self._capture:
            return
        try:
            self._capture.stop()
            self._capture.start()
            log.info("capture restarted")
        except Exception as exc:  # noqa: BLE001
            log.error("capture retry failed: %s", exc)
