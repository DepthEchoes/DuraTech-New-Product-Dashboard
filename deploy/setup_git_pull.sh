#!/bin/bash
# ============================================================
# DuraTech 看板 - 服务器一次性「转正」为 git 克隆
# 用途：让服务器项目从 GitHub 拉取更新（之后用 update.sh）
# 运行：在服务器上 bash setup_git_pull.sh
# 前置：已在 GitHub 上传纯代码版（duratech-code-only.tar.gz）
# ============================================================
set -e

REPO="git@github.com:DepthEchoes/DuraTech-New-Product-Dashboard.git"
PROJ="/workspace/sellersprite-automation"
BACKUP="/tmp/dt_data_$(date +%s)"

echo "== 1. 安装 git =="
apt-get update -y && apt-get install -y git

echo "== 2. 生成 SSH 部署密钥（只读拉取用）=="
if [ ! -f /root/.ssh/id_ed25519 ]; then
  ssh-keygen -t ed25519 -C "poolboard" -f /root/.ssh/id_ed25519 -N ""
fi
# 让 git 对 github.com 使用 SSH（避免 HTTPS 反复要密码）
git config --global url."git@github.com:".insteadOf "https://github.com/"
echo ""
echo ">>> 把下面的公钥加到 GitHub 仓库:"
echo "    Settings → Deploy keys → Add deploy key（只读即可，不用勾 Allow write）"
echo "===== 公钥开始 ====="
cat /root/.ssh/id_ed25519.pub
echo "===== 公钥结束 ====="
read -p "添加完成后按回车继续..."

echo "== 3. 备份服务器本地数据（不被 git 管理）=="
mkdir -p "$BACKUP"
cp -r "$PROJ/output"  "$BACKUP"/ 2>/dev/null || true
cp "$PROJ/board.db"   "$BACKUP"/ 2>/dev/null || true
cp -r "$PROJ/sessions" "$BACKUP"/ 2>/dev/null || true

echo "== 4. 重新克隆为 git 仓库 =="
cd /workspace
mv "$PROJ" "${PROJ}_old_$(date +%s)"
git clone "$REPO" "$PROJ"

echo "== 5. 取消数据文件跟踪（关键：防止 git pull 覆盖采集数据）=="
cd "$PROJ"
git rm -r --cached output board.db sessions logs 2>/dev/null || true
git commit -m "chore: untrack local data (server-side)" 2>/dev/null || true

echo "== 6. 恢复本地数据 =="
cp -r "$BACKUP/output/."   "$PROJ/output/"   2>/dev/null || true
cp "$BACKUP/board.db"       "$PROJ/"          2>/dev/null || true
cp -r "$BACKUP/sessions/." "$PROJ/sessions/" 2>/dev/null || true

echo "== 7. 重启服务 =="
systemctl restart poolboard
sleep 2
systemctl status poolboard --no-pager | head -3
echo ""
echo "✅ 服务器已转为 git 克隆。以后更新只需: bash update.sh"
