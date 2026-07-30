# Orange Pi Zero3 智能语音音乐播放器 — 实施计划

## Context（背景）

用户希望基于 Orange Pi Zero3（全志 H618 / 4×A53 @ 1.5GHz / 1-4GB LPDDR4 / 3×USB2.0 / 千兆网 / WiFi 5 / Ubuntu 22.04/20.04）打造一台"插电即可用"的智能语音音乐播放器：

- 通过外接麦克风（13Pin 板载麦 / USB 麦 二选一）接收中文语音指令
- 通过 13Pin 板载耳机口 / USB 声卡/USB 音箱 播放音乐
- 通过浏览器管理音乐源（**无需登录**），添加/修改/删除本地目录 / 网络电台 / 播放列表 / 在线 API（GD 音乐台）
- 说出关键词即播放指定音乐源
- 开机自启，长期常驻

由于 H618 的 Cortex-A53 性能有限（A53 浮点弱），必须采用轻量级方案。Orange Pi Zero3 官方规格: 13Pin 排针支持 **2 路音频输出 + 1 路音频输入**（H618 内置 codec 直接驱动，零硬件成本）+ 2×USB 2.0 焊盘；物理 USB-A 仅 1 个，Type-C 仅电源（5V/3A）。推荐 13Pin 全套方案 (13Pin 板载麦 + 13Pin 耳机口 + USB-A 留空)。工作目录 `c:\Users\cyber\Desktop\Orange Pi Zero3 Music` 当前为空，本计划从零开始交付完整项目。

**用户已确认的关键决策**：

| 决策点 | 选择 |
| --- | --- |
| 实施范围 | 完整方案（Web + STT + 唤醒词 + TTS + systemd） |
| 唤醒方案 | openWakeWord + Vosk grammar 双引擎可切换 |
| 内存优化 | 1GB 也能跑（关 openWakeWord 时仅约 180MB） |
| STT | Vosk 中文小模型（42MB，完全离线） |
| TTS | piper（zh_CN-huayan-x_low，1GB 友好） |
| Web 鉴权 | 无（按用户要求，文档强提示仅绑定局域网） |

---

## 1. 整体架构

单进程多线程 + asyncio 协程混合模型：

```
硬件层 ── 麦克风: 13Pin 板载麦 (H618 codec 内置 ADC) / USB 麦 (二选一)
        + 输出: 13Pin 3.5mm 耳机口 (H618 codec 内置 DAC) / USB 音箱 (二选一)
        + 总 USB 2.0 = 3 (1 物理座 + 2 焊盘)
        └─ ALSA (snd-usb-audio + sndh618/H616Audio/audiocodec) ─┐
                                 │
应用层 ───────────────────────────┼─────────────────────
  音频采集线程 (sounddevice 16kHz mono)
        ↓ ring buffer
  唤醒词检测 (openWakeWord / Vosk grammar)
        ↓ 命中
  STT 识别 (Vosk cn-small, 5s 滑窗)
        ↓ final 文本
  指令匹配 (关键词 + pypinyin 兜底)
        ↓ Command(action, target)
  播放器控制 (mpg123 -R / cvlc fallback)
        ↓
  TTS 反馈 (piper / espeak-ng 回退)
  Web 后端 (FastAPI :8080, 局域网)

持久化层 ── config/config.json + config/sources.json (fcntl 文件锁)
服务层   ── systemd (music-player.service, Type=notify, WatchdogSec=30)
```

---

## 2. 技术选型（已定）

| 模块 | 选型 | 1GB 模式开关 |
| --- | --- | --- |
| STT | Vosk small-cn (42MB) | 默认 |
| TTS | piper `zh_CN-huayan-x_low` (8MB) | 默认 |
| 唤醒词 | openWakeWord + Vosk grammar | 关 openWakeWord |
| 播放器 | mpg123 + mpc (mp3/电台) → cvlc (flac/m4a) | 自动 |
| Web | FastAPI + uvicorn 单 worker | — |
| 配置 | JSON + fcntl 区域锁 | — |
| 服务 | systemd `Type=notify` | — |
| 拼音兜底 | pypinyin（0 内存常驻） | 默认开启 |
| 模糊匹配 | rapidfuzz | **1GB 模式关闭** |

