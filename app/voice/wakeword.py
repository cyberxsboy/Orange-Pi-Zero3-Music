"""唤醒词检测.

支持两种后端:
- openWakeWord (高精度，需训练样本)
- Vosk grammar (零配置，1GB 模式默认)

均输出统一的: detect(pcm_bytes) -> Optional[float] (置信度) / str (匹配词)
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable, Optional

from ..constants import WakeBackend
from ..logger import get_logger

log = get_logger(__name__)


class WakeWordEngine:
    """唤醒词检测器（适配 openWakeWord + Vosk grammar）."""

    def __init__(
        self,
        backend: WakeBackend,
        keywords: list[str],
        sample_rate: int = 16000,
        threshold: float = 0.5,
        model_dir: Path | None = None,
    ) -> None:
        self.backend = backend
        self.keywords = keywords
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.model_dir = model_dir
        self._impl = None
        self._loop_task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self.backend == WakeBackend.OPENWAKEWORD:
            self._impl = _OpenWakeWordImpl(self.keywords, self.threshold, self.model_dir)
        elif self.backend == WakeBackend.VOSK_GRAMMAR:
            self._impl = _VoskGrammarImpl(self.keywords, self.sample_rate, self.threshold)
        else:
            self._impl = _NoopImpl()
        try:
            await self._impl.start()
        except Exception as exc:  # noqa: BLE001
            log.exception("wake engine start failed: %s", exc)
            self._impl = _NoopImpl()

    async def stop(self) -> None:
        self._stopping.set()
        if self._impl:
            await self._impl.stop()

    async def detect(self, pcm_bytes: bytes) -> Optional[str]:
        """送入音频，返回命中的关键字 / None."""
        if not self._impl:
            return None
        return await self._impl.detect(pcm_bytes)

    @property
    def active(self) -> bool:
        return self._impl is not None and not isinstance(self._impl, _NoopImpl)


# ─────────── 实现 ───────────


class _Base:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def detect(self, pcm: bytes) -> Optional[str]: ...


class _NoopImpl(_Base):
    async def start(self) -> None:
        log.info("wakeword disabled")

    async def stop(self) -> None:
        pass

    async def detect(self, pcm: bytes) -> Optional[str]:  # noqa: ARG002
        return None


class _VoskGrammarImpl(_Base):
    """使用 Vosk 限定 grammar 识别唤醒词.

    优点: 零配置，中文可工作
    缺点: 灵敏度一般，CPU 略高
    """

    def __init__(self, keywords: list[str], sample_rate: int, threshold: float) -> None:
        self.keywords = keywords
        self.sample_rate = sample_rate
        self.threshold = threshold
        self._recognizer = None
        self._model = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load)

    def _load(self) -> None:
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
            SetLogLevel(-1)
            # 找模型路径
            import os
            model_path = os.environ.get("VOSK_MODEL_PATH", "data/stt_models/vosk-cn-small")
            if not Path(model_path).exists():
                log.error("vosk model missing: %s", model_path)
                return
            self._model = Model(model_path)
            grammar = json.dumps(self.keywords, ensure_ascii=False)
            self._recognizer = KaldiRecognizer(self._model, self.sample_rate, grammar)
            log.info("vosk grammar wake engine ready: %s", self.keywords)
        except ImportError:
            log.error("vosk not installed")
        except Exception as exc:  # noqa: BLE001
            log.exception("vosk grammar load failed: %s", exc)

    async def stop(self) -> None:
        self._recognizer = None
        self._model = None

    async def detect(self, pcm: bytes) -> Optional[str]:
        if not self._recognizer:
            return None
        loop = asyncio.get_event_loop()
        accepted = await loop.run_in_executor(None, self._accept, pcm)
        if accepted:
            log.info("wake hit: %s", accepted)
            return accepted
        return None

    def _accept(self, pcm: bytes) -> Optional[str]:
        if self._recognizer.AcceptWaveform(pcm):
            res = json.loads(self._recognizer.Result())
            text = res.get("text", "").strip()
            if text:
                # 模糊匹配 keywords
                for kw in self.keywords:
                    if kw in text or text in kw:
                        return kw
                return text
        return None


class _OpenWakeWordImpl(_Base):
    """openWakeWord 自定义/预训练模型.

    中文唤醒需提供自定义 onnx 模型.
    若 model_dir 为空或模型缺失，自动 fallback 到 Vosk grammar.
    """

    def __init__(self, keywords: list[str], threshold: float, model_dir: Path | None) -> None:
        self.keywords = keywords
        self.threshold = threshold
        self.model_dir = model_dir
        self._model = None
        self._oww = None

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._load)
        except Exception as exc:  # noqa: BLE001
            log.warning("openWakeWord load failed, fallback to vosk grammar: %s", exc)
            self._oww = None
            self._model = None
            # 回退：替换 impl
            raise

    def _load(self) -> None:
        try:
            import openwakeword
            from openwakeword.model import Model as OWWModel
        except ImportError as exc:
            raise RuntimeError("openwakeword not installed") from exc

        # 1) 找自定义模型
        custom = []
        if self.model_dir and self.model_dir.exists():
            for f in self.model_dir.glob("*.onnx"):
                custom.append(str(f))
        # 2) 预训练（仅英文/西班牙语；中文必须自定义）
        pretrained = ["alexa", "hey_jarvis", "hey_mycroft"]
        try:
            self._oww = OWWModel(
                wakeword_models=custom if custom else pretrained,
                inference_framework="onnx",
            )
            log.info("openWakeWord loaded: custom=%s pretrained=%s", custom, pretrained)
        except Exception as exc:  # noqa: BLE001
            log.warning("openWakeWord Model init failed: %s", exc)
            self._oww = None
            raise

    async def stop(self) -> None:
        self._oww = None

    async def detect(self, pcm: bytes) -> Optional[str]:
        if not self._oww:
            return None
        import numpy as np
        loop = asyncio.get_event_loop()
        scores = await loop.run_in_executor(None, self._predict, pcm)
        # scores: dict[name -> score]
        best_name, best_score = None, 0.0
        for name, s in scores.items():
            if s > best_score:
                best_name, best_score = name, s
        if best_name and best_score >= self.threshold:
            # 映射到 keyword
            mapped = self._map_to_keyword(best_name)
            log.info("wake hit: %s (%.2f) -> %s", best_name, best_score, mapped)
            return mapped
        return None

    def _predict(self, pcm: bytes) -> dict:
        import numpy as np
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        return self._oww.predict(audio)

    def _map_to_keyword(self, model_name: str) -> str:
        # 自定义模型文件名约定: <keyword>.onnx
        if self.model_dir:
            for p in self.model_dir.glob("*.onnx"):
                if p.stem == model_name or p.stem.startswith(model_name):
                    return p.stem
        # 预训练名直接返回
        return self.keywords[0] if self.keywords else model_name
