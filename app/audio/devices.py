"""ALSA 设备枚举.

通过解析 `arecord -l` / `aplay -l` 输出得到当前可用的音频设备列表，
用于在 Web 管理页展示给用户。

Orange Pi Zero3 官方硬件接口 (USB 2.0 × 3, 13Pin 含 2 出 1 入音频):
  - 1×USB-A 2.0 (物理 USB-A 座)
  - 2×USB 2.0 (13Pin 排针上的焊盘, 需焊出才能用)
  - 1×Type-C (仅电源, 5V/3A)
  - 13Pin 排针:
      * 2×USB 2.0 (D+/D-/GND × 2)
      * 音频输出 L/R/GND  (3.5mm 耳机座, H618 codec 内置 DAC)
      * 音频输入 MIC/GND  (3.5mm 麦克风座 或 焊线, H618 codec 内置 ADC)
      * TV-Out (CVBS)
      * IR 接收
  - 26Pin 排针: GPIO (无标准功能, 通常不接)
  - 3Pin Debug UART

ALSA 设备命名规则:
  - 板载 codec (13Pin 耳机口 + 麦克风): 通常为 hw:0,0, 驱动名含 "sndh618"/"audiocodec"/"H616Audio"
  - USB 声卡/麦: hw:1,0 / hw:2,0 ..., 驱动名含 "USB"
  - HDMI 音频: hw:X,1 或类似, 驱动名含 "hdmi"
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from typing import Literal

from ..logger import get_logger

log = get_logger(__name__)


@dataclass
class AudioDevice:
    """音频设备描述."""

    card: int
    device: int
    index: str  # "hw:1,0"
    name: str  # 短名
    long_name: str  # 完整名
    kind: Literal["input", "output", "duplex"]

    # 推断出的接口类型
    bus: Literal["onboard", "usb", "hdmi", "unknown"] = "unknown"

    def to_dict(self) -> dict:
        return asdict(self)


_CARD_RE = re.compile(
    r"card\s+(\d+):\s+([^\s]+)\s+\[(?P<long>.+?)\],\s+device\s+(\d+):\s+(?P<devname>.+?)\s+\[(?P<devlong>.*?)\]"
)

# 推断 bus 类型的关键字
# Orange Pi Zero3 常见驱动名 (Ubuntu 22.04 + mainline kernel):
#   - 板载 codec: "sndh618" / "audiocodec" / "sun50i-h616-audio" / "cdc pcm codec" / "H616Audio"
#   - HDMI:       "sndhdmi" / "hdmi" (注意: 某些旧内核里 "sndhdmi" 是板载而非 HDMI)
#   - USB:        "usb" / "USB Audio"
_ONBOARD_KEYS = (
    # 优先匹配更具体的, 避免和 hdmi 冲突
    "sndh618",         # Orange Pi 官方镜像常见名
    "h616audio",       # H616Audio / H616 Audio (Ubuntu 22.04 常见)
    "h616-audio",
    "audiocodec",      # 主线内核 simple-audio-card
    "sun50i-h616",     # 主线内核
    "allwinner-h616",
    "allwinner-codec",
    "sunxi-sndac108",
    "sndac108",
    "es8388",
    "1c22800",         # H616 I2S 控制器
    "snd-sunxi",       # 旧内核
    "cdc pcm",         # codec 通用描述
    "headphone",       # codec 子设备名
    "3.5mm",
    "analog-audio",
)
_HDMI_KEYS = (
    "sndhdmi",         # 旧内核板载 codec 名字 (易混淆, 故放最后)
    "hdmi",
    "HDMI",
)
_USB_KEYS = ("usb", "USB")


def _infer_bus(long_name: str, devname: str) -> str:
    text = (long_name + " " + devname).lower()
    # 顺序很重要: 先 USB (最具体) → 板载 → HDMI
    # 因为某些镜像里 "sndhdmi" 实际是板载 codec, 不是 HDMI
    if any(k.lower() in text for k in _USB_KEYS):
        return "usb"
    if any(k.lower() in text for k in _ONBOARD_KEYS):
        return "onboard"
    if any(k.lower() in text for k in _HDMI_KEYS):
        return "hdmi"
    return "unknown"


def _list_alsa(kind: str) -> list[AudioDevice]:
    """运行 arecord -l / aplay -l 并解析."""
    cmd = "arecord" if kind == "input" else "aplay"
    if not shutil.which(cmd):
        log.warning("%s not found; ALSA tools missing?", cmd)
        return []

    try:
        out = subprocess.check_output([cmd, "-l"], text=True, stderr=subprocess.STDOUT, timeout=5)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.debug("%s -l failed: %s", cmd, exc)
        return []

    devices: list[AudioDevice] = []
    for line in out.splitlines():
        m = _CARD_RE.search(line)
        if not m:
            continue
        card = int(m.group(1))
        name = m.group(2)
        long_name = m.group("long").strip()
        device = int(m.group(4))
        devname = m.group("devname").strip()
        devlong = m.group("devlong").strip()
        bus = _infer_bus(long_name, devname)
        devices.append(
            AudioDevice(
                card=card,
                device=device,
                index=f"hw:{card},{device}",
                name=f"{name}::{devname}",
                long_name=f"{long_name} - {devlong}",
                kind=kind,  # 由调用方决定
                bus=bus,
            )
        )
    return devices


def list_devices() -> list[dict]:
    """列出所有 ALSA 设备（input/output/duplex）.

    同一 card+device 出现在 input 和 output 列表中则标记为 duplex。
    """
    ins = _list_alsa("input")
    outs = _list_alsa("output")

    # 用 (card, device) 合并
    in_set = {(d.card, d.device): d for d in ins}
    out_set = {(d.card, d.device): d for d in outs}
    keys = set(in_set) | set(out_set)
    merged: list[AudioDevice] = []
    for k in sorted(keys):
        in_d = in_set.get(k)
        out_d = out_set.get(k)
        # bus 推断: 取两个中更具体的那个 (usb/onboard 优先于 unknown)
        bus = "unknown"
        for d in (in_d, out_d):
            if d and d.bus != "unknown":
                bus = d.bus
                break
        if in_d and out_d:
            kind = "duplex"
        elif in_d:
            kind = "input"
        else:
            kind = "output"
        base = in_d or out_d
        assert base is not None
        merged.append(
            AudioDevice(
                card=k[0],
                device=k[1],
                index=f"hw:{k[0]},{k[1]}",
                name=base.name,
                long_name=base.long_name,
                kind=kind,
                bus=bus,
            )
        )
    return [d.to_dict() for d in merged]


def find_usb_audio() -> dict[str, str | None]:
    """查找第一块 USB 声卡作为默认输入/输出.

    Returns:
        {"input": "hw:X,0" or None, "output": "hw:Y,0" or None}
    """
    devs = list_devices()
    usb = [d for d in devs if d["bus"] == "usb"]
    in_dev = next((d for d in usb if d["kind"] in ("input", "duplex")), None)
    out_dev = next((d for d in usb if d["kind"] in ("output", "duplex")), None)
    return {
        "input": in_dev["index"] if in_dev else None,
        "output": out_dev["index"] if out_dev else None,
    }


def find_onboard_audio() -> dict[str, str | None]:
    """查找 13Pin 板载音频 (H618 内置 codec).

    13Pin 排针支持 2 路音频输出 (L/R) + 1 路音频输入 (MIC),
    H618 codec 内置 DAC + ADC, 同 ALSA card 暴露为 duplex 设备.

    Returns:
        {"input": "hw:X,0" or None, "output": "hw:Y,0" or None}
        同一 card 同时提供 input 和 output.
    """
    devs = list_devices()
    onb = [d for d in devs if d["bus"] == "onboard"]
    in_dev = next((d for d in onb if d["kind"] in ("input", "duplex")), None)
    out_dev = next((d for d in onb if d["kind"] in ("output", "duplex")), None)
    return {
        "input": in_dev["index"] if in_dev else None,
        "output": out_dev["index"] if out_dev else None,
    }


def find_onboard_mic() -> str | None:
    """仅查找 13Pin 板载麦克风输入 (H618 codec 的 ADC 通道).

    适合只想接 13Pin 模拟麦的场景, 不需要 USB 麦.
    """
    onb = find_onboard_audio()
    return onb.get("input")


def resolve_audio_device(
    explicit: str | None,
    mode: str = "auto",
    direction: Literal["input", "output"] = "output",
) -> str | int | None:
    """根据 config 解析最终要用的 ALSA 设备.

    优先级: explicit (input_device/output_device) > mode (auto/usb/onboard/hdmi/hw:X,Y)

    Args:
        explicit: config 中直接指定的设备 (e.g. "hw:1,0" 或 None)
        mode: config 中指定的 mode
        direction: input 或 output

    Returns:
        传给 sounddevice 的设备参数 (str like "hw:1,0", int card index, 或 None 用 default)
    """
    # 1) 显式指定 (input_device / output_device)
    if explicit and explicit not in ("", "auto", "default"):
        # 允许 int (card index) 或 str (hw:1,0)
        if isinstance(explicit, str) and explicit.startswith("hw:"):
            return explicit
        return explicit  # 可能是 int 字符串或纯数字

    # 2) 直接 hw:X,Y 模式
    if isinstance(mode, str) and mode.startswith("hw:"):
        return mode

    # 3) 名称模式
    # auto 模式下:
    #   - 输出: 板载 codec 优先 (零硬件成本) > USB 声卡 > HDMI
    #   - 输入: USB 麦优先 (灵敏度高, 抗噪好) > 板载麦 (零 USB 占用)
    if mode == "auto":
        if direction == "input":
            bus_filter = ["usb", "onboard", "hdmi"]
        else:
            bus_filter = ["onboard", "usb", "hdmi"]
    elif mode == "usb":
        bus_filter = ["usb"]
    elif mode == "onboard":
        bus_filter = ["onboard"]
    elif mode == "hdmi":
        bus_filter = ["hdmi"]
    else:
        return None

    if mode in ("usb", "auto", "onboard", "hdmi"):
        devs = list_devices()
        for bus in bus_filter:
            for d in devs:
                if d["bus"] == bus and d["kind"] in (direction, "duplex"):
                    return d["index"]

    # 4) fallback: None (用 ALSA default)
    return None
