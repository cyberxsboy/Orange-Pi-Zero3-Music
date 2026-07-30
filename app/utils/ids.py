"""短 ID 生成."""
from __future__ import annotations

import secrets
import string

# 排除易混字符
_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 32 chars


def new_id(length: int = 8) -> str:
    """生成 URL 友好的短 ID（默认 8 位 base32，不含 0/1/I/O）."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
