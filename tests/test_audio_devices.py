"""ALSA 设备检测单元测试 (devices.py).

在 Windows 上无 arecord/aplay, 用 mock subprocess 跑.
"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.audio import devices  # noqa: E402

# 典型 aplay -l / arecord -l 输出样本
# 参考 Orange Pi Zero3 Ubuntu 22.04 实际设备名
# 实际情况: codec 和 HDMI 可能在同一 card (sndh618) 也可能分两个
# 这里用分开的 card 模拟, 更稳定
SAMPLE_APLAY = """\
**** List of PLAYBACK Hardware Devices ****
card 0: H616Audio [H616Audio], device 0: 1c22800.i2s-i2s-hifi-0 []
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 1: sndhdmi [sndhdmi], device 0: HDMI PCM [HDMI PCM]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 2: Device [USB Audio Device], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""

SAMPLE_ARECORD = """\
**** List of CAPTURE Hardware Devices ****
card 0: H616Audio [H616Audio], device 0: 1c22800.i2s-i2s-hifi-0 []
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 2: Device [USB Audio Device], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""


def _mock_subprocess(*args, **kwargs):
    """mock subprocess.check_output: 直接返回字符串."""
    cmd = args[0]
    if cmd[0] == "aplay":
        return SAMPLE_APLAY
    if cmd[0] == "arecord":
        return SAMPLE_ARECORD
    return ""


def test_infer_bus():
    # 板载 codec (典型 H618 名)
    assert devices._infer_bus("H616Audio", "1c22800.i2s-i2s-hifi-0") == "onboard"
    assert devices._infer_bus("audiocodec", "snd-sunxi-codec") == "onboard"
    assert devices._infer_bus("sndh618", "CDC PCM Codec-0") == "onboard"
    # USB
    assert devices._infer_bus("Device", "USB Audio") == "usb"
    # HDMI
    assert devices._infer_bus("sndhdmi", "HDMI PCM") == "hdmi"
    assert devices._infer_bus("sndhdmi", "hdmi") == "hdmi"
    # 未知
    assert devices._infer_bus("mystery", "weird") == "unknown"


def test_list_devices():
    with patch.object(devices.shutil, "which", return_value="/usr/bin/aplay"), \
         patch.object(devices.subprocess, "check_output", side_effect=_mock_subprocess):
        devs = devices.list_devices()
    assert isinstance(devs, list)
    by_idx = {d["index"]: d for d in devs}
    # H616Audio codec - onboard, duplex (出现在 input 和 output)
    assert "hw:0,0" in by_idx
    assert by_idx["hw:0,0"]["bus"] == "onboard"
    assert by_idx["hw:0,0"]["kind"] == "duplex"
    # sndhdmi - hdmi, output only
    assert "hw:1,0" in by_idx
    assert by_idx["hw:1,0"]["bus"] == "hdmi"
    assert by_idx["hw:1,0"]["kind"] == "output"
    # USB Audio - usb, duplex
    assert "hw:2,0" in by_idx
    assert by_idx["hw:2,0"]["bus"] == "usb"
    assert by_idx["hw:2,0"]["kind"] == "duplex"


def test_find_usb_audio():
    with patch.object(devices.shutil, "which", return_value="/usr/bin/aplay"), \
         patch.object(devices.subprocess, "check_output", side_effect=_mock_subprocess):
        r = devices.find_usb_audio()
    assert r["input"] == "hw:2,0"
    assert r["output"] == "hw:2,0"


def test_find_onboard_audio():
    with patch.object(devices.shutil, "which", return_value="/usr/bin/aplay"), \
         patch.object(devices.subprocess, "check_output", side_effect=_mock_subprocess):
        r = devices.find_onboard_audio()
    assert r["input"] == "hw:0,0"
    assert r["output"] == "hw:0,0"


def test_find_onboard_mic():
    """13Pin 板载麦 (H618 codec ADC) 应能独立获取."""
    with patch.object(devices.shutil, "which", return_value="/usr/bin/aplay"), \
         patch.object(devices.subprocess, "check_output", side_effect=_mock_subprocess):
        r = devices.find_onboard_mic()
    assert r == "hw:0,0"


def test_resolve_input_onboard():
    """input_mode=onboard 应该用 13Pin 板载麦."""
    with patch.object(devices.shutil, "which", return_value="/usr/bin/aplay"), \
         patch.object(devices.subprocess, "check_output", side_effect=_mock_subprocess):
        r = devices.resolve_audio_device(None, mode="onboard", direction="input")
    assert r == "hw:0,0"


def test_resolve_input_usb():
    """input_mode=usb 应该用 USB 麦."""
    with patch.object(devices.shutil, "which", return_value="/usr/bin/aplay"), \
         patch.object(devices.subprocess, "check_output", side_effect=_mock_subprocess):
        r = devices.resolve_audio_device(None, mode="usb", direction="input")
    assert r == "hw:2,0"


def test_resolve_input_auto_prefers_usb():
    """input_mode=auto 应该优先 USB 麦 (灵敏度高)."""
    with patch.object(devices.shutil, "which", return_value="/usr/bin/aplay"), \
         patch.object(devices.subprocess, "check_output", side_effect=_mock_subprocess):
        r = devices.resolve_audio_device(None, mode="auto", direction="input")
    assert r == "hw:2,0"  # USB 麦优先于板载


def test_resolve_input_no_usb_fallback_onboard():
    """无 USB 麦时, auto 应回退到板载麦."""
    # 构造只有板载麦、没有 USB 麦的场景
    SAMPLE_NO_USB = """\
