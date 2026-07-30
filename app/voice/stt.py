"""Vosk 离线中文 STT 封装."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator

from ..logger import get_logger

log = get_logger(__name__)


class VoskSTT:
    """Vosk 中文识别器."""

    def __init__(
        self,
        model_path: str | Path,
        sample_rate: int = 16000,
        hotwords: str | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        self.sample_rate = sample_rate
        self.hotwords = hotwords or ""
        self._model = None
        self._recognizer = None
        self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    def load(self) -> None:
        if not self.model_path.exists():
            log.error("Vosk model not found: %s", self.model_path)
            self._available = False
            return
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
            SetLogLevel(-1)
            self._model = Model(str(self.model_path))
            self._recognizer = KaldiRecognizer(self._model, self.sample_rate)
            if self.hotwords:
                # Vosk 0.3.45 接口: SetWords + 关键词权重
                try:
                    # hotwords 格式: "word weight word weight"
                    self._recognizer.SetWords(True)
                except Exception:  # noqa: BLE001
                    pass
            self._available = True
            log.info("Vosk STT loaded: %s", self.model_path)
        except ImportError:
            log.error("vosk not installed")
            self._available = False
        except Exception as exc:  # noqa: BLE001
            log.exception("Vosk load failed: %s", exc)
            self._available = False

    def set_grammar(self, words: list[str]) -> None:
        """使用 grammar 模式，仅识别给定词表（用于唤醒）.

        Args:
            words: 词表 JSON 数组
        """
        if not self._model:
            return
        try:
            from vosk import KaldiRecognizer
            grammar = json.dumps(words, ensure_ascii=False)
            self._recognizer = KaldiRecognizer(self._model, self.sample_rate, grammar)
            log.info("Vosk grammar set: %s", words)
        except Exception as exc:  # noqa: BLE001
            log.warning("set grammar failed: %s", exc)

    def accept_waveform(self, pcm_bytes: bytes) -> str | None:
        """送入 PCM 帧. 若有 final 结果返回文本, 否则 None."""
        if not self._available or not self._recognizer:
            return None
        if self._recognizer.AcceptWaveform(pcm_bytes):
            res = json.loads(self._recognizer.Result())
            return res.get("text", "").strip() or None
        return None

    def partial(self) -> str:
        """获取当前 partial 结果."""
        if not self._recognizer:
            return ""
        try:
            res = json.loads(self._recognizer.PartialResult())
            return res.get("partial", "")
        except Exception:  # noqa: BLE001
            return ""

    def final(self) -> str:
        """强制收尾，返回尚未 final 的剩余文本."""
        if not self._recognizer:
            return ""
        try:
            res = json.loads(self._recognizer.FinalResult())
            return res.get("text", "").strip()
        except Exception:  # noqa: BLE001
            return ""

    def reset(self) -> None:
        """重置识别器状态 (不影响 grammar)."""
        if not self._model:
            return
        try:
            from vosk import KaldiRecognizer
            # 重新创建以清空 buffer; 若要保留 grammar 应在外层重新设置
            self._recognizer = KaldiRecognizer(self._model, self.sample_rate)
        except Exception as exc:  # noqa: BLE001
            log.warning("vosk reset failed: %s", exc)

    async def stream(self, audio_iter: AsyncIterator[bytes]) -> AsyncIterator[dict]:
        """异步流式识别: yield {"partial": str, "final": str}."""
        async for chunk in audio_iter:
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, self.accept_waveform, chunk)
            if text:
                yield {"final": text}
            else:
                p = self.partial()
                if p:
                    yield {"partial": p}
        # 收尾
        tail = self.final()
        if tail:
            yield {"final": tail}