---

## 3. 目录结构

```
Orange Pi Zero3 Music/
├── README.md                          # 用户手册
├── install.sh                         # 一键安装
├── uninstall.sh
├── requirements.txt
├── .gitignore
├── .env.example
├── config/
│   ├── config.json                    # 全局配置
│   └── sources.json                   # 音乐源（运行时）
├── data/                              # 运行时数据
│   ├── state.json
│   ├── tts_cache/
│   ├── stt_models/vosk-cn-small/
│   ├── tts_models/                    # piper .onnx
│   └── wakeword_models/
├── logs/
│   └── music-player.log
├── web/
│   ├── index.html                     # 单页 SPA
│   └── static/
│       ├── css/app.css
│       ├── js/app.js
│       └── img/logo.svg
├── app/
│   ├── __init__.py
│   ├── main.py                        # 入口：装配 + asyncio
│   ├── config.py                      # 配置加载/校验
│   ├── logger.py                      # 日志（按天滚动 10MB×5）
│   ├── constants.py
│   ├── shutdown.py
│   ├── audio/
│   │   ├── devices.py                 # ALSA 设备枚举
│   │   ├── capture.py                 # sounddevice + ring buffer
│   │   └── tts.py                     # piper/espeak 适配 + 缓存
│   ├── voice/
│   │   ├── listener.py                # 监听主循环
│   │   ├── wakeword.py                # openWakeWord / Vosk grammar 适配
│   │   ├── stt.py                     # Vosk Recognizer 封装
│   │   └── matcher.py                 # 意图分类 + 关键词匹配
│   ├── sources/
│   │   ├── models.py                  # MusicSource dataclass
│   │   ├── manager.py                 # CRUD + 文件锁
│   │   ├── local.py                   # 本地目录扫描
│   │   ├── stream.py                  # HTTP 流 + ICY
│   │   └── playlist.py                # M3U/PLS 解析
│   ├── player/
│   │   ├── base.py                    # PlayerBackend 抽象
│   │   ├── mpg123_backend.py          # mpg123 -R 子进程
│   │   ├── vlc_backend.py             # cvlc RC 接口
│   │   ├── queue.py                   # asyncio.Queue
│   │   ├── controller.py              # 主控 + 状态机
│   │   └── fsm.py
│   ├── web/
│   │   ├── server.py                  # FastAPI app
│   │   ├── api.py                     # 路由
│   │   └── schemas.py                 # Pydantic
│   ├── utils/
│   │   ├── filelock.py
│   │   ├── ids.py
│   │   ├── hotreload.py
│   │   └── systemd_notify.py
│   └── ipc/
│       └── bridge.py                  # 内部事件总线
├── systemd/
│   └── music-player.service
├── scripts/
│   ├── download_models.py             # 断点续传下载模型
│   ├── setup_alsa.sh                  # /etc/asound.conf
│   ├── test_audio.py                  # 录音→回放自检
│   └── make_wakeword.py               # 训练自定义唤醒词
└── tests/
    ├── test_matcher.py
    ├── test_sources.py
    ├── test_api.py
    └── test_player.py
```

---

## 4. 数据模型

`MusicSource`：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | string (8位 base32) | 是 | URL 友好 |
| `name` | string ≤64 | 是 | 展示名 / 默认主关键词 |
| `type` | `local` \| `stream` \| `playlist` | 是 | |
| `target` | string | 是 | 目录路径 / HTTP URL / M3U 路径或 URL |
| `keywords` | list[string] ≥1 | 是 | 主匹配词 |
| `description` | string ≤256 | 否 | |
| `enabled` | bool | 是 | 默认 true |
| `recursive` | bool | local 有效 | 是否递归 |
| `format_filter` | list[string] | 否 | 默认 mp3,wav,flac,m4a,ogg |
| `shuffle` | bool | 否 | 是否随机播放 |
| `created_at` | ISO8601 | 是 | |
| `updated_at` | ISO8601 | 是 | |

