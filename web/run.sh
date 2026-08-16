#!/bin/bash
# DuraTech 看板 Web 版启动脚本
# 用法: ./run.sh  (开发)  或  ./run.sh prod  (生产 gunicorn)
set -e
cd "$(dirname "$0")"
export PYTHONUNBUFFERED=1

if [ "$1" == "prod" ]; then
    echo "[启动] 生产模式 (gunicorn, 端口 58901)"
    # 4 个工作进程，绑定内网回环，由 Nginx 反向代理
    exec gunicorn -w 4 -b 127.0.0.1:58901 app:app
else
    echo "[启动] 开发模式 (flask, 端口 58901)"
    exec python3 app.py
fi
