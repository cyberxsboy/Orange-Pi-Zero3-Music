"""指令匹配: 关键词 + 拼音兜底.

输入: 中文文本
输出: Command(action, target_type, target_id, payload)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..logger import get_logger

log = get_logger(__name__)


# 系统指令意图（按优先级匹配）
SYSTEM_INTENTS: list[tuple[str, list[str]]] = [
    ("stop", ["停止", "关了", "关闭", "不听了", "结束"]),
    ("pause", ["暂停", "停一下", "等等"]),
    ("resume", ["继续", "接着", "恢复播放", "继续播放"]),
    ("next", ["下一首", "下一曲", "下一个", "换一首", "切歌"]),
    ("prev", ["上一首", "上一曲", "上一个", "前一首"]),
]


@dataclass
class Command:
    action: str  # play | pause | resume | next | prev | stop | query
    target_id: str | None = None
    target_name: str | None = None
    target_type: str | None = None  # local/stream/playlist
    raw: str = ""
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "target_id": self.target_id,
            "target_name": self.target_name,
            "target_type": self.target_type,
            "raw": self.raw,
            "payload": self.payload,
        }


class CommandMatcher:
    """指令匹配器."""

    def __init__(self, sources: list[dict], use_pinyin: bool = True, use_fuzzy: bool = False) -> None:
        self.sources = sources
        self.use_pinyin = use_pinyin
        self.use_fuzzy = use_fuzzy
        self._pinyin = None
        if use_pinyin:
            try:
                from pypinyin import lazy_pinyin
                self._pinyin = lazy_pinyin
            except ImportError:
                log.warning("pypinyin not installed; pinyin fallback disabled")

    def update_sources(self, sources: list[dict]) -> None:
        self.sources = sources

    def match(self, text: str) -> Command | None:
        if not text or not text.strip():
            return None
        text = self._normalize(text)

        # 1) 系统指令
        for action, kws in SYSTEM_INTENTS:
            for kw in kws:
                if kw in text:
                    return Command(action=action, raw=text)

        # 2) "音量" 指令
        m = re.search(r"音量\s*(?:调到|调成|调为|到)?\s*(\d+)\s*(?:%|％)?", text)
        if m:
            v = max(0, min(100, int(m.group(1))))
            return Command(action="volume", raw=text, payload={"value": v})

        # 3) 播放指令: 包含 "播放" / "来一首" / "听" / "放" / "想听" 等
        play_triggers = ["播放", "来一首", "听", "放", "想听", "来段", "要听"]
        triggered = any(t in text for t in play_triggers)
        # 即便没有触发词也尝试匹配（容错：用户可能直接说 "流行"）

        # 4) 匹配音乐源 (按 keyword/name 评分)
        best = self._match_source(text)
        if best:
            score, src = best
            if score > 0:
                return Command(
                    action="play",
                    target_id=src.get("id"),
                    target_name=src.get("name"),
                    target_type=src.get("type"),
                    raw=text,
                )

        # 5) 触发播放意图但无匹配/无源 -> unknown
        if triggered and self.sources:
            return Command(action="unknown", raw=text)
        return None

    def _normalize(self, text: str) -> str:
        # 去标点 (保留中文/字母/数字)
        text = re.sub(r"[，。！？、,.\!?;:：；\"'‘’\"\"]+", " ", text)
        return text.strip().lower()

    def _match_source(self, text: str) -> tuple[int, dict] | None:
        """返回 (score, source) - score 越高越好."""
        if not self.sources:
            return None

        candidates: list[tuple[int, dict]] = []
        text_pinyin = self._to_pinyin(text) if self._pinyin else text

        for src in self.sources:
            if not src.get("enabled", True):
                continue
            score = 0
            name = (src.get("name") or "").strip()
            for kw in src.get("keywords", []):
                kw = (kw or "").strip()
                if not kw:
                    continue
                if kw in text or text in kw:
                    score = max(score, 100 + len(kw))
                    continue
                # 拼音匹配
                if self._pinyin:
                    kw_py = self._to_pinyin(kw)
                    if kw_py and (kw_py in text_pinyin or text_pinyin in kw_py):
                        score = max(score, 70 + len(kw_py))
                # 模糊匹配（可选）
                if self.use_fuzzy and self._fuzzy:
                    ratio = self._fuzzy(text, kw)
                    if ratio >= 80:
                        score = max(score, 60 + int(ratio))
            if name and name in text:
                score = max(score, 50 + len(name))
            if score > 0:
                candidates.append((score, src))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0]

    def _to_pinyin(self, text: str) -> str:
        if not self._pinyin:
            return ""
        try:
            return "".join(self._pinyin(text))
        except Exception:  # noqa: BLE001
            return ""

    @property
    def _fuzzy(self):
        if not self.use_fuzzy:
            return None
        try:
            from rapidfuzz.fuzz import ratio
            return ratio
        except ImportError:
            return None
