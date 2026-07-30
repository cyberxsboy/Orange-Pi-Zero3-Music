# Orange Pi Zero3 智能语音音乐播放器

> 基于 Orange Pi Zero3 (全志 H618 / 4×A53 / Ubuntu 22.04) 的离线优先智能语音音乐播放器
> 外接 USB 麦克风 + USB 声卡（喇叭）即可使用，Web 管理音乐源，无需登录

## 特性

- 🎤 **离线中文语音识别** — Vosk 中文小模型 (42MB)，完全离线
- 🔊 **轻量播放器** — mpg123 (mp3/电台) + cvlc (flac/m4a) 自动切换
- 🌐 **Web 管理界面** — 浏览器访问 `http://<opi-ip>:8080`，免登录增删改音乐源
- 🗣 **双唤醒引擎** — openWakeWord (高精度) + Vosk grammar (零配置)
- 🔁 **开机自启** — systemd `Type=notify` + watchdog
- 💾 **内存友好** — 1GB 版本可运行（关闭 openWakeWord，仅约 180MB RSS）
- 🛠 **音乐源类型** — 本地目录 / 网络电台流 / M3U/PLS 播放列表

## 硬件需求

### Orange Pi Zero3 官方参数

| 项目 | 规格 |
| --- | --- |
| CPU | 全志 H618 四核 Cortex-A53 @ 1.5GHz |
| GPU | Mali G31 MP2 (OpenGL ES 1.0/2.0/3.2, OpenCL 2.0, Vulkan 1.1) |
| 内存 | **1GB / 1.5GB / 2GB / 4GB LPDDR4** |
| 板载存储 | 16MB SPI Flash |
| 电源 | AXP313A，**5V/3A Type-C 输入** |
| 网络 | **千兆以太网 (10/100/1000M)** + WiFi 5 + BT 5.0 |
| **USB 2.0** | **× 3**（1×USB-A 物理座 + 2×13Pin 焊盘） |
| **音频 I/O** | **13Pin 支持 2 路输出 + 1 路输入**（H618 内置 codec） |
| 视频 | Micro HDMI 4K@60fps + TV-Out (CVBS via 13Pin) |
| 其它 | Micro SD 卡槽、3Pin Debug UART、26Pin GPIO、IR |

### 音频接口说明（13Pin 排针 2 出 1 入）

| 信号 | 13Pin 排针功能 | 备注 |
| --- | --- | --- |
| LOUT / ROUT | **音频输出 L/R** | 接 3.5mm 耳机座，H618 codec 内置 DAC |
| MIC | **音频输入** | 接 3.5mm 麦克风（或焊线），H618 codec 内置 ADC |
| USB_DP/DM × 2 | **USB 2.0 × 2** | 焊盘形式，需焊出才能用 |
| TV-OUT | CVBS 视频输出 | 可选 |
| IR | 红外接收 | 可选 |

> **关键**：13Pin 排针的音频 I/O 由 H618 SoC **内置 codec** 直接驱动，**不需要**任何额外 USB 声卡！

### 推荐配置（3 种方案）

**方案 A：13Pin 全套（最省钱，1GB 推荐）**

```
[13Pin 排针]──3.5mm 麦克风──→ 模拟麦头（带 3.5mm 插头的小麦）
[13Pin 排针]──3.5mm 耳机口──→ 有源小音箱（或自备功放）
[USB-A 座]  ──空着（备调试 / U 盘）
```
**总计花费**：13Pin 排针 + 2 个 3.5mm 座 ≈ 10 元，无需任何 USB 音频设备

**方案 B：USB 方案（最简单，无焊接）**

```
[USB-A 座]──USB Hub──→ USB 麦 + USB 音箱 / USB 声卡
```
**总计花费**：USB Hub + USB 麦 + USB 音箱 ≈ 50-100 元

**方案 C：混合（板载麦 + USB 音箱）**

```
[13Pin 排针]──3.5mm 麦克风──→ 模拟麦
[USB-A 座]  ──USB 音箱─────→ 声音输出
```

