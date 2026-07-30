#!/usr/bin/env bash
# OPI Music Player 一键安装脚本
# 运行: sudo ./install.sh
# 可选: --skip-models (跳过模型下载), --dev (开发模式不部署到 /opt)

set -euo pipefail

# ────── 参数 ──────
SKIP_MODELS=0
DEV_MODE=0
for arg in "$@"; do
  case "$arg" in
    --skip-models) SKIP_MODELS=1 ;;
    --dev) DEV_MODE=1 ;;
    -h|--help)
      echo "Usage: sudo ./install.sh [--skip-models] [--dev]"
      exit 0
      ;;
  esac
done

# ────── 路径 ──────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ $DEV_MODE -eq 1 ]]; then
  INSTALL_DIR="$SCRIPT_DIR"
  SERVICE_FILE="$SCRIPT_DIR/systemd/music-player.service"
  USER_NAME="$(whoami)"
else
  INSTALL_DIR="/opt/music-player"
  SERVICE_FILE="/etc/systemd/system/music-player.service"
  USER_NAME="music"
fi

# ────── 权限检查 ──────
if [[ $EUID -ne 0 ]]; then
  echo "请使用 sudo 运行: sudo $0"
  exit 1
fi

# ────── 1) 系统依赖 ──────
echo "==> 1) 安装系统依赖"
apt-get update
apt-get install -y \
  python3 python3-venv python3-pip python3-dev \
  build-essential cmake git curl wget \
  alsa-utils pulseaudio-utils \
  mpg123 vlc-bin ffmpeg sox \
  libasound2-dev libportaudio2 portaudio19-dev \
  libsndfile1 udev avahi-daemon \
  espeak-ng

# ────── 2) 用户 ──────
if [[ $DEV_MODE -eq 0 ]]; then
  if ! id "$USER_NAME" &>/dev/null; then
    echo "==> 2) 创建用户 $USER_NAME"
    useradd -r -s /bin/false -G audio "$USER_NAME"
  else
    echo "==> 2) 用户 $USER_NAME 已存在, 加入 audio 组"
    usermod -aG audio "$USER_NAME"
  fi
fi

# ────── 3) 部署 ──────
if [[ $DEV_MODE -eq 0 ]]; then
  echo "==> 3) 部署到 $INSTALL_DIR"
  mkdir -p "$INSTALL_DIR"
  rsync -a --delete \
    --exclude=venv --exclude=__pycache__ --exclude=.git \
    --exclude=data/stt_models --exclude=data/tts_models \
    --exclude=data/wakeword_models --exclude=data/tts_cache \
    --exclude=logs --exclude='*.pyc' --exclude='.pytest_cache' \
    "$SCRIPT_DIR/" "$INSTALL_DIR/"

  chown -R "$USER_NAME:$USER_NAME" "$INSTALL_DIR"
  mkdir -p "$INSTALL_DIR"/{data/stt_models,data/tts_models,data/wakeword_models,data/tts_cache,logs}
  chown -R "$USER_NAME:$USER_NAME" "$INSTALL_DIR"/{data,logs}
fi

# ────── 4) Python venv ──────
echo "==> 4) 创建 Python venv"
sudo -u "$USER_NAME" python3 -m venv "$INSTALL_DIR/venv" 2>/dev/null || \
  python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip wheel setuptools
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# ────── 5) 模型下载 ──────
if [[ $SKIP_MODELS -eq 0 ]]; then
  echo "==> 5) 下载模型 (Vosk 中文 + piper 中文)"
  sudo -u "$USER_NAME" "$INSTALL_DIR/venv/bin/python" \
    "$INSTALL_DIR/scripts/download_models.py" || true
else
  echo "==> 5) 跳过模型下载 (--skip-models)"
fi

# ────── 6) ALSA / udev ──────
if [[ $DEV_MODE -eq 0 ]]; then
  echo "==> 6) 生成 /etc/asound.conf + udev 规则"
  bash "$INSTALL_DIR/scripts/setup_alsa.sh"
fi

# ────── 7) systemd ──────
if [[ $DEV_MODE -eq 0 ]]; then
  echo "==> 7) 安装 systemd service"
  cp "$SCRIPT_DIR/systemd/music-player.service" "$SERVICE_FILE"
  systemctl daemon-reload
  systemctl enable music-player.service
  systemctl restart music-player.service || true
fi

# ────── 完成 ──────
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ""
echo "==================================================================="
echo "  安装完成"
echo "==================================================================="
echo "  访问地址:    http://${IP:-<opi-ip>}:8080"
echo "  服务状态:    sudo systemctl status music-player"
echo "  实时日志:    sudo journalctl -u music-player -f"
echo "  配置文件:    $INSTALL_DIR/config/config.json"
echo "  音乐源:      $INSTALL_DIR/config/sources.json"
echo "==================================================================="
echo "  卸载:        sudo $SCRIPT_DIR/uninstall.sh"
echo "==================================================================="
