"""音乐源数据模型 + Pydantic schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from ..constants import SourceType


class MusicSource(BaseModel):
    """音乐源模型（持久化到 sources.json）."""

    id: str = Field(..., min_length=4, max_length=32, description="8位 base32 短ID")
    name: str = Field(..., min_length=1, max_length=64)
    type: SourceType
    target: str = Field(..., min_length=1, description="路径或 URL")
    keywords: list[str] = Field(..., min_length=1)
    description: str = Field(default="", max_length=256)
    enabled: bool = True
    recursive: bool = True
    format_filter: list[str] = Field(
        default_factory=lambda: ["mp3", "wav", "flac", "m4a", "ogg"]
    )
    shuffle: bool = False
    created_at: str
    updated_at: str

    @field_validator("keywords")
    @classmethod
    def _strip_keywords(cls, v: list[str]) -> list[str]:
        return [k.strip() for k in v if k and k.strip()]

    def to_dict(self) -> dict:
        d = self.model_dump()
        d["type"] = self.type.value
        return d


class MusicSourceCreate(BaseModel):
    """新增音乐源请求."""

    name: str = Field(..., min_length=1, max_length=64)
    type: SourceType
    target: str = Field(..., min_length=1)
    keywords: list[str] = Field(..., min_length=1)
    description: str = ""
    enabled: bool = True
    recursive: bool = True
    format_filter: list[str] | None = None
    shuffle: bool = False


class MusicSourceUpdate(BaseModel):
    """修改音乐源请求（所有字段可选）."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    type: SourceType | None = None
    target: str | None = None
    keywords: list[str] | None = None
    description: str | None = None
    enabled: bool | None = None
    recursive: bool | None = None
    format_filter: list[str] | None = None
    shuffle: bool | None = None


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