---

## 5. REST API（统一响应 `{code, msg, data}`）

| 方法 | 路径 | 描述 |
| --- | --- | --- |
| GET | `/api/sources` | 列出全部 |
| GET | `/api/sources/{id}` | 单个详情 |
| POST | `/api/sources` | 新增 |
| PUT | `/api/sources/{id}` | 修改 |
| DELETE | `/api/sources/{id}` | 删除 |
| POST | `/api/sources/{id}/rescan` | 重新扫描本地索引 |
| POST | `/api/player/play/{id}` | 播放指定源 |
| POST | `/api/player/play` | 恢复 |
| POST | `/api/player/pause` | 暂停 |
| POST | `/api/player/stop` | 停止 |
| POST | `/api/player/next` | 下一首 |
| POST | `/api/player/prev` | 上一首 |
| POST | `/api/player/volume` | 设置音量 `{"value": 0-100}` |
| GET | `/api/status` | 综合状态 |
| GET | `/api/logs?lines=200` | 最近日志 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/audio/devices` | 列出 ALSA 设备 |

**错误码**：1001 参数错误 / 1002 不存在 / 1003 已存在 / 1004 播放器忙 / 1005 音频设备不可用 / 1500 内部错误。

---

## 6. 关键文件（实施重点）

实施时按以下顺序创建与迭代（这是项目骨架的核心入口，便于后续填充）：

| 路径 | 角色 |
| --- | --- |
| [main.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/app/main.py) | 应用入口，组装子系统、启动 asyncio |
| [app/config.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/app/config.py) | 加载 config.json + 内存 profile 切换 |
| [app/voice/listener.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/app/voice/listener.py) | 唤醒→STT→matcher 编排 |
| [app/voice/matcher.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/app/voice/matcher.py) | 关键词匹配 + pypinyin 兜底 |
| [app/player/controller.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/app/player/controller.py) | 播放状态机 |
| [app/player/mpg123_backend.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/app/player/mpg123_backend.py) | mpg123 -R 子进程 |
| [app/sources/manager.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/app/sources/manager.py) | CRUD + 文件锁 + 热加载 |
| [app/web/api.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/app/web/api.py) | REST 路由 |
| [web/index.html](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/web/index.html) | 单页前端 |
| [systemd/music-player.service](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/systemd/music-player.service) | 自启 + watchdog |
| [install.sh](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/install.sh) | 一键安装 |
| [scripts/setup_alsa.sh](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/scripts/setup_alsa.sh) | 生成 /etc/asound.conf |
| [scripts/download_models.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/scripts/download_models.py) | 下载 Vosk + piper 模型 |

---

## 7. 部署步骤

### 7.1 系统依赖（apt）

```bash
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-pip python3-dev \
  build-essential cmake git curl wget \
  alsa-utils pulseaudio-utils \
  mpg123 mpc vlc-bin ffmpeg sox \
  libasound2-dev libportaudio2 portaudio19-dev \
  libsndfile1 udev avahi-daemon
