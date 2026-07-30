"""日志配置：按天滚动 + 限制大小."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

# 防止重复初始化
_initialized = False


def setup_logging(
    log_dir: Path,
    level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    console: bool = True,
) -> logging.Logger:
    """配置根 logger.

    Args:
        log_dir: 日志目录
        level: 日志级别
        max_bytes: 单文件最大字节
        backup_count: 备份数量
        console: 是否输出到控制台
    """
    global _initialized
    if _initialized:
        return logging.getLogger()

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "music-player.log"

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname).1s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件 handler（滚动 + 总数限制）
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(fmt)
        root.addHandler(stream)

    # 抑制过于吵杂的库
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    _initialized = True
    return root


def get_logger(name: str) -> logging.Logger:
    """获取 logger."""
    return logging.getLogger(name)
