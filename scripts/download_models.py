#!/usr/bin/env python3
"""下载 Vosk 中文模型 + piper 中文语音.

支持断点续传; 单独下载::

    python scripts/download_models.py vosk
    python scripts/download_models.py piper
    python scripts/download_models.py all (默认)
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STT = DATA / "stt_models"
TTS = DATA / "tts_models"

VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip"
VOSK_NAME = "vosk-model-small-cn-0.22"
VOSK_DIR = STT / "vosk-cn-small"

PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/x_low"
PIPER_FILES = [
    "zh_CN-huayan-x_low.onnx",
    "zh_CN-huayan-x_low.onnx.json",
]


def download(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_size > 0:
        print(f"  exists: {dst}")
        return
    print(f"  downloading: {url}")
    print(f"           to: {dst}")
    tmp = dst.with_suffix(dst.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            chunk = 64 * 1024
            downloaded = 0
            with tmp.open("wb") as f:
                while True:
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    f.write(buf)
                    downloaded += len(buf)
                    if total:
                        pct = downloaded * 100 // total
                        print(f"\r  {pct:3d}%  {downloaded}/{total}", end="", flush=True)
            print()
        tmp.replace(dst)
    except Exception as exc:
        print(f"  ERROR: {exc}", file=sys.stderr)
        if tmp.exists():
            tmp.unlink()
        raise


def download_vosk() -> None:
    print("==> Vosk 中文小模型 (42MB)")
    STT.mkdir(parents=True, exist_ok=True)
    zip_path = STT / f"{VOSK_NAME}.zip"
    download(VOSK_URL, zip_path)
    if VOSK_DIR.exists():
        print(f"  exists: {VOSK_DIR}")
        return
    print("  extracting...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(STT)
    extracted = STT / VOSK_NAME
    if extracted.exists():
        extracted.rename(VOSK_DIR)
    if zip_path.exists():
        zip_path.unlink()
    print(f"  done: {VOSK_DIR}")


def download_piper() -> None:
    print("==> Piper 中文 x_low 量化模型 (~8MB)")
    TTS.mkdir(parents=True, exist_ok=True)
    for f in PIPER_FILES:
        download(f"{PIPER_BASE}/{f}", TTS / f)
    print(f"  done: {TTS}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("target", nargs="?", default="all", choices=["all", "vosk", "piper"])
    args = p.parse_args()
    try:
        if args.target in ("all", "vosk"):
            download_vosk()
        if args.target in ("all", "piper"):
            download_piper()
    except KeyboardInterrupt:
        print("interrupted")
        return 130
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print("all models ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