### 物料清单

| 部件 | 推荐 | 备注 |
| --- | --- | --- |
| 主板 | Orange Pi Zero3 (1/2/4GB) | Ubuntu 22.04 / 20.04 Server |
| 麦克风 | 3.5mm 模拟麦（方案 A/C）/ USB 麦（方案 B） | 方案 A 灵敏度一般，需凑近 |
| 喇叭 | 3.5mm 有源小音箱（自备功放） | 8Ω/0.5W 即可 |
| 13Pin 排针 | 13Pin 1.27mm 或 2.54mm 排针 + 2×3.5mm 耳机座 | 方案 A 需 |
| 电源 | **5V/3A** Type-C | ⚠️ 必须 3A，2A 不够 |
| 存储 | TF 卡 ≥ 16GB Class10 | |
| 网络 | 网线 / WiFi 5 | 首次下载模型需要 |

### 音频配置

编辑 `config/config.json`：

```json
"audio": {
  "output_mode": "auto",       // auto | onboard | usb | hdmi | hw:1,0
  "input_mode":  "auto",       // auto | usb | onboard | hw:1,0
  "output_device": null,        // 留 null 用 mode 推断; 或填 "hw:1,0" 强制
  "input_device":  null
}
```

**输出模式**：
- `auto`（默认）：13Pin 板载耳机口 → USB 声卡 → HDMI
- `onboard`：强制 13Pin 板载耳机口（推荐方案 A）
- `usb`：强制 USB 声卡/USB 音箱
- `hdmi`：HDMI 音频（与 HDMI 视频同口，**不推荐**）
- `hw:X,Y`：直接指定 ALSA 设备

**输入模式**：
- `auto`（默认）：USB 麦 → 13Pin 板载麦
- `usb`：强制 USB 麦克风（推荐，灵敏度高）
- `onboard`：强制 13Pin 板载麦（方案 A，零 USB 占用）
- `hw:X,Y`：直接指定 ALSA 设备

**切换配置**：

```bash
# 方案 A: 13Pin 全套
sudo OUTPUT_MODE=onboard INPUT_MODE=onboard bash scripts/setup_alsa.sh

# 方案 B: 纯 USB
sudo OUTPUT_MODE=usb INPUT_MODE=usb bash scripts/setup_alsa.sh

# 方案 C: 板载麦 + USB 音箱
sudo OUTPUT_MODE=usb INPUT_MODE=onboard bash scripts/setup_alsa.sh
```

## 快速开始

### 1. 在 Orange Pi 上准备系统

```bash
sudo apt update
sudo apt install -y git
git clone <your-repo-url> opi-music-player
cd opi-music-player
```

### 2. 一键安装

```bash
chmod +x install.sh
sudo ./install.sh
```

`install.sh` 会：
1. 安装系统依赖（apt）
2. 创建 `music` 用户并加入 `audio` 组
3. 在 `/opt/music-player` 部署项目
4. 创建 venv 并安装 Python 依赖
5. 下载 Vosk 中文模型 + piper 中文语音（断点续传）
6. 生成 `/etc/asound.conf` 与 udev 规则
7. 注册 systemd service 并 `enable --now`

### 3. 访问

- **Web 管理**：浏览器打开 `http://<opi-ip>:8080`
- **查看状态**：`systemctl status music-player`
- **看日志**：`journalctl -u music-player -f` 或 `tail -f logs/music-player.log`

## 使用方法

### Web 界面

打开 `http://<opi-ip>:8080`：

- **顶部状态条**：当前播放、来源、音量
- **音乐源列表**：所有已添加的源，可启用/禁用、编辑、删除
- **新增音乐源**：
  - 类型 `local`：填写本地目录（如 `/mnt/usb/music/pop`）
  - 类型 `stream`：填写网络流 URL（如 `http://stream.hitfm.cn/live`）
  - 类型 `playlist`：填写 M3U/PLS 路径或 URL
  - **keywords**：用于语音匹配的关键字（至少 1 个）