**** List of PLAYBACK Hardware Devices ****
card 0: H616Audio [H616Audio], device 0: HiFi []
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""
    SAMPLE_NO_USB_REC = """\
**** List of CAPTURE Hardware Devices ****
card 0: H616Audio [H616Audio], device 0: HiFi []
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""
    def mock_no_usb(*args, **kwargs):
        if args[0][0] == "aplay":
            return SAMPLE_NO_USB
        return SAMPLE_NO_USB_REC

    with patch.object(devices.shutil, "which", return_value="/usr/bin/aplay"), \
         patch.object(devices.subprocess, "check_output", side_effect=mock_no_usb):
        r_in = devices.resolve_audio_device(None, mode="auto", direction="input")
    assert r_in == "hw:0,0"  # 回退到板载麦


def test_resolve_explicit_wins():
    """显式 input_device/output_device 优先于 mode."""
    r = devices.resolve_audio_device("hw:3,0", mode="auto", direction="output")
    assert r == "hw:3,0"


def test_resolve_explicit_default_ignored():
    """显式 'default' / 'auto' / '' 视作 None."""
    for v in ("default", "auto", ""):
        with patch.object(devices.shutil, "which", return_value="/usr/bin/aplay"), \
             patch.object(devices.subprocess, "check_output", side_effect=_mock_subprocess):
            r = devices.resolve_audio_device(v, mode="auto", direction="output")
        # mode=auto 应回退到板载 (hw:0,0)
        assert r == "hw:0,0", f"expected hw:0,0 for v={v!r}, got {r}"


def test_resolve_mode_onboard():
    with patch.object(devices.shutil, "which", return_value="/usr/bin/aplay"), \
         patch.object(devices.subprocess, "check_output", side_effect=_mock_subprocess):
        r = devices.resolve_audio_device(None, mode="onboard", direction="output")
    assert r == "hw:0,0"


def test_resolve_mode_usb():
    with patch.object(devices.shutil, "which", return_value="/usr/bin/aplay"), \
         patch.object(devices.subprocess, "check_output", side_effect=_mock_subprocess):
        r = devices.resolve_audio_device(None, mode="usb", direction="output")
    assert r == "hw:2,0"


def test_resolve_mode_hdmi():
    with patch.object(devices.shutil, "which", return_value="/usr/bin/aplay"), \
         patch.object(devices.subprocess, "check_output", side_effect=_mock_subprocess):
        r = devices.resolve_audio_device(None, mode="hdmi", direction="output")
    assert r == "hw:1,0"


def test_resolve_mode_auto_prefers_onboard():
    """auto 模式应该优先选择板载 codec, 而非 USB."""
    with patch.object(devices.shutil, "which", return_value="/usr/bin/aplay"), \
         patch.object(devices.subprocess, "check_output", side_effect=_mock_subprocess):
        r = devices.resolve_audio_device(None, mode="auto", direction="output")
    assert r == "hw:0,0"  # 板载 codec 优先


def test_resolve_mode_hw_direct():
    """mode 本身是 hw:X,Y 时也直接返回."""
    r = devices.resolve_audio_device(None, mode="hw:2,0", direction="output")
    assert r == "hw:2,0"


def test_resolve_mode_unknown_returns_none():
    """未知 mode + 无设备 → None (用 ALSA default)."""
    with patch.object(devices.shutil, "which", return_value=None):
        r = devices.resolve_audio_device(None, mode="bogus", direction="output")
    assert r is None


if __name__ == "__main__":
    import traceback
    funcs = [f for n, f in globals().items() if n.startswith("test_") and callable(f)]
    passed, failed = 0, 0
    for fn in funcs:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {fn.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
