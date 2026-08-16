#!/usr/bin/env bash
# DuraTech 看板系统 - 每日备份脚本
# 打包关键数据目录到 /root/backups，保留最近 30 天
# 建议 cron: 0 3 * * * bash /workspace/sellersprite-automation/deploy/backup.sh
set -e

PROJ="/workspace/sellersprite-automation"
BACKUP_DIR="/root/backups"
KEEP_DAYS=30
STAMP="$(date +%Y%m%d_%H%M%S)"
TARBALL="${BACKUP_DIR}/duratech_backup_${STAMP}.tar.gz"

mkdir -p "${BACKUP_DIR}"

# 打包关键数据（不含代码与日志噪音）
tar -czf "${TARBALL}" \
    -C /workspace \
    sellersprite-automation/output \
    sellersprite-automation/sessions/cookies.json \
    sellersprite-automation/web/board.db \
    progress_backup.json \
    2>/dev/null || true

# 单独打包 uploads（含已消费归档）
if [ -d /root/uploads ]; then
    tar -czf "${BACKUP_DIR}/duratech_uploads_${STAMP}.tar.gz" -C /root uploads 2>/dev/null || true
fi

# 清理 30 天前的备份
find "${BACKUP_DIR}" -name "duratech_*_*.tar.gz" -mtime +"${KEEP_DAYS}" -delete 2>/dev/null || true

echo "[OK] 备份完成: ${TARBALL}（保留 ${KEEP_DAYS} 天）"
echo "     如需异地容灾，请将 ${BACKUP_DIR} 同步到对象存储 COS。"
