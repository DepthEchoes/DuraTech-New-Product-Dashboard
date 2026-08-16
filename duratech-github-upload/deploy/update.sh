#!/bin/bash
# ============================================================
# DuraTech 看板 - 服务器日常更新（从 GitHub 拉最新代码 + 重启）
# 用法：ssh 登录服务器后 bash update.sh
# 前置：已运行过 setup_git_pull.sh（项目为 git 克隆）
# ============================================================
set -e
cd /workspace/sellersprite-automation

echo "== 拉取 GitHub 最新代码 =="
git pull

echo "== 重启服务 =="
systemctl restart poolboard
sleep 2
systemctl is-active poolboard && echo "✅ 更新完成" || echo "❌ 服务未启动，请检查 journalctl -u poolboard"
