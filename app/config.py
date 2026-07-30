"""配置加载 + 内存 profile 切换."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constants import MemoryProfile, PlayerBackend, TTSBackend, WakeBackend
from .logger import get_logger

log = get_logger(__name__)


# ────────────────────────── 默认值 ──────────────────────────

DEFAULT_CONFIG: dict[str, Any] = {
    "memory_profile": "1g",
    "web": {
        "host": "0.0.0.0",
        "port": 8080,
    },
    "audio": {
        "input_device": None,
        "output_device": None,
        "input_mode": "auto",
        "output_mode": "auto",
        "sample_rate": 16000,
        "channels": 1,
        "input_blocksize": 4000,
    },
    "voice": {
        "enabled": True,
        "wake_backend": "openwakeword",
        "wake_keywords": ["你好小音", "嗨同学"],
        "wake_threshold": 0.5,
        "stt_model_path": "data/stt_models/vosk-cn-small",
        "stt_hotwords": "流行,轻音乐,电台,民谣,古典,儿歌,摇滚,爵士",
        "command_timeout_s": 5.0,
        "silence_stop_s": 0.7,
    },
    "tts": {
        "backend": "piper",
        "piper_model": "data/tts_models/zh_CN-huayan-x_low.onnx",
        "piper_config": "data/tts_models/zh_CN-huayan-x_low.onnx.json",
        "volume": 1.0,
    },
    "player": {
        "backend": "auto",
        "volume": 80,
        "fade_ms": 200,
    },
    "features": {
        "enable_wakeword": True,
        "enable_fuzzy_match": False,
        "enable_inotify": False,
        "enable_tts_during_play": True,
    },
    "paths": {
        "config_dir": "config",
        "data_dir": "data",
        "log_dir": "logs",
        "sources_file": "config/sources.json",
        "state_file": "data/state.json",
    },
}


# ────────────────────────── 数据类 ──────────────────────────


@dataclass
class AppPaths:
    """运行时路径."""

    project_root: Path
    config_dir: Path
    data_dir: Path
    log_dir: Path
    sources_file: Path
    state_file: Path
    config_file: Path
    web_dir: Path
    stt_model_dir: Path
    tts_model_dir: Path
    wakeword_dir: Path
    tts_cache_dir: Path

    @classmethod
    def from_config(cls, cfg: dict[str, Any], project_root: Path | None = None) -> "AppPaths":
        root = project_root or Path.cwd()
        paths = cfg.get("paths", {})
        return cls(
            project_root=root,
            config_dir=root / paths.get("config_dir", "config"),
            data_dir=root / paths.get("data_dir", "data"),
            log_dir=root / paths.get("log_dir", "logs"),
            sources_file=root / paths.get("sources_file", "config/sources.json"),
            state_file=root / paths.get("state_file", "data/state.json"),
            config_file=root / paths.get("config_dir", "config") / "config.json",
            web_dir=root / "web",
            stt_model_dir=root / "data" / "stt_models",
            tts_model_dir=root / "data" / "tts_models",
            wakeword_dir=root / "data" / "wakeword_models",
            tts_cache_dir=root / "data" / "tts_cache",
        )


@dataclass
class AppConfig:
    """应用配置（解包后的 dataclass 视图）."""

    raw: dict[str, Any]
    paths: AppPaths
    memory_profile: MemoryProfile
    web_host: str
    web_port: int
    audio: dict[str, Any]
    voice: dict[str, Any]
    tts: dict[str, Any]
    player: dict[str, Any]
    features: dict[str, Any]

    # 派生
    wake_backend: WakeBackend = field(init=False)
    tts_backend: TTSBackend = field(init=False)
    player_backend: PlayerBackend = field(init=False)

    def __post_init__(self) -> None:
        self.wake_backend = WakeBackend(self.voice.get("wake_backend", "openwakeword"))
        self.tts_backend = TTSBackend(self.tts.get("backend", "piper"))
        self.player_backend = PlayerBackend(self.player.get("backend", "auto"))


# ────────────────────────── 加载 ──────────────────────────


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """深度合并，override 优先."""
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def apply_memory_profile(cfg: dict[str, Any]) -> dict[str, Any]:
    """根据 memory_profile 调整 features 等开关."""
    profile = cfg.get("memory_profile", "1g")
    features = cfg.setdefault("features", {})
    voice = cfg.setdefault("voice", {})
    tts = cfg.setdefault("tts", {})

    if profile == MemoryProfile.GB1.value:
        features["enable_wakeword"] = False  # 默认关 openWakeWord
        features["enable_fuzzy_match"] = False
        features["enable_inotify"] = False
        # 1GB 模式默认走 Vosk grammar
        voice["wake_backend"] = "vosk_grammar"
        # TTS 用最轻量
        tts["piper_model"] = tts.get(
            "piper_model", "data/tts_models/zh_CN-huayan-x_low.onnx"
        )
    elif profile == MemoryProfile.GB2.value:
        features["enable_wakeword"] = True
        features["enable_fuzzy_match"] = False
    elif profile == MemoryProfile.GB4.value:
        features["enable_wakeword"] = True
        features["enable_fuzzy_match"] = True
        voice["wake_backend"] = voice.get("wake_backend", "openwakeword")

    return cfg


def load_config(
    config_path: Path | str | None = None,
    project_root: Path | str | None = None,
) -> AppConfig:
    """加载配置文件.

    优先级：环境变量 MUSIC_PLAYER_CONFIG > 指定路径 > 默认 config/config.json
    """
    root = Path(project_root) if project_root else Path.cwd()
    env_path = os.environ.get("MUSIC_PLAYER_CONFIG")
    if env_path:
        path = Path(env_path)
    elif config_path:
        path = Path(config_path)
    else:
        path = root / "config" / "config.json"

    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # 深拷贝
    if path.exists():
        try:
            user_cfg = json.loads(path.read_text(encoding="utf-8"))
            cfg = _deep_merge(cfg, user_cfg)
            log.info("loaded config from %s", path)
        except json.JSONDecodeError as exc:
            log.error("config.json invalid: %s, using defaults", exc)
    else:
        log.warning("config file not found: %s, using defaults", path)

    cfg = apply_memory_profile(cfg)

    paths = AppPaths.from_config(cfg, root)
    return AppConfig(
        raw=cfg,
        paths=paths,
        memory_profile=MemoryProfile(cfg.get("memory_profile", "1g")),
        web_host=cfg["web"]["host"],
        web_port=int(cfg["web"]["port"]),
        audio=cfg["audio"],
        voice=cfg["voice"],
        tts=cfg["tts"],
        player=cfg["player"],
        features=cfg["features"],
    )


def ensure_dirs(cfg: AppConfig) -> None:
    """确保所有目录存在."""
    for p in (
        cfg.paths.config_dir,
        cfg.paths.data_dir,
        cfg.paths.log_dir,
        cfg.paths.tts_cache_dir,
        cfg.paths.stt_model_dir,
        cfg.paths.tts_model_dir,
        cfg.paths.wakeword_dir,
    ):
        p.mkdir(parents=True, exist_ok=True)
