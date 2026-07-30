"""全局常量与枚举."""
from __future__ import annotations

from enum import Enum


# ────────────────────────── 应用元数据 ──────────────────────────

APP_NAME = "opi-music-player"
APP_VERSION = "0.1.0"

# 路径（运行时由 config.AppPaths 提供具体值，这里仅保留默认名）
DEFAULT_CONFIG_DIR = "config"
DEFAULT_DATA_DIR = "data"
DEFAULT_LOG_DIR = "logs"

# Web
DEFAULT_WEB_HOST = "0.0.0.0"
DEFAULT_WEB_PORT = 8080

# ────────────────────────── 枚举 ──────────────────────────


class SourceType(str, Enum):
    """音乐源类型."""

    LOCAL = "local"
    STREAM = "stream"
    PLAYLIST = "playlist"
    ONLINE = "online"  # 在线 API 源（GD 音乐台等免认证公共 API）


class PlayerBackend(str, Enum):
    """播放器后端."""

    AUTO = "auto"
    MPG123 = "mpg123"
    VLC = "vlc"


class PlayerState(str, Enum):
    """播放状态机."""

    IDLE = "idle"
    LOADING = "loading"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


class WakeBackend(str, Enum):
    """唤醒词后端."""

    NONE = "none"
    OPENWAKEWORD = "openwakeword"
    VOSK_GRAMMAR = "vosk_grammar"


class TTSBackend(str, Enum):
    """TTS 后端."""

    PIPER = "piper"
    EDGE = "edge"
    ESPEAK = "espeak"


class MemoryProfile(str, Enum):
    """内存档位."""

    GB1 = "1g"
    GB2 = "2g"
    GB4 = "4g"


# ────────────────────────── 错误码 ──────────────────────────

ERR_PARAM = 1001
ERR_NOT_FOUND = 1002
ERR_CONFLICT = 1003
ERR_PLAYER_BUSY = 1004
ERR_AUDIO_DEVICE = 1005
ERR_INTERNAL = 1500


# ────────────────────────── 内部事件名 ──────────────────────────

EVENT_WAKE_DETECTED = "wake_detected"
EVENT_STT_FINAL = "stt_final"
EVENT_STT_PARTIAL = "stt_partial"
EVENT_COMMAND = "command"
EVENT_PLAYER_STATE = "player_state"
EVENT_TRACK_CHANGED = "track_changed"
EVENT_TTS_PLAYED = "tts_played"
EVENT_SOURCE_CHANGED = "source_changed"
EVENT_VOLUME_CHANGED = "volume_changed"
