#!/usr/bin/env bash
# OPI Music Player 卸载脚本
# 运行: sudo ./uninstall.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "请使用 sudo 运行: sudo $0"
  exit 1
fi

echo "==> 停止并禁用服务"
systemctl stop music-player.service 2>/dev/null || true
systemctl disable music-player.service 2>/dev/null || true

echo "==> 删除 service 文件"
rm -f /etc/systemd/system/music-player.service
systemctl daemon-reload

echo "==> 询问是否删除 /opt/music-player"
read -rp "删除 /opt/music-player 及其所有数据? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
  rm -rf /opt/music-player
  echo "已删除 /opt/music-player"
else
  echo "已保留 /opt/music-player (可手动删除)"
fi

echo "==> 询问是否删除 music 用户"
read -rp "删除用户 music? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
  userdel music 2>/dev/null || true
  echo "已删除用户 music"
fi

echo "==> 卸载完成"
