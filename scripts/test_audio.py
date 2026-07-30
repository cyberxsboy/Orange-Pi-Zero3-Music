#!/usr/bin/env python3
"""音频自检: 录 5 秒并回放."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import sounddevice as sd
import soundfile as sf


def main() -> int:
    sr = 16000
    duration = 5
    out = Path("data/test_capture.wav")
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"device: {sd.default.device}")
    print(f"recording {duration}s @ {sr}Hz ...")
    audio = sd.rec(int(duration * sr), samplerate=sr, channels=1, dtype="int16")
    sd.wait()
    sf.write(str(out), audio, sr)
    print(f"saved: {out}")
    print("现在请用 'aplay data/test_capture.wav' 听回放")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
