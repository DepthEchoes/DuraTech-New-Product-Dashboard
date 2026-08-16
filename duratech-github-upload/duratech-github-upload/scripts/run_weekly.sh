#!/bin/bash
# DuraTech 周度采集工作流 - 一键执行
# 用法: bash run_weekly.sh [cookies.json路径]
#   不传参数则使用默认 sessions/cookies.json
set -e
cd "$(dirname "$0")"

COOKIE="${1:-sessions/cookies.json}"
echo "════════════════════════════════════════════════"
echo "  DuraTech 周度采集工作流"
echo "  Cookie: $COOKIE"
echo "════════════════════════════════════════════════"

echo ""
echo "📡 步骤 1/4: 采集新品池 + 爆品池..."
python3 weekly_collect.py "$COOKIE"

echo ""
echo "🔍 步骤 2/4: 对比上周数据，去重..."
python3 weekly_diff.py

echo ""
echo "📋 步骤 3/4: 生成需求池看板..."
python3 pool_builder.py

echo ""
echo "📊 步骤 4/4: 更新产品追踪看板..."
python3 dashboard_builder.py

echo ""
echo "════════════════════════════════════════════════"
echo "  ✅ 全部完成!"
echo "  需求池看板: /workspace/DuraTech_需求池看板.html"
echo "  追踪看板:   /workspace/DuraTech_产品追踪看板.html"
echo "════════════════════════════════════════════════"
