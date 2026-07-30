"""TTS 适配：piper (本地) → edge-tts (在线) → espeak-ng (兜底).

提供异步 `speak(text)` 接口 + 短句缓存.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Awaitable, Callable

from ..constants import TTSBackend
from ..logger import get_logger

log = get_logger(__name__)


class TTSEngine:
    """TTS 引擎统一封装."""

    def __init__(
        self,
        backend: TTSBackend,
        cache_dir: Path,
        piper_model: Path | None = None,
        piper_config: Path | None = None,
        volume: float = 1.0,
    ) -> None:
        self.backend = backend
        self.cache_dir = cache_dir
        self.piper_model = piper_model
        self.piper_config = piper_config
        self.volume = volume
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._piper_voice = None  # lazy
        self._lock = asyncio.Lock()
        # 播放回调（默认使用 aplay）
        self._playback: Callable[[Path], Awaitable[None]] | None = None

    def set_playback(self, fn: Callable[[Path], Awaitable[None]]) -> None:
        """注册播放回调（用来和 music player 互斥）."""
        self._playback = fn

    # ─────────── 公开 API ───────────

    async def speak(self, text: str, use_cache: bool = True) -> None:
        """合成并播放一段语音."""
        if not text or not text.strip():
            return
        text = text.strip()
        async with self._lock:
            wav = await self._synthesize(text, use_cache=use_cache)
            if wav is None:
                log.warning("TTS synth failed: %s", text)
                return
            await self._play(wav)

    async def synthesize_to_file(self, text: str, out: Path) -> Path | None:
        """合成到指定路径（不播放）."""
        async with self._lock:
            return await self._synthesize(text, use_cache=False, force_out=out)

    def warm_cache(self, phrases: list[str]) -> None:
        """同步预热常用短句缓存（启动时调用）."""
        for p in phrases:
            try:
                asyncio.run(self._synthesize(p, use_cache=True))
            except Exception as exc:  # noqa: BLE001
                log.debug("warm cache failed for %r: %s", p, exc)

    # ─────────── 合成 ───────────

    async def _synthesize(
        self,
        text: str,
        use_cache: bool = True,
        force_out: Path | None = None,
    ) -> Path | None:
        if use_cache and force_out is None:
            cached = self._cache_path(text)
            if cached.exists():
                return cached

        out = force_out or (self.cache_dir / f"{self._hash(text)}.wav")
        if out.exists() and use_cache:
            return out

        if self.backend == TTSBackend.PIPER:
            ok = await self._piper_synth(text, out)
        elif self.backend == TTSBackend.EDGE:
            ok = await self._edge_synth(text, out)
        elif self.backend == TTSBackend.ESPEAK:
            ok = self._espeak_synth(text, out)
        else:
            log.error("unknown TTS backend: %s", self.backend)
            return None

        if not ok or not out.exists():
            return None
        return out

    async def _piper_synth(self, text: str, out: Path) -> bool:
        """调用 piper CLI 合成."""
        if not self.piper_model or not Path(self.piper_model).exists():
            log.warning("piper model missing, fallback to espeak")
            return self._espeak_synth(text, out)
        if not shutil.which("piper"):
            log.warning("piper binary missing, fallback to espeak")
            return self._espeak_synth(text, out)

        cmd = [
            "piper",
            "--model", str(self.piper_model),
            "--output_file", str(out),
        ]
        if self.piper_config and Path(self.piper_config).exists():
            cmd += ["--config", str(self.piper_config)]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=text.encode("utf-8")),
                    timeout=15.0,
                )
            except asyncio.TimeoutError:
                proc.kill()
                log.error("piper synth timeout: %s", text[:20])
                return False
            if proc.returncode != 0:
                log.error("piper failed: %s", stderr.decode(errors="ignore")[:200])
                return False
            return True
        except FileNotFoundError:
            log.warning("piper not installed")
            return False

    async def _edge_synth(self, text: str, out: Path) -> bool:
        """edge-tts 在线 (microsoft)."""
        try:
            import edge_tts  # type: ignore[import-not-found]
        except ImportError:
            log.warning("edge-tts not installed")
            return self._espeak_synth(text, out)
        try:
            communicate = edge_tts.Communicate(text, voice="zh-CN-XiaoxiaoNeural")
            await communicate.save(str(out))
            return out.exists()
        except Exception as exc:  # noqa: BLE001
            log.warning("edge-tts failed: %s; fallback espeak", exc)
            return self._espeak_synth(text, out)

    def _espeak_synth(self, text: str, out: Path) -> bool:
        """espeak-ng 兜底."""
        if not shutil.which("espeak-ng") and not shutil.which("espeak"):
            log.error("no TTS backend available")
            return False
        bin_ = shutil.which("espeak-ng") or shutil.which("espeak")
        cmd = [bin_, "-v", "zh+f3", "-s", "150", "-w", str(out), text]
        try:
            subprocess.run(cmd, check=True, timeout=10, capture_output=True)
            return out.exists()
        except Exception as exc:  # noqa: BLE001
            log.error("espeak failed: %s", exc)
            return False

    # ─────────── 播放 ───────────

    async def _play(self, wav: Path) -> None:
        if self._playback:
            try:
                await self._playback(wav)
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("custom TTS playback failed: %s, fallback aplay", exc)
        await self._aplay(wav)

    async def _aplay(self, wav: Path) -> None:
        if not shutil.which("aplay"):
            log.warning("aplay not installed; cannot play TTS")
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "aplay", "-q", str(wav),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            proc.kill()
        except Exception as exc:  # noqa: BLE001
            log.warning("aplay failed: %s", exc)

    # ─────────── 工具 ───────────

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]

    def _cache_path(self, text: str) -> Path:
        return self.cache_dir / f"{self._hash(text)}.wav"
