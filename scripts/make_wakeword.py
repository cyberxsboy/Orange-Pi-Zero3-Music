#!/usr/bin/env python3
"""录制并导出 openWakeWord 自定义唤醒词样本.

用法::

    python scripts/make_wakeword.py --keyword "你好小音" --out data/wakeword_models/
    python scripts/make_wakeword.py --keyword "你好小音" --out data/wakeword_models/ --count 30

每条样本约 2 秒；录入完成后用 openWakeWord 训练工具 (openwakeword/train.py) 训练 .onnx.
本脚本只负责采集 + 切片.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf


def record_one(sr: int, seconds: float) -> np.ndarray:
    print("  [press Enter to start recording]")
    input()
    print("  recording ...")
    audio = sd.rec(int(seconds * sr), samplerate=sr, channels=1, dtype="int16")
    sd.wait()
    print("  done.")
    return audio[:, 0]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--keyword", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--seconds", type=float, default=2.0)
    p.add_argument("--rate", type=int, default=16000)
    args = p.parse_args()

    out = Path(args.out) / args.keyword
    out.mkdir(parents=True, exist_ok=True)
    print(f"saving to {out} ({args.count} samples, {args.seconds}s each)")

    for i in range(args.count):
        print(f"[{i + 1}/{args.count}] 请清晰说出唤醒词: {args.keyword!r}")
        audio = record_one(args.rate, args.seconds)
        path = out / f"{i:03d}.wav"
        sf.write(str(path), audio, args.rate)
        print(f"  saved {path}")
        time.sleep(0.3)
    print("采集完成。训练方法:")
    print("  https://github.com/dscripnin/openWakeWord#training")
    return 0


if __name__ == "__main__":
    sys.exit(main())