```

### 7.2 Python 依赖（requirements.txt）

```
vosk==0.3.45
sounddevice==0.4.7
numpy==1.26.4
onnxruntime==1.17.1
piper-tts==1.3.0
fastapi==0.111.0
uvicorn[standard]==0.30.1
pydantic==2.7.4
pypinyin==0.51.0
openwakeword==0.6.0
psutil==5.9.8
watchfiles==0.21.0
aiofiles==23.2.1
```

### 7.3 模型下载

- Vosk small-cn: `https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip` → `data/stt_models/vosk-cn-small/`
- piper `zh_CN-huayan-x_low.onnx` + `.onnx.json` → `data/tts_models/`

### 7.4 ALSA / Udev

- `/etc/asound.conf`：默认输出优先 13Pin 板载 codec (`sndh618`/`H616Audio`/`audiocodec`)，其次 USB 声卡；mic 默认 USB 麦，备选 13Pin 板载麦
- `/etc/udev/rules.d/99-usb-audio.rules`：固定 by-id 设备名
- `scripts/setup_alsa.sh` 支持 `OUTPUT_MODE/INPUT_MODE` 环境变量切换 (auto/onboard/usb/hdmi/hw:X,Y)
- **音频方案 3 选 1**:
  - **方案 A (推荐, 1GB)**: 13Pin 板载麦 + 13Pin 板载耳机口 — 零 USB 占用，需焊 13Pin 排针
  - **方案 B (最简)**: USB 麦 + USB 音箱 — 需 USB Hub，无需焊接
  - **方案 C (混合)**: 13Pin 板载麦 + USB 音箱 — 需焊 13Pin MIC 口
- **电源**: Type-C **5V/3A** 必备（2A 不够）

### 7.5 systemd

`Type=notify` + `WatchdogSec=30` + `Restart=always` + `ProtectSystem=strict` + `ReadWritePaths=/opt/music-player/{data,logs,config}` + `SupplementaryGroups=audio pulse`

### 7.6 install.sh 流程

1. 检测 sudo
2. apt 装系统包
3. 创建 `music` 用户并加入 `audio` 组
4. `/opt/music-player` 目录 + 复制项目
5. venv + pip install
6. 下载模型（断点续传，可 --skip）
7. 生成 asound.conf + udev 规则
8. 安装 service 并 `enable --now`
9. 输出局域网访问 URL

---

## 8. 实施阶段（4 阶段交付）

| 阶段 | 交付物 | 验收 |
| --- | --- | --- |
| **P1: 基础设施** | 目录结构、config.py、logger、配置 + sources.json、asound.conf、systemd | `systemctl status music-player` active；无语音 |
| **P2: Web + 播放器** | FastAPI + 全部 API、mpg123_backend、controller、index.html 单页 | Web 添加音乐源并点播出声 |
| **P3: 语音链路** | audio/capture、vosk stt、matcher、TTS 反馈、listener 编排 | 说"播放流行"命中并播放 |
| **P4: 唤醒词 + 健壮性** | openWakeWord + Vosk grammar 双引擎、udev、watchdog、1GB 内存 profile | 唤醒词 1m 内 95% 命中；1GB 板子 RSS < 200MB |

---

## 9. 验证测试方案

### 9.1 硬件/驱动

- `arecord -l` / `aplay -l` 确认 USB 设备
- `arecord -D mic -d 5 -f S16_LE -r 16000 -c 1 test.wav && aplay test.wav` 录播自检

### 9.2 单元（pytest）

- `test_matcher.py`：30+ 指令覆盖
- `test_sources.py`：CRUD + 10 线程并发文件锁
- `test_api.py`：FastAPI TestClient 全部路由

### 9.3 端到端

| 用例 | 步骤 | 预期 |
| --- | --- | --- |
| 唤醒 | 2m 内说"你好小音" | TTS 回复"我在" + 日志命中 |
| 播本地 | "播放流行轻音乐" | 切换 USB 声卡出声 |
| 播电台 | "播放电台" | mpg123 接流，5s 内出声 |
| 暂停/音量 | "暂停" / "音量 80" | 即时响应 |
| 新增源 | Web 添加 | sources.json 自动加载 |
| 重启 | `systemctl restart music-player` | 状态恢复 |
| 1GB 内存 | 长期运行 1h | RSS < 200MB（关闭 openWakeWord） |

### 9.4 性能基线

- 闲置 CPU < 8%
- 唤醒态 CPU < 25%
- 播 mp3 CPU < 5%
- 启动到可用 < 12s

---

## 10. 风险与缓解

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| 1GB 内存吃紧 | 高 | 内存 profile 自动关 openWakeWord + rapidfuzz；piper x_low；默认仅 mp3 |
| USB 设备 index 漂移 | 高 | Udev by-id 固定；启动时按 name 解析重写 config |
| Vosk 中文识别率 | 中 | 启动加载 hotwords.txt 提升关键术语 |
| 中文唤醒词样本不足 | 中 | 双引擎：openWakeWord 训练样本 + Vosk grammar 兜底 |
| Web 无认证暴露 | 中 | 文档强提示仅绑定局域网；提供可选 BasicAuth 中间件 |
| mpg123 不支持 flac/m4a | 中 | `backend=auto` 自动切 cvlc |
| TTS 与播放互斥 | 中 | 互斥锁 + 短暂 fade 暂停 |
| sources.json 损坏 | 中 | 启动校验 JSON，损坏备份 `.corrupt` + 加载空列表 |
| 敏感字样 | — | 代码/文档/UI 全面规避 ads/ad |

---

## 11. 实施步骤（即将执行的代码工作）

按以下顺序在 `c:\Users\cyber\Desktop\Orange Pi Zero3 Music` 下产出文件（**注：以下为开发机的源码文件，最终通过 install.sh 部署到 Orange Pi 上的 /opt/music-player**）：

1. **基础设施**
   - 目录骨架 + `.gitignore` + `requirements.txt` + `README.md`
   - `config/config.json` 样例（含 1GB/2GB profile 切换开关）
   - `config/sources.json` 初始样例
   - `app/logger.py`、`app/config.py`、`app/constants.py`
   - `app/utils/{filelock,ids,hotreload,systemd_notify}.py`
   - `app/ipc/bridge.py`

2. **音频层**
   - `app/audio/devices.py`（解析 arecord/aplay）
   - `app/audio/capture.py`（sounddevice + ring buffer）
   - `app/audio/tts.py`（piper + 缓存）

3. **语音层**
   - `app/voice/wakeword.py`（openWakeWord + Vosk grammar 适配）
   - `app/voice/stt.py`（Vosk Recognizer）
   - `app/voice/matcher.py`（关键词 + pypinyin 评分）
   - `app/voice/listener.py`（主循环）

4. **音乐源层**
   - `app/sources/models.py`（Pydantic）
   - `app/sources/local.py`（目录扫描）
   - `app/sources/stream.py`（HTTP/ICY）
   - `app/sources/playlist.py`（M3U/PLS）
   - `app/sources/manager.py`（CRUD + 文件锁 + 热加载）

5. **播放器层**
   - `app/player/base.py`、`fsm.py`、`queue.py`
   - `app/player/mpg123_backend.py`、`vlc_backend.py`
   - `app/player/controller.py`

6. **Web 层**
   - `app/web/{server,api,schemas}.py`
   - `web/index.html` + `web/static/{css/app.css,js/app.js,img/logo.svg}`

7. **入口与部署**
   - `app/main.py`
   - `systemd/music-player.service`
   - `install.sh` / `uninstall.sh`
   - `scripts/{download_models,setup_alsa,test_audio,make_wakeword}.py`

8. **测试**
   - `tests/{test_matcher,test_sources,test_api,test_player}.py`

---

## 12. 验证方式（端到端）

实施完成后在开发机上做静态校验；在 Orange Pi 上做运行时验证：

1. `python -m pytest tests/ -v` — 单元测试全绿
2. `python -m app.main --check` — 配置/模型自检（无需音频设备）
3. Orange Pi 部署后：
   - `arecord -l` / `aplay -l` 识别 USB 设备
   - `systemctl status music-player` active
   - 浏览器访问 `http://<opi-ip>:8080` 打开 Web，新增/删除音乐源
   - 点播 → 喇叭出声
   - 说"你好小音" → TTS 回复
   - 说"播放 <关键词>" → 命中播放
4. `journalctl -u music-player -f` 观察日志
5. `free -m` 验证 1GB 模式 RSS < 200MB

---

## 关键文件入口（实施时优先关注）

- [main.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/app/main.py) — 装配入口
- [config.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/app/config.py) — 配置与内存 profile
- [listener.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/app/voice/listener.py) — 语音主循环
- [matcher.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/app/voice/matcher.py) — 指令匹配
- [controller.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/app/player/controller.py) — 播放状态机
- [api.py](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/app/web/api.py) — REST 路由
- [index.html](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/web/index.html) — Web UI
- [install.sh](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/install.sh) — 一键部署
- [music-player.service](file:///c:/Users/cyber/Desktop/Orange%20Pi%20Zero3%20Music/systemd/music-player.service) — systemd unit
