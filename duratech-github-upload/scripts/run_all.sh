#!/bin/bash
# DURATECH 卖家精灵自动化采集 - 一键运行
# 用法: bash run_all.sh [new|hot|all]
# 默认: all

TYPE="${1:-all}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATE="$(date +%Y-%m-%d)"

collect_and_build() {
    local type="$1"
    echo ""
    echo "=========================================="
    echo "  DURATECH 卖家精灵 - $type 采集"
    echo "=========================================="

    cd "$SCRIPT_DIR"
    python collector.py --type "$type" --max-pages 10

    # 找到最新的 JSON
    local json_file=$(ls -t "$SCRIPT_DIR/../output/raw_data_${type}_"*.json 2>/dev/null | head -1)
    if [ -z "$json_file" ]; then
        echo "[ERROR] 未找到 $type JSON 文件"
        return 1
    fi

    # 生成 HTML 筛选页面（含导出服务端口）
    python html_builder.py --json "$json_file" --type "$type" --port 58900

    # 生成 Excel
    python excel_builder.py --json "$json_file" --type "$type"

    echo "[OK] $type 完成"
}

# 启动导出服务（如果尚未启动）
start_export_server() {
    if ! curl -s http://127.0.0.1:58900/health > /dev/null 2>&1; then
        echo "[启动] 导出服务 (端口 58900)..."
        cd "$SCRIPT_DIR"
        nohup python export_server.py 58900 > /tmp/export_server.log 2>&1 &
        sleep 1
        if curl -s http://127.0.0.1:58900/health > /dev/null 2>&1; then
            echo "[OK] 导出服务已启动"
        else
            echo "[WARN] 导出服务启动失败，HTML 导出功能可能不可用"
        fi
    else
        echo "[OK] 导出服务已在运行"
    fi
}

start_export_server

if [ "$TYPE" = "all" ]; then
    collect_and_build "new"
    collect_and_build "hot"
elif [ "$TYPE" = "new" ] || [ "$TYPE" = "hot" ]; then
    collect_and_build "$TYPE"
else
    echo "用法: bash run_all.sh [new|hot|all]"
fi

echo ""
echo "=========================================="
echo "  完成！文件在 /workspace/"
echo "  - DuraTech 亚马逊新品机会_${DATE}.html"
echo "  - DuraTech 亚马逊新品机会_${DATE}.xlsx"
echo "  - DuraTech 亚马逊爆品机会_${DATE}.html"
echo "  - DuraTech 亚马逊爆品机会_${DATE}.xlsx"
echo ""
echo "  💡 提示: HTML 页面勾选后导出需导出服务运行中"
echo "     启动: python scripts/export_server.py 58900 &"
echo "=========================================="
