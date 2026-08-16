#!/bin/bash
# ============================================================
# DuraTech 看板 - 一键更新到服务器（在你的 Mac 本机运行）
# 前置：服务器已按 setup_server.sh 部署过一次
# 用法：
#   1) 下载最新的 duratech-deploy.tar.gz 到 ~/Downloads
#   2) 终端运行: bash ~/push_dt.sh
# ============================================================
set -euo pipefail

SERVER="root@116.62.43.110"
PKG="$HOME/Downloads/duratech-deploy.tar.gz"

if [ ! -f "$PKG" ]; then
  echo "❌ 找不到 $PKG"
  echo "   请先把最新的 duratech-deploy.tar.gz 下载到 下载 文件夹"
  exit 1
fi

echo "📤 上传部署包到服务器..."
scp "$PKG" "$SERVER:/root/" || { echo "❌ 上传失败（检查网络/密码）"; exit 1; }

echo "🔧 解包并重启服务..."
ssh "$SERVER" "tar -xzf /root/duratech-deploy.tar.gz -C /workspace && systemctl restart poolboard && sleep 2 && systemctl is-active poolboard && echo '✅ 更新完成'" \
  || { echo "❌ 远程执行失败"; exit 1; }

echo ""
echo "🌐 访问: https://116.62.43.110"
echo "   登录页: https://116.62.43.110/login"