- **控制按钮**：播放/暂停/下一首/音量

### 语音指令

唤醒后说出包含关键字的指令，例如：

| 语音 | 行为 |
| --- | --- |
| "你好小音" | 唤醒（需配置唤醒词） |
| "播放流行" | 播放名称/关键字包含"流行"的源 |
| "播放电台" | 播放关键字包含"电台"的源 |
| "暂停" / "继续" | 暂停 / 恢复 |
| "下一首" / "上一首" | 切换 |
| "音量八十" | 调节音量 |
| "停止" | 停止播放 |

## 内存档位

通过 `config/config.json` 切换 `memory_profile`：

| Profile | openWakeWord | 模糊匹配 | piper 模型 | 1GB 板 |
| --- | --- | --- | --- | --- |
| `1g` | ❌ 仅 Vosk grammar | ❌ | x_low (8MB) | ✅ 推荐 |
| `2g` | ✅ | ❌ | x_low / medium | ✅ |
| `4g` | ✅ | ✅ | medium (16MB) | ✅ |

## 项目结构

参见 [实施计划](.trae/documents/orange-pi-zero3-voice-music-player.md)。

## 常见问题

**Q: 麦克风没有声音？**
A: 按你的方案选排查步骤：

**方案 A（13Pin 板载麦）**：
1. 13Pin 排针需要先焊 MIC 接口（3.5mm 麦克风座 或 直接焊驻极体麦线）
2. 确认 `arecord -l` 能看到 `sndh618`/`H616Audio` 板载 codec（带 input device）
3. 用 `alsamixer` 选对应卡，**按 F4（Capture）调高麦克风音量**（默认可能被静音）
4. `config.json` 设置 `audio.input_mode` = `onboard`
5. 测试：`arecord -d 3 -f S16_LE -r 16000 -c 1 /tmp/test.wav && aplay /tmp/test.wav`

**方案 B（USB 麦）**：
1. **只有 1 个 USB-A 口** — 如果已插 USB 声卡/USB 音箱，麦克风需要插到 USB Hub 或 13Pin 排针上的 USB
2. `arecord -l` 应该看到 `USB Audio`
3. `config.json` 设置 `audio.input_mode` = `usb` 或 `audio.input_device` = `hw:1,0`
4. 测试同上

**通用排查**：
```bash
# 重新生成 asound.conf
sudo bash scripts/setup_alsa.sh

# 列出所有 ALSA 设备
arecord -l
aplay -l

# 调音量
alsamixer   # F6 选卡, F4 Capture, F3 Playback
```

**Q: 喇叭没声音？**
A:
1. 13Pin 排针上的耳机口需要先焊排针/扩展板 — 默认板子没引出来
2. 确认 `aplay -l` 能看到对应声卡（`sndh618` / `H616Audio` / `USB Audio` 之一）
3. `config.json` 设置 `audio.output_mode` 为 `onboard`（13Pin 耳机口）或 `usb`（USB 音箱）
4. `alsamixer` 检查是否被静音（`MM` 表示静音，按 `M` 解除）

**Q: Web 打不开？**
A: 确认 `systemctl status music-player` 为 active；防火墙放行 8080 端口；查看 `journalctl -u music-player -n 50`。

**Q: 唤醒词不灵敏？**
A: 1GB 模式默认使用 Vosk grammar，灵敏度较低；可调低 `voice.wake_threshold` (0.3-0.5)；或录制 30+ 句样本训练 openWakeWord 自定义唤醒词（运行 `scripts/make_wakeword.py`）。

**Q: 内存占用过高？**
A: 切换到 `1g` 模式；关闭 `enable_fuzzy_match`；确认没有运行 inotify。

## 开发

```bash
# 创建 venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 配置自检（不启动音频）
python -m app.main --check

# 启动（开发模式）
python -m app.main

# 单元测试
python -m pytest tests/ -v
```

## License

MIT
